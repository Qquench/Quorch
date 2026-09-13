# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

from adapters import (
    EnvironmentAdapter,
    EnvironmentDetector,
    EnvironmentType,
    AntigravityAdapter,
    CursorAdapter,
    GenericCLIAdapter,
    get_adapter,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_environment_detector_antigravity(temp_workspace):
    """验证 Antigravity IDE 环境检测"""
    # 含有 conversationId
    payload1 = {"conversationId": "conv-12345", "workspacePaths": [str(temp_workspace)]}
    assert EnvironmentDetector.detect(payload1) == EnvironmentType.ANTIGRAVITY

    # 含有 toolCall + workspacePaths 标准 Hook 结构
    payload2 = {"toolCall": {"name": "replace_file_content"}, "workspacePaths": [str(temp_workspace)]}
    assert EnvironmentDetector.detect(payload2) == EnvironmentType.ANTIGRAVITY


def test_environment_detector_cursor(temp_workspace):
    """验证 Cursor IDE 环境检测"""
    cursor_dir = temp_workspace / ".cursor"
    cursor_dir.mkdir(parents=True, exist_ok=True)

    # 包含 .cursor 目录的工作区
    payload = {"workspacePaths": [str(temp_workspace)]}
    assert EnvironmentDetector.detect(payload, workspace_root=str(temp_workspace)) == EnvironmentType.CURSOR

    # 通过环境变量识别
    empty_payload = {}
    with patch.dict(os.environ, {"CURSOR_PROJECT_DIR": str(temp_workspace)}):
        assert EnvironmentDetector.detect(empty_payload) == EnvironmentType.CURSOR


def test_environment_detector_generic_cli_fallback():
    """验证通用终端环境安全降级"""
    assert EnvironmentDetector.detect({}) == EnvironmentType.GENERIC_CLI
    assert EnvironmentDetector.detect(None) == EnvironmentType.GENERIC_CLI
    assert EnvironmentDetector.detect({"unknown": "signal"}) == EnvironmentType.GENERIC_CLI


def test_antigravity_adapter():
    """验证 Antigravity 适配器协议与行为契约"""
    adapter = AntigravityAdapter()
    assert adapter.supports_interactive_ask() is True

    # 提取 session_id
    assert adapter.extract_session_id({"conversationId": "sess-abc"}) == "sess-abc"
    assert adapter.extract_session_id({}) is None
    assert adapter.extract_session_id("invalid") is None

    # 决策格式化
    allow_res = adapter.format_decision("allow")
    assert allow_res == {"decision": "allow"}

    ask_res = adapter.format_decision("ask", reason="需要确认")
    assert ask_res == {"decision": "ask", "reason": "需要确认"}

    deny_res = adapter.format_decision("deny", reason="越界阻断")
    assert deny_res == {"decision": "deny", "reason": "越界阻断"}


def test_cursor_adapter(temp_workspace):
    """验证 Cursor 适配器终端文本格式化与会话标识推断"""
    adapter = CursorAdapter(workspace_root=str(temp_workspace))
    assert adapter.supports_interactive_ask() is False

    # 优先从 payload 提取
    assert adapter.extract_session_id({"session_id": "cursor-sess-1"}) == "cursor-sess-1"

    # 无显式 session 时通过工作区哈希推断
    inferred_id = adapter.extract_session_id({})
    assert inferred_id is not None
    assert inferred_id.startswith("cursor-")

    # 决策格式化（带颜色高亮文本）
    allow_text = adapter.format_decision("allow")
    assert "[Quench Guard] ALLOW" in allow_text

    deny_text = adapter.format_decision("deny", reason="未纳管生产文件")
    assert "[Quench Guard] DENIED" in deny_text
    assert "未纳管生产文件" in deny_text

    ask_text = adapter.format_decision("ask", reason="需确认")
    assert "[Quench Guard] ACTION REQUIRED" in ask_text
    assert "需确认" in ask_text


def test_generic_cli_adapter(temp_workspace):
    """验证通用命令行适配器退出与提示逻辑"""
    adapter = GenericCLIAdapter(workspace_root=str(temp_workspace))
    assert adapter.supports_interactive_ask() is False

    # 环境变量优先
    with patch.dict(os.environ, {"QUENCH_SESSION_ID": "cli-override-id"}):
        assert adapter.extract_session_id({}) == "cli-override-id"

    # 降级生成工作区标识
    sid = adapter.extract_session_id({})
    assert sid.startswith("cli-ws-")

    # 决策格式化
    allow_text = adapter.format_decision("allow")
    assert allow_text == "[Quench Guard] ALLOW"

    deny_text = adapter.format_decision("deny", reason="越界错误")
    assert "DENIED" in deny_text
    assert "越界错误" in deny_text

    ask_text = adapter.format_decision("ask", reason="非交互环境拦截")
    assert "BLOCKED (NO_INTERACTIVE_UI)" in ask_text


def test_get_adapter_factory(temp_workspace):
    """验证适配器工厂方法返回正确类型"""
    a1 = get_adapter(EnvironmentType.ANTIGRAVITY)
    assert isinstance(a1, AntigravityAdapter)

    a2 = get_adapter(EnvironmentType.CURSOR, workspace_root=str(temp_workspace))
    assert isinstance(a2, CursorAdapter)

    a3 = get_adapter(EnvironmentType.GENERIC_CLI, workspace_root=str(temp_workspace))
    assert isinstance(a3, GenericCLIAdapter)
