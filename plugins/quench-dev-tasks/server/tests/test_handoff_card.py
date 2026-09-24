# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
import pytest
import yaml

from handoff_card import render_handoff_card
from server import dev_tasks_export_handoff_card


@pytest.fixture
def mock_task_workspace():
    temp_dir = tempfile.mkdtemp(prefix="quench_handoff_ws_")
    agents_dir = os.path.join(temp_dir, ".agents")
    tasks_dir = os.path.join(temp_dir, "docs", "dev_tasks")
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(tasks_dir, exist_ok=True)

    config_data = {
        "project_name": "HandoffTestProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
    }
    with open(os.path.join(agents_dir, "quench_stack.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    sample_md = """# Sample Tasks

### 任务 1.1 ✅ 已确认 — 架构解耦示范任务

#### 【涉及文件】
```
[MODIFY] src/core.py
[NEW] src/helper.py
```

#### 【缺陷根因与修改目标】
```
【根因分析】
1. 模块存在强耦合。
【修改目标】
1. 提取接口进行依赖反转。
```

#### 【目标签名与类型契约】
```
def process_data(item: str) -> bool:
    pass
```

#### 【分步改造指引】
1. 重构 core.py；
2. 运行单测。

#### 【DoD 验证命令】
```bash
python -m pytest tests/test_core.py -q
```

---
"""
    with open(os.path.join(tasks_dir, "2026-09-24_demo.md"), "w", encoding="utf-8") as f:
        f.write(sample_md)

    yield temp_dir
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_render_handoff_card_basic_format():
    """验证 render_handoff_card 输出符合 GitHub GFM > [!IMPORTANT] 规范且默认无 details"""
    card = render_handoff_card(
        task_id="1.1",
        task_file="docs/dev_tasks/demo.md",
        reason="rework_required",
        task_meta={"preferred": "subagent", "title": "解耦任务"},
        include_context=False,
    )
    assert "> [!IMPORTANT]" in card
    assert "⏸️ Quench 任务交接卡 / Quench Task Handoff Card — 解耦任务" in card
    assert "**Task ID / 任务编号**: `1.1`" in card
    assert "**Task File / 任务文件**: `docs/dev_tasks/demo.md`" in card
    assert "**Handoff Reason / 交接原因**: rework_required" in card
    assert "**Preferred Mode / 推荐模式**: `subagent`" in card
    assert "<details>" not in card


def test_render_handoff_card_with_collapsible_context():
    """验证 include_context=True 时注入 <details> 折叠上下文且提取四大约束字段"""
    sample_spec = """
#### 【涉及文件】
```
[MODIFY] a.py
```

#### 【缺陷根因与修改目标】
根因说明

#### 【目标签名与类型契约】
契约说明

#### 【DoD 验证命令】
```bash
pytest
```
"""
    card = render_handoff_card(
        task_id="1.1",
        task_file="docs/dev_tasks/demo.md",
        reason="escalation",
        task_meta={"full_spec": sample_spec},
        include_context=True,
    )
    assert "<details>" in card
    assert "<summary><b>🔍 任务单上下文详情 / Task Context Details</b></summary>" in card
    assert "#### 【涉及文件】" in card
    assert "[MODIFY] a.py" in card
    assert "#### 【缺陷根因与修改目标】" in card
    assert "根因说明" in card
    assert "#### 【目标签名与类型契约】" in card
    assert "契约说明" in card
    assert "#### 【DoD 验证命令】" in card
    assert "pytest" in card
    assert "</details>" in card


def test_render_handoff_card_structured_meta_and_leak_defense():
    """验证传入结构化字典及严禁泄漏系统/敏感字段"""
    task_meta = {
        "files": ["[MODIFY] test.py"],
        "root_cause": "设计缺陷",
        "contract": "def test(): pass",
        "dod": ["pytest test.py"],
        # 敏感/内部字段，绝不应该被渲染
        "secret_env": "SK_SECRET_KEY_12345",
        "api_key": "sk-secret-token",
    }
    card = render_handoff_card(
        task_id="2.1",
        task_file="docs/dev_tasks/demo.md",
        reason="manual_review",
        task_meta=task_meta,
        include_context=True,
    )
    assert "SK_SECRET_KEY_12345" not in card
    assert "sk-secret-token" not in card
    assert "[MODIFY] test.py" in card
    assert "设计缺陷" in card
    assert "def test(): pass" in card
    assert "pytest test.py" in card


def test_dev_tasks_export_handoff_card_tool_success(mock_task_workspace):
    """验证 dev_tasks_export_handoff_card 工具成功导出卡片"""
    ws = mock_task_workspace
    res = dev_tasks_export_handoff_card(
        workspace_root=ws,
        task_id="1.1",
        include_context=True,
    )
    assert res["status"] == "exported"
    assert res["task_id"] == "1.1"
    assert "2026-09-24_demo.md" in res["task_file"]
    assert res["title"] == "架构解耦示范任务"
    assert "> [!IMPORTANT]" in res["handoff_card"]
    assert "<details>" in res["handoff_card"]
    assert "【涉及文件】" in res["handoff_card"]
    assert "src/core.py" in res["handoff_card"]


def test_dev_tasks_export_handoff_card_tool_not_found(mock_task_workspace):
    """验证 dev_tasks_export_handoff_card 目标 task_id 不存在时优雅返回结构化错误"""
    ws = mock_task_workspace
    res = dev_tasks_export_handoff_card(
        workspace_root=ws,
        task_id="non_existent_999",
        include_context=False,
    )
    assert res["status"] == "not_found"
    assert "error" in res
    assert "non_existent_999" in res["error"]
