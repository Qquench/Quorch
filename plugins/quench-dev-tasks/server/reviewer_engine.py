# -*- coding: utf-8 -*-
"""Quench Reviewer Engine: 深度思考审查模型客户端与 Prompt 组装器.

负责连接高阶推理审查模型 (Reviewer)，组装高命中率的静态架构上下文缓存前缀，
并为任务规约强化 (Spec Refine) 与架构疑难升级 (Escalate) 提供确定性分析能力。
具备非阻塞异步线程卸载 (acomplete)、企业网络异常防御与总耗时预算熔断。
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
import re
from typing import (
    Any,
    Dict,
    List,
    Literal,
    NamedTuple,
    Optional,
    Protocol,
    TextIO,
    Tuple,
    TypedDict,
)

import anyio

from project_config import QuenchStackConfig, ReviewerEngineConfig

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


class ReviewerEngineError(Exception):
    """Reviewer Engine 基础异常。"""
    pass


class ReviewerEngineUnavailableError(ReviewerEngineError):
    """Reviewer 引擎不可用（未配置或缺少 API Key）。"""
    pass


class ReviewerAuthenticationError(ReviewerEngineError):
    """身份鉴权失败（401 Unauthorized）。不可重试。"""
    pass


class ReviewerBadRequestError(ReviewerEngineError):
    """请求参数非法（400 Bad Request）。不可重试。"""
    pass


class ReviewerRateLimitError(ReviewerEngineError):
    """触发流控限制（429 Too Many Requests）。可重试。"""
    pass


class ThoughtChunk(NamedTuple):
    content: str
    is_thought: bool
    tokens_estimate: int


class ProgressSink(Protocol):
    def on_chunk(self, chunk: ThoughtChunk) -> None: ...
    def on_heartbeat(self, tokens_so_far: int, elapsed_s: float) -> None: ...
    def on_finish(self, reason: str, meta: Dict[str, Any]) -> None: ...


_SECRET_REDACTION_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{20,}")


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
        if self._is_closed:
            return
        if self._carry_over:
            final_text = _SECRET_REDACTION_PATTERN.sub("[REDACTED]", self._carry_over)
            self._carry_over = ""
            data_bytes = final_text.encode("utf-8")
            self._rotate_if_needed(len(data_bytes))
            self._fp.write(final_text)
            self._written_bytes += len(data_bytes)
        self.close()

    def close(self) -> None:
        if not self._is_closed:
            self._is_closed = True
            try:
                if not self._fp.closed:
                    self._fp.flush()
                    self._fp.close()
            except Exception:
                pass


class AdaptiveHeartbeatSink:
    """Low-frequency heartbeat pulse adapter (1Hz / 1000ms interval).
    Priority (B5):
    1. mcp_context (progress / info)
    2. isatty(stderr) -> single-line dynamic overwrite via \r
    3. silent (no-op)
    Zero stdout pollution (P0#1 invariant).
    """

    def __init__(
        self,
        mcp_context: Any = None,
        stderr: Optional[TextIO] = None,
        interval_ms: int = 1000,
    ):
        self.mcp_context = mcp_context
        self.stderr = stderr if stderr is not None else sys.stderr
        self.interval_s = max(interval_ms, 500) / 1000.0
        self._last_pulse = 0.0
        self._pulse_count = 0
        self._is_tty = bool(self.stderr and hasattr(self.stderr, "isatty") and self.stderr.isatty())

    def on_chunk(self, chunk: ThoughtChunk) -> None:
        pass

    def on_heartbeat(self, tokens_so_far: int, elapsed_s: float) -> None:
        now = time.monotonic()
        jitter = random.uniform(0.0, 0.015)
        if (now - self._last_pulse) < (self.interval_s + jitter):
            return

        self._last_pulse = now
        self._pulse_count += 1
        msg = f"[Reviewer 思考中: {tokens_so_far} tokens | {elapsed_s:.1f}s]"

        # 1. MCP context priority
        if self.mcp_context is not None:
            try:
                if hasattr(self.mcp_context, "info"):
                    self.mcp_context.info(msg)
                    return
                elif hasattr(self.mcp_context, "report_progress"):
                    self.mcp_context.report_progress(tokens_so_far, 64000)
                    return
            except Exception:
                pass

        # 2. isatty(stderr) priority
        if self._is_tty:
            try:
                self.stderr.write(f"\r{msg}...")
                self.stderr.flush()
                return
            except Exception:
                pass

        # 3. Silent fallback (no-op)

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
    
    ★ 核心防线：为保障 DeepSeek Prompt Cache 极致命中率，
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


class DeepSeekClient:
    """基于标准库与 AnyIO 实现的工业级 DeepSeek API 客户端。
    具备异步非阻塞调度 (acomplete)、退避重试、企业网络防崩解析与总耗时预算熔断。
    """

    def __init__(self, config: ReviewerEngineConfig):
        self.config = config

    def resolve_api_key(self) -> Optional[str]:
        """按优先级解析 API Key：指定变量名 -> 默认候选 -> Windows 注册表穿透。"""
        target_var = self.config.api_key_env or "DEEPSEEK_API_KEY_Quench"
        candidates = [target_var, "DEEPSEEK_API_KEY_Quench", "DEEPSEEK_API_KEY"]
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
        """检查 Reviewer 引擎是否就绪。支持通用 OpenAI 兼容端点与本地 Ollama。"""
        if self.config.provider in ("none", "", False):
            return False
        if self.config.provider == "ollama":
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
        """向 DeepSeek API 发起同步请求，具备精细化重试、有界读取、实时思考流落盘、心跳与总耗时预算熔断。"""
        if not self.is_available():
            raise ReviewerEngineUnavailableError(
                f"Reviewer 引擎未就绪 (provider='{self.config.provider}', api_key_env='{self.config.api_key_env}')"
            )

        api_key = self.resolve_api_key()
        endpoint = f"{self.config.base_url.rstrip('/')}/chat/completions"
        per_call_timeout = float(timeout or self.config.timeout_seconds)

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
            "model": self.config.model,
            "messages": messages,
            "stream": stream,
        }
        if self.config.thinking:
            payload["thinking"] = {"type": "enabled"}
            if self.config.reasoning_effort:
                payload["reasoning_effort"] = self.config.reasoning_effort

        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        max_attempts = 1 + max(0, self.config.max_retries)

        try:
            for attempt in range(max_attempts):
                # 动态检查剩余总时间预算
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReviewerEngineError(
                        f"[Deadline Exceeded] 审查引擎总耗时预算耗尽 ({deadline_budget:.1f}s)，已熔断"
                    )

                effective_timeout = min(per_call_timeout, max(1.0, remaining))

                req = urllib.request.Request(
                    url=endpoint,
                    data=data_bytes,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Quorch-Reviewer-Engine/1.0",
                    },
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

                                    delta = choice.get("delta", {})
                                    r_chunk = delta.get("reasoning_content") or ""
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

                                    # Check soft ceilings (B6: 64k tokens / 600s)
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
                            message = choice.get("message", {})
                            content = message.get("content", "")
                            reasoning_content = message.get("reasoning_content", "")
                            finish_reason = choice.get("finish_reason", "stop")
                            usage = body_json.get("usage", {})

                            elapsed_s = time.monotonic() - start_time
                            total_tokens = usage.get("total_tokens") or (len(content) + len(reasoning_content)) // 4

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
                        raise ReviewerAuthenticationError(
                            f"[HTTP 401 Unauthorized] DeepSeek API 凭据鉴权失败: {err_body}"
                        )
                    # 400 参数非法：单次快速失败，严禁重试
                    elif e.code == 400:
                        raise ReviewerBadRequestError(
                            f"[HTTP 400 Bad Request] DeepSeek 请求参数非法: {err_body}"
                        )
                    # 403 / 404：无权限或路由不存在，直接失败
                    elif e.code in (403, 404):
                        raise ReviewerEngineError(f"[HTTP {e.code}] 接口调用失败: {err_body}")

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

                    raise ReviewerEngineError(f"[HTTP {e.code}] 超过最大重试次数: {err_body}")

                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    # SSL 证书失效：快速失败，避免无谓重试
                    err_str = str(e)
                    if "CERTIFICATE_VERIFY_FAILED" in err_str or "certificate verify failed" in err_str.lower():
                        raise ReviewerEngineError(f"[SSL Error] 证书校验失败: {err_str}")

                    if attempt < max_attempts - 1:
                        base = 1.0 * (2 ** attempt)
                        backoff_sec = random.uniform(0.75, 1.25) * base
                        time.sleep(backoff_sec)
                        continue

                    raise ReviewerEngineError(f"[Network Error] 网络通信超时或异常: {e}")

            # 正常情况下由循环内返回或抛出，此处为类型系统安全兜底
            raise ReviewerEngineError("[Fatal] 审查客户端请求异常退出")
        finally:
            if sinks:
                for s in sinks:
                    if hasattr(s, "close"):
                        try:
                            s.close()
                        except Exception:
                            pass

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


class ReviewerClient(DeepSeekClient):
    """Generic OpenAI-compatible Reviewer Client supporting any standard /chat/completions provider."""
    pass

