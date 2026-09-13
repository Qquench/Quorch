# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import json
import os
import re
import pytest


def get_plugin_dir() -> str:
    """获取 plugins/quench-dev-tasks 根目录绝对路径"""
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )


def test_templates_exist_and_valid_structure():
    """测试模板文件存在，且结构合法"""
    plugin_dir = get_plugin_dir()
    mcp_template_path = os.path.join(plugin_dir, "mcp_config.json.template")
    hooks_template_path = os.path.join(plugin_dir, "hooks.json.template")

    assert os.path.isfile(mcp_template_path), f"缺失模板文件: {mcp_template_path}"
    assert os.path.isfile(hooks_template_path), f"缺失模板文件: {hooks_template_path}"

    with open(mcp_template_path, "r", encoding="utf-8") as f:
        mcp_raw = f.read()

    with open(hooks_template_path, "r", encoding="utf-8") as f:
        hooks_raw = f.read()

    # 替换占位符为 dummy 验证 JSON 骨架有效性
    mcp_dummy = re.sub(r"\{\{[A-Z_]+\}\}", "dummy_val", mcp_raw)
    mcp_data = json.loads(mcp_dummy)
    assert "mcpServers" in mcp_data
    assert "quench-dev-tasks" in mcp_data["mcpServers"]

    hooks_dummy = re.sub(r"\{\{[A-Z_]+\}\}", "dummy_val", hooks_raw)
    hooks_data = json.loads(hooks_dummy)
    assert "quench-file-guard" in hooks_data
    assert "quench-context-injector" in hooks_data


def test_template_required_placeholders():
    """测试模板必须包含特定规范占位符"""
    plugin_dir = get_plugin_dir()
    mcp_template_path = os.path.join(plugin_dir, "mcp_config.json.template")
    hooks_template_path = os.path.join(plugin_dir, "hooks.json.template")

    with open(mcp_template_path, "r", encoding="utf-8") as f:
        mcp_content = f.read()

    assert "{{PYTHON_EXECUTABLE}}" in mcp_content
    assert "{{SERVER_SCRIPT_PATH}}" in mcp_content

    with open(hooks_template_path, "r", encoding="utf-8") as f:
        hooks_content = f.read()

    assert "{{PYTHON_EXECUTABLE}}" in hooks_content
    assert "{{FILE_GUARD_SCRIPT_PATH}}" in hooks_content
    assert "{{CONTEXT_INJECTOR_SCRIPT_PATH}}" in hooks_content
    # hooks.json 中的命令必须用双引号包裹占位符，支持含空格路径
    assert r'\"{{PYTHON_EXECUTABLE}}\"' in hooks_content
    assert r'\"{{FILE_GUARD_SCRIPT_PATH}}\"' in hooks_content


def test_render_with_unix_paths():
    """测试在类 Unix 路径下的占位符渲染"""
    plugin_dir = get_plugin_dir()
    mcp_template_path = os.path.join(plugin_dir, "mcp_config.json.template")
    hooks_template_path = os.path.join(plugin_dir, "hooks.json.template")

    with open(mcp_template_path, "r", encoding="utf-8") as f:
        mcp_text = f.read()

    with open(hooks_template_path, "r", encoding="utf-8") as f:
        hooks_text = f.read()

    python_exe = "/usr/local/bin/python3"
    server_script = "/opt/quorch/plugins/quench-dev-tasks/server/server.py"
    guard_script = "/opt/quorch/plugins/quench-dev-tasks/server/hooks/file_scope_guard.py"
    injector_script = "/opt/quorch/plugins/quench-dev-tasks/server/hooks/context_injector.py"

    mcp_rendered = mcp_text.replace("{{PYTHON_EXECUTABLE}}", python_exe).replace("{{SERVER_SCRIPT_PATH}}", server_script)
    mcp_obj = json.loads(mcp_rendered)
    assert mcp_obj["mcpServers"]["quench-dev-tasks"]["command"] == python_exe
    assert mcp_obj["mcpServers"]["quench-dev-tasks"]["args"] == [server_script]

    hooks_rendered = (
        hooks_text.replace("{{PYTHON_EXECUTABLE}}", python_exe)
        .replace("{{FILE_GUARD_SCRIPT_PATH}}", guard_script)
        .replace("{{CONTEXT_INJECTOR_SCRIPT_PATH}}", injector_script)
    )
    hooks_obj = json.loads(hooks_rendered)
    cmd = hooks_obj["quench-file-guard"]["PreToolUse"][0]["hooks"][0]["command"]
    assert f'"{python_exe}" "{guard_script}"' == cmd


def test_render_windows_backslash_safety():
    """核心安全测试：Windows 路径包含 \\Users, \\Scripts, \\test 等反斜杠序列时的 JSON 安全转义测试"""
    plugin_dir = get_plugin_dir()
    mcp_template_path = os.path.join(plugin_dir, "mcp_config.json.template")
    hooks_template_path = os.path.join(plugin_dir, "hooks.json.template")

    with open(mcp_template_path, "r", encoding="utf-8") as f:
        mcp_text = f.read()

    with open(hooks_template_path, "r", encoding="utf-8") as f:
        hooks_text = f.read()

    # 包含典型危险转义子串的 Windows 路径
    win_python = r"C:\Users\test\venv\Scripts\python.exe"
    win_server = r"C:\Users\test\quorch\plugins\quench-dev-tasks\server\server.py"
    win_guard = r"C:\Users\test\quorch\plugins\quench-dev-tasks\server\hooks\file_scope_guard.py"
    win_injector = r"C:\Users\test\quorch\plugins\quench-dev-tasks\server\hooks\context_injector.py"

    # 1. 验证天真（Naive）的裸反斜杠直接替换会破坏 JSON 解析（\U, \S, \t 是非法 JSON 转义）
    naive_mcp = mcp_text.replace("{{PYTHON_EXECUTABLE}}", win_python).replace("{{SERVER_SCRIPT_PATH}}", win_server)
    with pytest.raises(json.JSONDecodeError):
        json.loads(naive_mcp)

    # 2. 验证使用标准 json.dumps 转义后的替换能 100% 正确解析且原样恢复 Windows 路径
    def json_escape(path_str: str) -> str:
        # json.dumps("C:\\Users") -> '"C:\\\\Users"', 切片 [1:-1] 提取内部转义文本
        return json.dumps(path_str)[1:-1]

    safe_mcp = mcp_text.replace("{{PYTHON_EXECUTABLE}}", json_escape(win_python)).replace(
        "{{SERVER_SCRIPT_PATH}}", json_escape(win_server)
    )
    mcp_obj = json.loads(safe_mcp)
    assert mcp_obj["mcpServers"]["quench-dev-tasks"]["command"] == win_python
    assert mcp_obj["mcpServers"]["quench-dev-tasks"]["args"] == [win_server]

    safe_hooks = (
        hooks_text.replace("{{PYTHON_EXECUTABLE}}", json_escape(win_python))
        .replace("{{FILE_GUARD_SCRIPT_PATH}}", json_escape(win_guard))
        .replace("{{CONTEXT_INJECTOR_SCRIPT_PATH}}", json_escape(win_injector))
    )
    hooks_obj = json.loads(safe_hooks)
    guard_cmd = hooks_obj["quench-file-guard"]["PreToolUse"][0]["hooks"][0]["command"]
    expected_cmd = f'"{win_python}" "{win_guard}"'
    assert guard_cmd == expected_cmd


def test_gitignore_contains_generated_configs():
    """测试 .gitignore 中已配置生成配置文件的过滤规则"""
    root_dir = os.path.normpath(os.path.join(get_plugin_dir(), "..", ".."))
    gitignore_path = os.path.join(root_dir, ".gitignore")
    assert os.path.isfile(gitignore_path)

    with open(gitignore_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "plugins/quench-dev-tasks/mcp_config.json" in content
    assert "plugins/quench-dev-tasks/hooks.json" in content
