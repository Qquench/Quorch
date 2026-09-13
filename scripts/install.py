#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Quench Dev Orchestrator (quorch) - 跨平台自适应安装与环境引导脚本
Cross-platform adaptive installation and configuration bootstrapping tool.

支持功能：
- 跨平台 Python 虚拟环境探测与必要依赖检查/安装
- 读取 .template 模板文件，自动渲染生成本地生效的 mcp_config.json 与 hooks.json
- Pre-flight 预检：目录句柄锁定探测、Windows MAX_PATH 长度审计、配置快照备份
- Rollback 回滚：一键从快照恢复旧版配置文件
- 冒烟自检与一键项目接入支持
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

# 跨平台控制台 UTF-8 编码防御
if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REQUIRED_DEPENDENCIES = [
    ("fastmcp", "fastmcp>=2.0"),
    ("filelock", "filelock>=3.0"),
    ("yaml", "pyyaml>=6.0"),
    ("pytest", "pytest"),
]


def get_repo_root() -> str:
    """获取代码仓库根目录绝对路径"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, ".."))


def get_plugin_dir(repo_root: Optional[str] = None) -> str:
    """获取 plugins/quench-dev-tasks 目录绝对路径"""
    root = repo_root or get_repo_root()
    return os.path.normpath(os.path.join(root, "plugins", "quench-dev-tasks"))


def get_backup_path(repo_root: Optional[str] = None) -> str:
    """获取快照备份文件路径"""
    root = repo_root or get_repo_root()
    return os.path.normpath(os.path.join(root, ".agents", ".quench_path_backup.json"))


def detect_python_executable(repo_root: Optional[str] = None) -> str:
    """自适应探测 Python 可执行文件路径。
    优先检查当前活跃的虚拟环境，其次检查仓库根目录下的 .venv 或 venv。
    """
    root = repo_root or get_repo_root()

    # 1. 若当前运行进程本身就在虚拟环境中
    if getattr(sys, "base_prefix", None) and sys.prefix != sys.base_prefix:
        return os.path.normpath(sys.executable)

    # 2. 检查根目录下的 .venv 与 venv
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

    # 3. 兜底返回当前 python 解释器
    return os.path.normpath(sys.executable)


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


def render_configs(plugin_dir: str, python_exe: str) -> Tuple[str, str]:
    """根据模板动态渲染 mcp_config.json 和 hooks.json。

    Returns:
        (mcp_config_path, hooks_config_path)
    """
    p_dir = os.path.normpath(plugin_dir)
    mcp_template = os.path.join(p_dir, "mcp_config.json.template")
    hooks_template = os.path.join(p_dir, "hooks.json.template")

    if not os.path.isfile(mcp_template):
        raise FileNotFoundError(f"MCP 模板文件缺失: {mcp_template}")
    if not os.path.isfile(hooks_template):
        raise FileNotFoundError(f"Hooks 模板文件缺失: {hooks_template}")

    server_script = os.path.normpath(os.path.join(p_dir, "server", "server.py"))
    guard_script = os.path.normpath(os.path.join(p_dir, "server", "hooks", "file_scope_guard.py"))
    injector_script = os.path.normpath(os.path.join(p_dir, "server", "hooks", "context_injector.py"))

    # 转义路径
    esc_python = json_escape_path(python_exe)
    esc_server = json_escape_path(server_script)
    esc_guard = json_escape_path(guard_script)
    esc_injector = json_escape_path(injector_script)

    # 1. 渲染 mcp_config.json
    with open(mcp_template, "r", encoding="utf-8") as f:
        mcp_content = f.read()

    mcp_rendered = mcp_content.replace("{{PYTHON_EXECUTABLE}}", esc_python).replace(
        "{{SERVER_SCRIPT_PATH}}", esc_server
    )
    # 严格校验 JSON 合法性
    try:
        json.loads(mcp_rendered)
    except Exception as e:
        raise ValueError(f"渲染后 mcp_config.json 不是合法 JSON: {e}") from e

    out_mcp_path = os.path.join(p_dir, "mcp_config.json")
    atomic_write_file(out_mcp_path, mcp_rendered)

    # 2. 渲染 hooks.json
    with open(hooks_template, "r", encoding="utf-8") as f:
        hooks_content = f.read()

    hooks_rendered = (
        hooks_content.replace("{{PYTHON_EXECUTABLE}}", esc_python)
        .replace("{{FILE_GUARD_SCRIPT_PATH}}", esc_guard)
        .replace("{{CONTEXT_INJECTOR_SCRIPT_PATH}}", esc_injector)
    )
    try:
        hooks_data = json.loads(hooks_rendered)
    except Exception as e:
        raise ValueError(f"渲染后 hooks.json 不是合法 JSON: {e}") from e

    out_hooks_path = os.path.join(p_dir, "hooks.json")
    atomic_write_file(out_hooks_path, json.dumps(hooks_data, indent=2, ensure_ascii=False) + "\n")

    return out_mcp_path, out_hooks_path


def run_preflight(plugin_dir: str, backup_path: str) -> Tuple[bool, List[str]]:
    """执行安装前 Pre-flight 检查。

    检查项：
    1. 目录/文件句柄锁定探测（os.rename 原地试探 + 可选 psutil 诊断）；
    2. Windows MAX_PATH 长度审计（>200 警告，>250 阻断）；
    3. 备份快照写入到 .agents/.quench_path_backup.json。

    Returns:
        (passed: bool, messages: list[str])
    """
    messages: List[str] = []
    passed = True
    p_dir = os.path.normpath(plugin_dir)
    repo_root = os.path.normpath(os.path.join(p_dir, "..", ".."))

    # 1. MAX_PATH 长度审计（检查最深目录层级）
    path_len = max(len(os.path.abspath(p_dir)), len(os.path.abspath(repo_root)))
    if sys.platform == "win32":
        if path_len > 250:
            passed = False
            messages.append(
                f"❌ [MAX_PATH 阻断] 当前安装路径长度 ({path_len} 字符) 接近 Windows 260 MAX_PATH 限制，请移至更浅目录！"
            )
        elif path_len > 200:
            messages.append(
                f"⚠️ [MAX_PATH 警告] 当前安装路径长度为 {path_len} 字符（建议小于 200 字符，以防嵌套文件超限）。"
            )
        else:
            messages.append(f"✅ 路径长度安全审计通过 (长度: {path_len} 字符)")
    else:
        messages.append(f"✅ 平台路径检查通过 ({sys.platform})")

    # 2. 句柄占用探测
    is_locked = False
    lock_err_detail = ""
    if os.path.exists(p_dir):
        try:
            # 原地重命名测试：若文件夹被其他排他性进程锁定，Windows 下会抛出 PermissionError
            os.rename(p_dir, p_dir)
        except PermissionError as e:
            is_locked = True
            lock_err_detail = str(e)
        except OSError as e:
            # WinError 5 (拒绝访问) 或 WinError 32 (另一个程序正在使用此文件)
            if getattr(e, "winerror", 0) in (5, 32):
                is_locked = True
                lock_err_detail = str(e)

    if is_locked:
        passed = False
        messages.append(f"❌ [目录句柄锁定] 目录被外部进程锁定占用，无法执行安装或更名: {lock_err_detail}")
    else:
        messages.append("✅ 目录句柄占用检测通过（无排他进程锁定）")

    # 3. 备份快照写入
    try:
        backup_dir = os.path.dirname(backup_path)
        os.makedirs(backup_dir, exist_ok=True)

        files_map: Dict[str, Optional[str]] = {}
        mcp_path = os.path.join(p_dir, "mcp_config.json")
        hooks_path = os.path.join(p_dir, "hooks.json")

        if os.path.isfile(mcp_path):
            with open(mcp_path, "r", encoding="utf-8") as f:
                files_map["plugins/quench-dev-tasks/mcp_config.json"] = f.read()
        else:
            files_map["plugins/quench-dev-tasks/mcp_config.json"] = None

        if os.path.isfile(hooks_path):
            with open(hooks_path, "r", encoding="utf-8") as f:
                files_map["plugins/quench-dev-tasks/hooks.json"] = f.read()
        else:
            files_map["plugins/quench-dev-tasks/hooks.json"] = None

        snapshot = {
            "snapshot_version": "1.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "python_executable": sys.executable,
            "files": files_map,
        }
        atomic_write_file(backup_path, json.dumps(snapshot, indent=2, ensure_ascii=False))
        messages.append(f"✅ 配置快照备份完成: {backup_path}")
    except Exception as e:
        messages.append(f"⚠️ 快照备份写入警告: {e}")

    return passed, messages


def rollback_configuration(plugin_dir: str, backup_path: str) -> bool:
    """从快照备份一键恢复配置文件。

    Returns:
        success: bool
    """
    if not os.path.isfile(backup_path):
        print(f"❌ 回滚失败: 备份快照文件不存在: {backup_path}", file=sys.stderr)
        return False

    try:
        with open(backup_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
    except Exception as e:
        print(f"❌ 回滚失败: 解析备份快照文件失败（格式损坏）: {e}", file=sys.stderr)
        return False

    files_map = snapshot.get("files", {})
    p_dir = os.path.normpath(plugin_dir)
    repo_root = os.path.normpath(os.path.join(p_dir, "..", ".."))

    restored_count = 0
    for rel_path, content in files_map.items():
        full_path = os.path.normpath(os.path.join(repo_root, rel_path))
        if content is not None:
            atomic_write_file(full_path, content)
            print(f"🔄 已恢复文件: {rel_path}")
            restored_count += 1
        else:
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                    print(f"🗑️ 已清理当时未存在的文件: {rel_path}")
                    restored_count += 1
                except Exception:
                    pass

    print(f"🎉 成功完成配置回滚！共恢复 {restored_count} 项配置文件。")
    return True


def check_and_install_dependencies(python_exe: str, auto_install: bool = False) -> bool:
    """检查并可选安装 Python 依赖"""
    missing_deps: List[Tuple[str, str]] = []

    for mod, pkg in REQUIRED_DEPENDENCIES:
        cmd = [python_exe, "-c", f"import {mod}"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode != 0:
                missing_deps.append((mod, pkg))
        except Exception:
            missing_deps.append((mod, pkg))

    if not missing_deps:
        print("✅ 核心运行时依赖全部就绪 (fastmcp, filelock, yaml, pytest)")
        return True

    missing_pkgs = [pkg for _, pkg in missing_deps]
    print(f"⚠️ 发现缺失依赖库: {', '.join(missing_pkgs)}")

    if auto_install:
        print(f"📦 正在使用 '{python_exe}' 自动安装缺失依赖...")
        cmd = [python_exe, "-m", "pip", "install"] + missing_pkgs
        try:
            res = subprocess.run(cmd, timeout=120)
            if res.returncode == 0:
                print("✅ 依赖自动安装完成！")
                return True
            else:
                print("❌ pip 安装依赖失败，请手动执行安装。", file=sys.stderr)
                return False
        except Exception as e:
            print(f"❌ 安装命令执行异常: {e}", file=sys.stderr)
            return False
    else:
        print(f"💡 建议在终端运行: \"{python_exe}\" -m pip install {' '.join(missing_pkgs)}")
        return False


def run_smoke_test(plugin_dir: str, python_exe: str) -> bool:
    """执行轻量冒烟自检：验证 MCP Server 可执行与导入有效性"""
    server_script = os.path.join(plugin_dir, "server", "server.py")
    if not os.path.isfile(server_script):
        print(f"❌ 冒烟测试失败: Server 脚本不存在: {server_script}", file=sys.stderr)
        return False

    cmd = [python_exe, "-c", "import sys; print('PYTHON_READY')"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and "PYTHON_READY" in res.stdout:
            print("✅ 运行环境与解释器冒烟自检通过")
            return True
        else:
            print(f"❌ 解释器自检异常: {res.stderr}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"❌ 冒烟测试执行失败: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Quench Dev Orchestrator (quorch) 跨平台安装配置引导脚手架"
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="仅执行安装前 Pre-flight 检查（句柄占用、路径长度与快照备份）",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="从最近一次快照备份 (.agents/.quench_path_backup.json) 一键恢复配置",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="检查当前运行环境与依赖就绪状态，不修改任何文件",
    )
    parser.add_argument(
        "--no-deps",
        action="store_true",
        help="跳过自动安装缺失依赖库",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="安装完成后直接为指定项目根目录执行初始化接入",
    )
    parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="输出全局注册指引 (~/.gemini/config/)",
    )
    parser.add_argument(
        "--ide",
        choices=["antigravity", "cursor", "all"],
        default="antigravity",
        help="指定项目接入的 IDE 环境 (antigravity | cursor | all，默认 antigravity)",
    )
    parser.add_argument(
        "--cursor",
        action="store_true",
        help="快捷选项：等同于 --ide cursor",
    )
    parser.add_argument(
        "--install-git-hook",
        action="store_true",
        help="自动将 Quench Git Pre-commit Guard 部署至目标项目的 .git/hooks/pre-commit",
    )

    args = parser.parse_args()

    repo_root = get_repo_root()
    plugin_dir = get_plugin_dir(repo_root)
    backup_path = get_backup_path(repo_root)
    python_exe = detect_python_executable(repo_root)

    print("=" * 65)
    print("🚀 Quench Dev Orchestrator (quorch) 安装引导中心")
    print("=" * 65)
    print(f"• 代码仓库根目录: {repo_root}")
    print(f"• 插件源码目录:   {plugin_dir}")
    print(f"• 探测 Python 路径: {python_exe}")
    print("-" * 65)

    # 1. 模式：回滚
    if args.rollback:
        print("🔄 正在执行配置快照回滚...")
        success = rollback_configuration(plugin_dir, backup_path)
        return 0 if success else 1

    # 2. 模式：仅 Pre-flight 检查
    if args.preflight:
        print("🩺 正在执行 Pre-flight 安全预检...")
        passed, msgs = run_preflight(plugin_dir, backup_path)
        for msg in msgs:
            print(f"  {msg}")
        print("-" * 65)
        if passed:
            print("🎉 Pre-flight 预检完全通过！可安全进行后续安装或目录更名。")
            return 0
        else:
            print("❌ Pre-flight 预检发现阻断问题，请解决后重试。", file=sys.stderr)
            return 1

    # 3. 模式：仅检查环境
    if args.check:
        print("🔍 正在检查运行环境与依赖...")
        deps_ok = check_and_install_dependencies(python_exe, auto_install=False)
        return 0 if deps_ok else 1

    # 4. 默认全量安装流程
    print("📋 [步骤 1/4] 执行 Pre-flight 预检与配置快照备份...")
    passed, msgs = run_preflight(plugin_dir, backup_path)
    for msg in msgs:
        print(f"  {msg}")
    if not passed:
        print("❌ Pre-flight 预检失败，安装终止。请解除句柄占用后重试。", file=sys.stderr)
        return 1

    print("\n📦 [步骤 2/4] 检查核心运行依赖...")
    check_and_install_dependencies(python_exe, auto_install=not args.no_deps)

    print("\n📝 [步骤 3/4] 根据模板动态渲染配置文件...")
    try:
        mcp_path, hooks_path = render_configs(plugin_dir, python_exe)
        print(f"  ✅ 已生成 MCP 配置:   {mcp_path}")
        print(f"  ✅ 已生成 Hooks 配置: {hooks_path}")
    except Exception as e:
        print(f"❌ 配置文件渲染失败: {e}", file=sys.stderr)
        return 1

    print("\n🔬 [步骤 4/4] 执行冒烟自检...")
    smoke_ok = run_smoke_test(plugin_dir, python_exe)

    print("-" * 65)
    if smoke_ok:
        print("🎉 恭喜！Quench Dev Orchestrator 插件已在当前环境成功就绪！")
        if args.global_install:
            home = os.path.expanduser("~")
            global_config = os.path.join(home, ".gemini", "config")
            print(f"\n💡 全局注册提示：若希望在全局使用，可将插件链接注入 {global_config}。")

        if args.project:
            init_script = os.path.join(plugin_dir, "scripts", "init_project.py")
            effective_ide = "cursor" if args.cursor else args.ide
            print(f"\n🚀 正在为目标项目 [{args.project}] 执行自动接入 (IDE: {effective_ide})...")
            cmd = [python_exe, init_script, args.project, "--force", "--ide", effective_ide]
            if args.install_git_hook:
                cmd.append("--install-git-hook")
            subprocess.run(cmd)
        else:
            print("\n💡 下一步：在任何项目中运行以下命令即可完成接入：")
            init_script = os.path.join(plugin_dir, "scripts", "init_project.py")
            print(f'   python "{init_script}" <你的项目根路径> [--ide cursor|antigravity|all] [--install-git-hook]')
        print("=" * 65)
        return 0
    else:
        print("⚠️ 安装完成但冒烟自检未全部通过，请检查上述日志。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
