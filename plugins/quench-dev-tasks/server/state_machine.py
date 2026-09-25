# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional
import filelock

try:
    from .manifest import (
        reconcile_workspace,
        get_baseline_path,
        load_baseline_snapshot,
        reconcile_workspace_against_whitelist,
    )
except (ImportError, ValueError):
    from manifest import (
        reconcile_workspace,
        get_baseline_path,
        load_baseline_snapshot,
        reconcile_workspace_against_whitelist,
    )

STATUS_PENDING = "⬜ 待确认"
STATUS_CONFIRMED = "✅ 已确认"
STATUS_IN_PROGRESS = "🔨 执行中"
STATUS_COMPLETED = "✔️ 已完成"
STATUS_SKIPPED = "⏭️ 跳过"
STATUS_REWORK = "🔄 需返工"

ALL_STATUSES = [
    STATUS_PENDING,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_SKIPPED,
    STATUS_REWORK,
]

VALID_TRANSITIONS: Dict[str, List[str]] = {
    STATUS_PENDING: [STATUS_CONFIRMED, STATUS_SKIPPED, STATUS_REWORK],
    STATUS_CONFIRMED: [STATUS_IN_PROGRESS, STATUS_PENDING, STATUS_SKIPPED, STATUS_REWORK],
    # 状态机防绕行守卫：STATUS_CONFIRMED 严格保留给 dev_tasks_reclaim 独占回收通道使用，禁止外部通过 dev_tasks_confirm 直接流转。
    STATUS_IN_PROGRESS: [STATUS_COMPLETED, STATUS_REWORK, STATUS_CONFIRMED],
    STATUS_REWORK: [STATUS_IN_PROGRESS, STATUS_CONFIRMED, STATUS_PENDING, STATUS_SKIPPED],
    STATUS_COMPLETED: [STATUS_REWORK, STATUS_PENDING],
    STATUS_SKIPPED: [STATUS_PENDING, STATUS_CONFIRMED],
}


class StateMachineError(Exception):
    """Base exception for Quench state machine. / 状态机基础异常。"""
    pass


class TaskNotFoundError(StateMachineError):
    """Task ID not found in file. / 任务 ID 未找到。"""
    pass


class InvalidTransitionError(StateMachineError):
    """Invalid state transition error. / 非法状态流转异常。"""
    pass


class ScopeViolationError(StateMachineError):
    """Raised when physical scope reconciliation detects modifications outside whitelist. / 当工作树对账检测到白名单外未授权改动时抛出。"""
    pass


@dataclass
class TaskItem:
    id: str              # e.g. "1.1" or "1"
    title: str           # Task title / 标题文本
    status: str          # Canonical status string / 状态字符串，如 "⬜ 待确认"
    line_number: int     # Line number (0-indexed) / 行号
    raw_line: str        # Raw line text / 原始行内容


EMOJI_STATUS_OPTIONS = [
    r"⬜\s*(?:待确认|Pending)",
    r"✅\s*(?:已确认|Confirmed)",
    r"🔨\s*(?:执行中|In[-_ ]?Progress)",
    r"✔️\s*(?:已完成|Completed)",
    r"✔\s*(?:已完成|Completed)",
    r"⏭️\s*(?:跳过|Skipped)",
    r"⏭\s*(?:跳过|Skipped)",
    r"🔄\s*(?:需返工|Rework)",
    r"待确认",
    r"已确认",
    r"执行中",
    r"已完成",
    r"跳过",
    r"需返工",
    r"Pending",
    r"Confirmed",
    r"In[-_ ]?Progress",
    r"Completed",
    r"Skipped",
    r"Rework",
]

STATUS_REGEX_PART = "|".join(EMOJI_STATUS_OPTIONS)

TASK_HEADER_PATTERN = re.compile(
    rf"^###\s+(?:任务|Task)\s+([0-9a-zA-Z\._\-]+)\s*[:—\-]?\s*({STATUS_REGEX_PART})\s*[:—\-]?\s*(.*)$",
    re.IGNORECASE,
)


def _normalize_status(status_str: str) -> str:
    """Normalize status string (supports emoji, whitespace variants, English and Chinese). / 标准化任务状态字符串（支持中英双语与各类空格Emoji变体）。"""
    s = status_str.strip()
    for standard in ALL_STATUSES:
        if standard in s or standard.replace(" ", "") in s.replace(" ", ""):
            return standard
        key = standard.split(" ")[-1]
        if key in s:
            return standard

    # English aliases mapping
    s_lower = s.lower()
    if "pending" in s_lower:
        return STATUS_PENDING
    if "confirmed" in s_lower:
        return STATUS_CONFIRMED
    if "progress" in s_lower:
        return STATUS_IN_PROGRESS
    if "completed" in s_lower or "done" in s_lower:
        return STATUS_COMPLETED
    if "skipped" in s_lower or "skip" in s_lower:
        return STATUS_SKIPPED
    if "rework" in s_lower:
        return STATUS_REWORK

    return s


def parse_task_file(filepath: str) -> List[TaskItem]:
    """Parse Markdown task file, extracting all task items and their current statuses. / 解析 Markdown 任务文件，提取所有任务条目及其当前状态。"""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Task file not found / 任务文件不存在: {filepath}")

    tasks: List[TaskItem] = []
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for idx, line in enumerate(lines):
        m = TASK_HEADER_PATTERN.match(line.strip())
        if m:
            t_id = m.group(1).strip()
            raw_status = m.group(2).strip()
            title = m.group(3).strip()
            norm_status = _normalize_status(raw_status)
            tasks.append(
                TaskItem(
                    id=t_id,
                    title=title,
                    status=norm_status,
                    line_number=idx,
                    raw_line=line,
                )
            )

    return tasks


def extract_task_whitelist(task_file_content: str, task_id: str) -> list[str]:
    """Extract affected files whitelist from task markdown content."""
    tid_pattern = re.escape(str(task_id).strip())
    pattern = re.compile(
        rf"###\s+(?:任务|Task)\s+{tid_pattern}\s+.*?####\s+(?:【涉及文件】|\[Affected Files\]|【Affected Files】)\s*```(.*?)```",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(task_file_content)
    whitelist: list[str] = []
    if m:
        raw_block = m.group(1).strip()
        for line in raw_block.splitlines():
            line = line.strip()
            if not line:
                continue
            cleaned = re.sub(r"^\[(MODIFY|NEW|DELETE|RENAME)\]\s*", "", line).strip()
            cleaned = cleaned.split("（")[0].split("(")[0].strip()
            if cleaned:
                whitelist.append(cleaned.replace("\\", "/"))
    return whitelist


def _verify_scope_reconciliation(
    filepath: str,
    task_id: str,
    workspace_root: Optional[str] = None,
) -> None:
    """Pre-transition check: verify that all physical workspace edits adhere to whitelist."""
    if workspace_root is None:
        cand = os.path.dirname(os.path.abspath(filepath))
        while cand and cand != os.path.dirname(cand):
            if os.path.exists(os.path.join(cand, ".agents")) or os.path.exists(
                os.path.join(cand, ".git")
            ):
                workspace_root = cand
                break
            cand = os.path.dirname(cand)
        if not workspace_root:
            workspace_root = os.getcwd()

    ws = os.path.realpath(os.path.abspath(workspace_root))
    baseline_path = get_baseline_path(ws, task_id)
    if not os.path.isfile(baseline_path):
        return

    snapshot = load_baseline_snapshot(baseline_path)
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    whitelist = extract_task_whitelist(content, task_id)
    default_unmanaged = [".agents/**", "docs/**", "*.md"]
    unmanaged = list(default_unmanaged)
    try:
        from project_config import load_project_config

        cfg = load_project_config(ws)
        if isinstance(cfg.governance_scope, dict):
            configured_unmanaged = cfg.governance_scope.get("unmanaged_paths", [])
            for pat in configured_unmanaged:
                if pat not in unmanaged:
                    unmanaged.append(pat)
    except Exception:
        pass

    report = reconcile_workspace_against_whitelist(
        workspace_root=ws,
        snapshot=snapshot,
        whitelist_paths=whitelist,
        unmanaged_patterns=unmanaged,
        budget_ms=2000.0,
    )

    if report.verdict == "deny":
        violating_str = ", ".join(report.violating_files)
        raise ScopeViolationError(
            f"Physical scope reconciliation denied for task {task_id}: modified files [{violating_str}] outside declared whitelist {whitelist}. / "
            f"任务 {task_id} 物理对账拦截：改动文件 [{violating_str}] 超出任务单声明的涉及文件白名单。"
        )
    elif report.verdict == "degraded":
        raise ScopeViolationError(
            f"Physical scope reconciliation degraded for task {task_id} ({report.degraded_reason}). Fail-closed. / "
            f"任务 {task_id} 物理对账超时降级阻断：{report.degraded_reason}。根据安全规则严格闭环阻断。"
        )


def transition_task(
    filepath: str,
    task_id: str,
    new_status: str,
    timeout: float = 5.0,
    workspace_root: Optional[str] = None,
) -> TaskItem:
    """Atomically transition task status with filelock: read -> validate -> replace -> write back. / 原子化状态转换：读取→校验合法性→替换写回。带 filelock 排他锁。"""
    norm_new = _normalize_status(new_status)
    if norm_new not in ALL_STATUSES:
        raise InvalidTransitionError(f"Unknown target status '{new_status}', valid: {ALL_STATUSES} / 未知目标状态 '{new_status}'，合法状态: {ALL_STATUSES}")

    lock_path = filepath + ".lock"
    lock = filelock.FileLock(lock_path, timeout=timeout, is_singleton=True)

    with lock:
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Task file disappeared after acquiring lock / 持有锁后发现任务文件不存在: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        target_item: Optional[TaskItem] = None
        target_idx = -1

        for idx, line in enumerate(lines):
            m = TASK_HEADER_PATTERN.match(line.strip())
            if m and m.group(1).strip() == str(task_id).strip():
                t_id = m.group(1).strip()
                raw_status = m.group(2).strip()
                title = m.group(3).strip()
                target_item = TaskItem(
                    id=t_id,
                    title=title,
                    status=_normalize_status(raw_status),
                    line_number=idx,
                    raw_line=line,
                )
                target_idx = idx
                break

        if not target_item:
            raise TaskNotFoundError(f"Task ID '{task_id}' not found in file {filepath} / 未在文件 {filepath} 中找到任务 ID '{task_id}'")

        cur_status = target_item.status
        if cur_status == norm_new:
            return target_item

        allowed = VALID_TRANSITIONS.get(cur_status, [])
        if norm_new not in allowed:
            raise InvalidTransitionError(
                f"Task {task_id} current status '{cur_status}' cannot transition to '{norm_new}'. Allowed: {allowed} / "
                f"任务 {task_id} 当前状态为 '{cur_status}'，不允许流转至 '{norm_new}'。合法路径: {allowed}"
            )

        # Physical scope reconciliation gate before completing or reworking
        if norm_new in (STATUS_COMPLETED, STATUS_REWORK):
            _verify_scope_reconciliation(filepath, target_item.id, workspace_root)

        old_line = lines[target_idx]
        new_line = old_line
        m_curr = TASK_HEADER_PATTERN.match(old_line.strip())
        if m_curr:
            raw_match_status = m_curr.group(2)
            new_line = old_line.replace(raw_match_status, norm_new, 1)
        else:
            new_line = f"### 任务 {target_item.id} {norm_new} — {target_item.title}\n"

        lines[target_idx] = new_line

        dir_name = os.path.dirname(os.path.abspath(filepath))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(tmp_path, filepath)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise

        target_item.status = norm_new
        target_item.raw_line = new_line
        return target_item


def get_status_summary(filepath: str) -> Dict[str, int]:
    """Return dictionary of task counts per status. / 返回文件内各状态的统计分布字典。"""
    tasks = parse_task_file(filepath)
    summary: Dict[str, int] = {s: 0 for s in ALL_STATUSES}
    for t in tasks:
        summary[t.status] = summary.get(t.status, 0) + 1
    return summary


def assert_task_checkout_allowed(workspace_root: str, filepath: str) -> None:
    """检查任务单是否已被隔离入 UNAUTHORIZED_BYPASS 队列，违者抛出 InvalidTransitionError。"""
    workspace_root = os.path.abspath(workspace_root)
    abs_path = os.path.abspath(os.path.join(workspace_root, filepath) if not os.path.isabs(filepath) else filepath)
    rel_path = os.path.relpath(abs_path, workspace_root).replace("\\", "/")
    dev_tasks_dir = os.path.dirname(abs_path)

    report = reconcile_workspace(workspace_root, dev_tasks_dir)
    norm_bypass = {p.replace("\\", "/").lower() for p in report.bypass_queue}
    if rel_path.lower() in norm_bypass:
        raise InvalidTransitionError(
            f"Task file '{rel_path}' is quarantined in UNAUTHORIZED_BYPASS queue. Checkout is forbidden. / "
            f"任务文件 '{rel_path}' 处于未授权旁路隔离队列中，已被物理阻断，禁止检出执行。"
        )
