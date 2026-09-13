from __future__ import annotations

import datetime
import os
from typing import List
from state_machine import TaskItem


def append_changelog_entry(
    changelog_path: str, task_file: str, completed_tasks: List[TaskItem]
) -> None:
    """在 CHANGELOG.md 中增量追加已完成任务的条目。

    若文件不存在则创建标准结构；若已存在则插入到第一个 '## ' 标题前。
    """
    today_str = datetime.date.today().isoformat()
    file_basename = os.path.basename(task_file)

    entry_lines = [
        f"## [{today_str}] {file_basename}\n",
        "\n",
    ]
    if completed_tasks:
        for t in completed_tasks:
            entry_lines.append(f"- **Task {t.id}**: {t.title}\n")
    else:
        entry_lines.append("- （无独立任务条目或全部跳过）\n")
    entry_lines.append("\n")

    if not os.path.exists(changelog_path):
        header = [
            "# 变更记录 (CHANGELOG)\n",
            "\n",
            "> 本文件记录由 Quench DevTasks 自动同步与人工补充的项目变更日志。\n",
            "\n",
        ]
        all_content = header + entry_lines
        with open(changelog_path, "w", encoding="utf-8") as f:
            f.writelines(all_content)
        return

    with open(changelog_path, "r", encoding="utf-8") as f:
        existing = f.readlines()

    insert_idx = -1
    for idx, line in enumerate(existing):
        if line.startswith("## "):
            insert_idx = idx
            break

    if insert_idx == -1:
        # 没有二级标题，直接追加到末尾
        existing.extend(["\n"] + entry_lines)
    else:
        existing = existing[:insert_idx] + entry_lines + existing[insert_idx:]

    with open(changelog_path, "w", encoding="utf-8") as f:
        f.writelines(existing)
