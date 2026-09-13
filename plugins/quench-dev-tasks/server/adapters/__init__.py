# -*- coding: utf-8 -*-
from __future__ import annotations

from adapters.base_adapter import EnvironmentAdapter, EnvironmentDetector, EnvironmentType
from adapters.antigravity_adapter import AntigravityAdapter
from adapters.cursor_adapter import CursorAdapter
from adapters.generic_cli_adapter import GenericCLIAdapter


def get_adapter(env_type: EnvironmentType, workspace_root: str | None = None) -> EnvironmentAdapter:
    """工厂函数：根据检测到的环境类型返回对应适配器实例。"""
    if env_type == EnvironmentType.ANTIGRAVITY:
        return AntigravityAdapter()
    elif env_type == EnvironmentType.CURSOR:
        return CursorAdapter(workspace_root=workspace_root)
    else:
        return GenericCLIAdapter(workspace_root=workspace_root)


__all__ = [
    "EnvironmentType",
    "EnvironmentDetector",
    "EnvironmentAdapter",
    "AntigravityAdapter",
    "CursorAdapter",
    "GenericCLIAdapter",
    "get_adapter",
]
