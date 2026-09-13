#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Quench Git Pre-commit Guard — 零依赖独立守卫脚本。
仅使用 Python 标准库，无任何第三方依赖。
在不支持 PreToolUse Hook 的开发工具（如 Cursor、Windsurf、Claude Code、裸 Git CLI）中
作为提交前最后物理防线，阻断超出当前任务【涉及文件】范围的代码变更。
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 免管控文件后缀集合（仅文档、素材、数据等，不含高危清单如 package.json）
UNMANAGED_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".rst", ".adoc",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".drawio", ".puml", ".mermaid",
    ".sample", ".example", ".bak",
    ".log", ".csv", ".tsv", ".parquet",
}

# 免管控通用目录
UNMANAGED_DIRS = (
    "docs/", "doc/", "documentation/", "future_roadmap/",
    "roadmap/", "notes/", "manuals/", "sample_data/",
    "samples/", ".vscode/", ".idea/", ".github/", ".agents/",
)

# 免管控单文件
UNMANAGED_META_FILES = {
    "changelog.md", "readme.md", "license", "license.md", "license.txt",
}


def _extract_yaml_field(content: str, field: str) -> Optional[str]:
    """从 YAML 内容中正则提取单行标量字段值（避免依赖 PyYAML）。"""
    pattern = re.compile(
        rf"^\s*{re.escape(field)}\s*:\s*['\"]?([^'\"#\r\n]+)['\"]?\s*$",
        re.MULTILINE,
    )
    match = pattern.search(content)
    return match.group(1).strip() if match else None


def get_git_root(cwd: Optional[str] = None) -> Optional[str]:
    """通过 git rev-parse --show-toplevel 获取当前 Git 仓库根路径。"""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd or os.getcwd(),
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        ).decode("utf-8", errors="ignore").strip()
        if out and os.path.isdir(out):
            return os.path.normpath(out)
    except Exception:
        pass
    return None


def get_staged_files(cwd: Optional[str] = None) -> List[str]:
    """通过 git diff --cached --name-only 获取本次暂存（staged）文件相对路径列表。"""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only"],
            cwd=cwd or os.getcwd(),
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        ).decode("utf-8", errors="ignore")
        files = [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]
        return files
    except Exception:
        return []


def is_antigravity_environment(workspace_root: str) -> bool:
    """检测当前是否处于 Antigravity IDE 管控环境。

    若检测到 Antigravity IDE 标识，Pre-commit Guard 降级为 warning-only 模式，
    避免双重拦截干扰开发者体验。
    """
    if os.environ.get("GEMINI_CLI") or os.environ.get("ANTIGRAVITY_APP_DIR"):
        return True

    plugins_json = os.path.join(workspace_root, ".agents", "plugins.json")
    if os.path.isfile(plugins_json):
        try:
            with open(plugins_json, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if "quench-dev-tasks" in content:
                    return True
        except Exception:
            pass

    return False


def find_active_task(dev_tasks_dir: str) -> Optional[Tuple[str, str, List[str]]]:
    """在 dev_tasks 目录中查找处于 🔨 执行中 的任务。

    返回: (task_id, task_title, allowed_files) 或 None
    直接基于标准库正则解析 Markdown 文件，不依赖 MCP Server 或第三方库。
    """
    if not os.path.isdir(dev_tasks_dir):
        return None

    md_files = sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True)
    for md_path in md_files:
        if os.path.basename(md_path).lower() == "readme.md":
            continue

        try:
            with open(md_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        # 匹配任务条目：### 任务/Task <id> <状态> — <标题>
        task_blocks = re.split(r"(?=^###\s+(?:任务|Task)\s+)", content, flags=re.MULTILINE)
        for block in task_blocks:
            if not block.strip():
                continue

            header_match = re.search(
                r"^###\s+(?:任务|Task)\s+(\d+)\s+([^\n—\-]+)[—\-]\s*([^\n]+)",
                block,
                re.MULTILINE,
            )
            if not header_match:
                continue

            task_id = header_match.group(1).strip()
            status_text = header_match.group(2).strip()
            task_title = header_match.group(3).strip()

            if "执行中" in status_text or "🔨" in status_text:
                # 提取【涉及文件】
                allowed_files: List[str] = []
                files_match = re.search(r"####\s+【涉及文件】\s*```(.*?)```", block, re.DOTALL)
                if files_match:
                    raw_block = files_match.group(1).strip()
                    for line in raw_block.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        cleaned = re.sub(r"^\[(MODIFY|NEW|DELETE|RENAME)\]\s*", "", line).strip()
                        cleaned = cleaned.split("（")[0].split("(")[0].strip()
                        if cleaned:
                            allowed_files.append(cleaned.replace("\\", "/"))

                return (task_id, task_title, allowed_files)

    return None


def is_file_unmanaged(rel_path: str) -> bool:
    """判断文件是否属于免管的文档、素材或元数据。"""
    norm = rel_path.replace("\\", "/").lower()
    basename = os.path.basename(norm)
    _, ext = os.path.splitext(norm)

    if basename in UNMANAGED_META_FILES:
        return True

    if ext in UNMANAGED_EXTENSIONS:
        return True

    for u_dir in UNMANAGED_DIRS:
        if norm.startswith(u_dir) or f"/{u_dir}" in f"/{norm}":
            return True

    return False


def check_violations(
    staged_files: List[str], allowed_files: List[str], workspace_root: str
) -> List[str]:
    """校验是否有超出任务白名单的代码文件。返回违规文件列表。"""
    violations: List[str] = []

    # 规范化白名单集合
    norm_allowed = set()
    allowed_basenames = set()
    for af in allowed_files:
        clean_af = af.replace("\\", "/").strip().lower()
        norm_allowed.add(clean_af)
        allowed_basenames.add(os.path.basename(clean_af))

    for sf in staged_files:
        norm_sf = sf.replace("\\", "/").strip().lower()

        # 1. 免管文件天然放行
        if is_file_unmanaged(norm_sf):
            continue

        # 2. 比对白名单
        matched = False
        if norm_sf in norm_allowed:
            matched = True
        elif os.path.basename(norm_sf) in allowed_basenames:
            matched = True
        else:
            for af in norm_allowed:
                if fnmatch.fnmatch(norm_sf, af) or norm_sf.endswith(af) or af.endswith(norm_sf):
                    matched = True
                    break

        if not matched:
            violations.append(sf)

    return violations


def install_hook(project_root: str) -> int:
    """一键安装 Pre-commit Guard 到目标项目的 .git/hooks/pre-commit。"""
    git_dir = os.path.join(project_root, ".git")
    if not os.path.isdir(git_dir):
        print(f"❌ 错误: 目标路径不是有效的 Git 仓库根目录: {project_root}", file=sys.stderr)
        return 1

    hooks_dir = os.path.join(git_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    target_hook = os.path.join(hooks_dir, "pre-commit")

    current_script = os.path.abspath(__file__)

    hook_content = (
        "#!/usr/bin/env bash\n"
        "# Quench Git Pre-commit Guard Shim\n"
        "set -e\n"
        f"python3 \"{current_script}\" || python \"{current_script}\"\n"
    )

    if os.path.isfile(target_hook):
        try:
            with open(target_hook, "r", encoding="utf-8", errors="ignore") as f:
                existing = f.read()
            if "git_pre_commit_guard.py" in existing:
                print(f"ℹ️ Quench Pre-commit Guard 已经安装在: {target_hook}")
                return 0
            else:
                print(f"⚠️ 目标 pre-commit 钩子已存在其他内容: {target_hook}")
                print(f"请手动将以下调用追加到该文件末尾:\n\npython \"{current_script}\"\n")
                return 0
        except Exception as e:
            print(f"❌ 读取已有 hook 失败: {e}", file=sys.stderr)
            return 1

    try:
        with open(target_hook, "w", encoding="utf-8", newline="\n") as f:
            f.write(hook_content)
        # 赋予可执行权限（类 Unix 系统）
        try:
            os.chmod(target_hook, 0o755)
        except Exception:
            pass
        print(f"✅ 成功安装 Quench Pre-commit Guard 至: {target_hook}")
        return 0
    except Exception as e:
        print(f"❌ 写入 hook 失败: {e}", file=sys.stderr)
        return 1


def main() -> int:
    """入口函数。返回 0 允许提交，返回 1 阻断提交。"""
    parser = argparse.ArgumentParser(
        description="Quench Git Pre-commit Guard — 零依赖独立守卫脚本"
    )
    parser.add_argument(
        "--install",
        nargs="?",
        const=".",
        help="安装 hook 到指定项目（默认为当前目录）",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="指定工作区路径（默认自动通过 git 定位）",
    )
    args = parser.parse_args()

    if args.install:
        target_proj = os.path.abspath(args.install)
        return install_hook(target_proj)

    workspace_root = args.workspace
    if not workspace_root:
        workspace_root = get_git_root()

    if not workspace_root or not os.path.isdir(workspace_root):
        # 非 Git 仓库或无法定位，放行
        return 0

    # 检查是否为 Quench 纳管项目
    stack_yaml = os.path.join(workspace_root, ".agents", "quench_stack.yaml")
    if not os.path.isfile(stack_yaml):
        # 非 Quench 项目，静默放行
        return 0

    # 获取 dev_tasks 目录
    dev_tasks_dir = os.path.join(workspace_root, "docs", "dev_tasks")
    try:
        with open(stack_yaml, "r", encoding="utf-8", errors="ignore") as f:
            yaml_content = f.read()
        configured_dir = _extract_yaml_field(yaml_content, "dev_tasks_dir")
        if configured_dir:
            if os.path.isabs(configured_dir):
                dev_tasks_dir = configured_dir
            else:
                dev_tasks_dir = os.path.join(workspace_root, configured_dir)
    except Exception:
        pass

    # 查找执行中任务
    active_task = find_active_task(dev_tasks_dir)
    if not active_task:
        print("ℹ️ [Quench Guard] 当前无处于【🔨 执行中】的任务，提交流程正常放行。")
        return 0

    task_id, task_title, allowed_files = active_task

    # 检查是否处于 Antigravity IDE 环境
    if is_antigravity_environment(workspace_root):
        print(
            "⚠️ [Quench Guard] 检测到 Antigravity IDE PreToolUse Hook 已接管管控，"
            "Pre-commit Guard 降级为 warning-only 放行。",
            file=sys.stderr,
        )
        return 0

    # 获取暂存区文件
    staged_files = get_staged_files(workspace_root)
    if not staged_files:
        return 0

    # 校验越界文件
    violations = check_violations(staged_files, allowed_files, workspace_root)
    if violations:
        print("\n" + "=" * 65, file=sys.stderr)
        print("🛑 \033[91m[Quench Guard] Git Commit 物理拦截：发现越界修改文件！\033[0m", file=sys.stderr)
        print("=" * 65, file=sys.stderr)
        print(f"📌 当前执行中任务: Task {task_id} — {task_title}", file=sys.stderr)
        print("📋 规划涉及文件白名单:", file=sys.stderr)
        for af in allowed_files:
            print(f"   • {af}", file=sys.stderr)
        print("\n⚠️ 试图提交但未在任务白名单中的代码文件:", file=sys.stderr)
        for vf in violations:
            print(f"   ❌ \033[91m{vf}\033[0m", file=sys.stderr)
        print("\n💡 解决指引:", file=sys.stderr)
        print(f"   1. 若确需修改上述文件，请先在任务单中将文件补充至 Task {task_id} 的【涉及文件】清单中；", file=sys.stderr)
        print("   2. 若属误改或临时调试产物，请使用 git reset HEAD <file> 移出暂存区后再提交；", file=sys.stderr)
        print("   3. 应急强行提交（不推荐）：git commit -n / --no-verify（将跳过所有 pre-commit 检查）。\n", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
