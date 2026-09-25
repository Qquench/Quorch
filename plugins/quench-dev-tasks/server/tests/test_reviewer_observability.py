# -*- coding: utf-8 -*-
"""Unit tests for Reviewer Observability: Minimalist Real-Time Thinking Log,
Pre-Write Redaction, Adaptive Heartbeat Pulse, Fail-Open Telemetry, and Soft Ceiling.
"""
import io
import json
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from reviewer_engine import (
    AdaptiveHeartbeatSink,
    DeepSeekClient,
    ProgressSink,
    ReviewerEngineConfig,
    RotatingFileSink,
    ThoughtChunk,
    compute_repetition_score,
    log_telemetry_event,
)


def test_stdout_is_byte_clean(capfd, tmp_path):
    """P0#1 Invariant: Under no circumstances should thinking logs or heartbeats pollute sys.stdout."""
    log_dir = str(tmp_path / "logs")
    session_id = "clean-test-session"
    sink = RotatingFileSink(log_dir=log_dir, session_id=session_id)
    heartbeat = AdaptiveHeartbeatSink(file_emit=sink.write_chunk_text, interval_ms=500)

    # Send chunks and heartbeat
    sink.on_chunk(ThoughtChunk(content="Thinking about architecture...", is_thought=True, tokens_estimate=5))
    heartbeat.on_heartbeat(tokens_so_far=10, elapsed_s=1.0)
    sink.on_finish("stop", {"tokens": 10, "elapsed_s": 1.0})
    heartbeat.on_finish("stop", {})

    captured = capfd.readouterr()
    assert captured.out == "", f"Expected completely clean stdout, got: {captured.out!r}"


def test_streaming_redaction_across_chunk_boundary(tmp_path):
    """B3: Pre-write 64B carry-over window redaction across chunk boundaries."""
    log_dir = str(tmp_path / "logs")
    session_id = "redaction-test"
    sink = RotatingFileSink(log_dir=log_dir, session_id=session_id, carry_over_bytes=32)

    # Chunk 1 ends mid-secret
    sink.on_chunk(ThoughtChunk(content="Reviewing secret: sk-1234567890", is_thought=True, tokens_estimate=6))
    # Chunk 2 completes the secret and adds padding
    sink.on_chunk(ThoughtChunk(content="abcdefghijklmnopqrstuvwx and more context follows", is_thought=True, tokens_estimate=10))
    sink.on_finish("stop", {})

    log_file = os.path.join(log_dir, f"latest-{session_id}.log")
    assert os.path.isfile(log_file)
    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "sk-1234567890abcdefghijklmnopqrstuvwx" not in content
    assert "[REDACTED]" in content
    assert "and more context follows" in content


def test_rotating_file_sink_cap_and_rotate(tmp_path):
    """B1 & T6-2: Live write-time 1024KB cap & rotation to .1.log rather than truncating in place."""
    log_dir = str(tmp_path / "logs")
    session_id = "rotate-test"
    # Small max_bytes for testing rotation
    sink = RotatingFileSink(log_dir=log_dir, session_id=session_id, max_bytes=1024)

    # Write 800 bytes
    sink.on_chunk(ThoughtChunk(content="A" * 800, is_thought=True, tokens_estimate=200))
    # Write another 800 bytes -> exceeds 1024 bytes -> triggers rotation
    sink.on_chunk(ThoughtChunk(content="B" * 800, is_thought=True, tokens_estimate=200))
    sink.on_finish("stop", {})

    log_file = os.path.join(log_dir, f"latest-{session_id}.log")
    rot_file = os.path.join(log_dir, f"latest-{session_id}.1.log")

    assert os.path.isfile(rot_file), "Rotated .1.log must exist"
    assert os.path.isfile(log_file), "New latest.log must exist"

    with open(rot_file, "r", encoding="utf-8") as f:
        rot_content = f.read()
    assert "A" in rot_content

    with open(log_file, "r", encoding="utf-8") as f:
        new_content = f.read()
    assert "ROTATED AT" in new_content
    assert "B" in new_content


def test_adaptive_heartbeat_throttling():
    """B4 & T6-4: Adaptive heartbeat throttled to >= 500ms / 1000ms."""
    fake_stderr = io.StringIO()
    fake_stderr.isatty = lambda: True
    emitted_files = []

    heartbeat = AdaptiveHeartbeatSink(
        file_emit=emitted_files.append,
        stderr=fake_stderr,
        interval_ms=1000,
    )

    # First pulse at t=0
    heartbeat.on_heartbeat(tokens_so_far=100, elapsed_s=1.0)
    assert len(emitted_files) == 1
    assert "[progress] [Reviewer thinking: 100 tokens | 1.0s]" in emitted_files[0]

    # Second pulse immediately after (no time elapsed) -> throttled
    heartbeat.on_heartbeat(tokens_so_far=200, elapsed_s=1.1)
    assert len(emitted_files) == 1

    # Fast forward clock > 1.05s
    with patch("time.monotonic", return_value=time.monotonic() + 2.0):
        heartbeat.on_heartbeat(tokens_so_far=300, elapsed_s=3.0)
        assert len(emitted_files) == 2
        assert "[progress] [Reviewer thinking: 300 tokens | 3.0s]" in emitted_files[1]


def test_heartbeat_multi_channel_dispatch_and_mandatory_file_fallback(capfd):
    """验证 AdaptiveHeartbeatSink 纯拉模型落盘与 FILE 常驻兜底，严格遵守零 stdout/stderr 污染。"""
    # 0. D6 强制校验：未传 file_emit 必须抛 ValueError
    with pytest.raises(ValueError, match="file_emit"):
        AdaptiveHeartbeatSink(file_emit=None)

    # 1. State: mcp_present -> file_emit 正常落盘，不再执行无效 mcp push
    mcp_ctx = MagicMock()
    fake_stderr1 = io.StringIO()
    file_emitted1: list[str] = []

    hb_mcp = AdaptiveHeartbeatSink(
        file_emit=file_emitted1.append,
        mcp_context=mcp_ctx,
        stderr=fake_stderr1,
        interval_ms=500,
    )
    hb_mcp.on_heartbeat(tokens_so_far=50, elapsed_s=0.5)
    assert len(file_emitted1) == 1
    assert "[progress] [Reviewer thinking: 50 tokens | 0.5s]" in file_emitted1[0]
    assert fake_stderr1.getvalue() == ""

    # 2. State: interactive terminal -> 遵循纯拉模型，stderr 零字符污染
    fake_stderr2 = io.StringIO()
    file_emitted2: list[str] = []

    hb_tty = AdaptiveHeartbeatSink(
        file_emit=file_emitted2.append,
        mcp_context=None,
        stderr=fake_stderr2,
        interval_ms=500,
    )
    hb_tty.on_heartbeat(tokens_so_far=60, elapsed_s=0.6)
    assert fake_stderr2.getvalue() == ""
    assert len(file_emitted2) == 1
    assert "[progress] [Reviewer thinking: 60 tokens | 0.6s]" in file_emitted2[0]

    # 3. State: no_ctx_no_tty (后台非 TTY 管道，无 MCP 上下文) -> FILE 常驻兜底，永不静默
    fake_stderr3 = io.StringIO()
    file_emitted3: list[str] = []

    hb_silent_stderr = AdaptiveHeartbeatSink(
        file_emit=file_emitted3.append,
        mcp_context=None,
        stderr=fake_stderr3,
        interval_ms=500,
    )
    hb_silent_stderr.on_heartbeat(tokens_so_far=70, elapsed_s=0.7)
    assert fake_stderr3.getvalue() == ""
    assert len(file_emitted3) == 1
    assert "[progress] [Reviewer thinking: 70 tokens | 0.7s]" in file_emitted3[0]

    # 4. 全局零 stdout 污染核验
    captured = capfd.readouterr()
    assert captured.out == "", f"Expected clean stdout, got: {captured.out!r}"


def test_telemetry_schema_and_fail_open(tmp_path):
    """B7 & T6-5: Telemetry schema: 1 format and fail-open logging behavior."""
    log_dir = str(tmp_path / "telemetry_test")
    record = {
        "schema": 1,
        "ts": "2026-09-21T10:00:00Z",
        "session_id": "session-123",
        "event": "start",
        "elapsed_ms": 0,
        "tokens_out": 0,
        "repetition_score": 0.0,
        "truncated": False,
        "advisory": None,
    }

    log_telemetry_event(log_dir, record)
    t_file = os.path.join(log_dir, "telemetry.jsonl")
    assert os.path.isfile(t_file)

    with open(t_file, "r", encoding="utf-8") as f:
        line = f.readline().strip()
        data = json.loads(line)
        assert data["schema"] == 1
        assert data["session_id"] == "session-123"
        assert data["event"] == "start"

    # Fail-open assertion: write to invalid path should not raise
    log_telemetry_event("\0invalid_path", record)


def test_repetition_score_computation():
    """Lexical repetition detection based on n-gram diversity."""
    short_text = "short text"
    assert compute_repetition_score(short_text) == 0.0

    diverse_text = (
        "The system architecture requires careful separation of concerns between "
        "the presentation layer, domain models, persistence adapters, and telemetry handlers. "
        "Each component operates under strict boundary guarantees and error isolation."
    )
    score_diverse = compute_repetition_score(diverse_text)
    assert score_diverse < 0.3, f"Expected low score for diverse text, got {score_diverse}"

    repeating_text = " ".join(["deadlock retry abort lock timeout release error"] * 20)
    score_loop = compute_repetition_score(repeating_text)
    assert score_loop > 0.6, f"Expected high score for looping text, got {score_loop}"


def test_deepseek_client_streaming_and_soft_ceiling(tmp_path):
    """B6: Streaming SSE response handling and non-destructive soft ceiling."""
    log_dir = str(tmp_path / "logs")
    session_id = "streaming-test"

    config = ReviewerEngineConfig(
        provider="deepseek",
        model="deepseek-flash",
        api_key_env="DUMMY_KEY",
        timeout_seconds=10,
    )
    client = DeepSeekClient(config)
    client.resolve_api_key = lambda: "dummy-key"

    sse_lines = [
        b"data: {\"choices\": [{\"delta\": {\"reasoning_content\": \"Thinking about constraints... \"}}]}\n",
        b"data: {\"choices\": [{\"delta\": {\"content\": \"Here is the refined specification.\"}}]}\n",
        b"data: [DONE]\n",
    ]

    mock_resp = MagicMock()
    mock_resp.__iter__.return_value = iter(sse_lines)
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    sink = RotatingFileSink(log_dir=log_dir, session_id=session_id)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.complete(
            messages=[{"role": "user", "content": "review"}],
            stream=True,
            sinks=[sink],
            session_id=session_id,
            log_dir=log_dir,
            soft_token_ceiling=64000,
        )

    assert "Thinking about constraints" in res["reasoning_content"]
    assert "Here is the refined specification" in res["content"]
    assert res["truncated"] is False

    # Check that log file recorded the text
    log_file = os.path.join(log_dir, f"latest-{session_id}.log")
    with open(log_file, "r", encoding="utf-8") as f:
        file_text = f.read()
    assert "Thinking about constraints" in file_text
    assert "Here is the refined specification" in file_text

    # Check telemetry
    telemetry_file = os.path.join(log_dir, "telemetry.jsonl")
    assert os.path.isfile(telemetry_file)
    with open(telemetry_file, "r", encoding="utf-8") as f:
        lines = [json.loads(l) for l in f.readlines()]
    assert any(l["event"] == "start" for l in lines)
    assert any(l["event"] == "finish" for l in lines)


def test_deepseek_client_soft_ceiling_trigger(tmp_path):
    """B6: Soft ceiling reached sets truncated=True without crashing."""
    log_dir = str(tmp_path / "logs")
    session_id = "ceiling-test"

    config = ReviewerEngineConfig(
        provider="deepseek",
        model="deepseek-flash",
        api_key_env="DUMMY_KEY",
        timeout_seconds=10,
    )
    client = DeepSeekClient(config)
    client.resolve_api_key = lambda: "dummy-key"

    # Generate 10 chunks of 100 characters each
    sse_lines = [
        f"data: {{\"choices\": [{{\"delta\": {{\"reasoning_content\": \"Chunk {i}: {'X' * 80} \"}}}}]}}\n".encode("utf-8")
        for i in range(10)
    ]
    sse_lines.append(b"data: [DONE]\n")

    mock_resp = MagicMock()
    mock_resp.__iter__.return_value = iter(sse_lines)
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        # Set soft token ceiling very low (e.g. 30 tokens)
        res = client.complete(
            messages=[{"role": "user", "content": "review"}],
            stream=True,
            session_id=session_id,
            log_dir=log_dir,
            soft_token_ceiling=30,
        )

    assert res["truncated"] is True
    assert res["finish_reason"] == "length"
    assert len(res["reasoning_content"]) > 0
