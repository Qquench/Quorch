"""Regression tests for v1.36 Batch 1 (Tasks 36.1, 36.2, 36.3)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import server
from project_config import QuenchStackConfig
from runtime_mode import get_runtime_mode_lock_path, get_runtime_mode_path, load_runtime_mode, update_runtime_mode
from server import (
    _audit_test_changes,
    _inject_harness_next_action,
    _python_source_has_real_assertions,
    _resolve_task_file_path,
    dev_tasks_archive,
    dev_tasks_checkout,
    dev_tasks_complete,
    dev_tasks_confirm,
    dev_tasks_escalate,
    dev_tasks_promote_draft,
    dev_tasks_propose,
    dev_tasks_status,
)


def _init_ws(tmp_path: Path) -> str:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    agents = ws / ".agents"
    agents.mkdir(exist_ok=True)
    cfg = {
        "project_name": "V136Batch1",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "changelog_path": "CHANGELOG.md",
        "test_dir": "tests",
        "test_runner": "pytest",
        "audit_gate": {"enabled": False},
    }
    (agents / "quench_stack.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (ws / "docs" / "dev_tasks").mkdir(parents=True, exist_ok=True)
    return str(ws)


def _sample_task(tid: str, file_path: str = "src/app.py") -> dict:
    return {
        "id": tid,
        "title": f"Task {tid}",
        "affected_files": [f"[MODIFY] {file_path}"],
        "root_cause_and_goal": "Fix defect",
        "type_contracts": "def fn() -> None",
        "steps": ["1. Implement"],
        "defensive_checks": ["- Check boundary"],
        "dod_commands": ["pytest"],
    }


@pytest.mark.tier1_fast
def test_archive_clears_autopilot_task_file_and_discovers_new_batch(tmp_path):
    """Task 36.1: dev_tasks_archive clears autopilot.task_file and missing task_file falls back to dev_tasks_dir scan."""
    ws = _init_ws(tmp_path)
    dev_tasks_propose(ws, "2026-11-26_batch1.md", [_sample_task("1.1")])
    dev_tasks_confirm(ws, "2026-11-26_batch1.md", ["1.1"], action="confirm")
    chk = dev_tasks_checkout(ws, task_id="1.1")
    dev_tasks_complete(
        ws,
        "2026-11-26_batch1.md",
        "1.1",
        dod_output="ok",
        holder_token=chk.get("holder_token"),
        generation=chk.get("generation"),
    )

    # Pin old task_file in runtime_mode
    update_runtime_mode(ws, task_file="docs/dev_tasks/2026-11-26_batch1.md", external_api_available=True)
    arch = dev_tasks_archive(ws, "2026-11-26_batch1.md")
    assert arch["archived"] is True

    snap_after_arch = load_runtime_mode(ws, True)
    assert snap_after_arch.autopilot.task_file == ""

    # Propose batch 2, and simulate stale autopilot.task_file pointing to missing file
    dev_tasks_propose(ws, "2026-11-26_batch2.md", [_sample_task("2.1")])
    update_runtime_mode(ws, task_file="docs/dev_tasks/deleted_ghost.md", external_api_available=True)

    res_dict = {}
    _inject_harness_next_action(ws, "dev_tasks_status", res_dict, last_success=True)
    assert res_dict["harness_next_action"]["task_file"] == "docs/dev_tasks/2026-11-26_batch2.md"
    assert res_dict["harness_next_action"]["action"] == "REVIEW"


@pytest.mark.tier1_fast
def test_cumulative_runner_tasks_backward_compat_increment_and_fuse_reset(tmp_path):
    """Task 36.1: Legacy runtime_mode defaults cumulative_runner_tasks=0; complete increments, >=12 triggers spawn_fresh, checkout resets."""
    ws = _init_ws(tmp_path)
    mode_path = Path(ws) / ".agents" / ".quench_runtime_mode.json"
    legacy_payload = {
        "orchestration_mode": "inverted",
        "reviewer_channel": "external_api",
        "autopilot": {
            "task_file": None,
            "stop_at": "none",
            "consumed": False,
            "consumed_for": None,
            "set_at": None,
        },
    }
    mode_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    # Backward compatibility
    snap0 = load_runtime_mode(ws, False)
    assert snap0.autopilot.cumulative_runner_tasks == 0

    # Complete task 1 -> cumulative_runner_tasks increments to 1
    dev_tasks_propose(ws, "2026-11-26_b1.md", [_sample_task("1.1", "backend/core.py")])
    dev_tasks_confirm(ws, "2026-11-26_b1.md", ["1.1"], action="confirm")
    chk1 = dev_tasks_checkout(ws, task_id="1.1")
    dev_tasks_complete(
        ws,
        "2026-11-26_b1.md",
        "1.1",
        dod_output="ok",
        holder_token=chk1.get("holder_token"),
        generation=chk1.get("generation"),
    )
    assert load_runtime_mode(ws, False).autopilot.cumulative_runner_tasks == 1
    assert dev_tasks_archive(ws, "2026-11-26_b1.md")["archived"] is True

    # Simulate 12 cumulative tasks completed before next overlapping batch
    update_runtime_mode(ws, switch_mode="inverted", cumulative_runner_tasks=12, external_api_available=False)
    dev_tasks_propose(ws, "2026-11-26_b2.md", [_sample_task("2.1", "backend/core.py")])
    conf2 = dev_tasks_confirm(ws, "2026-11-26_b2.md", ["2.1"], action="confirm")
    # Even though backend/core.py overlaps 100% with archived b1, >=12 fuse forces spawn_fresh
    assert conf2["harness_next_action"]["action"] == "DISPATCH_RUNNER"
    assert conf2["harness_next_action"]["channel"] == "spawn_fresh"

    # Checkout of first task in new batch with spawn_fresh resets cumulative_runner_tasks to 0
    chk2 = dev_tasks_checkout(ws, task_id="2.1")
    assert chk2["harness_next_action"]["channel"] == "spawn_fresh"
    assert load_runtime_mode(ws, False).autopilot.cumulative_runner_tasks == 0


@pytest.mark.tier1_fast
def test_runtime_mode_cas_mismatch_no_self_timeout_and_non_dict_tolerance(tmp_path):
    """Task 36.2: CAS mismatch avoids re-entering FileLock; non-dict JSON and autopilot:null are tolerated."""
    ws = _init_ws(tmp_path)
    mode_path = Path(get_runtime_mode_path(ws))

    # 1. CAS mismatch must NOT emit lock_contended_read_only warning
    snap_init, applied_init, _ = update_runtime_mode(ws, stop_at="after_confirm", external_api_available=True)
    assert applied_init is True
    snap_cas, applied_cas, meta_cas = update_runtime_mode(
        ws,
        consume_stop_at=True,
        expect_set_at="stale-timestamp",
        external_api_available=True,
    )
    assert applied_cas is False
    assert meta_cas.get("consume_mismatch") is True
    assert meta_cas.get("disk_set_at") == snap_init.autopilot.set_at
    assert snap_cas.runtime_mode_warning is None
    assert snap_cas.autopilot.stop_at == "after_confirm"

    # 2. Non-dict root JSON (e.g. [])
    mode_path.write_text("[]", encoding="utf-8")
    snap_list = load_runtime_mode(ws, True)
    assert snap_list.effective_mode == "standard"
    assert snap_list.runtime_mode_warning == "runtime_mode_invalid_root_type"

    # 3. autopilot: null
    mode_path.write_text(json.dumps({"orchestration_mode": "inverted", "autopilot": None}), encoding="utf-8")
    snap_null = load_runtime_mode(ws, True)
    assert snap_null.effective_mode == "inverted"
    assert snap_null.autopilot.stop_at == "none"
    assert snap_null.autopilot.cumulative_runner_tasks == 0
    assert snap_null.runtime_mode_warning == "runtime_mode_invalid_autopilot_type"


@pytest.mark.tier1_fast
def test_runtime_mode_lock_timeout_graceful_degradation(tmp_path):
    """Task 36.2: Contended FileLock Timeout degrades gracefully with rejected_reason='lock_timeout'."""
    from filelock import FileLock

    ws = _init_ws(tmp_path)
    update_runtime_mode(ws, stop_at="after_review", external_api_available=True)
    lock_path = get_runtime_mode_lock_path(ws)

    held = FileLock(lock_path, timeout=0.05)
    with held:
        snap, applied, meta = update_runtime_mode(
            ws,
            stop_at="none",
            lock_timeout_s=0.05,
            external_api_available=True,
        )
    assert applied is False
    assert meta.get("rejected_reason") == "lock_timeout"
    assert snap.autopilot.stop_at == "after_review"


@pytest.mark.tier1_fast
def test_resolve_task_file_path_confinement_and_tool_error_handling(tmp_path):
    """Task 36.3: _resolve_task_file_path blocks workspace escapes and tool callers return structured errors."""
    ws = _init_ws(tmp_path)
    dev_tasks_propose(ws, "2026-11-26_valid.md", [_sample_task("1.1")])
    valid_path = Path(ws) / "docs" / "dev_tasks" / "2026-11-26_valid.md"

    # Valid resolutions
    assert _resolve_task_file_path(ws, "2026-11-26_valid.md") == os.path.realpath(valid_path)
    assert _resolve_task_file_path(ws, "docs/dev_tasks/2026-11-26_valid.md") == os.path.realpath(valid_path)
    assert _resolve_task_file_path(ws, str(valid_path)) == os.path.realpath(valid_path)

    # Escape vectors
    outside_file = tmp_path / "outside_secret.md"
    outside_file.write_text("# secret\n", encoding="utf-8")
    for bad_path in ("../outside_secret.md", "../../../outside_secret.md", str(outside_file)):
        with pytest.raises(ValueError, match="escapes workspace_root"):
            _resolve_task_file_path(ws, bad_path)

    # Tool callers convert escapes into structured errors without mutating outside files
    arch_rel = dev_tasks_archive(ws, "../outside_secret.md")
    assert arch_rel.get("archived") is False and "error" in arch_rel
    arch_abs = dev_tasks_archive(ws, str(outside_file))
    assert arch_abs.get("archived") is False and "error" in arch_abs
    assert outside_file.exists()

    promo_res = dev_tasks_promote_draft(ws, "../outside_secret.md", "1.1")
    assert promo_res.get("status") == "rejected" and promo_res.get("promoted") is False

    esc_res = dev_tasks_escalate(ws, "../outside_secret.md", "1.1", "blocked")
    assert esc_res.get("status") == "error" and "error" in esc_res

    conf_res = dev_tasks_confirm(ws, "../outside_secret.md", ["1.1"])
    assert "error" in conf_res

    chk_res = dev_tasks_checkout(ws, task_file="../outside_secret.md")
    assert "error" in chk_res

    comp_res = dev_tasks_complete(ws, "../outside_secret.md", "1.1", "ok")
    assert comp_res.get("status") == "rejected"

    # dev_tasks_escalate context_files sanitization skips outside files
    inside_src = Path(ws) / "src" / "app.py"
    inside_src.parent.mkdir(parents=True, exist_ok=True)
    inside_src.write_text("def ok():\n    return 1\n", encoding="utf-8")
    esc_ctx = dev_tasks_escalate(
        ws,
        "2026-11-26_valid.md",
        "1.1",
        "need review",
        context_files=["../outside_secret.md", "src/app.py"],
    )
    assert esc_ctx.get("status") == "escalated"
    assert esc_ctx.get("context_files_loaded") == 1


@pytest.mark.tier1_fast
def test_python_source_has_real_assertions_ast_and_git_subdir_audit(tmp_path):
    """Task 36.3: AST assertion checker rejects comments/docstrings and git subdir/non-ASCII audit works."""
    assert _python_source_has_real_assertions("# assert True\n") is False
    assert _python_source_has_real_assertions('def test_fake():\n    """assert True"""\n    # assert 1 == 1\n    pass\n') is False
    assert _python_source_has_real_assertions("def test_real():\n    assert 1 == 1\n") is True
    assert _python_source_has_real_assertions("    assert result['ok'] is True\n") is True
    assert _python_source_has_real_assertions("with pytest.raises(ValueError):\n    fn()\n") is True
    assert _python_source_has_real_assertions("with pytest.warns(UserWarning):\n    fn()\n") is True
    assert _python_source_has_real_assertions("class T:\n    def test_a(self):\n        self.assertEqual(1, 1)\n") is True

    # Git repository where workspace_root is a subdirectory and filenames are non-ASCII
    repo = tmp_path / "repo"
    sub_ws = repo / "subws"
    (sub_ws / "src").mkdir(parents=True)
    (sub_ws / "tests").mkdir(parents=True)
    src_file = sub_ws / "src" / "核心.py"
    test_file = sub_ws / "tests" / "test_核心.py"
    src_file.write_text("def run():\n    return 1\n", encoding="utf-8")
    test_file.write_text("def test_run():\n    assert 1 == 1\n", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True, check=True)

    cfg = QuenchStackConfig(workspace_root=str(sub_ws), project_name="SubWs")

    # Modify governed code + add ONLY a comment '# assert True' to tracked test
    src_file.write_text("def run():\n    return 2\n", encoding="utf-8")
    test_file.write_text("def test_run():\n    assert 1 == 1\n    # assert True\n", encoding="utf-8")
    audit_fake = _audit_test_changes(str(sub_ws), cfg)
    assert "src/核心.py" in audit_fake["governed_code_changed"]
    assert "tests/test_核心.py" in audit_fake["test_files_changed"]
    assert audit_fake["assertions_found"] is False
    assert audit_fake["passed"] is False

    # Now add a real assertion in diff
    test_file.write_text("def test_run():\n    assert 1 == 1\n    assert 2 == 2\n", encoding="utf-8")
    audit_real = _audit_test_changes(str(sub_ws), cfg)
    assert audit_real["assertions_found"] is True
    assert audit_real["passed"] is True


@pytest.mark.tier1_fast
def test_naive_utc_bypass_expires_at_parsing(tmp_path):
    """Task 36.3: Naive ISO expires_at in .quench_bypass.json is interpreted as UTC."""
    ws = _init_ws(tmp_path)
    bypass_path = Path(ws) / ".agents" / ".quench_bypass.json"

    future_naive_utc = (datetime.now(timezone.utc) + timedelta(minutes=30)).replace(tzinfo=None).isoformat()
    bypass_path.write_text(
        json.dumps({
            "active": True,
            "session_id": "sess-1",
            "category": "docs_only",
            "patterns": ["*.md"],
            "reason": "test",
            "expires_at": future_naive_utc,
        }),
        encoding="utf-8",
    )
    st_active = dev_tasks_status(ws, verbosity="full")
    assert st_active["session_bypass"]["active"] is True

    past_naive_utc = (datetime.now(timezone.utc) - timedelta(minutes=30)).replace(tzinfo=None).isoformat()
    bypass_path.write_text(
        json.dumps({
            "active": True,
            "session_id": "sess-1",
            "category": "docs_only",
            "patterns": ["*.md"],
            "reason": "test",
            "expires_at": past_naive_utc,
        }),
        encoding="utf-8",
    )
    st_expired = dev_tasks_status(ws, verbosity="full")
    assert st_expired["session_bypass"]["active"] is False
    assert st_expired["session_bypass"]["expired"] is True
