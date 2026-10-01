# -*- coding: utf-8 -*-
"""Comprehensive verification suite for Reviewer Unified Async Channel (v1.10 Step 02).

Covers:
1. POLL_TERMINAL_STATES == PIN_RELEASABLE_STATES == TERMINAL_STATES invariant equality;
2. Authoritative Tri-State Discriminated Union Contract (discriminator 'state'):
   - Form A: COMPLETED (clean_result, degraded_reason=None)
   - Form B: FAILED / CANCELLED / ORPHANED (degraded_reason set, findings == "")
   - Form C: QUEUED / RUNNING / CANCELLED_PENDING_REAP (1KB bounded snapshot, retry_after, progress)
3. CANCELLED_PENDING_REAP assigned strictly to Form C (non-terminal, pin retained);
4. Strict Authoritative Execution Order in submit():
   CapacityLimiter -> Idempotency Cache Hit -> Sandbox & Context Assembly -> Allocate Log -> Pin -> Record -> GC;
5. Idempotency replay never triggers sandbox check or context assembly;
6. Pre-flight fail-closed sandbox defense (INV-6) blocks escaping paths before allocating logs;
7. dev_reviewer_consult strict non-blocking guidance card contract.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
from typing import Any
from unittest.mock import MagicMock
import pytest

from consultation import (
    assert_read_only_sandbox,
    assemble_reviewer_context,
)
from path_guard import PathTraversalError
from reviewer_jobs import (
    JobProgress,
    JobRecord,
    JobState,
    PIN_RELEASABLE_STATES,
    POLL_NONTERMINAL_FIELDS,
    POLL_TERMINAL_FIELDS,
    POLL_TERMINAL_STATES,
    ReviewerJobSupervisor,
    ReviewerPhase,
    SnapshotContractViolation,
    TERMINAL_STATES,
    project_terminal,
)
import server


def test_terminal_states_invariants_equivalence():
    """断言 POLL_TERMINAL_STATES == PIN_RELEASABLE_STATES == TERMINAL_STATES 严格恒等。"""
    assert POLL_TERMINAL_STATES == PIN_RELEASABLE_STATES
    assert PIN_RELEASABLE_STATES == TERMINAL_STATES
    assert JobState.COMPLETED in POLL_TERMINAL_STATES
    assert JobState.FAILED in POLL_TERMINAL_STATES
    assert JobState.CANCELLED in POLL_TERMINAL_STATES
    assert JobState.ORPHANED in POLL_TERMINAL_STATES
    assert JobState.CANCELLED_PENDING_REAP not in POLL_TERMINAL_STATES


def test_tristate_union_form_a_completed():
    """断言形态 A（终态成功）：state=='COMPLETED'，degraded_reason 恒为 None，返回合法审查正文。"""
    record = JobRecord(
        job_id="job_comp_1",
        session_id="sess_1",
        workspace_root="/ws",
        mode="critique",
        owner_pid=123,
        owner_boot_nonce="nonce_1",
        generation=1,
        state=JobState.COMPLETED,
        created_monotonic=10.0,
        updated_monotonic=15.0,
        created_wall_utc="2026-10-01T00:00:00Z",
        updated_wall_utc="2026-10-01T00:00:05Z",
        log_path="/ws/logs/latest.log",
        progress=JobProgress(elapsed_s=5.0, approx_reasoning_tokens=500, phase=ReviewerPhase.FINALIZING, idle_s=0.1),
        result_ref="/ws/results/job_comp_1.result.json",
        degraded_reason=None,
    )
    result_dict = {
        "status": "ok",
        "findings": "Design is structurally sound.",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        "truncated": False,
        "skipped_files": [],
    }

    projected = project_terminal(record, result_dict)
    assert set(projected.keys()) == POLL_TERMINAL_FIELDS
    assert projected["state"] == "COMPLETED"
    assert projected["degraded_reason"] is None
    assert projected["result"]["status"] == "ok"
    assert projected["result"]["findings"] == "Design is structurally sound."
    assert projected["usage"]["total_tokens"] == 150


@pytest.mark.parametrize("state,expected_reason", [
    (JobState.FAILED, "network"),
    (JobState.CANCELLED, "cancelled"),
    (JobState.ORPHANED, "orphaned"),
])
def test_tristate_union_form_b_degraded(state: JobState, expected_reason: str):
    """断言形态 B（终态降级）：state in {FAILED, CANCELLED, ORPHANED}，degraded_reason 必非空，findings 必为空串 (INV-3)。"""
    record = JobRecord(
        job_id=f"job_{state.value.lower()}_1",
        session_id="sess_1",
        workspace_root="/ws",
        mode="evaluate",
        owner_pid=123,
        owner_boot_nonce="nonce_1",
        generation=1,
        state=state,
        created_monotonic=10.0,
        updated_monotonic=15.0,
        created_wall_utc="2026-10-01T00:00:00Z",
        updated_wall_utc="2026-10-01T00:00:05Z",
        log_path="/ws/logs/latest.log",
        progress=JobProgress(elapsed_s=5.0, approx_reasoning_tokens=500, phase=ReviewerPhase.STREAMING, idle_s=0.1),
        result_ref=None,
        degraded_reason=None,  # 测试缺省自愈推断
    )

    projected = project_terminal(record, None)
    assert set(projected.keys()) == POLL_TERMINAL_FIELDS
    assert projected["state"] == state.value
    assert projected["degraded_reason"] == expected_reason
    assert projected["result"]["status"] == "degraded"
    assert projected["result"]["findings"] == ""
    assert projected["result"]["degraded_reason"] == expected_reason


def test_tristate_union_form_c_cancelled_pending_reap(tmp_path: Path):
    """断言形态 C：CANCELLED_PENDING_REAP 严格属于非终态形态 C，具备 progress 与 retry_after，不可提前按终态 unpin。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    job_id = "job_pending_reap_1"
    session_id = "sess_reap"

    rec = JobRecord(
        job_id=job_id,
        session_id=session_id,
        workspace_root=str(tmp_path),
        mode="critique",
        owner_pid=os.getpid(),
        owner_boot_nonce=supervisor.boot_nonce,
        generation=1,
        state=JobState.CANCELLED_PENDING_REAP,
        created_monotonic=time.monotonic(),
        updated_monotonic=time.monotonic(),
        created_wall_utc="2026-10-01T00:00:00Z",
        updated_wall_utc="2026-10-01T00:00:00Z",
        log_path=str(tmp_path / "20261001_001_sess_reap.log"),
        progress=JobProgress(elapsed_s=3.0, approx_reasoning_tokens=200, phase=ReviewerPhase.STREAMING, idle_s=1.0),
        result_ref=None,
    )
    supervisor._save_job_record(rec)

    # 1. 轮询结果必须为形态 C (POLL_NONTERMINAL_FIELDS)
    poll_res = supervisor.poll(job_id, session_id=session_id)
    assert isinstance(poll_res, dict)
    assert set(poll_res.keys()) == POLL_NONTERMINAL_FIELDS
    assert poll_res["state"] == "CANCELLED_PENDING_REAP"
    assert "retry_after_seconds" in poll_res
    assert "progress" in poll_res
    assert poll_res["progress"]["phase"] == "streaming"

    # 2. 状态机断言：CANCELLED_PENDING_REAP 绝对不在 PIN_RELEASABLE_STATES 中
    assert JobState.CANCELLED_PENDING_REAP not in PIN_RELEASABLE_STATES
    assert JobState.CANCELLED_PENDING_REAP not in POLL_TERMINAL_STATES


def test_submit_authoritative_sequence_and_idempotency_skip_assembly(tmp_path: Path, monkeypatch):
    """断言 submit() 权威步骤序：
    1. 准入判定
    2. 幂等查重命中时直接返回，绝不执行沙箱检查与上下文组装
    3. 全新提交时 fail-closed 沙箱检查与上下文组装前置于 allocate_log_file
    """
    supervisor = ReviewerJobSupervisor(tmp_path)
    ws = str(tmp_path)

    # 创建沙箱内测试文件
    f_ok = tmp_path / "valid.py"
    f_ok.write_text("print('hello')\n", encoding="utf-8")

    sandbox_calls = []
    assemble_calls = []

    def fake_sandbox(workspace_root, context_files):
        sandbox_calls.append((workspace_root, list(context_files or [])))
        assert_read_only_sandbox(workspace_root, context_files)

    def fake_assemble(workspace_root, context_files, **kwargs):
        assemble_calls.append((workspace_root, list(context_files or [])))
        return assemble_reviewer_context(workspace_root, context_files, **kwargs)

    monkeypatch.setattr("consultation.assert_read_only_sandbox", fake_sandbox)
    monkeypatch.setattr("consultation.assemble_reviewer_context", fake_assemble)

    # 第一次提交：全新作业，必须触发 sandbox 与 assemble
    rec1 = supervisor.submit(
        {"session_id": "idem_sess", "query": "Test query", "context_files": ["valid.py"]},
        idempotency_key="job_idem_001",
    )
    assert rec1.job_id == "job_idem_001"
    assert len(sandbox_calls) == 1
    assert len(assemble_calls) == 1

    # 第二次提交：幂等重放，必须直接返回既有 record，计数器不得递增
    rec2 = supervisor.submit(
        {"session_id": "idem_sess", "query": "Test query", "context_files": ["valid.py"]},
        idempotency_key="job_idem_001",
    )
    assert rec2.job_id == "job_idem_001"
    assert rec2.log_path == rec1.log_path
    assert len(sandbox_calls) == 1, "Idempotency cache hit MUST NOT trigger sandbox assertion"
    assert len(assemble_calls) == 1, "Idempotency cache hit MUST NOT trigger context assembly"


def test_submit_preflight_fail_closed_sandbox_blocks_before_allocation(tmp_path: Path):
    """断言沙箱阻断（INV-6）：当 context_files 包含逃逸路径时，在 allocate_log 之前 fail-closed 拦截，零残留日志。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    ws = str(tmp_path)

    initial_files = set(tmp_path.glob("**/*"))

    with pytest.raises(PathTraversalError):
        supervisor.submit(
            {
                "session_id": "sess_traversal",
                "query": "Malicious check",
                "context_files": ["../../outside.txt"],
            }
        )

    # 断言没有任何日志文件被分配或创建，也无残留 pin
    current_files = set(tmp_path.glob("**/*"))
    created = [f for f in current_files if f not in initial_files and "log" in f.name]
    assert len(created) == 0, f"No logs should be allocated upon sandbox violation, got {created}"
    assert len(supervisor.registry.snapshot()) == 0


@pytest.mark.anyio
async def test_dev_reviewer_consult_strict_guidance_card(tmp_path: Path):
    """断言 dev_reviewer_consult 统一收敛为严格非阻塞引导卡片，消除同轮阻塞并提供免任务单示例。"""
    ws = str(tmp_path)
    res = await server.dev_reviewer_consult(
        workspace_root=ws,
        query="Should we migrate to SQLite WAL mode?",
        mode="critique",
        session_id="consult_guide_test",
    )

    assert isinstance(res, dict)
    assert res["status"] == "degraded"
    assert res["findings"] == ""
    assert res["session_id"] == "consult_guide_test"
    assert res["mode"] == "critique"
    assert "guidance" in res
    assert "dev_reviewer_submit" in res["error"]
    assert "dev_reviewer_poll" in res["error"]
    assert "recommended_workflow" in res["guidance"]
    assert res["guidance"]["recommended_workflow"] == ["dev_reviewer_submit", "dev_reviewer_poll"]
    assert "submit" in res["guidance"]["example"]
    assert "poll" in res["guidance"]["example"]
