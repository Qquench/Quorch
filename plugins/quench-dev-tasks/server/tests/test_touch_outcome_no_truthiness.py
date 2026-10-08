# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import ast
from enum import Enum
import os
from pathlib import Path
import sys
import tempfile

import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from workspace_lease import (
    WorkspaceLeaseGuard,
    LeaseTouchOutcome,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory(prefix="quench_truthiness_test_") as tmpdir:
        yield Path(tmpdir)


def test_touch_outcome_enum_contract():
    """验证 LeaseTouchOutcome 严格派生自 Enum，且拥有预期常量。"""
    assert issubclass(LeaseTouchOutcome, Enum)
    assert LeaseTouchOutcome.RENEWED.value == "renewed"
    assert LeaseTouchOutcome.LOST.value == "lost"
    assert LeaseTouchOutcome.CONTENTION.value == "contention"

    # 关键红线验证：LOST 在布尔真值判定下为 True，因此调用点严禁使用 if not touch() 隐式真值！
    assert bool(LeaseTouchOutcome.LOST) is True


def test_touch_returns_lost_when_lease_file_deleted(temp_workspace):
    """验证租约文件被外部删除时，touch() 确凿返回 LOST。"""
    guard = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=1.0)
    guard.acquire_or_probe("nonce_truth")

    # 外部删除租约，使下一次 touch 确凿返回 LOST
    guard.lease_file.unlink()

    outcome = guard.touch()
    assert outcome == LeaseTouchOutcome.LOST
    assert guard.is_held() is False


def test_crlf_touch_outcome_truthiness_detection(tmp_path: Path):
    """追加 CRLF 规范化负向断言：验证包含 \\r\\n 换行符的隐式真值判定代码仍能被精确检测。"""
    crlf_source = (
        "if not guard.touch():\r\n"
        "    print('lost')\r\n"
    )
    test_file = tmp_path / "crlf_truthiness.py"
    test_file.write_bytes(crlf_source.encode("utf-8"))

    tree = ast.parse(test_file.read_bytes(), filename=str(test_file))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not):
            op = node.test.operand
            if isinstance(op, ast.Call) and isinstance(op.func, ast.Attribute) and op.func.attr == "touch":
                found = True
    assert found is True
