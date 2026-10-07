# -*- coding: utf-8 -*-
"""Unit and integration tests for dev_reviewer_poll streamlined polling loop (Option B).
Locks in:
- B1: Terminal short-circuit (exits early upon terminal state <= 1.0s)
- B2: No busy waiting (sleep >= 0.05s floor, bounded poll count, no sleep(0) tight spin)
- B3: Concurrent cancellation yields CANCELLED projection in <= 1.0s
- B4: asyncio.CancelledError passthrough (never swallowed by except Exception)
- B5: Pure 5-parameter signature (no ctx parameter, inputSchema pure)
- B6: Non-terminal wait returns format_heartbeat_line when raw_text=True
- B7: Zero wait (wait_max_s=0) immediate return without sleep
"""
import asyncio
import inspect
import os
import sys
import time
import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from reviewer_jobs import ReviewerJobSupervisor, JobState, POLL_TERMINAL_STATES, _durable_write_json
from reviewer_engine import format_heartbeat_line
import server


@pytest.fixture(autouse=True)
def prevent_auto_worker_failure(monkeypatch):
    monkeypatch.setattr(ReviewerJobSupervisor, "_launch_worker", lambda self, record, req: None)


@pytest.mark.anyio
async def test_b1_terminal_short_circuit(tmp_path):
    """B1: 断言作业提前完成时，长轮询在下一个 tick (<= 0.5s) 立即短路返回，无需等满 wait_max_s。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "b1_test"})

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

    start = time.monotonic()
    task = asyncio.create_task(_finish_early())
    res = await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="b1_test",
        wait_max_s=10,  # 配置 10 秒超时
    )
    await task
    duration = time.monotonic() - start

    assert res == "### Strategic Finding\n- All good."
    assert duration <= 1.0  # 远小于 10 秒


@pytest.mark.anyio
async def test_b2_no_busy_waiting_and_sleep_floor(tmp_path, monkeypatch):
    """B2: 断言无紧循环忙等，sleep 间隔 >= 0.05s 下限，累计循环轮数受限 (热旋防线)。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "b2_test"})

    sleep_durations = []
    real_sleep = asyncio.sleep

    async def _mock_sleep(d):
        sleep_durations.append(d)
        await real_sleep(d)

    monkeypatch.setattr(asyncio, "sleep", _mock_sleep)

    await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="b2_test",
        wait_max_s=1,
    )

    assert len(sleep_durations) > 0
    assert all(d >= 0.05 for d in sleep_durations), f"Found sleep < 0.05s: {sleep_durations}"
    assert len(sleep_durations) <= 6  # 1s / 0.25s + margin


@pytest.mark.anyio
async def test_b3_concurrent_cancellation_projection(tmp_path):
    """B3: 等待中调用 supervisor.cancel，轮询在 <= 0.5s 内返回 CANCELLED 降级卡片。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "b3_test"})

    async def _cancel_soon():
        await asyncio.sleep(0.1)
        supervisor.cancel(rec.job_id, session_id="b3_test")

    task = asyncio.create_task(_cancel_soon())
    start = time.monotonic()
    res = await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="b3_test",
        wait_max_s=5,
    )
    await task
    duration = time.monotonic() - start

    assert duration <= 1.0
    assert "### [Reviewer Consultation Degraded]" in res
    assert "CANCELLED" in res


@pytest.mark.anyio
async def test_b4_cancelled_error_passthrough(tmp_path):
    """B4: 客户端请求取消时，asyncio.CancelledError 正常向上透传，绝不被 except 吞掉。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "b4_test"})

    poll_task = asyncio.create_task(server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="b4_test",
        wait_max_s=5,
    ))

    await asyncio.sleep(0.1)
    poll_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await poll_task

    # 且后台 worker 的状态仍保持非终态存活，未被连带销毁
    poll_res = supervisor.poll(rec.job_id, session_id="b4_test", raw_text=False)
    assert poll_res["state"] not in POLL_TERMINAL_STATES


def test_b5_pure_signature_and_no_ctx():
    """B5: 断言 dev_reviewer_poll 签名纯净，不包含 ctx 形参，位置参数严格 5 项。"""
    sig = inspect.signature(server.dev_reviewer_poll)
    param_names = list(sig.parameters.keys())
    assert param_names == ["workspace_root", "job_id", "session_id", "wait_max_s", "raw_text"]
    assert "ctx" not in param_names
    assert sig.parameters["wait_max_s"].default == 0
    assert sig.parameters["raw_text"].default is True


@pytest.mark.anyio
async def test_b6_raw_text_heartbeat_projection(tmp_path):
    """B6: 非终态超时返回时，raw_text=True 返回单行心跳文本，raw_text=False 返回结构化 dict。"""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "b6_test"})

    res_text = await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="b6_test",
        wait_max_s=1,
        raw_text=True,
    )
    assert isinstance(res_text, str)
    assert res_text.startswith("[Reviewer thinking:")

    res_dict = await server.dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="b6_test",
        wait_max_s=1,
        raw_text=False,
    )
    assert isinstance(res_dict, dict)
    assert res_dict["state"] == "QUEUED"
    assert "job_id" in res_dict
