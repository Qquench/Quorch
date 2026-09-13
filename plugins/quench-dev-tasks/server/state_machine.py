from __future__ import annotations

import os
import re
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
    """状态机基础异常"""
    pass


class TaskNotFoundError(StateMachineError):
    """任务 ID 未找到"""
    pass


class InvalidTransitionError(StateMachineError):
    """非法状态流转异常"""
    pass


@dataclass
class TaskItem:
    id: str              # 如 "1.1" 或 "1"
    title: str           # 标题文本
    status: str          # 状态字符串，如 "⬜ 待确认"
    line_number: int     # 行号 (0-indexed)
    raw_line: str        # 原始行内容


EMOJI_STATUS_OPTIONS = [
    r"⬜\s*待确认",
    r"✅\s*已确认",
    r"🔨\s*执行中",
    r"✔️\s*已完成",
    r"✔\s*已完成",
    r"⏭️\s*跳过",
    r"⏭\s*跳过",
    r"🔄\s*需返工",
    r"待确认",
    r"已确认",
    r"执行中",
    r"已完成",
    r"跳过",
    r"需返工",
]

STATUS_REGEX_PART = "|".join(EMOJI_STATUS_OPTIONS)

TASK_HEADER_PATTERN = re.compile(
    rf"^###\s+(?:任务|Task)\s+([0-9a-zA-Z\._\-]+)\s*[:—\-]?\s*({STATUS_REGEX_PART})\s*[:—\-]?\s*(.*)$"
)


def _normalize_status(status_str: str) -> str:
    """将可能缺少 emoji 或带有前后空格的状态标准化"""
    s = status_str.strip()
    for standard in ALL_STATUSES:
        if standard in s or standard.replace(" ", "") in s.replace(" ", ""):
            return standard
        key = standard.split(" ")[-1]
        if key in s:
            return standard
    return s


def parse_task_file(filepath: str) -> List[TaskItem]:
    """解析 Markdown 任务文件，提取所有任务条目及其当前状态"""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"任务文件不存在: {filepath}")

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
    """原子化状态转换：读取→校验合法性→替换写回。带 filelock 排他锁。"""
    norm_new = _normalize_status(new_status)
    if norm_new not in ALL_STATUSES:
        raise InvalidTransitionError(f"未知目标状态 '{new_status}'，合法状态: {ALL_STATUSES}")

    lock_path = filepath + ".lock"
    lock = filelock.FileLock(lock_path, timeout=timeout)

    with lock:
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"持有锁后发现任务文件不存在: {filepath}")

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
            raise TaskNotFoundError(f"未在文件 {filepath} 中找到任务 ID '{task_id}'")

        cur_status = target_item.status
        if cur_status == norm_new:
            return target_item

        allowed = VALID_TRANSITIONS.get(cur_status, [])
        if norm_new not in allowed:
            raise InvalidTransitionError(
                f"任务 {task_id} 当前状态为 '{cur_status}'，不允许流转至 '{norm_new}'。"
                f"合法路径: {allowed}"
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

        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)

        target_item.status = norm_new
        target_item.raw_line = new_line
        return target_item


def get_status_summary(filepath: str) -> Dict[str, int]:
    """返回文件内各状态的统计字典"""
    tasks = parse_task_file(filepath)
    summary: Dict[str, int] = {s: 0 for s in ALL_STATUSES}
    for t in tasks:
        summary[t.status] = summary.get(t.status, 0) + 1
    return summary
