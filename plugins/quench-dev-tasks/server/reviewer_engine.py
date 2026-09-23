# -*- coding: utf-8 -*-
"""Quench Reviewer Engine: 深度思考审查模型客户端与 Prompt 组装器.

负责连接高阶推理审查模型 (Reviewer)，组装高命中率的静态架构上下文缓存前缀，
并为任务规约强化 (Spec Refine) 与架构疑难升级 (Escalate) 提供确定性分析能力。
具备非阻塞异步线程卸载 (acomplete/stream_chat)、企业网络异常防御与总耗时预算熔断。
"""
from __future__ import annotations

import codecs
import functools
import hashlib
import json
import os
import queue
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    NamedTuple,
    Optional,
    Protocol,
    TextIO,
    Tuple,
    TypedDict,
    Union,
)

import anyio

from project_config import QuenchStackConfig, ReviewerEngineConfig
from observability_policy import (
    MAX_RECORD_BYTES,
    ObservabilityDecision,
    SinkMode,
    VerdictAuditSink,
    make_verdict_sink,
    resolve_observability_policy,
)

# Windows UTF-8 控制台设防
if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 模块级并发限制器：限制同时在途的审查请求，防止突发流量触发 429 流控与 TLS 握手风暴
_REVIEWER_LIMITER = anyio.CapacityLimiter(4)
MAX_RESPONSE_BYTES = 1024 * 1024  # 1 MiB 响应体积硬上限


# ---- 异常体系（厂商中立，禁止硬编码厂商字面量）----
class ReviewerError(RuntimeError):
    """Reviewer 体系通用基类异常。"""
    pass


class ReviewerAuthError(ReviewerError):
    """身份鉴权或访问受限异常 (HTTP 401 / 403)。不可重试。"""
    pass


class ReviewerTimeoutError(ReviewerError):
    """通信或执行超时异常。"""
    pass


class ReviewerNotConfiguredError(ReviewerError):
    """Reviewer 引擎未配置或不可用。不可重试。"""
    pass


# 向后兼容别名与继承（保证现有捕获语句 100% 兼容）
class ReviewerEngineError(ReviewerError):
    """Reviewer Engine 基础异常 (向后兼容别名)。"""
    pass


class ReviewerEngineUnavailableError(ReviewerNotConfiguredError, ReviewerEngineError):
    """Reviewer 引擎不可用（未配置或缺少 API Key）。"""
    pass


class ReviewerAuthenticationError(ReviewerAuthError, ReviewerEngineError):
    """身份鉴权失败（401 Unauthorized）。不可重试。"""
    pass


class ReviewerBadRequestError(ReviewerEngineError):
    """请求参数非法（400 Bad Request）。不可重试。"""
    pass


class ReviewerRateLimitError(ReviewerEngineError):
    """触发流控限制（429 Too Many Requests）。可重试。"""
    pass


# ---- 数据结构 ----
@dataclass(frozen=True)
class UsageSnapshot:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0          # Prompt Cache 命中（跨厂商归一化）
    reasoning_tokens: int = 0
    provider_label: str = "generic"  # 运行时注入，禁止模块级厂商常量


@dataclass(frozen=True)
class StreamChunk:
    text: str = ""
    reasoning: str = ""
    usage: Optional[UsageSnapshot] = None
    done: bool = False


class ThoughtChunk(NamedTuple):
    content: str
    is_thought: bool
    tokens_estimate: int


class ProgressSink(Protocol):
    def on_chunk(self, chunk: ThoughtChunk) -> None: ...
    def on_heartbeat(self, tokens_so_far: int, elapsed_s: float) -> None: ...
    def on_finish(self, reason: str, meta: Dict[str, Any]) -> None: ...


_SECRET_REDACTION_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{20,}")


# ---- 通用探针（纯函数，无副作用，绝不抛异常）----
def _dig(payload: Any, *path: str) -> Any:
    """安全逐级取值纯函数，任一层缺失或非 Mapping 即返回 None。"""
    curr = payload
    for key in path:
        if not isinstance(curr, Mapping):
            return None
        curr = curr.get(key)
        if curr is None:
            return None
    return curr


def extract_reasoning_text(payload: Any) -> str:
    """从上游响应 payload 中以通用探针提取思考链/推理文本。纯函数，无副作用，绝不抛异常。"""
    if not isinstance(payload, Mapping):
        return ""

    target = payload
    choices = payload.get("choices")
    if isinstance(choices, list) and len(choices) > 0 and isinstance(choices[0], Mapping):
        target = choices[0]

    paths: List[Tuple[str, ...]] = [
        ("delta", "reasoning_content"),
        ("delta", "thought"),
        ("delta", "reasoning"),
        ("message", "reasoning_content"),
        ("message", "thought"),
        ("message", "reasoning"),
        ("reasoning_content",),
        ("thought",),
        ("reasoning",),
    ]

    for path in paths:
        val = _dig(target, *path)
        if isinstance(val, str) and val:
            return val

    if target is not payload:
        for path in paths:
            val = _dig(payload, *path)
            if isinstance(val, str) and val:
                return val

    return ""


def extract_cached_tokens(payload: Any) -> int:
    """提取 Prompt Cache 命中 token 数，依次探测 4 种跨厂商形态。纯函数，无副作用，绝不抛异常。"""
    if not isinstance(payload, Mapping):
        return 0

    usage_dict = payload.get("usage")
    target = usage_dict if isinstance(usage_dict, Mapping) else payload

    candidates: List[Tuple[str, ...]] = [
        ("prompt_cache_hit_tokens",),
        ("prompt_tokens_details", "cached_tokens"),
        ("cache_read_input_tokens",),
        ("cached_tokens",),
    ]

    for path in candidates:
        val = _dig(target, *path)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
            return val
        if target is not payload:
            val_root = _dig(payload, "usage", *path)
            if isinstance(val_root, int) and not isinstance(val_root, bool) and val_root >= 0:
                return val_root

    return 0


def extract_usage(payload: Any, provider_label: str = "generic") -> UsageSnapshot:
    """提取归一化用量快照 UsageSnapshot。纯函数，无副作用，绝不抛异常。"""
    if not isinstance(payload, Mapping):
        return UsageSnapshot(provider_label=provider_label)

    usage_dict = payload.get("usage")
    u = usage_dict if isinstance(usage_dict, Mapping) else payload

    prompt_tokens = 0
    completion_tokens = 0
    reasoning_tokens = 0

    pt = u.get("prompt_tokens")
    if isinstance(pt, int) and not isinstance(pt, bool):
        prompt_tokens = max(0, pt)

    ct = u.get("completion_tokens")
    if isinstance(ct, int) and not isinstance(ct, bool):
        completion_tokens = max(0, ct)

    rt = _dig(u, "completion_tokens_details", "reasoning_tokens")
    if not (isinstance(rt, int) and not isinstance(rt, bool)):
        rt = u.get("reasoning_tokens")
    if isinstance(rt, int) and not isinstance(rt, bool):
        reasoning_tokens = max(0, rt)

    cached_tokens = extract_cached_tokens(payload)

    return UsageSnapshot(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
        provider_label=provider_label,
    )


def _is_local_endpoint(base_url: str) -> bool:
    """判断端点是否为本地/私网回路。"""
    try:
        parsed = urllib.parse.urlparse(base_url)
        host = (parsed.hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
    except Exception:
        return False


def _normalize_chat_endpoint(base_url: str) -> str:
    """幂等拼接 /chat/completions 端点路径。"""
    clean_url = (base_url or "").strip().rstrip("/")
    if clean_url.endswith("/chat/completions"):
        return clean_url
    return f"{clean_url}/chat/completions"


class RotatingFileSink:
    """Live write-time capped log sink with carry-over desensitization and rotation.
    Writes strictly to latest-<session_id>.log.
    When max_bytes is reached, rotates to latest-<session_id>.1.log rather than truncating in place (T6-2).
    Pre-write redaction via 64B carry-over window (T6-3).
    """

    def __init__(
        self,
        log_dir: str,
        session_id: str,
        max_bytes: int = 1024 * 1024,
        carry_over_bytes: int = 64,
        flush_interval_s: float = 0.5,
    ):
        clean_sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id))
        self.log_dir = os.path.abspath(log_dir)
        self.session_id = clean_sid
        self.max_bytes = max(max_bytes, 1024)
        self.carry_over_bytes = max(carry_over_bytes, 16)
        self.flush_interval_s = max(flush_interval_s, 0.1)

        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, f"latest-{self.session_id}.log")
        self.rot_file = os.path.join(self.log_dir, f"latest-{self.session_id}.1.log")

        self._carry_over = ""
        self._written_bytes = 0
        self._last_flush = time.monotonic()
        self._fp = open(self.log_file, "w", encoding="utf-8", errors="replace")
        self._is_closed = False

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if self._written_bytes + incoming_bytes > self.max_bytes:
            if not self._fp.closed:
                self._fp.flush()
                self._fp.close()
            try:
                if os.path.exists(self.rot_file):
                    os.remove(self.rot_file)
                if os.path.exists(self.log_file):
                    os.replace(self.log_file, self.rot_file)
            except Exception:
                pass
            self._fp = open(self.log_file, "w", encoding="utf-8", errors="replace")
            marker = f"[... ROTATED AT {self.max_bytes // 1024}KB ...]\n"
            self._fp.write(marker)
            self._written_bytes = len(marker.encode("utf-8"))

    def write_chunk_text(self, text: str) -> None:
        if self._is_closed:
            return
        combined = self._carry_over + text
        redacted = _SECRET_REDACTION_PATTERN.sub("[REDACTED]", combined)

        if len(redacted) > self.carry_over_bytes:
            to_write = redacted[: -self.carry_over_bytes]
            self._carry_over = redacted[-self.carry_over_bytes :]
        else:
            to_write = ""
            self._carry_over = redacted

        if to_write:
            data_bytes = to_write.encode("utf-8")
            self._rotate_if_needed(len(data_bytes))
            self._fp.write(to_write)
            self._written_bytes += len(data_bytes)

            now = time.monotonic()
            if now - self._last_flush >= self.flush_interval_s:
                self._fp.flush()
                self._last_flush = now

    def on_chunk(self, chunk: ThoughtChunk) -> None:
        self.write_chunk_text(chunk.content)

    def on_heartbeat(self, tokens_so_far: int, elapsed_s: float) -> None:
        if not self._is_closed and not self._fp.closed:
            self._fp.flush()

    def on_finish(self, reason: str, meta: Dict[str, Any]) -> None:
        self.close()

    def flush(self) -> None:
        """显式刷新写缓冲区至底层磁盘文件。"""
        if not self._is_closed and not self._fp.closed:
            try:
                self._fp.flush()
                self._last_flush = time.monotonic()
            except Exception:
                pass

    def close(self) -> None:
        if not self._is_closed:
            self._is_closed = True
            try:
                if self._carry_over:
                    final_text = _SECRET_REDACTION_PATTERN.sub("[REDACTED]", self._carry_over)
                    self._carry_over = ""
                    data_bytes = final_text.encode("utf-8")
                    self._rotate_if_needed(len(data_bytes))
                    self._fp.write(final_text)
                    self._written_bytes += len(data_bytes)
                if not self._fp.closed:
                    self._fp.flush()
                    self._fp.close()
            except Exception:
                pass


@dataclass(frozen=True)
class CoalescingStats:
    """行聚合落盘 Sink 运行指标快照。"""
    lines_emitted: int
    total_chars_fed: int             # 累计喂入字符总量（单调递增）
    chars_currently_buffered: int    # 瞬时滞留待刷盘字符量（非单调）
    chunks_fed: int                  # 累计喂入分片数（单调递增）


class CoalescingTextSink:
    """将流式文本分片聚合并按行/尺寸/空闲边界落盘，杜绝分片级写行。

    - 按自然换行 `\n` 切分完整行输出；
    - 空白行直接写 `\n`，严保 Markdown 语义完整，不掺时间戳；
    - 非空行前缀 `<iso_ts> [<tag>] <line>\n`；
    - 超过 max_line_chars 强制切分；
    - 空闲超时 (idle_flush_seconds) 后台 watchdog 自动刷盘，保障实时可观测性；
    - close() / flush(force=True) 强制刷盘尾残内容（零丢损）；
    - 内部锁保护，严格早于底层 FileSink 锁，严禁反向交叉持锁。
    """

    def __init__(
        self,
        emit_line: Callable[[str], None],
        *,
        tag: str = "reasoning",
        max_line_chars: int = 400,
        idle_flush_seconds: float = 0.4,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._emit_line = emit_line
        self.tag = tag or "reasoning"
        self.max_line_chars = max(int(max_line_chars), 64)
        self.idle_flush_seconds = float(idle_flush_seconds)
        self._clock = clock if clock is not None else (lambda: time.monotonic())
        self._lock = threading.Lock()
        self._pending = ""
        self._lines_emitted = 0
        self._total_chars_fed = 0
        self._chunks_fed = 0
        self._last_feed_t = self._clock()
        self._closed = False
        self._watchdog_timer: Optional[threading.Timer] = None

    def feed(self, fragment: str) -> None:
        """喂入文本分片。若遇到换行符或超过长度/空闲阈值则触发切行输出。"""
        if fragment is None:
            fragment = ""
        with self._lock:
            if self._closed:
                return
            now = self._clock()
            # 若已有滞留文本且距离上次喂入超时，先将滞留文本作为一行刷出
            if self._pending and self.idle_flush_seconds > 0 and (now - self._last_feed_t >= self.idle_flush_seconds):
                self._flush_tail_locked()
            self._last_feed_t = now
            self._chunks_fed += 1
            if fragment:
                self._total_chars_fed += len(fragment)
                self._pending += fragment
                self._emit_ready_lines_locked()

            if self._pending and self.idle_flush_seconds > 0:
                self._arm_watchdog_locked(self.idle_flush_seconds)
            elif not self._pending and self._watchdog_timer is not None:
                try:
                    self._watchdog_timer.cancel()
                except Exception:
                    pass
                self._watchdog_timer = None

    def flush(self, *, force: bool = False) -> None:
        """刷新滞留文本。若 force=True 则无条件将滞留尾残刷出。"""
        with self._lock:
            if self._closed:
                return
            if force:
                self._flush_tail_locked()
            else:
                now = self._clock()
                if self._pending and self.idle_flush_seconds > 0 and (now - self._last_feed_t >= self.idle_flush_seconds):
                    self._flush_tail_locked()

    def close(self) -> None:
        """关闭汇聚器。强制刷盘尾残内容（零丢损）并取消定时器。幂等调用。"""
        with self._lock:
            if self._closed:
                return
            if self._watchdog_timer is not None:
                try:
                    self._watchdog_timer.cancel()
                except Exception:
                    pass
                self._watchdog_timer = None
            self._flush_tail_locked(is_close=True)
            self._closed = True

    def __enter__(self) -> "CoalescingTextSink":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    @property
    def stats(self) -> CoalescingStats:
        """获取当前聚合指标的只读快照。"""
        with self._lock:
            return CoalescingStats(
                lines_emitted=self._lines_emitted,
                total_chars_fed=self._total_chars_fed,
                chars_currently_buffered=len(self._pending),
                chunks_fed=self._chunks_fed,
            )

    def _arm_watchdog_locked(self, delay: float) -> None:
        if self._closed:
            return
        if self._watchdog_timer is not None:
            try:
                self._watchdog_timer.cancel()
            except Exception:
                pass
            self._watchdog_timer = None
        if self._pending:
            self._watchdog_timer = threading.Timer(delay, self._on_watchdog)
            self._watchdog_timer.daemon = True
            self._watchdog_timer.start()

    def _on_watchdog(self) -> None:
        with self._lock:
            if self._closed or not self._pending:
                return
            now = self._clock()
            idle = now - self._last_feed_t
            if idle >= self.idle_flush_seconds:
                self._flush_tail_locked()
            else:
                remaining = max(0.01, self.idle_flush_seconds - idle)
                self._arm_watchdog_locked(remaining)

    def _emit_ready_lines_locked(self) -> None:
        while True:
            pos = self._pending.find("\n")
            if pos != -1 and pos <= self.max_line_chars:
                raw_line = self._pending[:pos]
                self._pending = self._pending[pos + 1 :]
                if raw_line.endswith("\r"):
                    raw_line = raw_line[:-1]
                self._emit_formatted_locked(raw_line)
            elif len(self._pending) >= self.max_line_chars:
                raw_line = self._pending[: self.max_line_chars]
                self._pending = self._pending[self.max_line_chars :]
                self._emit_formatted_locked(raw_line)
            else:
                break

    def _flush_tail_locked(self, *, is_close: bool = False) -> None:
        if not self._pending:
            return
        self._emit_ready_lines_locked()
        if self._pending:
            raw_line = self._pending
            self._pending = ""
            if raw_line.endswith("\r"):
                raw_line = raw_line[:-1]
            self._emit_formatted_locked(raw_line, is_close=is_close)

    def _emit_formatted_locked(self, raw_line: str, *, is_close: bool = False) -> None:
        if not raw_line.strip():
            formatted = "\n"
        else:
            iso_ts = datetime.now(timezone.utc).isoformat()
            formatted = f"{iso_ts} [{self.tag}] {raw_line}\n"

        try:
            self._emit_line(formatted)
            self._lines_emitted += 1
        except Exception as e:
            try:
                sys.stderr.write(f"[CoalescingTextSink] emit_line failed: {e}\n")
                sys.stderr.flush()
            except Exception:
                pass
            if is_close:
                pass


class AdaptiveHeartbeatSink:
    """能力分发式心跳：向所有可用通道 fan-out，FILE 常驻兜底，严格遵守零 stdout 污染。

    通道分发：
    1. file_emit (强制必填): 无论任何环境均常驻追加 [progress] 记录至会话日志，永不失联；
    2. mcp_context: 若注入 FastMCP 上下文，调用 report_progress / info；
    3. stderr: 仅在 isatty 为真时进行动态 \r 覆盖输出；
    4. 零 stdout 污染 (P0#1 铁律)：严禁向 sys.stdout 输出任何字符。
    """

    def __init__(
        self,
        *,
        file_emit: Callable[[str], None],
        mcp_context: Any = None,
        stderr: Optional[TextIO] = None,
        interval_ms: int = 1000,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if file_emit is None or not callable(file_emit):
            raise ValueError(
                "AdaptiveHeartbeatSink requires a callable 'file_emit' channel as a mandatory last-resort fallback."
            )
        self.file_emit = file_emit
        self.mcp_context = mcp_context
        self.stderr = stderr if stderr is not None else sys.stderr
        self.interval_s = max(int(interval_ms), 500) / 1000.0
        self._clock = clock if clock is not None else (lambda: time.monotonic())
        self._lock = threading.Lock()
        self._last_pulse_monotonic = 0.0
        self._pulse_count = 0
        self._is_tty = bool(self.stderr and hasattr(self.stderr, "isatty") and self.stderr.isatty())
        self._disabled_channels: set[str] = set()

    def on_chunk(self, chunk: ThoughtChunk) -> None:
        pass

    def on_heartbeat(self, tokens_so_far: int, elapsed_s: float) -> None:
        with self._lock:
            now = self._clock()
            jitter = random.uniform(0.0, 0.015)
            if (now - self._last_pulse_monotonic) < (self.interval_s + jitter):
                return
            self._last_pulse_monotonic = now
            self._pulse_count += 1
            msg = f"[Reviewer 思考中: {tokens_so_far} tokens | {elapsed_s:.1f}s]"
            iso_ts = datetime.now(timezone.utc).isoformat()
            file_msg = f"{iso_ts} [progress] {msg}\n"

        # 1. FILE 常驻兜底通道
        if "file" not in self._disabled_channels:
            try:
                self.file_emit(file_msg)
            except Exception:
                self._disabled_channels.add("file")

        # 2. MCP 上下文通道
        if self.mcp_context is not None and "mcp" not in self._disabled_channels:
            try:
                if hasattr(self.mcp_context, "info"):
                    res = self.mcp_context.info(msg)
                    if asyncio.iscoroutine(res):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(res)
                        except RuntimeError:
                            pass
                elif hasattr(self.mcp_context, "report_progress"):
                    res = self.mcp_context.report_progress(tokens_so_far, 64000)
                    if asyncio.iscoroutine(res):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(res)
                        except RuntimeError:
                            pass
            except Exception:
                self._disabled_channels.add("mcp")

        # 3. stderr (TTY)
        if self._is_tty and "stderr" not in self._disabled_channels:
            try:
                self.stderr.write(f"\r{msg}...")
                self.stderr.flush()
            except Exception:
                self._disabled_channels.add("stderr")

    async def apulse(self, *, tokens_so_far: int, elapsed_s: float, step: str = "thinking") -> None:
        with self._lock:
            now = self._clock()
            jitter = random.uniform(0.0, 0.015)
            if (now - self._last_pulse_monotonic) < (self.interval_s + jitter):
                return
            self._last_pulse_monotonic = now
            self._pulse_count += 1
            msg = f"[Reviewer 思考中: {tokens_so_far} tokens | {elapsed_s:.1f}s]"
            iso_ts = datetime.now(timezone.utc).isoformat()
            file_msg = f"{iso_ts} [progress] {msg}\n"

        # 1. FILE 常驻兜底通道
        if "file" not in self._disabled_channels:
            try:
                self.file_emit(file_msg)
            except Exception:
                self._disabled_channels.add("file")

        # 2. MCP 上下文通道
        if self.mcp_context is not None and "mcp" not in self._disabled_channels:
            try:
                if hasattr(self.mcp_context, "info"):
                    res = self.mcp_context.info(msg)
                    if asyncio.iscoroutine(res):
                        await res
                elif hasattr(self.mcp_context, "report_progress"):
                    res = self.mcp_context.report_progress(tokens_so_far, 64000)
                    if asyncio.iscoroutine(res):
                        await res
            except Exception:
                self._disabled_channels.add("mcp")

        # 3. stderr (TTY)
        if self._is_tty and "stderr" not in self._disabled_channels:
            try:
                self.stderr.write(f"\r{msg}...")
                self.stderr.flush()
            except Exception:
                self._disabled_channels.add("stderr")

    def on_finish(self, reason: str, meta: Dict[str, Any]) -> None:
        if self._is_tty and self._pulse_count > 0:
            try:
                self.stderr.write("\n")
                self.stderr.flush()
            except Exception:
                pass


class TelemetryRecord(TypedDict):
    schema: Literal[1]
    ts: str
    session_id: str
    event: Literal["start", "tick", "warn_repetition", "finish"]
    elapsed_ms: int
    tokens_out: int
    repetition_score: float
    truncated: bool
    advisory: Optional[str]


def log_telemetry_event(
    log_dir: str,
    record: TelemetryRecord,
) -> None:
    """Append-only, fail-open JSONL telemetry logger with schema: 1."""
    try:
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "telemetry.jsonl")
        line = json.dumps(record, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        try:
            if sys.stderr and hasattr(sys.stderr, "write"):
                sys.stderr.write(f"[Telemetry Warning] Failed to log telemetry: {e}\n")
        except Exception:
            pass


def compute_repetition_score(text: str, n_gram: int = 4) -> float:
    """Compute lexical repetition score based on n-gram diversity.
    Returns 0.0 (low repetition) to 1.0 (high repetition / loop).
    """
    if len(text) < 80:
        return 0.0
    words = text.split()
    if len(words) < 15:
        return 0.0
    ngrams = [tuple(words[i : i + n_gram]) for i in range(len(words) - n_gram + 1)]
    if not ngrams:
        return 0.0
    unique = len(set(ngrams))
    total = len(ngrams)
    rep = 1.0 - (unique / total)
    return round(max(0.0, min(1.0, rep)), 4)


def _read_windows_env_var(var_name: str) -> Optional[str]:
    """安全读取 Windows 注册表环境变量（支持 HKCU 与 HKLM，免重启 IDE/终端）。
    抽离为模块级无副作用函数以保障跨平台与 CI 单元测试的可 Patch 隔离性。
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg  # type: ignore

        # 1. 优先检查当前用户级变量 (HKCU)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                val, _ = winreg.QueryValueEx(key, var_name)
                if val and str(val).strip():
                    return str(val).strip()
        except (FileNotFoundError, OSError):
            pass

        # 2. 兜底检查机器系统级变量 (HKLM)
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            ) as key:
                val, _ = winreg.QueryValueEx(key, var_name)
                if val and str(val).strip():
                    return str(val).strip()
        except (FileNotFoundError, OSError):
            pass
    except Exception:
        pass
    return None


class PromptAssembler:
    """静态系统提示词组装器。
    
    ★ 核心防线：为保障 Prompt Cache 极致命中率，
    本组装器组装的 System Prompt 必须保持绝对纯洁，严禁拼接任何动态时间戳、动态会话 ID 或随机数。
    """

    @staticmethod
    def build_static_system_prefix(workspace_root: str, config: QuenchStackConfig) -> str:
        """加载项目全局架构文档、工程约束与审查纪律规范，构建稳定的系统级缓存前缀。"""
        parts: List[str] = [
            "# Role & Mission: Senior System Architect & Specification Reviewer\n",
            "You are the Senior Architecture Reviewer operating within the Quench development governance framework.\n",
            "Your role is to conduct red-team architectural critique, identify edge-case risks, eliminate concurrency deadlocks, ",
            "and formulate rigorous Six-Core-Field DevTasks with mandatory test assertions for execution models.\n\n",
        ]

        # 1. 挂载全局架构设计文档（若配置）
        arch_doc_rel = config.architecture_doc
        if arch_doc_rel:
            arch_doc_abs = os.path.normpath(os.path.join(workspace_root, arch_doc_rel))
            if os.path.isfile(arch_doc_abs):
                try:
                    with open(arch_doc_abs, "r", encoding="utf-8", errors="ignore") as f:
                        arch_content = f.read().strip()
                    parts.append("## 1. Project Global Architecture & Domain Specifications (Static Baseline)\n")
                    parts.append(f"Source file: `{arch_doc_rel}`\n```markdown\n{arch_content}\n```\n\n")
                except Exception:
                    pass

        # 2. 挂载项目法定工程约束 (Constraints)
        if config.constraints:
            parts.append("## 2. Project Engineering Constraints & Boundaries (Rigid Rules)\n")
            for c in config.constraints:
                parts.append(f"- {c}\n")
            parts.append("\n")

        # 3. 挂载 Quench 六大核心字段标准与审查纪律
        rules_path = os.path.normpath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "rules",
                "dev-tasks-discipline.md",
            )
        )
        if os.path.isfile(rules_path):
            try:
                with open(rules_path, "r", encoding="utf-8", errors="ignore") as f:
                    rules_content = f.read().strip()
                parts.append("## 3. Quench Six Core Fields Standard & Review Discipline\n")
                parts.append(f"```markdown\n{rules_content}\n```\n\n")
            except Exception:
                pass

        parts.append(
            "## 4. Reviewer Instructions & Output Contract\n"
            "When refining draft tasks or performing architectural evaluations:\n"
            "1. Deeply check state machine transitions, concurrent race conditions, boundary overflows, and offline fallbacks;\n"
            "2. Always provide concrete, executable [DoD Verification Commands / DoD 验证命令] with mandatory test assertions;\n"
            "3. Strictly maintain the six core fields in valid Quench markdown format.\n"
        )

        return "".join(parts)

    @staticmethod
    def get_prefix_hash(prefix: str) -> str:
        """获取静态前缀的 SHA256 指纹前 16 位，用于 Prompt Cache 命中审计与观测。"""
        return hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def assemble_messages(static_prefix: str, dynamic_turns: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """从结构上强制保证静态前缀作为第 1 个 system message，确保最长缓存前缀不被破坏。"""
        return [{"role": "system", "content": static_prefix}, *dynamic_turns]


class ReviewerClient:
    """基于标准库与 AnyIO 实现的工业级厂商中立 Reviewer 客户端。
    支持任意 OpenAI 兼容的 /chat/completions 端点。
    具备异步非阻塞调度 (acomplete/stream_chat)、退避重试、跨厂商思考链探针与总耗时预算熔断。
    """

    def __init__(
        self,
        config: Optional[ReviewerEngineConfig] = None,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key_env: Optional[str] = None,
        provider_label: str = "generic",
        timeout_seconds: int = 60,
        max_retries: int = 2,
        thinking: bool = True,
        reasoning_effort: Literal["low", "medium", "high"] = "high",
        sink: Optional[ProgressSink] = None,
    ):
        if config is not None:
            self.config = config
            url_val = (base_url or getattr(config, "base_url", "")).strip()
            prov = getattr(config, "provider", None)
            self.provider_label = provider_label if provider_label != "generic" else (prov or "generic")
            if not url_val and self.provider_label:
                from project_config import resolve_preset
                preset = resolve_preset(self.provider_label)
                if preset and preset.base_url:
                    url_val = preset.base_url
            self.base_url = url_val
            self.model = model or getattr(config, "model", "")
            self.api_key_env = api_key_env if api_key_env is not None else getattr(config, "api_key_env", None)
            self.timeout_seconds = timeout_seconds if timeout_seconds != 60 else getattr(config, "timeout_seconds", 60)
            self.max_retries = max_retries if max_retries != 2 else getattr(config, "max_retries", 2)
            self.thinking = thinking if thinking is not True else getattr(config, "thinking", True)
            self.reasoning_effort = reasoning_effort if reasoning_effort != "high" else getattr(config, "reasoning_effort", "high")
        else:
            url_val = (base_url or "").strip()
            self.model = model or ""
            self.api_key_env = api_key_env
            self.provider_label = provider_label
            if not url_val and self.provider_label:
                from project_config import resolve_preset
                preset = resolve_preset(self.provider_label)
                if preset and preset.base_url:
                    url_val = preset.base_url
            self.base_url = url_val
            self.timeout_seconds = timeout_seconds
            self.max_retries = max_retries
            self.thinking = thinking
            self.reasoning_effort = reasoning_effort
            self.config = ReviewerEngineConfig(
                provider=self.provider_label,
                model=self.model,
                api_key_env=self.api_key_env,
                base_url=self.base_url,
                timeout_seconds=self.timeout_seconds,
                max_retries=self.max_retries,
                thinking=self.thinking,
                reasoning_effort=self.reasoning_effort,
            )
        self.sink = sink

    def resolve_api_key(self) -> Optional[str]:
        """按优先级解析 API Key：指定变量名 -> 默认候选 -> Windows 注册表穿透。"""
        if self.api_key_env is None and _is_local_endpoint(self.base_url):
            return None

        candidates: List[str] = []
        if self.api_key_env:
            candidates.append(self.api_key_env)

        if self.provider_label and self.provider_label not in ("generic", "none"):
            normalized_prov = self.provider_label.upper().replace("-", "_")
            candidates.append(f"{normalized_prov}_API_KEY_QUENCH")
            candidates.append(f"{normalized_prov}_API_KEY")

        candidates.append("OPENAI_API_KEY")
        candidates.append("DEEPSEEK_API_KEY_Quench")  # vendor-literal: allow
        candidates.append("DEEPSEEK_API_KEY")  # vendor-literal: allow

        seen = set()
        unique_candidates = [c for c in candidates if not (c in seen or seen.add(c))]

        # 1. 检查当前进程环境变量
        for var in unique_candidates:
            val = os.environ.get(var, "").strip()
            if val:
                return val

        # 2. Windows 注册表动态穿透（免重启 IDE/终端）
        for var in unique_candidates:
            val = _read_windows_env_var(var)
            if val:
                return val

        return None

    def is_available(self) -> bool:
        """检查 Reviewer 引擎是否就绪。支持通用 OpenAI 兼容端点与本地端点。"""
        if self.provider_label in ("none", "", False):
            return False
        if _is_local_endpoint(self.base_url):
            return True
        return bool(self.resolve_api_key())

    @staticmethod
    def _parse_json_body(raw: bytes, context: str = "") -> Dict[str, Any]:
        """健壮的响应 JSON 解析 Seam：防御企业代理 200+HTML、非 UTF-8 编码与残缺报文。"""
        try:
            text = raw.decode("utf-8", errors="replace")
            return json.loads(text)
        except (UnicodeDecodeError, ValueError) as e:
            truncated = raw[:200].decode("utf-8", errors="replace")
            raise ReviewerEngineError(
                f"[Malformed Response] {context} 非合法 JSON 响应 ({len(raw)}B): {truncated!r}"
            ) from e

    def complete(
        self,
        messages: List[Dict[str, str]],
        timeout: Optional[int] = None,
        *,
        total_deadline_s: Optional[float] = None,
        stream: bool = False,
        sinks: Optional[List[ProgressSink]] = None,
        session_id: str = "default",
        log_dir: Optional[str] = None,
        soft_token_ceiling: int = 64000,
        soft_time_ceiling_s: float = 600.0,
    ) -> Dict[str, Any]:
        """向 Reviewer API 发起同步请求，具备精细化重试、有界读取、实时思考流落盘、心跳与总耗时预算熔断。"""
        if not self.is_available():
            raise ReviewerEngineUnavailableError(
                f"Reviewer 引擎未就绪 (provider='{self.provider_label}', api_key_env='{self.api_key_env}')"
            )

        api_key = self.resolve_api_key()
        endpoint = _normalize_chat_endpoint(self.base_url)
        per_call_timeout = float(timeout or self.timeout_seconds)

        # 整体总耗时预算（Wall-clock Total Deadline），防止多次重试导致 MCP 请求无限挂起
        deadline_budget = total_deadline_s or (per_call_timeout * 2.5)
        start_time = time.monotonic()
        deadline = start_time + deadline_budget

        if log_dir:
            log_telemetry_event(
                log_dir,
                {
                    "schema": 1,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "session_id": session_id,
                    "event": "start",
                    "elapsed_ms": 0,
                    "tokens_out": 0,
                    "repetition_score": 0.0,
                    "truncated": False,
                    "advisory": None,
                },
            )

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if self.thinking:
            payload["thinking"] = {"type": "enabled"}
            if self.reasoning_effort:
                payload["reasoning_effort"] = self.reasoning_effort

        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        max_attempts = 1 + max(0, self.max_retries)

        try:
            for attempt in range(max_attempts):
                # 动态检查剩余总时间预算
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReviewerEngineError(
                        f"[Deadline Exceeded] 审查引擎总耗时预算耗尽 ({deadline_budget:.1f}s)，已熔断"
                    )

                effective_timeout = min(per_call_timeout, max(1.0, remaining))

                req_headers: Dict[str, str] = {
                    "Content-Type": "application/json",
                    "User-Agent": f"Quorch-Reviewer-Engine/1.0 ({self.provider_label})",
                }
                if api_key:
                    req_headers["Authorization"] = f"Bearer {api_key}"

                req = urllib.request.Request(
                    url=endpoint,
                    data=data_bytes,
                    headers=req_headers,
                    method="POST",
                )

                try:
                    with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                        if stream:
                            full_content: List[str] = []
                            full_reasoning: List[str] = []
                            tokens_out = 0
                            reasoning_tokens = 0
                            finish_reason = "stop"
                            truncated = False
                            last_rep_check_tokens = 0

                            for raw_line in resp:
                                line = raw_line.decode("utf-8", errors="replace").strip()
                                if not line or line.startswith(":"):
                                    continue
                                if line.startswith("data:"):
                                    data_str = line[5:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        chunk_json = json.loads(data_str)
                                    except Exception:
                                        continue

                                    choices = chunk_json.get("choices") or []
                                    if not choices:
                                        continue
                                    choice = choices[0]
                                    if choice.get("finish_reason"):
                                        finish_reason = choice["finish_reason"]

                                    delta = choice.get("delta", {}) if isinstance(choice, Mapping) else {}
                                    r_chunk = extract_reasoning_text(choice) or extract_reasoning_text(chunk_json)
                                    c_chunk = delta.get("content") or ""

                                    if r_chunk:
                                        tok_est = max(1, len(r_chunk) // 4)
                                        tokens_out += tok_est
                                        reasoning_tokens += tok_est
                                        full_reasoning.append(r_chunk)
                                        if sinks:
                                            chunk_obj = ThoughtChunk(
                                                content=r_chunk,
                                                is_thought=True,
                                                tokens_estimate=tok_est,
                                            )
                                            for s in sinks:
                                                s.on_chunk(chunk_obj)

                                    if c_chunk:
                                        tok_est = max(1, len(c_chunk) // 4)
                                        tokens_out += tok_est
                                        full_content.append(c_chunk)
                                        if sinks:
                                            chunk_obj = ThoughtChunk(
                                                content=c_chunk,
                                                is_thought=False,
                                                tokens_estimate=tok_est,
                                            )
                                            for s in sinks:
                                                s.on_chunk(chunk_obj)

                                    elapsed_s = time.monotonic() - start_time
                                    if sinks:
                                        for s in sinks:
                                            s.on_heartbeat(tokens_out, elapsed_s)

                                    # Check soft ceilings (64k tokens / 600s)
                                    if tokens_out >= soft_token_ceiling or elapsed_s >= soft_time_ceiling_s:
                                        truncated = True
                                        finish_reason = "length"
                                        break

                                    # Repetition check periodically (~500 tokens)
                                    if tokens_out - last_rep_check_tokens >= 500:
                                        last_rep_check_tokens = tokens_out
                                        sample_text = (
                                            "".join(full_reasoning[-50:])
                                            if full_reasoning
                                            else "".join(full_content[-50:])
                                        )
                                        rep_score = compute_repetition_score(sample_text)
                                        if rep_score > 0.6 and log_dir:
                                            log_telemetry_event(
                                                log_dir,
                                                {
                                                    "schema": 1,
                                                    "ts": datetime.now(timezone.utc).isoformat(),
                                                    "session_id": session_id,
                                                    "event": "warn_repetition",
                                                    "elapsed_ms": int(elapsed_s * 1000),
                                                    "tokens_out": tokens_out,
                                                    "repetition_score": rep_score,
                                                    "truncated": truncated,
                                                    "advisory": f"Repetition detected ({rep_score:.2f})",
                                                },
                                            )

                            elapsed_s = time.monotonic() - start_time
                            reasoning_str = "".join(full_reasoning)
                            content_str = "".join(full_content)
                            final_rep_score = compute_repetition_score(reasoning_str or content_str)

                            if sinks:
                                for s in sinks:
                                    s.on_finish(
                                        finish_reason,
                                        {
                                            "tokens": tokens_out,
                                            "elapsed_s": elapsed_s,
                                            "truncated": truncated,
                                        },
                                    )

                            if log_dir:
                                log_telemetry_event(
                                    log_dir,
                                    {
                                        "schema": 1,
                                        "ts": datetime.now(timezone.utc).isoformat(),
                                        "session_id": session_id,
                                        "event": "finish",
                                        "elapsed_ms": int(elapsed_s * 1000),
                                        "tokens_out": tokens_out,
                                        "repetition_score": final_rep_score,
                                        "truncated": truncated,
                                        "advisory": "[Warning] Soft ceiling reached" if truncated else None,
                                    },
                                )

                            return {
                                "content": content_str,
                                "reasoning_content": reasoning_str,
                                "finish_reason": finish_reason,
                                "usage": {
                                    "completion_tokens": tokens_out,
                                    "reasoning_tokens": reasoning_tokens,
                                    "total_tokens": tokens_out,
                                },
                                "truncated": truncated,
                                "raw": {"stream": True, "truncated": truncated},
                            }

                        else:
                            # 有界读取：最大读取 MAX_RESPONSE_BYTES + 1
                            raw_bytes = resp.read(MAX_RESPONSE_BYTES + 1)
                            if len(raw_bytes) > MAX_RESPONSE_BYTES:
                                raise ReviewerEngineError(
                                    f"[Payload Too Large] 审查服务端响应超出体积安全上限 ({MAX_RESPONSE_BYTES}B)"
                                )

                            body_json = self._parse_json_body(raw_bytes, context="HTTP 200")
                            choices = body_json.get("choices") or []
                            if not choices:
                                raise ReviewerEngineError(
                                    f"[Malformed Response] 响应缺少 choices 字段: {raw_bytes[:200]!r}"
                                )

                            choice = choices[0]
                            message = choice.get("message", {}) if isinstance(choice, Mapping) else {}
                            content = message.get("content", "")
                            reasoning_content = extract_reasoning_text(choice) or extract_reasoning_text(body_json) or message.get("reasoning_content", "")
                            finish_reason = choice.get("finish_reason", "stop") if isinstance(choice, Mapping) else "stop"
                            usage = body_json.get("usage", {})
                            if isinstance(usage, Mapping) and "prompt_cache_hit_tokens" not in usage:
                                cached_tok = extract_cached_tokens(body_json)
                                if cached_tok > 0:
                                    usage = dict(usage)
                                    usage["prompt_cache_hit_tokens"] = cached_tok

                            elapsed_s = time.monotonic() - start_time
                            total_tokens = usage.get("total_tokens") if isinstance(usage, Mapping) else None
                            if total_tokens is None:
                                total_tokens = (len(content) + len(reasoning_content)) // 4

                            if sinks:
                                if reasoning_content:
                                    tok_est = max(1, len(reasoning_content) // 4)
                                    for s in sinks:
                                        s.on_chunk(
                                            ThoughtChunk(
                                                content=reasoning_content,
                                                is_thought=True,
                                                tokens_estimate=tok_est,
                                            )
                                        )
                                if content:
                                    tok_est = max(1, len(content) // 4)
                                    for s in sinks:
                                        s.on_chunk(
                                            ThoughtChunk(
                                                content=content,
                                                is_thought=False,
                                                tokens_estimate=tok_est,
                                            )
                                        )
                                for s in sinks:
                                    s.on_heartbeat(total_tokens, elapsed_s)
                                    s.on_finish(
                                        finish_reason,
                                        {
                                            "tokens": total_tokens,
                                            "elapsed_s": elapsed_s,
                                            "truncated": False,
                                        },
                                    )

                            if log_dir:
                                rep_score = compute_repetition_score(reasoning_content or content)
                                log_telemetry_event(
                                    log_dir,
                                    {
                                        "schema": 1,
                                        "ts": datetime.now(timezone.utc).isoformat(),
                                        "session_id": session_id,
                                        "event": "finish",
                                        "elapsed_ms": int(elapsed_s * 1000),
                                        "tokens_out": total_tokens,
                                        "repetition_score": rep_score,
                                        "truncated": False,
                                        "advisory": None,
                                    },
                                )

                            return {
                                "content": content,
                                "reasoning_content": reasoning_content,
                                "finish_reason": finish_reason,
                                "usage": usage,
                                "truncated": False,
                                "raw": body_json,
                            }

                except urllib.error.HTTPError as e:
                    err_body = ""
                    try:
                        raw_err = e.read(5000 + 1)
                        err_body = raw_err[:500].decode("utf-8", errors="replace")
                    except Exception:
                        pass
                    finally:
                        try:
                            e.close()
                        except Exception:
                            pass

                    # 401 鉴权失败：单次快速失败，严禁盲目重试
                    if e.code == 401:
                        key_display = self.api_key_env or "API_KEY"
                        raise ReviewerAuthenticationError(
                            f"[HTTP 401 Unauthorized] Reviewer API ({self.provider_label}) 鉴权失败：请检查环境变量 {key_display} 是否已导出: {err_body}"
                        )
                    # 400 参数非法：单次快速失败，严禁重试
                    elif e.code == 400:
                        raise ReviewerBadRequestError(
                            f"[HTTP 400 Bad Request] Reviewer API ({self.provider_label}) 请求参数非法: {err_body}"
                        )
                    # 403 / 404：无权限或路由不存在，直接失败
                    elif e.code == 403:
                        key_display = self.api_key_env or "API_KEY"
                        raise ReviewerAuthenticationError(
                            f"[HTTP 403 Forbidden] Reviewer API ({self.provider_label}) 访问受限：请检查权限或凭据 {key_display}: {err_body}"
                        )
                    elif e.code == 404:
                        raise ReviewerEngineError(f"[HTTP 404 Not Found] Reviewer API ({self.provider_label}) 路由端点不存在: {err_body}")

                    # 429（流控）或 5xx（服务端错误）：支持有限次数指数退避 + 抖动重试
                    if (e.code == 429 or e.code >= 500) and attempt < max_attempts - 1:
                        retry_after_hdr = e.headers.get("Retry-After") if hasattr(e, "headers") else None
                        if retry_after_hdr and retry_after_hdr.isdigit():
                            backoff_sec = min(float(retry_after_hdr), 30.0)
                        else:
                            base = 1.0 * (2 ** attempt)
                            backoff_sec = random.uniform(0.75, 1.25) * base

                        time.sleep(backoff_sec)
                        continue

                    raise ReviewerEngineError(f"[HTTP {e.code}] Reviewer API ({self.provider_label}) 超过最大重试次数: {err_body}")

                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    err_str = str(e)
                    if "CERTIFICATE_VERIFY_FAILED" in err_str or "certificate verify failed" in err_str.lower():
                        raise ReviewerEngineError(f"[SSL Error] 证书校验失败: {err_str}")

                    if attempt < max_attempts - 1:
                        base = 1.0 * (2 ** attempt)
                        backoff_sec = random.uniform(0.75, 1.25) * base
                        time.sleep(backoff_sec)
                        continue

                    raise ReviewerEngineError(f"[Network Error] 网络通信超时或异常: {e}")

            raise ReviewerEngineError("[Fatal] 审查客户端请求异常退出")
        finally:
            if sinks:
                for s in sinks:
                    if hasattr(s, "close"):
                        try:
                            s.close()
                        except Exception:
                            pass

    async def stream_chat(
        self,
        system_prompt_or_messages: str | List[Dict[str, str]],
        user_prompt: Optional[str] = None,
        *,
        session_id: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """异步消费通用 /chat/completions SSE 推理与思考流。
        基于探针提取 reasoning 与跨厂商 usage，单行 JSON 容错，带 1MB 单行截断防护与连接释放。
        """
        if not self.is_available():
            key_display = self.api_key_env or "API_KEY"
            raise ReviewerNotConfiguredError(
                f"Reviewer 引擎未就绪 (provider='{self.provider_label}', api_key_env='{key_display}')"
            )

        endpoint = _normalize_chat_endpoint(self.base_url)
        api_key = self.resolve_api_key()

        if isinstance(system_prompt_or_messages, list):
            messages: List[Dict[str, str]] = system_prompt_or_messages
        else:
            messages = []
            if system_prompt_or_messages:
                messages.append({"role": "system", "content": system_prompt_or_messages})
            if user_prompt:
                messages.append({"role": "user", "content": user_prompt})

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if self.thinking:
            payload["thinking"] = {"type": "enabled"}
            if self.reasoning_effort:
                payload["reasoning_effort"] = self.reasoning_effort

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": f"Quorch-Reviewer-Engine/1.0 ({self.provider_label})",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        max_attempts = 1 + max(0, self.max_retries)
        chunk_queue: queue.Queue = queue.Queue(maxsize=100)
        stop_event = threading.Event()
        MAX_LINE_BYTES = 1024 * 1024  # 1 MiB 单行上限

        def _stream_worker() -> None:
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            for attempt in range(max_attempts):
                if stop_event.is_set():
                    break
                req = urllib.request.Request(
                    url=endpoint,
                    data=data_bytes,
                    headers=headers,
                    method="POST",
                )
                resp = None
                try:
                    resp = urllib.request.urlopen(req, timeout=float(self.timeout_seconds))
                    line_buffer = bytearray()
                    while not stop_event.is_set():
                        raw_byte = resp.read(8192)
                        if not raw_byte:
                            break
                        line_buffer.extend(raw_byte)
                        while b"\n" in line_buffer:
                            line_end = line_buffer.index(b"\n")
                            raw_line = bytes(line_buffer[:line_end])
                            del line_buffer[: line_end + 1]

                            if len(raw_line) > MAX_LINE_BYTES:
                                raw_line = raw_line[:MAX_LINE_BYTES]

                            line = decoder.decode(raw_line).strip()
                            if not line or line.startswith(":"):
                                continue
                            if line.startswith("data:"):
                                data_str = line[5:].strip()
                                if data_str == "[DONE]":
                                    chunk_queue.put(StreamChunk(done=True))
                                    return

                                try:
                                    chunk_json = json.loads(data_str)
                                except Exception:
                                    continue

                                choices = chunk_json.get("choices") or []
                                r_chunk = extract_reasoning_text(chunk_json)
                                c_chunk = ""
                                if choices and isinstance(choices[0], Mapping):
                                    c_chunk = choices[0].get("delta", {}).get("content") or ""

                                usage_snapshot = None
                                if "usage" in chunk_json and chunk_json["usage"]:
                                    usage_snapshot = extract_usage(chunk_json, provider_label=self.provider_label)

                                if r_chunk or c_chunk or usage_snapshot:
                                    chunk_queue.put(
                                        StreamChunk(
                                            text=c_chunk,
                                            reasoning=r_chunk,
                                            usage=usage_snapshot,
                                            done=False,
                                        )
                                    )
                    chunk_queue.put(StreamChunk(done=True))
                    return

                except urllib.error.HTTPError as e:
                    err_body = ""
                    try:
                        raw_err = e.read(1000)
                        err_body = raw_err.decode("utf-8", errors="replace")
                    except Exception:
                        pass
                    finally:
                        try:
                            e.close()
                        except Exception:
                            pass

                    if e.code in (401, 403):
                        key_display = self.api_key_env or "API_KEY"
                        chunk_queue.put(
                            ReviewerAuthError(
                                f"[HTTP {e.code}] Reviewer API ({self.provider_label}) 鉴权失败：请检查环境变量 {key_display} 是否已导出: {err_body}"
                            )
                        )
                        return
                    if e.code == 400:
                        chunk_queue.put(
                            ReviewerError(
                                f"[HTTP 400 Bad Request] Reviewer API ({self.provider_label}) 请求被拒：{err_body}"
                            )
                        )
                        return

                    if (e.code == 429 or e.code >= 500) and attempt < max_attempts - 1:
                        time.sleep(1.0 * (2 ** attempt))
                        continue

                    chunk_queue.put(ReviewerError(f"[HTTP {e.code}] Reviewer API ({self.provider_label}) 请求失败: {err_body}"))
                    return

                except (TimeoutError, urllib.error.URLError, OSError) as e:
                    if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
                        if attempt >= max_attempts - 1:
                            chunk_queue.put(ReviewerTimeoutError(f"Reviewer API ({self.provider_label}) 通信超时: {e}"))
                            return
                    else:
                        if attempt >= max_attempts - 1:
                            chunk_queue.put(ReviewerError(f"Reviewer API ({self.provider_label}) 网络通信异常: {e}"))
                            return
                    time.sleep(1.0 * (2 ** attempt))
                finally:
                    if resp is not None:
                        try:
                            resp.close()
                        except Exception:
                            pass

            chunk_queue.put(StreamChunk(done=True))

        worker_thread = threading.Thread(target=_stream_worker, daemon=True)
        worker_thread.start()

        try:
            while True:
                item = await anyio.to_thread.run_sync(chunk_queue.get)
                if isinstance(item, Exception):
                    raise item
                if isinstance(item, StreamChunk):
                    yield item
                    if item.done:
                        break
        finally:
            stop_event.set()

    async def acomplete(
        self,
        messages: List[Dict[str, str]],
        timeout: Optional[int] = None,
        *,
        total_deadline_s: Optional[float] = None,
        stream: bool = False,
        sinks: Optional[List[ProgressSink]] = None,
        session_id: str = "default",
        log_dir: Optional[str] = None,
        soft_token_ceiling: int = 64000,
        soft_time_ceiling_s: float = 600.0,
    ) -> Dict[str, Any]:
        """异步非阻塞调用门面：使用 AnyIO 卸载至后台线程，防止阻塞 FastMCP 主事件循环。
        自带容量限制器 (_REVIEWER_LIMITER) 防拥塞，abandon_on_cancel=True 支持超时快速取消。
        """
        fn = functools.partial(
            self.complete,
            messages,
            timeout,
            total_deadline_s=total_deadline_s,
            stream=stream,
            sinks=sinks,
            session_id=session_id,
            log_dir=log_dir,
            soft_token_ceiling=soft_token_ceiling,
            soft_time_ceiling_s=soft_time_ceiling_s,
        )
        async with _REVIEWER_LIMITER:
            return await anyio.to_thread.run_sync(fn, abandon_on_cancel=True)


# ---- PEP 562 兼容层（模块级）----
def __getattr__(name: str) -> Any:
    """PEP 562 兼容别名：平滑迁移旧客户端至 ReviewerClient。"""
    if name == "DeepSeekClient":  # vendor-literal: allow
        warnings.warn("DeepSeekClient 已弃用，请改用 ReviewerClient", DeprecationWarning, stacklevel=2)  # vendor-literal: allow
        return ReviewerClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ReviewerClient",
    "DeepSeekClient",  # vendor-literal: allow
    "UsageSnapshot",
    "StreamChunk",
    "extract_reasoning_text",
    "extract_cached_tokens",
    "extract_usage",
    "ReviewerError",
    "ReviewerAuthError",
    "ReviewerTimeoutError",
    "ReviewerNotConfiguredError",
    "ReviewerEngineError",
    "ReviewerEngineUnavailableError",
    "ReviewerAuthenticationError",
    "ReviewerBadRequestError",
    "ReviewerRateLimitError",
    "ThoughtChunk",
    "ProgressSink",
    "RotatingFileSink",
    "AdaptiveHeartbeatSink",
    "CoalescingStats",
    "CoalescingTextSink",
    "SinkMode",
    "ObservabilityDecision",
    "VerdictAuditSink",
    "MAX_RECORD_BYTES",
    "resolve_observability_policy",
    "make_verdict_sink",
    "PromptAssembler",
    "compute_repetition_score",
    "log_telemetry_event",
    "_read_windows_env_var",
]
