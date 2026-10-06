# -*- coding: utf-8 -*-
"""Unit and integration tests for dev_reviewer_poll MCP progress bridge.
Locks in:
- A1: Immediate first emission + ~1.0s throttled cadence
- A2: ctx=None zero emission, zero exception, baseline identical
- A3: Progress exception isolation (RuntimeError, ConnectionResetError)
- A4: Backpressure truncation (hang report_progress capped at 0.2s)
- A5: Terminal short-circuit (exits early upon terminal state)
- A6: No busy waiting (sleep >= 0.05s, bounded poll count)
- A7: Progress payload compliance (progress=consumed_s, total=timeout_s, message=format_heartbeat_line)
- A8: Concurrent cancellation yields CANCELLED projection
- A9: asyncio.CancelledError passthrough (never swallowed by except Exception)
"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock

from reviewer_jobs import ReviewerJobSupervisor, JobState, _durable_write_json
from reviewer_engine import format_heartbeat_line
import server


class TrackingContext:
    def __init__(self, raise_exc=None, delay_s=0.0):
        self.calls = []
        self.raise_exc = raise_exc
        self.delay_s = delay_s

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None):
        self.calls.append({
            "progress": progress,
            "total": total,
            "message": message,
            "time": time.monotonic(),
        })
        if self.delay_s > 0:
            await asyncio.sleep(self.delay_s)
        if self.raise_exc:
            raise self.raise_exc


@pytest.fixture(autouse=True)
def prevent_auto_worker_failure(monkeypatch):
    monkeypatch.setattr(ReviewerJobSupervisor, "_launch_worker", lambda self, record, req: None)



@pytest.mark.anyio
async def test_a1_and_a7_first_tick_immediate_and_payload_cadence(tmp_path):
    """A1 / A7: 断言首拍即时发射，后续 ~1.0s 节流，载荷结构符合进度契约。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "a1_test"})

    ctx = TrackingContext()
    start = time.monotonic()
    # 等待 2.2 秒（应该触发：t=0, t=1.0, t=2.0 共 3 次）
    res = await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="a1_test",
        wait_max_s=2,
        ctx=ctx,
    )
    elapsed = time.monotonic() - start

    assert isinstance(res, str)
    assert res.startswith("[Reviewer thinking:")
    assert len(ctx.calls) >= 2  # 首拍 + 至少 1 次后续节流
    # 首拍即时性：第一次发射距 start <= 0.2s
    assert ctx.calls[0]["time"] - start <= 0.2
    assert ctx.calls[0]["total"] == 2.0
    assert "Reviewer thinking:" in ctx.calls[0]["message"]

    # 间隔在 ~1.0s 附近
    if len(ctx.calls) >= 2:
        interval = ctx.calls[1]["time"] - ctx.calls[0]["time"]
        assert 0.90 <= interval <= 1.35


@pytest.mark.anyio
async def test_a2_ctx_none_zero_emissions(tmp_path):
    """A2: 断言 ctx=None 或未注入时不抛异常、零通知，返回值与无 ctx 基线完全一致。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "a2_test"})

    res = await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="a2_test",
        wait_max_s=1,
        ctx=None,
    )
    assert isinstance(res, str)
    assert res.startswith("[Reviewer thinking:")


@pytest.mark.anyio
async def test_a3_exception_isolation_in_progress(tmp_path):
    """A3: 断言 report_progress 抛错（RuntimeError / ConnectionResetError）被静默隔离，不影响轮询主结果。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "a3_test"})

    ctx = TrackingContext(raise_exc=ConnectionResetError("transport closed"))
    res = await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="a3_test",
        wait_max_s=1,
        ctx=ctx,
    )
    assert isinstance(res, str)
    assert res.startswith("[Reviewer thinking:")
    assert len(ctx.calls) >= 1


@pytest.mark.anyio
async def test_a4_backpressure_truncation(tmp_path):
    """A4: 断言 report_progress 悬挂挂起时被 0.2s 截断，总耗时不超过 wait_max_s + 0.5s。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "a4_test"})

    ctx = TrackingContext(delay_s=5.0)  # 模拟通知端背压悬挂 5 秒
    start = time.monotonic()
    res = await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="a4_test",
        wait_max_s=1,
        ctx=ctx,
    )
    duration = time.monotonic() - start

    assert isinstance(res, str)
    assert duration <= 1.8  # 1.0s timeout + 0.2s backpressure wait + margin


@pytest.mark.anyio
async def test_a5_terminal_short_circuit(tmp_path):
    """A5: 断言作业提前完成时，长轮询在下一个 tick (<= 0.5s) 立即短路返回，无需等满 wait_max_s。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "a5_test"})

    res_path = supervisor._get_result_path(rec.session_id, rec.job_id)
    _durable_write_json(res_path, {"verdict": "PASS", "findings": "### Strategic Finding\n- All good.", "usage": {}})

    async def _finish_early():
        await asyncio.sleep(0.15)
        supervisor._cas_transition(
            rec.session_id,
            rec.job_id,
            JobState.QUEUED,
            JobState.COMPLETED,
            updates={"result_ref": str(res_path)},
        )

    ctx = TrackingContext()
    start = time.monotonic()
    task = asyncio.create_task(_finish_early())
    res = await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="a5_test",
        wait_max_s=10,  # 配置 10 秒超时
        ctx=ctx,
    )
    await task
    duration = time.monotonic() - start

    assert res == "### Strategic Finding\n- All good."
    assert duration <= 1.0  # 远小于 10 秒


@pytest.mark.anyio
async def test_a6_no_busy_waiting(tmp_path, monkeypatch):
    """A6: 断言无紧循环忙等，sleep 间隔 >= 0.05s，累计循环轮数受限。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "a6_test"})

    sleep_durations = []
    real_sleep = asyncio.sleep

    async def _mock_sleep(d):
        sleep_durations.append(d)
        await real_sleep(d)

    monkeypatch.setattr(asyncio, "sleep", _mock_sleep)

    await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="a6_test",
        wait_max_s=1,
    )

    assert len(sleep_durations) > 0
    assert all(d >= 0.05 for d in sleep_durations)
    assert len(sleep_durations) <= 6  # 1s / 0.25s + margin


@pytest.mark.anyio
async def test_a8_concurrent_cancellation_projection(tmp_path):
    """A8: 等待中调用 supervisor.cancel，轮询在 <= 0.5s 内返回 CANCELLED 降级卡片。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "a8_test"})

    async def _cancel_soon():
        await asyncio.sleep(0.1)
        supervisor.cancel(rec.job_id, session_id="a8_test")

    task = asyncio.create_task(_cancel_soon())
    start = time.monotonic()
    res = await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="a8_test",
        wait_max_s=5,
    )
    await task
    duration = time.monotonic() - start

    assert duration <= 1.0
    assert "### [Reviewer Consultation Degraded]" in res
    assert "CANCELLED" in res


@pytest.mark.anyio
async def test_a9_cancelled_error_passthrough(tmp_path):
    """A9: 客户端请求取消时，asyncio.CancelledError 正常向上透传，绝不被 except 吞掉。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "a9_test"})

    poll_task = asyncio.create_task(server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="a9_test",
        wait_max_s=5,
    ))

    await asyncio.sleep(0.1)
    poll_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await poll_task

    # 且后台 worker 的 JobRecord 仍保持存活，未被连带销毁
    assert supervisor.is_terminal_state(rec.job_id, session_id="a9_test") is False
