# -*- coding: utf-8 -*-
"""Unit tests for ReviewerEngine stream_chat SSE reader seam and idle watchdog."""
import asyncio
import os
import threading
import time
from typing import Any, List, Mapping, Optional
from unittest.mock import MagicMock, patch

import pytest

import reviewer_engine
from reviewer_engine import (
    ReviewerClient,
    StreamChunk,
    UsageSnapshot,
    _open_sse_response,
)


class MockSseResponse:
    """Mock HTTP response simulating SSE stream with optional hang/delay."""

    def __init__(self, initial_data: bytes, hang_after_data: bool = False) -> None:
        self._data = initial_data
        self._hang_after = hang_after_data
        self._read_first = False
        self._close_event = threading.Event()
        self.closed = False

    def read(self, size: int = 8192) -> bytes:
        if self.closed:
            return b""
        if not self._read_first:
            self._read_first = True
            return self._data
        if self._hang_after:
            # Hang until watchdog triggers close() or timeout guard
            self._close_event.wait(timeout=2.0)
            return b""
        return b""

    def close(self) -> None:
        self.closed = True
        self._close_event.set()


@pytest.mark.anyio
async def test_stream_delayed_usage_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    """(a) 延迟 choices:[] usage 块（断言 usage.cached_tokens > 0）。"""
    sse_text = (
        'data: {"choices": [{"delta": {"content": "Hello "}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "world!"}}]}\n\n'
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'
        'data: {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_cache_hit_tokens": 60}}\n\n'
        'data: [DONE]\n\n'
    )
    mock_resp = MockSseResponse(sse_text.encode("utf-8"), hang_after_data=False)

    def fake_open_sse(url: str, data: bytes, headers: Mapping[str, str], timeout: float) -> Any:
        return mock_resp

    monkeypatch.setattr(reviewer_engine, "_open_sse_response", fake_open_sse)

    client = ReviewerClient(
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        provider_label="mock_provider",
    )

    with patch.object(client, "resolve_api_key", return_value="fake_key"):
        chunks: List[StreamChunk] = []
        async for chunk in client.stream_chat("sys", "user"):
            chunks.append(chunk)

    full_text = "".join(c.text for c in chunks)
    assert full_text == "Hello world!"
    assert any(c.done for c in chunks)

    usage_chunks = [c for c in chunks if c.usage is not None]
    assert len(usage_chunks) >= 1
    snap = usage_chunks[-1].usage
    assert snap is not None
    assert snap.cached_tokens == 60
    assert snap.cached_tokens > 0
    assert snap.prompt_tokens == 100
    assert snap.completion_tokens == 20


@pytest.mark.anyio
async def test_stream_idle_watchdog_hang_after_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    """(b) finish_reason 后空闲悬挂（断言在 ~SSE_IDLE_TIMEOUT_S 内收敛且 content 完整）。"""
    monkeypatch.setattr(reviewer_engine, "SSE_IDLE_TIMEOUT_S", 0.1)
    monkeypatch.setenv("QUENCH_REVIEWER_SSE_IDLE_TIMEOUT", "0.1")

    sse_text = (
        'data: {"choices": [{"delta": {"content": "Complete output"}, "finish_reason": "stop"}]}\n\n'
    )
    mock_resp = MockSseResponse(sse_text.encode("utf-8"), hang_after_data=True)

    def fake_open_sse(url: str, data: bytes, headers: Mapping[str, str], timeout: float) -> Any:
        return mock_resp

    monkeypatch.setattr(reviewer_engine, "_open_sse_response", fake_open_sse)

    client = ReviewerClient(
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        provider_label="mock_provider",
    )

    start_t = time.monotonic()
    with patch.object(client, "resolve_api_key", return_value="fake_key"):
        chunks: List[StreamChunk] = []
        async for chunk in client.stream_chat("sys", "user"):
            chunks.append(chunk)
    elapsed = time.monotonic() - start_t

    # 断言在 ~0.1s 左右收敛（给操作系统调度留宽限，绝不超过 1.5s）
    assert elapsed < 1.5
    full_text = "".join(c.text for c in chunks)
    assert full_text == "Complete output"
    assert any(c.done for c in chunks)
    assert mock_resp.closed is True


@pytest.mark.anyio
async def test_stream_idle_watchdog_midway_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """(c) 中途断连超时（断言 content 保留、usage 为 None、不抛异常）。"""
    monkeypatch.setattr(reviewer_engine, "SSE_IDLE_TIMEOUT_S", 0.1)
    monkeypatch.setenv("QUENCH_REVIEWER_SSE_IDLE_TIMEOUT", "0.1")

    sse_text = (
        'data: {"choices": [{"delta": {"content": "Partial content before stall"}}]}\n\n'
    )
    mock_resp = MockSseResponse(sse_text.encode("utf-8"), hang_after_data=True)

    def fake_open_sse(url: str, data: bytes, headers: Mapping[str, str], timeout: float) -> Any:
        return mock_resp

    monkeypatch.setattr(reviewer_engine, "_open_sse_response", fake_open_sse)

    client = ReviewerClient(
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        provider_label="mock_provider",
    )

    with patch.object(client, "resolve_api_key", return_value="fake_key"):
        chunks: List[StreamChunk] = []
        async for chunk in client.stream_chat("sys", "user"):
            chunks.append(chunk)

    full_text = "".join(c.text for c in chunks)
    assert full_text == "Partial content before stall"
    # 中途断开未收到 usage 块，usage 为 None
    assert all(c.usage is None for c in chunks)
    assert any(c.done for c in chunks)
    assert mock_resp.closed is True


@pytest.mark.anyio
async def test_consultation_stream_usage_preservation(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """断言 consultation 消费 stream_chat 时能正确暂存并向外透传流末尾的 UsageSnapshot。"""
    import server

    class FakeStreamingClient:
        provider_label = "mock"

        def is_available(self) -> bool:
            return True

        def resolve_api_key(self) -> str:
            return "mock-key"

        async def stream_chat(self, messages, session_id=None):
            yield StreamChunk(text="Architectural ", reasoning="Thinking...")
            yield StreamChunk(text="findings.")
            yield StreamChunk(
                text="",
                usage=UsageSnapshot(
                    prompt_tokens=150,
                    completion_tokens=25,
                    cached_tokens=100,
                    provider_label="mock",
                ),
            )
            yield StreamChunk(done=True)

    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: FakeStreamingClient())

    result = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Verify cache usage propagation",
        session_id="stream-usage-test",
    )
    assert result["status"] == "ok"
    assert result["findings"] == "Architectural findings."
    assert result["usage"]["prompt_tokens"] == 150
    assert result["usage"]["completion_tokens"] == 25
    assert result["usage"]["prompt_cache_hit_tokens"] == 100

