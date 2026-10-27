# -*- coding: utf-8 -*-
"""Unit tests for ReviewerClient.complete(stream=True) and acomplete usage/telemetry capture."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from project_config import ReviewerEngineConfig
from reviewer_engine import ReviewerClient


def _create_mock_sse_response(chunks: list[dict]) -> MagicMock:
    """Helper to create a mock HTTP response yielding SSE formatted data."""
    lines = []
    for c in chunks:
        lines.append(f"data: {json.dumps(c)}\n".encode("utf-8"))
        lines.append(b"\n")
    lines.append(b"data: [DONE]\n")
    lines.append(b"\n")

    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__iter__.return_value = iter(lines)
    mock_resp.read.return_value = b"".join(lines)
    return mock_resp


def test_stream_complete_extracts_delayed_usage_and_cache_hit() -> None:
    """验证 complete(stream=True) 在 choices=[] 延迟 usage 尾包时能正确提取 usage 并归一缓存命中数。"""
    cfg = ReviewerEngineConfig(
        provider="custom",
        model="test-model",
        base_url="https://api.example.com/v1",
    )
    client = ReviewerClient(cfg)
    client.resolve_api_key = MagicMock(return_value="sk-test")

    chunks = [
        {"choices": [{"delta": {"content": "Hello"}}]},
        {"choices": [{"delta": {"content": " world!"}}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 1200,
                "completion_tokens": 30,
                "total_tokens": 1230,
                "prompt_cache_hit_tokens": 960,
            },
        },
    ]

    mock_resp = _create_mock_sse_response(chunks)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.complete([{"role": "user", "content": "hi"}], stream=True)

    assert res["content"] == "Hello world!"
    usage = res["usage"]
    assert usage["prompt_tokens"] == 1200
    assert usage["prompt_cache_hit_tokens"] == 960
    assert usage["completion_tokens"] >= 2


@pytest.mark.anyio
async def test_acomplete_stream_emits_telemetry_with_actual_hit_ratio(tmp_path: Path) -> None:
    """验证 acomplete(stream=True) 能将流式提取出的实际使用量正确落盘至 cache_telemetry.jsonl。"""
    log_dir = str(tmp_path / "logs")
    os.makedirs(log_dir, exist_ok=True)

    cfg = ReviewerEngineConfig(
        provider="custom",
        model="test-model",
        base_url="https://api.example.com/v1",
    )
    client = ReviewerClient(cfg)
    client.resolve_api_key = MagicMock(return_value="sk-test")

    chunks = [
        {"choices": [{"delta": {"content": "Audit result: OK"}}]},
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 2000,
                "completion_tokens": 15,
                "total_tokens": 2015,
                "prompt_tokens_details": {"cached_tokens": 1500},
            },
        },
    ]

    mock_resp = _create_mock_sse_response(chunks)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = await client.acomplete(
            [{"role": "user", "content": "run audit"}],
            stream=True,
            log_dir=log_dir,
            session_id="test-session-acomplete",
        )

    assert res["content"] == "Audit result: OK"
    assert res["usage"]["prompt_tokens"] == 2000
    assert res["usage"]["prompt_cache_hit_tokens"] == 1500

    # 验证 telemetry 日志文件
    telemetry_path = os.path.join(log_dir, "cache_telemetry.jsonl")
    assert os.path.isfile(telemetry_path)

    with open(telemetry_path, "r", encoding="utf-8") as f:
        lines = [json.loads(line.strip()) for line in f if line.strip()]

    assert len(lines) == 1
    record = lines[0]
    assert record["mode"] == "acomplete"
    assert record["session_id"] == "test-session-acomplete"
    assert record["prompt_tokens"] == 2000
    assert record["cached_tokens"] == 1500
    assert record["miss_tokens"] == 500
    assert record["hit_ratio"] == 0.75
    assert record["usage_available"] is True


def test_stream_complete_without_usage_graceful_fallback(tmp_path: Path) -> None:
    """验证当上游完全未返回 usage 字段时，不会抛出异常且优雅降级。"""
    cfg = ReviewerEngineConfig(
        provider="custom",
        model="test-model",
        base_url="https://api.example.com/v1",
    )
    client = ReviewerClient(cfg)
    client.resolve_api_key = MagicMock(return_value="sk-test")

    chunks = [
        {"choices": [{"delta": {"content": "Fallback content"}}]},
    ]

    mock_resp = _create_mock_sse_response(chunks)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.complete([{"role": "user", "content": "hi"}], stream=True)

    assert res["content"] == "Fallback content"
    assert "usage" in res
    assert res["usage"].get("prompt_tokens") is None
