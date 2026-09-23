# -*- coding: utf-8 -*-
"""Adaptive Observability Policy & Verdict Audit Sink.

Decouples verbose streaming I/O from permanent decision evidence:
1. SinkMode: STREAM (engine), SNAPSHOT (subagent/manual), DISABLED;
2. ObservabilityDecision: Frozen metadata contract governing stream and verdict sinks;
3. VerdictAuditSink: Process-safe JSONL append with 16KB bounded structured truncation;
4. Zero vendor literals, zero stdout pollution, strict cross-process locking.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
import sys
from typing import Any, Mapping, Optional, Protocol

from filelock import FileLock

MAX_RECORD_BYTES: int = 16 * 1024  # 16KB 有界截断硬上限 (SSOT 常量 D11)


class SinkMode(str, Enum):
    """观测落盘模式。"""
    STREAM = "stream"       # engine 模式：流式 CoT -> RotatingFileSink, verdict_enabled=True
    SNAPSHOT = "snapshot"   # subagent/manual：物理旁路流式，仅裁决落盘, verdict_enabled=True
    DISABLED = "disabled"   # 离线/纯人工：流式与裁决均禁用, verdict_enabled=False (D4)


@dataclass(frozen=True)
class ObservabilityDecision:
    """观测策略决策快照（不可变契约）。"""
    mode: SinkMode
    stream_enabled: bool          # 仅 STREAM 为 True
    verdict_enabled: bool         # STREAM 与 SNAPSHOT 为 True，DISABLED 为 False (D4)
    verdict_path: str             # 归一化后的裁决快照落盘绝对路径 (D3)
    max_record_bytes: int = MAX_RECORD_BYTES


class VerdictAuditSink(Protocol):
    """裁决快照审计接口。"""
    def emit_verdict(
        self,
        *,
        task_id: str,
        verdict_hash: str,
        payload: Mapping[str, object],
        generation: int = 0,      # 不透明整型，解耦 1.4，默认 0 杜绝跳步 (D5)
    ) -> None:
        """安全原子追加一条裁决快照记录至审计清单。"""
        ...


def resolve_observability_policy(
    reviewer_mode: str,
    *,
    verdict_path: str,
    explicit_disable_verdict: bool = False,
) -> ObservabilityDecision:
    """模式驱动的拓扑自适应观测分流纯函数。

    - subagent / manual: 旁路流式写盘 (stream_enabled=False)，但保留裁决快照 (verdict_enabled=True)；
    - engine: 流式写盘与裁决快照双开；
    - disabled: 流式与裁决均禁用；
    - 未知模式: 保守退避至 STREAM 模式并记录告警。
    """
    normalized_path = os.path.abspath(os.path.normpath(verdict_path))
    raw_mode = (reviewer_mode or "").strip().lower()

    if raw_mode == "disabled":
        return ObservabilityDecision(
            mode=SinkMode.DISABLED,
            stream_enabled=False,
            verdict_enabled=False,
            verdict_path=normalized_path,
            max_record_bytes=MAX_RECORD_BYTES,
        )

    if raw_mode in ("subagent", "manual"):
        mode = SinkMode.SNAPSHOT
        stream_enabled = False
    elif raw_mode == "engine":
        mode = SinkMode.STREAM
        stream_enabled = True
    else:
        # 未知模式保守退避
        try:
            sys.stderr.write(f"[ObservabilityPolicy] Unknown reviewer_mode '{reviewer_mode}', falling back to STREAM\n")
            sys.stderr.flush()
        except Exception:
            pass
        mode = SinkMode.STREAM
        stream_enabled = True

    verdict_enabled = not explicit_disable_verdict

    return ObservabilityDecision(
        mode=mode,
        stream_enabled=stream_enabled,
        verdict_enabled=verdict_enabled,
        verdict_path=normalized_path,
        max_record_bytes=MAX_RECORD_BYTES,
    )


class FileVerdictAuditSink:
    """基于跨进程文件锁 (FileLock) 与结构化截断保护的 JSONL 裁决快照汇。"""

    def __init__(
        self,
        path: str,
        lock_path: Optional[str] = None,
        max_record_bytes: int = MAX_RECORD_BYTES,
    ) -> None:
        self.path = os.path.abspath(os.path.normpath(path))
        self.lock_path = lock_path if lock_path is not None else f"{self.path}.lock"
        self.max_record_bytes = max(int(max_record_bytes), 256)
        self._lock = FileLock(self.lock_path, timeout=5.0)

    def emit_verdict(
        self,
        *,
        task_id: str,
        verdict_hash: str,
        payload: Mapping[str, object],
        generation: int = 0,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        record: dict[str, Any] = {
            "task_id": str(task_id),
            "verdict_hash": str(verdict_hash),
            "generation": int(generation),
            "ts": ts,
            "payload": dict(payload),
        }

        raw_line = json.dumps(record, ensure_ascii=False)
        raw_bytes = raw_line.encode("utf-8")
        if len(raw_bytes) <= self.max_record_bytes:
            final_line = raw_line
        else:
            final_line = self._structured_truncate(record, orig_bytes=len(raw_bytes))

        dir_path = os.path.dirname(self.path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        try:
            with self._lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(final_line + "\n")
                    f.flush()
        except Exception as e:
            try:
                sys.stderr.write(f"[VerdictAuditSink] Failed to write verdict line: {e}\n")
                sys.stderr.flush()
            except Exception:
                pass

    def _structured_truncate(self, record: dict[str, Any], orig_bytes: int) -> str:
        payload_copy = dict(record["payload"])
        payload_copy["_truncated"] = True
        payload_copy["_orig_bytes"] = orig_bytes
        record["payload"] = payload_copy

        candidate = json.dumps(record, ensure_ascii=False)
        if len(candidate.encode("utf-8")) <= self.max_record_bytes:
            return candidate

        str_keys = [k for k, v in payload_copy.items() if isinstance(v, str) and not k.startswith("_")]
        if not str_keys:
            for k, v in list(payload_copy.items()):
                if not k.startswith("_"):
                    payload_copy[k] = str(v)[:100]
            str_keys = [k for k in payload_copy.keys() if not k.startswith("_")]

        str_keys.sort(key=lambda k: len(str(payload_copy[k])), reverse=True)
        for key in str_keys:
            orig_str = str(payload_copy[key])
            low = 0
            high = len(orig_str)
            best_str = ""
            while low <= high:
                mid = (low + high) // 2
                payload_copy[key] = orig_str[:mid]
                record["payload"] = payload_copy
                line = json.dumps(record, ensure_ascii=False)
                if len(line.encode("utf-8")) <= self.max_record_bytes:
                    best_str = orig_str[:mid]
                    low = mid + 1
                else:
                    high = mid - 1
            payload_copy[key] = best_str
            record["payload"] = payload_copy
            line = json.dumps(record, ensure_ascii=False)
            if len(line.encode("utf-8")) <= self.max_record_bytes:
                return line

        record["payload"] = {"_truncated": True, "_orig_bytes": orig_bytes}
        return json.dumps(record, ensure_ascii=False)


def make_verdict_sink(path: str, lock_path: Optional[str] = None) -> VerdictAuditSink:
    """创建跨进程线程安全的 VerdictAuditSink 实例。"""
    return FileVerdictAuditSink(path=path, lock_path=lock_path)
