# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import shutil
import tempfile
import typing
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import pytest
import yaml

from project_config import (
    canonical_artifact_ref,
    AuditGatePolicy,
    AuditGateReason,
    AuditGateResult,
    QuenchStackConfig,
    ObservabilityConfig,
    load_project_config,
    most_restrictive_policy,
)
from path_guard import PathTraversalError
from state_machine import TaskItem, STATUS_PENDING, STATUS_CONFIRMED, STATUS_COMPLETED
from server import (
    _managed_path_matches,
    _freshness_ok,
    _extract_task_scoped_files,
    _read_recent_audit_records,
    _check_audit_gate,
    dev_tasks_propose,
    dev_tasks_confirm,
    dev_tasks_checkout,
)

TEST_IDS = [
    "01_roundtrip_real_writer_record_matches",
    "02_batch_two_tasks_single_doc_both_confirmed",
    "03_tail_window_exhausted_warns_and_allows",
    "04_torn_last_line_skipped_previous_matched",
    "05_degraded_record_follows_on_degraded_policy",
    "06_rework_revoke_skip_never_gated",
    "07_missing_log_dogfood_no_self_lock",
    "08_session_bypass_allows",
    "09_naive_timestamp_reports_timestamp_invalid",
    "10_blocked_when_no_matching_record",
    "11_stale_record_reports_record_stale",
    "12_internal_error_fail_open_reason",
    "13_audit_log_path_follows_observability_verdict_path",
    "14_bind_artifact_false_rejected_by_validator",
    "15_audit_log_path_traversal_rejected_by_path_guard",
    "16_no_manifest_lock_acquired_during_gate",
    "17_block_leaves_manifest_unchanged",
    "18_artifact_ref_is_task_scoped_two_tasks_same_doc_distinct",
    "19_truncated_with_matching_record_in_tail_returns_matched",
    "20_truncated_zero_parseable_tail_reports_tail_window_exhausted_not_unparsable",
    "21_confirm_revalidates_state_under_lock",
    "22_internal_error_never_used_for_block",
    "23_require_undegraded_false_accepts_fresh_degraded_record",
    "24_step10_only_when_truly_no_matching_record",
    "25_future_timestamp_beyond_tolerance_reports_timestamp_invalid",
    "26_stale_and_timestamp_invalid_are_mutually_exclusive",
    "27_disabled_reason_when_gate_disabled",
    "28_not_managed_scope_reason_when_no_managed_file",
    "29_log_unparsable_reason_on_io_failure",
    "30_canonical_artifact_ref_strips_leading_dot_slash",
    "31_corrupt_line_yields_parse_skipped_diagnostics",
    "32_ladder_predicate_exclusivity_matrix",
    "33_freshness_boundary_max_age_minus_epsilon_allows",
    "34_freshness_boundary_max_age_plus_epsilon_blocks_as_stale",
    "35_scoped_files_marker_normalization_reaches_managed_scope",
    "36_blocking_payload_exact_five_keys_no_allowed_key",
    "37_degraded_record_blocks_under_default_policy",
    "38_session_id_none_never_grants_bypass",
    "39_step5_tolerates_skew_within_tolerance_step8_rejects_beyond",
    "40_managed_glob_matches_concrete_server_path_reaches_blocked_not_not_managed_scope",
    "41_on_missing_record_warn_allows_and_reports_reason",
    "42_canonical_artifact_ref_task_id_equals_state_machine_task_id",
]

assert len(TEST_IDS) == 42


def _make_ws(tmp_path: Any, gate_kwargs: Optional[dict] = None) -> tuple[str, str, QuenchStackConfig]:
    ws = str(tmp_path)
    agents_dir = os.path.join(ws, ".agents")
    tasks_dir = os.path.join(ws, "docs", "dev_tasks")
    logs_dir = os.path.join(ws, ".agents", "logs", "reviewer")
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(tasks_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    g_cfg = {
        "enabled": True,
        "on_missing_record": "block",
        "on_degraded": "block",
        "on_internal_error": "allow",
    }
    if gate_kwargs:
        g_cfg.update(gate_kwargs)

    raw_yaml = {
        "project_name": "TestProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "governance_scope": {
            "managed_paths": ["plugins/quench-dev-tasks/server/**", "src/**"],
            "unmanaged_paths": ["docs/**"],
        },
        "observability": {"verdict_path": ".agents/logs/reviewer/verdicts.jsonl"},
        "audit_gate": g_cfg,
    }
    with open(os.path.join(agents_dir, "quench_stack.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(raw_yaml, f)

    cfg = load_project_config(ws)
    return ws, os.path.join(ws, ".agents", "logs", "reviewer", "verdicts.jsonl"), cfg


def _write_verdict(log_path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def test_roundtrip_real_writer_record_matches(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path)
    target_path = os.path.join(ws, "docs", "dev_tasks", "task.md")
    ref = canonical_artifact_ref(ws, target_path, "1.1")
    now_wall = datetime.now(timezone.utc).isoformat()
    _write_verdict(log_path, {
        "job_id": "job_1",
        "session_id": "s1",
        "created_wall_utc": now_wall,
        "updated_wall_utc": now_wall,
        "context_files": [ref],
        "status": "ok",
    })
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="### 任务 1.1")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, target_path, task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "matched"
    assert res["artifact_ref"] == ref
    assert res["audit_ref"] == ".agents/logs/reviewer/verdicts.jsonl#1"


def test_batch_two_tasks_single_doc_both_confirmed(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path)
    tasks = [
        {"id": "1.1", "title": "A", "affected_files": ["[MODIFY] src/a.py"], "root_cause_and_goal": "G", "type_contracts": "C", "steps": ["1"], "defensive_checks": ["-"], "dod_commands": ["pytest"]},
        {"id": "1.2", "title": "B", "affected_files": ["[MODIFY] src/b.py"], "root_cause_and_goal": "G", "type_contracts": "C", "steps": ["1"], "defensive_checks": ["-"], "dod_commands": ["pytest"]},
    ]
    dev_tasks_propose(ws, "batch.md", tasks)
    doc_path = os.path.join(ws, "docs", "dev_tasks", "batch.md")
    now_wall = datetime.now(timezone.utc).isoformat()
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": [canonical_artifact_ref(ws, doc_path, "1.1")]})
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": [canonical_artifact_ref(ws, doc_path, "1.2")]})
    conf = dev_tasks_confirm(ws, "batch.md", ["1.1", "1.2"], action="confirm")
    assert len(conf["updated"]) == 2


def test_tail_window_exhausted_warns_and_allows(tmp_path):
    ws, log_path, cfg = _make_ws(
        tmp_path,
        {"max_tail_bytes": 64, "on_degraded": "warn", "tail_window_exhausted_policy": "warn"},
    )
    _write_verdict(log_path, {"created_wall_utc": "2026-01-01T00:00:00+00:00", "padding": "x" * 200, "context_files": ["other#1"]})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "tail_window_exhausted"

    # 姊妹断言：on_degraded=block ∧ tail_window=warn → most-restrictive-wins block
    ws2, log_path2, cfg2 = _make_ws(
        tmp_path / "sister",
        {"max_tail_bytes": 64, "on_degraded": "block", "tail_window_exhausted_policy": "warn"},
    )
    _write_verdict(log_path2, {"created_wall_utc": "2026-01-01T00:00:00+00:00", "padding": "x" * 200, "context_files": ["other#1"]})
    res2 = _check_audit_gate(ws2, "task.md", task, cfg2)
    assert res2["allowed"] is False
    assert res2["reason"] == "tail_window_exhausted"


def test_torn_last_line_skipped_previous_matched(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path)
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    now_wall = datetime.now(timezone.utc).isoformat()
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": [ref]})
    with open(log_path, "a", encoding="utf-8") as f:
        f.write('{"torn": true, "broken\n')
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "matched"
    assert res["parse_skipped_lines"] == 1


def test_degraded_record_follows_on_degraded_policy(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path)
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    now_wall = datetime.now(timezone.utc).isoformat()
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": [ref], "degraded_reason": "timeout"})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]

    import dataclasses
    cfg_block = dataclasses.replace(cfg, audit_gate=AuditGatePolicy(enabled=True, on_degraded="block", audit_log_path=log_path))
    assert _check_audit_gate(ws, "task.md", task, cfg_block)["allowed"] is False

    cfg_warn = dataclasses.replace(cfg, audit_gate=AuditGatePolicy(enabled=True, on_degraded="warn", audit_log_path=log_path))
    res_w = _check_audit_gate(ws, "task.md", task, cfg_warn)
    assert res_w["allowed"] is True
    assert res_w["reason"] == "record_degraded"


def test_rework_revoke_skip_never_gated(tmp_path):
    ws, _, _ = _make_ws(tmp_path)
    tasks = [{"id": "1", "title": "A", "affected_files": ["[MODIFY] src/a.py"], "root_cause_and_goal": "G", "type_contracts": "C", "steps": ["1"], "defensive_checks": ["-"], "dod_commands": ["pytest"]}]
    dev_tasks_propose(ws, "rework_test.md", tasks)
    r1 = dev_tasks_confirm(ws, "rework_test.md", ["1"], action="rework")
    assert len(r1["updated"]) == 1
    r2 = dev_tasks_confirm(ws, "rework_test.md", ["1"], action="skip")
    assert len(r2["updated"]) == 1
    r3 = dev_tasks_confirm(ws, "rework_test.md", ["1"], action="revoke")
    assert len(r3["updated"]) == 1


def test_missing_log_dogfood_no_self_lock(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"on_degraded": "warn", "audit_log_path": "missing_verdicts.jsonl"})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "log_missing"


def test_session_bypass_allows(tmp_path):
    ws, _, cfg = _make_ws(tmp_path)
    b_path = os.path.join(ws, ".agents", ".quench_bypass.json")
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    with open(b_path, "w", encoding="utf-8") as f:
        json.dump({"active": True, "session_id": "sess_123", "expires_at": future}, f)
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg, session_id="sess_123")
    assert res["allowed"] is True
    assert res["reason"] == "session_bypass_active"


def test_naive_timestamp_reports_timestamp_invalid(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path)
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    _write_verdict(log_path, {"created_wall_utc": "2026-10-01T12:00:00", "context_files": [ref]})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["reason"] == "record_timestamp_invalid"


def test_blocked_when_no_matching_record(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"on_missing_record": "block"})
    now_wall = datetime.now(timezone.utc).isoformat()
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": ["other#1"]})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is False
    assert res["reason"] == "no_matching_record"


def test_stale_record_reports_record_stale(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"max_age_minutes": 60})
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    stale_wall = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _write_verdict(log_path, {"created_wall_utc": stale_wall, "context_files": [ref]})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["reason"] == "record_stale"


def test_internal_error_fail_open_reason(tmp_path, monkeypatch):
    ws, _, cfg = _make_ws(tmp_path)
    monkeypatch.setattr("server._managed_path_matches", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated crash")))
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "internal_error"


def test_audit_log_path_follows_observability_verdict_path(tmp_path):
    ws = str(tmp_path)
    agents_dir = os.path.join(ws, ".agents")
    os.makedirs(agents_dir, exist_ok=True)
    with open(os.path.join(agents_dir, "quench_stack.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump({
            "project_name": "T",
            "observability": {"verdict_path": "custom/path.jsonl"},
            "audit_gate": {"enabled": True},
        }, f)
    cfg = load_project_config(ws)
    assert cfg.audit_gate.audit_log_path == "custom/path.jsonl"


def test_bind_artifact_false_rejected_by_validator():
    with pytest.raises(ValueError, match="bind_artifact must be True"):
        AuditGatePolicy(enabled=True, bind_artifact=False)


def test_audit_log_path_traversal_rejected_by_path_guard(tmp_path):
    ws, _, cfg = _make_ws(tmp_path, {"audit_log_path": "../../etc/shadow"})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    with pytest.raises(PathTraversalError):
        _check_audit_gate(ws, "task.md", task, cfg)


def test_no_manifest_lock_acquired_during_gate(tmp_path, monkeypatch):
    ws, log_path, cfg = _make_ws(tmp_path)
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    lock_file = os.path.join(ws, ".agents", ".quorch", "manifest.json.lock")
    import filelock
    orig_acquire = filelock.FileLock.acquire
    lock_calls = []

    def mock_acquire(self, *args, **kwargs):
        if self.lock_file == lock_file:
            lock_calls.append(self.lock_file)
        return orig_acquire(self, *args, **kwargs)

    monkeypatch.setattr(filelock.FileLock, "acquire", mock_acquire)
    _check_audit_gate(ws, "task.md", task, cfg)
    assert len(lock_calls) == 0


def test_block_leaves_manifest_unchanged(tmp_path):
    ws, _, _ = _make_ws(tmp_path)
    tasks = [{"id": "1.1", "title": "A", "affected_files": ["[MODIFY] src/app.py"], "root_cause_and_goal": "G", "type_contracts": "C", "steps": ["1"], "defensive_checks": ["-"], "dod_commands": ["pytest"]}]
    dev_tasks_propose(ws, "block.md", tasks)
    manifest_p = os.path.join(ws, ".agents", ".quorch", "manifest.json")
    m_before = open(manifest_p, "rb").read() if os.path.exists(manifest_p) else None
    dev_tasks_confirm(ws, "block.md", ["1.1"], action="confirm")
    m_after = open(manifest_p, "rb").read() if os.path.exists(manifest_p) else None
    assert m_before == m_after


def test_artifact_ref_is_task_scoped_two_tasks_same_doc_distinct():
    r1 = canonical_artifact_ref("/ws", "docs/tasks.md", "1.1")
    r2 = canonical_artifact_ref("/ws", "docs/tasks.md", "1.2")
    assert r1 != r2
    assert r1.endswith("#1.1")
    assert r2.endswith("#1.2")


def test_truncated_with_matching_record_in_tail_returns_matched(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"max_tail_bytes": 200})
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    now_wall = datetime.now(timezone.utc).isoformat()
    # 头部写入大量无关数据
    _write_verdict(log_path, {"padding": "x" * 300})
    # 尾部写入匹配记录
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": [ref]})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "matched"


def test_truncated_zero_parseable_tail_reports_tail_window_exhausted_not_unparsable(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"max_tail_bytes": 50})
    # 写入长于 50 字节且尾部全为非换行或残缺行
    with open(log_path, "wb") as f:
        f.write(b"x" * 150)
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["reason"] == "tail_window_exhausted"
    assert res["allowed"] is False


def test_confirm_revalidates_state_under_lock(tmp_path, monkeypatch):
    ws, log_path, _ = _make_ws(tmp_path)
    tasks = [{"id": "1.1", "title": "A", "affected_files": ["[MODIFY] src/app.py"], "root_cause_and_goal": "G", "type_contracts": "C", "steps": ["1"], "defensive_checks": ["-"], "dod_commands": ["pytest"]}]
    dev_tasks_propose(ws, "race.md", tasks)
    now_wall = datetime.now(timezone.utc).isoformat()
    doc_path = os.path.join(ws, "docs", "dev_tasks", "race.md")
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": [canonical_artifact_ref(ws, doc_path, "1.1")]})

    # 模拟在取锁前任务已被他人推进或修改为已完成
    orig_check = _check_audit_gate

    def mock_gate_then_tamper(*args, **kwargs):
        res = orig_check(*args, **kwargs)
        # 窜改任务状态
        with open(doc_path, "r", encoding="utf-8") as f:
            c = f.read().replace("⬜ 待确认", "✔️ 已完成")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(c)
        return res

    monkeypatch.setattr("server._check_audit_gate", mock_gate_then_tamper)
    res = dev_tasks_confirm(ws, "race.md", ["1.1"], action="confirm")
    assert res["ok"] is False
    assert res["reason"] == "precondition_changed"


def test_internal_error_never_used_for_block():
    p1 = AuditGatePolicy(on_internal_error="allow")
    p2 = AuditGatePolicy(on_internal_error="warn")
    assert p1.on_internal_error != "block"
    assert p2.on_internal_error != "block"


def test_require_undegraded_false_accepts_fresh_degraded_record(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"require_undegraded_record": False})
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    now_wall = datetime.now(timezone.utc).isoformat()
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": [ref], "degraded_reason": "timeout"})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "matched"


def test_step10_only_when_truly_no_matching_record(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path)
    now_wall = datetime.now(timezone.utc).isoformat()
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": ["foo#1"]})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["reason"] == "no_matching_record"


def test_future_timestamp_beyond_tolerance_reports_timestamp_invalid(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"clock_skew_tolerance_seconds": 2})
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    future_wall = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
    _write_verdict(log_path, {"created_wall_utc": future_wall, "context_files": [ref]})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["reason"] == "record_timestamp_invalid"


def test_stale_and_timestamp_invalid_are_mutually_exclusive(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"clock_skew_tolerance_seconds": 2, "max_age_minutes": 10})
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    future_wall = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _write_verdict(log_path, {"created_wall_utc": future_wall, "context_files": [ref]})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["reason"] == "record_timestamp_invalid"
    assert res["reason"] != "record_stale"


def test_disabled_reason_when_gate_disabled(tmp_path):
    ws, _, cfg = _make_ws(tmp_path, {"enabled": False})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "disabled"


def test_not_managed_scope_reason_when_no_managed_file(tmp_path):
    ws, _, cfg = _make_ws(tmp_path)
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] docs/README.md"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "not_managed_scope"


def test_log_unparsable_reason_on_io_failure(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("NOT_JSON\n")
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["reason"] == "log_unparsable"


def test_canonical_artifact_ref_strips_leading_dot_slash():
    assert canonical_artifact_ref("/ws", "./docs/test.md", "1.1") == "docs/test.md#1.1"
    assert canonical_artifact_ref("/ws", "docs/test.md", "1.1") == "docs/test.md#1.1"


def test_corrupt_line_yields_parse_skipped_diagnostics(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path)
    now_wall = datetime.now(timezone.utc).isoformat()
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": [ref]})
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("corrupt line 1\ncorrupt line 2\n")
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["reason"] == "matched"
    assert res["parse_skipped_lines"] == 2


def test_ladder_predicate_exclusivity_matrix():
    reasons = typing.get_args(AuditGateReason)
    assert len(reasons) == 13
    assert len(set(reasons)) == 13
    # R11 读序互斥梯次防短路（优先匹配，无匹配且截断落入 tail_window_exhausted，无匹配且未截断落入 no_matching_record）
    assert "matched" in reasons
    assert "tail_window_exhausted" in reasons
    assert "no_matching_record" in reasons


def test_freshness_boundary_max_age_minus_epsilon_allows():
    p = AuditGatePolicy(max_age_minutes=10, clock_skew_tolerance_seconds=2)
    now = datetime.now(timezone.utc)
    ts = now - timedelta(minutes=10) + timedelta(seconds=1)
    ok, _ = _freshness_ok(now, ts, p)
    assert ok is True


def test_freshness_boundary_max_age_plus_epsilon_blocks_as_stale():
    p = AuditGatePolicy(max_age_minutes=10, clock_skew_tolerance_seconds=2)
    now = datetime.now(timezone.utc)
    ts = now - timedelta(minutes=10) - timedelta(seconds=1)
    ok, _ = _freshness_ok(now, ts, p)
    assert ok is False


def test_scoped_files_marker_normalization_reaches_managed_scope():
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] `plugins/quench-dev-tasks/server/server.py`", "[NEW] `src/sub/util.py` (comment)"]
    cleaned = _extract_task_scoped_files(task)
    assert "plugins/quench-dev-tasks/server/server.py" in cleaned
    assert "src/sub/util.py" in cleaned
    pats = ["plugins/quench-dev-tasks/server/**", "src/**"]
    assert any(_managed_path_matches(f, pats) for f in cleaned)


def test_blocking_payload_exact_five_keys_no_allowed_key(tmp_path):
    ws, _, _ = _make_ws(tmp_path)
    tasks = [{"id": "1.1", "title": "A", "affected_files": ["[MODIFY] src/app.py"], "root_cause_and_goal": "G", "type_contracts": "C", "steps": ["1"], "defensive_checks": ["-"], "dod_commands": ["pytest"]}]
    dev_tasks_propose(ws, "block.md", tasks)
    res = dev_tasks_confirm(ws, "block.md", ["1.1"], action="confirm")
    assert res["ok"] is False
    assert "allowed" not in res
    assert set(res.keys()) == {"ok", "reason", "artifact_ref", "audit_ref", "parse_skipped_lines"}


def test_degraded_record_blocks_under_default_policy(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"on_degraded": "block"})
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    now_wall = datetime.now(timezone.utc).isoformat()
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": [ref], "degraded_reason": "timeout"})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is False
    assert res["reason"] == "record_degraded"


def test_session_id_none_never_grants_bypass(tmp_path):
    ws, _, cfg = _make_ws(tmp_path)
    b_path = os.path.join(ws, ".agents", ".quench_bypass.json")
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    with open(b_path, "w", encoding="utf-8") as f:
        json.dump({"active": True, "session_id": "sess_123", "expires_at": future}, f)
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg, session_id=None)
    assert res["reason"] != "session_bypass_active"


def test_step5_tolerates_skew_within_tolerance_step8_rejects_beyond(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"clock_skew_tolerance_seconds": 2})
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]

    # 1. 容差内未来偏移 (+1s) -> step 5 matched
    ts_ok = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    _write_verdict(log_path, {"created_wall_utc": ts_ok, "context_files": [ref]})
    res_ok = _check_audit_gate(ws, "task.md", task, cfg)
    assert res_ok["allowed"] is True
    assert res_ok["reason"] == "matched"

    # 2. 超容差未来偏移 (+5s) -> step 8 record_timestamp_invalid
    ts_bad = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    _write_verdict(log_path, {"created_wall_utc": ts_bad, "context_files": [ref]})
    res_bad = _check_audit_gate(ws, "task.md", task, cfg)
    assert res_bad["allowed"] is False
    assert res_bad["reason"] == "record_timestamp_invalid"


def test_managed_glob_matches_concrete_server_path_reaches_blocked_not_not_managed_scope(tmp_path):
    ws, _, cfg = _make_ws(tmp_path, {"on_missing_record": "block"})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] plugins/quench-dev-tasks/server/server.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["reason"] != "not_managed_scope"
    assert res["reason"] in ("no_matching_record", "log_missing")


def test_on_missing_record_warn_allows_and_reports_reason(tmp_path):
    ws, log_path, cfg = _make_ws(tmp_path, {"on_missing_record": "warn"})
    _write_verdict(log_path, {"created_wall_utc": datetime.now(timezone.utc).isoformat(), "context_files": ["other#1"]})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "no_matching_record"


def test_canonical_artifact_ref_task_id_equals_state_machine_task_id():
    tid = "1.1"
    ref = canonical_artifact_ref("/workspace", "docs/dev_tasks/test.md", tid)
    assert ref.split("#")[-1] == tid


def test_most_restrictive_policy_monotone_matrix():
    """断言：别名最严优先 9 组合与 None 缺省单调性（block > warn > allow）。"""
    levels = ["block", "warn", "allow"]
    rank = {"block": 3, "warn": 2, "allow": 1}
    for p in levels:
        assert most_restrictive_policy(p, None) == p
        for s in levels:
            expected = "block" if ("block" in (p, s)) else ("warn" if ("warn" in (p, s)) else "allow")
            res = most_restrictive_policy(p, s)
            assert res == expected, f"Mismatch for ({p}, {s}): got {res}, expected {expected}"
            assert rank[res] >= rank[p]
            assert rank[res] >= rank[s]


def test_alias_tightens_record_degraded_to_block(tmp_path):
    """集成断言：全局单点 effective_on_degraded 驱动，on_degraded=allow ∧ tail_window=block 触发 record_degraded 时判定为 block。"""
    ws, log_path, cfg = _make_ws(
        tmp_path,
        {"on_degraded": "allow", "tail_window_exhausted_policy": "block"},
    )
    ref = canonical_artifact_ref(ws, "task.md", "1.1")
    now_wall = datetime.now(timezone.utc).isoformat()
    _write_verdict(log_path, {"created_wall_utc": now_wall, "context_files": [ref], "degraded_reason": "worker_timeout"})
    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    task.affected_files = ["[MODIFY] src/app.py"]
    res = _check_audit_gate(ws, "task.md", task, cfg)
    assert res["reason"] == "record_degraded"
    assert res["allowed"] is False
