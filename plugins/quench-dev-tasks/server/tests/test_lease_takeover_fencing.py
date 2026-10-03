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
    with tempfile.TemporaryDirectory(prefix="quench_fencing_test_") as tmpdir:
        yield Path(tmpdir)


def test_generation_increments_on_takeover(temp_workspace):
    """验证夺权时 generation 严格单调自增。"""
    guard1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=2.0, heartbeat_interval_s=0.5)
    assert guard1.acquire_or_probe("nonce_g1") is True
    assert guard1.generation == 1

    # 外部写入超时时间戳（模拟原持有者挂死且租约超时）
    with open(guard1.lease_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["updated_at"] = time.time() - 100.0  # 远超 2.0 * 3.0
    with open(guard1.lease_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    guard2 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=2.0, heartbeat_interval_s=0.5)
    assert guard2.acquire_or_probe("nonce_g2") is True
    assert guard2.generation == 2

    # guard1 此时调用 touch 必然遭遇代际失配返回 LOST
    outcome = guard1.touch()
    assert outcome == LeaseTouchOutcome.LOST
    assert not guard1.is_held()


def test_unexpired_lease_takeover_rejection(temp_workspace):
    """验证租约未超时时，严格拒绝其他实例接管。"""
    guard1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    assert guard1.acquire_or_probe("nonce_live") is True

    # 模拟更新时间戳仍然新鲜（未超时）
    with open(guard1.lease_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["updated_at"] = time.time() - 2.0  # 远小于 10.0 * 3.0
    with open(guard1.lease_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    guard2 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    assert guard2.acquire_or_probe("nonce_taker") is False
    assert not guard2.is_held()


def test_fencing_prevents_stale_writer_operations(temp_workspace):
    """验证被夺权的原持有者执行 renew_or_die 时立即抛出 WorkspaceLeaseNotHeldError。"""
    guard1 = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=2.0, heartbeat_interval_s=0.5)
    guard1.acquire_or_probe("nonce_old")
    assert guard1.generation == 1

    # 外部直接将 lease_file 的 generation 改为 2（模拟已发生夺权）
    with open(guard1.lease_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["generation"] = 2
    data["boot_nonce"] = "nonce_new"
    with open(guard1.lease_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    assert guard1.touch() == LeaseTouchOutcome.LOST
    with pytest.raises(WorkspaceLeaseNotHeldError):
        guard1.renew_or_die()
