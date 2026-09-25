# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import ast
import os
import sys
import tempfile
from pathlib import Path

import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from enum import Enum

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


def test_heartbeat_thread_exits_on_lost(temp_workspace):
    """验证心跳守护线程在 touch() 返回 LOST 时能够确定性退出，而不是死循环。"""
    guard = WorkspaceLeaseGuard(temp_workspace, lease_ttl_s=10.0, heartbeat_interval_s=0.1)
    guard.acquire_or_probe("nonce_truth")
    guard.start_heartbeat_thread()

    assert guard._heartbeat_thread is not None
    assert guard._heartbeat_thread.is_alive()

    # 外部删除租约，使下一次 touch 确凿返回 LOST
    guard.lease_file.unlink()

    # 等待心跳线程感知并主动退出
    guard._heartbeat_thread.join(timeout=1.5)
    assert not guard._heartbeat_thread.is_alive()
    guard.release()


def test_no_implicit_truthiness_on_touch_in_server_ast():
    """静态 AST 扫描门禁：确保服务端生产代码中绝不存在对 touch() 进行布尔隐式判定的模式。
    禁止出现：
      - if not <expr>.touch():
      - if <expr>.touch():
    必须显式比对：
      - if <expr>.touch() == LeaseTouchOutcome.LOST:
    """
    server_path = Path(SERVER_DIR)
    py_files = list(server_path.glob("*.py"))
    assert len(py_files) > 0

    violations = []

    for py_file in py_files:
        with open(py_file, "r", encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read(), filename=str(py_file))
            except SyntaxError:
                continue

        for node in ast.walk(tree):
            # 扫描 if <test>:
            if isinstance(node, ast.If):
                test = node.test
                # 检查直接调用: if <x>.touch():
                if isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute) and test.func.attr == "touch":
                    violations.append(f"{py_file.name}:{node.lineno} -> if {test.func.attr}() (隐式真值判定)")
                # 检查一元非: if not <x>.touch():
                elif isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                    operand = test.operand
                    if isinstance(operand, ast.Call) and isinstance(operand.func, ast.Attribute) and operand.func.attr == "touch":
                        violations.append(f"{py_file.name}:{node.lineno} -> if not {operand.func.attr}() (隐式真值判定)")

    assert not violations, f"发现违规的 touch() 隐式真值判定：\n" + "\n".join(violations)
