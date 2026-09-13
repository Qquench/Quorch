# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Any, Optional
from adapters.base_adapter import EnvironmentAdapter


class CursorAdapter(EnvironmentAdapter):
    """Cursor IDE 适配器：终端文本输出 + Git 分支/工作区会话推断。"""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = workspace_root

    def extract_session_id(self, context_input: Any) -> Optional[str]:
        """从上下文或 Git 分支/工作区哈希推断会话级代理标识符。"""
        if isinstance(context_input, dict):
            sid = context_input.get("session_id") or context_input.get("conversationId")
            if sid and isinstance(sid, str):
                return sid.strip()

        ws = self.workspace_root
        if not ws and isinstance(context_input, dict):
            paths = context_input.get("workspacePaths", [])
            if paths and isinstance(paths, list):
                ws = paths[0]

        if ws and os.path.isdir(ws):
            # 尝试通过 git branch 获取当前上下文标识
            try:
                out = subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=ws,
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                ).decode("utf-8", errors="ignore").strip()
                if out and out != "HEAD":
                    return f"cursor-branch-{out}"
            except Exception:
                pass

            # 降级为工作区路径哈希
            h = hashlib.sha256(os.path.normpath(ws).lower().encode("utf-8")).hexdigest()[:16]
            return f"cursor-ws-{h}"

        return None

    def format_decision(self, decision: str, reason: str = "") -> str:
        """格式化为 Cursor / 终端高可读性彩色文本。"""
        d = decision.strip().lower()
        if d == "allow":
            return "[Quench Guard] ALLOW: Modification permitted."

        if d == "deny":
            res = "\033[91m[Quench Guard] DENIED:\033[0m"
            if reason:
                res += f" {reason}"
            return res

        # ask 降级为警告/需确认提示
        res = "\033[93m[Quench Guard] ACTION REQUIRED:\033[0m"
        if reason:
            res += f" {reason}"
        return res

    def supports_interactive_ask(self) -> bool:
        """Cursor 目前不支持 PreToolUse 交互式模态确认。"""
        return False
