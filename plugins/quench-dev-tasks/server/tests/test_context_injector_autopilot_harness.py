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
    _build_reminder,
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
