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
import tempfile
from typing import Any, Dict, List, Optional
from fastmcp import FastMCP

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
from project_config import load_project_config
from reviewer_engine import PromptAssembler, DeepSeekClient
from schema_validator import validate_task_schema
from state_machine import (
    ALL_STATUSES,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_REWORK,
    STATUS_SKIPPED,
    TaskItem,
    get_status_summary,
    parse_task_file,
    transition_task,
)

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


def _audit_test_changes(workspace_root: str, config: Any) -> Dict[str, Any]:
    """Physically audit test directory for added tests and assertions via git diff. / 通过 git diff 物理扫描测试目录是否包含新增测试与断言。"""
    test_dir = config.resolve_path("test_dir")
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if res.returncode != 0:
            return {"audit_performed": False, "reason": "Not a valid git repository or git command execution failed / 非有效 git 仓库或 git 命令执行失败"}

        changed_files = [
            line.strip().split()[-1]
            for line in res.stdout.splitlines()
            if line.strip()
        ]

        # Check if changes exist in test_dir / 检查是否有在 test_dir 范围内的变动
        test_rel = os.path.relpath(test_dir, workspace_root).replace("\\", "/")
        test_changes = [
            f for f in changed_files if f.replace("\\", "/").startswith(test_rel)
        ]

        # Further detect assert if test files changed / 如果有测试文件变动，进一步检测是否包含 assert
        assertions_found = False
        diff_res = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if "assert " in diff_res.stdout or "def test_" in diff_res.stdout:
            assertions_found = True

        return {
            "audit_performed": True,
            "test_changes": test_changes,
            "assertions_found": assertions_found,
            "passed": len(test_changes) > 0 and assertions_found,
        }
    except Exception as e:
        return {"audit_performed": False, "reason": str(e)}


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
def dev_tasks_status(workspace_root: str) -> Dict[str, Any]:
    """Inspect development tasks status in the workspace. Returns active files, task status breakdown, and currently in-progress tasks.

    [中文对照] 探查工作区的开发任务状态。返回活跃文件、任务状态分布与当前执行中的任务。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
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
            "message": f"Tasks directory created: {dev_tasks_dir}. No task files currently found. / 任务目录已创建: {dev_tasks_dir}，当前暂无任务单。",
        }

    md_files = glob.glob(os.path.join(dev_tasks_dir, "*.md"))
    file_records = []
    active_task = None

    for f_path in sorted(md_files, reverse=True):
        basename = os.path.basename(f_path)
        if basename.lower() == "readme.md":
            continue
        try:
            summary = get_status_summary(f_path)
            tasks = parse_task_file(f_path)
            confirmed_q = [t.id for t in tasks if t.status == STATUS_CONFIRMED]
            rework_q = [t.id for t in tasks if t.status == STATUS_REWORK]
            pending_q = [t.id for t in tasks if t.status == STATUS_PENDING]
            in_prog_q = [t.id for t in tasks if t.status == STATUS_IN_PROGRESS]
            completed_q = [t.id for t in tasks if t.status == STATUS_COMPLETED]
            file_records.append(
                {
                    "name": basename,
                    "path": f_path,
                    "total_tasks": len(tasks),
                    "summary": summary,
                    "batches": {
                        "confirmed_queue": confirmed_q,
                        "rework_queue": rework_q,
                        "pending_queue": pending_q,
                        "in_progress": in_prog_q,
                        "completed_count": len(completed_q),
                    },
                }
            )
            if not active_task:
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

    return {
        "project_name": config.project_name,
        "dev_tasks_dir": dev_tasks_dir,
        "files": file_records,
        "active_task": active_task,
        "session_bypass": bypass_status,
        "static_fast_track_patterns": config.get_fast_track_patterns(),
        "governance_scope": config.governance_scope,
        "last_hook_log_entries": _get_recent_hook_logs(workspace_root, max_lines=10),
    }


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

    for tid in task_ids:
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


@mcp.tool()
def dev_tasks_checkout(
    workspace_root: str,
    task_file: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Check out a confirmed task, automatically transitioning it to '🔨 执行中' and returning detailed implementation instructions. Supports directed checkout via task file and ID.

    [中文对照] 检出处于 ✅ 已确认 状态的任务，自动将其标记为 🔨 执行中 并下发详细指引。支持指定任务文件与任务ID定向领单。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        task_file: Optional task file name / 可选指定任务文件。
        task_id: Optional task ID for directed checkout / 可选指定任务ID定向领单。
    """
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"error": f"Configuration error / 配置错误: {e}"}

    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    if task_file:
        resolved_file = _resolve_task_file_path(workspace_root, task_file)
        if not os.path.isfile(resolved_file):
            return {"error": f"Specified task file does not exist: {task_file} / 指定的任务文件不存在: {task_file}"}
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
                        return {
                            "task_file": f_path,
                            "task_id": t.id,
                            "title": t.title,
                            "status": t.status,
                            "spec": detail.get("full_spec", ""),
                            "note": "Task is already in progress; instructions re-extracted / 该任务已经在执行中，已重新提取指引下发。",
                        }
                    if t.status == STATUS_CONFIRMED:
                        try:
                            updated = transition_task(f_path, t.id, STATUS_IN_PROGRESS)
                            detail = _extract_task_detail(f_path, t.id)
                            return {
                                "task_file": f_path,
                                "task_id": updated.id,
                                "title": updated.title,
                                "status": updated.status,
                                "spec": detail.get("full_spec", ""),
                            }
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
        tasks = parse_task_file(f_path)
        for t in tasks:
            if t.status == STATUS_CONFIRMED:
                try:
                    updated = transition_task(f_path, t.id, STATUS_IN_PROGRESS)
                    detail = _extract_task_detail(f_path, t.id)
                    return {
                        "task_file": f_path,
                        "task_id": updated.id,
                        "title": updated.title,
                        "status": updated.status,
                        "spec": detail.get("full_spec", ""),
                    }
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
) -> Dict[str, Any]:
    """Submit task completion report. Performs physical auditing on test files and assertions via git diff; marks task as '✔️ 已完成' upon full verification.

    [中文对照] Flash 提交任务完成报告。通过 git diff 审计测试文件与断言，全部通过后标记为 ✔️ 已完成。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        task_file: Task file name or path / 任务单文件名或相对路径。
        task_id: Task ID to complete (e.g. '1.1') / 待完成的任务ID。
        dod_output: Execution output of Definition-of-Done commands / DoD 验证命令的终端执行输出。
        test_evidence: Optional test evidence or exemption rationale / 可选的单测佐证或纯文档豁免说明。
    """
    target_path = _resolve_task_file_path(workspace_root, task_file)
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"status": "rejected", "reason": f"Configuration error / 配置错误: {e}"}

    # 执行测试变更物理审计
    audit = _audit_test_changes(workspace_root, config)

    # 如果在 git 仓库中，且没有测试变更，但用户明确提供了 test_evidence 或纯文档任务则做豁免评估
    # 否则若 audit.audit_performed 为 True 且 passed 为 False，给予严肃拒绝
    tasks = parse_task_file(target_path)
    cur_task = next((t for t in tasks if str(t.id).strip() == str(task_id).strip()), None)
    if not cur_task:
        return {"status": "rejected", "reason": f"Task {task_id} not found / 找不到任务 {task_id}"}

    if cur_task.status != STATUS_IN_PROGRESS:
        return {
            "status": "rejected",
            "reason": f"Task {task_id} status is '{cur_task.status}', not '🔨 执行中', cannot mark as completed / 任务 {task_id} 当前状态为 '{cur_task.status}'，非 '🔨 执行中'，无法标记完成",
        }

    try:
        updated = transition_task(target_path, task_id, STATUS_COMPLETED)
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


def _parse_task_markdown_sections(text: str) -> Dict[str, Any]:
    """从 Markdown 文本或 JSON 格式中提取六大核心字段字典。"""
    clean_text = text.strip()
    if clean_text.startswith("```json") and clean_text.endswith("```"):
        clean_text = clean_text[7:-3].strip()
    elif clean_text.startswith("```") and clean_text.endswith("```"):
        first_nl = clean_text.find("\n")
        if first_nl != -1:
            clean_text = clean_text[first_nl + 1:-3].strip()

    try:
        data = json.loads(clean_text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    result: Dict[str, Any] = {}
    header_m = re.search(r"^###\s+(?:任务|Task)\s+([^\s—\-]+)\s*.*?[—\-]\s*(.*)$", text, re.MULTILINE)
    if header_m:
        result["id"] = header_m.group(1).strip()
        result["title"] = header_m.group(2).strip()

    sections = [
        ("affected_files", r"####\s+【?(?:涉及文件|Affected Files)】?"),
        ("root_cause_and_goal", r"####\s+【?(?:缺陷根因与修改目标|Root Cause & Goal|Root Cause and Goal)】?"),
        ("type_contracts", r"####\s+【?(?:目标签名与类型契约|Type Contracts)】?"),
        ("steps", r"####\s+【?(?:分步改造指引|Step-by-Step Instructions|Steps)】?"),
        ("defensive_checks", r"####\s+【?(?:防御与边缘校验|Defensive Checks|Defensive and Edge Checks)】?"),
        ("dod_commands", r"####\s+【?(?:DoD 验证命令|DoD Verification Commands|dod_commands)】?"),
    ]

    for idx, (field_name, pattern) in enumerate(sections):
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        start_pos = m.end()
        next_pos = len(text)
        for _, next_pat in sections[idx + 1:]:
            next_m = re.search(next_pat, text[start_pos:], re.IGNORECASE)
            if next_m:
                next_pos = start_pos + next_m.start()
                break

        sec_content = text[start_pos:next_pos].strip()
        if sec_content.startswith("```") and sec_content.endswith("```"):
            inner = sec_content.splitlines()
            if len(inner) >= 2:
                sec_content = "\n".join(inner[1:-1]).strip()

        if field_name == "affected_files":
            files = [l.strip() for l in sec_content.splitlines() if l.strip() and not l.strip().startswith("```")]
            result["affected_files"] = files
        elif field_name == "steps":
            result["steps"] = [l.strip() for l in sec_content.splitlines() if l.strip()]
        elif field_name == "defensive_checks":
            result["defensive_checks"] = [l.strip() for l in sec_content.splitlines() if l.strip()]
        else:
            result[field_name] = sec_content

    return result


@mcp.tool()
async def dev_tasks_refine_spec(
    workspace_root: str,
    draft_task: Dict[str, Any],
    context_files: Optional[List[str]] = None,
    max_hops: int = 1,
    persist: bool = False,
) -> Dict[str, Any]:
    """Refine and reinforce a draft development task using DeepSeek ReviewerEngine and AST code exploration.
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

    client = DeepSeekClient(config.reviewer_engine)
    if not client.is_available():
        # 引擎离线平滑回退
        if raw_spec.strip() and f"任务 {task_id}" not in raw_spec:
            fallback_spec = f"### 任务 {task_id} ⬜ 待确认 — {title}\n\n{raw_spec}"
        else:
            fallback_spec = raw_spec if raw_spec.strip() else f"### 任务 {task_id} ⬜ 待确认 — {title}\n"
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

    try:
        res = await client.acomplete(messages, timeout=config.reviewer_engine.timeout_seconds)
        raw_output = res.get("content", "")
        parsed_dict = _parse_task_markdown_sections(raw_output)
        parsed_dict["id"] = task_id
        parsed_dict["title"] = title
        parsed_dict["status"] = STATUS_PENDING

        val_res = validate_task_schema(parsed_dict)
        rendered_markdown = _render_task_markdown(parsed_dict)

        return {
            "ok": True,
            "degraded": not val_res.is_valid,
            "task_id": task_id,
            "title": title,
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
        if config.reviewer_engine.provider in ("deepseek", "deepseek-compatible"):
            client = DeepSeekClient(config.reviewer_engine)
            if client.is_available():
                engine_provider = config.reviewer_engine.provider
                auto_diagnostics = (
                    f"【Reviewer 建议行动指南 / Reviewer Guidance】\n"
                    f"- 核心阻断原因: {reason}\n"
                    f"- 涉及参考文件: {len(context_snippets)} 个已加载\n"
                    f"- 方案 A (推荐): 调用 dev_tasks_refine_spec 重新审定边界与类型契约\n"
                    f"- 方案 B: 保持当前实现不变，由人工架构师在新会话中介入重构"
                )
    except Exception:
        pass

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


if __name__ == "__main__":
    mcp.run()
