# -*- coding: utf-8 -*-
"""Unit tests for Reviewer consultation telemetry sink and audit emission.

Covers assertions (a) through (m) for Phase 1 Epic C:
(a) COMPLETED state writes 1 line jsonl, job_id is '', session_id exact match;
(b1) DEGRADED state -> premises_parsed_count == 0 and is_degraded is True;
(b2) COMPLETED but degraded_reason='timeout' -> premises_parsed_count == 0 and is_degraded is True;
(b3) CANCELLED state with non-empty findings -> premises_parsed_count == 0 and is_degraded is True;
(c) DISABLED mode telemetry_enabled is False: does not write file and sink is not constructed;
(d) filelock.Timeout competition timeout emit does not raise;
(e) enforce_unified_log_quota execution keeps telemetry.jsonl alive;
(f) SUT identity equivalence assert rec.prompt_hash == compute_prompt_hash(messages);
(g) Three lock paths are pairwise distinct;
(h) Three boolean presence 8 combinations coverage;
(i) _get_consultation_telemetry_sink lru_cache keyed by path;
(m) test_telemetry_sink_cache_is_clearable: two calls currsize == 2; reset currsize == 0; maxsize == 32.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from unittest.mock import patch

import filelock
import pytest

from consultation import _emit_consultation_audit
from log_naming import enforce_unified_log_quota
from observability_policy import (
    ConsultationTelemetryRecord,
    FileConsultationTelemetrySink,
    _get_consultation_telemetry_sink,
    make_consultation_telemetry_sink,
    make_verdict_sink,
    reset_consultation_telemetry_sink_cache,
    resolve_observability_policy,
)
from reviewer_engine import compute_prompt_hash


@pytest.fixture(autouse=True)
def clean_telemetry_cache():
    """Ensure cache is reset before and after every test to prevent file lock leaks on Windows."""
    reset_consultation_telemetry_sink_cache()
    yield
    reset_consultation_telemetry_sink_cache()


@pytest.mark.anyio
async def test_completed_state_writes_one_line_jsonl(tmp_path: Path):
    """(a) COMPLETED 状态写 1 行 jsonl，job_id 为 ''，session_id 精确匹配。"""
    latch = threading.Event()
    messages = [{"role": "user", "content": "Review this architecture design."}]
    session_id = "sess_alpha_123"

    await _emit_consultation_audit(
        latch,
        tmp_path,
        session_id=session_id,
        mode="evaluate",
        messages=messages,
        usage={"prompt_tokens": 100, "completion_tokens": 50, "prompt_cache_hit_tokens": 20},
        status="ok",
        degraded_reason=None,
        findings="<<<PREMISES>>>\npremise: p1\nflip_condition: f1\nfalsifiable: true\n<<<END>>>",
        verdict_state="COMPLETED",
    )

    t_file = tmp_path / "consultation_telemetry.jsonl"
    assert t_file.exists(), "Telemetry file must be created"
    lines = t_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    rec = json.loads(lines[0])
    assert rec["session_id"] == session_id
    assert rec["job_id"] == ""
    assert rec["verdict_state"] == "COMPLETED"
    assert rec["is_degraded"] is False
    assert rec["premises_parsed_count"] == 1
    assert rec["schema_version"] == 1


@pytest.mark.anyio
async def test_degraded_state_forces_zero_premises_and_is_degraded(tmp_path: Path):
    """(b1) DEGRADED 状态 -> premises_parsed_count == 0 且 is_degraded is True。"""
    latch = threading.Event()
    findings_with_premises = "<<<PREMISES>>>\npremise: p\nflip_condition: f\nfalsifiable: true\n<<<END>>>"

    await _emit_consultation_audit(
        latch,
        tmp_path,
        session_id="sess_deg_1",
        mode="critique",
        messages=[{"role": "user", "content": "hi"}],
        usage={},
        status="degraded",
        degraded_reason="network",
        findings=findings_with_premises,
        verdict_state="DEGRADED",
    )

    lines = (tmp_path / "consultation_telemetry.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["premises_parsed_count"] == 0
    assert rec["is_degraded"] is True
    assert rec["verdict_state"] == "DEGRADED"


@pytest.mark.anyio
async def test_completed_state_with_degraded_reason_is_degraded(tmp_path: Path):
    """(b2) COMPLETED 但 degraded_reason='timeout' -> premises_parsed_count == 0 且 is_degraded is True。"""
    latch = threading.Event()
    findings_with_premises = "<<<PREMISES>>>\npremise: p\nflip_condition: f\nfalsifiable: true\n<<<END>>>"

    await _emit_consultation_audit(
        latch,
        tmp_path,
        session_id="sess_deg_2",
        mode="evaluate",
        messages=[{"role": "user", "content": "hi"}],
        usage={},
        status="degraded",
        degraded_reason="timeout",
        findings=findings_with_premises,
        verdict_state="COMPLETED",
    )

    lines = (tmp_path / "consultation_telemetry.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["premises_parsed_count"] == 0
    assert rec["is_degraded"] is True


@pytest.mark.anyio
async def test_cancelled_state_with_findings_forces_zero_premises(tmp_path: Path):
    """(b3) CANCELLED 状态且非空 findings -> premises_parsed_count == 0 且 is_degraded is True。"""
    latch = threading.Event()
    findings_with_premises = "<<<PREMISES>>>\npremise: p\nflip_condition: f\nfalsifiable: true\n<<<END>>>"

    await _emit_consultation_audit(
        latch,
        tmp_path,
        session_id="sess_canc_1",
        mode="evaluate",
        messages=[{"role": "user", "content": "hi"}],
        usage={},
        status="cancelled",
        degraded_reason=None,
        findings=findings_with_premises,
        verdict_state="CANCELLED",
    )

    lines = (tmp_path / "consultation_telemetry.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["premises_parsed_count"] == 0
    assert rec["is_degraded"] is True
    assert rec["verdict_state"] == "CANCELLED"


@pytest.mark.anyio
async def test_disabled_mode_does_not_write_telemetry_or_construct_sink(tmp_path: Path):
    """(c) DISABLED 模式 telemetry_enabled is False 不写文件且 sink 未被构造。"""
    v_path = str(tmp_path / "verdicts.jsonl")
    dec = resolve_observability_policy("disabled", verdict_path=v_path)
    assert dec.telemetry_enabled is False

    latch = threading.Event()
    with patch("observability_policy._get_consultation_telemetry_sink") as mock_get_sink:
        await _emit_consultation_audit(
            latch,
            tmp_path,
            session_id="sess_dis_1",
            mode="evaluate",
            messages=[{"role": "user", "content": "hi"}],
            usage={},
            status="ok",
            telemetry_enabled=dec.telemetry_enabled,
        )
        mock_get_sink.assert_not_called()

    t_file = tmp_path / "consultation_telemetry.jsonl"
    assert not t_file.exists()


def test_filelock_timeout_emit_does_not_raise(tmp_path: Path):
    """(d) filelock.Timeout 竞争超时 emit 不抛异常。"""
    t_file = tmp_path / "telemetry.jsonl"
    sink = FileConsultationTelemetrySink(str(t_file))

    rec = ConsultationTelemetryRecord(
        ts="2026-11-02T00:00:00Z",
        workspace_root=str(tmp_path),
        job_id="j1",
        session_id="s1",
        prompt_hash="h1",
        prompt_chars=10,
        observations_present=False,
        hypotheses_present=False,
        need_files_present=False,
        premises_parsed_count=0,
        verdict_state="COMPLETED",
        is_degraded=False,
    )

    with patch.object(sink._lock, "acquire", side_effect=filelock.Timeout("mock timeout")):
        # 必须静默 fail-open，绝不向外抛异常
        sink.emit_telemetry(rec)


def test_enforce_unified_log_quota_keeps_telemetry_alive(tmp_path: Path):
    """(e) enforce_unified_log_quota 执行后 telemetry.jsonl 保持存活。"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 创建 15 个 .log 文件，超出 keep=5 的配额
    for i in range(15):
        (log_dir / f"20261102_{i:03d}_sess.log").write_text(f"log {i}\n", encoding="utf-8")

    # 创建 consultation_telemetry.jsonl
    telemetry_file = log_dir / "consultation_telemetry.jsonl"
    telemetry_file.write_text('{"ts": "2026-11-02", "schema_version": 1}\n', encoding="utf-8")

    # 执行配额回收
    enforce_unified_log_quota(str(log_dir), keep=5)

    # 验证 telemetry.jsonl 完好存活（GC 仅枚举 *.log 并排除 *.jsonl）
    assert telemetry_file.exists(), "consultation_telemetry.jsonl must survive GC quota prune"


@pytest.mark.anyio
async def test_sut_identity_equivalence_prompt_hash(tmp_path: Path):
    """(f) SUT 身份等价断言 rec.prompt_hash == compute_prompt_hash(messages)。"""
    messages = [
        {"role": "system", "content": "You are an architecture reviewer."},
        {"role": "user", "content": "Analyze memory allocation in queue worker."},
    ]
    expected_hash = compute_prompt_hash(messages)

    latch = threading.Event()
    await _emit_consultation_audit(
        latch,
        tmp_path,
        session_id="sess_hash_check",
        mode="critique",
        messages=messages,
        usage={},
        status="ok",
    )

    lines = (tmp_path / "consultation_telemetry.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["prompt_hash"] == expected_hash


def test_three_locks_paths_distinct(tmp_path: Path):
    """(g) 三锁路径两两不等。"""
    v_path = str(tmp_path / "verdicts.jsonl")
    t_path = str(tmp_path / "telemetry" / "consultation_telemetry.jsonl")
    c_lock = str(tmp_path / "cache_telemetry.jsonl.lock")

    v_sink = make_verdict_sink(v_path)
    t_sink = make_consultation_telemetry_sink(t_path)

    v_lock = v_sink.lock_path
    t_lock = t_sink.lock_path

    assert v_lock != t_lock, "Verdict lock and telemetry lock must be distinct"
    assert v_lock != c_lock, "Verdict lock and cache lock must be distinct"
    assert t_lock != c_lock, "Telemetry lock and cache lock must be distinct"


@pytest.mark.anyio
@pytest.mark.parametrize("obs", [False, True])
@pytest.mark.parametrize("hypo", [False, True])
@pytest.mark.parametrize("need", [False, True])
async def test_three_boolean_presence_eight_combinations(tmp_path: Path, obs: bool, hypo: bool, need: bool):
    """(h) 三布尔 presence 8 组组合覆盖。"""
    latch = threading.Event()
    sess_id = f"sess_{int(obs)}_{int(hypo)}_{int(need)}"

    await _emit_consultation_audit(
        latch,
        tmp_path,
        session_id=sess_id,
        mode="evaluate",
        messages=[{"role": "user", "content": "hi"}],
        usage={},
        status="ok",
        observations_present=obs,
        hypotheses_present=hypo,
        need_files_present=need,
    )

    t_file = tmp_path / "consultation_telemetry.jsonl"
    lines = t_file.read_text(encoding="utf-8").strip().splitlines()
    rec = json.loads(lines[-1])

    assert rec["observations_present"] is obs
    assert rec["hypotheses_present"] is hypo
    assert rec["need_files_present"] is need


def test_get_consultation_telemetry_sink_lru_cache_keyed_by_path(tmp_path: Path):
    """(i) _get_consultation_telemetry_sink lru_cache 按 path 分键。"""
    path_a = str(tmp_path / "dir_a" / "telemetry.jsonl")
    path_b = str(tmp_path / "dir_b" / "telemetry.jsonl")

    s1 = _get_consultation_telemetry_sink(path_a)
    s2 = _get_consultation_telemetry_sink(path_a)
    s3 = _get_consultation_telemetry_sink(path_b)

    assert s1 is s2, "Same path must return cached singleton"
    assert s1 is not s3, "Different paths must return distinct instances"
    assert s1.path == os.path.abspath(path_a)
    assert s3.path == os.path.abspath(path_b)


def test_telemetry_sink_cache_is_clearable(tmp_path: Path):
    """(m) test_telemetry_sink_cache_is_clearable：两次以不同 tmp_path 调用工厂后 currsize == 2；调用 reset_consultation_telemetry_sink_cache() 后 currsize == 0；cache_info().maxsize == 32。"""
    p1 = str(tmp_path / "p1" / "t.jsonl")
    p2 = str(tmp_path / "p2" / "t.jsonl")

    reset_consultation_telemetry_sink_cache()
    assert _get_consultation_telemetry_sink.cache_info().currsize == 0

    _get_consultation_telemetry_sink(p1)
    _get_consultation_telemetry_sink(p2)

    info = _get_consultation_telemetry_sink.cache_info()
    assert info.currsize == 2
    assert info.maxsize == 32

    reset_consultation_telemetry_sink_cache()
    info_after = _get_consultation_telemetry_sink.cache_info()
    assert info_after.currsize == 0
    assert info_after.maxsize == 32

