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
    LeaseTouchOutcome,
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
    with pytest.raises(ValueError):
        WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=300.0, heartbeat_interval_s=0)

    with pytest.raises(ValueError):
        WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=300.0, heartbeat_interval_s=-10)

    # 异常场景 2: heartbeat_interval_s >= lease_ttl_s
    with pytest.raises(ValueError):
        WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=100.0, heartbeat_interval_s=100.0)

    with pytest.raises(ValueError):
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
    """验证不同进程/实例间的租约互斥：已被持有时拒绝其他实例接管（基于 TTL 未超时判定）。"""
    guard1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=100.0, heartbeat_interval_s=10.0)
    guard2 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=100.0, heartbeat_interval_s=10.0)

    assert guard1.acquire_or_probe("nonce_guard_1") is True
    assert guard1.is_held() is True

    # 另一个实例使用不同 nonce 尝试抢占，因当前租约未超时（TTL=100s）应被拒绝
    assert guard2.acquire_or_probe("nonce_guard_2") is False
    assert guard2.is_held() is False

    # guard1 释放后，guard2 应该可以正常获取
    guard1.release()
    assert guard2.acquire_or_probe("nonce_guard_2") is True
    assert guard2.is_held() is True
    guard2.release()


def test_dead_peer_takeover(temp_workspace):
    """验证当原租约持有者已超时时，新实例可以安全接管（基于纯 TTL 超时判定）。"""
    guard1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    # 人工构造已超时的租约文件
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
    # TTL 超时，允许接管
    acquired = guard2.acquire_or_probe("new_nonce")
    assert acquired is True
    assert guard2.is_held() is True
    assert guard2.boot_nonce == "new_nonce"
    guard2.release()


def test_is_held_pure_local_flag_independent_of_elapsed_time(temp_workspace):
    """is_held() 语义重写：纯本地持有标志，无 touch 超过 0.8*TTL 仍返回 True，去除心跳时代新鲜度假设。"""
    guard = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=0.5, heartbeat_interval_s=0.1)
    assert not guard.is_held()

    assert guard.acquire_or_probe("nonce_held_test") is True
    assert guard.is_held() is True

    # 经过超过 0.8 * lease_ttl_s (0.4s) 且无 touch
    time.sleep(0.5)

    # 纯本地持有标志依然为 True
    assert guard.is_held() is True

    guard.release()
    assert guard.is_held() is False


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
    # 未持锁调用 touch 返回 LOST
    assert guard.touch() == LeaseTouchOutcome.LOST

    guard.acquire_or_probe("nonce_touch")
    assert guard.touch() == LeaseTouchOutcome.RENEWED

    # 模拟外部强行删除租约文件
    guard.lease_file.unlink()
    assert guard.touch() == LeaseTouchOutcome.LOST
    assert not guard.is_held()


def test_destructive_context_guard(temp_workspace):
    """验证破坏性操作上下文门禁：未持锁时 raise WorkspaceLeaseNotHeldError。"""
    guard = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    with pytest.raises(WorkspaceLeaseNotHeldError):
        with guard.destructive_context():
            pass

    guard.acquire_or_probe("nonce_destruct")
    assert guard.is_held()
    executed = False
    with guard.destructive_context():
        executed = True
    assert executed is True


def test_renew_or_die(temp_workspace):
    """验证 renew_or_die 在失去租约时立即 raise WorkspaceLeaseNotHeldError。"""
    guard = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    with pytest.raises(WorkspaceLeaseNotHeldError):
        guard.renew_or_die()

    guard.acquire_or_probe("nonce_renew")
    guard.renew_or_die()  # 持有时成功

    guard.lease_file.unlink()
    with pytest.raises(WorkspaceLeaseNotHeldError):
        guard.renew_or_die()
