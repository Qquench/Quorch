from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import filelock
import pytest
import yaml

from manifest import (
    Manifest,
    TaskRecord,
    MANIFEST_REL_PATH,
    FencedTokenError,
    _resolve_namespaced_id,
    atomic_replace_manifest,
    commit_lease,
    compute_manifest_metrics,
    load_manifest,
    register_proposal,
)
from manifest_lease import (
    HealthVerdict,
    _evaluate_affected_files_mtime,
    _extract_affected_files_from_task,
    is_workspace_actively_modifying,
    probe_lease_health,
    reclaim_stale_task,
    touch_lease_heartbeat,
)
from server import (
    dev_tasks_checkout,
    dev_tasks_confirm,
    dev_tasks_heartbeat,
)
from state_machine import (
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    parse_task_file,
)


def _init_ws(tmp_path: Path) -> tuple[str, Path]:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    agents = ws / ".agents"
    agents.mkdir(parents=True)
    cfg = {
        "project_name": "Batch3Test",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "changelog_path": "CHANGELOG.md",
        "test_dir": "tests",
        "test_runner": "pytest",
        "audit_gate": {"enabled": False},
        "reaper_policy": {
            "heartbeat_silence_threshold_seconds": 900,
            "affected_files_mtime_threshold_seconds": 600,
        },
    }
    (agents / "quench_stack.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    tasks_dir = ws / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True)
    src_dir = ws / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "app.py").write_text("# app\n", encoding="utf-8")
    return str(ws), tasks_dir


def test_dev_tasks_confirm_acquires_md_lock_before_manifest_lock(tmp_path, monkeypatch):
    """Task 36.6: dev_tasks_confirm acquires Markdown lock before Manifest lock (canonical order)."""
    ws, tasks_dir = _init_ws(tmp_path)
    task_file = tasks_dir / "2026-11-26_lock_order.md"
    task_file.write_text(
        "### 任务 1.1 ⬜ 待确认 — Lock Order Test\n\n"
        "#### 【涉及文件】\n```\n[MODIFY] src/app.py\n```\n",
        encoding="utf-8",
    )
    register_proposal(ws, task_id="1.1", md_path=str(task_file))

    acquired: list[str] = []
    orig_acquire = filelock.FileLock.acquire

    def spy_acquire(self, *args, **kwargs):
        acquired.append(os.path.basename(self.lock_file))
        return orig_acquire(self, *args, **kwargs)

    monkeypatch.setattr(filelock.FileLock, "acquire", spy_acquire)
    res = dev_tasks_confirm(ws, task_file.name, ["1.1"], action="confirm")
    assert res["errors"] == []
    assert len(res["updated"]) == 1
    lease_locks = [f for f in acquired if f.endswith(".md.lock") or f == "manifest.json.lock"]
    assert lease_locks.index(f"{task_file.name}.lock") < lease_locks.index("manifest.json.lock")


def test_reclaim_stale_task_no_half_commit_on_transition_failure(tmp_path):
    """Task 36.6: reclaim_stale_task keeps manifest unreleased if transition_task fails."""
    ws, tasks_dir = _init_ws(tmp_path)
    task_file = tasks_dir / "2026-11-26_half.md"
    task_file.write_text(
        "### 任务 1.1 🔨 执行中 — Half Commit Guard\n\n"
        "#### 【涉及文件】\n```\n[MODIFY] src/app.py\n```\n",
        encoding="utf-8",
    )
    ns_id = "2026-11-26_half::1.1"
    m = load_manifest(ws)
    stale_wall = (datetime.now(timezone.utc) - timedelta(seconds=1500)).isoformat()
    m.records[ns_id] = TaskRecord(
        task_id=ns_id,
        md_sha256="hash",
        generation=1,
        holder_token="tok_half",
        last_heartbeat_monotonic_ns=0,
        last_heartbeat_wall_utc=stale_wall,
        git_head_sha="sha",
        git_index_mtime=0.0,
        released=False,
    )
    atomic_replace_manifest(ws, m)

    with patch("manifest_lease.transition_task", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            reclaim_stale_task(
                ws,
                task_id=ns_id,
                expected_generation=1,
                expected_holder_token="tok_half",
                force=True,
            )

    # Manifest must remain unreleased at gen=1 so retry can recover
    m_after_fail = load_manifest(ws)
    assert m_after_fail.records[ns_id].released is False
    assert m_after_fail.records[ns_id].generation == 1

    ok, reason = reclaim_stale_task(
        ws,
        task_id=ns_id,
        expected_generation=1,
        expected_holder_token="tok_half",
        force=True,
    )
    assert ok is True
    assert reason == "reclaimed"
    assert parse_task_file(str(task_file))[0].status == STATUS_CONFIRMED


def test_checkout_lease_failure_rolls_back_markdown_and_returns_error(tmp_path):
    """Task 36.6: _issue_checkout_lease does not forge tokens on failure; checkout rolls back to Confirmed."""
    ws, tasks_dir = _init_ws(tmp_path)
    task_file = tasks_dir / "2026-11-26_lease_fail.md"
    task_file.write_text(
        "### 任务 1.1 ✅ 已确认 — Lease Fail Rollback\n\n"
        "#### 【涉及文件】\n```\n[MODIFY] src/app.py\n```\n",
        encoding="utf-8",
    )
    register_proposal(ws, task_id="1.1", md_path=str(task_file))

    with patch("server.commit_lease", side_effect=FencedTokenError("forced conflict")):
        res = dev_tasks_checkout(ws, task_file=task_file.name, task_id="1.1")

    assert "error" in res
    assert "holder_token" not in res
    assert parse_task_file(str(task_file))[0].status == STATUS_CONFIRMED


def test_checkout_reentrant_cross_session_blocks_token_leak(tmp_path):
    """Task 36.6: Re-entrant checkout rejects mismatched/missing session_id when bound, allows matching or unscoped."""
    ws, tasks_dir = _init_ws(tmp_path)
    task_file = tasks_dir / "2026-11-26_reentrant.md"
    task_file.write_text(
        "### 任务 1.1 ✅ 已确认 — Scoped Task\n\n"
        "### 任务 1.2 ✅ 已确认 — Unscoped Task\n",
        encoding="utf-8",
    )
    register_proposal(ws, task_id="1.1", md_path=str(task_file))
    register_proposal(ws, task_id="1.2", md_path=str(task_file))

    # 1. Scoped checkout
    r1 = dev_tasks_checkout(ws, task_file=task_file.name, task_id="1.1", session_id="sess-alpha-1111")
    assert r1["status"] == STATUS_IN_PROGRESS
    assert "holder_token" in r1

    # Re-entrant with missing session_id -> blocked, no token leaked
    r_missing = dev_tasks_checkout(ws, task_file=task_file.name, task_id="1.1")
    assert "error" in r_missing
    assert "holder_token" not in r_missing

    # Re-entrant with different session_id -> blocked, no token leaked
    r_wrong = dev_tasks_checkout(ws, task_file=task_file.name, task_id="1.1", session_id="sess-beta-2222")
    assert "error" in r_wrong
    assert "holder_token" not in r_wrong

    # Re-entrant with matching session_id -> allowed
    r_same = dev_tasks_checkout(ws, task_file=task_file.name, task_id="1.1", session_id="sess-alpha-1111")
    assert r_same["holder_token"] == r1["holder_token"]
    assert r_same["generation"] == r1["generation"]

    # 2. Unscoped checkout -> re-entrant without session_id stays 100% compatible
    r2 = dev_tasks_checkout(ws, task_file=task_file.name, task_id="1.2")
    assert "holder_token" in r2
    r2_again = dev_tasks_checkout(ws, task_file=task_file.name, task_id="1.2")
    assert r2_again["holder_token"] == r2["holder_token"]


def test_bare_task_id_prefers_active_over_released_tombstone(tmp_path):
    """Task 36.6: Bare task_id resolution prefers unreleased active records over released tombstones."""
    ws, tasks_dir = _init_ws(tmp_path)
    old_file = tasks_dir / "2026-01-01_old.md"
    new_file = tasks_dir / "2026-11-26_new.md"
    old_file.write_text("### 任务 1.1 ✔️ 已完成 — Old\n", encoding="utf-8")
    new_file.write_text("### 任务 1.1 🔨 执行中 — New\n", encoding="utf-8")

    now_iso = datetime.now(timezone.utc).isoformat()
    m = Manifest(
        schema_version="1.0",
        records={
            "2026-01-01_old::1.1": TaskRecord(
                task_id="2026-01-01_old::1.1",
                md_sha256="a" * 64,
                generation=3,
                holder_token="token_old_1000_1",
                last_heartbeat_monotonic_ns=1,
                last_heartbeat_wall_utc=now_iso,
                git_head_sha="sha",
                git_index_mtime=1.0,
                released=True,
            ),
            "2026-11-26_new::1.1": TaskRecord(
                task_id="2026-11-26_new::1.1",
                md_sha256="b" * 64,
                generation=1,
                holder_token="token_sess-active_1000_1",
                last_heartbeat_monotonic_ns=2,
                last_heartbeat_wall_utc=now_iso,
                git_head_sha="sha",
                git_index_mtime=2.0,
                released=False,
            ),
        },
    )
    atomic_replace_manifest(ws, m)

    assert _resolve_namespaced_id(m, "1.1") == "2026-11-26_new::1.1"
    ev = probe_lease_health(ws, task_id="1.1")
    assert ev.task_id == "2026-11-26_new::1.1"
    assert ev.verdict == HealthVerdict.HEALTHY

    hb_res = asyncio.run(dev_tasks_heartbeat(workspace_root=ws, task_id="1.1"))
    assert hb_res["status"] == "ok"
    assert hb_res["task_id"] == "2026-11-26_new::1.1"


def test_touch_lease_heartbeat_matches_second_record_for_same_session(tmp_path):
    """Task 36.6: touch_lease_heartbeat filters by holder_token/generation instead of breaking on first session match."""
    ws, tasks_dir = _init_ws(tmp_path)
    f1 = tasks_dir / "2026-11-26_a.md"
    f2 = tasks_dir / "2026-11-26_b.md"
    f1.write_text("### 任务 1.1 🔨 执行中 — A\n", encoding="utf-8")
    f2.write_text("### 任务 2.1 🔨 执行中 — B\n", encoding="utf-8")

    sid = "same-session-77"
    tok1 = f"token_{sid}_1000_11"
    tok2 = f"token_{sid}_2000_22"
    commit_lease(ws, task_id="1.1", holder_token=tok1, expected_generation=0, md_path=str(f1))
    commit_lease(ws, task_id="2.1", holder_token=tok2, expected_generation=0, md_path=str(f2))

    assert touch_lease_heartbeat(ws, session_id=sid, ttl_seconds=60, holder_token=tok2, generation=1) is True


def test_probe_empty_hb_and_missing_new_parent_and_extract_isolation(tmp_path, caplog):
    """Task 36.6: Empty/invalid hb is stale; missing [NEW] parent is not HEALTHY; extract ignores next task."""
    ws, tasks_dir = _init_ws(tmp_path)
    task_file = tasks_dir / "2026-11-26_probe.md"
    task_file.write_text(
        "### 任务 1.1 🔨 执行中 — No Affected Section\n\n"
        "#### 【缺陷根因与修改目标】\n无涉及文件\n\n"
        "### 任务 1.2 🔨 执行中 — Has Affected Section\n\n"
        "#### 【涉及文件】\n"
        "```\n"
        "[new] ./missing_dir/brand_new.py (新建)\n"
        "[rename] ./src/old.py -> ./src/app.py （重命名）\n"
        "```\n",
        encoding="utf-8",
    )

    assert _extract_affected_files_from_task(str(tasks_dir), "2026-11-26_probe", "1.1") is None
    extracted_12 = _extract_affected_files_from_task(str(tasks_dir), "2026-11-26_probe", "1.2")
    assert extracted_12 == ["missing_dir/brand_new.py", "src/old.py", "src/app.py"]

    # Outside workspace paths rejected in _evaluate_affected_files_mtime
    age, note = _evaluate_affected_files_mtime(ws, ["../../outside.py"], time.time())
    assert age is None
    assert note is not None

    # Empty heartbeat + missing [NEW] parent dir -> STALE_SUSPECT (conservative_on_unreadable=False)
    m = load_manifest(ws)
    m.records["2026-11-26_probe::1.2"] = TaskRecord(
        task_id="2026-11-26_probe::1.2",
        md_sha256="c" * 64,
        generation=1,
        holder_token="tok_empty_hb",
        last_heartbeat_monotonic_ns=0,
        last_heartbeat_wall_utc="",
        git_head_sha="sha",
        git_index_mtime=0.0,
        released=False,
    )
    atomic_replace_manifest(ws, m)

    # Make src/app.py and src dir stale (>600s) and missing_dir/brand_new.py non-existent
    stale_ts = time.time() - 1500.0
    os.utime(os.path.join(ws, "src", "app.py"), (stale_ts, stale_ts))
    os.utime(os.path.join(ws, "src"), (stale_ts, stale_ts))
    ev = probe_lease_health(ws, task_id="2026-11-26_probe::1.2")
    assert ev.verdict == HealthVerdict.STALE_SUSPECT
    assert is_workspace_actively_modifying(
        ws, ["missing_dir/brand_new.py"], window_seconds=600.0, conservative_on_unreadable=False
    ) is False

    # Manifest size warning threshold check
    big_records = {
        f"spec::{i}": TaskRecord(
            task_id=f"spec::{i}",
            md_sha256="x" * 64,
            generation=1,
            holder_token="tok",
            last_heartbeat_monotonic_ns=1,
            last_heartbeat_wall_utc="",
            git_head_sha="sha",
            git_index_mtime=1.0,
            released=True,
        )
        for i in range(501)
    }
    with caplog.at_level(logging.WARNING, logger="quench_dev_tasks.manifest"):
        metrics = compute_manifest_metrics(Manifest(records=big_records))
    assert metrics.record_count == 501
    assert any("Manifest size warning" in rec.message for rec in caplog.records)


def test_normalize_status_word_boundaries():
    """Task 36.7: normalize_status rejects negations/compounds like unconfirmed, undone, skip_check."""
    from task_status import (
        STATUS_COMPLETED,
        STATUS_CONFIRMED,
        STATUS_IN_PROGRESS,
        STATUS_PENDING,
        STATUS_REWORK,
        STATUS_SKIPPED,
        STATUS_UNKNOWN,
        normalize_status,
    )

    assert normalize_status("unconfirmed") == STATUS_UNKNOWN
    assert normalize_status("undone") == STATUS_UNKNOWN
    assert normalize_status("skip_check") == STATUS_UNKNOWN
    assert normalize_status("pre_confirmed") == STATUS_UNKNOWN
    assert normalize_status("Confirmed") == STATUS_CONFIRMED
    assert normalize_status("in_progress") == STATUS_IN_PROGRESS
    assert normalize_status("in progress") == STATUS_IN_PROGRESS
    assert normalize_status("done") == STATUS_COMPLETED
    assert normalize_status("skip") == STATUS_SKIPPED
    assert normalize_status("pending") == STATUS_PENDING
    assert normalize_status("rework") == STATUS_REWORK


def test_task_writer_compose_newline_and_state_machine_fenced_headers(tmp_path):
    """Task 36.7: compose_task_document adds newline only when appending to non-newline-ended text; state_machine ignores fenced headers."""
    from state_machine import extract_task_whitelist
    from task_writer import compose_task_document, split_task_document, write_task_file_guarded

    # Lossless roundtrip with no appended items even without trailing newline
    no_nl = "### 任务 1.1 ⬜ 待确认 — A\n\nBody"
    doc = split_task_document(no_nl)
    assert compose_task_document(doc, {}, ()) == no_nl
    composed = compose_task_document(doc, {}, ("### 任务 1.2 ⬜ 待确认 — B\n",))
    assert "\n### 任务 1.2" in composed
    assert "Body\n### 任务 1.2" in composed

    # Fence and cross-task isolation in extract_task_whitelist
    content = (
        "\ufeff# Doc\n\n"
        "```md\n### 任务 1.1 ⬜ 待确认 — Fake\n#### 【涉及文件】\n```\n[MODIFY] fake.py\n```\n```\n\n"
        "### 任务 1.1 ⬜ 待确认 — Real 1.1\n\n#### 【缺陷根因与修改目标】\n无涉及文件\n\n"
        "### 任务 1.2 ✅ 已确认 — Real 1.2\n\n#### 【涉及文件】\n```\n[modify] ./src/b.py (note)\n```\n"
    )
    assert extract_task_whitelist(content, "1.1") == []
    assert extract_task_whitelist(content, "1.2") == ["src/b.py"]

    # Append onto task file without trailing newline does not glue headers
    ws, tasks_dir = _init_ws(tmp_path)
    tf = tasks_dir / "2026-11-26_no_trailing_nl.md"
    tf.write_text("### 任务 1.1 ⬜ 待确认 — First\n\nBody without newline", encoding="utf-8")
    res = write_task_file_guarded(
        ws,
        tf.name,
        [
            {
                "id": "1.2",
                "title": "Second",
                "affected_files": ["[NEW] src/second.py"],
                "root_cause_and_goal": "Goal",
                "type_contracts": "None",
                "steps": ["1. Step"],
                "defensive_checks": ["- Check"],
                "dod_commands": ["pytest"],
            }
        ],
        mode="append",
    )
    assert res["ok"] is True
    written_text = tf.read_text(encoding="utf-8")
    assert "Body without newline\n### 任务 1.2 ⬜ 待确认 — Second" in written_text
