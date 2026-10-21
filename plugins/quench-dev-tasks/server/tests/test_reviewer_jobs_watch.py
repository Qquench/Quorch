# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import asyncio
import builtins
import os
import time
from datetime import datetime, timezone
from typing import Any

import anyio
import pytest
from filelock import FileLock

from reviewer_jobs import (
    JobProgress,
    JobRecord,
    JobState,
    PollSnapshot,
    ReviewerJobSupervisor,
    ReviewerPhase,
    probe_lease_health,
)


def _make_record(
    supervisor: ReviewerJobSupervisor,
    job_id: str = "job_watch_test",
    session_id: str = "sess_watch_test",
    state: JobState = JobState.RUNNING,
    progress: JobProgress | None = None,
    generation: int = 1,
    started_monotonic: float | None = None,
) -> JobRecord:
    now_m = time.monotonic() if started_monotonic is None else started_monotonic
    rec = JobRecord(
        job_id=job_id,
        session_id=session_id,
        workspace_root=supervisor.workspace_root,
        mode="critique",
        owner_pid=os.getpid(),
        owner_boot_nonce=supervisor.boot_nonce,
        generation=generation,
        state=state,
        created_monotonic=now_m,
        updated_monotonic=now_m,
        created_wall_utc=datetime.now(timezone.utc).isoformat(),
        updated_wall_utc=datetime.now(timezone.utc).isoformat(),
        log_path=os.path.join(supervisor.workspace_root, "20261022_001_sesswatchtest.log"),
        progress=progress,
        result_ref=None,
    )
    supervisor._save_job_record(rec)
    return rec


@pytest.mark.tier1_fast
def test_phase_degrades_to_state_when_progress_absent(tmp_path):
    """B-1 / P0-NEW-1: 当 record.progress is None 时，phase 单值降级为 state.value。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = _make_record(supervisor, state=JobState.RUNNING, progress=None)

    snap = supervisor.read_snapshot(rec.job_id)
    assert snap.state == "RUNNING"
    assert snap.phase == "RUNNING"
    assert snap.phase == snap.state


@pytest.mark.tier1_fast
def test_read_snapshot_phase_not_attribute_error_on_none_progress(tmp_path):
    """B-1: 当 record.progress 为 None 时，严禁出现 AttributeError(None.value)。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = _make_record(supervisor, state=JobState.QUEUED, progress=None)

    # 必须成功读取，且 phase 为 'QUEUED'
    snap = supervisor.read_snapshot(rec.job_id)
    assert snap.phase == "QUEUED"
    assert snap.state == "QUEUED"


@pytest.mark.tier1_fast
def test_read_snapshot_elapsed_s_non_negative_with_fake_clock(tmp_path):
    """B-2: 时钟注入与非负耗时闭环：时钟回拨时 elapsed_s 钳制为 0，前行时单调整数计算。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    base_m = 1000.0
    rec = _make_record(supervisor, started_monotonic=base_m)

    # 1. 模拟时钟回拨 (clock < created_monotonic) -> 必须 >= 0
    fake_clock_back = lambda: base_m - 50.0
    snap_back = supervisor.read_snapshot(rec.job_id, clock=fake_clock_back)
    assert snap_back.elapsed_s == 0
    assert isinstance(snap_back.elapsed_s, int)

    # 2. 模拟正常时钟前行 25.8s -> 取整为 25
    fake_clock_forward = lambda: base_m + 25.8
    snap_fwd = supervisor.read_snapshot(rec.job_id, clock=fake_clock_forward)
    assert snap_fwd.elapsed_s == 25
    assert isinstance(snap_fwd.elapsed_s, int)


@pytest.mark.tier1_fast
def test_read_snapshot_with_progress_phase(tmp_path):
    """正常进度时 phase 来自 progress.phase.value。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    prog = JobProgress(
        elapsed_s=12.0,
        approx_reasoning_tokens=300,
        phase=ReviewerPhase.STREAMING,
        idle_s=0.5,
    )
    rec = _make_record(supervisor, state=JobState.RUNNING, progress=prog)

    snap = supervisor.read_snapshot(rec.job_id)
    assert snap.state == "RUNNING"
    assert snap.phase == "streaming"
    assert snap.progress["approx_reasoning_tokens"] == 300


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_watch_short_circuit_on_terminal(tmp_path):
    """短路退出：初始即终态的任务，watch 仅 yield 1 次快照并立即退出。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = _make_record(supervisor, state=JobState.COMPLETED, progress=None)

    snapshots: list[PollSnapshot] = []
    async for snap in supervisor.watch(rec.job_id, deadline_monotonic=time.monotonic() + 5.0):
        snapshots.append(snap)

    assert len(snapshots) == 1
    assert snapshots[0].state == "COMPLETED"


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_watch_exponential_backoff(tmp_path, monkeypatch):
    """W7: 退避翻倍机制：无状态/代际变迁时，等待间隔呈指数级增长至 max_interval_s。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = _make_record(supervisor, state=JobState.RUNNING, progress=None)

    sleep_intervals: list[float] = []
    original_sleep = anyio.sleep

    async def tracking_sleep(seconds: float):
        sleep_intervals.append(seconds)
        if len(sleep_intervals) >= 4:
            # 模拟任务完成以中止 watch
            rec_done = JobRecord(
                **{**rec.__dict__, "state": JobState.COMPLETED, "generation": rec.generation}
            )
            supervisor._save_job_record(rec_done)
        await original_sleep(0.001)

    monkeypatch.setattr(anyio, "sleep", tracking_sleep)

    async for _ in supervisor.watch(
        rec.job_id,
        deadline_monotonic=time.monotonic() + 10.0,
        min_interval_s=0.05,
        max_interval_s=0.4,
    ):
        pass

    # 验证翻倍: 0.05 -> 0.1 -> 0.2 -> 0.4 (capped)
    assert len(sleep_intervals) >= 4
    assert pytest.approx(sleep_intervals[0], abs=1e-3) == 0.05
    assert pytest.approx(sleep_intervals[1], abs=1e-3) == 0.10
    assert pytest.approx(sleep_intervals[2], abs=1e-3) == 0.20
    assert pytest.approx(sleep_intervals[3], abs=1e-3) == 0.40


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_watch_generation_drift_healing(tmp_path, monkeypatch):
    """W7: 代际自愈：发生代际漂移时重置退避并 yield 最新快照，绝不抛出异常。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = _make_record(supervisor, state=JobState.RUNNING, generation=1)

    sleep_count = 0
    original_sleep = anyio.sleep

    async def mutate_sleep(seconds: float):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count == 1:
            # 制造代际漂移 (generation: 1 -> 2)
            bumped = JobRecord(**{**rec.__dict__, "generation": 2})
            supervisor._save_job_record(bumped)
        elif sleep_count >= 2:
            # 终态收尾
            done = JobRecord(**{**rec.__dict__, "generation": 2, "state": JobState.COMPLETED})
            supervisor._save_job_record(done)
        await original_sleep(0.001)

    monkeypatch.setattr(anyio, "sleep", mutate_sleep)

    yielded: list[PollSnapshot] = []
    async for s in supervisor.watch(
        rec.job_id,
        deadline_monotonic=time.monotonic() + 5.0,
        min_interval_s=0.05,
    ):
        yielded.append(s)

    generations = [s.generation for s in yielded]
    assert 1 in generations
    assert 2 in generations
    assert yielded[-1].state == "COMPLETED"


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_watch_liveness_probe_throttling(tmp_path, monkeypatch):
    """W9: 探针节流：probe_lease_health 在轮询中受 liveness_probe_interval_s 节流限制。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = _make_record(supervisor, state=JobState.RUNNING)

    probe_calls = 0
    orig_probe = supervisor.probe_lease_health

    def counted_probe(r: JobRecord) -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return orig_probe(r)

    monkeypatch.setattr(supervisor, "probe_lease_health", counted_probe)

    # 在 0.15s 内触发 3 次轮询，但 probe 节流为 2.0s
    ticks = 0
    original_sleep = anyio.sleep

    async def fast_sleep(seconds: float):
        nonlocal ticks
        ticks += 1
        if ticks >= 3:
            done = JobRecord(**{**rec.__dict__, "state": JobState.COMPLETED})
            supervisor._save_job_record(done)
        await original_sleep(0.001)

    monkeypatch.setattr(anyio, "sleep", fast_sleep)

    async for _ in supervisor.watch(
        rec.job_id,
        deadline_monotonic=time.monotonic() + 5.0,
        min_interval_s=0.01,
        liveness_probe_interval_s=2.0,
    ):
        pass

    # 即使轮询多次，2.0s 窗口内仅探测 1 次
    assert probe_calls == 1


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_watch_zero_disk_write(tmp_path, monkeypatch):
    """W10: 全程零写盘：watch 路径禁止 open(..., 'w'/'a'/'+') 等写盘行为。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = _make_record(supervisor, state=JobState.RUNNING)

    real_open = builtins.open
    write_attempts = []

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(w in mode for w in ("w", "a", "+", "x")):
            write_attempts.append((str(file), mode))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)

    # 运行 2 轮退出
    ticks = 0
    orig_sleep = anyio.sleep

    async def stop_sleep(seconds: float):
        nonlocal ticks
        ticks += 1
        if ticks >= 2:
            done = JobRecord(**{**rec.__dict__, "state": JobState.COMPLETED})
            # 允许在测试注入中写盘，临时恢复
            real_open_call = real_open(supervisor._get_record_path(rec.session_id, rec.job_id), "w", encoding="utf-8")
            with real_open_call as f:
                import json
                from reviewer_jobs import _record_to_dict
                json.dump(_record_to_dict(done), f)
        await orig_sleep(0.001)

    monkeypatch.setattr(anyio, "sleep", stop_sleep)

    async for _ in supervisor.watch(
        rec.job_id,
        deadline_monotonic=time.monotonic() + 5.0,
        min_interval_s=0.01,
    ):
        pass

    # watch 自身读取路径零写盘
    assert len(write_attempts) == 0


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_watch_cancelled_scope_propagates(tmp_path):
    """W8: 取消透传：cancel scope 中止时 CancelledError 自然透传，不被静默吞灭。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = _make_record(supervisor, state=JobState.RUNNING)

    async def watch_worker():
        async for _ in supervisor.watch(
            rec.job_id,
            deadline_monotonic=time.monotonic() + 10.0,
            min_interval_s=0.01,
        ):
            await anyio.sleep(0.01)

    task = asyncio.create_task(watch_worker())
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.concurrent_moat
@pytest.mark.anyio
async def test_watch_zero_lock_during_await(tmp_path, monkeypatch):
    """P1-5 / W6: 零锁跨 await 物理证明：在任意 await 挂起点期间断言 is_locked 为 False。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = _make_record(supervisor, state=JobState.RUNNING)

    active_locks = set()
    orig_acquire = FileLock.acquire
    orig_release = FileLock.release

    def track_acquire(self, *args, **kwargs):
        res = orig_acquire(self, *args, **kwargs)
        active_locks.add(self.lock_file)
        return res

    def track_release(self, *args, **kwargs):
        active_locks.discard(self.lock_file)
        return orig_release(self, *args, **kwargs)

    monkeypatch.setattr(FileLock, "acquire", track_acquire)
    monkeypatch.setattr(FileLock, "release", track_release)

    orig_sleep = anyio.sleep
    ticks = 0

    async def asserting_sleep(seconds: float):
        nonlocal ticks
        ticks += 1
        # ★硬断言★ 在任意 await 挂起期间，FileLock 绝不可处于被持有状态
        assert len(active_locks) == 0, f"Lock held across await point: {active_locks}"
        if ticks >= 3:
            done = JobRecord(**{**rec.__dict__, "state": JobState.COMPLETED})
            supervisor._save_job_record(done)
        await orig_sleep(0.001)

    monkeypatch.setattr(anyio, "sleep", asserting_sleep)

    async for _ in supervisor.watch(
        rec.job_id,
        deadline_monotonic=time.monotonic() + 5.0,
        min_interval_s=0.01,
    ):
        # 在 yield 消费挂起点，锁也必须处于释放状态
        assert len(active_locks) == 0, f"Lock held during yield: {active_locks}"

    assert ticks >= 3
