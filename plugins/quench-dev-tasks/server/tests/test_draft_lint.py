import os
import shutil
import tempfile
import pytest
import yaml

from schema_validator import lint_task_physical_feasibility
from server import (
    dev_tasks_status,
    dev_tasks_promote_draft,
    dev_tasks_propose,
)


@pytest.fixture
def mock_workspace():
    temp_dir = tempfile.mkdtemp(prefix="quench_draft_ws_")
    agents_dir = os.path.join(temp_dir, ".agents")
    os.makedirs(agents_dir, exist_ok=True)

    config_data = {
        "project_name": "DraftLintProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "changelog_path": "CHANGELOG.md",
        "test_dir": "tests",
        "test_runner": "pytest",
    }
    with open(os.path.join(agents_dir, "quench_stack.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    yield temp_dir
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_lint_physical_feasibility_missing_modify_file(mock_workspace):
    ws = mock_workspace
    task = {
        "id": "1.1",
        "title": "修改不存在的文件",
        "affected_files": ["[MODIFY] src/nonexistent_file.py"],
        "root_cause_and_goal": "根因明确，目标明确。",
        "type_contracts": "无",
        "steps": ["1. 修复缺陷", "2. 测试验证"],
        "defensive_checks": ["- 边界防御"],
        "dod_commands": ["pytest"],
    }
    res = lint_task_physical_feasibility(ws, task)
    assert res.passed is False
    assert any("物理不存在" in i.message for i in res.issues)


def test_lint_physical_feasibility_new_file_overwrite_hazard(mock_workspace):
    ws = mock_workspace
    src_dir = os.path.join(ws, "src")
    os.makedirs(src_dir, exist_ok=True)
    existing_file = os.path.join(src_dir, "already_exists.py")
    with open(existing_file, "w", encoding="utf-8") as f:
        f.write("# existing\n")

    task = {
        "id": "1.2",
        "title": "新建已有文件",
        "affected_files": ["[NEW] src/already_exists.py"],
        "root_cause_and_goal": "根因明确，目标明确。",
        "type_contracts": "无",
        "steps": ["1. 修复缺陷", "2. 测试验证"],
        "defensive_checks": ["- 边界防御"],
        "dod_commands": ["pytest"],
    }
    res = lint_task_physical_feasibility(ws, task)
    assert res.passed is False
    assert any("覆盖冲突风险" in i.message for i in res.issues)


def test_lint_physical_feasibility_path_traversal(mock_workspace):
    ws = mock_workspace
    task = {
        "id": "1.3",
        "title": "路径穿越危险任务",
        "affected_files": ["[MODIFY] ../../outside_workspace.py"],
        "root_cause_and_goal": "根因明确，目标明确。",
        "type_contracts": "无",
        "steps": ["1. 修复缺陷", "2. 测试验证"],
        "defensive_checks": ["- 边界防御"],
        "dod_commands": ["pytest"],
    }
    res = lint_task_physical_feasibility(ws, task)
    assert res.passed is False
    assert any("路径穿越安全违规" in i.message for i in res.issues)


def test_lint_dod_command_injection_defense(mock_workspace):
    ws = mock_workspace
    task = {
        "id": "1.4",
        "title": "命令注入检测",
        "affected_files": [],
        "root_cause_and_goal": "根因明确，目标明确。",
        "type_contracts": "无",
        "steps": ["1. 修复缺陷", "2. 测试验证"],
        "defensive_checks": ["- 边界防御"],
        "dod_commands": ["pytest tests/ ; rm -rf /"],
    }
    res = lint_task_physical_feasibility(ws, task)
    assert res.passed is False
    assert any("危险 shell 元字符" in i.message for i in res.issues)


def test_lint_dod_command_pytest_dry_run(mock_workspace):
    ws = mock_workspace
    # 1. 语法错误参数
    task_bad_arg = {
        "id": "1.5",
        "title": "无效参数命令",
        "affected_files": [],
        "root_cause_and_goal": "根因明确，目标明确。",
        "type_contracts": "无",
        "steps": ["1. 修复缺陷", "2. 测试验证"],
        "defensive_checks": ["- 边界防御"],
        "dod_commands": ["pytest --this-is-an-unrecognized-argument-xyz"],
    }
    res_bad = lint_task_physical_feasibility(ws, task_bad_arg)
    assert res_bad.passed is False
    assert any("未知参数" in i.message or "dry-run" in i.message for i in res_bad.issues)

    # 2. 合法单测 dry-run（指向已存在的测试文件）
    test_file = os.path.join(ws, "test_sample.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("def test_ok(): pass\n")

    task_ok = {
        "id": "1.6",
        "title": "合法单测命令",
        "affected_files": ["[MODIFY] test_sample.py"],
        "root_cause_and_goal": "根因明确，目标明确。",
        "type_contracts": "无",
        "steps": ["1. 修复缺陷", "2. 测试验证"],
        "defensive_checks": ["- 边界防御"],
        "dod_commands": ["pytest test_sample.py -q"],
    }
    res_ok = lint_task_physical_feasibility(ws, task_ok)
    assert res_ok.passed is True


def test_dev_tasks_status_draft_isolation(mock_workspace):
    ws = mock_workspace
    tasks_dir = os.path.join(ws, "docs", "dev_tasks")
    os.makedirs(tasks_dir, exist_ok=True)
    task_file_path = os.path.join(tasks_dir, "2026-09-21_test.md")

    # 创建一个草案任务和一个正式任务
    content = """# 测试任务集

### 任务 1.1 ⬜ 待确认 (草案) — 草案任务标题
<!-- quench-task-meta: {"draft": true} -->
- **状态**: ⬜ 待确认
- **优先级**: P1

#### 【涉及文件】
- `[MODIFY] src/foo.py`

#### 【缺陷根因与修改目标】
根因明确。

#### 【目标签名与类型契约】
无

#### 【分步改造指引】
1. 第一步
2. 第二步

#### 【防御与边缘校验】
- 校验项

#### 【DoD 验证命令】
```bash
pytest
```

### 任务 1.2 ⬜ 待确认 — 正式待领任务
- **状态**: ⬜ 待确认
- **优先级**: P1

#### 【涉及文件】
- `[NEW] src/bar.py`

#### 【缺陷根因与修改目标】
根因明确。

#### 【目标签名与类型契约】
无

#### 【分步改造指引】
1. 第一步
2. 第二步

#### 【防御与边缘校验】
- 校验项

#### 【DoD 验证命令】
```bash
pytest
```
"""
    with open(task_file_path, "w", encoding="utf-8") as f:
        f.write(content)

    # 默认隔离草案：include_drafts=False
    st = dev_tasks_status(ws, include_drafts=False)
    file_rec = st["files"][0]
    assert file_rec["summary"]["📝 草案"] == 1
    assert "1.1" in file_rec["batches"]["draft_queue"]
    # 正式待领队列中应只有 1.2，不包含 1.1
    assert "1.2" in file_rec["batches"]["pending_queue"]
    assert "1.1" not in file_rec["batches"]["pending_queue"]

    # include_drafts=True 时将草案包含在待领队列中
    st_all = dev_tasks_status(ws, include_drafts=True)
    file_rec_all = st_all["files"][0]
    assert "1.1" in file_rec_all["batches"]["pending_queue"]


def test_dev_tasks_promote_draft_workflow(mock_workspace):
    ws = mock_workspace
    tasks_dir = os.path.join(ws, "docs", "dev_tasks")
    os.makedirs(tasks_dir, exist_ok=True)
    task_file_name = "2026-09-21_test.md"
    task_file_path = os.path.join(tasks_dir, task_file_name)

    content = """# 测试草案晋升任务集

### 任务 2.1 ⬜ 待确认 (草案) — 待晋升草案
<!-- quench-task-meta: {"draft": true} -->
- **状态**: ⬜ 待确认
- **优先级**: P1

#### 【涉及文件】
- `[MODIFY] src/core.py`

#### 【缺陷根因与修改目标】
根因明确。

#### 【目标签名与类型契约】
无

#### 【分步改造指引】
1. 第一步
2. 第二步

#### 【防御与边缘校验】
- 校验项

#### 【DoD 验证命令】
```bash
pytest
```
"""
    with open(task_file_path, "w", encoding="utf-8") as f:
        f.write(content)

    # 1. 磁盘上没有 src/core.py，晋升应被拦截
    res_rejected = dev_tasks_promote_draft(ws, task_file_name, "2.1")
    assert res_rejected["status"] == "rejected"
    assert res_rejected["promoted"] is False
    assert len(res_rejected["issues"]) > 0

    # 2. 在磁盘上创建 src/core.py，满足物理存在条件
    src_dir = os.path.join(ws, "src")
    os.makedirs(src_dir, exist_ok=True)
    with open(os.path.join(src_dir, "core.py"), "w", encoding="utf-8") as f:
        f.write("# core implementation\n")

    # 再次晋升：应成功全绿
    res_promoted = dev_tasks_promote_draft(ws, task_file_name, "2.1")
    assert res_promoted["status"] == "promoted"
    assert res_promoted["promoted"] is True

    # 检查文件内容：(草案) 和 quench-task-meta 注释已被移除
    with open(task_file_path, "r", encoding="utf-8") as f:
        updated_content = f.read()
    assert "(草案)" not in updated_content
    assert "<!-- quench-task-meta:" not in updated_content
    assert "### 任务 2.1 ⬜ 待确认 — 待晋升草案" in updated_content
