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


def test_submit_opportunistic_gc_expired_terminal_jobs_and_cleans_empty_dir(tmp_path: Path):
    """验证超 max_age_s 的历史终态作业在下次 submit() 时被自动机会式 GC 且空会话目录被清理，同时不再阻塞超额 .log 文件裁剪。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    old_sess = "sess_expired"
    old_sess_dir = supervisor._get_session_dir(old_sess)
    (old_sess_dir / "results").mkdir(exist_ok=True)

    old_log_path = str(tmp_path / "logs" / f"reviewer_{old_sess}_old_job.log")
    Path(old_log_path).parent.mkdir(parents=True, exist_ok=True)
    Path(old_log_path).write_text("old log", encoding="utf-8")

    rec_old = JobRecord(
        job_id="job_expired",
        session_id=old_sess,
        workspace_root=str(tmp_path),
        mode="critique",
        owner_pid=os.getpid(),
        owner_boot_nonce=supervisor.boot_nonce,
        generation=1,
        state=JobState.COMPLETED,
        created_monotonic=time.monotonic() - 4000.0,
        updated_monotonic=time.monotonic() - 3900.0,
        created_wall_utc="2026-10-01T00:00:00Z",
        updated_wall_utc="2026-10-01T00:00:00Z",
        log_path=old_log_path,
        progress=JobProgress(1.0, 100, ReviewerPhase.FINALIZING, 10.0),
        result_ref=str(old_sess_dir / "results" / "job_expired.result.json"),
    )
    supervisor._save_job_record(rec_old)
    Path(rec_old.result_ref).write_text("{}", encoding="utf-8")
    (old_sess_dir / "job_expired.record.lock").write_text("", encoding="utf-8")

    r_file = supervisor._get_record_path(old_sess, rec_old.job_id)
    assert r_file.is_file()
    old_time = time.time() - 3600.0
    os.utime(r_file, (old_time, old_time))

    supervisor.submit({"session_id": "sess_active", "query": "hello"})

    assert not r_file.exists()
    assert not old_sess_dir.exists()


def test_gc_terminal_jobs_prunes_excess_retains_recent_and_preserves_active(tmp_path: Path):
    """未超 max_age_s 的近期终态作业在 max_records 以内保留完好；跨会话超出 max_records 时仅保留最新 max_records 条终态记录且活跃非终态作业绝不被误删。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    now = time.time()

    active_dir = supervisor._get_session_dir("sess_active")
    rec_active = JobRecord(
        job_id="job_active_1",
        session_id="sess_active",
        workspace_root=str(tmp_path),
        mode="critique",
        owner_pid=os.getpid(),
        owner_boot_nonce=supervisor.boot_nonce,
        generation=1,
        state=JobState.RUNNING,
        created_monotonic=time.monotonic(),
        updated_monotonic=time.monotonic(),
        created_wall_utc="2026-10-01T00:00:00Z",
        updated_wall_utc="2026-10-01T00:00:00Z",
        log_path=str(tmp_path / "active.log"),
        progress=JobProgress(0.5, 50, ReviewerPhase.STREAMING, 5.0),
        result_ref=None,
    )
    supervisor._save_job_record(rec_active)

    terminal_ids = []
    for i in range(5):
        s_id = f"sess_{i % 2}"
        j_id = f"job_term_{i}"
        s_dir = supervisor._get_session_dir(s_id)
        rec = JobRecord(
            job_id=j_id,
            session_id=s_id,
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
            log_path=str(tmp_path / f"{j_id}.log"),
            progress=JobProgress(1.0, 100, ReviewerPhase.FINALIZING, 1.0),
            result_ref=None,
        )
        supervisor._save_job_record(rec)
        rf = supervisor._get_record_path(s_id, j_id)
        os.utime(rf, (now - (100 - i * 10), now - (100 - i * 10)))
        terminal_ids.append((s_id, j_id))

    reaped = supervisor.gc_terminal_jobs(max_records=10, max_age_s=1800.0)
    assert reaped == 0
    for s_id, j_id in terminal_ids:
        assert supervisor._get_record_path(s_id, j_id).is_file()

    reaped_excess = supervisor.gc_terminal_jobs(max_records=2, max_age_s=1800.0)
    assert reaped_excess == 3

    assert not supervisor._get_record_path("sess_0", "job_term_0").exists()
    assert not supervisor._get_record_path("sess_1", "job_term_1").exists()
    assert not supervisor._get_record_path("sess_0", "job_term_2").exists()
    assert supervisor._get_record_path("sess_1", "job_term_3").is_file()
    assert supervisor._get_record_path("sess_0", "job_term_4").is_file()

    assert supervisor._get_record_path("sess_active", "job_active_1").is_file()


