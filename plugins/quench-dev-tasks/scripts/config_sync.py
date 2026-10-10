#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quench DevTasks 跨仓库自适应配置同步与运行时静默自愈模块。

功能：
1. 毫秒级比对模板 (mcp_config.json.template, hooks.json.template) 与生成物的同步状态；
2. 无论从哪个业务项目触发调用，当检测到模板更新或本地配置缺失时，静默自动重新渲染；
3. 支持同步刷新插件本体配置及当前工作区的 .agents/hooks.json。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import List, Optional, Tuple


def json_escape_path(path_str: str) -> str:
    """对文件路径进行 JSON 安全转义，杜绝 Windows 反斜杠破坏 JSON 格式"""
    return json.dumps(path_str)[1:-1]


def atomic_write_file(target_path: str, content: str) -> None:
    """原子化写入文件：先写临时文件后原子替换"""
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir, exist_ok=True)
    temp_fd, temp_file = tempfile.mkstemp(dir=target_dir, text=True)
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp_file, target_path)
    except Exception:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
        raise


def get_default_plugin_dir() -> str:
    """获取 plugins/quench-dev-tasks 目录绝对路径"""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.dirname(scripts_dir))


def detect_python_executable(plugin_dir: Optional[str] = None) -> str:
    """探测 Python 解释器路径：优先插件所属上级仓库的 venv，兜底返回当前解释器"""
    p_dir = plugin_dir or get_default_plugin_dir()
    repo_root = os.path.normpath(os.path.join(p_dir, "..", ".."))

    candidates = [
        os.path.join(repo_root, "venv", "Scripts", "python.exe"),
        os.path.join(repo_root, ".venv", "Scripts", "python.exe"),
        os.path.join(repo_root, "venv", "bin", "python"),
        os.path.join(repo_root, ".venv", "bin", "python"),
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            return os.path.normpath(cand)

    if getattr(sys, "base_prefix", None) and sys.prefix != sys.base_prefix:
        return os.path.normpath(sys.executable)

    return os.path.normpath(sys.executable)


def render_plugin_configs(
    plugin_dir: Optional[str] = None,
    python_exe: Optional[str] = None,
    workspace_root: Optional[str] = None,
) -> Tuple[str, str, Optional[str]]:
    """根据模板动态渲染 mcp_config.json 和 hooks.json，并可选同步目标工作区的 hooks.json。"""
    p_dir = os.path.normpath(plugin_dir or get_default_plugin_dir())
    py_exe = os.path.normpath(python_exe or detect_python_executable(p_dir))

    mcp_template = os.path.join(p_dir, "mcp_config.json.template")
    hooks_template = os.path.join(p_dir, "hooks.json.template")

    if not os.path.isfile(mcp_template):
        raise FileNotFoundError(f"MCP 模板文件缺失: {mcp_template}")
    if not os.path.isfile(hooks_template):
        raise FileNotFoundError(f"Hooks 模板文件缺失: {hooks_template}")

    server_script = os.path.normpath(os.path.join(p_dir, "server", "server.py"))
    guard_script = os.path.normpath(os.path.join(p_dir, "server", "hooks", "file_scope_guard.py"))
    injector_script = os.path.normpath(os.path.join(p_dir, "server", "hooks", "context_injector.py"))

    esc_python = json_escape_path(py_exe)
    esc_server = json_escape_path(server_script)
    esc_guard = json_escape_path(guard_script)
    esc_injector = json_escape_path(injector_script)

    # 1. 渲染 mcp_config.json
    with open(mcp_template, "r", encoding="utf-8") as f:
        mcp_content = f.read()
    mcp_rendered = mcp_content.replace("{{PYTHON_EXECUTABLE}}", esc_python).replace(
        "{{SERVER_SCRIPT_PATH}}", esc_server
    )

    # 2. 渲染 hooks.json
    with open(hooks_template, "r", encoding="utf-8") as f:
        hooks_content = f.read()
    hooks_rendered = (
        hooks_content.replace("{{PYTHON_EXECUTABLE}}", esc_python)
        .replace("{{FILE_GUARD_SCRIPT_PATH}}", esc_guard)
        .replace("{{CONTEXT_INJECTOR_SCRIPT_PATH}}", esc_injector)
        .replace("{{GUARD_SCRIPT_PATH}}", esc_guard)
        .replace("{{INJECTOR_SCRIPT_PATH}}", esc_injector)
    )

    # 3. 渲染目标工作区的 .agents/hooks.json
    workspace_hooks_rendered: Optional[str] = None
    if workspace_root:
        ws_root = os.path.abspath(workspace_root)
        esc_ws = json_escape_path(ws_root)
        workspace_hooks_rendered = (
            hooks_content.replace("{{PYTHON_EXECUTABLE}}", esc_python)
            .replace("{{FILE_GUARD_SCRIPT_PATH}}", esc_guard)
            .replace("{{CONTEXT_INJECTOR_SCRIPT_PATH}}", esc_injector)
            .replace("{{GUARD_SCRIPT_PATH}}", esc_guard)
            .replace("{{INJECTOR_SCRIPT_PATH}}", esc_injector)
            .replace("{{WORKSPACE_ROOT}}", esc_ws)
        )

    return mcp_rendered, hooks_rendered, workspace_hooks_rendered


def auto_heal_configs(
    plugin_dir: Optional[str] = None,
    workspace_root: Optional[str] = None,
    python_exe: Optional[str] = None,
    quiet: bool = True,
) -> Tuple[bool, List[str]]:
    """毫秒级检查模板与衍生配置的更新状态，若有落后或缺失则自动原子刷新。
    
    返回 (True, affected_files) 表示执行了配置重新生成与自愈，(False, []) 表示当前配置已是最新无需改动。
    """
    p_dir = os.path.normpath(plugin_dir or get_default_plugin_dir())
    mcp_template = os.path.join(p_dir, "mcp_config.json.template")
    hooks_template = os.path.join(p_dir, "hooks.json.template")

    if not os.path.isfile(mcp_template) or not os.path.isfile(hooks_template):
        return False, []

    mcp_target = os.path.join(p_dir, "mcp_config.json")
    hooks_target = os.path.join(p_dir, "hooks.json")

    affected: List[str] = []

    # 检查插件级 mcp_config.json
    if not os.path.isfile(mcp_target) or os.path.getmtime(mcp_template) > os.path.getmtime(mcp_target):
        affected.append(mcp_target)

    # 检查插件级 hooks.json
    if not os.path.isfile(hooks_target) or os.path.getmtime(hooks_template) > os.path.getmtime(hooks_target):
        affected.append(hooks_target)

    # 检查工作区级 hooks.json（若提供 workspace_root）
    ws_hooks_target: Optional[str] = None
    if workspace_root:
        ws_hooks_target = os.path.normpath(os.path.join(workspace_root, ".agents", "hooks.json"))
        if not os.path.isfile(ws_hooks_target) or os.path.getmtime(hooks_template) > os.path.getmtime(ws_hooks_target):
            affected.append(ws_hooks_target)

    if not affected:
        return False, []

    try:
        mcp_rendered, hooks_rendered, ws_hooks_rendered = render_plugin_configs(
            plugin_dir=p_dir,
            python_exe=python_exe,
            workspace_root=workspace_root,
        )
        if mcp_target in affected:
            atomic_write_file(mcp_target, mcp_rendered)
        if hooks_target in affected:
            atomic_write_file(hooks_target, hooks_rendered)

        if ws_hooks_target and ws_hooks_target in affected and ws_hooks_rendered:
            atomic_write_file(ws_hooks_target, ws_hooks_rendered)

        if not quiet:
            print(f"[Quench] 运行时配置自愈完成: 已同步 {len(affected)} 个配置文件。")
        return True, affected
    except Exception as e:
        if not quiet:
            print(f"[Quench] 警告: 运行时配置自愈遇到异常: {e}", file=sys.stderr)
        return False, []


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Quench DevTasks 跨仓配置同步与自愈")
    parser.add_argument("--workspace-root", default=None, help="目标工作区根路径")
    parser.add_argument("--force", action="store_true", help="强制覆盖渲染")
    args = parser.parse_args()

    healed, affected = auto_heal_configs(workspace_root=args.workspace_root, quiet=False)
    if not healed:
        print("[Quench] 配置文件已是最新，无需刷新。")
    else:
        print(f"[Quench] 已更新文件: {affected}")
