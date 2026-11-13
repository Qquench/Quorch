# -*- coding: utf-8 -*-
"""Unit tests for Autopilot relay-aware context injector.

Validates Task 26.4:
1. Relay states (PROPOSE, REVIEW, CONFIRM, etc.) suppress obsolete handoff cards and provide positive relay guidance.
2. Halt states (PAUSE_FOR_ACCEPTANCE, BLOCKED, ROADMAP_DONE) provide stopping guidance with > [!IMPORTANT].
3. Active in-progress task takes precedence.
4. Fallback behavior when harness is unavailable.
5. Absolute absence of '/n' syntax bugs and obsolete 'Default Golden Standard' handoff cards.
6. Documentation integrity: dev-tasks-discipline.md unified on > [!IMPORTANT].
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add hooks directory to path for import
hooks_dir = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "hooks")
)
if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)

import context_injector
from context_injector import (
    _HALT_STATES,
    _RELAY_STATES,
    _STOP_HOOK_RELAY_STATES,
    _atomic_write_json,
    _build_reminder,
    _handle_stop_event,
    _is_external_api_available,
    _resolve_harness_baton,
    main,
)


def test_relay_state_suppresses_c3_card():
    """断言接力状态下抑制过时的 C3/交接卡，并输出正向接力指引。"""
    for state in _RELAY_STATES:
        msg = _build_reminder(
            harness_state=state,
            harness_instruction="请继续执行下一环",
            active_task=None,
            active_file_name=None,
            pending_count=1,
            latest_pending_file="2026-10-28_test.md",
        )
        assert msg is not None
        assert "【Quench Autopilot 接力守卫】" in msg
        assert f"动作: {state}" in msg
        assert "严禁中途非预期停机抛出交接卡" in msg
        # 绝不出现旧版的硬编码强制交接卡提示
        assert "双模型交接是默认流程" not in msg
        assert "Default Golden Standard" not in msg
        assert "> [!NOTE]" not in msg
        assert "/n" not in msg


def test_halt_state_emits_important_card():
    """断言停靠/终态下发出规范的停靠提醒，要求使用 > [!IMPORTANT]。"""
    for state in _HALT_STATES:
        msg = _build_reminder(
            harness_state=state,
            harness_instruction="流程已到达终点",
            active_task=None,
            active_file_name=None,
            pending_count=0,
            latest_pending_file=None,
        )
        assert msg is not None
        assert "【Quench Autopilot 停靠提醒】" in msg
        assert "> [!IMPORTANT]" in msg
        assert "/n" not in msg


def test_active_task_precedence():
    """断言当存在执行中任务时，优先下发执行中上下文守卫提醒。"""
    mock_task = MagicMock()
    mock_task.id = "26.4"
    mock_task.title = "测试任务"

    msg = _build_reminder(
        harness_state="REVIEW",
        harness_instruction="...",
        active_task=mock_task,
        active_file_name="task.md",
        pending_count=2,
        latest_pending_file="pending.md",
    )
    assert msg is not None
    assert "【Quench DevTasks 上下文守卫】" in msg
    assert "Task 26.4" in msg
    assert "执行纪律提醒" in msg


def test_fallback_when_harness_unavailable():
    """断言 harness 状态未解析出来时，优雅降级到待确认提醒。"""
    msg = _build_reminder(
        harness_state=None,
        harness_instruction=None,
        active_task=None,
        active_file_name=None,
        pending_count=3,
        latest_pending_file="pending_batch.md",
    )
    assert msg is not None
    assert "【Quench DevTasks 待确认任务提醒】" in msg
    assert "3 项【⬜ 待确认】任务" in msg
    assert "双模型交接是默认流程" not in msg


def test_no_injection_when_clean():
    """断言无任务、无接力时返回 None（输出 {}）。"""
    msg = _build_reminder(
        harness_state=None,
        harness_instruction=None,
        active_task=None,
        active_file_name=None,
        pending_count=0,
        latest_pending_file=None,
    )
    assert msg is None


def test_end_to_end_main_with_relay(tmp_path: Path, monkeypatch):
    """端到端模拟 main() 在接力态下的输出 JSON 结构。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    (agents_dir / "quench_stack.yaml").write_text("project_name: test\ndev_tasks_dir: docs/dev_tasks\n", encoding="utf-8")
    dev_tasks_dir = ws / "docs" / "dev_tasks"
    dev_tasks_dir.mkdir(parents=True)
    task_file = dev_tasks_dir / "test_task.md"
    task_file.write_text("### 任务 1.1 ⬜ 待确认 — 测试\n", encoding="utf-8")

    # Mock _resolve_harness_baton to simulate relay state
    monkeypatch.setattr(
        context_injector,
        "_resolve_harness_baton",
        lambda *args, **kwargs: ("REVIEW", "提交 Reviewer 进行规约推演"),
    )

    stdin_payload = json.dumps({"workspacePaths": [str(ws)]})
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_payload))

    captured_stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured_stdout)

    main()

    output = json.loads(captured_stdout.getvalue())
    assert "injectSteps" in output
    ephemeral = output["injectSteps"][0]["ephemeralMessage"]
    assert "【Quench Autopilot 接力守卫】" in ephemeral
    assert "严禁中途非预期停机抛出交接卡" in ephemeral
    assert "双模型交接是默认流程" not in ephemeral


def test_discipline_doc_unified_on_important():
    """断言 dev-tasks-discipline.md 统一使用 > [!IMPORTANT] 且无旧版 > [!NOTE] 遗留。"""
    rules_file = Path(__file__).resolve().parents[2] / "rules" / "dev-tasks-discipline.md"
    assert rules_file.is_file()

    content = rules_file.read_text(encoding="utf-8")
    assert "> [!NOTE]" not in content
    assert "> [!IMPORTANT]" in content
    assert "Continuous Relay Non-Braking Invariant" in content


def test_handle_stop_event_guardrails_unit(tmp_path: Path, monkeypatch):
    """单元测试直接校验 _handle_stop_event 的六重护栏与单次熔断机制。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    (agents_dir / "quench_stack.yaml").write_text("project_name: test\ndev_tasks_dir: docs/dev_tasks\n", encoding="utf-8")
    dev_tasks_dir = ws / "docs" / "dev_tasks"
    dev_tasks_dir.mkdir(parents=True)
    task_file = dev_tasks_dir / "test_task.md"
    task_file.write_text("### 任务 1.1 ⬜ 待确认 — 测试\n", encoding="utf-8")

    # 1. 缺失 terminationReason -> allow
    assert _handle_stop_event({"workspacePaths": [str(ws)]}) == {"decision": "allow"}

    # 2. terminationReason 非 NO_TOOL_CALL -> allow
    assert _handle_stop_event({
        "terminationReason": "MAX_TOKENS",
        "fullyIdle": True,
        "workspacePaths": [str(ws)],
    }) == {"decision": "allow"}

    # 3. fullyIdle 为 False -> allow
    assert _handle_stop_event({
        "terminationReason": "NO_TOOL_CALL",
        "fullyIdle": False,
        "workspacePaths": [str(ws)],
    }) == {"decision": "allow"}

    # 4. lastUserInput 含 [QUENCH-DISPATCH: -> allow
    assert _handle_stop_event({
        "terminationReason": "NO_TOOL_CALL",
        "fullyIdle": True,
        "lastUserInput": "[QUENCH-DISPATCH: RUNNER] proceed",
        "workspacePaths": [str(ws)],
    }) == {"decision": "allow"}

    # 5. 非 quench 项目 -> allow
    non_quench_ws = tmp_path / "non_quench"
    non_quench_ws.mkdir()
    assert _handle_stop_event({
        "terminationReason": "NO_TOOL_CALL",
        "fullyIdle": True,
        "workspacePaths": [str(non_quench_ws)],
    }) == {"decision": "allow"}

    # 6. 接力态下的首次与第二次单次熔断
    base = {
        "terminationReason": "NO_TOOL_CALL",
        "fullyIdle": True,
        "conversationId": "sess_unit_test",
        "workspacePaths": [str(ws)],
    }
    monkeypatch.setattr(
        context_injector,
        "_resolve_harness_baton",
        lambda *args, **kwargs: ("CHECKOUT", "检出下一任务"),
    )
    res_first = _handle_stop_event(base)
    assert res_first["decision"] == "continue"
    assert "Autopilot relay 'CHECKOUT' active" in res_first["reason"]

    # 第二次必熔断放行
    res_second = _handle_stop_event(base)
    assert res_second == {"decision": "allow"}


def test_main_routing_for_stop_event(tmp_path: Path, monkeypatch):
    """端到端模拟 main() 接收 Stop Hook 时的分流输出。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    (agents_dir / "quench_stack.yaml").write_text("project_name: test\ndev_tasks_dir: docs/dev_tasks\n", encoding="utf-8")
    dev_tasks_dir = ws / "docs" / "dev_tasks"
    dev_tasks_dir.mkdir(parents=True)
    task_file = dev_tasks_dir / "test_task.md"
    task_file.write_text("### 任务 1.1 ⬜ 待确认 — 测试\n", encoding="utf-8")

    monkeypatch.setattr(
        context_injector,
        "_resolve_harness_baton",
        lambda *args, **kwargs: ("CONFIRM", "推进确认"),
    )

    stdin_payload = json.dumps({
        "terminationReason": "NO_TOOL_CALL",
        "fullyIdle": True,
        "conversationId": "sess_main_test",
        "workspacePaths": [str(ws)],
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_payload))

    captured_stdout = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured_stdout)

    main()

    output = json.loads(captured_stdout.getvalue())
    assert output["decision"] == "continue"
    assert "CONFIRM" in output["reason"]


def test_external_api_available_when_configured(tmp_path: Path, monkeypatch):
    """断言当正常配置外部 Reviewer 且 API Key 存在时，_is_external_api_available 返回 True。"""
    ws = tmp_path / "ws_configured"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    stack_yaml = """project_name: test_ext
dev_tasks_dir: docs/dev_tasks
reviewer_engine:
  provider: deepseek
  api_key_env: TEST_REVIEWER_KEY
"""
    (agents_dir / "quench_stack.yaml").write_text(stack_yaml, encoding="utf-8")
    monkeypatch.setenv("TEST_REVIEWER_KEY", "sk-test-secret-12345")

    assert _is_external_api_available(str(ws)) is True


def test_external_api_unavailable_when_provider_none(tmp_path: Path, monkeypatch):
    """断言未配置外部引擎（provider: 'none'）且无 Key 时，_is_external_api_available 返回 False。"""
    ws = tmp_path / "ws_none"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    stack_yaml = """project_name: test_none
dev_tasks_dir: docs/dev_tasks
reviewer_engine:
  provider: none
"""
    (agents_dir / "quench_stack.yaml").write_text(stack_yaml, encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert _is_external_api_available(str(ws)) is False


def test_external_api_unavailable_when_provider_none_despite_env_key(tmp_path: Path, monkeypatch):
    """断言 provider: 'none' 时，即便环境中存在 DEEPSEEK_API_KEY / OPENAI_API_KEY，仍必须返回 False。"""
    ws = tmp_path / "ws_none_env"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    stack_yaml = """project_name: test_none_env
dev_tasks_dir: docs/dev_tasks
reviewer_engine:
  provider: none
"""
    (agents_dir / "quench_stack.yaml").write_text(stack_yaml, encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-accidental-deepseek-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-accidental-openai-key")

    assert _is_external_api_available(str(ws)) is False


def test_external_api_check_does_no_network(tmp_path: Path, monkeypatch):
    """断言 _is_external_api_available 纯本地判定，绝不发起 socket 网络建连。"""
    import socket
    ws = tmp_path / "ws_net"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    stack_yaml = """project_name: test_net
dev_tasks_dir: docs/dev_tasks
reviewer_engine:
  provider: deepseek
  api_key_env: TEST_REVIEWER_KEY
"""
    (agents_dir / "quench_stack.yaml").write_text(stack_yaml, encoding="utf-8")
    monkeypatch.setenv("TEST_REVIEWER_KEY", "sk-valid-key")

    def _forbidden_connect(*args, **kwargs):
        raise AssertionError("Network connection forbidden in hook probe")

    monkeypatch.setattr(socket.socket, "connect", _forbidden_connect)
    res = _is_external_api_available(str(ws))
    assert res is True


def test_atomic_write_json_success(tmp_path: Path):
    """断言 _atomic_write_json 正确原子写入格式化 JSON 且目录无临时文件残留。"""
    target = tmp_path / "sub" / "test.json"
    data = {"history": {"key1": 1, "key2": 2}}
    _atomic_write_json(str(target), data)

    assert target.is_file()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == data

    # 验证目录中只有目标文件，无临时文件残留
    files = list(target.parent.iterdir())
    assert files == [target]


def test_atomic_write_json_cleanup_on_failure(tmp_path: Path, monkeypatch):
    """断言当原子替换失败时，_atomic_write_json 抛出异常并清理临时文件。"""
    target = tmp_path / "fail_sub" / "fail.json"
    data = {"error": True}

    def _mock_replace(src, dst):
        raise OSError("Simulated disk write failure")

    monkeypatch.setattr(os, "replace", _mock_replace)

    with pytest.raises(OSError, match="Simulated disk write failure"):
        _atomic_write_json(str(target), data)

    # 目标文件不应存在
    assert not target.exists()
    # 临时文件必须被清理，目录中无残留文件
    if target.parent.exists():
        assert list(target.parent.iterdir()) == []



