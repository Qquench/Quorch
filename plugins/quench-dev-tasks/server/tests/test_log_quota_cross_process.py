# -*- coding: utf-8 -*-
"""Cross-process liveness probe & registry reap tests (Task 1.1)."""

import json
import os
import threading
import time
from pathlib import Path

import pytest

from log_naming import ActiveLogRegistry, enforce_unified_log_quota, norm_registry_key
from reviewer_jobs import (
    JobProgress,
    JobRecord,
    JobState,
    ReviewerPhase,
    build_peer_liveness_probe,
    compute_protected_logs,
)


def _create_mock_job_record(
    jobs_dir: Path,
    session_id: str,
    job_id: str,
    log_path: str,
    state: JobState,
    owner_pid: int,
    owner_boot_nonce: str,
) -> None:
    s_dir = jobs_dir / session_id
    s_dir.mkdir(parents=True, exist_ok=True)
    r_path = s_dir / f"{job_id}.record.json"
    now_mono = time.monotonic()
    now_wall = "2026-10-01T00:00:00Z"
    rec = JobRecord(
        job_id=job_id,
        session_id=session_id,
        workspace_root=str(jobs_dir.parent.parent.parent.parent),
        mode="critique",
        owner_pid=owner_pid,
        owner_boot_nonce=owner_boot_nonce,
        generation=1,
        state=state,
        created_monotonic=now_mono,
        updated_monotonic=now_mono,
        created_wall_utc=now_wall,
        updated_wall_utc=now_wall,
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


def test_build_peer_liveness_probe_alive_and_dead(tmp_path: Path):
    """测试 build_peer_liveness_probe 对真实存活与死亡进程的准确判别。"""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True)
    ws_root = str(tmp_path)

    alive_log = str(tmp_path / "alive.log")
    dead_log = str(tmp_path / "dead.log")
    unknown_log = str(tmp_path / "unknown.log")

    # 当前进程 PID (存活)
    _create_mock_job_record(
        jobs_dir, "s1", "j1", alive_log, JobState.RUNNING, os.getpid(), "nonce_alive"
    )
    # 不可能存在的超大 PID (死亡)
    _create_mock_job_record(
        jobs_dir, "s2", "j2", dead_log, JobState.RUNNING, 9999999, "nonce_dead"
    )

    probe = build_peer_liveness_probe(str(jobs_dir), ws_root)

    # 1. 存活进程在途 -> True
    assert probe(alive_log) is True

    # 2. 死亡进程在途 -> False
    assert probe(dead_log) is False

    # 3. 无对应 record (fail-safe 默认存活) -> True
    assert probe(unknown_log) is True


def test_reap_dead_lock_order_and_concurrency():
    """断言 ActiveLogRegistry.reap_dead 锁内快照 + 锁外探测 + 锁内差分写回，杜绝锁内阻塞。"""
    reg = ActiveLogRegistry()
    reg.pin("key1")
    reg.pin("key2")
    reg.pin("key3")

    probe_started = threading.Event()
    probe_continue = threading.Event()

    def slow_probe(k: str) -> bool:
        if k == norm_registry_key("key2"):
            probe_started.set()
            probe_continue.wait(timeout=2.0)
            return False  # key2 死亡
        return True

    def runner():
        reg.reap_dead(slow_probe)

    t = threading.Thread(target=runner)
    t.start()

    assert probe_started.wait(timeout=1.0) is True

    # 关键断言：探测期间锁已释放，主线程可自由并发查询与加锁
    assert reg.is_pinned("key1") is True
    reg.pin("key4")
    assert reg.is_pinned("key4") is True

    # 允许探针继续
    probe_continue.set()
    t.join(timeout=2.0)

    # key2 被移除，其余正常保留
    assert reg.is_pinned("key1") is True
    assert reg.is_pinned("key2") is False
    assert reg.is_pinned("key3") is True
    assert reg.is_pinned("key4") is True
