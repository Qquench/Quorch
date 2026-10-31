# -*- coding: utf-8 -*-
"""test_reviewer_poll_longpoll_v124.py - Long-polling loop and ProgressBridge integration tests for v1.24.

Verifies:
1. _clamp_wait: Type safety, bool rejection with TypeError, float clamping [0.0, 25.0], non-finite handling.
2. Direct Python vs FastMCP protocol calling boundaries (P1-12).
3. Fast-path short circuit (< 250ms) for wait_max_s<=0 and pre-terminal tasks.
4. Terminal states never emit progress notifications to prevent client UI flicker.
5. ProgressBridge emits notifications when progressToken present, 0 notifications when absent.
6. Zero Reviewer capacity consumption (_REVIEWER_LIMITER.borrowed_tokens delta is 0) under @pytest.mark.concurrent_moat.
7. Zero disk writes during polling (W10).
8. Multi-session authorization isolation.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from fastmcp import Context
from tool_surface_constants import POLL_WAIT_MAX_S_HARD_CEILING
from progress_bridge import ProgressBridge
from reviewer_engine import _REVIEWER_LIMITER
from reviewer_jobs import (
    POLL_TERMINAL_FIELDS,
    JobProgress,
    JobRecord,
    JobState,
    ReviewerJobSupervisor,
    ReviewerPhase,
    _durable_write_json,
    _inode_key,
    _new_tracker_for_poll,
    _snapshot_business_state_scandir,
)
import server
from server import _clamp_wait, _poll_impl, dev_reviewer_poll


@pytest.fixture(autouse=True)
def prevent_auto_worker_launch(monkeypatch):
    """Ensure supervisor worker thread does not auto-execute in tests."""
    monkeypatch.setattr(ReviewerJobSupervisor, "_launch_worker", lambda self, record, req: None)


# ---------------------------------------------------------------------------
# 1. Parameter Clamping and Type Safety (_clamp_wait & P1-12)
# ---------------------------------------------------------------------------


def test_clamp_wait_rejects_boolean_with_type_error():
    """P1-12: Direct Python call with boolean explicitly raises TypeError."""
    with pytest.raises(TypeError, match="boolean"):
        _clamp_wait(True)

    with pytest.raises(TypeError, match="boolean"):
        _clamp_wait(False)


def test_clamp_wait_defaults_none_and_clamps_ranges():
    """Validates None -> 0.0, negatives -> 0.0, non-finite -> 0.0, cap at POLL_WAIT_MAX_S_HARD_CEILING."""
    assert POLL_WAIT_MAX_S_HARD_CEILING == 25.0
    assert _clamp_wait(None) == 0.0
    assert _clamp_wait(0) == 0.0
    assert _clamp_wait(-10) == 0.0
    assert _clamp_wait(-0.01) == 0.0
    assert _clamp_wait(float("nan")) == 0.0
    assert _clamp_wait(float("inf")) == 0.0
    assert _clamp_wait(float("-inf")) == 0.0
    assert _clamp_wait(10) == 10.0
    assert _clamp_wait(20.5) == 20.5
    assert _clamp_wait(25.0) == 25.0
    assert _clamp_wait(POLL_WAIT_MAX_S_HARD_CEILING) == POLL_WAIT_MAX_S_HARD_CEILING
    assert _clamp_wait(POLL_WAIT_MAX_S_HARD_CEILING + 5.0) == POLL_WAIT_MAX_S_HARD_CEILING
    assert _clamp_wait(30) == 25.0
    assert _clamp_wait(999.0) == 25.0


def test_clamp_wait_rejects_unparseable_strings():
    """Invalid string raises ValueError."""
    with pytest.raises(ValueError, match="must be an integer"):
        _clamp_wait("not_a_number")


@pytest.mark.anyio
async def test_dev_reviewer_poll_direct_call_bool_raises_type_error(tmp_path):
    """P1-12: Direct call to dev_reviewer_poll with wait_max_s=True raises TypeError."""
    ws = str(tmp_path)
    with pytest.raises(TypeError, match="boolean"):
        await dev_reviewer_poll(
            workspace_root=ws,
            job_id="job_dummy",
            session_id="sess_dummy",
            wait_max_s=True,
        )

    with pytest.raises(TypeError, match="boolean"):
        await dev_reviewer_poll(
            workspace_root=ws,
            job_id="job_dummy",
            session_id="sess_dummy",
            wait_max_s=False,
        )


# ---------------------------------------------------------------------------
# 2. Fast Path Short-Circuit (< 250ms)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fast_path_short_circuit_zero_wait(tmp_path):
    """wait_max_s <= 0 returns immediately (< 250ms) without polling loops."""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "sess_fastpath"})

    t0 = time.monotonic()
    res = await dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="sess_fastpath",
        wait_max_s=0,
    )
    elapsed = time.monotonic() - t0

    assert elapsed < 0.25, f"Expected fast-path < 250ms, took {elapsed:.4f}s"
    assert isinstance(res, dict)
    assert res["state"] == "QUEUED"
    assert "elapsed_s" in res


@pytest.mark.anyio
async def test_fast_path_short_circuit_terminal_task(tmp_path):
    """Pre-terminal task returns immediately (< 250ms) even if wait_max_s is 20s."""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "sess_term"})

    res_path = supervisor._get_result_path(rec.session_id, rec.job_id)
    _durable_write_json(res_path, {"verdict": "PASS", "findings": "Done.", "usage": {}})
    supervisor._cas_transition(
        rec.session_id,
        rec.job_id,
        JobState.QUEUED,
        JobState.COMPLETED,
        updates={"result_ref": str(res_path)},
    )

    t0 = time.monotonic()
    res = await dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="sess_term",
        wait_max_s=20,
    )
    elapsed = time.monotonic() - t0

    assert elapsed < 0.25, f"Expected terminal short-circuit < 250ms, took {elapsed:.4f}s"
    assert isinstance(res, dict)
    assert res["state"] == "COMPLETED"
    assert set(res.keys()) == POLL_TERMINAL_FIELDS


# ---------------------------------------------------------------------------
# 3. Notification Behavior: Emitted on Token, Zero on Absent, Zero on Terminal
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_progress_notifications_emitted_when_token_present(tmp_path):
    """When progressToken is present, notifications are emitted via bridge."""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "sess_prog"})

    # Setup fake Context with progressToken
    mock_ctx = MagicMock(spec=Context)
    mock_ctx.report_progress = AsyncMock()
    req_ctx = MagicMock()
    req_ctx.meta = {"progressToken": "token-test-124"}
    mock_ctx.request_context = req_ctx

    async def _transition_to_completed_after_delay():
        await asyncio.sleep(0.12)
        res_path = supervisor._get_result_path(rec.session_id, rec.job_id)
        _durable_write_json(res_path, {"verdict": "PASS", "findings": "Ok", "usage": {}})
        supervisor._cas_transition(
            rec.session_id,
            rec.job_id,
            JobState.QUEUED,
            JobState.COMPLETED,
            updates={"result_ref": str(res_path)},
        )

    task = asyncio.create_task(_transition_to_completed_after_delay())

    res = await dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="sess_prog",
        wait_max_s=5,
        ctx=mock_ctx,
    )
    await task

    assert res["state"] == "COMPLETED"
    # Bridge should have emitted at least the initial QUEUED non-terminal snapshot
    assert mock_ctx.report_progress.call_count >= 1

    # Verify no terminal notification was emitted (final call must be non-terminal)
    for call_args in mock_ctx.report_progress.call_args_list:
        msg = call_args.kwargs.get("message", "")
        assert "COMPLETED" not in msg, f"Terminal state must not emit progress notification: {msg}"


@pytest.mark.anyio
async def test_zero_notifications_when_progress_token_absent(tmp_path):
    """When progressToken is absent, ProgressBridge is None and zero notifications are sent."""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "sess_notoken"})

    mock_ctx = MagicMock(spec=Context)
    mock_ctx.report_progress = AsyncMock()
    req_ctx = MagicMock()
    req_ctx.meta = {}  # No progressToken
    mock_ctx.request_context = req_ctx

    res = await dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="sess_notoken",
        wait_max_s=0,
        ctx=mock_ctx,
    )

    assert res["state"] == "QUEUED"
    assert mock_ctx.report_progress.call_count == 0


# ---------------------------------------------------------------------------
# 4. Multi-Session Authorization Isolation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_poll_rejects_unauthorized_session(tmp_path):
    """Poll rejects mismatched session_id with structured error dict."""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "owner_session"})

    res = await dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="intruder_session",
        wait_max_s=0,
    )

    assert res["status"] == "error"
    assert "Access denied" in res["error"]


# ---------------------------------------------------------------------------
# 5. Zero Disk Write During Long-Polling (W10)
# ---------------------------------------------------------------------------


@pytest.mark.heavy
@pytest.mark.anyio
async def test_watch_zero_disk_writes_during_poll(tmp_path):
    """W10: Polling loop performs zero disk write or log flushing."""
    ws = Path(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(str(ws))
    rec = supervisor.submit({"query": "q", "session_id": "sess_w10"})

    # 显式在 ws 下创建 .lock 文件，模拟 Unix filelock 在混合环境下的锁原语波动
    lock_file = ws / "supervisor.lock"
    lock_file.write_text("initial lock")

    tracker = _new_tracker_for_poll()
    files_before = _snapshot_business_state_scandir(ws, exempt=tracker)

    res = await dev_reviewer_poll(
        workspace_root=str(ws),
        job_id=rec.job_id,
        session_id="sess_w10",
        wait_max_s=1,
    )
    assert res["state"] == "QUEUED"

    # 模拟 lock 文件内容变动或触碰，断言其因属于 W10 Exclusion Domain 不会导致零写契约失败
    lock_file.write_text("lock touched during poll")

    files_after = _snapshot_business_state_scandir(ws, exempt=tracker)

    # 断言业务状态完全一致，无磁盘写入
    assert files_before == files_after


def test_exempt_tracker_key_consistency(tmp_path):
    """验证 _inode_key(st_dev, st_ino) 的元组输出在同一物理 inode 上的唯一与恒定性。"""
    f = Path(tmp_path) / "test_key.txt"
    f.write_text("sample")
    st1 = f.stat()
    k1 = _inode_key(st1.st_dev, st1.st_ino)
    st2 = f.stat()
    k2 = _inode_key(st2.st_dev, st2.st_ino)
    assert k1 == k2
    assert isinstance(k1, tuple)
    assert len(k1) == 2


def test_register_stat_failure_is_failclosed(tmp_path):
    """模拟 register 捕获 OSError，验证确保降级为业务文件受控审计 (fail-closed)。"""
    tracker = _new_tracker_for_poll()
    non_existent = Path(tmp_path) / "ghost.txt"
    # 不存在路径 register 不抛异常，静默不写基线
    tracker.register(non_existent)
    # is_exempt 恒 False (fail-closed)
    assert tracker.is_exempt((0, 0), 100, 200) is False


def test_exempt_drift_reincluded_as_business(tmp_path):
    """豁免文件内容发生写漂移时，is_exempt 返回 False 并被重新纳入业务状态快照进行写探测。"""
    ws = Path(tmp_path)
    f = ws / "exempt_target.log"
    f.write_text("initial")

    tracker = _new_tracker_for_poll()
    tracker.register(f)
    st_init = f.stat()
    k = _inode_key(st_init.st_dev, st_init.st_ino)

    # 未漂移时，属于豁免
    assert tracker.is_exempt(k, st_init.st_size, st_init.st_mtime_ns) is True
    snap1 = _snapshot_business_state_scandir(ws, exempt=tracker)
    assert not any(v == (st_init.st_size, st_init.st_mtime_ns) for v in snap1.values())

    # 发生写漂移
    f.write_text("drifted content that alters size or mtime")
    st_drift = f.stat()

    # 漂移后，is_exempt 返回 False
    assert tracker.is_exempt(k, st_drift.st_size, st_drift.st_mtime_ns) is False
    snap2 = _snapshot_business_state_scandir(ws, exempt=tracker)
    assert any(v == (st_drift.st_size, st_drift.st_mtime_ns) for v in snap2.values())
    if sys.platform != "win32":
        assert k in snap2
        assert snap2[k] == (st_drift.st_size, st_drift.st_mtime_ns)


# ---------------------------------------------------------------------------
# 6. Zero Reviewer Capacity Consumption (C.5 / P1-11, concurrent_moat)
# ---------------------------------------------------------------------------


@pytest.mark.concurrent_moat
@pytest.mark.anyio
async def test_zero_capacity_limiter_consumption(tmp_path):
    """C.5 / P1-11: Polling loop consumes zero tokens from _REVIEWER_LIMITER."""
    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "sess_capacity"})

    initial_tokens = _REVIEWER_LIMITER.borrowed_tokens

    res = await dev_reviewer_poll(
        workspace_root=ws,
        job_id=rec.job_id,
        session_id="sess_capacity",
        wait_max_s=1,
    )
    assert res["state"] == "QUEUED"

    final_tokens = _REVIEWER_LIMITER.borrowed_tokens
    assert final_tokens == initial_tokens, (
        f"Capacity limiter was polluted by poll: initial={initial_tokens}, final={final_tokens}"
    )
