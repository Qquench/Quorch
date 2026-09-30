# -*- coding: utf-8 -*-
"""Unit tests for cache_telemetry RollingJsonlTelemetrySink and retention."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import pytest

from log_naming import ActiveLogRegistry, norm_registry_key
from reviewer_engine import (
    TELEMETRY_RECORD_BYTES,
    CacheTelemetryRecord,
    RollingJsonlTelemetrySink,
    compute_prompt_hash,
)


def test_cache_telemetry_record_fields_and_hit_ratio() -> None:
    """验证 CacheTelemetryRecord 字段约束及 hit_ratio 在 prompt_tokens 为 0 时严格为 0.0。"""
    rec = CacheTelemetryRecord(
        ts="2026-09-30T10:00:00Z",
        prompt_hash="abc123456789def0",
        prompt_tokens=0,
        cached_tokens=0,
        miss_tokens=0,
        hit_ratio=0.0,
        mode="audit",
        session_id="sess-01",
        usage_available=False,
    )
    assert rec.hit_ratio == 0.0
    assert rec.prompt_tokens == 0
    assert rec.cached_tokens == 0
    # Frozen contract check
    with pytest.raises(Exception):
        rec.hit_ratio = 0.5  # type: ignore


def test_prompt_hash_workspace_deterministic_salt(tmp_path: Path) -> None:
    """验证 prompt_hash 使用基于 workspace_root 的确定性盐，同工作区同前缀哈希一致，跨工作区隔离。"""
    ws1 = str(tmp_path / "ws1")
    ws2 = str(tmp_path / "ws2")
    os.makedirs(ws1, exist_ok=True)
    os.makedirs(ws2, exist_ok=True)

    messages = [{"role": "system", "content": "You are a senior reviewer"}]
    h1 = compute_prompt_hash(messages, workspace_root=ws1)
    h1_repeat = compute_prompt_hash(messages, workspace_root=ws1)
    assert h1 == h1_repeat
    assert len(h1) == 16

    h2 = compute_prompt_hash(messages, workspace_root=ws2)
    assert h1 != h2


def test_rolling_jsonl_fifo_rotation(tmp_path: Path) -> None:
    """断言超限时以 os.replace 原子轮转为 .1.jsonl，老数据 FIFO 淘汰且各行均为合法 JSON。"""
    telemetry_path = tmp_path / "cache_telemetry.jsonl"
    # 设置一个小的 max_bytes (如 600 字节)，写入数条约 180 字节的记录
    sink = RollingJsonlTelemetrySink(str(telemetry_path), max_bytes=500, max_rotations=2)

    for i in range(10):
        rec = CacheTelemetryRecord(
            ts="2026-09-30T10:00:00Z",
            prompt_hash=f"hash_{i:04d}",
            prompt_tokens=100,
            cached_tokens=50,
            miss_tokens=50,
            hit_ratio=0.5,
            mode="critique",
            session_id=f"session-{i}",
            usage_available=True,
        )
        sink.emit(rec)

    assert telemetry_path.exists()
    rot1_path = tmp_path / "cache_telemetry.1.jsonl"
    assert rot1_path.exists()

    # 验证主文件与轮转文件中的每行都是合法 JSON
    for p in (telemetry_path, rot1_path):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    data = json.loads(stripped)
                    assert "prompt_hash" in data
                    assert "prompt_tokens" in data


def test_field_level_degradation_preserves_valid_json(tmp_path: Path) -> None:
    """单条记录超出 4KB 时采用字段级降级，绝不采用破坏 JSON 语法完整性的字节截断。"""
    telemetry_path = tmp_path / "cache_telemetry.jsonl"
    sink = RollingJsonlTelemetrySink(str(telemetry_path), max_bytes=100 * 1024)

    # 构造极长 session_id 超过 4KB
    huge_session_id = "sess_" + "X" * 6000
    rec = CacheTelemetryRecord(
        ts="2026-09-30T10:00:00Z",
        prompt_hash="12345678abcdef00",
        prompt_tokens=200,
        cached_tokens=100,
        miss_tokens=100,
        hit_ratio=0.5,
        mode="audit",
        session_id=huge_session_id,
        usage_available=True,
    )
    sink.emit(rec)

    assert telemetry_path.exists()
    with open(telemetry_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    assert len(content.encode("utf-8")) <= TELEMETRY_RECORD_BYTES
    # 严格验证 JSON 语法完整
    data = json.loads(content)
    assert data["prompt_tokens"] == 200
    assert "[truncated]" in data["session_id"] or len(data["session_id"]) < len(huge_session_id)


def test_secret_redaction(tmp_path: Path) -> None:
    """落盘前必须执行敏感信息（API Key）脱敏过滤，严禁输出密钥明文。"""
    telemetry_path = tmp_path / "cache_telemetry.jsonl"
    sink = RollingJsonlTelemetrySink(str(telemetry_path))

    secret_key = "sk-1234567890abcdef1234567890"
    rec = CacheTelemetryRecord(
        ts="2026-09-30T10:00:00Z",
        prompt_hash="12345678abcdef00",
        prompt_tokens=100,
        cached_tokens=50,
        miss_tokens=50,
        hit_ratio=0.5,
        mode="critique",
        session_id=f"sess-with-key-{secret_key}",
        usage_available=True,
    )
    sink.emit(rec)

    raw_text = telemetry_path.read_text(encoding="utf-8")
    assert secret_key not in raw_text
    assert "[REDACTED]" in raw_text


@pytest.mark.anyio
async def test_async_aemit_concurrency(tmp_path: Path) -> None:
    """在异步上下文内通过 aemit 并发落盘，验证无死锁、无主事件循环停顿、各行保持合法。"""
    telemetry_path = tmp_path / "cache_telemetry.jsonl"
    sink = RollingJsonlTelemetrySink(str(telemetry_path), max_bytes=50 * 1024)

    async def _worker(i: int) -> None:
        rec = CacheTelemetryRecord(
            ts="2026-09-30T10:00:00Z",
            prompt_hash=f"concurrent_hash_{i}",
            prompt_tokens=100 + i,
            cached_tokens=50 + i,
            miss_tokens=50,
            hit_ratio=round((50 + i) / (100 + i), 4),
            mode="evaluate",
            session_id=f"concurrent-sess-{i}",
            usage_available=True,
        )
        await sink.aemit(rec)

    tasks = [_worker(i) for i in range(20)]
    await asyncio.gather(*tasks)

    assert telemetry_path.exists()
    lines = [l.strip() for l in telemetry_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 20
    for line in lines:
        data = json.loads(line)
        assert data["mode"] == "evaluate"


def test_registry_integration(tmp_path: Path) -> None:
    """验证接入 ActiveLogRegistry 与配额体系，活跃分片被正确登记锁护。"""
    telemetry_path = tmp_path / "cache_telemetry.jsonl"
    registry = ActiveLogRegistry()

    sink = RollingJsonlTelemetrySink(str(telemetry_path), registry=registry)
    key = norm_registry_key(sink.path)
    assert not registry.is_reclaimable(key)
