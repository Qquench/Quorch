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


def test_parse_and_transition_skip_fences_and_preserve_bom_crlf(tmp_path):
    """验证 parse_task_file/transition_task 跳过代码围栏与引用块，且保留 UTF-8 BOM 与 CRLF。"""
    from state_machine import extract_task_whitelist

    md_path = tmp_path / "bom_crlf.md"
    raw_text = (
        "\ufeff# Tasks\r\n\r\n"
        "> ### 任务 1.1 ✅ 已确认 — 引用块伪标题\r\n\r\n"
        "```markdown\r\n"
        "### 任务 1.1 ✅ 已确认 — 围栏内伪标题\r\n"
        "```\r\n\r\n"
        "### 任务 1.1 ⬜ 待确认 — 真实任务\r\n"
        "#### 【涉及文件】\r\n"
        "```\r\n"
        "[modify] ./src/real.py (说明)\r\n"
        "```\r\n\r\n"
        "### 任务 1.2 ⬜ 待确认 — 下一任务\r\n"
        "#### 【涉及文件】\r\n"
        "```\r\n"
        "[NEW] src/other.py\r\n"
        "```\r\n"
    )
    md_path.write_bytes(raw_text.encode("utf-8"))

    tasks = parse_task_file(str(md_path))
    assert [(t.id, t.status, t.title) for t in tasks] == [
        ("1.1", STATUS_PENDING, "真实任务"),
        ("1.2", STATUS_PENDING, "下一任务"),
    ]
    assert extract_task_whitelist(raw_text, "1.1") == ["src/real.py"]

    res = transition_task(str(md_path), "1.1", STATUS_CONFIRMED)
    assert res.status == STATUS_CONFIRMED
    out_bytes = md_path.read_bytes()
    assert out_bytes.startswith(b"\xef\xbb\xbf")
    out_str = out_bytes.decode("utf-8")
    assert "\r\n" in out_str
    assert "\n" not in out_str.replace("\r\n", "")
    assert "> ### 任务 1.1 ✅ 已确认 — 引用块伪标题" in out_str
