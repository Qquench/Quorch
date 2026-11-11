"""test_tool_response_slim.py - Comprehensive Verification for Task 33.3.

Covers:
- E1: Closed-vocabulary reconciliation: reason_code ∈ CHECKOUT_REASON_CODES.
- E2: Echo stripping & SHA256 equivalence: refine_spec content_sha256 vs disk content.
- E3: Full surface response budget regression across all 16 MCP tools (with terminal poll exemption).
- E3 Overload: 40-task overload & long handoff card clamping within declared budgets.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from fixtures.response_payloads import (
    OVERLOAD_STATUS_PAYLOAD,
    TYPICAL_PAYLOADS,
)
from response_compactor import fit_to_budget, measure_payload_bytes
from server import (
    dev_tasks_checkout,
    dev_tasks_complete,
    dev_tasks_confirm,
    dev_tasks_export_handoff_card,
    dev_tasks_propose,
    dev_tasks_refine_spec,
)
from tool_surface_constants import (
    CHECKOUT_REASON_CODES,
    EXPECTED_TOOL_NAMES,
    RESPONSE_BUDGET_BYTES,
)


@pytest.fixture
def slim_workspace(tmp_path):
    """Create a temporary initialized workspace for checkout and refine testing."""
    ws = tmp_path / "slim_ws"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    tasks_dir = ws / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True)
    src_dir = ws / "src"
    src_dir.mkdir()

    config_data = {
        "schema_version": "1.0",
        "project_name": "SlimTestProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "reviewer_engine": {
            "mode": "manual",
            "provider": "none",
        },
    }
    with open(agents_dir / "quench_stack.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    (src_dir / "core.py").write_text("def core_fn() -> bool:\n    return True\n", encoding="utf-8")
    return str(ws)


def test_checkout_reason_codes_closed_vocabulary_e1(slim_workspace):
    """E1: Assert checkout reason_code is strictly within CHECKOUT_REASON_CODES."""
    ws = slim_workspace

    assert CHECKOUT_REASON_CODES == frozenset({
        "REWORK_REQUIRED",
        "PENDING_REVIEW",
        "NO_CONFIRMED_TASKS",
    })

    # Sub-case A: File with rework task
    dev_tasks_propose(
        workspace_root=ws,
        task_file_name="rework.md",
        tasks=[{
            "id": "1.1",
            "title": "Rework Task",
            "affected_files": ["[MODIFY] src/core.py"],
            "root_cause_and_goal": "Need fix",
            "type_contracts": "def core_fn() -> bool",
            "steps": ["1. Fix"],
            "defensive_checks": ["- check"],
            "dod_commands": ["pytest"],
        }],
    )
    dev_tasks_confirm(workspace_root=ws, task_file="rework.md", task_ids=["1.1"], action="rework")
    res_rework = dev_tasks_checkout(workspace_root=ws, task_file="rework.md")
    assert res_rework.get("reason_code") == "REWORK_REQUIRED"
    assert res_rework["reason_code"] in CHECKOUT_REASON_CODES
    assert measure_payload_bytes(res_rework) <= RESPONSE_BUDGET_BYTES["dev_tasks_checkout"]

    # Sub-case B: File with pending review task
    dev_tasks_propose(
        workspace_root=ws,
        task_file_name="pending.md",
        tasks=[{
            "id": "2.1",
            "title": "Pending Task",
            "affected_files": ["[MODIFY] src/core.py"],
            "root_cause_and_goal": "Need review",
            "type_contracts": "def core_fn() -> bool",
            "steps": ["1. Review"],
            "defensive_checks": ["- check"],
            "dod_commands": ["pytest"],
        }],
    )
    res_pending = dev_tasks_checkout(workspace_root=ws, task_file="pending.md")
    assert res_pending.get("reason_code") == "PENDING_REVIEW"
    assert res_pending["reason_code"] in CHECKOUT_REASON_CODES
    assert measure_payload_bytes(res_pending) <= RESPONSE_BUDGET_BYTES["dev_tasks_checkout"]

    # Sub-case C: File with all completed tasks
    dev_tasks_propose(
        workspace_root=ws,
        task_file_name="done.md",
        tasks=[{
            "id": "3.1",
            "title": "Done Task",
            "affected_files": ["[MODIFY] src/core.py"],
            "root_cause_and_goal": "Already done",
            "type_contracts": "def core_fn() -> bool",
            "steps": ["1. Done"],
            "defensive_checks": ["- check"],
            "dod_commands": ["pytest"],
        }],
    )
    dev_tasks_confirm(workspace_root=ws, task_file="done.md", task_ids=["3.1"], action="confirm")
    chk = dev_tasks_checkout(workspace_root=ws, task_file="done.md")
    dev_tasks_complete(
        workspace_root=ws,
        task_file="done.md",
        task_id="3.1",
        dod_output="All tests passed",
        holder_token=chk.get("holder_token"),
        generation=chk.get("generation"),
    )
    res_done = dev_tasks_checkout(workspace_root=ws, task_file="done.md")
    assert res_done.get("reason_code") == "NO_CONFIRMED_TASKS"
    assert res_done["reason_code"] in CHECKOUT_REASON_CODES
    assert measure_payload_bytes(res_done) <= RESPONSE_BUDGET_BYTES["dev_tasks_checkout"]


@pytest.mark.anyio
async def test_refine_spec_echo_stripped_and_sha256_equivalence_e2(slim_workspace):
    """E2: Assert refine_spec strips markdown echo and matches disk sha256."""
    ws = slim_workspace
    tasks_dir = Path(ws) / "docs" / "dev_tasks"

    dev_tasks_propose(
        workspace_root=ws,
        task_file_name="spec_test.md",
        tasks=[{
            "id": "1.1",
            "title": "Initial Spec",
            "affected_files": ["[MODIFY] src/core.py"],
            "root_cause_and_goal": "Need refine",
            "type_contracts": "def core_fn() -> bool",
            "steps": ["1. Step"],
            "defensive_checks": ["- check"],
            "dod_commands": ["pytest"],
        }],
    )

    draft = {
        "id": "1.1",
        "title": "Refine Target Spec",
        "affected_files": ["[MODIFY] src/core.py"],
        "root_cause_and_goal": "Add thread-safe lock to core_fn to prevent race conditions",
        "type_contracts": "def core_fn() -> bool",
        "steps": ["1. Wrap core_fn in threading lock"],
        "defensive_checks": ["- Concurrency race check"],
        "dod_commands": ["pytest"],
    }

    # Offline/fallback branch test
    res = await dev_tasks_refine_spec(
        workspace_root=ws,
        draft_task=draft,
        context_files=["src/core.py"],
        persist=True,
        task_file="spec_test.md",
    )

    assert res["ok"] is True
    assert res["task_id"] == "1.1"
    assert "content_sha256" in res
    assert "bytes_written" in res
    assert res["bytes_written"] > 0
    assert "refined_spec" not in res
    assert "exploration" not in res
    assert "degraded_card" not in res
    # Ensure raw markdown body does not leak into response
    assert "【涉及文件】" not in json.dumps(res, ensure_ascii=False)
    assert measure_payload_bytes(res) <= RESPONSE_BUDGET_BYTES["dev_tasks_refine_spec"]

    # Verify sha256 equivalence with persisted file content
    persisted_bytes = (tasks_dir / "spec_test.md").read_bytes()
    expected_sha256 = hashlib.sha256(persisted_bytes).hexdigest()
    assert res["content_sha256"] == expected_sha256
    assert res["bytes_written"] == len(persisted_bytes)


def test_all_16_tools_response_budget_regression_e3():
    """E3: Verify all 16 tools fit within declared RESPONSE_BUDGET_BYTES."""
    assert len(EXPECTED_TOOL_NAMES) == 16
    assert set(TYPICAL_PAYLOADS.keys()) == set(EXPECTED_TOOL_NAMES)

    for tool_name in sorted(EXPECTED_TOOL_NAMES):
        raw_payload = TYPICAL_PAYLOADS[tool_name]
        clamped = fit_to_budget(tool_name, raw_payload)
        measured_bytes = measure_payload_bytes(clamped)
        budget = RESPONSE_BUDGET_BYTES[tool_name]
        assert measured_bytes <= budget, (
            f"Tool '{tool_name}' clamped payload size {measured_bytes}B exceeds budget {budget}B"
        )


def test_overload_payloads_clamping_e3():
    """E3 Overload: Assert 40-task status and long handoff card clamp safely within budget."""
    # 1. 40-task status overload
    clamped_status = fit_to_budget("dev_tasks_status", OVERLOAD_STATUS_PAYLOAD)
    assert measure_payload_bytes(clamped_status) <= RESPONSE_BUDGET_BYTES["dev_tasks_status"]
    assert "truncated_sections" in clamped_status

    # 2. Long handoff card overload (5000B text)
    long_card_payload = {
        "status": "exported",
        "task_id": "1.1",
        "task_file": "docs/dev_tasks/test.md",
        "title": "Long Card Test",
        "task_status": "⬜ 待确认",
        "handoff_card": "# Long Card Content\n" + ("x" * 5000),
        "include_context": True,
    }
    clamped_card = fit_to_budget("dev_tasks_export_handoff_card", long_card_payload)
    assert measure_payload_bytes(clamped_card) <= RESPONSE_BUDGET_BYTES["dev_tasks_export_handoff_card"]


def test_reviewer_poll_terminal_phase_budget_exemption():
    """Verify dev_reviewer_poll in terminal phase is exempt from non-terminal 1024B budget."""
    large_terminal_poll = {
        "job_id": "job_123456",
        "session_id": "sess1",
        "state": "COMPLETED",
        "review_report": "Detailed architectural analysis report\n" + ("Analysis..." * 200),
    }
    # Non-terminal phase enforces 1024B
    clamped_nonterminal = fit_to_budget("dev_reviewer_poll", large_terminal_poll, phase="default")
    assert measure_payload_bytes(clamped_nonterminal) <= RESPONSE_BUDGET_BYTES["dev_reviewer_poll"]

    # Terminal phase is exempt
    clamped_terminal = fit_to_budget("dev_reviewer_poll", large_terminal_poll, phase="terminal")
    assert clamped_terminal == large_terminal_poll
