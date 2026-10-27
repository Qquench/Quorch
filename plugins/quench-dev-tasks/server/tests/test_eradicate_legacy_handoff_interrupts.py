"""Unit tests verifying eradication of legacy handoff card interrupts and Autopilot pipeline prompt contract alignment."""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import pytest

server_dir = str(Path(__file__).resolve().parent.parent)
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from reporting import render_handoff_card
from server import (
    dev_tasks_propose,
    dev_tasks_checkout,
    dev_tasks_escalate,
    dev_tasks_export_handoff_card,
)


def test_render_handoff_card_auto_engine():
    """Verify render_handoff_card with auto/engine strategy and reviewer available."""
    card = render_handoff_card(
        task_id="1.1",
        task_file="docs/dev_tasks/test.md",
        reason="Architecture review required",
        strategy="auto",
        reviewer_available=True,
    )
    assert "> [!IMPORTANT]" in card
    assert "### ⏸️ Quench" in card
    assert "dev_reviewer_submit" in card
    assert "Automated Review Guidance" in card
    assert "点击 + 开启新的纯净会话" not in card


def test_render_handoff_card_subagent():
    """Verify render_handoff_card with subagent strategy."""
    card = render_handoff_card(
        task_id="1.1",
        task_file="docs/dev_tasks/test.md",
        reason="Architecture review required",
        strategy="subagent",
        reviewer_available=False,
    )
    assert "> [!IMPORTANT]" in card
    assert "QUENCH-DISPATCH: REVIEWER" in card
    assert "Subagent Review Guidance" in card
    assert "点击 + 开启新的纯净会话" not in card


def test_render_handoff_card_manual_fallback():
    """Verify render_handoff_card fallback to manual cross-session instructions when offline or manual."""
    card = render_handoff_card(
        task_id="1.1",
        task_file="docs/dev_tasks/test.md",
        reason="Architecture review required",
        strategy="manual",
        reviewer_available=False,
    )
    assert "> [!IMPORTANT]" in card
    assert "Low-Token Handoff Steps" in card
    assert "开启**新的纯净会话**" in card
    assert "高阶架构审查模型" in card


@pytest.fixture
def temp_workspace():
    tmp_dir = tempfile.mkdtemp(prefix="quench_test_handoff_")
    agents_dir = os.path.join(tmp_dir, ".agents")
    dev_tasks_dir = os.path.join(tmp_dir, "docs", "dev_tasks")
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(dev_tasks_dir, exist_ok=True)
    with open(os.path.join(agents_dir, "quench_stack.yaml"), "w", encoding="utf-8") as f:
        f.write("project_name: test_quench\ndev_tasks_dir: docs/dev_tasks\n")
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_dev_tasks_checkout_no_interruption(temp_workspace):
    """Verify dev_tasks_checkout does not interrupt with legacy handoff card when pending tasks exist."""
    sample_tasks = [
        {
            "id": "1.1",
            "title": "Pending feature task",
            "affected_files": ["[MODIFY] src/foo.py"],
            "root_cause_and_goal": "Need new feature",
            "type_contracts": "def foo() -> None",
            "steps": ["1. Implement foo"],
            "defensive_checks": ["- Bounds check"],
            "dod_commands": ["pytest"],
        }
    ]
    prop = dev_tasks_propose(
        workspace_root=temp_workspace,
        task_file_name="2026-10-28_test_checkout.md",
        tasks=sample_tasks,
    )
    assert prop.get("created") is True or prop.get("count", 0) > 0 or prop.get("created_count", 0) > 0

    # Calling checkout with no confirmed tasks
    res = dev_tasks_checkout(workspace_root=temp_workspace)
    assert res.get("has_pending_tasks") is True
    assert res.get("batch_finished") is True
    assert "instruction" in res
    instruction = res["instruction"]

    # Assert legacy brake instructions are eradicated
    assert "请输出【Quench 任务交接卡】" not in instruction
    assert "在新会话切换至自选的高阶架构审查模型" not in instruction
    assert "开新会话" not in instruction

    # Assert positive automation alignment
    assert "harness_next_action" in instruction or "dev_reviewer_submit" in instruction or "dev_tasks_confirm" in instruction

    # Assert backward-compatible schema fields are maintained
    assert "reviewer_handoff" in res
    assert "handoff_card" in res
    assert "batch_finished" in res


def test_dev_tasks_escalate_instruction(temp_workspace):
    """Verify dev_tasks_escalate provides modern in-band reviewer guidance instead of halting."""
    sample_tasks = [
        {
            "id": "2.1",
            "title": "Escalation target task",
            "affected_files": ["[MODIFY] src/bar.py"],
            "root_cause_and_goal": "Complex architectural challenge",
            "type_contracts": "def bar() -> None",
            "steps": ["1. Refactor bar"],
            "defensive_checks": ["- Concurrency guard"],
            "dod_commands": ["pytest"],
        }
    ]
    dev_tasks_propose(
        workspace_root=temp_workspace,
        task_file_name="2026-10-28_test_escalate.md",
        tasks=sample_tasks,
    )

    res = dev_tasks_escalate(
        workspace_root=temp_workspace,
        task_file="2026-10-28_test_escalate.md",
        task_id="2.1",
        reason="Hit complex deadlock between locks",
    )

    assert res.get("status") == "escalated"
    instruction = res.get("instruction", "")
    assert "向用户输出【Quench 任务交接卡】，等待用户在新会话中" not in instruction
    assert "dev_reviewer_submit" in instruction or "reviewer subagent" in instruction
    assert "handoff_card" in res
    assert "prompt_hint" in res


def test_dev_tasks_export_handoff_card(temp_workspace):
    """Verify dev_tasks_export_handoff_card returns valid structured card."""
    sample_tasks = [
        {
            "id": "3.1",
            "title": "Export target task",
            "affected_files": ["[MODIFY] src/baz.py"],
            "root_cause_and_goal": "Needs export review",
            "type_contracts": "def baz() -> None",
            "steps": ["1. Do baz"],
            "defensive_checks": ["- None"],
            "dod_commands": ["pytest"],
        }
    ]
    dev_tasks_propose(
        workspace_root=temp_workspace,
        task_file_name="2026-10-28_test_export.md",
        tasks=sample_tasks,
    )

    res = dev_tasks_export_handoff_card(
        workspace_root=temp_workspace,
        task_id="3.1",
        include_context=True,
    )
    assert res.get("status") == "exported"
    assert "handoff_card" in res
    assert "> [!IMPORTANT]" in res["handoff_card"]


def test_anti_interruption_grep_guard():
    """Verify obsolete interrupt strings are absent from server.py."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "server.py")
    with open(server_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "请输出【Quench 任务交接卡】" not in content
    assert "引导用户在新会话切换至自选的高阶架构审查模型" not in content
    assert "向用户输出【Quench 任务交接卡】，等待用户在新会话中" not in content
