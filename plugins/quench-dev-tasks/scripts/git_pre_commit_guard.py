#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
"""Quench Git Pre-commit Guard — Zero-dependency standalone pre-commit guard script.
Only uses Python standard library without third-party dependencies.
Acts as final physical defense before commit in tools without PreToolUse hooks
(such as Cursor, Windsurf, Claude Code, bare Git CLI) to block code changes outside
the active task's affected files whitelist.

[中文说明] Quench Git Pre-commit Guard — 零依赖独立守卫脚本。
仅使用 Python 标准库，无任何第三方依赖。
在不支持 PreToolUse Hook 的开发工具（如 Cursor、Windsurf、Claude Code、裸 Git CLI）中
作为提交前最后物理防线，阻断超出当前任务【涉及文件】范围的代码变更。
"""
from __future__ import annotations

import argparse
import enum
import fnmatch
import glob
import io
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final, List, Optional, Sequence, Tuple, Union

if sys.version_info >= (3, 7):
    try:
        for _stream in (sys.stdin, sys.stdout, sys.stderr):
            if isinstance(_stream, io.TextIOWrapper):
                _stream.reconfigure(encoding="utf-8")
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


class SchemaCheckOutcome(enum.Enum):
    SKIP = "skip"          # 变更集未命中：零子进程，<50ms
    PASS = "pass"          # rc == 0
    DRIFT = "drift"        # rc == 1 → 阻断
    UNVERIFIABLE = "unverifiable"  # rc == 2 / TimeoutExpired → 阻断（fail-closed）
    GUARD_ERROR = "guard_error"    # 仅变更集获取失败 → fail-open


SCHEMA_TRIGGER_PATHS: Final[frozenset[str]] = frozenset({
    "plugins/quench-dev-tasks/server/server.py",
    "plugins/quench-dev-tasks/server/tool_surface_constants.py",
    "scripts/export_ide_schemas.py",
    "docs/architecture/ide_tool_schemas.json",
})


def should_run_schema_check(changed_paths: Sequence[str]) -> bool:
    """Determine if any of the changed paths intersect with SCHEMA_TRIGGER_PATHS."""
    if not changed_paths:
        return False
    normalized_triggers = {p.replace("\\", "/").strip().lstrip("./") for p in SCHEMA_TRIGGER_PATHS}
    for p in changed_paths:
        norm = p.replace("\\", "/").strip().lstrip("./")
        if norm in normalized_triggers:
            return True
    return False


def evaluate_schema_check(
    changed_paths: Optional[Sequence[str]], *, repo_root: Path
) -> SchemaCheckOutcome:
    """Evaluate IDE tool schemas drift gate. Fail-closed on drift/error, fail-open only on missing staged files."""
    if changed_paths is None:
        return SchemaCheckOutcome.GUARD_ERROR

    if not should_run_schema_check(changed_paths):
        return SchemaCheckOutcome.SKIP

    try:
        res = subprocess.run(
            [sys.executable, "scripts/export_ide_schemas.py", "--check"],
            cwd=str(repo_root),
            capture_output=True,
            timeout=30,
        )
        if res.returncode == 0:
            return SchemaCheckOutcome.PASS
        elif res.returncode == 1:
            return SchemaCheckOutcome.DRIFT
        else:
            return SchemaCheckOutcome.UNVERIFIABLE
    except subprocess.TimeoutExpired:
        return SchemaCheckOutcome.UNVERIFIABLE
    except Exception:
        return SchemaCheckOutcome.UNVERIFIABLE


class PromptSurfaceOutcome(enum.Enum):
    SKIP = "skip"          # 变更集未命中：零子进程，<50ms
    PASS = "pass"          # rc == 0
    VIOLATION = "violation" # rc == 1 → 阻断
    UNVERIFIABLE = "unverifiable"  # rc == 2 / TimeoutExpired → 阻断（fail-closed）
    GUARD_ERROR = "guard_error"    # 仅变更集获取失败 → fail-open


QUENCH_CORE_STRONG_ANCHORS: Final[Tuple[str, ...]] = (
    # 强锚点 = 不随插件分发、仅核心宿主拥有的 CI 脚本与小制品。
    # 依据 docs/architecture/README.md §5：scripts/* 属客户端宿主脚本，
    # 不属于 plugins/quench-dev-tasks/ 分发单元。
    "scripts/check_prompt_surface.py",
    "scripts/check_test_tiering_invariants.py",
    "scripts/check_test_duration_baselines.py",
    "docs/architecture/ide_tool_schemas.json",
)


def is_quorch_core_repo(repo_root: Union[Path, str]) -> bool:
    """Host classification via STRONG anchors (not vendor-distributed).

    Returns True iff at least one strong anchor exists under repo_root.
    Vendored-plugin downstream repos (which contain plugins/quench-dev-tasks/scripts/
    git_pre_commit_guard.py but none of the strong anchors) correctly classify as
    downstream -> transparent SKIP, eliminating the ModuleNotFoundError/UNVERIFIABLE
    false-positive that blocked all .md commits.

    Security trade-off (explicit): all strong anchors absent => False (downstream).
    This is intentionally fail-open for the gate, accepted because:
      (a) strong anchors are client-side host CI artifacts NOT distributed with the plugin;
      (b) any attempt to fake downstream by deleting strong anchors must itself modify
          out-of-whitelist files, intercepted upstream by file_scope_guard (Tier-1) and
          reconcile_workspace_against_whitelist (§3.2).
    """
    root = Path(repo_root)
    return any((root / anchor).is_file() for anchor in QUENCH_CORE_STRONG_ANCHORS)


PROMPT_SURFACE_TRIGGER_PATHS: Final[frozenset[str]] = frozenset({
    "plugins/quench-dev-tasks/server/server.py",
    "plugins/quench-dev-tasks/server/tool_surface_constants.py",
    "scripts/check_prompt_surface.py",
    "scripts/export_ide_schemas.py",
    "docs/architecture/ide_tool_schemas.json",
    "CHANGELOG.md",
    "README.md",
    "README_zh.md",
    "docs/configuration.md",
    "dev_tasks_mcp_specification.md",
    "docs/architecture/README.md",
    "plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md",
    "plugins/quench-dev-tasks/rules/dev-tasks-discipline.md",
    "docs/ci_incident_tracker_and_compatibility_guide.md",
})


def should_run_prompt_surface_check(changed_paths: Sequence[str]) -> bool:
    """Determine if any of the changed paths intersect with PROMPT_SURFACE_TRIGGER_PATHS or are markdown files."""
    if not changed_paths:
        return False
    normalized_triggers = {p.replace("\\", "/").strip().lstrip("./") for p in PROMPT_SURFACE_TRIGGER_PATHS}
    for p in changed_paths:
        norm = p.replace("\\", "/").strip().lstrip("./")
        if norm.endswith(".md") or norm in normalized_triggers:
            return True
    return False


def evaluate_prompt_surface_check(
    changed_paths: Optional[Sequence[str]], *, repo_root: Path
) -> PromptSurfaceOutcome:
    """Evaluate Prompt-Surface contract gate (P1~P5). Fail-closed on violation/error."""
    if not is_quorch_core_repo(repo_root):
        return PromptSurfaceOutcome.SKIP

    if changed_paths is None:
        return PromptSurfaceOutcome.GUARD_ERROR

    if not should_run_prompt_surface_check(changed_paths):
        return PromptSurfaceOutcome.SKIP

    checker_script = repo_root / "scripts" / "check_prompt_surface.py"
    if not checker_script.is_file():
        try:
            scripts_dir = repo_root / "scripts"
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            import importlib.util
            spec = importlib.util.find_spec("check_prompt_surface")
            if not spec or not spec.origin or str(repo_root) not in spec.origin:
                return PromptSurfaceOutcome.UNVERIFIABLE
            import check_prompt_surface
            rc = check_prompt_surface.main(["--check", "--workspace", str(repo_root)])
            if rc == 0:
                return PromptSurfaceOutcome.PASS
            elif rc == 1:
                return PromptSurfaceOutcome.VIOLATION
            else:
                return PromptSurfaceOutcome.UNVERIFIABLE
        except Exception:
            return PromptSurfaceOutcome.UNVERIFIABLE

    try:
        res = subprocess.run(
            [sys.executable, str(checker_script), "--check", "--workspace", str(repo_root)],
            cwd=str(repo_root),
            capture_output=True,
            timeout=30,
        )
        if res.returncode == 0:
            return PromptSurfaceOutcome.PASS
        elif res.returncode == 1:
            return PromptSurfaceOutcome.VIOLATION
        else:
            return PromptSurfaceOutcome.UNVERIFIABLE
    except subprocess.TimeoutExpired:
        return PromptSurfaceOutcome.UNVERIFIABLE
    except Exception:
        return PromptSurfaceOutcome.UNVERIFIABLE


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
            ["git", "-c", "core.quotePath=false", "diff", "--cached", "--name-only"],
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


def _parse_affected_files_block(section_lines: List[str]) -> List[str]:
    """Extract normalized affected file paths from a task section, ignoring outer fences."""
    allowed_files: List[str] = []
    in_fence_char: Optional[str] = None
    in_fence_len = 0
    found_heading = False
    in_affected_fence = False

    for line in section_lines:
        stripped_left = line.lstrip(" ")
        indent = len(line) - len(stripped_left)

        if indent <= 3 and (stripped_left.startswith("```") or stripped_left.startswith("~~~")):
            fence_char = stripped_left[0]
            flen = len(stripped_left) - len(stripped_left.lstrip(fence_char))
            if in_fence_char is None:
                in_fence_char = fence_char
                in_fence_len = flen
                if found_heading:
                    in_affected_fence = True
                continue
            elif in_fence_char == fence_char and flen >= in_fence_len:
                in_fence_char = None
                in_fence_len = 0
                if in_affected_fence:
                    break
                continue

        if in_affected_fence:
            item = line.strip()
            if not item:
                continue
            item = re.sub(r"^(?:[-*+]\s+)+", "", item).strip()
            item = re.sub(r"^\[(?:MODIFY|NEW|DELETE|RENAME)\]\s*", "", item, flags=re.IGNORECASE).strip()
            item = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", item).strip()
            for part in re.split(r"\s*(?:->|➔)\s*", item):
                cleaned = part.strip().strip("`").strip().replace("\\", "/")
                while cleaned.startswith("./"):
                    cleaned = cleaned[2:]
                if cleaned:
                    allowed_files.append(cleaned)
            continue

        if in_fence_char is not None:
            continue

        if re.match(r"^####\s+(?:【涉及文件】|\[Affected Files\]|【Affected Files】)\s*$", stripped_left, re.IGNORECASE):
            found_heading = True
        elif found_heading and stripped_left and not stripped_left.startswith("#"):
            # Allow non-empty non-fence content? No, reset if another section starts
            pass
        elif found_heading and stripped_left.startswith("####"):
            break

    return allowed_files


def find_active_task(dev_tasks_dir: str) -> Optional[Tuple[str, str, List[str]]]:
    """在 dev_tasks 目录中查找处于 🔨 执行中 的任务。

    返回: (task_id, task_title, allowed_files) 或 None
    直接基于标准库正则解析 Markdown 文件，不依赖 MCP Server 或第三方库。
    """
    if not os.path.isdir(dev_tasks_dir):
        return None

    md_files = sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True)
    header_re = re.compile(r"^###\s+(?:任务|Task)\s+([0-9a-zA-Z\._\-]+)\s+([^\n]+)$", re.IGNORECASE)

    for md_path in md_files:
        if os.path.basename(md_path).lower() == "readme.md":
            continue

        try:
            with open(md_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue

        # Fence-aware scan for ### 任务/Task headers
        in_fence_char: Optional[str] = None
        in_fence_len = 0
        lines = content.splitlines()
        active_info: Optional[Tuple[str, str]] = None
        section_lines: List[str] = []

        for line in lines:
            stripped_left = line.lstrip(" ")
            indent = len(line) - len(stripped_left)

            if indent <= 3 and (stripped_left.startswith("```") or stripped_left.startswith("~~~")):
                fence_char = stripped_left[0]
                flen = len(stripped_left) - len(stripped_left.lstrip(fence_char))
                if in_fence_char is None:
                    in_fence_char = fence_char
                    in_fence_len = flen
                elif in_fence_char == fence_char and flen >= in_fence_len:
                    in_fence_char = None
                    in_fence_len = 0
                if active_info is not None:
                    section_lines.append(line)
                continue

            if in_fence_char is not None:
                if active_info is not None:
                    section_lines.append(line)
                continue

            if stripped_left.startswith(">"):
                if active_info is not None:
                    section_lines.append(line)
                continue

            if stripped_left.startswith("###") and not stripped_left.startswith("####"):
                if active_info is not None:
                    return (active_info[0], active_info[1], _parse_affected_files_block(section_lines))

                m = header_re.match(stripped_left)
                if m:
                    task_id = m.group(1).strip()
                    rest = m.group(2).strip()
                    sep_match = re.match(r"^(.+?)\s*[—]\s*(.*)$", rest) or re.match(r"^(.+?)\s+-\s+(.*)$", rest)
                    if sep_match:
                        status_text = sep_match.group(1).strip()
                        task_title = sep_match.group(2).strip()
                    else:
                        status_text = rest
                        task_title = ""

                    status_lower = status_text.lower()
                    if (
                        "执行中" in status_text
                        or "🔨" in status_text
                        or "in progress" in status_lower
                        or "in-progress" in status_lower
                    ):
                        active_info = (task_id, task_title)
                        section_lines = []
                        continue

            if active_info is not None:
                section_lines.append(line)

        if active_info is not None:
            return (active_info[0], active_info[1], _parse_affected_files_block(section_lines))

    return None


def _match_anchored_glob(rel_path: str, pattern: str) -> bool:
    """Segment-aware anchored glob matching for pre-commit whitelist patterns."""
    path_parts = [p for p in rel_path.replace("\\", "/").strip("/").split("/") if p]
    raw_pat_parts = [p for p in pattern.replace("\\", "/").strip("/").split("/") if p]
    if not raw_pat_parts:
        return not path_parts

    pat_parts: List[str] = []
    for part in raw_pat_parts:
        if part == "**" and pat_parts and pat_parts[-1] == "**":
            continue
        pat_parts.append(part)

    n_pat = len(pat_parts)
    n_path = len(path_parts)
    memo: dict[Tuple[int, int], bool] = {}

    def _dp(i: int, j: int) -> bool:
        state = (i, j)
        if state in memo:
            return memo[state]
        if i == n_pat:
            res = j == n_path
        elif pat_parts[i] == "**":
            res = _dp(i + 1, j) or (j < n_path and _dp(i, j + 1))
        else:
            res = (
                j < n_path
                and fnmatch.fnmatchcase(os.path.normcase(path_parts[j]), os.path.normcase(pat_parts[i]))
                and _dp(i + 1, j + 1)
            )
        memo[state] = res
        return res

    return _dp(0, 0)


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

    norm_exact: set[str] = set()
    glob_patterns: List[str] = []
    ws_norm = os.path.normpath(workspace_root).replace("\\", "/").rstrip("/") if workspace_root else ""

    for af in allowed_files:
        clean_af = af.replace("\\", "/").strip()
        while clean_af.startswith("./"):
            clean_af = clean_af[2:]
        if ws_norm and clean_af.lower().startswith(ws_norm.lower() + "/"):
            clean_af = clean_af[len(ws_norm) + 1:]
        clean_af = clean_af.lstrip("/")
        if not clean_af:
            continue
        if "*" in clean_af or "?" in clean_af:
            glob_patterns.append(clean_af)
        else:
            norm_exact.add(os.path.normcase(clean_af))

    for sf in staged_files:
        norm_sf = sf.replace("\\", "/").strip()
        while norm_sf.startswith("./"):
            norm_sf = norm_sf[2:]
        norm_sf = norm_sf.lstrip("/")

        # 1. 免管文件天然放行
        if is_file_unmanaged(norm_sf.lower()):
            continue

        # 2. 精确相对路径或锚定通配符比对（禁止 basename 与双向 endswith 绕过）
        matched = os.path.normcase(norm_sf) in norm_exact
        if not matched:
            for pat in glob_patterns:
                if _match_anchored_glob(norm_sf, pat):
                    matched = True
                    break

        if not matched:
            violations.append(sf)

    return violations


def _resolve_git_dir(project_root: str) -> Optional[str]:
    """Resolve .git directory for standard repos and git worktrees."""
    dot_git = os.path.join(project_root, ".git")
    if os.path.isdir(dot_git):
        return dot_git
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--git-dir"],
            cwd=project_root,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        ).decode("utf-8", errors="ignore").strip()
        if out:
            candidate = out if os.path.isabs(out) else os.path.normpath(os.path.join(project_root, out))
            if os.path.isdir(candidate):
                return candidate
    except Exception:
        pass
    if os.path.isfile(dot_git):
        try:
            with open(dot_git, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline().strip()
            if first_line.lower().startswith("gitdir:"):
                raw_dir = first_line.split(":", 1)[1].strip()
                candidate = raw_dir if os.path.isabs(raw_dir) else os.path.normpath(os.path.join(project_root, raw_dir))
                if os.path.isdir(candidate):
                    return candidate
        except Exception:
            pass
    return None


def install_hook(project_root: str) -> int:
    """一键安装 Pre-commit Guard 到目标项目的 .git/hooks/pre-commit。"""
    git_dir = _resolve_git_dir(project_root)
    if not git_dir:
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

    # 获取暂存区文件
    try:
        staged_files = get_staged_files(workspace_root)
    except Exception:
        staged_files = None

    # 执行 Schema 漂移硬门禁判定（独立硬门禁，不受 is_antigravity_environment 豁免）
    schema_outcome = evaluate_schema_check(staged_files, repo_root=Path(workspace_root))
    if schema_outcome == SchemaCheckOutcome.DRIFT:
        print("\n" + "=" * 65, file=sys.stderr)
        print("🛑 \033[91m[Quench Guard] Git Commit 物理拦截：IDE Tool Schema 快照与代码漂移！\033[0m", file=sys.stderr)
        print("=" * 65, file=sys.stderr)
        print("💡 解决指引: 请运行 `python scripts/export_ide_schemas.py --write` 更新快照，确认无误后暂存再提交。\n", file=sys.stderr)
        return 1
    elif schema_outcome == SchemaCheckOutcome.UNVERIFIABLE:
        print("\n" + "=" * 65, file=sys.stderr)
        print("🛑 \033[91m[Quench Guard] Git Commit 物理拦截：Schema 校验失败或超时（Fail-Closed 阻断）！\033[0m", file=sys.stderr)
        print("=" * 65, file=sys.stderr)
        return 1
    elif schema_outcome == SchemaCheckOutcome.GUARD_ERROR:
        print("⚠️ [Quench Guard] 无法获取暂存区文件，Schema 门禁降级放行（Fail-Open）。", file=sys.stderr)

    # 执行 Prompt-Surface 契约硬门禁判定（独立硬门禁，不受 is_antigravity_environment 豁免）
    prompt_surface_outcome = evaluate_prompt_surface_check(staged_files, repo_root=Path(workspace_root))
    if prompt_surface_outcome == PromptSurfaceOutcome.VIOLATION:
        print("\n" + "=" * 65, file=sys.stderr)
        print("🛑 \033[91m[Quench Guard] Git Commit 物理拦截：Prompt Surface 契约违规（P1~P5 门禁拦截）！\033[0m", file=sys.stderr)
        print("=" * 65, file=sys.stderr)
        print("💡 解决指引: 请运行 `python scripts/check_prompt_surface.py --check` 查看详细违规并修正。\n", file=sys.stderr)
        return 1
    elif prompt_surface_outcome == PromptSurfaceOutcome.UNVERIFIABLE:
        print("\n" + "=" * 65, file=sys.stderr)
        print("🛑 \033[91m[Quench Guard] Git Commit 物理拦截：Prompt Surface 门禁执行失败或超时（Fail-Closed 阻断）！\033[0m", file=sys.stderr)
        print("=" * 65, file=sys.stderr)
        return 1
    elif prompt_surface_outcome == PromptSurfaceOutcome.GUARD_ERROR:
        print("⚠️ [Quench Guard] 无法获取暂存区文件，Prompt Surface 门禁降级放行（Fail-Open）。", file=sys.stderr)

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
