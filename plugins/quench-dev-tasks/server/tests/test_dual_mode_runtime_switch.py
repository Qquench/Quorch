"""Tests for dual-mode runtime persistence, hot switching, CAS re-arm, and backward compatibility."""

import os
import json
import time
import subprocess
from filelock import FileLock
import pytest

from runtime_mode import (
    load_runtime_mode,
    update_runtime_mode,
    get_runtime_mode_path,
    get_runtime_mode_lock_path,
    generate_session_role_contract,
    AutopilotRuntimeState,
    EffectiveModeSnapshot,
)
from server import dev_tasks_status


def _init_mock_workspace(tmp_path) -> str:
    ws = str(tmp_path)
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    dev_tasks_dir = tmp_path / "docs" / "dev_tasks"
    dev_tasks_dir.mkdir(parents=True, exist_ok=True)
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text(
        "project_name: test-dual-mode\ndev_tasks_dir: docs/dev_tasks\naudit_gate:\n  enabled: false\n",
        encoding="utf-8",
    )
    return ws


def test_status_read_hotpath_does_not_block_on_lock(tmp_path):
    ws = _init_mock_workspace(tmp_path)
    # Write an initial state
    update_runtime_mode(ws, switch_mode="standard", stop_at="after_propose")
    lock_path = get_runtime_mode_lock_path(ws)
    
    # Hold the lock externally
    external_lock = FileLock(lock_path)
    external_lock.acquire()
    try:
        t0 = time.perf_counter()
        snapshot = load_runtime_mode(ws, external_api_available=True)
        elapsed = time.perf_counter() - t0
        # Hot-path read must be non-blocking (< 50ms)
        assert elapsed < 0.1
        assert snapshot.runtime_mode_warning == "lock_contended_read_only"
        assert snapshot.effective_mode == "standard"
        assert snapshot.autopilot.stop_at == "after_propose"
    finally:
        external_lock.release()


def test_concurrent_double_consume_rejected(tmp_path):
    ws = _init_mock_workspace(tmp_path)
    snap, applied, _ = update_runtime_mode(ws, stop_at="after_propose")
    assert applied is True
    initial_set_at = snap.autopilot.set_at
    assert initial_set_at is not None

    # First consumer succeeds with expect_set_at
    snap_a, applied_a, mut_a = update_runtime_mode(
        ws,
        consume_stop_at=True,
        expect_set_at=initial_set_at,
        current_task_id="1.1",
    )
    assert applied_a is True
    assert snap_a.autopilot.consumed is True
    assert snap_a.autopilot.consumed_for == "1.1"
    new_set_at = snap_a.autopilot.set_at
    assert new_set_at != initial_set_at  # Monotonic refresh

    # Second consumer tries with stale expect_set_at -> rejected
    snap_b, applied_b, mut_b = update_runtime_mode(
        ws,
        consume_stop_at=True,
        expect_set_at=initial_set_at,
        current_task_id="1.2",
    )
    assert applied_b is False
    assert mut_b.get("consume_mismatch") is True
    assert mut_b.get("expected_set_at") == initial_set_at
    assert mut_b.get("disk_set_at") == new_set_at
    # Disk was not corrupted by second consumer
    assert snap_b.autopilot.consumed_for == "1.1"


def test_consumed_for_never_uses_task_file_key(tmp_path):
    ws = _init_mock_workspace(tmp_path)
    snap1, _, _ = update_runtime_mode(
        ws,
        task_file="2026-10-24_feature.md",
        stop_at="after_review",
    )
    assert snap1.autopilot.task_file == "2026-10-24_feature.md"
    assert snap1.autopilot.consumed_for is None

    # Consume without task_id
    snap2, applied, _ = update_runtime_mode(
        ws,
        consume_stop_at=True,
        expect_set_at=snap1.autopilot.set_at,
    )
    assert applied is True
    # Crucial: consumed_for NEVER falls back to task_file path
    assert snap2.autopilot.consumed_for is None
    assert snap2.autopilot.consumed_for != "2026-10-24_feature.md"

    # Reset and consume with task_id
    snap3, _, _ = update_runtime_mode(ws, stop_at="after_review")
    snap4, _, _ = update_runtime_mode(
        ws,
        consume_stop_at=True,
        expect_set_at=snap3.autopilot.set_at,
        current_task_id="1.1",
    )
    assert snap4.autopilot.consumed_for == "1.1"

    # Batch stage namespace
    snap5, _, _ = update_runtime_mode(ws, stop_at="after_batch")
    snap6, _, _ = update_runtime_mode(
        ws,
        consume_stop_at=True,
        expect_set_at=snap5.autopilot.set_at,
        consume_for="__batch__:2026-10-24_feature.md",
    )
    assert snap6.autopilot.consumed_for == "__batch__:2026-10-24_feature.md"


def test_status_response_backward_compat(tmp_path):
    ws = _init_mock_workspace(tmp_path)
    res = dev_tasks_status(ws)

    # Legacy keys set frozen
    legacy_keys = {
        "project_name",
        "dev_tasks_dir",
        "files",
        "active_task",
        "session_bypass",
        "static_fast_track_patterns",
        "governance_scope",
        "last_hook_log_entries",
        "reconcile_report",
        "bypass_queue",
    }
    for k in legacy_keys:
        assert k in res, f"Missing legacy key: {k}"

    # New dual mode keys
    new_keys = {
        "effective_mode",
        "mode_source",
        "effective_reviewer_channel",
        "runner_subagent_model_hint",
        "fallback_notice",
        "runtime_mode_warning",
        "session_role_contract",
        "autopilot",
    }
    for k in new_keys:
        assert k in res, f"Missing new dual mode key: {k}"

    contract = res["session_role_contract"]
    assert contract["role"] in ("runner", "reviewer_orchestrator")
    assert "[QUENCH-DISPATCH: RUNNER]" in contract["dispatch_envelope"]
    assert contract["handshake_rule"] == "status_called_by_main_only"


def test_stop_at_none_clears_consumed_even_when_foreign_task(tmp_path):
    ws = _init_mock_workspace(tmp_path)
    snap1, _, _ = update_runtime_mode(ws, stop_at="after_confirm")
    snap2, _, _ = update_runtime_mode(
        ws,
        consume_stop_at=True,
        expect_set_at=snap1.autopilot.set_at,
        current_task_id="task_A",
    )
    assert snap2.autopilot.consumed is True
    assert snap2.autopilot.consumed_for == "task_A"

    # Calling stop_at="none" clears consumed and consumed_for
    snap3, _, _ = update_runtime_mode(ws, stop_at="none", current_task_id="task_B")
    assert snap3.autopilot.stop_at == "none"
    assert snap3.autopilot.consumed is False
    assert snap3.autopilot.consumed_for is None
    assert snap3.autopilot.set_at is not None


def test_switch_denied_mode_inverted(tmp_path):
    ws = _init_mock_workspace(tmp_path)
    # Switch to inverted mode
    res1 = dev_tasks_status(ws, switch_mode="inverted")
    assert res1["effective_mode"] == "inverted"
    assert res1.get("runtime_mode_changed") is True

    # Attempt to change reviewer channel while in inverted mode
    res2 = dev_tasks_status(ws, switch_reviewer_channel="host_subagent")
    assert res2["runtime_mode_changed"] is False
    assert res2["reason"] == "switch_denied_mode_inverted"
    assert "reviewer_channel 仅在 standard 模式下有效" in res2["runtime_mode_warning"]


def test_switch_denied_task_in_progress(tmp_path):
    from server import dev_tasks_propose, dev_tasks_confirm, dev_tasks_checkout

    ws = _init_mock_workspace(tmp_path)
    # Propose, confirm, and check out a task
    dev_tasks_propose(
        ws,
        "2026-10-24_active.md",
        [{
            "id": "1.1",
            "title": "Active Task",
            "affected_files": ["foo.py"],
            "root_cause_and_goal": "Goal",
            "type_contracts": "def foo(): pass",
            "steps": "1. Step",
            "defensive_checks": "Defense",
            "dod_commands": ["pytest foo.py"],
        }],
        mode="overwrite",
    )
    dev_tasks_confirm(ws, "2026-10-24_active.md", ["1.1"], action="confirm")
    dev_tasks_checkout(ws, "2026-10-24_active.md", "1.1")

    # Status sees active task
    status_res = dev_tasks_status(ws)
    assert status_res["active_task"] is not None
    assert status_res["active_task"]["id"] == "1.1"

    # Switching mode while task is in progress must be rejected
    res_deny = dev_tasks_status(ws, switch_mode="inverted")
    assert res_deny["runtime_mode_changed"] is False
    assert res_deny["reason"] == "switch_denied_task_in_progress"

    # But resetting breakpoint (stop_at="none") must be permitted!
    res_allow = dev_tasks_status(ws, stop_at="none")
    assert res_allow.get("runtime_mode_changed") is True
    assert res_allow.get("reason") is None
    assert res_allow["autopilot"]["stop_at"] == "none"



def test_auto_fallback_dynamic_computation_without_disk_mutation(tmp_path):
    ws = _init_mock_workspace(tmp_path)
    mode_path = get_runtime_mode_path(ws)
    assert not os.path.exists(mode_path)

    # When external API is not available and no explicit mode is configured:
    snapshot = load_runtime_mode(ws, external_api_available=False)
    assert snapshot.effective_mode == "inverted"
    assert snapshot.mode_source == "auto_fallback"
    assert snapshot.fallback_notice is not None
    assert "自动回退为 inverted 模式" in snapshot.fallback_notice
    # Must NOT mutate disk!
    assert not os.path.exists(mode_path)


def test_gitignore_ignores_runtime_mode_files():
    # Use git check-ignore to verify physical ignore in the real repository
    proc = subprocess.run(
        ["git", "check-ignore", "-v", ".agents/.quench_runtime_mode.json", ".agents/.quench_runtime_mode.json.lock"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert ".agents/.quench_runtime_mode.json" in proc.stdout
    assert ".agents/.quench_runtime_mode.json.lock" in proc.stdout
