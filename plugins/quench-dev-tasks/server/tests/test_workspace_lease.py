# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure server module is in sys.path
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from workspace_lease import (
    WorkspaceLeaseGuard,
    WorkspaceLeaseNotHeldError,
    PeerLiveness,
    LeaseHeartbeatThread,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory(prefix="quench_lease_test_") as tmpdir:
        yield Path(tmpdir)


def test_initialization_invariants(temp_workspace):
    """验证初始化不变量：0 < heartbeat_interval_s < lease_ttl_s。"""
    # 正常初始化
    guard = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=300.0, heartbeat_interval_s=30.0)
    assert not guard.is_held()

    # 异常场景 1: heartbeat_interval_s <= 0
    with pytest.raises(AssertionError):
        WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=300.0, heartbeat_interval_s=0)

    with pytest.raises(AssertionError):
        WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=300.0, heartbeat_interval_s=-10)

    # 异常场景 2: heartbeat_interval_s >= lease_ttl_s
    with pytest.raises(AssertionError):
        WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=100.0, heartbeat_interval_s=100.0)

    with pytest.raises(AssertionError):
        WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=50.0, heartbeat_interval_s=80.0)


def test_acquire_and_release_lifecycle(temp_workspace):
    """验证租约获取、状态检查与正常释放生命周期。"""
    guard = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    assert not guard.is_held()

    acquired = guard.acquire_or_probe("nonce_test_1")
    assert acquired is True
    assert guard.is_held() is True
    assert guard.boot_nonce == "nonce_test_1"
    assert guard.lease_file.is_file()

    with open(guard.lease_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["pid"] == os.getpid()
    assert data["boot_nonce"] == "nonce_test_1"

    # 同一 guard 重复 acquire 同一 nonce 应直接成功
    assert guard.acquire_or_probe("nonce_test_1") is True

    guard.release()
    assert guard.is_held() is False
    assert guard.boot_nonce is None
    assert not guard.lease_file.exists()


def test_mutual_exclusion_and_preemption(temp_workspace):
    """验证不同进程/实例间的租约互斥：已被持有时拒绝其他实例接管。"""
    guard1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=100.0, heartbeat_interval_s=10.0)
    guard2 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=100.0, heartbeat_interval_s=10.0)

    assert guard1.acquire_or_probe("nonce_guard_1") is True
    assert guard1.is_held() is True

    # 另一个实例使用不同 nonce 尝试抢占，因当前持有者存活应被拒绝
    # mock probe_peer 为存活
    with patch.object(WorkspaceLeaseGuard, "probe_peer") as mock_probe:
        mock_probe.return_value = PeerLiveness(
            is_alive=True,
            pid=os.getpid(),
            boot_nonce="nonce_guard_1",
            takeover_allowed=False,
        )
        assert guard2.acquire_or_probe("nonce_guard_2") is False
        assert guard2.is_held() is False

    # guard1 释放后，guard2 应该可以正常获取
    guard1.release()
    assert guard2.acquire_or_probe("nonce_guard_2") is True
    assert guard2.is_held() is True
    guard2.release()


def test_dead_peer_takeover(temp_workspace):
    """验证当原租约持有者已死亡时，新实例可以安全接管。"""
    guard1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    # 人工构造已死亡进程的租约文件
    guard1._lease_dir.mkdir(parents=True, exist_ok=True)
    dead_pid = 99999999  # 绝大多数系统上不存在的 PID
    data = {
        "pid": dead_pid,
        "boot_nonce": "dead_nonce",
        "acquired_at": time.time() - 100,
        "updated_at": time.time() - 100,
        "lease_ttl_s": 10.0,
        "heartbeat_interval_s": 1.0,
    }
    with open(guard1.lease_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    guard2 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    # probe_peer 发现 dead_pid 死亡，允许接管
    with patch.object(WorkspaceLeaseGuard, "probe_peer") as mock_probe:
        mock_probe.return_value = PeerLiveness(
            is_alive=False,
            pid=dead_pid,
            boot_nonce="dead_nonce",
            takeover_allowed=True,
        )
        acquired = guard2.acquire_or_probe("new_nonce")
        assert acquired is True
        assert guard2.is_held() is True
        assert guard2.boot_nonce == "new_nonce"

    guard2.release()


def test_posix_eperm_liveness(temp_workspace):
    """EPERM 存活断言：模拟 os.kill 抛出 PermissionError 时，断言返回 is_alive=True, takeover_allowed=False。"""
    with patch("sys.platform", "linux"):
        with patch("os.kill", side_effect=PermissionError("Operation not permitted")):
            res = WorkspaceLeaseGuard.probe_peer(1234, "nonce_posix", temp_workspace)
            assert res.is_alive is True
            assert res.takeover_allowed is False
            assert res.pid == 1234


def test_posix_process_lookup_error(temp_workspace):
    """POSIX 下进程不存在抛出 ProcessLookupError 时断言返回 is_alive=False, takeover_allowed=True。"""
    with patch("sys.platform", "linux"):
        with patch("os.kill", side_effect=ProcessLookupError):
            res = WorkspaceLeaseGuard.probe_peer(99999, "nonce_posix", temp_workspace)
            assert res.is_alive is False
            assert res.takeover_allowed is True


def test_pid_reuse_conservative_rejection(temp_workspace):
    """PID 复用保守拒绝：当 PID 物理存在但盘上记录的 boot_nonce 与探测目标不一致时，断言 takeover_allowed=False。"""
    # 模拟盘上租约文件记录了不同的 boot_nonce
    lease_dir = temp_workspace / ".agents" / "logs" / "reviewer"
    lease_dir.mkdir(parents=True, exist_ok=True)
    lease_file = lease_dir / "workspace.lease.json"
    with open(lease_file, "w", encoding="utf-8") as f:
        json.dump({"pid": 54321, "boot_nonce": "current_disk_nonce"}, f)

    # 探测存活进程 54321，但探测传入的是异代 target_nonce="ancient_probed_nonce"
    with patch.object(WorkspaceLeaseGuard, "_probe_posix", wraps=WorkspaceLeaseGuard._probe_posix):
        with patch("sys.platform", "linux"):
            with patch("os.kill", return_value=None):  # os.kill 成功表示物理存活
                res = WorkspaceLeaseGuard.probe_peer(54321, "ancient_probed_nonce", temp_workspace)
                assert res.is_alive is True
                assert res.takeover_allowed is False


def test_windows_api_exit_code_scenarios(temp_workspace):
    """Windows 真实退出码断言：验证 STILL_ACTIVE 与 非 STILL_ACTIVE 的判定。"""
    STILL_ACTIVE = 259
    EXITED_CODE = 0

    mock_kernel32 = MagicMock()

    # 场景 1: STILL_ACTIVE (正在运行)
    mock_kernel32.OpenProcess.return_value = 100
    mock_kernel32.GetExitCodeProcess.side_effect = lambda handle, byref_val: setattr(byref_val._obj, "value", STILL_ACTIVE) or 1

    with patch("sys.platform", "win32"):
        with patch("ctypes.windll", MagicMock(kernel32=mock_kernel32)):
            res = WorkspaceLeaseGuard.probe_peer(12345, "nonce_win", temp_workspace)
            assert res.is_alive is True
            assert res.takeover_allowed is False

    # 场景 2: 进程已退出 (ExitCode = 0)
    mock_kernel32.OpenProcess.return_value = 100
    mock_kernel32.GetExitCodeProcess.side_effect = lambda handle, byref_val: setattr(byref_val._obj, "value", EXITED_CODE) or 1

    with patch("sys.platform", "win32"):
        with patch("ctypes.windll", MagicMock(kernel32=mock_kernel32)):
            res = WorkspaceLeaseGuard.probe_peer(12345, "nonce_win", temp_workspace)
            assert res.is_alive is False
            assert res.takeover_allowed is True

    # 场景 3: OpenProcess 失败且 GetLastError == ERROR_ACCESS_DENIED (5)
    mock_kernel32.OpenProcess.return_value = 0
    mock_kernel32.GetLastError.return_value = 5

    with patch("sys.platform", "win32"):
        with patch("ctypes.windll", MagicMock(kernel32=mock_kernel32)):
            res = WorkspaceLeaseGuard.probe_peer(12345, "nonce_win", temp_workspace)
            assert res.is_alive is True
            assert res.takeover_allowed is False


def test_heartbeat_thread_updates_timestamp(temp_workspace):
    """独立线程保活防骤停：在主线程执行 time.sleep 模拟重任务阻塞，断言后台心跳线程能正常更新租约文件时间戳。"""
    guard = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=0.2)
    assert guard.acquire_or_probe("nonce_heartbeat") is True

    with open(guard.lease_file, "r", encoding="utf-8") as f:
        initial_ts = json.load(f)["updated_at"]

    guard.start_heartbeat_thread()
    try:
        # 阻塞主线程 0.8s
        time.sleep(0.8)

        with open(guard.lease_file, "r", encoding="utf-8") as f:
            updated_ts = json.load(f)["updated_at"]

        # 验证心跳线程在后台更新了时间戳
        assert updated_ts > initial_ts, f"Expected {updated_ts} > {initial_ts}"
    finally:
        guard.stop_heartbeat_thread()
        guard.release()


def test_release_idempotency(temp_workspace):
    """release 幂等性：对未持锁、二次 release、外部 unlink 租约文件的实例调用 release()，断言无任何异常。"""
    guard = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)

    # 1. 未持有锁直接 release
    guard.release()
    assert not guard.is_held()

    # 2. 正常获取后二次 release
    guard.acquire_or_probe("nonce_idem")
    assert guard.is_held()
    guard.release()
    assert not guard.is_held()
    guard.release()  # 二次调用
    assert not guard.is_held()

    # 3. 外部提前 unlink 租约文件后再 release
    guard.acquire_or_probe("nonce_idem_3")
    assert guard.lease_file.is_file()
    guard.lease_file.unlink()  # 外部强行删除
    guard.release()  # 依然安全无异常
    assert not guard.is_held()


def test_touch_failures(temp_workspace):
    """touch 在租约被外部盗取或删除时的自愈防守。"""
    guard = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    # 未持锁调用 touch 返回 False
    assert guard.touch() is False

    guard.acquire_or_probe("nonce_touch")
    assert guard.touch() is True

    # 模拟外部强行删除租约文件
    guard.lease_file.unlink()
    assert guard.touch() is False
    assert not guard.is_held()
