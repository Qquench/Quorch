# -*- coding: utf-8 -*-
"""Unit tests for ObservabilityPolicy and VerdictAuditSink.

Covers:
1. SinkMode enum values & MAX_RECORD_BYTES SSOT constant;
2. ObservabilityDecision frozen dataclass immutability;
3. Mode-driven policy resolution:
   - subagent / manual -> SNAPSHOT (stream bypassed, verdict enabled);
   - engine -> STREAM (stream enabled, verdict enabled);
   - disabled -> DISABLED (both disabled);
   - unknown mode conservative fallback to STREAM;
   - explicit_disable_verdict flag enforcement;
4. VerdictAuditSink file emission:
   - JSONL format with task_id, verdict_hash, generation (default 0), ts, payload;
   - Cross-process FileLock concurrency safety;
5. 16KB bounded structured truncation:
   - Strict physical UTF-8 byte measurement (len(line.encode('utf-8')) <= 16384);
   - Preserves outer keys and valid JSON parseability (never torn JSON);
   - Injects _truncated=True and _orig_bytes;
6. P0#1 zero stdout pollution guard.
"""
import json
import os
from pathlib import Path
import threading
from typing import List

import pytest

from observability_policy import (
    MAX_RECORD_BYTES,
    ObservabilityDecision,
    SinkMode,
    VerdictAuditSink,
    make_verdict_sink,
    resolve_observability_policy,
)


def test_sink_mode_and_constants():
    """验证 SinkMode 枚举值与 16KB 截断硬上限常数。"""
    assert SinkMode.STREAM == "stream"
    assert SinkMode.SNAPSHOT == "snapshot"
    assert SinkMode.DISABLED == "disabled"
    assert MAX_RECORD_BYTES == 16 * 1024


def test_observability_decision_immutability():
    """验证 ObservabilityDecision 为不可变冻结数据类。"""
    dec = ObservabilityDecision(
        mode=SinkMode.STREAM,
        stream_enabled=True,
        verdict_enabled=True,
        verdict_path="/tmp/verdicts.jsonl",
    )
    assert dec.max_record_bytes == 16 * 1024
    with pytest.raises(Exception):
        dec.stream_enabled = False  # frozen dataclass


def test_resolve_observability_policy_matrix(tmp_path: Path):
    """验证全模式分流矩阵决策。"""
    v_path = str(tmp_path / "v.jsonl")

    # 1. subagent 模式：物理旁路流式，但裁决通道恒开 (零空写 I/O 与完整审计链的平衡)
    dec_sub = resolve_observability_policy("subagent", verdict_path=v_path)
    assert dec_sub.mode == SinkMode.SNAPSHOT
    assert dec_sub.stream_enabled is False
    assert dec_sub.verdict_enabled is True
    assert os.path.isabs(dec_sub.verdict_path)

    # 2. manual 模式：同 subagent
    dec_man = resolve_observability_policy("manual", verdict_path=v_path)
    assert dec_man.mode == SinkMode.SNAPSHOT
    assert dec_man.stream_enabled is False
    assert dec_man.verdict_enabled is True

    # 3. engine 模式：流式写盘与裁决快照双开
    dec_eng = resolve_observability_policy("engine", verdict_path=v_path)
    assert dec_eng.mode == SinkMode.STREAM
    assert dec_eng.stream_enabled is True
    assert dec_eng.verdict_enabled is True

    # 4. disabled 模式：流式与裁决均禁用 (D4)
    dec_dis = resolve_observability_policy("disabled", verdict_path=v_path)
    assert dec_dis.mode == SinkMode.DISABLED
    assert dec_dis.stream_enabled is False
    assert dec_dis.verdict_enabled is False

    # 5. 显式禁用裁决开关 explicit_disable_verdict
    dec_no_v = resolve_observability_policy("engine", verdict_path=v_path, explicit_disable_verdict=True)
    assert dec_no_v.mode == SinkMode.STREAM
    assert dec_no_v.stream_enabled is True
    assert dec_no_v.verdict_enabled is False


def test_resolve_observability_policy_unknown_mode_conservative_fallback(tmp_path: Path, capfd):
    """验证未知非法模式保守退避至 STREAM 模式，并严守零 stdout 污染。"""
    v_path = str(tmp_path / "v.jsonl")
    dec = resolve_observability_policy("invalid_unknown_mode", verdict_path=v_path)
    assert dec.mode == SinkMode.STREAM
    assert dec.stream_enabled is True
    assert dec.verdict_enabled is True

    captured = capfd.readouterr()
    assert captured.out == "", f"Expected clean stdout, got: {captured.out!r}"
    assert "Unknown reviewer_mode" in captured.err


def test_verdict_sink_normal_write(tmp_path: Path):
    """验证普通体积裁决快照的正确落盘与字段契约。"""
    v_path = str(tmp_path / "logs" / "verdicts.jsonl")
    sink = make_verdict_sink(v_path)

    payload = {
        "status": "confirmed",
        "rationale": "Architecture boundaries satisfied",
        "affected_files": ["core.py", "server.py"],
    }
    sink.emit_verdict(
        task_id="1.3",
        verdict_hash="sha256:abcdef123456",
        payload=payload,
        generation=0,
    )

    assert os.path.exists(v_path)
    with open(v_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["task_id"] == "1.3"
    assert record["verdict_hash"] == "sha256:abcdef123456"
    assert record["generation"] == 0
    assert "ts" in record
    assert record["payload"]["status"] == "confirmed"
    assert record["payload"]["affected_files"] == ["core.py", "server.py"]
    assert len(lines[0].encode("utf-8")) <= MAX_RECORD_BYTES


def test_verdict_sink_16kb_bounded_structured_truncation(tmp_path: Path):
    """B4 & D11: 验证超大 payload (100KB) 在 16KB 物理字节边界处的结构化安全截断。"""
    v_path = str(tmp_path / "logs" / "oversize_verdicts.jsonl")
    sink = make_verdict_sink(v_path)

    huge_text = "重要架构推理与防御审计分析详情：" + ("X" * 100_000)
    payload = {
        "title": "Large Review Verdict",
        "details": huge_text,
        "score": 98,
    }

    sink.emit_verdict(
        task_id="2.1",
        verdict_hash="sha256:999888777",
        payload=payload,
        generation=1,
    )

    with open(v_path, "r", encoding="utf-8") as f:
        raw_line = f.readline()

    # 1. 物理字节硬上限严格校验（不含换行）
    raw_content = raw_line.rstrip("\r\n")
    byte_len = len(raw_content.encode("utf-8"))
    assert byte_len <= MAX_RECORD_BYTES, f"Record bytes {byte_len} exceeded MAX_RECORD_BYTES {MAX_RECORD_BYTES}"

    # 2. 结构完好性校验：绝非盲切，必须为合法可解析的 JSON
    parsed = json.loads(raw_content)
    assert parsed["task_id"] == "2.1"
    assert parsed["verdict_hash"] == "sha256:999888777"
    assert parsed["generation"] == 1
    assert "ts" in parsed

    # 3. 截断标记与原体积记录
    payload_res = parsed["payload"]
    assert payload_res["_truncated"] is True
    assert payload_res["_orig_bytes"] > 100_000
    assert payload_res["title"] == "Large Review Verdict"
    assert len(payload_res["details"]) > 0
    assert payload_res["details"].startswith("重要架构推理与防御审计分析详情：")


def test_verdict_sink_cross_process_file_locking_concurrency(tmp_path: Path):
    """D2: 验证多线程/跨进程并发写入时 FileLock 保护，杜绝行交错撕裂。"""
    v_path = str(tmp_path / "logs" / "concurrent_verdicts.jsonl")
    sink = make_verdict_sink(v_path)

    num_threads = 6
    records_per_thread = 20

    def worker(tid: int):
        for i in range(records_per_thread):
            sink.emit_verdict(
                task_id=f"t_{tid}_{i}",
                verdict_hash=f"hash_{tid}_{i}",
                payload={"thread": tid, "seq": i, "content": "A" * 500},
                generation=i,
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with open(v_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == num_threads * records_per_thread
    # 逐行校验均为合法且未撕裂的 JSON
    for line in lines:
        data = json.loads(line)
        assert "task_id" in data
        assert "verdict_hash" in data
        assert "payload" in data
