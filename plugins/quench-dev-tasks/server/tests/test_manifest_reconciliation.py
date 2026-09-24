# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
import pytest
import yaml

from manifest import (
    load_manifest,
    register_proposal,
    reconcile_workspace,
    ReconcileClass,
    ReconcileReport,
    compute_normalized_md_hash,
)
from server import (
    dev_tasks_status,
    dev_tasks_propose,
    dev_tasks_checkout,
)
from state_machine import (
    assert_task_checkout_allowed,
    InvalidTransitionError,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
)


@pytest.fixture
def reconcile_workspace_fixture(tmp_path):
    """构建用于测试清单后置对账与旁路隔离的工作区。"""
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True)
    agents_dir = ws / ".agents"
    agents_dir.mkdir(parents=True)

    config_data = {
        "project_name": "ReconcileTestProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "changelog_path": "CHANGELOG.md",
        "test_dir": "tests",
        "test_runner": "pytest",
    }
    with open(agents_dir / "quench_stack.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    tasks_dir = ws / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True)

    return ws, tasks_dir


def _create_sample_task_md(filepath: Path, task_id: str = "1.1", status: str = "✅ 已确认", title: str = "Sample Task") -> str:
    content = f"""# Sample Dev Tasks

## Task List & Status

### 任务 {task_id} {status} — {title}

#### 【需求描述】
测试需求描述

#### 【分步改造指引】
1. 第一步
2. 第二步

#### 【DoD 验证命令】
```bash
pytest tests
```
"""
    filepath.write_text(content, encoding="utf-8")
    return content


def test_register_proposal_creates_manifest_record(reconcile_workspace_fixture):
    ws, tasks_dir = reconcile_workspace_fixture
    task_file = tasks_dir / "2026-09-24_feature.md"
    _create_sample_task_md(task_file, task_id="1.1")

    md_hash = register_proposal(str(ws), task_id="1.1", md_path=str(task_file))
    assert md_hash
    assert len(md_hash) == 64

    manifest = load_manifest(str(ws))
    expected_id = "2026-09-24_feature::1.1"
    assert expected_id in manifest.records
    record = manifest.records[expected_id]
    assert record.md_sha256 == md_hash
    assert record.generation == 0
    assert not record.released


def test_reconcile_registered_match(reconcile_workspace_fixture):
    ws, tasks_dir = reconcile_workspace_fixture
    task_file = tasks_dir / "2026-09-24_feature.md"
    _create_sample_task_md(task_file, task_id="1.1")

    register_proposal(str(ws), task_id="1.1", md_path=str(task_file))

    report = reconcile_workspace(str(ws), str(tasks_dir))
    rel_path = "docs/dev_tasks/2026-09-24_feature.md"

    assert rel_path in report.matched_queue
    assert rel_path not in report.bypass_queue
    assert rel_path not in report.drift_queue

    matches = [e for e in report.entries if e.rel_path == rel_path]
    assert len(matches) == 1
    assert matches[0].classification == ReconcileClass.REGISTERED_MATCH


def test_reconcile_registered_drift(reconcile_workspace_fixture):
    ws, tasks_dir = reconcile_workspace_fixture
    task_file = tasks_dir / "2026-09-24_feature.md"
    _create_sample_task_md(task_file, task_id="1.1")

    register_proposal(str(ws), task_id="1.1", md_path=str(task_file))

    # 人工篡改正文内容（非状态变更，而是修改指令/标题）
    modified_content = task_file.read_text(encoding="utf-8") + "\n\n#### 【恶意插入指令】\nrm -rf /"
    task_file.write_text(modified_content, encoding="utf-8")

    report = reconcile_workspace(str(ws), str(tasks_dir))
    rel_path = "docs/dev_tasks/2026-09-24_feature.md"

    assert rel_path in report.drift_queue
    assert rel_path not in report.bypass_queue

    matches = [e for e in report.entries if e.rel_path == rel_path]
    assert len(matches) == 1
    assert matches[0].classification == ReconcileClass.REGISTERED_DRIFT
    assert "Hash mismatch" in matches[0].drift_reason


def test_reconcile_branch_changed(reconcile_workspace_fixture):
    ws, tasks_dir = reconcile_workspace_fixture
    task_file = tasks_dir / "2026-09-24_feature.md"
    _create_sample_task_md(task_file, task_id="1.1")

    # 登记时带有旧的 git_head_sha
    with patch("manifest._get_git_metadata", return_value=("commit_branch_a_12345678", 1000.0)):
        register_proposal(str(ws), task_id="1.1", md_path=str(task_file))

    # 内容改变，但同时 git_head_sha 也发生了分支切换变更
    task_file.write_text(task_file.read_text(encoding="utf-8") + "\n# Merged from Branch B", encoding="utf-8")
    with patch("manifest._get_git_metadata", return_value=("commit_branch_b_87654321", 2000.0)):
        report = reconcile_workspace(str(ws), str(tasks_dir))

    rel_path = "docs/dev_tasks/2026-09-24_feature.md"
    assert rel_path in report.matched_queue
    assert rel_path not in report.drift_queue
    assert rel_path not in report.bypass_queue

    matches = [e for e in report.entries if e.rel_path == rel_path]
    assert len(matches) == 1
    assert matches[0].classification == ReconcileClass.BRANCH_CHANGED
    assert "Git HEAD changed" in matches[0].drift_reason


def test_reconcile_git_tracked_historical_onboarding(reconcile_workspace_fixture):
    ws, tasks_dir = reconcile_workspace_fixture
    task_file = tasks_dir / "2026-09-20_legacy_feature.md"
    _create_sample_task_md(task_file, task_id="1.1")

    rel_path = "docs/dev_tasks/2026-09-20_legacy_feature.md"

    # 模拟该文件已由 Git 跟踪（历史遗留合法任务单）
    with patch("manifest._get_git_tracked_files", return_value={rel_path}):
        report = reconcile_workspace(str(ws), str(tasks_dir))

    assert rel_path in report.matched_queue
    assert rel_path not in report.bypass_queue

    matches = [e for e in report.entries if e.rel_path == rel_path]
    assert len(matches) == 1
    assert matches[0].classification == ReconcileClass.REGISTERED_MATCH
    assert "Git-tracked historical file smoothly onboarded" in matches[0].drift_reason

    # 验证该历史文件已被自动平滑收录入权威清单
    manifest = load_manifest(str(ws))
    assert any("2026-09-20_legacy_feature" in k for k in manifest.records)


def test_reconcile_untracked_rogue_file_quarantine(reconcile_workspace_fixture):
    ws, tasks_dir = reconcile_workspace_fixture
    rogue_file = tasks_dir / "2026-09-24_rogue_bypass.md"
    original_content = _create_sample_task_md(rogue_file, task_id="9.9", title="Rogue Untracked Task")

    rel_path = "docs/dev_tasks/2026-09-24_rogue_bypass.md"

    # 未在清单登记，且未被 Git 跟踪（非法旁路文件）
    with patch("manifest._get_git_tracked_files", return_value=set()):
        report = reconcile_workspace(str(ws), str(tasks_dir))

    assert rel_path in report.bypass_queue
    assert rel_path not in report.matched_queue
    assert rel_path not in report.drift_queue

    matches = [e for e in report.entries if e.rel_path == rel_path]
    assert len(matches) == 1
    assert matches[0].classification == ReconcileClass.UNAUTHORIZED_BYPASS

    # 验证状态行零污染：Markdown 原文绝不被污染写入 UNAUTHORIZED_BYPASS
    assert rogue_file.read_text(encoding="utf-8") == original_content
    assert "UNAUTHORIZED_BYPASS" not in rogue_file.read_text(encoding="utf-8")


def test_assert_task_checkout_allowed_blocking_and_permission(reconcile_workspace_fixture):
    ws, tasks_dir = reconcile_workspace_fixture

    # 1. 正常登记的文件允许检出
    valid_file = tasks_dir / "2026-09-24_valid.md"
    _create_sample_task_md(valid_file, task_id="1.1")
    register_proposal(str(ws), task_id="1.1", md_path=str(valid_file))

    # 应当静默通过
    assert_task_checkout_allowed(str(ws), str(valid_file))

    # 2. 未登记且未跟踪的旁路文件被阻断
    rogue_file = tasks_dir / "2026-09-24_rogue.md"
    _create_sample_task_md(rogue_file, task_id="2.1")

    with patch("manifest._get_git_tracked_files", return_value=set()):
        with pytest.raises(InvalidTransitionError) as exc_info:
            assert_task_checkout_allowed(str(ws), str(rogue_file))
        assert "UNAUTHORIZED_BYPASS" in str(exc_info.value)
        assert "quarantined" in str(exc_info.value).lower() or "隔离" in str(exc_info.value)


def test_dev_tasks_checkout_tool_blocks_quarantined_task(reconcile_workspace_fixture):
    ws, tasks_dir = reconcile_workspace_fixture

    rogue_file = tasks_dir / "2026-09-24_rogue.md"
    _create_sample_task_md(rogue_file, task_id="7.7", status="✅ 已确认")

    with patch("manifest._get_git_tracked_files", return_value=set()):
        # 1. 指定 task_file 检出被阻断
        res1 = dev_tasks_checkout(str(ws), task_file=rogue_file.name)
        assert "error" in res1
        assert "Checkout blocked by security policy" in res1["error"] or "UNAUTHORIZED_BYPASS" in res1["error"]

        # 2. 定向 task_id 检出被阻断
        res2 = dev_tasks_checkout(str(ws), task_id="7.7")
        assert "error" in res2
        assert "Checkout blocked by security policy" in res2["error"] or "UNAUTHORIZED_BYPASS" in res2["error"]

        # 3. 顺序领单模式自动跳过该隔离文件
        res3 = dev_tasks_checkout(str(ws))
        # 因为没有其他合法 confirmed 任务，应返回无任务领单提示而非检出 rogue 任务
        assert res3.get("task_id") != "7.7"


def test_dev_tasks_status_reports_bypass_queue(reconcile_workspace_fixture):
    ws, tasks_dir = reconcile_workspace_fixture

    valid_file = tasks_dir / "2026-09-24_valid.md"
    _create_sample_task_md(valid_file, task_id="1.1", status="✅ 已确认")
    register_proposal(str(ws), task_id="1.1", md_path=str(valid_file))

    rogue_file = tasks_dir / "2026-09-24_rogue.md"
    _create_sample_task_md(rogue_file, task_id="2.1", status="🔨 执行中")

    with patch("manifest._get_git_tracked_files", return_value=set()):
        status_res = dev_tasks_status(str(ws))

    rel_rogue = "docs/dev_tasks/2026-09-24_rogue.md"
    rel_valid = "docs/dev_tasks/2026-09-24_valid.md"

    assert "reconcile_report" in status_res
    assert rel_rogue in status_res["reconcile_report"]["bypass_queue"]
    assert rel_valid in status_res["reconcile_report"]["matched_queue"]
    assert "bypass_warning" in status_res

    # 验证 active_task 绝不被非法执行中任务劫持
    if status_res.get("active_task"):
        assert status_res["active_task"]["id"] != "2.1"

    # 验证 file_records 中 rogue 带有隔离标记
    rogue_rec = next(f for f in status_res["files"] if f["name"] == rogue_file.name)
    assert rogue_rec["quarantined"] is True
    assert "UNAUTHORIZED_BYPASS" in rogue_rec["quarantine_reason"]


def test_dev_tasks_propose_auto_registers_in_manifest(reconcile_workspace_fixture):
    ws, tasks_dir = reconcile_workspace_fixture

    task_payload = [{
        "id": "1.1",
        "title": "Auto Registered Task",
        "affected_files": ["[MODIFY] src/app.py"],
        "root_cause_and_goal": "根因目标清晰，完成自动登记。",
        "type_contracts": "无特殊类型契约",
        "steps": ["1. 步骤一", "2. 步骤二"],
        "defensive_checks": ["- 边界检查防御"],
        "dod_commands": ["pytest tests"],
    }]

    propose_res = dev_tasks_propose(str(ws), "2026-09-24_proposed.md", task_payload)
    assert propose_res.get("created") is True

    # 提案后立即后置对账，无需额外手动操作即直接 MATCH
    report = reconcile_workspace(str(ws), str(tasks_dir))
    rel_path = "docs/dev_tasks/2026-09-24_proposed.md"

    assert rel_path in report.matched_queue
    assert rel_path not in report.bypass_queue
