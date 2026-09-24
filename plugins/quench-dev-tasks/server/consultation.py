# -*- coding: utf-8 -*-
"""Ad-hoc architecture consultation module for Quench.

Provides dev_reviewer_consult engine integration without requiring DevTask lifecycle.
Maintains byte-stable Prompt Cache prefix, sandboxed context slice extraction,
real-time reasoning stream persistence, and strict anti-roleplaying degradation cards.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
from uuid import uuid4
import weakref

from path_guard import sanitize_workspace_path, PathTraversalError
from project_config import (
    QuenchStackConfig,
    ReviewerEngineConfig,
    RunnerProfile,
    check_self_verification_warning,
    create_reviewer_client,
)
from reviewer_engine import (
    AdaptiveHeartbeatSink,
    CoalescingTextSink,
    PromptAssembler,
    ReviewerClient,
    ReviewerEngineError,
    ReviewerEngineUnavailableError,
    RotatingFileSink,
    extract_reasoning_text,
    extract_usage,
)
from log_naming import allocate_log_file, enforce_unified_log_quota, gc_by_filename_order

class ReasoningBudgetExceededError(ReviewerEngineError):
    """推理链长度超出安全天花板异常。"""
    pass


ConsultMode = Literal["critique", "evaluate", "brainstorm", "audit"]
VALID_MODES: tuple[str, ...] = ("critique", "evaluate", "brainstorm", "audit")

SESSION_ID_PATTERN = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")
NEED_FILES_PATTERN = re.compile(r"<<<NEED-FILES>>>\s*(.*?)\s*<<<END>>>", re.DOTALL)
TASK_DRAFT_PATTERN = re.compile(r"<<<TASK_DRAFT>>>\s*(.*?)\s*<<<END>>>", re.DOTALL)

MAX_CONTEXT_FILES = 6
DEFAULT_WINDOW_LINES = 200
MIN_WINDOW_LINES = 30
MAX_LINES_PER_SLICE = 600
MAX_TOTAL_INJECTION_CHARS = 40000
MAX_INJECTION_CHARS = MAX_TOTAL_INJECTION_CHARS  # SSOT backward compatibility alias
MAX_QUERY_CHARS = 8000
MAX_LOG_FILES_QUOTA = 20
MAX_LOG_FILE_BYTES = 2_000_000
MAX_REASONING_TOKENS_CEILING = 32000

CONTEXT_SPEC_PATTERN = re.compile(r"^(?P<path>.+):(?P<start>\d+)-(?P<end>\d+)$")


@dataclass(frozen=True)
class CodeSlice:
    rel_path: str
    start_line: int
    end_line: int
    text: str                       # 头部含 "# file: <rel_path>:<start>-<end>" 锚点


@dataclass(frozen=True)
class ConsultRequest:
    workspace_root: str
    query: str
    context_files: tuple[str, ...] = ()
    mode: ConsultMode = "critique"
    max_hops: int = 1               # 允许的上下文扩展轮次，钳制 [0, 3]
    session_id: str | None = None


@dataclass(frozen=True)
class ConsultResult:
    status: Literal["ok", "degraded"]
    session_id: str
    mode: ConsultMode
    findings: str
    log_path: str
    usage: dict[str, int]
    truncated: bool
    skipped_files: list[str]
    degraded_reason: str | None = None      # "reviewer_not_configured" | "timeout" | "auth" | "network" | "reasoning_budget_exceeded"
    handoff_prompt: str | None = None
    suggested_task_draft: dict[str, Any] | None = None
    reviewer_identity: dict[str, Any] = field(default_factory=dict)
    self_verification_warning: Optional[str] = None


def sanitize_session_id(raw: str | None) -> str:
    """校验并清洗 session_id。若为空则生成 12 字符十六进制串；若提供则必须匹配 ^[0-9a-zA-Z_-]{1,64}$。"""
    if raw is None or not str(raw).strip():
        return uuid4().hex[:12]
    val = str(raw).strip()
    if not SESSION_ID_PATTERN.match(val):
        raise ValueError(
            f"Invalid session_id: '{raw}'. Must match '^[0-9a-zA-Z_-]{{1,64}}$' and cannot contain '/', '\\', or '..'."
        )
    return val


def resolve_context_files(
    workspace_root: str,
    rel_paths: Sequence[str],
    *,
    max_files: int = 6,
    window_lines: int = DEFAULT_WINDOW_LINES,
    max_total_injection_chars: int = MAX_TOTAL_INJECTION_CHARS,
    max_lines_per_slice: int = MAX_LINES_PER_SLICE,
) -> tuple[list[CodeSlice], list[str], bool]:
    """安全解析并切片上下文文件，支持 path:start-end 行号区间文法并实行全局字符预算聚合。
    越界路径（..、绝对路径、符号链接逃逸、盘符漂移）一律跳过并计入 skipped_files，绝不抛出异常。
    """
    real_ws = os.path.realpath(workspace_root)
    slices: list[CodeSlice] = []
    skipped_files: list[str] = []
    truncated = False

    effective_window = max(window_lines, MIN_WINDOW_LINES)
    total_chars = 0
    seen_paths: set[tuple[str, Optional[int], Optional[int]]] = set()

    for raw_p in rel_paths:
        if not raw_p or not isinstance(raw_p, str):
            continue
        p_str = raw_p.strip()
        if not p_str:
            continue

        # 提前短路：若预算已耗尽，不再进行无意义的路径解析与文件 I/O
        if total_chars >= max_total_injection_chars:
            truncated = True
            break

        # 0. 解析路径与行号区间文法 (e.g. path/to/file.py:10-50 或纯路径)
        range_match = CONTEXT_SPEC_PATTERN.match(p_str)
        if range_match:
            spec_path = range_match.group("path").strip()
            explicit_start = int(range_match.group("start"))
            explicit_end = int(range_match.group("end"))
            if explicit_start < 1 or explicit_start > explicit_end:
                skipped_files.append(p_str)
                continue
        else:
            spec_path = p_str
            explicit_start = None
            explicit_end = None

        # 1. 规范化路径并检查是否逃逸与存在 (使用单一事实源 path_guard)
        try:
            real_target = sanitize_workspace_path(real_ws, spec_path, must_exist=True)
        except PathTraversalError:
            skipped_files.append(p_str)
            continue
        except Exception:
            skipped_files.append(p_str)
            continue

        # 2. 必须为普通文件 (排除目录)
        if not os.path.isfile(real_target):
            skipped_files.append(p_str)
            continue

        # 3. 敏感文件防御（.env, *.key, *secret*, 等）
        base_name = os.path.basename(real_target).lower()
        if any(base_name.startswith(pre) for pre in (".env", "id_rsa", "id_ed25519")) or any(
            ext in base_name for ext in (".key", ".pem", ".pfx", ".p12", "secret", "credential", "token")
        ):
            skipped_files.append(p_str)
            continue

        target_key = (real_target, explicit_start, explicit_end)
        if target_key in seen_paths:
            continue
        seen_paths.add(target_key)

        # 4. 超出 max_files 限制
        if len(slices) >= max_files:
            truncated = True
            break

        # 5. 读取切片
        try:
            with open(real_target, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except Exception:
            skipped_files.append(p_str)
            continue

        total_file_lines = len(all_lines)
        if total_file_lines == 0:
            if explicit_start is not None:
                skipped_files.append(p_str)
                continue
            start_line = 0
            end_line = 0
        elif explicit_start is not None:
            if explicit_start > total_file_lines:
                skipped_files.append(p_str)
                continue
            start_line = explicit_start
            req_end = explicit_end
            if req_end - start_line + 1 > max_lines_per_slice:
                req_end = start_line + max_lines_per_slice - 1
            end_line = min(total_file_lines, req_end)
        else:
            start_line = 1
            end_line = min(total_file_lines, effective_window)

        selected_lines = all_lines[start_line - 1 : end_line]
        slice_content = "".join(selected_lines)

        norm_rel = os.path.relpath(real_target, real_ws).replace("\\", "/")
        anchor = f"# file: {norm_rel}:{start_line}-{end_line}\n"
        full_slice_text = anchor + slice_content

        # 6. 全局聚合字符预算检查 (max_total_injection_chars)
        if total_chars + len(full_slice_text) > max_total_injection_chars:
            remaining_budget = max_total_injection_chars - total_chars
            marker = "\n# [... truncated due to global budget cap ...]\n"
            needed_overhead = len(anchor) + len(marker)
            if remaining_budget > needed_overhead:
                # 严格按字符串字符切片，绝不对 UTF-8 字节进行撕裂性盲切 (R-C5)
                cut_len = remaining_budget - needed_overhead
                truncated_content = slice_content[:cut_len] + marker
                slices.append(
                    CodeSlice(
                        rel_path=norm_rel,
                        start_line=start_line,
                        end_line=end_line,
                        text=anchor + truncated_content,
                    )
                )
            truncated = True
            break

        total_chars += len(full_slice_text)
        slices.append(
            CodeSlice(
                rel_path=norm_rel,
                start_line=start_line,
                end_line=end_line,
                text=full_slice_text,
            )
        )

    return slices, skipped_files, truncated


_PREFIX_CACHE: dict[tuple, str] = {}
_PREFIX_LOCK = threading.Lock()


def build_static_prefix(workspace_root: str, config: Any) -> str:
    """构建字节级纯洁稳定的全局架构静态基线前缀，基于 workspace_root 与源文件 mtime 进程内缓存。"""
    real_ws = os.path.realpath(workspace_root)

    arch_doc_rel = getattr(config, "architecture_doc", None)
    arch_mtime = 0.0
    if arch_doc_rel:
        arch_abs = os.path.normpath(os.path.join(real_ws, arch_doc_rel))
        if os.path.isfile(arch_abs):
            try:
                arch_mtime = os.path.getmtime(arch_abs)
            except OSError:
                pass

    rules_path = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rules", "dev-tasks-discipline.md")
    )
    rules_mtime = 0.0
    if os.path.isfile(rules_path):
        try:
            rules_mtime = os.path.getmtime(rules_path)
        except OSError:
            pass

    constraints_tuple = tuple(getattr(config, "constraints", []) or [])
    cache_key = (real_ws, arch_mtime, rules_mtime, arch_doc_rel or "", constraints_tuple)

    with _PREFIX_LOCK:
        if cache_key in _PREFIX_CACHE:
            return _PREFIX_CACHE[cache_key]

        prefix = PromptAssembler.build_static_system_prefix(real_ws, config)
        _PREFIX_CACHE[cache_key] = prefix
        return prefix


MODE_INSTRUCTIONS: dict[str, str] = {
    "critique": (
        "### Mode: Architectural Critique (Red-Team Threat Modeling)\n"
        "Your duty is to relentlessly challenge assumptions, uncover race conditions, identify single points of failure, "
        "and scrutinize concurrency, persistence, and state invariants.\n"
        "- Explicitly categorize each risk by severity (Critical / High / Medium / Low) with concrete trigger scenarios;\n"
        "- FORBIDDEN: Stylistic or aesthetic preferences. Focus strictly on system correctness, reliability, and invariants."
    ),
    "evaluate": (
        "### Mode: Technical Trade-off Evaluation (A/B Comparative Matrix)\n"
        "Your duty is to provide an objective, multi-dimensional trade-off matrix for the architectural alternatives.\n"
        "- Structure your assessment across: Theoretical Benefits / Operational & Engineering Costs / Latent Failure Modes / Rollback & Migration Path;\n"
        "- Explicitly declare which design is favored under which operational conditions."
    ),
    "brainstorm": (
        "### Mode: Architectural Exploration & Brainstorming\n"
        "Your duty is to explore divergent architectural approaches and innovative patterns to address the problem statement.\n"
        "- For each proposed direction, annotate technical feasibility, key trade-offs, and a minimal proof-of-concept verification experiment;\n"
        "- Keep solutions grounded in realistic constraints."
    ),
    "audit": (
        "### Mode: Contract & Implementation Conformance Audit\n"
        "Your duty is to conduct a strict, read-only audit between architectural specifications/contracts and current implementations.\n"
        "- Enumerate explicit drift points, undocumented side effects, unhandled error conditions, and lifecycle violations;\n"
        "- Provide line-anchored citations where deviations occur."
    ),
}


def render_mode_prompt(mode: ConsultMode, query: str, slices: Sequence[CodeSlice]) -> str:
    """渲染咨询模式提示词，融合模式指引、用户问题与安全切片上下文。"""
    instructions = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["critique"])

    parts = [
        f"{instructions}\n",
        "### Consultation Query\n",
        f"{query.strip()}\n",
    ]

    if slices:
        parts.append("\n### Injected Code Context Slices\n")
        for s in slices:
            parts.append(f"```\n{s.text.strip()}\n```\n")

    parts.append(
        "\n### Protocols for Reviewer Output\n"
        "1. If you need additional code files to deepen your analysis, specify them inside:\n"
        "<<<NEED-FILES>>>\n"
        "relative/path/to/file1.py\n"
        "relative/path/to/file2.py\n"
        "<<<END>>>\n\n"
        "2. If you propose an actionable DevTask, append the task draft inside:\n"
        "<<<TASK_DRAFT>>>\n"
        "### 任务 X.Y ⬜ 待确认 — <Task Title>\n"
        "#### 【涉及文件】\n"
        "- `[MODIFY]` `path/to/file.py`\n"
        "#### 【缺陷根因与修改目标】\n"
        "...\n"
        "#### 【目标签名与类型契约】\n"
        "...\n"
        "#### 【分步改造指引】\n"
        "...\n"
        "#### 【防御与边缘校验】\n"
        "...\n"
        "#### 【DoD 验证命令】\n"
        "...\n"
        "<<<END>>>\n"
    )

    return "\n".join(parts)


_SESSION_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
_LOCKS_MUTEX = threading.Lock()


def _get_session_lock(session_id: str) -> asyncio.Lock:
    with _LOCKS_MUTEX:
        lock = _SESSION_LOCKS.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            _SESSION_LOCKS[session_id] = lock
        return lock


def _enforce_log_quota(log_dir: Path, max_files: int = MAX_LOG_FILES_QUOTA) -> None:
    """清理历史日志，最多保留最新的 max_files 个文件（统合新旧格式与轮转文件）。"""
    try:
        enforce_unified_log_quota(log_dir, keep=max_files)
    except Exception:
        pass



async def run_consultation(
    req: ConsultRequest,
    *,
    config: Any,
    ctx: Any = None,
) -> ConsultResult:
    """执行免任务单绑定的架构咨询流程，具备降级卡防线、流式日志与防超时机制。"""
    session_id = sanitize_session_id(req.session_id)
    workspace_root = os.path.realpath(req.workspace_root)
    mode: ConsultMode = req.mode if req.mode in VALID_MODES else "critique"

    re_cfg = getattr(config, "reviewer_engine", None)
    client: Optional[ReviewerClient] = None
    if re_cfg is not None:
        client = create_reviewer_client(re_cfg)

    # 1. 引擎未配置降级防御（严禁主模型扮演）
    if client is None or not client.is_available():
        prov = getattr(re_cfg, "provider", "none") if re_cfg else "none"
        model = getattr(re_cfg, "model", "default") if re_cfg else "default"
        thinking = bool(getattr(re_cfg, "thinking", True)) if re_cfg else False
        return ConsultResult(
            status="degraded",
            session_id=session_id,
            mode=mode,
            findings="",
            log_path="",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "prompt_cache_hit_tokens": 0},
            truncated=False,
            skipped_files=[],
            degraded_reason="reviewer_not_configured",
            handoff_prompt=(
                f"[Reviewer Engine Not Configured]\n"
                f"当前工作区未配置有效的 Reviewer 引擎（当前 provider='{prov}'）。\n"
                f"【核心防线】：主执行模型严禁就地角色扮演 Reviewer 进行自审，以杜绝认知偏见。\n"
                f"请配置 quench_stack.yaml 中的 reviewer_engine，或在 IDE 中开启新会话切换至旗舰 Reviewer 模型重新提问。"
            ),
            suggested_task_draft=None,
            reviewer_identity={
                "provider": prov,
                "model": model,
                "thinking": thinking,
                "status": "degraded",
            },
            self_verification_warning="reviewer_not_configured",
        )

    runner_profile = getattr(config, "runner_profile", None)
    prov = getattr(re_cfg, "provider", "none") if re_cfg else "none"
    model = getattr(re_cfg, "model", "default") if re_cfg else "default"
    thinking = bool(getattr(re_cfg, "thinking", True)) if re_cfg else False
    self_verification_warning = check_self_verification_warning(runner_profile, prov, model)

    # 2. 准备日志环境
    log_dir = Path(workspace_root) / ".agents" / "logs" / "reviewer"
    log_dir.mkdir(parents=True, exist_ok=True)
    _enforce_log_quota(log_dir, max_files=MAX_LOG_FILES_QUOTA)
    allocated_log_path, _ = allocate_log_file(
        str(log_dir),
        slug=session_id,
        header_metadata={"mode": mode, "session_id": session_id},
    )
    log_file = Path(allocated_log_path)

    session_lock = _get_session_lock(session_id)

    cfg_window_lines = getattr(re_cfg, "default_window_lines", DEFAULT_WINDOW_LINES) if re_cfg else DEFAULT_WINDOW_LINES
    cfg_max_total_chars = getattr(re_cfg, "max_total_injection_chars", MAX_TOTAL_INJECTION_CHARS) if re_cfg else MAX_TOTAL_INJECTION_CHARS
    cfg_max_lines_per_slice = getattr(re_cfg, "max_lines_per_slice", MAX_LINES_PER_SLICE) if re_cfg else MAX_LINES_PER_SLICE

    # 3. 初始切片解析
    initial_files = list(req.context_files)
    slices, skipped_files, truncated = resolve_context_files(
        workspace_root,
        initial_files,
        max_files=MAX_CONTEXT_FILES,
        window_lines=cfg_window_lines,
        max_total_injection_chars=cfg_max_total_chars,
        max_lines_per_slice=cfg_max_lines_per_slice,
    )

    static_prefix = build_static_prefix(workspace_root, config)
    max_hops = min(max(req.max_hops, 0), 3)

    sink = RotatingFileSink(
        str(log_dir),
        session_id=session_id,
        max_bytes=MAX_LOG_FILE_BYTES,
        carry_over_bytes=64,
        flush_interval_s=0.2,
        log_file=allocated_log_path,
    )
    if self_verification_warning:
        sink.write_chunk_text(
            f"{datetime.now(timezone.utc).isoformat()} [warning] {self_verification_warning}\n"
        )
    heartbeat_sink = AdaptiveHeartbeatSink(
        file_emit=sink.write_chunk_text,
        mcp_context=ctx,
        interval_ms=1000,
    )

    async with session_lock:
        current_hop = 0
        all_findings = ""
        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_cache_hit_tokens": 0,
        }

        # 心跳后台任务（多通道能力分发 + FILE 常驻兜底）
        heartbeat_stop = asyncio.Event()
        stream_stats = {"chars": 0, "start_t": time.monotonic()}

        async def _heartbeat_worker():
            while not heartbeat_stop.is_set():
                try:
                    await asyncio.sleep(1.0)
                    if heartbeat_stop.is_set():
                        break
                    now = time.monotonic()
                    elapsed_s = now - stream_stats["start_t"]
                    tokens_est = stream_stats["chars"] // 4
                    await heartbeat_sink.apulse(tokens_so_far=tokens_est, elapsed_s=elapsed_s)
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass

        heartbeat_task = asyncio.create_task(_heartbeat_worker())

        try:
            active_slices = list(slices)
            active_skipped = list(skipped_files)

            while True:
                user_content = render_mode_prompt(mode, req.query, active_slices)
                messages = [
                    {"role": "system", "content": static_prefix},
                    {"role": "user", "content": user_content},
                ]

                timeout_s = getattr(re_cfg, "timeout_seconds", 60)

                async def _call_engine():
                    content_parts: list[str] = []
                    last_flush_t = time.monotonic()
                    coalescer = CoalescingTextSink(sink.write_chunk_text, tag="reasoning")

                    try:
                        accumulated_reasoning_chars = 0
                        async for chunk in client.stream_chat(messages):
                            reasoning = getattr(chunk, "reasoning", "") or ""
                            chunk_text = getattr(chunk, "text", "") or ""
                            if reasoning:
                                accumulated_reasoning_chars += len(reasoning)
                                stream_stats["chars"] = accumulated_reasoning_chars
                                if accumulated_reasoning_chars > MAX_REASONING_TOKENS_CEILING * 4:
                                    raise ReasoningBudgetExceededError("Reasoning tokens exceeded ceiling 32000")
                                coalescer.feed(reasoning)
                                now = time.monotonic()
                                if now - last_flush_t >= 0.5:
                                    sink.flush()
                                    last_flush_t = now

                            if chunk_text:
                                content_parts.append(chunk_text)

                        coalescer.close()
                        sink.flush()

                        full_text = "".join(content_parts)
                        return {"content": full_text, "usage": {}}
                    except (AttributeError, NotImplementedError):
                        coalescer.close()
                        resp = await client.acomplete(messages)
                        reasoning = extract_reasoning_text(resp)
                        if reasoning:
                            fallback_coalescer = CoalescingTextSink(sink.write_chunk_text, tag="reasoning")
                            fallback_coalescer.feed(reasoning)
                            fallback_coalescer.close()
                            sink.flush()
                        return resp
                    finally:
                        coalescer.close()
                        try:
                            sink.flush()
                        except Exception:
                            pass

                try:
                    raw_result = await asyncio.wait_for(_call_engine(), timeout=float(timeout_s))
                except asyncio.TimeoutError:
                    sink.write_chunk_text(
                        f"\n{datetime.now(timezone.utc).isoformat()} [error] Engine timeout after {timeout_s}s\n"
                    )
                    sink.flush()
                    return ConsultResult(
                        status="degraded",
                        session_id=session_id,
                        mode=mode,
                        findings="",
                        log_path=str(log_file),
                        usage=total_usage,
                        truncated=truncated,
                        skipped_files=active_skipped,
                        degraded_reason="timeout",
                        handoff_prompt=(
                            f"[Reviewer Engine Timeout]\n"
                            f"审查引擎在 {timeout_s} 秒内未完成响应。部分思考流已保存在 {log_file}。\n"
                            f"请尝试缩小 context_files 或提高 timeout_seconds 配置。"
                        ),
                        reviewer_identity={
                            "provider": prov,
                            "model": model,
                            "thinking": thinking,
                            "status": "degraded",
                        },
                        self_verification_warning=self_verification_warning,
                    )
                except ReasoningBudgetExceededError:
                    sink.write_chunk_text(
                        f"\n{datetime.now(timezone.utc).isoformat()} [error] Reasoning budget ceiling exceeded\n"
                    )
                    sink.flush()
                    return ConsultResult(
                        status="degraded",
                        session_id=session_id,
                        mode=mode,
                        findings="",
                        log_path=str(log_file),
                        usage=total_usage,
                        truncated=truncated,
                        skipped_files=active_skipped,
                        degraded_reason="reasoning_budget_exceeded",
                        handoff_prompt=(
                            "[Reasoning Budget Exceeded]\n"
                            "思考流超出 32000 tokens 安全天花板，已主动熔断。部分思考轨迹已保存至日志，请精简问题或降低上下文量。"
                        ),
                        reviewer_identity={
                            "provider": prov,
                            "model": model,
                            "thinking": thinking,
                            "status": "degraded",
                        },
                        self_verification_warning=self_verification_warning,
                    )
                except ReviewerEngineError as ee:
                    err_msg = str(ee)
                    sink.write_chunk_text(
                        f"\n{datetime.now(timezone.utc).isoformat()} [error] ReviewerEngineError: {err_msg}\n"
                    )
                    sink.flush()
                    if "401" in err_msg or "鉴权" in err_msg:
                        deg_reason = "auth_401"
                    elif "connection" in err_msg.lower() or "unavailable" in err_msg.lower() or "refused" in err_msg.lower():
                        deg_reason = "connect_error"
                    else:
                        deg_reason = "network"
                    return ConsultResult(
                        status="degraded",
                        session_id=session_id,
                        mode=mode,
                        findings="",
                        log_path=str(log_file),
                        usage=total_usage,
                        truncated=truncated,
                        skipped_files=active_skipped,
                        degraded_reason=deg_reason,
                        handoff_prompt=f"[Reviewer Error: {err_msg}]\n请检查引擎连接与 API 凭据配置，严禁由当前模型扮演 Reviewer。",
                        reviewer_identity={
                            "provider": prov,
                            "model": model,
                            "thinking": thinking,
                            "status": "degraded",
                        },
                        self_verification_warning=self_verification_warning,
                    )

                findings_text = raw_result.get("content", "")
                all_findings = findings_text
                usage_snap = extract_usage(raw_result)
                total_usage["prompt_tokens"] += usage_snap.prompt_tokens
                total_usage["completion_tokens"] += usage_snap.completion_tokens
                total_usage["total_tokens"] += (usage_snap.prompt_tokens + usage_snap.completion_tokens)
                total_usage["prompt_cache_hit_tokens"] += usage_snap.cached_tokens

                # 检查上下文扩展轮次
                need_files_match = NEED_FILES_PATTERN.search(findings_text)
                if need_files_match and current_hop < max_hops:
                    current_hop += 1
                    raw_extra_paths = [
                        line.strip()
                        for line in need_files_match.group(1).splitlines()
                        if line.strip() and not line.strip().startswith("#")
                    ]
                    if raw_extra_paths:
                        current_total_chars = sum(len(s.text) for s in active_slices)
                        remaining_budget = max(0, cfg_max_total_chars - current_total_chars)
                        extra_slices, extra_skipped, extra_trunc = resolve_context_files(
                            workspace_root,
                            raw_extra_paths,
                            max_files=MAX_CONTEXT_FILES - len(active_slices),
                            window_lines=cfg_window_lines,
                            max_total_injection_chars=remaining_budget,
                            max_lines_per_slice=cfg_max_lines_per_slice,
                        )
                        active_slices.extend(extra_slices)
                        active_skipped.extend(extra_skipped)
                        if extra_trunc:
                            truncated = True
                        continue

                break

            # 解析任务草案
            suggested_task_draft = None
            task_draft_match = TASK_DRAFT_PATTERN.search(all_findings)
            if task_draft_match:
                draft_markdown = task_draft_match.group(1).strip()
                suggested_task_draft = {
                    "raw_markdown": draft_markdown,
                    "parsed": True,
                }

            return ConsultResult(
                status="ok",
                session_id=session_id,
                mode=mode,
                findings=all_findings,
                log_path=str(log_file),
                usage=total_usage,
                truncated=truncated,
                skipped_files=active_skipped,
                degraded_reason=None,
                handoff_prompt=None,
                suggested_task_draft=suggested_task_draft,
                reviewer_identity={
                    "provider": prov,
                    "model": model,
                    "thinking": thinking,
                    "status": "active",
                },
                self_verification_warning=self_verification_warning,
            )

        finally:
            heartbeat_stop.set()
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            heartbeat_sink.on_finish("stop", {})
            sink.close()
