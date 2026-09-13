# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional
import filelock

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


def transition_task(
    filepath: str, task_id: str, new_status: str, timeout: float = 5.0
) -> TaskItem:
    """Atomically transition task status with filelock: read -> validate -> replace -> write back. / 原子化状态转换：读取→校验合法性→替换写回。带 filelock 排他锁。"""
    norm_new = _normalize_status(new_status)
    if norm_new not in ALL_STATUSES:
        raise InvalidTransitionError(f"Unknown target status '{new_status}', valid: {ALL_STATUSES} / 未知目标状态 '{new_status}'，合法状态: {ALL_STATUSES}")

    lock_path = filepath + ".lock"
    lock = filelock.FileLock(lock_path, timeout=timeout)

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
