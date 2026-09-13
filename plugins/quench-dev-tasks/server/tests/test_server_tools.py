import json
import os
import shutil
import tempfile
import pytest
import yaml

from server import (
    dev_tasks_status,
    dev_tasks_propose,
    dev_tasks_confirm,
    dev_tasks_checkout,
    dev_tasks_complete,
    dev_tasks_escalate,
    dev_tasks_archive,
    dev_tasks_set_bypass,
)

@pytest.fixture
def mock_workspace():
    temp_dir = tempfile.mkdtemp(prefix="quench_test_ws_")
    agents_dir = os.path.join(temp_dir, ".agents")
    os.makedirs(agents_dir, exist_ok=True)

    config_data = {
        "project_name": "MockProject",
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


def test_full_tool_workflow(mock_workspace):
    ws = mock_workspace

    # 1. 初始状态检查
    st = dev_tasks_status(ws)
    assert st["project_name"] == "MockProject"
    assert len(st["files"]) == 0
    assert "governance_scope" in st

    # 2. 提出任务 propose
    sample_tasks = [
        {
            "id": "1.1",
            "title": "任务一",
            "affected_files": ["[MODIFY] src/app.py"],
            "root_cause_and_goal": "根因目标清晰。",
            "type_contracts": "无",
            "steps": ["1. 第一步", "2. 第二步"],
            "defensive_checks": ["- 边界检查"],
            "dod_commands": ["pytest"],
        },
        {
            "id": "1.2",
            "title": "任务二",
            "affected_files": ["[NEW] src/util.py"],
            "root_cause_and_goal": "新增工具类。",
            "type_contracts": "无",
            "steps": ["1. 编写类", "2. 测试"],
            "defensive_checks": ["无"],
            "dod_commands": ["pytest"],
        },
    ]
    prop = dev_tasks_propose(ws, "2026-09-11_feature_test.md", sample_tasks)
    assert prop["created"] is True
    assert prop["created_count"] == 2

    # 3. 再次查看状态
    st2 = dev_tasks_status(ws)
    assert len(st2["files"]) == 1
    assert st2["files"][0]["total_tasks"] == 2

    # 4. 确认任务 confirm
    conf = dev_tasks_confirm(ws, "2026-09-11_feature_test.md", ["1.1", "1.2"], action="confirm")
    assert len(conf["updated"]) == 2
    assert conf["updated"][0]["new_status"] == "✅ 已确认"

    # 5. 检出任务 checkout
    chk = dev_tasks_checkout(ws)
    assert chk["task_id"] == "1.1"
    assert chk["status"] == "🔨 执行中"

    # 6. 模拟 escalate
    esc = dev_tasks_escalate(ws, "2026-09-11_feature_test.md", "1.1", "死锁难题需架构模型深度审视")
    assert esc["status"] == "escalated"
    assert "reviewer" in esc["suggested_subagent"]

    # 7. 完成任务 complete
    comp = dev_tasks_complete(ws, "2026-09-11_feature_test.md", "1.1", dod_output="All tests passed")
    assert comp["status"] == "completed"

    # 将 1.2 也标记为 skip 或 complete
    conf_skip = dev_tasks_confirm(ws, "2026-09-11_feature_test.md", ["1.2"], action="skip")
    assert conf_skip["updated"][0]["new_status"] == "⏭️ 跳过"

    # 8. 归档 archive
    arch = dev_tasks_archive(ws, "2026-09-11_feature_test.md")
    assert arch["archived"] is True
    assert os.path.exists(arch["archive_path"])
    assert arch["changelog_updated"] is True

    # 验证 CHANGELOG 内容
    changelog_file = os.path.join(ws, "CHANGELOG.md")
    assert os.path.isfile(changelog_file)
    with open(changelog_file, "r", encoding="utf-8") as f:
        cl_text = f.read()
    assert "2026-09-11_feature_test.md" in cl_text
    assert "任务一" in cl_text


def test_batch_and_rework_workflow(mock_workspace):
    ws = mock_workspace
    tasks = [
        {
            "id": "1",
            "title": "批次一任务",
            "affected_files": ["[MODIFY] a.py"],
            "root_cause_and_goal": "目标明确。",
            "type_contracts": "无",
            "steps": ["1. 修改"],
            "defensive_checks": ["无"],
            "dod_commands": ["pytest"],
        },
        {
            "id": "2",
            "title": "需要架构审查返工的任务",
            "affected_files": ["[MODIFY] b.py"],
            "root_cause_and_goal": "需要深度架构梳理。",
            "type_contracts": "无",
            "steps": ["1. 梳理"],
            "defensive_checks": ["无"],
            "dod_commands": ["pytest"],
        },
        {
            "id": "3",
            "title": "待确认的第二批任务",
            "affected_files": ["[MODIFY] c.py"],
            "root_cause_and_goal": "后续开发。",
            "type_contracts": "无",
            "steps": ["1. 待定"],
            "defensive_checks": ["无"],
            "dod_commands": ["pytest"],
        },
    ]
    dev_tasks_propose(ws, "batch_test.md", tasks)

    # 1. 仅分批确认任务 1
    dev_tasks_confirm(ws, "batch_test.md", ["1"], action="confirm")
    # 将任务 2 明确打上需返工标签
    dev_tasks_confirm(ws, "batch_test.md", ["2"], action="rework")

    # 2. 检查 status 包含 batches
    st = dev_tasks_status(ws)
    b = st["files"][0]["batches"]
    assert b["confirmed_queue"] == ["1"]
    assert b["rework_queue"] == ["2"]
    assert b["pending_queue"] == ["3"]

    # 3. 定向检出任务 1
    chk1 = dev_tasks_checkout(ws, task_id="1")
    assert chk1["task_id"] == "1"
    assert chk1["status"] == "🔨 执行中"

    # 尝试定向检出需返工的任务 2，应被安全阻断
    chk2 = dev_tasks_checkout(ws, task_id="2")
    assert "error" in chk2
    assert "需返工" in chk2["error"]

    # 4. 完成任务 1
    dev_tasks_complete(ws, "batch_test.md", "1", dod_output="ok")

    # 5. 此时已确认队列为空，自动领单应安全检测到 batch_finished 并提示交接
    chk_next = dev_tasks_checkout(ws)
    assert chk_next["task_id"] is None
    assert chk_next["batch_finished"] is True
    assert chk_next["has_rework_tasks"] is True
    assert chk_next["has_pending_tasks"] is True
    assert chk_next["handoff_recommended"] is True


def test_dev_tasks_set_bypass_and_anti_abuse(mock_workspace):
    ws = mock_workspace

    # 1. 纪律反滥用拦截：未传 user_authorized=True 时必须阻断
    res_abuse = dev_tasks_set_bypass(
        ws,
        action="enable",
        category="ui_styling",
        reason="Agent 想私自跳过流程",
        user_authorized=False,
    )
    assert res_abuse["success"] is False
    assert "纪律红线拦截" in res_abuse["error"]

    # 2. 理由为空或过短时必须阻断
    res_short = dev_tasks_set_bypass(
        ws,
        action="enable",
        category="ui_styling",
        reason="短",
        user_authorized=True,
    )
    assert res_short["success"] is False
    assert "参数校验失败" in res_short["error"]

    # 3. 正常开启 ui_styling 旁路（附带物理会话锁 session_id）
    res_ok = dev_tasks_set_bypass(
        ws,
        action="enable",
        category="ui_styling",
        reason="用户指示：微调前端表格内边距与表头颜色",
        user_authorized=True,
        duration_hours=2,
        session_id="conv-session-xyz",
    )
    assert res_ok["success"] is True
    assert res_ok["status"] == "enabled"
    assert "*.vue" in res_ok["patterns"]

    # 4. status 工具应透明公示旁路状态与物理会话锁，绝不静默
    st = dev_tasks_status(ws)
    assert st["session_bypass"] is not None
    assert st["session_bypass"]["active"] is True
    assert st["session_bypass"]["session_id"] == "conv-session-xyz"
    assert st["session_bypass"]["category"] == "ui_styling"
    assert "微调前端表格" in st["session_bypass"]["reason"]

    # 5. 支持 custom 类别
    res_custom = dev_tasks_set_bypass(
        ws,
        action="enable",
        category="custom",
        custom_patterns=["*.config.js", "vite.config.ts"],
        reason="用户指示：更新打包脚本配置",
        user_authorized=True,
    )
    assert res_custom["success"] is True
    assert res_custom["patterns"] == ["*.config.js", "vite.config.ts"]

    # 6. 关闭并清理旁路
    res_dis = dev_tasks_set_bypass(ws, action="disable")
    assert res_dis["success"] is True
    assert res_dis["status"] == "disabled"

    # status 检查确认旁路已清除
    st2 = dev_tasks_status(ws)
    assert st2["session_bypass"] is None


def test_dev_tasks_set_bypass_sanitization_and_utc(mock_workspace):
    ws = mock_workspace

    # 1. 尝试传入非法 session_id (含路径遍历/特殊字符)
    res_bad = dev_tasks_set_bypass(
        ws,
        action="enable",
        category="docs",
        session_id="../../malicious/path",
        reason="测试非法路径",
        user_authorized=True,
    )
    assert res_bad["success"] is False
    assert "非法的 session_id 格式" in res_bad["error"]

    # 2. 尝试传入超长 session_id (> 128 字符)
    res_overlong = dev_tasks_set_bypass(
        ws,
        action="enable",
        category="docs",
        session_id="a" * 150,
        reason="测试超长 session_id",
        user_authorized=True,
    )
    assert res_overlong["success"] is False
    assert "非法的 session_id 格式" in res_overlong["error"]

    # 3. 正常合规 UUID/十六进制 session_id
    res_ok = dev_tasks_set_bypass(
        ws,
        action="enable",
        category="docs",
        session_id="4b138e9a-d661-4e38-b0ff-dfe8f07cb4ee",
        reason="合规会话 ID 测试",
        user_authorized=True,
    )
    assert res_ok["success"] is True

    # 4. 超长 reason 截断至 500 字符
    long_reason = "理由前缀: " + ("x" * 600)
    res_trunc = dev_tasks_set_bypass(
        ws,
        action="enable",
        category="docs",
        session_id="valid-id-1",
        reason=long_reason,
        user_authorized=True,
    )
    assert res_trunc["success"] is True
    assert "超出 500 字符" in res_trunc["message"]
    # 检查 bypass 文件中确为 500 字符
    bypass_file = os.path.join(ws, ".agents", ".quench_bypass.json")
    with open(bypass_file, "r", encoding="utf-8") as f:
        bdata = json.load(f)
    assert len(bdata["reason"]) == 500



