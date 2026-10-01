# -*- coding: utf-8 -*-
"""Log retention semantics & zero-stat GC tests (Task 1.1)."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from log_naming import (
    REVIEWER_LOG_QUOTA_KEEP,
    REVIEWER_TERMINAL_LOG_RETENTION,
    ActiveLogRegistry,
    enforce_unified_log_quota,
)
from reviewer_jobs import (
    JobProgress,
    JobRecord,
    JobState,
    ReviewerPhase,
    compute_protected_logs,
)


def _create_job_record(
    jobs_dir: Path,
    session_id: str,
    job_id: str,
    log_path: str,
    state: JobState,
) -> None:
    s_dir = jobs_dir / session_id
    s_dir.mkdir(parents=True, exist_ok=True)
    r_path = s_dir / f"{job_id}.record.json"
    now_mono = time.monotonic()
    rec = JobRecord(
        job_id=job_id,
        session_id=session_id,
        workspace_root=str(jobs_dir.parent.parent),
        mode="critique",
        owner_pid=os.getpid(),
        owner_boot_nonce="nonce_test",
        generation=1,
        state=state,
        created_monotonic=now_mono,
        updated_monotonic=now_mono,
        created_wall_utc="2026-10-01T00:00:00Z",
        updated_wall_utc="2026-10-01T00:00:00Z",
        log_path=log_path,
        progress=JobProgress(0.0, 0, ReviewerPhase.ASSEMBLING, 0.0),
        result_ref=None,
    )
    from dataclasses import asdict
    d = asdict(rec)
    d["state"] = rec.state.value
    d["progress"]["phase"] = rec.progress.phase.value
    with open(r_path, "w", encoding="utf-8") as f:
        json.dump(d, f)


def test_compute_protected_logs_semantics(tmp_path: Path):
    """测试 compute_protected_logs:
    1. 按 basename 字典序保留最近 retention 条终态日志;
    2. 全量涵盖非终态在途作业 (QUEUED, RUNNING, CANCELLED_PENDING_REAP);
    3. 排除 latest-* 命名空间。
    """
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True)

    # 1. 创建 10 个终态日志 (按字典序递增)
    terminal_logs = []
    for i in range(1, 11):
        lpath = str(tmp_path / f"20261001_{i:03d}_task.log")
        terminal_logs.append(lpath)
        _create_job_record(jobs_dir, f"sess_{i}", f"job_term_{i}", lpath, JobState.COMPLETED)

    # 2. 创建在途作业 (RUNNING, CANCELLED_PENDING_REAP)
    running_log = str(tmp_path / "20261001_090_running.log")
    _create_job_record(jobs_dir, "sess_run", "job_run", running_log, JobState.RUNNING)

    pending_reap_log = str(tmp_path / "20261001_091_pending_reap.log")
    _create_job_record(
        jobs_dir, "sess_reap", "job_reap", pending_reap_log, JobState.CANCELLED_PENDING_REAP
    )

    # 3. 创建带有 latest-* 命名空间的 record (应被排除)
    latest_log = str(tmp_path / "latest-sess_xyz.log")
    _create_job_record(jobs_dir, "sess_xyz", "job_xyz", latest_log, JobState.COMPLETED)

    # 保留最近 5 条终态 (retention=5)
    protected = compute_protected_logs(str(jobs_dir), retention=5)

    # 最近 5 条终态 (006 ~ 010) 必须受保护
    for p in terminal_logs[5:]:
        assert p in protected
    # 较旧的 5 条终态 (001 ~ 005) 不在终态保护集合内
    for p in terminal_logs[:5]:
        assert p not in protected

    # 在途日志必须受保护
    assert running_log in protected
    assert pending_reap_log in protected

    # latest-* 命名空间被排除
    assert latest_log not in protected


def test_verdicts_jsonl_and_latest_logs_never_deleted(tmp_path: Path):
    """断言 verdicts.jsonl 与 latest-*.log 永远不会被 GC 误删。"""
    log_dir = tmp_path / "reviewer_logs"
    log_dir.mkdir()

    # 特殊文件
    verdicts = log_dir / "verdicts.jsonl"
    verdicts.write_text('{"job_id": "test"}\n', encoding="utf-8")

    latest_ptr = log_dir / "latest.log"
    latest_ptr.write_text("pointer\n", encoding="utf-8")

    latest_session = log_dir / "latest-session_alpha.log"
    latest_session.write_text("cot reasoning\n", encoding="utf-8")

    # 创建 30 个普通新日志文件
    for i in range(1, 31):
        f = log_dir / f"20261001_{i:03d}_task.log"
        f.write_text("content\n", encoding="utf-8")

    reg = ActiveLogRegistry()
    # 执行强制限额清理 keep=10 (超额 20 条普通日志需被回收)
    enforce_unified_log_quota(str(log_dir), keep=10, registry=reg)

    # 断言特殊文件绝对不受损害
    assert verdicts.exists()
    assert latest_ptr.exists()
    assert latest_session.exists()


def test_retention_allows_reading_past_20_submits(tmp_path: Path):
    """断言保留期内 (RETENTION=40 > KEEP=20) 25 次连续提交生成的终态日志全部在保护集中可读。"""
    jobs_dir = tmp_path / "jobs"
    log_dir = tmp_path / "reviewer_logs"
    jobs_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)

    all_logs = []
    for i in range(1, 26):
        lpath = str(log_dir / f"20261001_{i:03d}_task.log")
        Path(lpath).write_text(f"content {i}\n", encoding="utf-8")
        all_logs.append(lpath)
        _create_job_record(jobs_dir, f"sess_{i}", f"job_{i}", lpath, JobState.COMPLETED)

    reg = ActiveLogRegistry()
    protected = compute_protected_logs(str(jobs_dir), retention=REVIEWER_TERMINAL_LOG_RETENTION)

    # 虽然当前有 25 个文件 > KEEP=20，但全部处于 retention=40 保护集中
    enforce_unified_log_quota(
        str(log_dir),
        keep=REVIEWER_LOG_QUOTA_KEEP,
        retention=REVIEWER_TERMINAL_LOG_RETENTION,
        registry=reg,
        protected_paths=protected,
    )

    # 验证全部 25 个文件完好无损，依然可读
    for lpath in all_logs:
        assert Path(lpath).exists()
