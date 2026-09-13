# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Optional
from adapters.base_adapter import EnvironmentAdapter


class AntigravityAdapter(EnvironmentAdapter):
    """Antigravity IDE 专有适配器：输出标准 JSON 报文与 Ask 弹窗契约。"""

    def extract_session_id(self, context_input: Any) -> Optional[str]:
        """从 Antigravity Hook 报文中提取 conversationId。"""
        if isinstance(context_input, dict):
            conv_id = context_input.get("conversationId")
            if conv_id and isinstance(conv_id, str):
                return conv_id.strip()
        return None

    def format_decision(self, decision: str, reason: str = "") -> dict:
        """格式化为 Antigravity 专有 JSON 报文对象与弹窗契约。"""
        d = decision.strip().lower()
        if d == "allow":
            return {"decision": "allow"}

        # 核心加固：Antigravity IDE 中必须使用 force_ask 才能穿透 Always Allow 缓存强制弹窗
        if d == "ask":
            d = "force_ask"

        out = {"decision": d}
        if reason:
            out["reason"] = reason
        return out

    def supports_interactive_ask(self) -> bool:
        """Antigravity IDE 原生支持 PreToolUse 交互式弹窗。"""
        return True
