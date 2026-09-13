# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import os
from typing import Any, Optional
from adapters.base_adapter import EnvironmentAdapter


class GenericCLIAdapter(EnvironmentAdapter):
    """通用命令行适配器：适用于 Claude Code、Windsurf、裸 Git CLI 等非 IDE 环境。"""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = workspace_root

    def extract_session_id(self, context_input: Any) -> Optional[str]:
        """优先从环境变量或上下文提取，兜底生成工作区哈希代理键。"""
        env_sid = os.environ.get("QUENCH_SESSION_ID")
        if env_sid and env_sid.strip():
            return env_sid.strip()

        if isinstance(context_input, dict):
            sid = context_input.get("session_id") or context_input.get("conversationId")
            if sid and isinstance(sid, str):
                return sid.strip()

        ws = self.workspace_root
        if not ws and isinstance(context_input, dict):
            paths = context_input.get("workspacePaths", [])
            if paths and isinstance(paths, list):
                ws = paths[0]

        if ws:
            h = hashlib.sha256(os.path.normpath(ws).lower().encode("utf-8")).hexdigest()[:16]
            return f"cli-ws-{h}"

        return "cli-session-generic"

    def format_decision(self, decision: str, reason: str = "") -> str:
        """格式化为控制台彩色告警文本。"""
        d = decision.strip().lower()
        if d == "allow":
            return "[Quench Guard] ALLOW"

        if d == "deny":
            res = "\033[91m[Quench Guard] DENIED:\033[0m"
            if reason:
                res += f" {reason}"
            return res

        # ask 在非交互式 CLI 下降级为硬拦截或需通过 bypass 指令放行
        res = "\033[91m[Quench Guard] BLOCKED (NO_INTERACTIVE_UI):\033[0m"
        if reason:
            res += f" {reason}"
        return res

    def supports_interactive_ask(self) -> bool:
        """通用 CLI 环境无原生交互模态框。"""
        return False
