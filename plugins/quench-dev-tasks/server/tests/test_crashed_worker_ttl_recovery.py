# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from workspace_lease import (
    WorkspaceLeaseGuard,
    WorkspaceLeaseNotHeldError,
    LeaseGenerationLostError,
    LeaseTouchOutcome,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory(prefix="quench_crashed_worker_test_") as tmpdir:
        yield Path(tmpdir)


def test_crashed_worker_lease_expired_can_be_taken_over(temp_workspace):
    """① 崩溃进程租约超时后新进程可接管。"""
    worker1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=2.0, heartbeat_interval_s=0.5)
    assert worker1.acquire_or_probe("nonce_crashed_1") is True
    assert worker1.generation == 1

    # 模拟 worker1 崩溃挂死，不再刷新租约时间戳
    with open(worker1.lease_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["updated_at"] = time.time() - 20.0  # 远超 lease_ttl_s * take_over_stale_multiplier (2.0 * 3.0 = 6.0s)
    with open(worker1.lease_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    worker2 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=2.0, heartbeat_interval_s=0.5)
    assert worker2.acquire_or_probe("nonce_new_2") is True
    assert worker2.is_held() is True
    assert worker2.generation == 2
    assert worker2.boot_nonce == "nonce_new_2"


def test_unexpired_lease_takeover_rejected(temp_workspace):
    """② 未超时租约被拒绝。"""
    worker1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    assert worker1.acquire_or_probe("nonce_active") is True

    # 租约更新时间戳保持新鲜
    with open(worker1.lease_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["updated_at"] = time.time() - 2.0  # 远小于 10.0 * 3.0 = 30.0s
    with open(worker1.lease_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    worker2 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    assert worker2.acquire_or_probe("nonce_rejected") is False
    assert worker2.is_held() is False


def test_zombie_worker_expired_generation_touch_rejected_lost(temp_workspace):
    """③ 僵尸进程过期 generation 写被 touch() CAS 拒绝（LOST）。"""
    worker1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=2.0, heartbeat_interval_s=0.5)
    assert worker1.acquire_or_probe("nonce_zombie_1") is True
    assert worker1.generation == 1

    # 模拟外部租约被新 worker 接管，generation 递增为 2
    with open(worker1.lease_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["generation"] = 2
    data["boot_nonce"] = "nonce_new_taker"
    data["pid"] = 88888
    with open(worker1.lease_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    # 僵尸 worker1 尝试 touch() 续约，触发代际或 boot_nonce 失配
    outcome = worker1.touch()
    assert outcome == LeaseTouchOutcome.LOST
    assert worker1.is_held() is False

    with pytest.raises(WorkspaceLeaseNotHeldError):
        worker1.renew_or_die()


def test_takeover_generation_strictly_monotonic_increment(temp_workspace):
    """④ 接管后 generation 严格递增。"""
    worker1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=2.0, heartbeat_interval_s=0.5)
    assert worker1.acquire_or_probe("nonce_1") is True
    assert worker1.generation == 1

    # 第一次接管
    with open(worker1.lease_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["updated_at"] = time.time() - 10.0
    with open(worker1.lease_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    worker2 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=2.0, heartbeat_interval_s=0.5)
    assert worker2.acquire_or_probe("nonce_2") is True
    assert worker2.generation == 2

    # 第二次接管
    with open(worker2.lease_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["updated_at"] = time.time() - 10.0
    with open(worker2.lease_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    worker3 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=2.0, heartbeat_interval_s=0.5)
    assert worker3.acquire_or_probe("nonce_3") is True
    assert worker3.generation == 3

    assert worker1.generation < worker2.generation < worker3.generation


def test_wall_clock_jump_forward_premature_takeover_recorded_behavior(temp_workspace):
    """⑤ wall-clock 前跳导致提前夺权的显式记录用例（当前不加防护，断言仅记录当前已知行为）。
    
    单机 A1 公理下，若系统时钟骤然向前跳变超过 lease_ttl_s * take_over_stale_multiplier，
    新进程会视既有租约为 stale 并提前接管。此为文档化已知局限（fail-safe fail-closed 仅防回拨，不防前跳）。
    """
    base_time = 1700000000.0
    with patch("time.time", return_value=base_time):
        worker1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=100.0, heartbeat_interval_s=10.0)
        assert worker1.acquire_or_probe("nonce_clock_1") is True
        assert worker1.generation == 1

    # 模拟系统时钟前跳 400 秒 (400 > 100 * 3.0)
    jumped_time = base_time + 400.0
    with patch("time.time", return_value=jumped_time):
        worker2 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=100.0, heartbeat_interval_s=10.0)
        # 断言记录当前行为：时钟前跳导致 is_stale 判定成立，提前接管成功
        premature_acquired = worker2.acquire_or_probe("nonce_clock_2")
        assert premature_acquired is True
        assert worker2.generation == 2
