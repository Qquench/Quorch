# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import inspect
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
import yaml

from project_config import (
    ConfigError,
    ConfigFault,
    canonical_artifact_ref,
    load_project_config,
    _validate_accepted_sources,
)
from state_machine import TaskItem
from server import (
    _resolve_record_source,
    _check_audit_gate,
    _inject_harness_next_action,
    dev_tasks_refine_spec,
    dev_tasks_status,
    dev_tasks_confirm,
    dev_tasks_propose,
)
from runtime_mode import (
    EffectiveModeSnapshot,
    AutopilotRuntimeState,
    update_runtime_mode,
)


def _setup_ws(tmp_path, gate_kwargs=None):
    ws = str(tmp_path)
    agents_dir = os.path.join(ws, ".agents")
    tasks_dir = os.path.join(ws, "docs", "dev_tasks")
    logs_dir = os.path.join(ws, ".agents", "logs", "reviewer")
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(tasks_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    g_cfg = {
        "enabled": True,
        "on_missing_record": "block",
        "on_degraded": "block",
        "on_internal_error": "allow",
    }
    if gate_kwargs:
        g_cfg.update(gate_kwargs)

    raw_yaml = {
        "project_name": "TestChannelProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "governance_scope": {
            "managed_paths": ["plugins/**", "src/**"],
            "unmanaged_paths": ["docs/**"],
        },
        "observability": {"verdict_path": ".agents/logs/reviewer/verdicts.jsonl"},
        "audit_gate": g_cfg,
    }
    with open(os.path.join(agents_dir, "quench_stack.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(raw_yaml, f)

    cfg = load_project_config(ws)
    return ws, os.path.join(ws, ".agents", "logs", "reviewer", "verdicts.jsonl"), cfg


def _write_verdict_line(log_path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def test_refine_spec_rejects_self_reported_review_source():
    """断言 dev_tasks_refine_spec 签名严禁引入自报凭据参数 (INV-3 防角色扮演硬红线)。"""
    fn = getattr(dev_tasks_refine_spec, "fn", dev_tasks_refine_spec)
    params = inspect.signature(fn).parameters
    assert "review_source" not in params
    assert "review_verdict" not in params
    assert "review_findings_digest" not in params


def test_accepted_sources_standard_mode_forbids_host_subagent():
    """断言 standard 模式拒绝包含 host_subagent 的 accepted_sources 配置。"""
    with pytest.raises(ConfigError) as exc_info:
        _validate_accepted_sources(["reviewer_client", "host_subagent"], "standard")
    assert ConfigFault.SAFETY_DOWNGRADE_DENIED in str(exc_info.value)


def test_accepted_sources_auto_fallback_locked_to_reviewer_client():
    """断言 auto_fallback 锁定为仅允许 reviewer_client。"""
    with pytest.raises(ConfigError) as exc_info:
        _validate_accepted_sources(["reviewer_client", "host_subagent"], "auto_fallback")
    assert ConfigFault.SAFETY_DOWNGRADE_DENIED in str(exc_info.value)


def test_empty_string_source_is_not_resurrected_as_legacy():
    """断言空字符串 source 不被当作缺失而复活为 legacy，明确返回 record_unparsable。"""
    src, deg = _resolve_record_source({"source": ""})
    assert src is None
    assert deg == "record_unparsable"


def test_null_source_is_legacy_compat():
    """断言 null / None source 作为历史存量数据平滑兼容为 reviewer_client。"""
    src, deg = _resolve_record_source({"source": None})
    assert src == "reviewer_client"
    assert deg is None


def test_missing_source_key_is_legacy_compat():
    """断言缺失 source 键的存量记录兼容为 reviewer_client。"""
    src, deg = _resolve_record_source({})
    assert src == "reviewer_client"
    assert deg is None


def test_non_str_source_yields_record_unparsable():
    """断言非 str 类型的 source 返回 record_unparsable。"""
    src1, deg1 = _resolve_record_source({"source": 12345})
    assert src1 is None
    assert deg1 == "record_unparsable"

    src2, deg2 = _resolve_record_source({"source": ["reviewer_client"]})
    assert src2 is None
    assert deg2 == "record_unparsable"


def test_record_unparsable_routes_through_effective_on_degraded(tmp_path):
    """断言 record_unparsable 归入 degraded_family，严格受 policy.on_degraded 约束。"""
    ws, log_path, cfg = _setup_ws(tmp_path, {"on_degraded": "block"})
    task_file = os.path.join(ws, "docs", "dev_tasks", "task.md")
    ref = canonical_artifact_ref(ws, task_file, "1.1")
    now_wall = datetime.now(timezone.utc).isoformat()

    # 写入 source 为空串的畸变凭据
    _write_verdict_line(log_path, {
        "job_id": "job_corrupt",
        "session_id": "s1",
        "created_wall_utc": now_wall,
        "updated_wall_utc": now_wall,
        "context_files": [ref],
        "source": "",
        "verdict": "approve",
        "status": "ok",
    })

    task = TaskItem(id="1.1", title="T", status="⬜ 待确认", line_number=1, raw_line="### 任务 1.1")
    task.affected_files = ["[MODIFY] src/core.py"]

    # 1. on_degraded == "block" 必须被拒绝
    gate_res_block = _check_audit_gate(ws, task_file, task, cfg)
    assert gate_res_block["allowed"] is False
    assert gate_res_block["reason"] == "record_unparsable"

    # 2. on_degraded == "warn" 允许通过
    _, _, cfg_warn = _setup_ws(tmp_path, {"on_degraded": "warn"})
    gate_res_warn = _check_audit_gate(ws, task_file, task, cfg_warn)
    assert gate_res_warn["allowed"] is True
    assert gate_res_warn["reason"] == "record_unparsable"


def test_harness_cas_mismatch_recomputes_and_reenvelopes(tmp_path):
    """断言 Autopilot Harness 在命中 CAS mismatch 时重新计算并在 reason 追加标记重封包。"""
    ws, _, cfg = _setup_ws(tmp_path)

    # 创建任务单文件
    tf_path = os.path.join(ws, "docs", "dev_tasks", "2026-10-24_test.md")
    with open(tf_path, "w", encoding="utf-8") as f:
        f.write("# 任务单\n\n### 任务 1.1 ⬜ 待确认 — 测试任务\n#### 【涉及文件】\n```\nsrc/app.py\n```\n")

    # 配置运行时状态：开启 autopilot stop_at="after_propose"
    update_runtime_mode(
        workspace_root=ws,
        stop_at="after_propose",
        task_file="2026-10-24_test.md",
        external_api_available=True,
    )

    # 模拟 update_runtime_mode 在 consume_stop_at 时返回 consume_mismatch=True
    orig_update = update_runtime_mode

    def mock_update(*args, **kwargs):
        if kwargs.get("consume_stop_at"):
            # 返回 mismatch
            fresh_snap = orig_update(ws, external_api_available=True)[0]
            return (fresh_snap, False, {"consume_mismatch": True})
        return orig_update(*args, **kwargs)

    res_data = {"ok": True}
    with patch("server.update_runtime_mode", side_effect=mock_update):
        _inject_harness_next_action(
            workspace_root=ws,
            tool_name="dev_tasks_propose",
            result_data=res_data,
            last_success=True,
            task_file="2026-10-24_test.md",
            config=cfg,
        )

    assert "harness_next_action" in res_data
    harness = res_data["harness_next_action"]
    assert "[recomputed after CAS mismatch]" in harness["reason"]


def test_explicit_inverted_mode_confirm_allows_without_verdicts(tmp_path):
    """显式 switch_mode='inverted' 下无 verdicts.jsonl 或无匹配记录时 dev_tasks_confirm 以 explicit_inverted_orchestrator 放行。"""
    ws, log_path, cfg = _setup_ws(tmp_path)
    if os.path.exists(log_path):
        os.remove(log_path)
    tf_name = "2026-10-31_test.md"
    tasks = [
        {
            "id": "1.1",
            "title": "Inverted task",
            "affected_files": ["[MODIFY] src/core.py"],
            "root_cause_and_goal": "G",
            "type_contracts": "C",
            "steps": ["1"],
            "defensive_checks": ["-"],
            "dod_commands": ["pytest"],
        },
    ]
    dev_tasks_propose(ws, tf_name, tasks)
    status_res = dev_tasks_status(workspace_root=ws, switch_mode="inverted")
    assert status_res["effective_mode"] == "inverted"
    assert status_res["mode_source"] == "explicit"

    conf = dev_tasks_confirm(workspace_root=ws, task_file=tf_name, task_ids=["1.1"], action="confirm")
    assert len(conf.get("updated", [])) == 1
    assert conf["updated"][0]["id"] == "1.1"


def test_auto_fallback_inverted_mode_confirm_blocked_when_no_record(tmp_path):
    """auto_fallback 委派模式下无记录仍被 no_matching_record / log_missing 阻断。"""
    ws, log_path, cfg = _setup_ws(tmp_path)
    if os.path.exists(log_path):
        os.remove(log_path)
    tf_name = "2026-10-31_test.md"
    tasks = [
        {
            "id": "1.1",
            "title": "Auto fallback task",
            "affected_files": ["[MODIFY] src/core.py"],
            "root_cause_and_goal": "G",
            "type_contracts": "C",
            "steps": ["1"],
            "defensive_checks": ["-"],
            "dod_commands": ["pytest"],
        },
    ]
    dev_tasks_propose(ws, tf_name, tasks)
    with patch("server._is_external_api_available", return_value=False):
        status_res = dev_tasks_status(workspace_root=ws)
        assert status_res["effective_mode"] == "inverted"
        assert status_res["mode_source"] == "auto_fallback"

        conf = dev_tasks_confirm(workspace_root=ws, task_file=tf_name, task_ids=["1.1"], action="confirm")
        assert conf.get("ok") is False
        assert conf["reason"] in ("log_missing", "no_matching_record")


def test_explicit_inverted_mode_confirm_blocked_when_matching_rework(tmp_path):
    """显式 inverted 模式下若账本已存在匹配 verdict='rework' 记录仍被 record_rework 阻断。"""
    ws, log_path, cfg = _setup_ws(tmp_path)
    tf_name = "2026-10-31_test.md"
    tasks = [
        {
            "id": "1.1",
            "title": "Rework task",
            "affected_files": ["[MODIFY] src/core.py"],
            "root_cause_and_goal": "G",
            "type_contracts": "C",
            "steps": ["1"],
            "defensive_checks": ["-"],
            "dod_commands": ["pytest"],
        },
    ]
    dev_tasks_propose(ws, tf_name, tasks)
    status_res = dev_tasks_status(workspace_root=ws, switch_mode="inverted")
    assert status_res["effective_mode"] == "inverted"
    assert status_res["mode_source"] == "explicit"

    target_path = os.path.join(ws, "docs", "dev_tasks", tf_name)
    ref = canonical_artifact_ref(ws, target_path, "1.1")
    now_wall = datetime.now(timezone.utc).isoformat()
    _write_verdict_line(log_path, {
        "job_id": "job_rwk",
        "session_id": "s1",
        "created_wall_utc": now_wall,
        "updated_wall_utc": now_wall,
        "context_files": [ref],
        "source": "reviewer_client",
        "verdict": "rework",
        "status": "ok",
    })

    conf = dev_tasks_confirm(workspace_root=ws, task_file=tf_name, task_ids=["1.1"], action="confirm")
    assert conf.get("ok") is False
    assert conf["reason"] == "record_rework"

