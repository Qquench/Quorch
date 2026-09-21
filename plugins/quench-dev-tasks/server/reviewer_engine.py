# -*- coding: utf-8 -*-
"""Quench Reviewer Engine: 深度思考审查模型客户端与 Prompt 组装器.

负责连接高阶推理模型 (DeepSeek-Flash / Reasoner)，组装高命中率的静态架构上下文缓存前缀，
并为任务规约强化 (Spec Refine) 与架构疑难升级 (Escalate) 提供确定性分析能力。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from project_config import QuenchStackConfig, ReviewerEngineConfig

# Windows UTF-8 控制台设防
if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


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


class PromptAssembler:
    """静态系统提示词组装器。
    
    ★ 核心防线：为保障 DeepSeek Prompt Cache 极致命中率（>1024 tokens 缓存后成本降至 $0.006/M），
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
        rules_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "rules",
            "dev-tasks-discipline.md",
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


class DeepSeekClient:
    """基于标准库实现的 DeepSeek API 客户端，具备退避重试与异常智能分级。"""

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
        if sys.platform == "win32":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                    for var in unique_candidates:
                        try:
                            val, _ = winreg.QueryValueEx(key, var)
                            if val and str(val).strip():
                                return str(val).strip()
                        except FileNotFoundError:
                            continue
            except Exception:
                pass

        return None

    def is_available(self) -> bool:
        """检查 Reviewer 引擎是否就绪。"""
        if self.config.provider != "deepseek":
            return False
        return bool(self.resolve_api_key())

    def complete(
        self,
        messages: List[Dict[str, str]],
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """向 DeepSeek API 发起请求，具备精细化重试与结果解析。"""
        if not self.is_available():
            raise ReviewerEngineUnavailableError(
                f"Reviewer 引擎未就绪 (provider='{self.config.provider}', api_key_env='{self.config.api_key_env}')"
            )

        api_key = self.resolve_api_key()
        endpoint = f"{self.config.base_url.rstrip('/')}/chat/completions"
        effective_timeout = timeout or self.config.timeout_seconds

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
                    raw_bytes = resp.read()
                    body_json = json.loads(raw_bytes.decode("utf-8"))

                    choice = body_json.get("choices", [{}])[0]
                    message = choice.get("message", {})
                    content = message.get("content", "")
                    reasoning_content = message.get("reasoning_content", "")

                    return {
                        "content": content,
                        "reasoning_content": reasoning_content,
                        "usage": body_json.get("usage", {}),
                        "raw": body_json,
                    }

            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass

                # 401 鉴权失败：不可重试，立即报错
                if e.code == 401:
                    raise ReviewerAuthenticationError(
                        f"[HTTP 401 Unauthorized] DeepSeek API 凭据鉴权失败: {err_body}"
                    )
                # 400 参数非法：不可重试，立即报错
                elif e.code == 400:
                    raise ReviewerBadRequestError(
                        f"[HTTP 400 Bad Request] DeepSeek 请求参数非法: {err_body}"
                    )
                # 403 / 404：不可重试
                elif e.code in (403, 404):
                    raise ReviewerEngineError(f"[HTTP {e.code}] 接口调用失败: {err_body}")

                # 429（流控）或 5xx（服务端错误）：支持有限次数退避重试
                if (e.code == 429 or e.code >= 500) and attempt < max_attempts - 1:
                    backoff_sec = 1.0 * (2 ** attempt)
                    time.sleep(backoff_sec)
                    continue

                raise ReviewerEngineError(f"[HTTP {e.code}] 超过最大重试次数: {err_body}")

            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < max_attempts - 1:
                    backoff_sec = 1.0 * (2 ** attempt)
                    time.sleep(backoff_sec)
                    continue
                raise ReviewerEngineError(f"[Network Error] 网络通信超时或异常: {e}")

        raise ReviewerEngineError("请求异常终止")
