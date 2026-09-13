# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional


class EnvironmentType(Enum):
    ANTIGRAVITY = "antigravity"
    CURSOR = "cursor"
    GENERIC_CLI = "generic_cli"


class EnvironmentDetector:
    """环境检测器（一次性调用，可缓存结果）"""

    @staticmethod
    def detect(context_input: dict | None = None, workspace_root: Optional[str] = None) -> EnvironmentType:
        """根据上下文信号判断当前运行环境。

        判断依据：
        1. payload 中是否含有 conversationId 或 toolCall 结构（Antigravity IDE）
        2. 工作区内是否存在 .cursor 配置目录，或包含 CURSOR 相关环境变量（Cursor IDE）
        3. 否则降级为通用命令行（Generic CLI，适用于 Claude Code、Windsurf 等）
        """
        payload = context_input if isinstance(context_input, dict) else {}

        # 1. Antigravity IDE 标志性信号
        if payload.get("conversationId") or ("toolCall" in payload and "workspacePaths" in payload):
            return EnvironmentType.ANTIGRAVITY

        # 2. Cursor IDE 标志性信号
        ws_root = workspace_root
        if not ws_root:
            ws_paths = payload.get("workspacePaths", [])
            if ws_paths and isinstance(ws_paths, list):
                ws_root = ws_paths[0]

        if ws_root and os.path.isdir(os.path.join(ws_root, ".cursor")):
            return EnvironmentType.CURSOR

        if os.environ.get("CURSOR_PROJECT_DIR") or os.environ.get("CURSOR_VERSION"):
            return EnvironmentType.CURSOR

        # 3. 默认安全降级
        return EnvironmentType.GENERIC_CLI


class EnvironmentAdapter(ABC):
    """环境适配器抽象基类（高频调用）"""

    @abstractmethod
    def extract_session_id(self, context_input: Any) -> Optional[str]:
        """从客户端上下文中提取会话唯一标识符"""
        pass

    @abstractmethod
    def format_decision(self, decision: str, reason: str = "") -> dict | str:
        """根据客户端类型格式化输出决策动作"""
        pass

    @abstractmethod
    def supports_interactive_ask(self) -> bool:
        """是否支持交互式确认弹窗（仅 Antigravity 支持）"""
        pass
