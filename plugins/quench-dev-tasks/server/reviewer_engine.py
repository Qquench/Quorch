# -*- coding: utf-8 -*-
"""Quench Reviewer Engine: 深度思考审查模型客户端与 Prompt 组装器.

负责连接高阶推理模型 (DeepSeek-Flash / Reasoner)，组装高命中率的静态架构上下文缓存前缀，
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
from typing import Any, Dict, List, Optional, Tuple

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
    ) -> Dict[str, Any]:
        """向 DeepSeek API 发起同步请求，具备精细化重试、有界读取与总耗时预算熔断。"""
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

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
        }
        if self.config.thinking:
            payload["thinking"] = {"type": "enabled"}
            if self.config.reasoning_effort:
                payload["reasoning_effort"] = self.config.reasoning_effort

        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        max_attempts = 1 + max(0, self.config.max_retries)

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

                    return {
                        "content": content,
                        "reasoning_content": reasoning_content,
                        "finish_reason": finish_reason,
                        "usage": body_json.get("usage", {}),
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

    async def acomplete(
        self,
        messages: List[Dict[str, str]],
        timeout: Optional[int] = None,
        *,
        total_deadline_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """异步非阻塞调用门面：使用 AnyIO 卸载至后台线程，防止阻塞 FastMCP 主事件循环。
        自带容量限制器 (_REVIEWER_LIMITER) 防拥塞，abandon_on_cancel=True 支持超时快速取消。
        """
        fn = functools.partial(self.complete, messages, timeout, total_deadline_s=total_deadline_s)
        async with _REVIEWER_LIMITER:
            return await anyio.to_thread.run_sync(fn, abandon_on_cancel=True)


class ReviewerClient(DeepSeekClient):
    """Generic OpenAI-compatible Reviewer Client supporting any standard /chat/completions provider."""
    pass

