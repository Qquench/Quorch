#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# Ensure UTF-8 output on Windows
if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def json_escape_path(path_str: str) -> str:
    """对文件路径进行 JSON 安全转义，杜绝 Windows 反斜杠破坏 JSON 格式"""
    return json.dumps(path_str)[1:-1]


def detect_python_executable(project_root: str | None = None) -> str:
    """探测 Python 可执行文件路径。
    优先检查目标项目根目录下的 .venv 或 venv，其次检查当前运行环境的虚拟环境，兜底返回当前解释器。
    """
    if project_root:
        root = os.path.abspath(project_root)
        candidates = [".venv", "venv"]
        for cand in candidates:
            cand_dir = os.path.join(root, cand)
            if os.path.isdir(cand_dir):
                if sys.platform == "win32":
                    exe = os.path.join(cand_dir, "Scripts", "python.exe")
                else:
                    exe = os.path.join(cand_dir, "bin", "python")
                if os.path.isfile(exe):
                    return os.path.normpath(exe)

    # 若当前运行进程本身就在虚拟环境中
    if getattr(sys, "base_prefix", None) and sys.prefix != sys.base_prefix:
        return os.path.normpath(sys.executable)

    return os.path.normpath(sys.executable)


def _render_hooks_json(project_root: str, force: bool = False) -> None:
    """在目标项目的 .agents/ 目录下渲染并写入 hooks.json。
    遵循幂等性：若已存在且未指定 force 则跳过，指定 force 则覆盖。
    根据 sys.platform 自动施加 Windows cmd.exe /c 双引号剥离保护。
    """
    root = os.path.abspath(project_root)
    agents_dir = os.path.join(root, ".agents")
    os.makedirs(agents_dir, exist_ok=True)
    target_hooks_path = os.path.join(agents_dir, "hooks.json")

    if os.path.isfile(target_hooks_path) and not force:
        print("ℹ️ .agents/hooks.json 已存在，跳过覆盖。如需更新请配合 --force 覆盖。")
        return

    if os.path.isfile(target_hooks_path) and force:
        print("⚠️ 检测到 --force 参数，正在覆盖已有 .agents/hooks.json...")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    plugin_dir = os.path.dirname(script_dir)
    hooks_template_path = os.path.join(plugin_dir, "hooks.json.template")

    if not os.path.isfile(hooks_template_path):
        print(f"❌ 错误: Hooks 模板文件缺失: {hooks_template_path}", file=sys.stderr)
        return

    python_exe = detect_python_executable(root)
    guard_script = os.path.normpath(os.path.join(plugin_dir, "server", "hooks", "file_scope_guard.py"))
    injector_script = os.path.normpath(os.path.join(plugin_dir, "server", "hooks", "context_injector.py"))

    esc_python = json_escape_path(python_exe)
    esc_guard = json_escape_path(guard_script)
    esc_injector = json_escape_path(injector_script)

    with open(hooks_template_path, "r", encoding="utf-8") as f:
        content = f.read()

    rendered = (
        content.replace("{{PYTHON_EXECUTABLE}}", esc_python)
        .replace("{{FILE_GUARD_SCRIPT_PATH}}", esc_guard)
        .replace("{{CONTEXT_INJECTOR_SCRIPT_PATH}}", esc_injector)
    )

    try:
        hooks_data = json.loads(rendered)
    except Exception as e:
        print(f"❌ 渲染后 hooks.json 不是合法 JSON: {e}", file=sys.stderr)
        return

    with open(target_hooks_path, "w", encoding="utf-8") as f:
        json.dump(hooks_data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"✅ 已生成 .agents/hooks.json (配置生命周期拦截钩子，解释器: {python_exe})")


def generate_cursor_mcp_config(project_root: str, python_exe: str, force: bool = False) -> str:
    """在目标项目根目录下生成或安全合并 .cursor/mcp.json 配置。
    自动注册 quench-dev-tasks FastMCP 服务，并保留用户现有的其他 MCP 工具。
    返回目标配置文件路径。
    """
    root = os.path.abspath(project_root)
    cursor_dir = os.path.join(root, ".cursor")
    os.makedirs(cursor_dir, exist_ok=True)
    mcp_path = os.path.join(cursor_dir, "mcp.json")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    plugin_dir = os.path.dirname(script_dir)
    server_script = os.path.normpath(os.path.join(plugin_dir, "server", "server.py"))

    quench_server_def = {
        "command": python_exe,
        "args": [server_script],
    }

    existing_data: dict = {}
    if os.path.isfile(mcp_path):
        try:
            with open(mcp_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception as e:
            print(f"⚠️ 解析已有 .cursor/mcp.json 失败 ({e})，将重置该文件。")
            existing_data = {}

    if not isinstance(existing_data, dict):
        existing_data = {}

    mcp_servers = existing_data.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
        existing_data["mcpServers"] = mcp_servers

    if "quench-dev-tasks" in mcp_servers and not force:
        current_def = mcp_servers["quench-dev-tasks"]
        if current_def == quench_server_def:
            print("ℹ️ .cursor/mcp.json 中的 quench-dev-tasks 配置已存在且一致，跳过更新。")
            return mcp_path

    mcp_servers["quench-dev-tasks"] = quench_server_def

    with open(mcp_path, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"✅ 已生成/更新 .cursor/mcp.json (注册 quench-dev-tasks，解释器: {python_exe})")
    return mcp_path


def install_git_pre_commit_hook(project_root: str, force: bool = False) -> bool:
    """将 git_pre_commit_guard.py 部署至目标项目的 .git/hooks/pre-commit 并赋予可执行权限。
    若未初始化 Git 仓库，优雅提示并返回 False。
    若目标已存在自定义 pre-commit 钩子，采用链式追加策略注入调用。
    """
    root = os.path.abspath(project_root)
    git_dir = os.path.join(root, ".git")
    if not os.path.isdir(git_dir):
        print("⚠️ 目标目录不是 Git 仓库（未找到 .git 目录），跳过 Git Pre-commit Hook 安装。")
        return False

    hooks_dir = os.path.join(git_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    target_hook = os.path.join(hooks_dir, "pre-commit")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    guard_script = os.path.normpath(os.path.join(script_dir, "git_pre_commit_guard.py"))
    guard_script_unix = guard_script.replace("\\", "/")

    injection_block = (
        "\n# === Quench Git Pre-commit Guard Injection ===\n"
        f'python3 "{guard_script_unix}" "$@" || python "{guard_script_unix}" "$@"\n'
    )

    if os.path.isfile(target_hook):
        try:
            with open(target_hook, "r", encoding="utf-8", errors="ignore") as f:
                existing_content = f.read()
        except Exception as e:
            print(f"❌ 读取已有 pre-commit 钩子失败: {e}", file=sys.stderr)
            return False

        if "git_pre_commit_guard.py" in existing_content:
            print(f"ℹ️ Quench Pre-commit Guard 已存在于: {target_hook}")
            return True

        if force:
            hook_content = (
                "#!/usr/bin/env bash\n"
                "# Quench Git Pre-commit Guard Shim\n"
                "set -e\n"
                f'python3 "{guard_script_unix}" "$@" || python "{guard_script_unix}" "$@"\n'
            )
            with open(target_hook, "w", encoding="utf-8", newline="\n") as f:
                f.write(hook_content)
            try:
                os.chmod(target_hook, 0o755)
            except Exception:
                pass
            print(f"✅ 已强制覆盖安装 Quench Pre-commit Guard 至: {target_hook}")
            return True
        else:
            with open(target_hook, "a", encoding="utf-8", newline="\n") as f:
                f.write(injection_block)
            try:
                os.chmod(target_hook, 0o755)
            except Exception:
                pass
            print(f"✅ 已链式追加 Quench Pre-commit Guard 至现有 hook: {target_hook}")
            return True

    hook_content = (
        "#!/usr/bin/env bash\n"
        "# Quench Git Pre-commit Guard Shim\n"
        "set -e\n"
        f'python3 "{guard_script_unix}" "$@" || python "{guard_script_unix}" "$@"\n'
    )
    try:
        with open(target_hook, "w", encoding="utf-8", newline="\n") as f:
            f.write(hook_content)
        try:
            os.chmod(target_hook, 0o755)
        except Exception:
            pass
        print(f"✅ 已成功安装 Quench Pre-commit Guard 至: {target_hook}")
        return True
    except Exception as e:
        print(f"❌ 写入 pre-commit 钩子失败: {e}", file=sys.stderr)
        return False



def diagnose_environment(project_root: str) -> dict:
    """全面诊断目标项目的治理环境就绪状态。
    返回结构: {
        "is_git_repo": bool,
        "has_quench_stack": bool,
        "has_plugins_json": bool,
        "has_hooks_json": bool,
        "hooks_json_valid": bool,
        "python_valid": bool,
        "dependencies_ready": bool,
        "issues": list[str],
        "suggestions": list[str]
    }
    """
    root = os.path.abspath(project_root)
    issues: list[str] = []
    suggestions: list[str] = []

    # 1. 检查目标目录是否存在
    if not os.path.isdir(root):
        issues.append(f"目标项目根目录不存在: {root}")
        suggestions.append("请提供已存在的项目目录路径")
        return {
            "is_git_repo": False,
            "has_quench_stack": False,
            "has_plugins_json": False,
            "has_hooks_json": False,
            "hooks_json_valid": False,
            "python_valid": sys.version_info >= (3, 8),
            "dependencies_ready": False,
            "issues": issues,
            "suggestions": suggestions,
        }

    # 2. 检查 Git 仓库有效性
    is_git_repo = False
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and "true" in (res.stdout or "").strip().lower():
            is_git_repo = True
        else:
            issues.append("目标目录不是 Git 仓库（缺少 .git 目录）")
            suggestions.append("在项目根目录执行 'git init' 初始化版本控制")
    except FileNotFoundError:
        issues.append("git 命令未找到，请安装 Git 或将其添加到系统 PATH")
        suggestions.append("安装 Git 并配置系统环境变量 PATH: https://git-scm.com/")
    except Exception as e:
        issues.append(f"Git 检测失败: {e}")
        suggestions.append("请确保 Git 已安装并在项目目录中可用")

    # 3. 检查 .agents/quench_stack.yaml
    quench_stack_path = os.path.join(root, ".agents", "quench_stack.yaml")
    has_quench_stack = os.path.isfile(quench_stack_path)
    if not has_quench_stack:
        issues.append("缺少 Quench 核心配置文件: .agents/quench_stack.yaml")
        suggestions.append(f"运行 'python {os.path.abspath(__file__)} {project_root}' 初始化配置文件")

    # 4. 检查 .agents/plugins.json
    plugins_json_path = os.path.join(root, ".agents", "plugins.json")
    has_plugins_json = os.path.isfile(plugins_json_path)
    if not has_plugins_json:
        issues.append("缺少插件注册文件: .agents/plugins.json")
        suggestions.append(f"运行 'python {os.path.abspath(__file__)} {project_root}' 注册插件")

    # 5. 检查 .agents/hooks.json
    hooks_json_path = os.path.join(root, ".agents", "hooks.json")
    has_hooks_json = os.path.isfile(hooks_json_path)
    hooks_json_valid = False

    if not has_hooks_json:
        issues.append("缺少生命周期 Hook 配置文件: .agents/hooks.json (导致 PreToolUse 规范拦截与任务上下文注入失效)")
        suggestions.append(f"运行 'python {os.path.abspath(__file__)} {project_root} --force' 补齐 .agents/hooks.json")
    else:
        try:
            with open(hooks_json_path, "r", encoding="utf-8") as f:
                hooks_data = json.load(f)

            # 提取 command 字段并校验引用的路径可达性
            commands_found: list[str] = []

            def _extract_commands(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k == "command" and isinstance(v, str):
                            commands_found.append(v)
                        else:
                            _extract_commands(v)
                elif isinstance(obj, list):
                    for item in obj:
                        _extract_commands(item)

            _extract_commands(hooks_data)

            if not commands_found:
                issues.append(".agents/hooks.json 未包含任何有效的 Hook 命令定义")
                suggestions.append(f"运行 'python {os.path.abspath(__file__)} {project_root} --force' 重新生成 Hook 配置")
            else:
                unreachable_paths = []
                import shlex
                for cmd_str in commands_found:
                    clean_cmd = cmd_str.strip()
                    if clean_cmd.startswith('""') and clean_cmd.endswith('""'):
                        clean_cmd = clean_cmd[1:-1]
                    try:
                        tokens = shlex.split(clean_cmd, posix=False)
                    except Exception:
                        tokens = [t.strip('"') for t in clean_cmd.split('"') if t.strip()]
                    for tok in tokens:
                        clean_tok = tok.strip('"')
                        if os.path.isabs(clean_tok) and (clean_tok.lower().endswith(".py") or clean_tok.lower().endswith(".exe")):
                            if not os.path.isfile(clean_tok):
                                unreachable_paths.append(clean_tok)

                if unreachable_paths:
                    issues.append(f".agents/hooks.json 中引用的依赖路径在本地不存在: {', '.join(unreachable_paths)}")
                    suggestions.append(f"运行 'python {os.path.abspath(__file__)} {project_root} --force' 重新生成匹配当前环境的 Hook 配置")
                else:
                    hooks_json_valid = True
        except Exception as e:
            issues.append(f".agents/hooks.json 格式损坏（非有效 JSON）: {e}")
            suggestions.append(f"运行 'python {os.path.abspath(__file__)} {project_root} --force' 重新生成 hooks.json")

    # 6. 检查 Python 版本
    python_valid = sys.version_info >= (3, 8)
    if not python_valid:
        py_ver_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        issues.append(f"当前 Python 版本 ({py_ver_str}) 过低，推荐 Python >= 3.8")
        suggestions.append("请升级 Python 运行环境至 3.8 或更高版本")

    # 7. 检查关键依赖库
    missing_deps = []
    for dep in ["fastmcp", "yaml", "filelock"]:
        try:
            __import__(dep)
        except ImportError:
            missing_deps.append(dep)

    dependencies_ready = (len(missing_deps) == 0)
    if not dependencies_ready:
        issues.append(f"缺少关键 Python 依赖库: {', '.join(missing_deps)}")
        suggestions.append(f"在当前运行环境中执行: pip install {' '.join(missing_deps)}")

    return {
        "is_git_repo": is_git_repo,
        "has_quench_stack": has_quench_stack,
        "has_plugins_json": has_plugins_json,
        "has_hooks_json": has_hooks_json,
        "hooks_json_valid": hooks_json_valid,
        "python_valid": python_valid,
        "dependencies_ready": dependencies_ready,
        "issues": issues,
        "suggestions": suggestions,
    }


def print_diagnostic_report(diag: dict, project_root: str) -> None:
    root = os.path.abspath(project_root)
    print("=" * 60)
    print(f"🏥 Quench DevTasks 治理环境体检报告: {root}")
    print("=" * 60)
    print(f"• Git 仓库有效性:   {'✅ 是' if diag['is_git_repo'] else '❌ 否'}")
    print(f"• 核心配置文件:     {'✅ 已存在 (.agents/quench_stack.yaml)' if diag['has_quench_stack'] else '❌ 缺失'}")
    print(f"• 插件注册清单:     {'✅ 已就绪 (.agents/plugins.json)' if diag['has_plugins_json'] else '❌ 缺失'}")
    hooks_status = "✅ 已就绪 (.agents/hooks.json)" if diag.get("hooks_json_valid") else (
        "⚠️ 存在但配置失效" if diag.get("has_hooks_json") else "❌ 缺失 (生命周期拦截未生效)"
    )
    print(f"• 生命周期 Hooks:   {hooks_status}")
    print(f"• Python 运行环境:  {'✅ 合格 (>= 3.8)' if diag['python_valid'] else '❌ 版本过低'}")
    print(f"• 关键依赖库就绪:   {'✅ 全部就绪 (fastmcp, yaml, filelock)' if diag['dependencies_ready'] else '❌ 缺失部分依赖'}")
    print("-" * 60)
    if not diag["issues"]:
        print("🎉 恭喜！当前项目治理环境完全就绪，可无缝使用 Quench DevTasks。")
    else:
        print("⚠️ 诊断发现以下潜在问题与建议:")
        for idx, issue in enumerate(diag["issues"], 1):
            sugg = diag["suggestions"][idx - 1] if idx - 1 < len(diag["suggestions"]) else ""
            print(f"  {idx}. [问题] {issue}")
            if sugg:
                print(f"     [建议] {sugg}")
    print("=" * 60)


def init_project(
    project_root: str,
    project_name: str | None = None,
    force: bool = False,
    ide: str = "antigravity",
    install_hook: bool = False,
) -> None:
    """在 project_root 初始化 Quench DevTasks 治理配置。

    Args:
        project_root: 目标项目根目录路径。
        project_name: 项目名称，若未提供则默认使用 project_root 的文件夹名称。
        force: 是否强制覆盖已有 quench_stack.yaml 配置文件。
        ide: 目标接入 IDE 环境 (antigravity | cursor | all，默认 antigravity)。
        install_hook: 是否自动安装 Git Pre-commit 守卫脚本。
    """
    root = os.path.abspath(project_root)
    if not os.path.isdir(root):
        print(f"❌ 错误: 目标项目根目录不存在: {root}", file=sys.stderr)
        sys.exit(1)

    effective_name = project_name or os.path.basename(root)

    # 0. 检查 Git 仓库（友好提示但不强阻断）
    is_git = False
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and "true" in (res.stdout or "").strip().lower():
            is_git = True
    except Exception:
        pass

    if not is_git:
        print("⚠️ 提示: 目标目录暂未初始化为 Git 仓库。建议初始化完成后运行 'git init' 以获得完整的规范守卫能力。")

    # 1. 查找模板文件路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    plugin_dir = os.path.dirname(script_dir)
    plugins_parent_dir = os.path.dirname(plugin_dir)
    template_path = os.path.join(plugin_dir, "templates", "quench_stack.yaml")

    if not os.path.isfile(template_path):
        print(
            f"❌ 错误: Plugin 模板文件缺失: {template_path}\n"
            f"请检查 quench-dev-tasks Plugin 安装完整性。",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"🚀 开始在项目 [{effective_name}] ({root}) 初始化 Quench DevTasks 配置 (IDE 目标: {ide})...")

    # 2. 创建 .agents 目录
    agents_dir = os.path.join(root, ".agents")
    os.makedirs(agents_dir, exist_ok=True)

    # 3. 配置 plugins.json (仅 antigravity 或 all)
    if ide in ("antigravity", "all"):
        plugins_json_path = os.path.join(agents_dir, "plugins.json")
        norm_plugins_parent = os.path.normpath(plugins_parent_dir)

        if os.path.isfile(plugins_json_path):
            try:
                with open(plugins_json_path, "r", encoding="utf-8") as f:
                    plugins_data = json.load(f)
            except Exception:
                plugins_data = {}

            entries = plugins_data.setdefault("entries", [])
            already_configured = False
            for entry in entries:
                entry_path = entry.get("path", "")
                if os.path.normpath(entry_path).lower() == norm_plugins_parent.lower() or "quench-dev-tasks" in entry_path.lower():
                    already_configured = True
                    break

            if already_configured:
                print("ℹ️ .agents/plugins.json 已配置 quench-dev-tasks 插件路径，跳过添加。")
            else:
                entries.append({"path": norm_plugins_parent})
                with open(plugins_json_path, "w", encoding="utf-8") as f:
                    json.dump(plugins_data, f, indent=2, ensure_ascii=False)
                print(f"✅ 已在 .agents/plugins.json 中添加插件路径: {norm_plugins_parent}")
        else:
            plugins_data = {
                "entries": [
                    {"path": norm_plugins_parent}
                ]
            }
            with open(plugins_json_path, "w", encoding="utf-8") as f:
                json.dump(plugins_data, f, indent=2, ensure_ascii=False)
            print(f"✅ 已创建 .agents/plugins.json (注册插件路径: {norm_plugins_parent})")

    # 4. 创建 .agents/quench_stack.yaml
    stack_yaml_path = os.path.join(agents_dir, "quench_stack.yaml")
    if os.path.isfile(stack_yaml_path) and not force:
        print("ℹ️ .agents/quench_stack.yaml 已存在，跳过覆盖。如需更新请使用版本迁移检查或配合 --force 覆盖。")
    else:
        if os.path.isfile(stack_yaml_path) and force:
            print("⚠️ 检测到 --force 参数，正在覆盖已有 .agents/quench_stack.yaml...")
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        # 替换项目名称占位符
        customized_content = re.sub(
            r'project_name:\s*"[^"]*"',
            f'project_name: "{effective_name}"',
            template_content,
            count=1,
        )

        with open(stack_yaml_path, "w", encoding="utf-8") as f:
            f.write(customized_content)
        print(f"✅ 已创建 .agents/quench_stack.yaml (项目名称: {effective_name})")

    # 5. 创建 / 渲染 .agents/hooks.json (仅 antigravity 或 all)
    if ide in ("antigravity", "all"):
        _render_hooks_json(root, force=force)

    # 6. 创建任务目录结构
    dev_tasks_dir = os.path.join(root, "docs", "dev_tasks")
    archive_dir = os.path.join(dev_tasks_dir, "archive")
    os.makedirs(dev_tasks_dir, exist_ok=True)
    os.makedirs(archive_dir, exist_ok=True)
    print(f"✅ 已确认任务目录结构: {dev_tasks_dir} 及 {archive_dir}")

    # 7. 初始化默认 README.md (如果不存在)
    readme_path = os.path.join(dev_tasks_dir, "README.md")
    if not os.path.isfile(readme_path):
        readme_content = f"""# {effective_name} 开发任务管理

本项目接入 Quench 开发任务治理体系（quench-dev-tasks）。

## 任务状态图例
- `⬜ 待确认`：新提出的需求或架构整改方案，待人工审核。
- `✅ 已确认`：已通过审查或用户确认，待进入开发流程。
- `🔨 执行中`：正在由模型领单执行中（单核执行，同一时间只允许一个任务处于此状态）。
- `✔️ 已完成`：通过完整分步改造及 DoD 自动化命令验证。
- `⏭️ 跳过`：由于环境变动或需求废弃暂缓执行。
- `🔄 需返工`：在测试或审查中发现缺陷，需要退回重新整改。

## 常用交互
- 查阅进度：AI 调用 `dev_tasks_status`
- 领取任务：AI 调用 `dev_tasks_checkout`
- 标记完成：AI 调用 `dev_tasks_complete`
- 归档历史：AI 调用 `dev_tasks_archive`
"""
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(readme_content)
        print("✅ 已生成 docs/dev_tasks/README.md 说明文档。")

    # 8. Cursor MCP 配置与 Rules 规范注入 (仅 cursor 或 all)
    if ide in ("cursor", "all"):
        python_exe = detect_python_executable(root)
        generate_cursor_mcp_config(root, python_exe, force=force)
        try:
            from rules_exporter import RulesExporter
            RulesExporter.export_all(project_root=root, force=force)
        except Exception as e:
            print(f"⚠️ 导出 Cursor rules 规范失败: {e}", file=sys.stderr)

    # 9. 安装 Git Pre-commit Hook (若指定 install_hook)
    if install_hook:
        install_git_pre_commit_hook(root, force=force)

    if ide == "cursor":
        print(f"\n🎉 项目 [{effective_name}] Cursor 接入初始化完成！随时可在 Cursor 中连接 MCP 并开始开发。")
    elif ide == "all":
        print(f"\n🎉 项目 [{effective_name}] 全生态接入初始化完成！可在 Antigravity 与 Cursor 等多客户端协同开发。")
    else:
        print(f"\n🎉 项目 [{effective_name}] 初始化完成！随时可在 Antigravity IDE 中开始开发。")


def main():
    parser = argparse.ArgumentParser(
        description="Quench DevTasks 项目接入初始化脚本：为目标项目生成 .agents 插件注册与配置清单，或诊断环境就绪状态。"
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="目标项目根目录路径（默认当前目录）",
    )
    parser.add_argument(
        "--name",
        dest="project_name",
        default=None,
        help="项目名称（可选，默认使用目标目录文件夹名）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="健康体检模式：全面诊断目标项目的治理环境就绪状态",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制覆盖已有的 quench_stack.yaml 与 hooks.json（默认不覆盖）",
    )
    parser.add_argument(
        "--ide",
        choices=["antigravity", "cursor", "all"],
        default="antigravity",
        help="目标接入 IDE 环境 (antigravity | cursor | all，默认 antigravity)",
    )
    parser.add_argument(
        "--cursor",
        action="store_true",
        help="快捷选项：等同于 --ide cursor",
    )
    parser.add_argument(
        "--install-git-hook",
        action="store_true",
        help="自动将 Quench Git Pre-commit Guard 挂载到目标项目的 .git/hooks/pre-commit",
    )

    args = parser.parse_args()

    if args.check:
        diag = diagnose_environment(args.project_root)
        print_diagnostic_report(diag, args.project_root)
        return

    effective_ide = "cursor" if args.cursor else args.ide
    init_project(
        args.project_root,
        args.project_name,
        force=args.force,
        ide=effective_ide,
        install_hook=args.install_git_hook,
    )


if __name__ == "__main__":
    main()

