# -*- coding: utf-8 -*-
"""Unit tests for Reviewer Job Supervisor log quota & pin lifecycle (Task 1.1)."""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from log_naming import ActiveLogRegistry, norm_registry_key
from reviewer_jobs import (
    JobProgress,
    JobRecord,
    JobState,
    PIN_RELEASABLE_STATES,
    ReviewerJobSupervisor,
    ReviewerPhase,
    TERMINAL_STATES,
    compute_protected_logs,
)


def test_terminal_states_equals_pin_releasable_states():
    """断言 TERMINAL_STATES == PIN_RELEASABLE_STATES 且排除 CANCELLED_PENDING_REAP。"""
    assert TERMINAL_STATES == PIN_RELEASABLE_STATES
    assert frozenset(
        {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.ORPHANED}
    ) == PIN_RELEASABLE_STATES
    assert JobState.CANCELLED_PENDING_REAP not in PIN_RELEASABLE_STATES


def test_pin_log_and_release_log_pin(tmp_path: Path):
    """测试 Supervisor 的 _pin_log 与 _release_log_pin 幂等闭环。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    log_path = str(tmp_path / "test_sess.log")

    pinned_key = supervisor._pin_log(log_path)
    assert supervisor.registry.is_pinned(log_path) is True
    assert pinned_key == norm_registry_key(log_path)

    # 构造假 JobRecord 测试释放
    rec = JobRecord(
        job_id="job_test_1",
        session_id="sess_1",
        workspace_root=str(tmp_path),
        mode="critique",
        owner_pid=os.getpid(),
        owner_boot_nonce=supervisor.boot_nonce,
        generation=1,
        state=JobState.COMPLETED,
        created_monotonic=time.monotonic(),
        updated_monotonic=time.monotonic(),
        created_wall_utc="2026-10-01T00:00:00Z",
        updated_wall_utc="2026-10-01T00:00:00Z",
        log_path=log_path,
        progress=JobProgress(0.0, 0, ReviewerPhase.ASSEMBLING, 0.0),
        result_ref=None,
    )

    supervisor._release_log_pin(rec)
    assert supervisor.registry.is_pinned(log_path) is False

    # 幂等释放不抛错
    supervisor._release_log_pin(rec)
    supervisor._release_log_pin(None)
    assert supervisor.registry.is_pinned(log_path) is False


def test_submit_pins_log_and_rollback_on_exception(tmp_path: Path):
    """测试 submit 在异常分支下安全回滚 pin。"""
    supervisor = ReviewerJobSupervisor(tmp_path)

    with patch.object(supervisor, "_save_job_record", side_effect=RuntimeError("Disk failure")):
        with pytest.raises(RuntimeError, match="Disk failure"):
            supervisor.submit({"session_id": "sess_err", "query": "q"})

    # 注册表中不应有遗留的孤立 pin
    assert len(supervisor.registry.snapshot()) == 0


def test_submit_idempotent_no_double_pin(tmp_path: Path):
    """测试命中幂等键直接返回既有 record，不二次 pin 也不二次分配。"""
    supervisor = ReviewerJobSupervisor(tmp_path)

    rec1 = supervisor.submit(
        {"session_id": "sess_idem", "query": "q"},
        idempotency_key="fixed_job_id",
    )
    assert rec1.job_id == "fixed_job_id"
    initial_pins = set(supervisor.registry.snapshot())
    assert norm_registry_key(rec1.log_path) in initial_pins

    # 第二次带相同幂等键提交
    rec2 = supervisor.submit(
        {"session_id": "sess_idem", "query": "q_different"},
        idempotency_key="fixed_job_id",
    )
    assert rec2.job_id == "fixed_job_id"
    assert rec2.log_path == rec1.log_path
    # 注册表条目数不翻倍
    assert set(supervisor.registry.snapshot()) == initial_pins


def test_cancelled_pending_reap_does_not_release_pin(tmp_path: Path):
    """断言 CANCELLED_PENDING_REAP 状态下严禁释放 pin。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    log_path = str(tmp_path / "pending_reap.log")
    supervisor._pin_log(log_path)

    rec = JobRecord(
        job_id="job_pending_reap",
        session_id="sess_reap",
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
        log_path=log_path,
        progress=JobProgress(0.0, 0, ReviewerPhase.ASSEMBLING, 0.0),
        result_ref=None,
    )
    supervisor._save_job_record(rec)

    # 模拟终态收尾检查：非 PIN_RELEASABLE_STATES 不得释放
    if rec.state in PIN_RELEASABLE_STATES:
        supervisor._release_log_pin(rec)

    assert supervisor.registry.is_pinned(log_path) is True
