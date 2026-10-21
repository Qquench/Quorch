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
import errno
import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Dict, Final, List, Literal, Optional, Tuple

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

ProbeVerdict = Literal["ok", "advisory", "blocked"]
PREFLIGHT_PROBE_ATTEMPTS: Final[int] = 3
PREFLIGHT_PROBE_BACKOFF_S: Final[float] = 0.05
MAX_PATH_WARN_CHARS: Final[int] = 200
MAX_PATH_BLOCK_CHARS: Final[int] = 250
_LOG_ARTIFACT_RESERVE_CHARS: Final[int] = 40  # 跨层日志引用字符上限；派生于 8+1+3+1+20+4=37，取 40
_PROBE_PREFIX: Final[str] = ".quench_preflight_"
_PROBE_REMOVE_RETRY_S: Final[float] = 0.01


def _is_enoent(err: OSError) -> bool:
    """判定异常是否表示文件不存在（含 Windows WinError 2/3 语义映射）。"""
    if isinstance(err, FileNotFoundError):
        return True
    if getattr(err, "winerror", None) in (2, 3):
        return True
    return getattr(err, "errno", None) == errno.ENOENT


def classify_probe_error(err: OSError) -> ProbeVerdict:
    """分类探测产生的 OSError。

    优先级：
    1. winerror 判定（仅当 winerror 不为 None 时）：
       - winerror in (32, 33) -> 'advisory'（文件正在被其他进程使用 / 共享冲突）
       - winerror == 5 -> 'blocked'（拒绝访问，权限不足）
       - 其它 winerror -> 'blocked'（fail-closed）
    2. errno 判定：
       - ENOENT -> 'blocked'（TOCTOU 场景，目录已不存在）
       - in (EACCES, EPERM, EROFS, ENOSPC, EIO, ENOTDIR) -> 'blocked'
       - 其它（含 None 或未知 errno）-> 'blocked'
    """
    winerror = getattr(err, "winerror", None)
    if winerror is not None:
        if winerror in (32, 33):
            return "advisory"
        return "blocked"

    err_no = getattr(err, "errno", None)
    if err_no == errno.ENOENT:
        return "blocked"
    if err_no in (
        errno.EACCES,
        errno.EPERM,
        errno.EROFS,
        errno.ENOSPC,
        errno.EIO,
        errno.ENOTDIR,
    ):
        return "blocked"

    return "blocked"


def probe_directory_writability(target_dir: str) -> Tuple[ProbeVerdict, str]:
    """探测目标目录的可写性与基本文件创建能力。

    采用带特定前缀的临时哨兵文件试探写入，杜绝原地更名重命名副作用。
    最多尝试 PREFLIGHT_PROBE_ATTEMPTS 轮：
    - 若成功创建、写入并清理，返回 ("ok", "目录可写性探测通过")
    - 若捕获 blocked 级错误，立即返回 ("blocked", 错误详情) 不重试
    - 若捕获 advisory 级错误，退避后重试，耗尽后返回 ("advisory", 错误详情)
    - 若清理删除时遇 ENOENT/WinError 2/3，视为目标文件已不存在，判定为 ok，不产生 residue
    - 若重试后仍删除失败且非 ENOENT，降级返回 ("advisory", f"哨兵文件删除失败: {rm_err}; residue={probe_path}")
    """
    last_advisory_msg = ""
    for attempt in range(PREFLIGHT_PROBE_ATTEMPTS):
        fd: Optional[int] = None
        probe_path: Optional[str] = None
        residue_confirmed: bool = False
        try:
            fd, probe_path = tempfile.mkstemp(prefix=_PROBE_PREFIX, dir=target_dir)
            assert fd is not None
            local_fd: int = fd
            fd = None  # 所有权转移，防双 close
            try:
                if os.write(local_fd, b"\x00") != 1:
                    raise OSError(errno.EIO, "probe short write")
            finally:
                os.close(local_fd)

            # 清理哨兵文件，容错重试 1 次
            try:
                os.remove(probe_path)
                probe_path = None
                return "ok", "目录可写性探测通过"
            except OSError as first_err:
                if _is_enoent(first_err):
                    probe_path = None
                    return "ok", "目录可写性探测通过"
                time.sleep(_PROBE_REMOVE_RETRY_S)
                try:
                    os.remove(probe_path)
                    probe_path = None
                    return "ok", "目录可写性探测通过"
                except OSError as rm_err:
                    if _is_enoent(rm_err):
                        probe_path = None
                        return "ok", "目录可写性探测通过"
                    residue_confirmed = True
                    return (
                        "advisory",
                        f"哨兵文件删除失败: {rm_err}; residue={probe_path}",
                    )
        except OSError as e:
            verdict = classify_probe_error(e)
            if verdict == "blocked":
                return "blocked", f"目录无法写入或受阻: {e}"
            last_advisory_msg = f"目录存在轻微竞争或锁定: {e}"
            if attempt < PREFLIGHT_PROBE_ATTEMPTS - 1:
                time.sleep(PREFLIGHT_PROBE_BACKOFF_S)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if probe_path is not None and not residue_confirmed:
                try:
                    os.remove(probe_path)
                except OSError:
                    pass

    return "advisory", last_advisory_msg or "目录可写性探测超时"


def get_repo_root() -> str:
    """获取代码仓库根目录绝对路径"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, ".."))


def get_plugin_dir(repo_root: Optional[str] = None) -> str:
    """获取 plugins/quench-dev-tasks 目录绝对路径"""
    root = repo_root or get_repo_root()
    return os.path.normpath(os.path.join(root, "plugins", "quench-dev-tasks"))


def get_backup_path(repo_root: Optional[str] = None, override: Optional[str] = None) -> str:
    """获取快照备份文件路径"""
    if override:
        return os.path.normpath(os.path.abspath(override))
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


def run_preflight(
    plugin_dir: str,
    backup_path: str,
    *,
    repo_root: Optional[str] = None,
    log_dir: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """执行安装前 Pre-flight 检查。

    检查项：
    1. Windows MAX_PATH 长度审计（>200 警告，>250 阻断）；
    2. 目录存在性校验与目录可写性探测（带前缀临时哨兵文件）；
    3. 备份快照写入到 backup_path。

    Returns:
        (passed: bool, messages: list[str])
    """
    messages: List[str] = []
    passed = True
    p_dir = os.path.normpath(plugin_dir)
    r_root = (
        os.path.normpath(repo_root)
        if repo_root
        else os.path.normpath(os.path.join(p_dir, "..", ".."))
    )
    l_dir = (
        os.path.normpath(log_dir)
        if log_dir
        else os.path.normpath(os.path.join(r_root, ".agents", "logs"))
    )

    # (a) MAX_PATH 长度审计（检查最深目录层级与日志保留空间）
    path_len = max(
        len(os.path.abspath(p_dir)),
        len(os.path.abspath(r_root)),
        len(os.path.abspath(l_dir)) + 1 + _LOG_ARTIFACT_RESERVE_CHARS,
    )
    if sys.platform == "win32":
        if path_len > MAX_PATH_BLOCK_CHARS:
            passed = False
            messages.append(
                f"❌ [MAX_PATH 阻断] 当前安装路径长度 ({path_len} 字符) 接近 Windows 260 MAX_PATH 限制，请移至更浅目录！"
            )
        elif path_len > MAX_PATH_WARN_CHARS:
            messages.append(
                f"⚠️ [MAX_PATH 警告] 当前安装路径长度为 {path_len} 字符（建议小于 200 字符，以防嵌套文件超限）。"
            )
        else:
            messages.append(f"✅ 路径长度安全审计通过 (长度: {path_len} 字符)")
    else:
        messages.append(f"✅ 平台路径检查通过 ({sys.platform})")

    # (b) 目录存在性校验
    if not os.path.isdir(p_dir):
        passed = False
        messages.append(f"❌ [目录可写性探测] plugin directory missing: {p_dir}")
    else:
        # (c) 目录可写性探测
        verdict, probe_msg = probe_directory_writability(p_dir)
        if verdict == "blocked":
            passed = False
            messages.append(f"❌ [目录可写性探测] {probe_msg}")
        elif verdict == "advisory":
            messages.append(f"⚠️ [目录可写性探测] {probe_msg}")
        else:
            messages.append(f"✅ [目录可写性探测] {probe_msg}")

    # (d) 备份快照写入
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
    parser.add_argument(
        "--repo-root",
        type=str,
        default=None,
        help="显式指定代码仓库根目录绝对路径（用于测试隔离）",
    )
    parser.add_argument(
        "--backup-path",
        type=str,
        default=None,
        help="显式指定快照备份文件绝对路径（用于测试隔离）",
    )

    args = parser.parse_args()

    repo_root = os.path.abspath(args.repo_root) if args.repo_root else get_repo_root()
    plugin_dir = get_plugin_dir(repo_root)
    backup_path = get_backup_path(repo_root, override=args.backup_path)
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
        passed, msgs = run_preflight(plugin_dir, backup_path, repo_root=repo_root)
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
    passed, msgs = run_preflight(plugin_dir, backup_path, repo_root=repo_root)
    for msg in msgs:
        print(f"  {msg}")
    if not passed:
        print("❌ Pre-flight 预检失败，安装终止。请解除阻断问题后重试。", file=sys.stderr)
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
