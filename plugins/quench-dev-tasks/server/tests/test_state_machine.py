import os
import tempfile
import pytest
from state_machine import (
    parse_task_file,
    transition_task,
    get_status_summary,
    STATUS_PENDING,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_SKIPPED,
    STATUS_REWORK,
    InvalidTransitionError,
    TaskNotFoundError,
)

SAMPLE_MARKDOWN = """# 开发任务单

### 任务 1.1 ⬜ 待确认 — 目录骨架构建
详情内容 1.1

### 任务 1.2 ✅ 已确认 — 配置加载器
详情内容 1.2

### 任务 1.3 🔨 执行中 — 状态机引擎
详情内容 1.3
"""

def test_parse_task_file():
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as f:
        f.write(SAMPLE_MARKDOWN)
        f_path = f.name

    try:
        tasks = parse_task_file(f_path)
        assert len(tasks) == 3
        assert tasks[0].id == "1.1"
        assert tasks[0].status == STATUS_PENDING
        assert tasks[0].title == "目录骨架构建"

        assert tasks[1].id == "1.2"
        assert tasks[1].status == STATUS_CONFIRMED

        assert tasks[2].id == "1.3"
        assert tasks[2].status == STATUS_IN_PROGRESS

        summary = get_status_summary(f_path)
        assert summary[STATUS_PENDING] == 1
        assert summary[STATUS_CONFIRMED] == 1
        assert summary[STATUS_IN_PROGRESS] == 1
        assert summary[STATUS_COMPLETED] == 0
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)
        if os.path.exists(f_path + ".lock"):
            os.remove(f_path + ".lock")


def test_transition_valid_flow():
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as f:
        f.write(SAMPLE_MARKDOWN)
        f_path = f.name

    try:
        # 1.1 ⬜ 待确认 -> ✅ 已确认
        res = transition_task(f_path, "1.1", STATUS_CONFIRMED)
        assert res.status == STATUS_CONFIRMED

        # 1.1 ✅ 已确认 -> 🔨 执行中
        res = transition_task(f_path, "1.1", STATUS_IN_PROGRESS)
        assert res.status == STATUS_IN_PROGRESS

        # 1.1 🔨 执行中 -> ✔️ 已完成
        res = transition_task(f_path, "1.1", STATUS_COMPLETED)
        assert res.status == STATUS_COMPLETED

        # 验证持久化写回
        updated_tasks = parse_task_file(f_path)
        assert updated_tasks[0].status == STATUS_COMPLETED
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)
        if os.path.exists(f_path + ".lock"):
            os.remove(f_path + ".lock")


def test_transition_invalid():
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as f:
        f.write(SAMPLE_MARKDOWN)
        f_path = f.name

    try:
        # 1.1 ⬜ 待确认 直接跳到 🔨 执行中 应该被阻断！
        with pytest.raises(InvalidTransitionError):
            transition_task(f_path, "1.1", STATUS_IN_PROGRESS)

        # 不存在的任务 ID
        with pytest.raises(TaskNotFoundError):
            transition_task(f_path, "99.9", STATUS_CONFIRMED)
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)
        if os.path.exists(f_path + ".lock"):
            os.remove(f_path + ".lock")
