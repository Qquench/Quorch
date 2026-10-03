# -*- coding: utf-8 -*-
"""Unit tests for AdaptiveHeartbeatSink, ladder backoff, event-gating and MCP progress channel."""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock
import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from reviewer_engine import AdaptiveHeartbeatSink, format_heartbeat_line


def test_heartbeat_first_pulse_immediate_or_low_latency():
    """断言首帧心跳无等待，_pulse_count == 0 时立即发射。"""
    emitted = []
    progress_calls = []

    mock_clock_time = 100.0

    def fake_clock():
        return mock_clock_time

    sink = AdaptiveHeartbeatSink(
        file_emit=lambda line: emitted.append(line),
        progress_emit=lambda tokens, elapsed: progress_calls.append((tokens, elapsed)),
        interval_ms=1000,
        clock=fake_clock,
    )

    assert sink._pulse_count == 0
    assert sink._should_emit(tokens_so_far=10, now=100.0) is True

    sink.on_heartbeat(tokens_so_far=10, elapsed_s=0.2)
    assert sink._pulse_count == 1
    assert len(emitted) == 1
    assert len(progress_calls) == 1
    assert progress_calls[0] == (10, 0.2)
    assert "[Reviewer thinking: 0.2s | 10 tokens]" in emitted[0]


def test_heartbeat_event_gating_suppresses_redundancy():
    """断言 token 无增量时，在 keepalive_floor (5.0s) 内不会重复发射纯时钟噪声。"""
    emitted = []
    curr_time = 1000.0

    sink = AdaptiveHeartbeatSink(
        file_emit=lambda line: emitted.append(line),
        interval_ms=1000,
        clock=lambda: curr_time,
    )

    # 1. 触发首帧
    sink.on_heartbeat(tokens_so_far=100, elapsed_s=0.1)
    assert len(emitted) == 1

    # 2. 过了 1.5 秒，但 token 完全没变（依然是 100）
    curr_time = 1001.5
    sink.on_heartbeat(tokens_so_far=100, elapsed_s=1.6)
    assert len(emitted) == 1  # 被事件门控拦截！不产生噪声

    # 3. 过了 3 秒，token 依然没变
    curr_time = 1003.0
    sink.on_heartbeat(tokens_so_far=100, elapsed_s=3.1)
    assert len(emitted) == 1  # 依然被拦截

    # 4. 此时 token 产生实质进展 (100 -> 150，增量 >= 20)
    curr_time = 1003.5
    sink.on_heartbeat(tokens_so_far=150, elapsed_s=3.6)
    assert len(emitted) == 2  # 有进展立即发射！
    assert "[Reviewer thinking: 3.6s | 150 tokens]" in emitted[1]

    # 5. 再次停滞 5.1 秒（超过保活底线 5.0s），即使 token 没变也必须触发保活心跳
    curr_time = 1008.7
    sink.on_heartbeat(tokens_so_far=150, elapsed_s=8.8)
    assert len(emitted) == 3  # keepalive 触发
    assert "[Reviewer thinking: 8.8s | 150 tokens]" in emitted[2]


@pytest.mark.anyio
async def test_heartbeat_async_progress_emit_and_exception_swallow():
    """断言 progress_emit 异步调用正常，且抛出异常时静默吞吐，绝不中断流式。"""
    emitted = []

    async def faulty_progress_emit(tokens, elapsed):
        raise RuntimeError("Host UI disconnected")

    sink = AdaptiveHeartbeatSink(
        file_emit=lambda line: emitted.append(line),
        progress_emit=faulty_progress_emit,
        interval_ms=500,
    )

    # 抛出异常不应中断 apulse
    await sink.apulse(tokens_so_far=42, elapsed_s=0.5)
    assert len(emitted) == 1
    assert "[Reviewer thinking: 0.5s | 42 tokens]" in emitted[0]


@pytest.mark.anyio
async def test_heartbeat_fastmcp_ctx_integration():
    """断言支持传入兼容 FastMCP Context 的 report_progress 协程。"""
    mock_ctx = MagicMock()
    mock_ctx.report_progress = AsyncMock()

    async def _progress_adapter(tokens: int, elapsed_s: float):
        msg = format_heartbeat_line(tokens, elapsed_s)
        await mock_ctx.report_progress(progress=float(tokens), total=None, message=msg)

    sink = AdaptiveHeartbeatSink(
        file_emit=lambda line: None,
        progress_emit=_progress_adapter,
        interval_ms=500,
    )

    await sink.apulse(tokens_so_far=200, elapsed_s=1.2)
    mock_ctx.report_progress.assert_awaited_once_with(
        progress=200.0,
        total=None,
        message="[Reviewer thinking: 1.2s | 200 tokens]",
    )


def test_heartbeat_zero_stdout_pollution(capfd):
    """断言 AdaptiveHeartbeatSink 运行期严禁向 stdout 打印任何裸字符。"""
    sink = AdaptiveHeartbeatSink(
        file_emit=lambda line: None,
        progress_emit=lambda tokens, elapsed: None,
        interval_ms=500,
    )
    sink.on_heartbeat(tokens_so_far=50, elapsed_s=1.0)
    captured = capfd.readouterr()
    assert captured.out == ""

