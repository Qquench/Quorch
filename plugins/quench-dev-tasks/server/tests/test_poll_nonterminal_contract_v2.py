# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import os
import pytest

from reviewer_jobs import (
    MAX_NONTERMINAL_SNAPSHOT_BYTES,
    POLL_NONTERMINAL_FIELDS,
    POLL_TERMINAL_FIELDS,
    TERMINAL_RESULT_ALLOWED_FIELDS,
    JobState,
    PollSnapshot,
    SnapshotContractViolation,
    _assert_nonterminal_contract,
    canonical_snapshot_bytes,
    project_nonterminal,
)


@pytest.fixture
def sample_snapshot() -> PollSnapshot:
    return PollSnapshot(
        job_id="job_20261022_v2test",
        session_id="session_v2_001",
        state="RUNNING",
        retry_after_seconds=5,
        log_ref="20261022_001_sessionv2001.log",
        elapsed_s=42,
        progress={"phase": "streaming", "approx_reasoning_tokens": 100},
        generation=1,
        phase="streaming",
    )


@pytest.mark.tier1_fast
def test_project_nonterminal_preserves_snapshot_elapsed_s(sample_snapshot):
    """B-2: 只读投射 snap.elapsed_s 至返回字典，不重新计算或修改耗时。"""
    res = project_nonterminal(sample_snapshot)
    assert res["elapsed_s"] == 42
    assert isinstance(res["elapsed_s"], int)


@pytest.mark.tier1_fast
def test_project_nonterminal_six_fields_contract_and_no_progress(sample_snapshot):
    """B-1: 键集合恒等于 6 字段白名单，剥离嵌套 progress 字典，且 progress 严禁在 key 列表中暴露。"""
    res = project_nonterminal(sample_snapshot)
    assert set(res.keys()) == POLL_NONTERMINAL_FIELDS
    assert POLL_NONTERMINAL_FIELDS == frozenset(
        {"job_id", "session_id", "state", "retry_after_seconds", "log_ref", "elapsed_s"}
    )
    assert "progress" not in res.keys()
    assert "progress" in res
    assert res["progress"]["phase"] == "streaming"
    assert res["job_id"] == "job_20261022_v2test"
    assert res["session_id"] == "session_v2_001"
    assert res["state"] == "RUNNING"
    assert res["retry_after_seconds"] == 5
    assert res["log_ref"] == "20261022_001_sessionv2001.log"
    assert res["elapsed_s"] == 42


@pytest.mark.tier1_fast
def test_project_nonterminal_under_1024_bytes_budget(sample_snapshot):
    """1024 字节预算硬防线：瘦身后的 6 字段字典体积应在 ~160B，严格 <= 1024 字节。"""
    res = project_nonterminal(sample_snapshot)
    size_bytes = canonical_snapshot_bytes(res)
    assert size_bytes <= MAX_NONTERMINAL_SNAPSHOT_BYTES
    # 瘦身后体积应大幅缩减（小于 250 字节）
    assert size_bytes < 250


@pytest.mark.tier1_fast
def test_assert_nonterminal_contract_rejects_extra_keys(sample_snapshot):
    """强对称校验：额外注入未知字段硬拦截。"""
    res = dict(project_nonterminal(sample_snapshot))
    res["unexpected_field"] = "malicious"
    with pytest.raises(SnapshotContractViolation) as exc_info:
        _assert_nonterminal_contract(res)
    assert "extra keys" in str(exc_info.value)


@pytest.mark.tier1_fast
def test_assert_nonterminal_contract_rejects_missing_keys(sample_snapshot):
    """强对称校验：缺失必要字段硬拦截。"""
    res = dict(project_nonterminal(sample_snapshot))
    del res["elapsed_s"]
    with pytest.raises(SnapshotContractViolation) as exc_info:
        _assert_nonterminal_contract(res)
    assert "missing keys" in str(exc_info.value)


@pytest.mark.tier1_fast
def test_assert_nonterminal_contract_rejects_absolute_path_log_ref(sample_snapshot):
    """P1-7: 路径防泄漏：绝对路径在三重守卫中被硬拦截。"""
    bad_refs = [
        "/var/log/20261022_001_session.log",
        "C:\\logs\\20261022_001_session.log",
        "D:/work/20261022_001_session.log",
        "subdir/20261022_001_session.log",
    ]
    base = dict(project_nonterminal(sample_snapshot))
    for bad in bad_refs:
        corrupted = {**base, "log_ref": bad}
        with pytest.raises(SnapshotContractViolation) as exc_info:
            _assert_nonterminal_contract(corrupted)
        assert "relative path" in str(exc_info.value)


@pytest.mark.tier1_fast
def test_assert_nonterminal_contract_accepts_relative_path_log_ref(sample_snapshot):
    """相对路径合法 log_ref 正常通过。"""
    res = dict(project_nonterminal(sample_snapshot))
    assert not os.path.isabs(res["log_ref"])
    _assert_nonterminal_contract(res)


@pytest.mark.tier1_fast
def test_assert_nonterminal_contract_budget_overflow_raises(sample_snapshot, monkeypatch):
    """1KB 约束检查，超限抛 SnapshotContractViolation，严禁截断。"""
    res = project_nonterminal(sample_snapshot)
    monkeypatch.setattr(
        "reviewer_jobs.canonical_snapshot_bytes",
        lambda _: 1025,
    )
    with pytest.raises(SnapshotContractViolation) as exc_info:
        _assert_nonterminal_contract(res)
    assert "exceeds 1024 bytes limit" in str(exc_info.value)


@pytest.mark.tier1_fast
def test_snapshot_contract_violation_dual_base_classes():
    """DRIFT-4: 双基类防御：同时继承 RuntimeError 与 AssertionError，保证 python -O 下依然生效。"""
    assert issubclass(SnapshotContractViolation, RuntimeError)
    assert issubclass(SnapshotContractViolation, AssertionError)
    exc = SnapshotContractViolation("contract violation")
    assert isinstance(exc, RuntimeError)
    assert isinstance(exc, AssertionError)


@pytest.mark.tier1_fast
def test_terminal_contract_zero_regression():
    """终态契约红线：POLL_TERMINAL_FIELDS 与 TERMINAL_RESULT_ALLOWED_FIELDS 严格保持不变。"""
    assert POLL_TERMINAL_FIELDS == frozenset(
        {"job_id", "session_id", "state", "log_path", "usage", "result", "degraded_reason"}
    )
    assert "reasoning" not in TERMINAL_RESULT_ALLOWED_FIELDS
    assert "findings" in TERMINAL_RESULT_ALLOWED_FIELDS
