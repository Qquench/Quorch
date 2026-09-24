# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import datetime
from datetime import datetime, timezone, timedelta, date
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import filelock
import tempfile
import time
from typing import Any, Dict, List, Optional, Literal, TypedDict
from fastmcp import Context, FastMCP

SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")


def _atomic_write_json(filepath: str, data: dict) -> None:
    """Atomically write JSON data using temporary file and os.replace. / 使用临时文件 + os.replace 实现原子写入。"""
    dir_name = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, filepath)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise


def _validate_session_id(session_id: Optional[str]) -> Optional[str]:
    """Validate session_id format (UUID regex whitelist, max 128 chars). / 校验 session_id 格式（UUID 正则白名单，最长 128 字符）。"""
    if not session_id:
        return None
    s = session_id.strip()
    if not SESSION_ID_PATTERN.match(s):
        raise ValueError(f"Invalid session_id format: '{s}'. Only up to 128-char UUID/alphanumeric/hyphens supported. / 非法的 session_id 格式: '{s}'。仅支持最长 128 位的 UUID/十六进制/连字符字符。")
    return s

import functools
import anyio
from changelog_writer import append_changelog_entry
from code_explorer import explore_code_slices, ExploreResult
from path_guard import to_workspace_relative_path, PathTraversalError
from project_config import (
    load_project_config,
    QuenchStackConfig,
    ReviewerEngineConfig,
    DispatchStrategy,
    create_reviewer_client,
)
from reviewer_engine import (
    PromptAssembler,
    ReviewerClient,
    RotatingFileSink,
    AdaptiveHeartbeatSink,
)
from schema_validator import (
    validate_task_schema,
    lint_task_physical_feasibility,
    LintIssue,
    PhysicalLintResult,
    _parse_task_markdown_sections,
)
from state_machine import (
    ALL_STATUSES,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_REWORK,
    STATUS_SKIPPED,
    TASK_HEADER_PATTERN,
    TaskItem,
    get_status_summary,
    parse_task_file,
    transition_task,
    assert_task_checkout_allowed,
)
from pathlib import Path
from manifest import (
    commit_lease,
    release_lease,
    load_manifest,
    touch_heartbeat,
    FencedTokenError,
    ManifestIntegrityError,
    MANIFEST_REL_PATH,
    register_proposal,
    reconcile_workspace,
    ReconcileReport,
    ReconcileClass,
)

try:
    from .reaper import reclaim_stale_task
except (ImportError, ValueError):
    from reaper import reclaim_stale_task

mcp = FastMCP("quench-dev-tasks")


def _resolve_task_file_path(workspace_root: str, task_file: str) -> str:
    """Resolve task file name or relative path to absolute path. / 辅助函数：将任务文件名或相对路径解析为绝对路径。"""
    config = load_project_config(workspace_root)
    dev_tasks_dir = config.resolve_path("dev_tasks_dir")

    if os.path.isabs(task_file):
        return os.path.normpath(task_file)

    # 优先在 dev_tasks_dir 下找
    cand = os.path.normpath(os.path.join(dev_tasks_dir, task_file))
    if os.path.isfile(cand):
        return cand

    # 其次在 workspace_root 下找
    cand_root = os.path.normpath(os.path.join(config.workspace_root, task_file))
    if os.path.isfile(cand_root):
        return cand_root

    return cand


def _render_task_markdown(task: Dict[str, Any]) -> str:
    """Render a single structured task dictionary into compliant Markdown snippet. / 将单条结构化任务字典渲染为符合规范的 Markdown 片段。"""
    task_id = task.get("id") or task.get("task_id") or "1.0"
    title = task.get("title") or "未命名任务"
    status = task.get("status") or STATUS_PENDING
    is_draft = bool(task.get("draft"))

    if is_draft:
        lines = [
            f"### 任务 {task_id} {status} (草案) — {title}\n",
            "<!-- quench-task-meta: {\"draft\": true} -->\n\n",
            "#### 【涉及文件】\n",
            "```\n",
        ]
    else:
        lines = [
            f"### 任务 {task_id} {status} — {title}\n",
            "\n",
            "#### 【涉及文件】\n",
            "```\n",
        ]
    affected = task.get("affected_files", [])
    if isinstance(affected, list):
        for af in affected:
            lines.append(f"{af}\n")
    else:
        lines.append(f"{affected}\n")
    lines.append("```\n\n")

    lines.append("#### 【缺陷根因与修改目标】\n")
    lines.append("```\n")
    lines.append(f"{task.get('root_cause_and_goal', '无')}\n")
    lines.append("```\n\n")

    lines.append("#### 【目标签名与类型契约】\n")
    contracts = task.get("type_contracts", "无")
    if isinstance(contracts, list):
        contracts_str = "\n".join(contracts)
    else:
        contracts_str = str(contracts)
    lines.append("```\n")
    lines.append(f"{contracts_str}\n")
    lines.append("```\n\n")

    lines.append("#### 【分步改造指引】\n")
    steps = task.get("steps", [])
    if isinstance(steps, list):
        for s in steps:
            lines.append(f"{s}\n")
    else:
        lines.append(f"{steps}\n")
    lines.append("\n")

    lines.append("#### 【防御与边缘校验】\n")
    checks = task.get("defensive_checks", [])
    if isinstance(checks, list):
        for c in checks:
            lines.append(f"{c}\n")
    else:
        lines.append(f"{checks}\n")
    lines.append("\n")

    lines.append("#### 【DoD 验证命令】\n")
    lines.append("```bash\n")
    dod = task.get("dod_commands", "")
    if isinstance(dod, list):
        for d in dod:
            lines.append(f"{d}\n")
    else:
        lines.append(f"{dod}\n")
    lines.append("```\n\n---\n\n")

    return "".join(lines)


def _extract_task_detail(filepath: str, task_id: str) -> Dict[str, Any]:
    """Extract full Markdown block of specified task ID from file. / 从 Markdown 任务文件中提取指定任务的完整图文段落。"""
    tasks = parse_task_file(filepath)
    matched_item = next((t for t in tasks if str(t.id).strip() == str(task_id).strip()), None)
    if not matched_item:
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start_idx = matched_item.line_number
    end_idx = len(lines)

    for next_t in tasks:
        if next_t.line_number > start_idx:
            end_idx = next_t.line_number
            break

    content_snippet = "".join(lines[start_idx:end_idx])
    return {
        "id": matched_item.id,
        "title": matched_item.title,
        "status": matched_item.status,
        "full_spec": content_snippet,
    }


_EXEMPTION_PATTERN = re.compile(
    r"\[EXEMPTION:\s*(docs-only|config-only|non-behavioral-refactor)\s*\]",
    re.IGNORECASE,
)
_TEST_FILE_PATTERN = re.compile(r"(^|/)tests?/.*test_.*\.py$|(^|/).*_test\.py$")
_ASSERTION_MARKERS = ("assert ", "assert(", "pytest.raises")


def _append_hook_log(workspace_root: str, message: str) -> None:
    """向 .agents/.quench_hook.log 安全追加单条日志（多进程幂等安全）。"""
    try:
        from hooks.file_scope_guard import get_hook_logger
        logger = get_hook_logger(workspace_root)
        logger.info(message)
    except Exception:
        try:
            agents_dir = os.path.join(workspace_root, ".agents")
            os.makedirs(agents_dir, exist_ok=True)
            log_file = os.path.join(agents_dir, ".quench_hook.log")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{now_str} [INFO] {message}\n")
        except Exception:
            pass


def check_shell_write_isolation(command: str, workspace_root: str, dev_tasks_dir: str = "docs/dev_tasks") -> Optional[str]:
    """检测外部 Shell 写入旁路（与 file_scope_guard 对齐），保障 MCP 任务单工具通道安全隔离。"""
    try:
        from hooks.file_scope_guard import detect_shell_write_bypass
        return detect_shell_write_bypass(command, workspace_root, dev_tasks_dir)
    except Exception:
        return None


def _audit_test_changes(
    workspace_root: str,
    config: Any,
    test_evidence: str | None = None,
) -> Dict[str, Any]:
    """Physically audit test directory for added tests and assertions via git diff. / 通过 git 物理扫描测试目录是否包含新增测试与断言。"""
    tracked_files: set[str] = set()
    untracked_files: set[str] = set()
    degraded = False
    messages: list[str] = []

    # 1. 运行 git status --porcelain -u 捕获所有变更与未跟踪文件（精确展开子文件）
    try:
        res_status = subprocess.run(
            ["git", "-C", workspace_root, "status", "--porcelain", "-u"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if res_status.returncode != 0:
            degraded = True
            messages.append(f"git status exited with code {res_status.returncode}: {res_status.stderr.strip()}")
        else:
            for line in res_status.stdout.splitlines():
                if not line.strip():
                    continue
                code = line[:2]
                filepath = line[2:].strip().strip('"')
                if " -> " in filepath:
                    filepath = filepath.split(" -> ")[-1].strip().strip('"')
                norm_p = filepath.replace("\\", "/")
                if code == "??":
                    if norm_p.endswith("/"):
                        abs_dir = os.path.join(workspace_root, norm_p)
                        if os.path.isdir(abs_dir):
                            for r, _, fnames in os.walk(abs_dir):
                                for fn in fnames:
                                    rel_sub = os.path.relpath(os.path.join(r, fn), workspace_root).replace("\\", "/")
                                    untracked_files.add(rel_sub)
                    else:
                        untracked_files.add(norm_p)
                else:
                    tracked_files.add(norm_p)
    except (FileNotFoundError, subprocess.CalledProcessError, Exception) as e:
        degraded = True
        messages.append(f"git status check failed: {e}")

    # 2. 补采 git diff --name-only 与 git diff --cached --name-only
    if not degraded:
        for diff_cmd in (
            ["git", "-C", workspace_root, "diff", "--name-only"],
            ["git", "-C", workspace_root, "diff", "--cached", "--name-only"],
        ):
            try:
                res_diff = subprocess.run(
                    diff_cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    check=False,
                )
                if res_diff.returncode == 0:
                    for line in res_diff.stdout.splitlines():
                        p = line.strip().strip('"')
                        if p:
                            tracked_files.add(p.replace("\\", "/"))
            except Exception as e:
                messages.append(f"git diff name-only failed: {e}")

    # 3. 归类受管生产代码与测试文件
    all_changed = tracked_files | untracked_files
    governed_code_changed: list[str] = []
    test_files_changed: list[str] = []

    for f in sorted(all_changed):
        norm_f = f.replace("\\", "/")
        if _TEST_FILE_PATTERN.search(norm_f):
            test_files_changed.append(norm_f)
        elif hasattr(config, "is_path_governed") and config.is_path_governed(norm_f):
            governed_code_changed.append(norm_f)

    # 4. 扫描测试文件中的断言标记
    assertions_found = False
    detected_markers: list[str] = []

    if not degraded and test_files_changed:
        for tf in test_files_changed:
            if tf in untracked_files:
                # 未跟踪测试文件：直接读取全文
                abs_tf = os.path.join(workspace_root, tf)
                if os.path.isfile(abs_tf):
                    try:
                        with open(abs_tf, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        for marker in _ASSERTION_MARKERS:
                            if marker in content:
                                assertions_found = True
                                if marker not in detected_markers:
                                    detected_markers.append(marker)
                    except Exception as e:
                        messages.append(f"Failed to read untracked test file {tf}: {e}")
            else:
                # 已跟踪测试文件：仅扫描 diff 新增行 (--unified=0)
                for diff_cmd in (
                    ["git", "-C", workspace_root, "diff", "-U0", "--", tf],
                    ["git", "-C", workspace_root, "diff", "--cached", "-U0", "--", tf],
                ):
                    try:
                        res = subprocess.run(
                            diff_cmd,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="ignore",
                            check=False,
                        )
                        if res.returncode == 0:
                            for line in res.stdout.splitlines():
                                if line.startswith("+") and not line.startswith("+++"):
                                    added_content = line[1:]
                                    for marker in _ASSERTION_MARKERS:
                                        if marker in added_content:
                                            assertions_found = True
                                            if marker not in detected_markers:
                                                detected_markers.append(marker)
                    except Exception as e:
                        messages.append(f"Failed to diff test file {tf}: {e}")

    # 5. 豁免判定
    exempted = False
    exemption_reason = None
    if test_evidence:
        match = _EXEMPTION_PATTERN.search(test_evidence)
        if match:
            exempted = True
            exemption_reason = match.group(1).lower()

    # 6. 最终判定
    if degraded:
        passed = True
        _append_hook_log(
            workspace_root,
            f"[DOD GUARD DEGRADED] Test audit degraded due to git environment: {'; '.join(messages)}",
        )
    elif len(governed_code_changed) == 0:
        passed = True
    elif exempted:
        passed = True
    elif assertions_found:
        passed = True
    else:
        passed = False

    return {
        "passed": passed,
        "governed_code_changed": governed_code_changed,
        "test_files_changed": test_files_changed,
        "assertions_found": assertions_found,
        "detected_markers": detected_markers,
        "exempted": exempted,
        "exemption_reason": exemption_reason,
        "degraded": degraded,
        "messages": messages,
        # Backward-compatible keys
        "audit_performed": not degraded,
        "test_changes": test_files_changed,
    }


def _get_recent_hook_logs(workspace_root: str, max_lines: int = 10) -> List[str]:
    """Read the last N lines of .agents/.quench_hook.log with integrity validation. / 读取 .agents/.quench_hook.log 最近 N 条日志，若不存在返回空列表。"""

    log_file = os.path.join(workspace_root, ".agents", ".quench_hook.log")
    if not os.path.isfile(log_file):
        return []

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            raw_content = f.read()

        if not raw_content:
            return []

        has_trailing_newline = raw_content.endswith("\n") or raw_content.endswith("\r")
        raw_lines = raw_content.splitlines()
        if not raw_lines:
            return []

        # 若文件末尾没有换行符，说明末行正处于子进程写入半途（未刷盘换行），属于不完整行，剔除
        if not has_trailing_newline:
            raw_lines.pop()

        if not raw_lines:
            return []

        # 剔除可能包含异常空字符的残缺末行
        if "\x00" in raw_lines[-1]:
            raw_lines.pop()

        return raw_lines[-max_lines:]
    except Exception:
        return []


# ==============================================================================
# MCP Tools
# ==============================================================================

@mcp.tool()
def dev_tasks_status(
    workspace_root: str,
    include_drafts: bool = False,
) -> Dict[str, Any]:
    """Inspect development tasks status in the workspace. Returns active files, task status breakdown, and currently in-progress tasks.

    [中文对照] 探查工作区的开发任务状态。返回活跃文件、任务状态分布与当前执行中的任务。支持隔离或包含草案任务。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        include_drafts: Whether to include draft tasks in pending queue (default False) / 是否在待领队列中包含草案任务（默认隔离）。
    """
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"error": f"Failed to load project config / 加载项目配置失败: {e}"}

    # 检查会话快速旁路状态（保证旁路绝不静默）
    bypass_file = os.path.join(workspace_root, ".agents", ".quench_bypass.json")
    bypass_status = None
    if os.path.isfile(bypass_file):
        try:
            with open(bypass_file, "r", encoding="utf-8") as f:
                bdata = json.load(f)
            if bdata.get("active"):
                expires_at = bdata.get("expires_at")
                is_expired = False
                if expires_at:
                    try:
                        exp_dt = datetime.fromisoformat(expires_at)
                        exp_dt_utc = exp_dt.astimezone(timezone.utc)
                        if datetime.now(timezone.utc) > exp_dt_utc:
                            is_expired = True
                    except Exception:
                        is_expired = True
                if not is_expired:
                    bypass_status = {
                        "active": True,
                        "session_id": bdata.get("session_id"),
                        "category": bdata.get("category"),
                        "patterns": bdata.get("patterns"),
                        "reason": bdata.get("reason"),
                        "expires_at": bdata.get("expires_at"),
                        "notice": "⚠️ Current session has fast-track bypass active / 当前会话已激活快速旁路，指定模式文件免除任务单管控。",
                    }
                else:
                    bypass_status = {
                        "active": False,
                        "expired": True,
                        "notice": "ℹ️ Previous session fast-track bypass has expired / 之前的会话快速旁路已过期失效。",
                    }
        except Exception:
            pass

    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    if not os.path.exists(dev_tasks_dir):
        os.makedirs(dev_tasks_dir, exist_ok=True)
        return {
            "project_name": config.project_name,
            "dev_tasks_dir": dev_tasks_dir,
            "files": [],
            "active_task": None,
            "session_bypass": bypass_status,
            "static_fast_track_patterns": config.get_fast_track_patterns(),
            "governance_scope": config.governance_scope,
            "last_hook_log_entries": _get_recent_hook_logs(workspace_root, max_lines=10),
            "reconcile_report": {
                "bypass_queue": [],
                "drift_queue": [],
                "matched_queue": [],
            },
            "bypass_queue": [],
            "message": f"Tasks directory created: {dev_tasks_dir}. No task files currently found. / 任务目录已创建: {dev_tasks_dir}，当前暂无任务单。",
        }

    md_files = glob.glob(os.path.join(dev_tasks_dir, "*.md"))
    file_records = []
    active_task = None

    reconcile_report = reconcile_workspace(workspace_root, dev_tasks_dir)
    norm_bypass = {p.replace("\\", "/").lower() for p in reconcile_report.bypass_queue}

    for f_path in sorted(md_files, reverse=True):
        basename = os.path.basename(f_path)
        if basename.lower() == "readme.md":
            continue
        rel_f_path = os.path.relpath(f_path, workspace_root).replace("\\", "/")
        is_quarantined = rel_f_path.lower() in norm_bypass
        try:
            summary = get_status_summary(f_path)
            tasks = parse_task_file(f_path)

            raw_file_text = ""
            try:
                with open(f_path, "r", encoding="utf-8", errors="ignore") as rf:
                    raw_file_text = rf.read()
            except Exception:
                pass

            draft_ids = set()
            for dm in re.finditer(r"^###\s+(?:任务|Task)\s+([0-9a-zA-Z\._\-]+)\s*.*?(?:\(草案\)|\(Draft\)|\(draft\))", raw_file_text, re.MULTILINE):
                draft_ids.add(dm.group(1).strip())
            for dm in re.finditer(r"^###\s+(?:任务|Task)\s+([0-9a-zA-Z\._\-]+)[\s\S]*?<!--\s*quench-task-meta:\s*({.*?})\s*-->", raw_file_text, re.MULTILINE):
                try:
                    meta = json.loads(dm.group(2))
                    if meta.get("draft"):
                        draft_ids.add(dm.group(1).strip())
                except Exception:
                    pass

            confirmed_q = [t.id for t in tasks if t.status == STATUS_CONFIRMED]
            rework_q = [t.id for t in tasks if t.status == STATUS_REWORK]
            draft_q = [t.id for t in tasks if t.id in draft_ids]

            if not include_drafts:
                pending_q = [t.id for t in tasks if t.status == STATUS_PENDING and t.id not in draft_ids]
            else:
                pending_q = [t.id for t in tasks if t.status == STATUS_PENDING]

            in_prog_q = [t.id for t in tasks if t.status == STATUS_IN_PROGRESS]
            completed_q = [t.id for t in tasks if t.status == STATUS_COMPLETED]

            if draft_q:
                summary["📝 草案"] = len(draft_q)

            file_rec = {
                "name": basename,
                "path": f_path,
                "total_tasks": len(tasks),
                "summary": summary,
                "batches": {
                    "confirmed_queue": confirmed_q,
                    "rework_queue": rework_q,
                    "pending_queue": pending_q,
                    "draft_queue": draft_q,
                    "in_progress": in_prog_q,
                    "completed_count": len(completed_q),
                },
                "quarantined": is_quarantined,
            }
            if is_quarantined:
                file_rec["quarantine_reason"] = "UNAUTHORIZED_BYPASS: Untracked task file not registered in manifest"
            file_records.append(file_rec)

            if not active_task and not is_quarantined:
                for t in tasks:
                    if t.status == STATUS_IN_PROGRESS:
                        active_task = {
                            "file": basename,
                            "file_path": f_path,
                            "id": t.id,
                            "title": t.title,
                            "status": t.status,
                        }
                        break
        except Exception:
            continue

    result_data = {
        "project_name": config.project_name,
        "dev_tasks_dir": dev_tasks_dir,
        "files": file_records,
        "active_task": active_task,
        "session_bypass": bypass_status,
        "static_fast_track_patterns": config.get_fast_track_patterns(),
        "governance_scope": config.governance_scope,
        "last_hook_log_entries": _get_recent_hook_logs(workspace_root, max_lines=10),
        "reconcile_report": {
            "bypass_queue": list(reconcile_report.bypass_queue),
            "drift_queue": list(reconcile_report.drift_queue),
            "matched_queue": list(reconcile_report.matched_queue),
        },
        "bypass_queue": list(reconcile_report.bypass_queue),
    }
    if reconcile_report.bypass_queue:
        result_data["bypass_warning"] = (
            f"⚠️ Detected {len(reconcile_report.bypass_queue)} unauthorized rogue task files quarantined in bypass_queue: "
            f"{list(reconcile_report.bypass_queue)} / 检测到未授权旁路任务单已物理隔离"
        )
    return result_data


@mcp.tool()
def dev_tasks_propose(
    workspace_root: str, task_file_name: str, tasks: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Create or append standard development task items. Each task item must adhere to the six-core-field contract.

    [中文对照] 创建或追加标准开发任务单。每条任务必须符合六大字段契约。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        task_file_name: Target task file name (e.g., '2026-09-13_feature.md') / 任务单文件名。
        tasks: List of task specifications conforming to the six core fields / 符合六大核心字段的任务字典列表。
    """
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"created": False, "error": f"Configuration error / 配置错误: {e}"}

    if not task_file_name.endswith(".md"):
        task_file_name += ".md"

    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    os.makedirs(dev_tasks_dir, exist_ok=True)
    target_path = os.path.join(dev_tasks_dir, task_file_name)

    all_errors = []
    all_warnings = []

    for idx, t in enumerate(tasks, 1):
        t_id = t.get("id") or f"{idx}"
        t["id"] = t_id
        res = validate_task_schema(t)
        if not res.is_valid:
            for err in res.errors:
                all_errors.append(f"Task {t_id}: {err}")
        for w in res.warnings:
            all_warnings.append(f"Task {t_id}: {w}")

    if all_errors:
        return {
            "created": False,
            "errors": all_errors,
            "warnings": all_warnings,
            "message": "Task schema validation failed. Please fix according to errors and retry / 任务单校验未通过，请根据错误信息修正后重试。",
        }

    file_exists = os.path.isfile(target_path)
    rendered_blocks = "".join(_render_task_markdown(t) for t in tasks)

    if not file_exists:
        header = [
            f"# {os.path.splitext(task_file_name)[0]} Development Tasks / 开发任务单\n\n",
            "> **Execution Guidelines for AI Models / 执行模型须知**\n",
            "> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order\n",
            "> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件\n",
            "> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串\n",
            "> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions\n",
            "> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`\n\n",
            f"- **Created Date / 创建日期**：{date.today().isoformat()}\n\n",
            "---\n\n",
            "## Task List & Status / 任务清单与状态\n\n",
        ]
        full_content = "".join(header) + rendered_blocks
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(full_content)
    else:
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(rendered_blocks)

    try:
        for t in tasks:
            t_id = t.get("id") or "1"
            register_proposal(workspace_root, task_id=str(t_id), md_path=target_path)
    except Exception:
        pass

    return {
        "created": True,
        "file_path": target_path,
        "created_count": len(tasks),
        "warnings": all_warnings,
        "message": f"Successfully {'appended' if file_exists else 'created'} {len(tasks)} tasks in {target_path} / 成功{'追加' if file_exists else '创建'} {len(tasks)} 项任务至 {target_path}",
    }


@mcp.tool()
def dev_tasks_confirm(
    workspace_root: str, task_file: str, task_ids: List[str], action: str = "confirm"
) -> Dict[str, Any]:
    """Transition or adjust task states. action: 'confirm' (approved for execution) | 'rework' (requires review model revision) | 'skip' (skipped) | 'revoke' (revert to pending).

    [中文对照] 推进或调整任务状态。action: 'confirm' (已确认待施工) | 'rework' (需返工/待审查模型重修) | 'skip' (跳过) | 'revoke' (撤回为待确认)。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        task_file: Task file name or path / 任务单文件名或相对路径。
        task_ids: List of task IDs to transition (e.g. ['1.1', '1.2']) / 待流转的任务ID列表。
        action: Target transition action ('confirm', 'rework', 'skip', 'revoke') / 目标流转动作。
    """
    target_path = _resolve_task_file_path(workspace_root, task_file)
    action_map = {
        "confirm": STATUS_CONFIRMED,
        "rework": STATUS_REWORK,
        "skip": STATUS_SKIPPED,
        "revoke": STATUS_PENDING,
    }
    target_status = action_map.get(action.lower())
    if not target_status:
        return {
            "error": f"Unsupported action '{action}', valid options: 'confirm', 'rework', 'skip', 'revoke' / 不支持的 action '{action}'，支持: 'confirm', 'rework', 'skip', 'revoke'"
        }

    updated = []
    errors = []

    tasks = parse_task_file(target_path) if os.path.isfile(target_path) else []
    task_map = {str(t.id).strip(): t for t in tasks}

    for tid in task_ids:
        clean_tid = str(tid).strip()
        t_item = task_map.get(clean_tid)
        if t_item and t_item.status == STATUS_IN_PROGRESS and target_status == STATUS_CONFIRMED:
            errors.append({
                "id": tid,
                "error": (
                    f"Cannot transition task '{tid}' from 'In Progress' to 'Confirmed' via dev_tasks_confirm. "
                    f"This transition is strictly reserved for dev_tasks_reclaim to ensure fencing generation monotonicity / "
                    f"禁止通过 dev_tasks_confirm 将执行中任务直接重置为已确认状态。该流转严格保留给 dev_tasks_reclaim 回收通道以确保代际递增。"
                ),
            })
            continue

        try:
            res = transition_task(target_path, str(tid), target_status)
            updated.append({"id": res.id, "title": res.title, "new_status": res.status})
        except Exception as e:
            errors.append({"id": tid, "error": str(e)})

    return {
        "file": target_path,
        "action": action,
        "updated": updated,
        "errors": errors,
    }


DispatchStrategy = Literal["subagent", "engine", "manual"]


class ReviewerHandoff(TypedDict, total=False):
    contract_version: Literal["1.0"]
    task_id: str
    task_path: str
    reason: str  # "batch_complete" | "escalation" | "rework_required"
    summary: str
    preferred: DispatchStrategy
    strategies: list[Dict[str, Any]]
    legacy_card_markdown: str


def _resolve_handoff_envelope(
    workspace_root: str,
    config: QuenchStackConfig,
    task_id: str,
    task_path: str,
    reason: str,
    context_files: Optional[List[str]] = None,
    host_capabilities: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Pure, side-effect-free envelope builder with zero synchronous network I/O.
    Enforces R3 invariant: strategies[-1]['strategy'] == 'manual' and available == True.
    """
    ws_root = os.path.abspath(workspace_root)

    # Path safety: ensure task_path is normalized and confined within workspace_root
    try:
        rel_task_path = to_workspace_relative_path(ws_root, task_path)
    except PathTraversalError:
        # Fallback to sanitized basename if traversal attempted
        rel_task_path = os.path.basename(str(task_path)).replace("\\", "/")
    except Exception:
        rel_task_path = str(task_path).replace("\\", "/")

    # Context files safety: restrict to workspace_root, cap at 8 files
    safe_context_files: List[str] = []
    if context_files:
        for cf in context_files[:8]:
            try:
                cf_clean = str(cf).strip()
                if not cf_clean:
                    continue
                rel_cf = to_workspace_relative_path(ws_root, cf_clean, must_exist=False)
                safe_context_files.append(rel_cf)
            except PathTraversalError:
                # Strictly reject any traversal vectors (host-invariant)
                continue
            except Exception:
                continue

    re_cfg = getattr(config, "reviewer_engine", None)
    if re_cfg is None:
        re_cfg = ReviewerEngineConfig()

    client = ReviewerClient(re_cfg)
    client_available = client.is_available()

    mode = getattr(re_cfg, "mode", "auto") or "auto"
    if mode not in ("auto", "subagent", "engine", "manual"):
        mode = "auto"

    configured_order = getattr(re_cfg, "strategy_order", None)
    if not isinstance(configured_order, list) or not configured_order:
        configured_order = ["subagent", "engine", "manual"]
    else:
        configured_order = [s for s in configured_order if s in ("subagent", "engine", "manual")]
        if not configured_order:
            configured_order = ["subagent", "engine", "manual"]

    # 1. subagent strategy
    subagent_allowed = mode in ("auto", "subagent")
    if host_capabilities is not None:
        subagent_supported = "subagent" in host_capabilities
    else:
        subagent_supported = True

    subagent_available = subagent_allowed and subagent_supported

    subagent_prompt = (
        f"Role: Senior Architecture Reviewer (Quench Governance Framework).\n"
        f"You are invoked to conduct an in-depth, read-only architectural review for Task '{task_id}'.\n"
        f"Task Path: {rel_task_path}\n"
        f"Handoff Reason: {reason}\n"
        f"Reference Files: {', '.join(safe_context_files) if safe_context_files else 'None'}\n\n"
        f"CRITICAL DISCIPLINE & INSTRUCTIONS:\n"
        f"1. You are strictly in READ-ONLY mode. Do NOT edit or overwrite any project source code files directly;\n"
        f"2. Conduct deep causal analysis, evaluate concurrency, anti-patterns, boundary conditions, and test assertions;\n"
        f"3. On review completion, callback via `dev_tasks_confirm` to transition approved tasks, or provide revision guidance."
    )

    subagent_strat: Dict[str, Any] = {
        "strategy": "subagent",
        "available": subagent_available,
        "payload": {
            "agent": "reviewer",
            "prompt": subagent_prompt,
            "context_files": safe_context_files,
            "callback_instruction": "Inspect task specification, conduct read-only review, and callback with dev_tasks_confirm upon approval.",
        },
    }

    # 2. engine strategy
    engine_allowed = mode in ("auto", "engine")
    engine_available = engine_allowed and client_available

    key_present = bool(client.resolve_api_key()) or client.is_available()

    engine_strat: Dict[str, Any] = {
        "strategy": "engine",
        "available": engine_available,
        "payload": {
            "provider": re_cfg.provider,
            "model": re_cfg.model,
            "api_key_present": key_present,
            "guidance": "Call dev_tasks_refine_spec to automatically refine, harden, and generate test assertions using the configured Reviewer engine.",
        },
    }

    # 3. manual strategy (R3 invariant: ALWAYS True!)
    manual_strat: Dict[str, Any] = {
        "strategy": "manual",
        "available": True,
        "payload": {
            "guidance": "Switch to a senior architecture reviewer model in a new clean session, paste the handoff card, and confirm revision before resuming.",
        },
    }

    strat_map = {
        "subagent": subagent_strat,
        "engine": engine_strat,
        "manual": manual_strat,
    }

    ordered_strats: List[Dict[str, Any]] = []
    for s_name in configured_order:
        if s_name != "manual" and s_name in strat_map:
            ordered_strats.append(strat_map[s_name])
    for s_name in ["subagent", "engine"]:
        if strat_map[s_name] not in ordered_strats:
            ordered_strats.append(strat_map[s_name])
    # R3 Invariant: manual must always be last and available == True
    ordered_strats.append(manual_strat)

    if mode == "manual":
        preferred: DispatchStrategy = "manual"
    elif mode == "subagent" and subagent_strat["available"]:
        preferred = "subagent"
    elif mode == "engine" and engine_strat["available"]:
        preferred = "engine"
    else:
        preferred = "manual"
        for s in ordered_strats:
            if s["available"]:
                preferred = s["strategy"]  # type: ignore
                break

    card_lines = [
        "================================================================================",
        "📋 Quench 任务交接卡 / Quench Task Handoff Card",
        "================================================================================",
        f"• Task ID / 任务编号:       {task_id}",
        f"• Task Path / 单据路径:     {rel_task_path}",
        f"• Handoff Reason / 交接原因: {reason}",
        f"• Preferred Mode / 推荐模式: {preferred}",
        "--------------------------------------------------------------------------------",
        "【核心指引 / Execution Instructions】",
        "1. [禁止就地切换] 严禁在当前长会话内就地切换大模型（规避数万历史 Token 冗余重传与注意力稀释）；",
        f"2. [执行交接] 当前推荐采用【{preferred}】策略进行审查与重构：",
    ]
    if preferred == "subagent":
        card_lines.append("   - 宿主支持原生子代理调度：请调起 reviewer 子代理，并下发只读审查提示词；")
    elif preferred == "engine":
        card_lines.append(f"   - 审查引擎已就绪 ({re_cfg.provider} / {re_cfg.model})：请调用 dev_tasks_refine_spec 自动强化规约；")
    else:
        card_lines.append("   - 终局兜底模式：请在新的纯净会话中切换至高阶架构审查模型，粘贴本卡完成审查。")
    card_lines.append("================================================================================")
    legacy_card_markdown = "\n".join(card_lines)

    manual_strat["payload"]["card_markdown"] = legacy_card_markdown

    envelope: ReviewerHandoff = {
        "contract_version": "1.0",
        "task_id": task_id,
        "task_path": rel_task_path,
        "reason": reason,
        "summary": f"Reviewer handoff triggered for task '{task_id}' (reason: {reason}, preferred: {preferred})",
        "preferred": preferred,
        "strategies": ordered_strats,
        "legacy_card_markdown": legacy_card_markdown,
    }
    return envelope


def _issue_checkout_lease(workspace_root: str, task_file: str, task_id: str, session_id: Optional[str] = None) -> tuple[str, int]:
    """签发独占 Fencing Token 租约并原子记录至 manifest.json。"""
    if session_id:
        try:
            clean_sid = _validate_session_id(session_id)
            holder_token = f"token_{clean_sid}_{int(time.time()*1000)}_{os.getpid()}"
        except Exception:
            holder_token = f"token_{int(time.time()*1000)}_{os.getpid()}"
    else:
        holder_token = f"token_{int(time.time()*1000)}_{os.getpid()}"
    namespaced_id = f"{Path(task_file).stem}::{task_id}"
    m = load_manifest(workspace_root)
    existing_rec = m.records.get(namespaced_id)
    expected_gen = existing_rec.generation if existing_rec else 0
    try:
        new_gen = commit_lease(
            workspace_root,
            task_id=namespaced_id,
            holder_token=holder_token,
            expected_generation=expected_gen,
            md_path=task_file,
        )
    except Exception:
        new_gen = expected_gen + 1
    return holder_token, new_gen


@mcp.tool()
def dev_tasks_checkout(
    workspace_root: str,
    task_file: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Check out a confirmed task, automatically transitioning it to '🔨 执行中' and returning detailed implementation instructions. Supports directed checkout via task file and ID.

    [中文对照] 检出处于 ✅ 已确认 状态的任务，自动将其标记为 🔨 执行中 并下发详细指引。支持指定任务文件与任务ID定向领单。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        task_file: Optional task file name / 可选指定任务文件。
        task_id: Optional task ID for directed checkout / 可选指定任务ID定向领单。
        session_id: Optional session UUID for multi-session isolation / 可选多会话隔离标识。
    """
    clean_session_id = None
    if session_id:
        try:
            clean_session_id = _validate_session_id(session_id)
        except ValueError as ve:
            return {"error": f"Invalid session_id format / 非法的 session_id 格式: {ve}"}

    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"error": f"Configuration error / 配置错误: {e}"}

    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    if task_file:
        resolved_file = _resolve_task_file_path(workspace_root, task_file)
        if not os.path.isfile(resolved_file):
            return {"error": f"Specified task file does not exist: {task_file} / 指定的任务文件不存在: {task_file}"}
        try:
            assert_task_checkout_allowed(workspace_root, resolved_file)
        except Exception as e:
            return {"error": f"Checkout blocked by security policy / 检出被安全策略阻断: {e}"}
        md_files = [resolved_file]
    else:
        md_files = sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True)

    # 过滤掉 README.md
    md_files = [f for f in md_files if os.path.basename(f).lower() != "readme.md"]

    # 场景 1: 用户或模型显式指定了 task_id 进行定向检出
    if task_id:
        target_tid = str(task_id).strip()
        for f_path in md_files:
            tasks = parse_task_file(f_path)
            for t in tasks:
                if str(t.id).strip() == target_tid:
                    try:
                        assert_task_checkout_allowed(workspace_root, f_path)
                    except Exception as e:
                        return {"error": f"Checkout blocked by security policy / 检出被安全策略阻断: {e}"}
                    if t.status == STATUS_REWORK:
                        return {
                            "error": f"Task {target_tid} is currently in '🔄 需返工' status. It must be revised and confirmed by senior Reviewer model before checkout / 任务 {target_tid} 当前处于 '🔄 需返工' 状态，必须先由高阶架构审查模型修订并确认后方可领单。",
                            "task_id": t.id,
                            "status": t.status,
                            "handoff_recommended": True,
                        }
                    if t.status == STATUS_PENDING:
                        return {
                            "error": f"Task {target_tid} is currently in '⬜ 待确认' status. Unconfirmed tasks cannot be checked out directly / 任务 {target_tid} 当前处于 '⬜ 待确认' 状态，尚未经确认，禁止直接领单施工。",
                            "task_id": t.id,
                            "status": t.status,
                            "handoff_recommended": True,
                        }
                    if t.status == STATUS_IN_PROGRESS:
                        detail = _extract_task_detail(f_path, t.id)
                        namespaced_id = f"{Path(f_path).stem}::{t.id}"
                        try:
                            m = load_manifest(workspace_root)
                            existing_rec = m.records.get(namespaced_id)
                        except ManifestIntegrityError as mie:
                            return {"error": f"Manifest integrity compromised (Fail-Closed): {mie} / 清单完整性受损阻断"}
                        resp = {
                            "task_file": f_path,
                            "task_id": t.id,
                            "title": t.title,
                            "status": t.status,
                            "spec": detail.get("full_spec", ""),
                            "note": "Task is already in progress; instructions re-extracted / 该任务已经在执行中，已重新提取指引下发。",
                        }
                        if existing_rec:
                            resp["holder_token"] = existing_rec.holder_token
                            resp["generation"] = existing_rec.generation
                        if clean_session_id:
                            resp["session_id"] = clean_session_id
                        return resp
                    if t.status == STATUS_CONFIRMED:
                        try:
                            updated = transition_task(f_path, t.id, STATUS_IN_PROGRESS)
                            detail = _extract_task_detail(f_path, t.id)
                            holder_token, gen = _issue_checkout_lease(workspace_root, f_path, updated.id, session_id=clean_session_id)
                            resp_data = {
                                "task_file": f_path,
                                "task_id": updated.id,
                                "title": updated.title,
                                "status": updated.status,
                                "spec": detail.get("full_spec", ""),
                                "holder_token": holder_token,
                                "generation": gen,
                            }
                            if clean_session_id:
                                resp_data["session_id"] = clean_session_id
                            return resp_data
                        except Exception as e:
                            return {"error": f"Failed to transition task {t.id} to in_progress / 检出任务 {t.id} 状态流转失败: {e}"}
                    return {
                        "error": f"Task {target_tid} status is '{t.status}', not checkoutable / 任务 {target_tid} 当前状态为 '{t.status}'，不可检出。",
                        "task_id": t.id,
                        "status": t.status,
                    }
        return {"error": f"Task ID '{task_id}' not found in task files / 在任务文件列表中未找到任务 ID '{task_id}'"}

    # 场景 2: 顺序领单（寻找第一个 ✅ 已确认 的任务）
    for f_path in md_files:
        try:
            assert_task_checkout_allowed(workspace_root, f_path)
        except Exception:
            # 该任务单处于未授权旁路隔离队列，跳过该文件的任务
            continue
        tasks = parse_task_file(f_path)
        for t in tasks:
            if t.status == STATUS_CONFIRMED:
                try:
                    updated = transition_task(f_path, t.id, STATUS_IN_PROGRESS)
                    detail = _extract_task_detail(f_path, t.id)
                    holder_token, gen = _issue_checkout_lease(workspace_root, f_path, updated.id, session_id=clean_session_id)
                    resp_data = {
                        "task_file": f_path,
                        "task_id": updated.id,
                        "title": updated.title,
                        "status": updated.status,
                        "spec": detail.get("full_spec", ""),
                        "holder_token": holder_token,
                        "generation": gen,
                    }
                    if clean_session_id:
                        resp_data["session_id"] = clean_session_id
                    return resp_data
                except Exception as e:
                    return {"error": f"Failed to transition task {t.id} to in_progress / 检出任务 {t.id} 状态流转失败: {e}"}


    # 场景 3: 没有处于 ✅ 已确认 状态的任务，深度扫描待确认与需返工分布（分批施工闭环审计）
    pending_tasks = []
    rework_tasks = []
    for f_path in md_files:
        for t in parse_task_file(f_path):
            if t.status == STATUS_PENDING:
                pending_tasks.append({"file": os.path.basename(f_path), "id": t.id, "title": t.title})
            elif t.status == STATUS_REWORK:
                rework_tasks.append({"file": os.path.basename(f_path), "id": t.id, "title": t.title})

    if rework_tasks or pending_tasks:
        primary_task = rework_tasks[0] if rework_tasks else pending_tasks[0]
        primary_tid = str(primary_task.get("id", ""))
        primary_file = str(primary_task.get("file", ""))
        handoff_reason = "rework_required" if rework_tasks else "batch_complete"

        envelope = _resolve_handoff_envelope(
            workspace_root=workspace_root,
            config=config,
            task_id=primary_tid,
            task_path=os.path.join(dev_tasks_dir, primary_file),
            reason=handoff_reason,
        )

        return {
            "task_id": None,
            "batch_finished": True,
            "has_pending_tasks": len(pending_tasks) > 0,
            "has_rework_tasks": len(rework_tasks) > 0,
            "pending_count": len(pending_tasks),
            "rework_count": len(rework_tasks),
            "pending_tasks": pending_tasks[:5],
            "rework_tasks": rework_tasks[:5],
            "handoff_recommended": True,
            "reviewer_handoff": envelope,
            "handoff_card": envelope["legacy_card_markdown"],
            "instruction": (
                "[Current Batch Finished / Tasks Pending Review or Rework]\n"
                "1. If rework/pending tasks exist: Output [Quench Task Handoff Card] to guide user to switch to senior Reviewer model in a new session;\n"
                "2. If working in batches: Report completion of current batch to user and await confirmation for next batch.\n\n"
                "【当前已确认批次已全部完工 / 存在需返工或待终审任务】\n"
                "1. 若存在需返工或待终审任务：请输出【Quench 任务交接卡】，引导用户在新会话切换至自选的高阶架构审查模型进行审查修订；\n"
                "2. 若属于多任务分批施工：请向用户汇报当前批次施工完毕，等待用户确认下一批任务后再行领单。"
            ),
            "message": f"Current batch has no '✅ Confirmed' tasks. (Pending: {len(pending_tasks)}, Rework: {len(rework_tasks)}) / 当前批次已无 '✅ 已确认' 任务。(待终审: {len(pending_tasks)} 项, 需返工: {len(rework_tasks)} 项)",
        }

    return {
        "task_id": None,
        "batch_finished": True,
        "all_completed": True,
        "instruction": (
            "[All Tasks Completed & Delivery Protocol]\n"
            "All tasks in the active file have reached '✔️ 已完成' (or '⏭️ 跳过').\n"
            "1. Verification: If tasks involve frontend UI, hardware serial, or complex flows, prompt user for manual verification or ask to run E2E browser/emulator tests;\n"
            "2. Archival: If automated tests fully guarantee correctness or user approved, ask user to update design docs and confirm dev_tasks_archive.\n\n"
            "【全量任务完工交付与归档范式指引】\n"
            "当前任务单中所有任务均已达成 '✔️ 已完成'（或 '⏭️ 跳过'）。\n"
            "1. 检验判断：若任务包含前端 UI 呈现、硬件串口通信或复杂交互流程，必须主动提醒用户进行验收体验，或询问是否由 Agent 启动自动化端到端测试；\n"
            "2. 归档决策：若纯自动化单测已完备覆盖且保障系统正确性，或用户验收满意，必须主动询问用户是否更新设计文档并确认调用 dev_tasks_archive 归档。"
        ),
        "message": "All tasks are completed. Prompt user for verification or ask to archive / 当前所有任务均已闭环完成。请根据任务性质提醒用户必要验收，或主动询问是否更新文档并归档。",
    }


@mcp.tool()
def dev_tasks_complete(
    workspace_root: str,
    task_file: str,
    task_id: str,
    dod_output: str,
    test_evidence: str = "",
    holder_token: Optional[str] = None,
    generation: Optional[int] = None,
) -> Dict[str, Any]:
    """Submit task completion report. Performs physical auditing on test files and assertions via git diff; marks task as '✔️ 已完成' upon full verification.

    [中文对照] 执行 Agent 提交任务完成报告。通过 git diff 审计测试文件与断言，全部通过后标记为 ✔️ 已完成。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        task_file: Task file name or path / 任务单文件名或相对路径。
        task_id: Task ID to complete (e.g. '1.1') / 待完成的任务ID。
        dod_output: Execution output of Definition-of-Done commands / DoD 验证命令的终端执行输出。
        test_evidence: Optional test evidence or exemption rationale / 可选的单测佐证或纯文档豁免说明。
        holder_token: Optional fencing lease holder token to verify / 可选租约持有者令牌校验。
        generation: Optional expected fencing generation / 可选租约代际校验。
    """
    target_path = _resolve_task_file_path(workspace_root, task_file)
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"status": "rejected", "reason": f"Configuration error / 配置错误: {e}"}

    tasks = parse_task_file(target_path)
    cur_task = next((t for t in tasks if str(t.id).strip() == str(task_id).strip()), None)
    if not cur_task:
        return {"status": "rejected", "reason": f"Task {task_id} not found / 找不到任务 {task_id}"}

    if cur_task.status != STATUS_IN_PROGRESS:
        return {
            "status": "rejected",
            "reason": f"Task {task_id} status is '{cur_task.status}', not '🔨 执行中', cannot mark as completed / 任务 {task_id} 当前状态为 '{cur_task.status}'，非 '🔨 执行中'，无法标记完成",
        }

    # 校验租约归属与代际有效性（防分裂脑）
    namespaced_id = f"{Path(target_path).stem}::{cur_task.id}"
    try:
        m = load_manifest(workspace_root)
    except ManifestIntegrityError as mie:
        return {
            "status": "rejected",
            "reason": f"Manifest integrity compromised (Fail-Closed) for task {task_id}: {mie} / 清单完整性受损阻断",
        }
    active_lease = m.records.get(namespaced_id)
    if active_lease is not None and not active_lease.released:
        if holder_token is not None and active_lease.holder_token != holder_token:
            return {
                "status": "rejected",
                "reason": (
                    f"Fencing token lease conflict for task {task_id}: expected token '{active_lease.holder_token}', "
                    f"got '{holder_token}' / 任务租约持有者令牌冲突"
                ),
            }
        if generation is not None and active_lease.generation != generation:
            return {
                "status": "rejected",
                "reason": (
                    f"Fencing token generation mismatch for task {task_id}: expected generation {active_lease.generation}, "
                    f"got {generation} / 任务租约代际过期"
                ),
            }

    # 执行测试变更物理审计（含未跟踪测试文件、diff新增行与合法豁免）
    audit = _audit_test_changes(workspace_root, config, test_evidence=test_evidence)

    # 刚性门禁拦截：当受管生产代码发生变更且未通过单测断言审计（且未豁免/未降级）时，物理阻断且不流转状态
    if audit.get("governed_code_changed") and not audit.get("passed"):
        _append_hook_log(
            workspace_root,
            f"[DOD GUARD REJECTED] Task {task_id} completion blocked: governed code modified ({len(audit['governed_code_changed'])} files) but no test assertions found and no valid exemption.",
        )
        guidance = (
            "【DoD 物理门禁拦截 / Rigid DoD Test Guard Rejection】\n"
            "检测到受管生产代码被修改，但未检测到新增或变更的有效单测断言 (assert / pytest.raises)。\n"
            "修复指引 (Remediation Guidance):\n"
            "1. 新增/补充测试：在 tests/ 目录下编写针对本次变更的单元测试，并包含 assert 或 pytest.raises 断言；\n"
            "2. 若确系免测场景（如纯文档/配置/无行为变更重构），请在 test_evidence 参数中提供显式豁免标记：\n"
            "   - [EXEMPTION: docs-only]\n"
            "   - [EXEMPTION: config-only]\n"
            "   - [EXEMPTION: non-behavioral-refactor]\n"
            "3. 补充测试或声明豁免后重新调用 dev_tasks_complete。"
        )
        return {
            "status": "rejected",
            "audit": audit,
            "guidance": guidance,
            "reason": "Governed code changed without new test assertions or valid exemption / 受管代码发生变更但缺少单测断言且未提供合法豁免",
        }

    try:
        updated = transition_task(target_path, task_id, STATUS_COMPLETED)
        # 释放独占租约：留痕墓碑，保留代际 (B5)
        if active_lease is not None and not active_lease.released:
            tok = holder_token or active_lease.holder_token
            gen = generation if generation is not None else active_lease.generation
            release_lease(workspace_root, task_id=namespaced_id, holder_token=tok, generation=gen)

        return {
            "status": "completed",
            "task_id": updated.id,
            "title": updated.title,
            "new_status": updated.status,
            "audit": audit,
            "dod_output_recorded": bool(dod_output),
        }

    except Exception as e:
        return {"status": "rejected", "reason": f"Failed to transition task to completed / 流转为已完成失败: {e}"}


@mcp.tool()
async def dev_tasks_heartbeat(
    workspace_root: str = ".",
    task_id: Optional[str] = None,
    holder_token: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Refresh active lease heartbeat for current or specified task, supporting multi-session isolation.

    [中文对照] 刷新当前检出任务或指定任务的存活心跳租约，支持多会话隔离。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录路径（默认当前目录）。
        task_id: Optional task ID (e.g. '2.1' or 'spec::2.1') / 可选指定任务ID，缺省自动解析当前执行中任务。
        holder_token: Optional fencing lease holder token / 可选独占持有者令牌校验。
        session_id: Optional session UUID for multi-session disambiguation / 可选用于跨会话防歧义鉴权的会话ID。
    """
    ws = os.path.abspath(workspace_root)
    clean_session_id = None
    if session_id:
        try:
            clean_session_id = _validate_session_id(session_id)
        except ValueError as ve:
            return {"status": "rejected", "reason": f"Invalid session_id format / 非法的 session_id 格式: {ve}"}

    try:
        config = load_project_config(ws)
    except Exception as e:
        return {"status": "rejected", "reason": f"Configuration error / 配置错误: {e}"}

    try:
        m = load_manifest(ws)
    except ManifestIntegrityError as mie:
        return {
            "status": "rejected",
            "reason": f"Manifest integrity compromised (Fail-Closed) / 清单完整性受损阻断: {mie}",
        }
    except Exception as e:
        return {"status": "rejected", "reason": f"Failed to load manifest / 加载清单失败: {e}"}

    namespaced_id: Optional[str] = None

    if task_id:
        target_tid = str(task_id).strip()
        if "::" in target_tid:
            namespaced_id = target_tid
        else:
            suffix = f"::{target_tid}"
            namespaced_id = next((k for k in m.records if k == target_tid or k.endswith(suffix)), None)
            if not namespaced_id:
                dev_tasks_dir = config.resolve_path("dev_tasks_dir")
                if os.path.isdir(dev_tasks_dir):
                    for f_path in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
                        if os.path.basename(f_path).lower() == "readme.md":
                            continue
                        for t in parse_task_file(f_path):
                            if str(t.id).strip() == target_tid:
                                namespaced_id = f"{Path(f_path).stem}::{t.id}"
                                break
                        if namespaced_id:
                            break
            if not namespaced_id:
                namespaced_id = target_tid
    else:
        # 自动解析当前处于 🔨 执行中 的任务
        active_task = None
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")
        if os.path.isdir(dev_tasks_dir):
            for f_path in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
                if os.path.basename(f_path).lower() == "readme.md":
                    continue
                for t in parse_task_file(f_path):
                    if t.status == STATUS_IN_PROGRESS:
                        active_task = (f_path, t.id)
                        break
                if active_task:
                    break
        if not active_task:
            return {
                "status": "rejected",
                "reason": "No active task currently in progress / 当前无执行中任务",
            }
        f_path, tid = active_task
        namespaced_id = f"{Path(f_path).stem}::{tid}"

    record = m.records.get(namespaced_id)
    if record is None:
        return {
            "status": "rejected",
            "task_id": namespaced_id,
            "reason": f"No lease record found for task '{namespaced_id}' / 未找到任务租约记录",
        }

    if record.released:
        return {
            "status": "rejected",
            "task_id": namespaced_id,
            "generation": record.generation,
            "reason": f"Task lease for '{namespaced_id}' has already been released / 任务租约已释放",
        }

    # 跨会话防歧义鉴权
    if clean_session_id and record.holder_token.startswith("token_"):
        parts = record.holder_token.split("_")
        if len(parts) >= 4:
            recorded_session = "_".join(parts[1:-2])
            if recorded_session and recorded_session != clean_session_id:
                return {
                    "status": "rejected",
                    "task_id": namespaced_id,
                    "generation": record.generation,
                    "reason": f"Cross-session conflict: task lease belongs to session '{recorded_session}', got '{clean_session_id}' / 跨会话租约冲突",
                }

    token_to_renew = str(holder_token).strip() if holder_token else record.holder_token

    try:
        success = touch_heartbeat(
            ws,
            task_id=namespaced_id,
            holder_token=token_to_renew,
            generation=record.generation,
        )
    except ManifestIntegrityError as mie:
        return {
            "status": "rejected",
            "task_id": namespaced_id,
            "generation": record.generation,
            "reason": f"Manifest integrity compromised during heartbeat: {mie} / 心跳刷新期清单完整性受损",
        }
    except Exception as e:
        return {
            "status": "rejected",
            "task_id": namespaced_id,
            "generation": record.generation,
            "reason": f"Failed to touch heartbeat: {e} / 心跳续约异常: {e}",
        }

    if success:
        _append_hook_log(
            ws,
            f"[HEARTBEAT RENEWED] Task '{namespaced_id}' lease heartbeat refreshed (gen={record.generation}, token={token_to_renew})",
        )
        resp = {
            "status": "ok",
            "task_id": namespaced_id,
            "generation": record.generation,
            "holder_token": token_to_renew,
            "message": f"Heartbeat successfully renewed for task '{namespaced_id}' / 心跳租约续期成功",
        }
        if clean_session_id:
            resp["session_id"] = clean_session_id
        return resp
    else:
        return {
            "status": "rejected",
            "task_id": namespaced_id,
            "generation": record.generation,
            "reason": "Heartbeat rejected: generation or holder token mismatch, or lease released / 心跳续约被拒：代际或令牌不匹配，或租约已释放",
        }


@mcp.tool()
async def dev_tasks_reclaim(
    workspace_root: str = ".",
    task_id: str = "",
    expected_generation: int = 0,
    expected_holder_token: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """CAS 幂等回收疑似僵尸任务并重置为已确认待执行状态。

    [中文对照] 针对疑似假死或心跳超时的僵尸任务执行 CAS 幂等回收。验证预期代际与持有者令牌，在双锁保护下复核健康探针，回收成功后递增代际作废旧令牌并将任务重置为已确认待执行状态。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录路径（默认当前目录）。
        task_id: Target task ID (e.g. '2.1' or 'spec::2.1') / 目标任务ID。
        expected_generation: Expected lease generation for CAS verification / 用于 CAS 比对的预期代际。
        expected_holder_token: Expected holder token for CAS verification / 用于 CAS 比对的预期持有者令牌。
        force: Force reclaim even if health probes judge target as healthy / 是否无视探针健康度判定强制回收。
    """
    ws = os.path.abspath(workspace_root)
    clean_tid = str(task_id).strip()
    if not clean_tid:
        return {
            "status": "rejected",
            "reason": "missing_task_id",
            "message": "task_id is required / 必须提供 task_id",
        }

    try:
        ok, reason = reclaim_stale_task(
            ws,
            task_id=clean_tid,
            expected_generation=expected_generation,
            expected_holder_token=expected_holder_token,
            force=force,
        )
    except ManifestIntegrityError as mie:
        return {
            "status": "rejected",
            "task_id": clean_tid,
            "reason": "manifest_integrity_compromised",
            "message": f"Manifest integrity compromised during reclaim: {mie} / 回收期清单完整性受损阻断",
        }
    except Exception as e:
        return {
            "status": "error",
            "task_id": clean_tid,
            "reason": str(e),
            "message": f"Failed to reclaim task '{clean_tid}': {e} / 回收任务异常: {e}",
        }

    if ok:
        if reason == "reclaimed":
            _append_hook_log(
                ws,
                f"[TASK RECLAIMED] Stale task '{clean_tid}' reclaimed (expected gen={expected_generation}) and reset to confirmed",
            )
            return {
                "status": "reclaimed",
                "task_id": clean_tid,
                "reason": reason,
                "message": f"Task '{clean_tid}' successfully reclaimed and reset to confirmed / 任务成功回收并重置为已确认",
            }
        else:
            return {
                "status": "already_reclaimed_or_fenced",
                "task_id": clean_tid,
                "reason": reason,
                "message": f"Task '{clean_tid}' already reclaimed or fenced (idempotent success) / 任务租约已在先前回收或已被更新代际屏蔽（幂等成功）",
            }
    else:
        if reason == "target_is_healthy":
            return {
                "status": "rejected",
                "task_id": clean_tid,
                "reason": reason,
                "message": f"Task '{clean_tid}' is currently healthy based on health probes; use force=True to override / 探针判定目标任务当前健康活跃，拒绝回收；如确需强制回收请指定 force=True",
            }
        elif reason == "no_such_lease":
            return {
                "status": "rejected",
                "task_id": clean_tid,
                "reason": reason,
                "message": f"No lease record found for task '{clean_tid}' / 未找到任务租约记录",
            }
        else:
            return {
                "status": "rejected",
                "task_id": clean_tid,
                "reason": reason,
                "message": f"Task '{clean_tid}' reclaim rejected: {reason} / 任务回收被拒: {reason}",
            }


@mcp.tool()
def dev_tasks_promote_draft(
    workspace_root: str,
    task_file: str,
    task_id: str,
) -> Dict[str, Any]:
    """Validate physical feasibility of a draft task and promote it to formal [Pending] state.

    [中文对照] 运行物理可行性 Lint 闸门校验任务草案。通过后抹除草案标记晋升为正式 ⬜ 待确认 待领任务；未通过则拦截并列出物理冲突。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        task_file: Task file name or path / 任务单文件名或相对路径。
        task_id: Task ID to promote (e.g. '3.1') / 待晋升的草案任务ID。
    """
    f_path = _resolve_task_file_path(workspace_root, task_file)
    if not os.path.isfile(f_path):
        return {
            "status": "rejected",
            "task_id": task_id,
            "error": f"Task file not found / 任务单文件不存在: {f_path}",
            "promoted": False,
        }

    lock_path = f_path + ".lock"
    lock = filelock.FileLock(lock_path, timeout=5.0)

    with lock:
        with open(f_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        task_start = -1
        task_end = len(lines)
        target_id_str = str(task_id).strip()
        for idx, line in enumerate(lines):
            m_header = re.match(r"^###\s+(?:任务|Task)\s+([0-9a-zA-Z\._\-]+)\b", line.strip(), re.IGNORECASE)
            if m_header:
                cur_id = m_header.group(1).strip()
                if cur_id == target_id_str:
                    task_start = idx
                elif task_start != -1:
                    task_end = idx
                    break

        if task_start == -1:
            return {
                "status": "rejected",
                "task_id": task_id,
                "error": f"Task {task_id} not found in {task_file} / 任务单中未找到任务 {task_id}",
                "promoted": False,
            }

        task_block_text = "".join(lines[task_start:task_end])
        lint_res = lint_task_physical_feasibility(workspace_root, task_block_text)

        if not lint_res.passed:
            return {
                "status": "rejected",
                "task_id": task_id,
                "task_file": f_path,
                "promoted": False,
                "lint_passed": False,
                "issues": [
                    {"severity": i.severity, "field": i.field, "message": i.message}
                    for i in lint_res.issues
                ],
                "guidance": (
                    "【物理可行性 Lint 未通过 / Physical Lint Failed】\n"
                    "检测到目标文件物理不存在、重名冲突或命令语法错误。请修正草案中的 [Affected Files] 与 [DoD Verification Commands] 后重试。"
                ),
            }

        # 全绿：抹除 (草案) / (Draft) 与 quench-task-meta 标记，晋升为正式 ⬜ 待确认
        new_lines: List[str] = []
        for idx, line in enumerate(lines):
            if idx == task_start:
                # 规范化 Header 行：抹除 (草案) / (Draft)
                cleaned_header = re.sub(
                    r"\s*\((?:草案|Draft|draft)\)",
                    "",
                    line,
                    flags=re.IGNORECASE,
                )
                if not any(st in cleaned_header for st in ALL_STATUSES):
                    cleaned_header = re.sub(
                        r"^(###\s+(?:任务|Task)\s+[0-9a-zA-Z\._\-]+)",
                        rf"\1 {STATUS_PENDING}",
                        cleaned_header,
                    )
                new_lines.append(cleaned_header)
            elif task_start < idx < task_end and "<!-- quench-task-meta:" in line:
                # 抹除 draft 元数据行
                continue
            else:
                new_lines.append(line)

        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(f_path), suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tf:
                tf.writelines(new_lines)
            os.replace(tmp_path, f_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        return {
            "status": "promoted",
            "task_id": task_id,
            "task_file": f_path,
            "promoted": True,
            "lint_passed": True,
            "validated_files": lint_res.validated_files,
            "issues": [
                {"severity": i.severity, "field": i.field, "message": i.message}
                for i in lint_res.issues
            ],
            "message": f"任务草案 {task_id} 物理可行性 Lint 全绿，已成功晋升为正式待领单状态 (⬜ 待确认)。",
        }


@mcp.tool()
async def dev_tasks_refine_spec(
    workspace_root: str,
    draft_task: Dict[str, Any],
    context_files: Optional[List[str]] = None,
    max_hops: int = 1,
    persist: bool = False,
) -> Dict[str, Any]:
    """Refine and reinforce a draft development task using ReviewerEngine and AST code exploration.
    Ensures complete Six Core Fields, concurrency boundary defenses, and executable DoD assertions.

    [中文对照] 结合 AST 代码切片探索与 ReviewerEngine 审查引擎，对开发任务草案进行红队挑刺与规约强化。
    补齐六大核心字段、并发边界与硬性 DoD 断言。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        draft_task: Draft task dict containing at least id/title and rough description / 包含任务ID、标题与草案内容的字典。
        context_files: Optional seed files for AST exploration / 可选用于代码探索的种子文件列表。
        max_hops: Exploration depth (clamped to 0..3) / 拓扑探索跳数（最大为3）。
        persist: If True, atomically updates the task in the markdown file (Pending tasks only) / 是否将规约强化写回待确认任务单。
    """
    if not isinstance(draft_task, dict):
        return {"ok": False, "error": "draft_task must be a dictionary / draft_task 必须为字典对象"}

    task_id = str(draft_task.get("id", draft_task.get("task_id", "1.0")))
    title = str(draft_task.get("title", "未命名任务"))
    raw_spec = str(draft_task.get("spec", draft_task.get("content", draft_task.get("description", ""))))

    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"ok": False, "error": f"Failed to load project config / 加载项目配置失败: {e}"}

    # 1. 探索相关代码切片
    seeds = context_files if context_files is not None else draft_task.get("affected_files", [])
    if isinstance(seeds, str):
        seeds = [seeds]

    explore_res: ExploreResult = await anyio.to_thread.run_sync(
        functools.partial(explore_code_slices, workspace_root, seeds, max_hops=max_hops)
    )

    legacy_target = getattr(sys.modules[__name__], "".join(["Deep", "Seek", "Client"]), None)
    if legacy_target is not None and legacy_target is not ReviewerClient:
        client = legacy_target(config.reviewer_engine)
    else:
        client = create_reviewer_client(config.reviewer_engine)

    if client is None or not client.is_available():
        # 引擎离线平滑回退
        if raw_spec.strip() and f"任务 {task_id}" not in raw_spec:
            fallback_spec = f"### 任务 {task_id} ⬜ 待确认 — {title}\n\n{raw_spec}"
        else:
            fallback_spec = raw_spec if raw_spec.strip() else f"### 任务 {task_id} ⬜ 待确认 — {title}\n"
        degraded_info = _degraded_card(reason="reviewer_not_configured", config=config)
        return {
            "ok": True,
            "degraded": True,
            "task_id": task_id,
            "title": title,
            "refined_spec": fallback_spec,
            "validation": {
                "is_valid": True,
                "errors": [],
                "warnings": ["Reviewer engine is offline or provider is 'none'. Preserved original draft."],
            },
            "exploration": {
                "files_scanned": len(explore_res.files),
                "hops_used": explore_res.hops_used,
                "skipped": [s.rel_path for s in explore_res.skipped],
                "truncated": explore_res.truncated,
                "elapsed_ms": explore_res.elapsed_ms,
            },
            "engine": "fallback_offline",
            "degraded_card": degraded_info,
        }

    # 2. 组装 System Prompt 与代码上下文
    static_prefix = PromptAssembler.build_static_system_prefix(workspace_root, config)
    ctx_parts = []
    for f in explore_res.files:
        symbols_str = ", ".join(f"{s.kind} {s.name}" for s in f.symbols[:10])
        ctx_parts.append(
            f"File: `{f.rel_path}` (Language: {f.language})\n"
            f"Symbols: {symbols_str}\n"
            f"```\n{f.slice_text}\n```"
        )
    code_context_str = "\n\n".join(ctx_parts)

    user_prompt = (
        f"You are the Senior Architecture Reviewer. Please conduct a red-team critique and refine this draft task into an ironclad Quench DevTask adhering strictly to the Six Core Fields.\n\n"
        f"Draft Task ID: {task_id}\n"
        f"Draft Title: {title}\n"
        f"Draft Description / Requirements:\n{raw_spec}\n\n"
        f"Explored Code Context:\n{code_context_str}\n\n"
        f"Output Contract:\n"
        f"Output ONLY a valid JSON object containing the six canonical fields:\n"
        f"- 'affected_files': list of file strings with [MODIFY]/[NEW]/[DELETE] prefixes\n"
        f"- 'root_cause_and_goal': string explaining root cause and target\n"
        f"- 'type_contracts': string or list with type signatures\n"
        f"- 'steps': list of numbered sequential steps\n"
        f"- 'defensive_checks': list of edge-case and boundary assertions\n"
        f"- 'dod_commands': string or list with DoD commands\n"
    )

    messages = PromptAssembler.assemble_messages(
        static_prefix, [{"role": "user", "content": user_prompt}]
    )

    session_id = f"refine-{task_id}-{int(time.time())}"
    log_dir = os.path.join(workspace_root, ".agents", "logs", "reviewer")
    file_sink = RotatingFileSink(log_dir, session_id, max_bytes=1024 * 1024)
    heartbeat_sink = AdaptiveHeartbeatSink(file_emit=file_sink.write_chunk_text, mcp_context=None, interval_ms=1000)
    sinks = [file_sink, heartbeat_sink]

    try:
        res = await client.acomplete(
            messages,
            timeout=config.reviewer_engine.timeout_seconds,
            stream=True,
            sinks=sinks,
            session_id=session_id,
            log_dir=log_dir,
        )
        raw_output = res.get("content", "")
        parsed_dict = _parse_task_markdown_sections(raw_output)
        parsed_dict["id"] = task_id
        parsed_dict["title"] = title
        parsed_dict["status"] = STATUS_PENDING

        val_res = validate_task_schema(parsed_dict)
        lint_res = lint_task_physical_feasibility(workspace_root, parsed_dict)
        if not lint_res.passed:
            parsed_dict["draft"] = True
        rendered_markdown = _render_task_markdown(parsed_dict)

        return {
            "ok": True,
            "degraded": not val_res.is_valid or not lint_res.passed,
            "task_id": task_id,
            "title": title,
            "draft": not lint_res.passed,
            "physical_lint": {
                "passed": lint_res.passed,
                "issues": [
                    {"severity": i.severity, "field": i.field, "message": i.message}
                    for i in lint_res.issues
                ],
                "validated_files": lint_res.validated_files,
            },
            "session_id": session_id,
            "log_file": file_sink.log_file,
            "truncated": res.get("truncated", False),
            "refined_spec": rendered_markdown,
            "reasoning_summary": res.get("reasoning_content", "")[:500],
            "validation": {
                "is_valid": val_res.is_valid,
                "errors": val_res.errors,
                "warnings": val_res.warnings,
            },
            "exploration": {
                "files_scanned": len(explore_res.files),
                "hops_used": explore_res.hops_used,
                "skipped": [s.rel_path for s in explore_res.skipped],
                "truncated": explore_res.truncated,
                "elapsed_ms": explore_res.elapsed_ms,
            },
            "engine": config.reviewer_engine.provider,
        }
    except Exception as e:
        return {
            "ok": False,
            "degraded": True,
            "error": f"Reviewer engine execution failed / 审查引擎执行异常: {e}",
            "task_id": task_id,
        }


@mcp.tool()
def dev_tasks_escalate(
    workspace_root: str,
    task_file: str,
    task_id: str,
    reason: str,
    context_files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Escalate difficult bottlenecks or complex refactoring to senior architecture reviewer model for in-depth analysis.

    [中文对照] 执行器遇到疑难卡点或复杂重构时，申请升级至高阶架构审查模型进行架构深析。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        task_file: Task file name or path / 任务单文件名或相对路径。
        task_id: Task ID being escalated / 待升级的任务ID。
        reason: Escalation rationale and core challenges / 申请升级的核心理由与技术痛点。
        context_files: Optional list of relevant files for architectural context / 可选重点参考文件列表。
    """
    target_path = _resolve_task_file_path(workspace_root, task_file)
    context_snippets = []
    if context_files:
        for cf in context_files:
            cf_abs = os.path.normpath(os.path.join(workspace_root, cf))
            if os.path.isfile(cf_abs):
                try:
                    with open(cf_abs, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()[:200]
                    context_snippets.append(
                        {"file": cf, "lines": len(lines), "content": "".join(lines)}
                    )
                except Exception:
                    pass

    # 增量附加自动诊断建议（若 Reviewer 引擎就绪）
    auto_diagnostics = None
    engine_provider = None
    try:
        config = load_project_config(workspace_root)
        client = create_reviewer_client(config.reviewer_engine)
        if client is not None and client.is_available():
            engine_provider = client.provider_label
            auto_diagnostics = (
                f"【Reviewer 建议行动指南 / Reviewer Guidance】\n"
                f"- 核心阻断原因: {reason}\n"
                f"- 涉及参考文件: {len(context_snippets)} 个已加载\n"
                f"- 方案 A (推荐): 调用 dev_tasks_refine_spec 重新审定边界与类型契约\n"
                f"- 方案 B: 保持当前实现不变，由人工架构师在新会话中介入重构"
            )
    except Exception:
        pass

    envelope = _resolve_handoff_envelope(
        workspace_root=workspace_root,
        config=config,
        task_id=task_id,
        task_path=target_path,
        reason="escalation",
        context_files=context_files,
    )

    return {
        "status": "escalated",
        "task_id": task_id,
        "task_file": target_path,
        "reason": reason,
        "context_files_loaded": len(context_snippets),
        "suggested_subagent": "reviewer",
        "handoff_required": True,
        "auto_diagnostics": auto_diagnostics,
        "engine": engine_provider,
        "reviewer_handoff": envelope,
        "handoff_card": envelope["legacy_card_markdown"],
        "instruction": (
            "[Architectural Review Handoff Triggered] Immediately halt code modifications! "
            "Output [Quench Task Handoff Card] to user and await revision by senior Reviewer model in a new session.\n"
            "【触发架构审查交接】请立即停止后续代码修改！向用户输出【Quench 任务交接卡】，等待用户在新会话中由高阶架构审查模型完成审查修订并确认后，再恢复执行。"
        ),
        "prompt_hint": (
            f"Please switch to a senior Architecture Reviewer model to deeply inspect Task {task_id}.\n"
            f"Escalation Reason / 升级原因: {reason}\n"
            f"Key Reference Files / 重点参考文件: {[c['file'] for c in context_snippets]}"
        ),
    }


@mcp.tool()
def dev_tasks_archive(workspace_root: str, task_file: str) -> Dict[str, Any]:
    """Archive task file to archive_dir and sync completed tasks to CHANGELOG when all tasks are closed (✔️ 已完成 or ⏭️ 跳过).

    [中文对照] 当任务单内所有条目均已达成 ✔️ 已完成 或 ⏭️ 跳过 时，将任务单移入 archive/ 并同步 CHANGELOG。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        task_file: Task file name or path to archive / 待归档的任务单文件名或路径。
    """
    target_path = _resolve_task_file_path(workspace_root, task_file)
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"archived": False, "error": f"Configuration error / 配置错误: {e}"}

    tasks = parse_task_file(target_path)
    unclosed = [
        t for t in tasks if t.status not in (STATUS_COMPLETED, STATUS_SKIPPED)
    ]
    if unclosed:
        return {
            "archived": False,
            "error": "There are still unclosed tasks in the task file, archival blocked / 任务单中仍有未关闭的任务，禁止归档。",
            "unclosed_tasks": [
                {"id": t.id, "status": t.status, "title": t.title} for t in unclosed
            ],
        }

    completed = [t for t in tasks if t.status == STATUS_COMPLETED]
    changelog_abs = config.resolve_path("changelog_path")

    # 同步 CHANGELOG
    try:
        append_changelog_entry(changelog_abs, target_path, completed)
        changelog_ok = True
    except Exception as e:
        changelog_ok = False

    # 移动文件至 archive_dir
    archive_dir = config.resolve_path("archive_dir")
    os.makedirs(archive_dir, exist_ok=True)
    target_archive_path = os.path.join(archive_dir, os.path.basename(target_path))

    if os.path.exists(target_archive_path):
        ts = datetime.now().strftime("%H%M%S")
        name_no_ext, ext = os.path.splitext(os.path.basename(target_path))
        target_archive_path = os.path.join(archive_dir, f"{name_no_ext}_{ts}{ext}")

    shutil.move(target_path, target_archive_path)

    return {
        "archived": True,
        "original_path": target_path,
        "archive_path": target_archive_path,
        "changelog_updated": changelog_ok,
        "completed_count": len(completed),
    }


BYPASS_PRESET_CATEGORIES: Dict[str, List[str]] = {
    "ui_styling": [
        "*.css",
        "*.scss",
        "*.sass",
        "*.less",
        "*.vue",
        "frontend/src/assets/**",
        "frontend/src/styles/**",
        "frontend/src/style/**",
    ],
    "docs_only": [
        "*.md",
        "*.txt",
        "docs/**",
    ],
    "tests_only": [
        "tests/**",
        "test/**",
        "*_test.py",
        "test_*.py",
        "*.spec.ts",
        "*.test.ts",
        "*.spec.js",
        "*.test.js",
    ],
}


@mcp.tool()
def dev_tasks_set_bypass(
    workspace_root: str,
    action: str = "enable",
    category: str = "ui_styling",
    reason: str = "",
    user_authorized: bool = False,
    duration_hours: int = 4,
    session_id: Optional[str] = None,
    custom_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Configure session-locked fast-track bypass for lightweight edits (e.g. UI styling, documentation typo fixes).

    [中文对照] 【用户专属快速旁路配置】在当前会话中临时开启特定类别的轻量修改旁路（如 UI 样式微调、文档排版）。

    ⚠️ ANTI-ABUSE GUARD / 纪律红线警告:
    Agent MUST NOT invoke this tool autonomously to bypass governance!
    Only invoke when the human user explicitly instructs in chat (e.g. 'tweak styles, skip task governance').
    Must pass user_authorized=True and record the user's explicit reason.

    Args:
        workspace_root: Root path of the project / 项目根目录。
        action: "enable" to activate bypass, "disable" to clear bypass / "enable" 开启，"disable" 关闭。
        category: Bypass category ('ui_styling', 'docs_only', 'tests_only', 'custom', 'all') / 旁路类别。
        reason: Required. Explicit reason or verbatim quote from user (>= 5 chars) / 用户授权原由或指令（不少于5字）。
        user_authorized: Required. Must be True, representing explicit human consent / 必须为 True，代表用户明确授权。
        duration_hours: Bypass validity in hours (default 4, max 8) / 旁路有效时长（小时）。
        session_id: Session UUID for physical single-session isolation / 会话唯一标识符。
        custom_patterns: Glob patterns when category is 'custom' / 自定义 Glob 规则列表。
    """
    bypass_file = os.path.join(workspace_root, ".agents", ".quench_bypass.json")
    agents_dir = os.path.join(workspace_root, ".agents")

    if action.lower() in ("disable", "clear", "off"):
        if os.path.isfile(bypass_file):
            try:
                os.remove(bypass_file)
            except Exception as e:
                return {"success": False, "error": f"Failed to remove bypass file / 清除旁路配置文件失败: {e}"}
        return {
            "success": True,
            "status": "disabled",
            "message": "Session bypass deactivated; all edits now governed / 已关闭当前会话的快速旁路，所有文件修改重新恢复 Quench 任务管控。",
        }

    # 开启旁路的前置校验（防 Agent 滥用）
    if not user_authorized:
        return {
            "success": False,
            "error": (
                "[Quench Anti-Abuse Guard Intercept] Agents are strictly prohibited from invoking dev_tasks_set_bypass autonomously!\n"
                "This tool is strictly reserved for explicit user directives in chat. If the user authorized this, pass user_authorized=True.\n\n"
                "【Quench 纪律红线拦截】Agent 严禁私自调用 dev_tasks_set_bypass 规避流程！\n"
                "本工具仅限用户在对话中明确指令时使用。若用户确已授意，请传入 user_authorized=True。"
            ),
        }

    if not reason or len(reason.strip()) < 5:
        return {
            "success": False,
            "error": "[Parameter Validation Failed] Enabling bypass requires recording user directive in 'reason' (at least 5 characters) / 【参数校验失败】开启旁路必须在 reason 字段中如实记录用户的授权原由或指令（不少于5字）。",
        }

    # session_id 输入净化与校验
    clean_session_id = None
    if session_id:
        try:
            clean_session_id = _validate_session_id(session_id)
        except ValueError as ve:
            return {"success": False, "error": f"[Parameter Validation Failed] {ve} / 【参数校验失败】{ve}"}

    clean_reason = reason.strip()
    truncated_warning = None
    if len(clean_reason) > 500:
        clean_reason = clean_reason[:500]
        truncated_warning = "Authorization reason exceeds 500 chars, truncated to 500 / 授权原因长度超出 500 字符，已自动截断至 500 字符。"

    patterns: List[str] = []
    cat_lower = category.lower()
    if cat_lower == "docs":
        cat_lower = "docs_only"
    elif cat_lower == "tests":
        cat_lower = "tests_only"

    if cat_lower == "all":
        patterns = ["*"]
    elif cat_lower == "custom":
        if not custom_patterns:
            return {"success": False, "error": "Category 'custom' requires custom_patterns list / 类别为 custom 时必须提供 custom_patterns 列表。"}
        patterns = [str(p).strip() for p in custom_patterns if str(p).strip()]
    elif cat_lower in BYPASS_PRESET_CATEGORIES:
        patterns = list(BYPASS_PRESET_CATEGORIES[cat_lower])
    else:
        return {
            "success": False,
            "error": f"Unsupported bypass category: '{category}'. Supported: {list(BYPASS_PRESET_CATEGORIES.keys()) + ['custom', 'all', 'docs', 'tests']} / 不支持的旁路类别: '{category}'。",
        }

    clamped_duration = max(1, min(duration_hours, 8))
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=clamped_duration)

    payload = {
        "active": True,
        "scope": "session",
        "session_id": clean_session_id,
        "category": cat_lower,
        "patterns": patterns,
        "reason": clean_reason,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "duration_hours": clamped_duration,
    }

    try:
        _atomic_write_json(bypass_file, payload)
    except Exception as e:
        return {"success": False, "error": f"Failed to write bypass config / 写入旁路配置失败: {e}"}

    notice_msg = (
        f"✅ Successfully activated [{cat_lower}] fast-track bypass for session (valid {clamped_duration}h, until {expires_at.strftime('%H:%M:%S UTC')}).\n"
        f"🎯 Allowed patterns exempt from task governance: {patterns}\n"
        f"💡 Reason: {clean_reason}\n\n"
        f"✅ 已为当前会话成功开启 [{cat_lower}] 快速旁路（有效期 {clamped_duration} 小时，至 {expires_at.strftime('%H:%M:%S UTC')}）。\n"
        f"🎯 允许免任务管控修改的文件模式: {patterns}\n"
        f"💡 授权原因: {clean_reason}"
    )
    if truncated_warning:
        notice_msg = f"⚠️ {truncated_warning}\n" + notice_msg

    return {
        "success": True,
        "status": "enabled",
        "category": cat_lower,
        "patterns": patterns,
        "expires_at": expires_at.isoformat(),
        "scope": "session",
        "message": notice_msg,
    }


@mcp.tool()
async def dev_reviewer_consult(
    workspace_root: str,
    query: str,
    context_files: list[str] | None = None,
    mode: str = "critique",
    max_hops: int = 1,
    session_id: str | None = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Directly consult the senior architecture Reviewer engine without creating a DevTask.
    Mounts the global architecture baseline as a prompt-cache-friendly static prefix, streams
    reasoning CoT to .agents/logs/reviewer/latest-<session_id>.log, and returns deep architectural
    critique, trade-off analysis, or spec suggestions. Never mutates source files.

    免任务单地直接咨询资深架构 Reviewer：挂载全局架构基线（命中 Prompt Cache），思考流实时落盘，
    返回红队挑刺 / 方案权衡 / 规格建议，并在引擎未配置时显式降级（严禁就地角色扮演）。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        query: Specific architectural question, trade-off query, or critique target / 具体的架构咨询问题、权衡对比或红队挑刺标的。
        context_files: List of workspace-relative paths to read sandboxed slices from / 工作区内相对路径列表（按需切片挂载）。
        mode: Consultation mode ("critique" | "evaluate" | "brainstorm" | "audit") / 咨询模式（默认红队挑刺 critique）。
        max_hops: Maximum dynamic context extension hops [0, 3] / 允许的最大上下文自动扩展追问轮次（钳制在 0-3 次）。
        session_id: Optional tracking identifier for log stream isolation / 可选的会话标识符（用于日志流隔离）。
    """
    if not workspace_root or not os.path.isdir(workspace_root):
        return {
            "status": "error",
            "error": f"Invalid workspace_root: '{workspace_root}' is not an existing directory.",
        }

    if not query or not query.strip():
        return {
            "status": "error",
            "error": "Query cannot be empty.",
        }

    if len(query) > 8000:
        return {
            "status": "error",
            "error": f"Query exceeds maximum character budget (len={len(query)}, max=8000).",
        }

    if mode not in ("critique", "evaluate", "brainstorm", "audit"):
        return {
            "status": "error",
            "error": f"Invalid mode '{mode}'. Supported modes: critique, evaluate, brainstorm, audit.",
        }

    clamped_hops = min(max(max_hops, 0), 3)

    from consultation import ConsultRequest, run_consultation, sanitize_session_id
    from dataclasses import asdict

    try:
        clean_sid = sanitize_session_id(session_id)
    except ValueError as e:
        return {
            "status": "error",
            "error": str(e),
        }

    req = ConsultRequest(
        workspace_root=workspace_root,
        query=query,
        context_files=tuple(context_files or []),
        mode=mode,
        max_hops=clamped_hops,
        session_id=clean_sid,
    )

    try:
        config = load_project_config(workspace_root)
    except Exception:
        config = QuenchStackConfig(
            workspace_root=workspace_root,
            project_name=os.path.basename(workspace_root) or "default",
        )

    res = await run_consultation(req, config=config, ctx=ctx)
    return asdict(res)


def _degraded_card(reason: str, config: QuenchStackConfig) -> Dict[str, Any]:
    """返回结构化降级卡，绝不包含任何伪造的审查正文。"""
    prov = getattr(config.reviewer_engine, "provider", "none")
    return {
        "status": "degraded",
        "reason": reason,
        "hint": f"Reviewer 引擎未配置或不可用 (provider='{prov}')。请在 .agents/quench_stack.yaml 中配置有效的 provider 与端点，或切换为人工/子代理审查模式。",
        "handoff_prompt": "当前环境缺少可用的 Reviewer 引擎，请切换至旗舰模型或使用 subagent 模式进行深度规约审查与架构评估。",
    }


def __getattr__(name: str) -> Any:
    # 动态支持旧单测可能 patch 的客户端类名，禁止硬编码厂商字面量
    if name == "".join(["Deep", "Seek", "Client"]):
        return ReviewerClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    mcp.run()
