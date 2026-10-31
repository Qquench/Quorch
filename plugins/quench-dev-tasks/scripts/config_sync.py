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
import shutil
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


def is_workspace_plugin_mounted(workspace_root: str, plugin_dir: Optional[str] = None) -> bool:
    """检查目标工作区的 .agents/plugins.json 是否已挂载 quench-dev-tasks 插件。"""
    if not workspace_root:
        return False
    p_dir = os.path.realpath(plugin_dir or get_default_plugin_dir())
    plugins_file = os.path.join(workspace_root, ".agents", "plugins.json")
    if not os.path.isfile(plugins_file):
        return False
    try:
        with open(plugins_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            return False

        target_name = os.path.basename(p_dir)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("enabled") is False:
                continue
            raw_path = entry.get("path")
            if not raw_path or not isinstance(raw_path, str):
                continue

            bases = [workspace_root, os.path.join(workspace_root, ".agents")]
            for base in bases:
                resolved = os.path.realpath(os.path.normpath(os.path.join(base, raw_path)))
                if resolved == p_dir:
                    return True
                child_resolved = os.path.realpath(os.path.normpath(os.path.join(resolved, target_name)))
                if child_resolved == p_dir:
                    return True
        return False
    except Exception:
        return False


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


def render_agents_mcp_config(
    project_root: str,
    python_exe: str,
    existing_data: Optional[dict] = None,
    plugin_dir: Optional[str] = None,
) -> dict:
    """根据模板纯函数渲染 .agents/mcp_config.json 结构并安全合并已有第三方配置。

    保持无副作用纯函数契约：不触碰磁盘，返回合并后的完整字典。
    """
    p_dir = os.path.normpath(plugin_dir or get_default_plugin_dir())
    py_exe = os.path.normpath(python_exe)
    server_script = os.path.normpath(os.path.join(p_dir, "server", "server.py"))
    mcp_template = os.path.join(p_dir, "mcp_config.json.template")

    if os.path.isfile(mcp_template):
        esc_python = json_escape_path(py_exe)
        esc_server = json_escape_path(server_script)
        with open(mcp_template, "r", encoding="utf-8") as f:
            template_content = f.read()
        rendered_str = template_content.replace("{{PYTHON_EXECUTABLE}}", esc_python).replace(
            "{{SERVER_SCRIPT_PATH}}", esc_server
        )
        try:
            rendered_json = json.loads(rendered_str)
            quench_def = rendered_json.get("mcpServers", {}).get(
                "quench-dev-tasks", {"command": py_exe, "args": [server_script]}
            )
        except Exception:
            quench_def = {"command": py_exe, "args": [server_script]}
    else:
        quench_def = {"command": py_exe, "args": [server_script]}

    out_data = dict(existing_data) if isinstance(existing_data, dict) else {}
    mcp_servers = dict(out_data.get("mcpServers", {})) if isinstance(out_data.get("mcpServers"), dict) else {}
    mcp_servers["quench-dev-tasks"] = quench_def
    res = dict(out_data)
    res["mcpServers"] = mcp_servers
    return res


def generate_agents_mcp_config(
    project_root: str,
    python_exe: str,
    force: bool = False,
    plugin_dir: Optional[str] = None,
    quiet: bool = True,
) -> str:
    """在目标项目的 .agents/ 目录下生成或安全合并 mcp_config.json 配置。

    特性：
    1. 自动注册 quench-dev-tasks FastMCP 服务，保留用户现有的其他第三方 MCP 工具；
    2. 已有 JSON 损坏时自动生成 .agents/mcp_config.json.bak 备份；
    3. 幂等性：内容一致且未指定 force 时跳过写入；
    4. 原子落盘：采用 atomic_write_file 杜绝写入中途中断损坏。

    返回目标配置文件路径。
    """
    root = os.path.abspath(project_root)
    agents_dir = os.path.join(root, ".agents")
    os.makedirs(agents_dir, exist_ok=True)
    target_path = os.path.normpath(os.path.join(agents_dir, "mcp_config.json"))

    existing_data: dict = {}
    if os.path.isfile(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception as e:
            bak_path = target_path + ".bak"
            try:
                shutil.copy2(target_path, bak_path)
            except Exception:
                pass
            if not quiet:
                print(f"⚠️ 解析已有 .agents/mcp_config.json 失败 ({e})，已备份至 {os.path.basename(bak_path)} 并重置该文件。")
            existing_data = {}

    if not isinstance(existing_data, dict):
        existing_data = {}

    merged_data = render_agents_mcp_config(
        project_root=root,
        python_exe=python_exe,
        existing_data=existing_data,
        plugin_dir=plugin_dir,
    )

    # 幂等性检查：若已有相同配置且未强刷，跳过写入
    if os.path.isfile(target_path) and not force:
        curr_def = existing_data.get("mcpServers", {}).get("quench-dev-tasks")
        new_def = merged_data.get("mcpServers", {}).get("quench-dev-tasks")
        if curr_def == new_def:
            if not quiet:
                print("ℹ️ .agents/mcp_config.json 中的 quench-dev-tasks 配置已存在且一致，跳过更新。")
            return target_path

    content = json.dumps(merged_data, indent=2, ensure_ascii=False) + "\n"
    atomic_write_file(target_path, content)
    if not quiet:
        print(f"✅ 已生成/更新 .agents/mcp_config.json (注册 quench-dev-tasks，解释器: {python_exe})")
    return target_path


def auto_heal_configs(
    plugin_dir: Optional[str] = None,
    workspace_root: Optional[str] = None,
    python_exe: Optional[str] = None,
    quiet: bool = True,
    force: bool = False,
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
    if force or not os.path.isfile(mcp_target) or os.path.getmtime(mcp_template) > os.path.getmtime(mcp_target):
        affected.append(mcp_target)

    # 检查插件级 hooks.json
    if force or not os.path.isfile(hooks_target) or os.path.getmtime(hooks_template) > os.path.getmtime(hooks_target):
        affected.append(hooks_target)

    # 检查工作区级 hooks.json 与 mcp_config.json（若提供 workspace_root）
    ws_hooks_target: Optional[str] = None
    ws_mcp_target: Optional[str] = None
    is_mounted = bool(workspace_root and is_workspace_plugin_mounted(workspace_root, p_dir))

    if workspace_root:
        ws_hooks_target = os.path.normpath(os.path.join(workspace_root, ".agents", "hooks.json"))
        ws_mcp_target = os.path.normpath(os.path.join(workspace_root, ".agents", "mcp_config.json"))

        if is_mounted:
            # 单源插件已挂载：不再向 .agents/ 写入 hooks.json 与 mcp_config.json
            # 若已有文件，剥离 quench 专属配置
            if os.path.isfile(ws_hooks_target):
                try:
                    with open(ws_hooks_target, "r", encoding="utf-8") as f:
                        h_data = json.load(f)
                    if isinstance(h_data, dict):
                        mutated = False
                        for k in ["quench-file-guard", "quench-context-injector"]:
                            if k in h_data:
                                h_data.pop(k)
                                mutated = True
                        if mutated:
                            if not h_data:
                                os.unlink(ws_hooks_target)
                            else:
                                atomic_write_file(ws_hooks_target, json.dumps(h_data, indent=2, ensure_ascii=False) + "\n")
                            affected.append(ws_hooks_target)
                except Exception:
                    pass

            if os.path.isfile(ws_mcp_target):
                try:
                    with open(ws_mcp_target, "r", encoding="utf-8") as f:
                        m_data = json.load(f)
                    if isinstance(m_data, dict):
                        servers = m_data.get("mcpServers")
                        mutated = False
                        if isinstance(servers, dict) and "quench-dev-tasks" in servers:
                            servers.pop("quench-dev-tasks")
                            mutated = True
                        if mutated:
                            has_other = False
                            for k, v in m_data.items():
                                if k == "mcpServers":
                                    if isinstance(v, dict) and len(v) > 0:
                                        has_other = True
                                elif v:
                                    has_other = True
                            if not has_other:
                                os.unlink(ws_mcp_target)
                            else:
                                atomic_write_file(ws_mcp_target, json.dumps(m_data, indent=2, ensure_ascii=False) + "\n")
                            affected.append(ws_mcp_target)
                except Exception:
                    pass
        else:
            if force or not os.path.isfile(ws_hooks_target) or os.path.getmtime(hooks_template) > os.path.getmtime(ws_hooks_target):
                affected.append(ws_hooks_target)

            if force or not os.path.isfile(ws_mcp_target) or os.path.getmtime(mcp_template) > os.path.getmtime(ws_mcp_target):
                affected.append(ws_mcp_target)

    if not affected:
        return False, []

    try:
        py_exe = os.path.normpath(python_exe or detect_python_executable(p_dir))
        mcp_rendered, hooks_rendered, ws_hooks_rendered = render_plugin_configs(
            plugin_dir=p_dir,
            python_exe=py_exe,
            workspace_root=workspace_root if not is_mounted else None,
        )
        if mcp_target in affected:
            atomic_write_file(mcp_target, mcp_rendered)
        if hooks_target in affected:
            atomic_write_file(hooks_target, hooks_rendered)

        if not is_mounted:
            if ws_hooks_target and ws_hooks_target in affected and ws_hooks_rendered:
                atomic_write_file(ws_hooks_target, ws_hooks_rendered)

            if ws_mcp_target and ws_mcp_target in affected:
                generate_agents_mcp_config(
                    project_root=workspace_root,
                    python_exe=py_exe,
                    force=True,
                    plugin_dir=p_dir,
                    quiet=True,
                )

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

    healed, affected = auto_heal_configs(
        workspace_root=args.workspace_root,
        quiet=False,
        force=args.force,
    )
    if not healed:
        print("[Quench] 配置文件已是最新，无需刷新。")
    else:
        print(f"[Quench] 已更新文件: {affected}")
