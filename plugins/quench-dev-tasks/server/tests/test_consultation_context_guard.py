# -*- coding: utf-8 -*-
"""Unit tests for ad-hoc consultation context guard & parameter defenses.

Verifies:
1. FastMCP tool registration for dev_reviewer_consult;
2. Path traversal guards (.., absolute path, symlink escapes);
3. Slicing window limits & total character budget constraints;
4. Prompt Cache static prefix byte-level identity & stability;
5. Session ID sanitization & filename injection prevention;
6. Negative assertions: invalid mode/workspace/query structured error handling without tracebacks;
7. Zero-hallucination degradation when engine is unconfigured.
"""
from pathlib import Path
import os
import pytest

from consultation import (
    CodeSlice,
    ConsultRequest,
    build_static_prefix,
    render_mode_prompt,
    resolve_context_files,
    run_consultation,
    sanitize_session_id,
)
from project_config import QuenchStackConfig, ReviewerEngineConfig
import server


@pytest.mark.anyio
async def test_dev_reviewer_consult_tool_registered():
    """断言 dev_reviewer_consult 工具已在 FastMCP 服务中成功注册且元数据完备。"""
    tool = await server.mcp.get_tool("dev_reviewer_consult")
    assert tool is not None
    assert tool.name == "dev_reviewer_consult"
    assert "Reviewer" in tool.description or "架构" in tool.description


def test_sanitize_session_id_validation():
    """断言 session_id 清洗与白名单校验，拒绝非法路径注入字符并拒绝超长输入。"""
    # 1. 正常值直接返回
    assert sanitize_session_id("session_123-abc") == "session_123-abc"

    # 2. None 或空串自动生成 12 字符十六进制串
    auto_id = sanitize_session_id(None)
    assert len(auto_id) == 12
    assert auto_id.isalnum()

    # 3. 负向断言：含斜杠路径注入必须抛出 ValueError
    with pytest.raises(ValueError, match=r"Invalid session_id"):
        sanitize_session_id("sess/ion")

    # 4. 负向断言：含反斜杠必须抛出 ValueError
    with pytest.raises(ValueError, match=r"Invalid session_id"):
        sanitize_session_id("sess\\ion")

    # 5. 负向断言：含相对路径上跳必须抛出 ValueError
    with pytest.raises(ValueError, match=r"Invalid session_id"):
        sanitize_session_id("../escape")

    # 6. 负向断言：长度超过 64 必须抛出 ValueError
    with pytest.raises(ValueError, match=r"Invalid session_id"):
        sanitize_session_id("a" * 65)


def test_resolve_context_files_path_traversal_guards(tmp_path: Path):
    """断言 resolve_context_files 对 ..、绝对路径、符号链接逃逸三类非法输入静默过滤不抛栈。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside_file = tmp_path / "outside_secret.txt"
    outside_file.write_text("SUPER_SECRET_KEY = 12345", encoding="utf-8")

    inside_file = ws / "valid_code.py"
    inside_file.write_text("def valid_function(): return 42\n", encoding="utf-8")

    # 符号链接逃逸尝试
    symlink_file = ws / "symlink_escape.py"
    try:
        os.symlink(str(outside_file), str(symlink_file))
        symlink_created = True
    except (OSError, NotImplementedError):
        symlink_created = False

    test_paths = [
        "../outside_secret.txt",                # 负向用例 1: 相对路径越界
        str(outside_file),                      # 负向用例 2: 绝对路径越界
        "valid_code.py",                        # 正向用例
    ]
    if symlink_created:
        test_paths.append("symlink_escape.py")  # 负向用例 3: 符号链接逃逸

    slices, skipped, truncated = resolve_context_files(str(ws), test_paths)

    # 断言越界文件均被记录在 skipped 列表中，绝不抛出异常
    assert "../outside_secret.txt" in skipped
    assert str(outside_file) in skipped
    if symlink_created:
        assert "symlink_escape.py" in skipped

    # 断言合法文件被正确切片
    assert len(slices) == 1
    assert slices[0].rel_path.replace("\\", "/") == "valid_code.py"
    assert "def valid_function():" in slices[0].text


def test_resolve_context_files_window_lines_and_budget_guards(tmp_path: Path):
    """断言切片行数不超过 window_lines，且总注入字符受 12000 预算约束。"""
    ws = tmp_path / "ws"
    ws.mkdir()

    # 构造 100 行大文件
    lines_100 = [f"line_{i} = {i} * 10\n" for i in range(1, 101)]
    big_file = ws / "big_module.py"
    big_file.write_text("".join(lines_100), encoding="utf-8")

    # 1. 窗口限制测试
    slices, skipped, truncated = resolve_context_files(
        str(ws),
        ["big_module.py"],
        window_lines=35,
    )
    assert len(slices) == 1
    assert slices[0].start_line == 1
    assert slices[0].end_line == 35
    assert slices[0].text.startswith("# file: big_module.py:1-35\n")

    # 2. 预算溢出测试 (10 个文件尝试填入，每个文件包含多行)
    many_files = []
    for f_idx in range(10):
        fname = f"chunk_{f_idx}.py"
        (ws / fname).write_text("".join([f"var_{f_idx}_{j} = 'x' * 80\n" for j in range(40)]), encoding="utf-8")
        many_files.append(fname)

    slices_budget, _, is_truncated = resolve_context_files(
        str(ws),
        many_files,
        max_files=6,
    )
    # 断言被截断且总注入字符 <= 12000
    assert is_truncated is True
    total_chars = sum(len(s.text) for s in slices_budget)
    assert total_chars <= 12000


def test_build_static_prefix_byte_level_identity_and_cache(tmp_path: Path):
    """断言 build_static_prefix 连续两次调用返回完全相同的字符串，保障 Prompt Cache 稳定。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    docs = ws / "docs"
    docs.mkdir()
    arch_file = docs / "arch.md"
    arch_file.write_text("# Test Architecture Baseline\nCore Domain Entities", encoding="utf-8")

    cfg = QuenchStackConfig(
        workspace_root=str(ws),
        project_name="TestProject",
        architecture_doc="docs/arch.md",
        constraints=["Constraint A", "Constraint B"],
    )

    prefix_1 = build_static_prefix(str(ws), cfg)
    prefix_2 = build_static_prefix(str(ws), cfg)

    # 绝对字节级一致性断言
    assert prefix_1 == prefix_2
    assert "Test Architecture Baseline" in prefix_1
    assert "Constraint A" in prefix_1
    assert "Quench Six Core Fields Standard" in prefix_1


@pytest.mark.anyio
async def test_dev_reviewer_consult_invalid_mode_returns_structured_error():
    """负向断言：传入非法 mode 时返回结构化错误字典，严禁抛栈中断 MCP 通信。"""
    res = await server.dev_reviewer_consult(
        workspace_root=".",
        query="Verify architectural integrity",
        mode="unsupported_mode",
    )
    assert isinstance(res, dict)
    assert res["status"] == "error"
    assert "Invalid mode" in res["error"]
    assert "critique" in res["error"]


@pytest.mark.anyio
async def test_dev_reviewer_consult_boundary_errors():
    """负向断言：非存在工作区路径、空问题与超长问题均返回结构化错误。"""
    # 1. 非法工作区路径
    res_ws = await server.dev_reviewer_consult(
        workspace_root="/non/existing/workspace/path_987",
        query="Some question",
    )
    assert res_ws["status"] == "error"
    assert "Invalid workspace_root" in res_ws["error"]

    # 2. 空问题
    res_empty = await server.dev_reviewer_consult(
        workspace_root=".",
        query="   ",
    )
    assert res_empty["status"] == "error"
    assert "Query cannot be empty" in res_empty["error"]

    # 3. 超过 8000 字符限制的问题
    res_toolong = await server.dev_reviewer_consult(
        workspace_root=".",
        query="A" * 8001,
    )
    assert res_toolong["status"] == "error"
    assert "exceeds maximum character budget" in res_toolong["error"]


@pytest.mark.anyio
async def test_dev_reviewer_consult_unconfigured_engine_degraded_safely(tmp_path: Path):
    """断言未配置有效引擎时，安全返回 degraded 降级卡且 findings 绝对为空（防角色扮演伪造审查）。"""
    ws = tmp_path / "ws_unconfigured"
    ws.mkdir()

    res = await server.dev_reviewer_consult(
        workspace_root=str(ws),
        query="Should we replace Redis with memory queue?",
        mode="evaluate",
    )

    assert isinstance(res, dict)
    assert res["status"] == "degraded"
    assert res["degraded_reason"] == "reviewer_not_configured"
    # 核心防角色扮演断言：findings 严禁包含伪造的审查正文
    assert res["findings"] == ""
    assert res["handoff_prompt"] is not None
    assert "严禁" in res["handoff_prompt"] or "请勿" in res["handoff_prompt"] or "Reviewer" in res["handoff_prompt"]
