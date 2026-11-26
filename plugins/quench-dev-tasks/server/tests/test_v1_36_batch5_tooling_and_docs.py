# -*- coding: utf-8 -*-
"""Batch 5 (Task 36.10) comprehensive unit tests for tooling, eager MCP sync, CLI, and CI gates."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SERVER_DIR = TESTS_DIR.parent
PLUGIN_DIR = SERVER_DIR.parent
PLUGIN_SCRIPTS_DIR = PLUGIN_DIR / "scripts"
REPO_ROOT = PLUGIN_DIR.parent.parent
REPO_SCRIPTS_DIR = REPO_ROOT / "scripts"

for _p in (str(SERVER_DIR), str(PLUGIN_SCRIPTS_DIR), str(REPO_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_prompt_surface  # noqa: E402
import check_test_duration_baselines as dur_gate  # noqa: E402
import check_test_tiering_invariants as tier_gate  # noqa: E402
import cli  # noqa: E402
import config_sync  # noqa: E402
import conftest  # noqa: E402
import ide_schema_export  # noqa: E402
import install  # noqa: E402
import probe_client_capabilities as probe_cap  # noqa: E402
from rules_exporter import RulesExporter  # noqa: E402
from schema_validator import lint_task_physical_feasibility  # noqa: E402
from tool_surface_constants import EXPECTED_TOOL_NAMES  # noqa: E402


def test_render_agents_mcp_config_preserves_all_16_eager_tools(tmp_path: Path) -> None:
    """config_sync.render_agents_mcp_config 必须将全部 16 个 eager:true 工具完整同步到工作区 quench-dev-tasks 键。"""
    rendered = config_sync.render_agents_mcp_config(
        project_root=str(tmp_path),
        python_exe=sys.executable,
        plugin_dir=str(PLUGIN_DIR),
    )
    assert "mcpServers" in rendered
    assert "quench-dev-tasks" in rendered["mcpServers"]
    tools = rendered["mcpServers"]["quench-dev-tasks"].get("tools")
    assert isinstance(tools, dict)
    assert set(tools.keys()) == set(EXPECTED_TOOL_NAMES)
    assert len(tools) == 16
    for name in EXPECTED_TOOL_NAMES:
        assert tools[name] == {"eager": True}


def test_cli_status_archive_verbosity_full_and_confirmed_block(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """cli.cmd_status 与 cmd_archive 显式传递 verbosity='full'，且 cmd_archive 拦截 ✅ 已确认 状态。"""
    with patch("server.dev_tasks_status") as mock_status:
        mock_status.return_value = {
            "project_name": "Demo",
            "dev_tasks_dir": str(tmp_path / "docs" / "dev_tasks"),
            "files": [],
            "active_task": None,
            "session_bypass": None,
        }
        rc = cli.cmd_status(str(tmp_path), plain=True)
        assert rc == 0
        mock_status.assert_called_once_with(os.path.abspath(str(tmp_path)), verbosity="full")

    with patch("server.dev_tasks_status") as mock_status, patch("server.dev_tasks_archive") as mock_archive:
        mock_status.return_value = {
            "files": [
                {
                    "name": "batch.md",
                    "summary": {"⬜ 待确认": 0, "✅ 已确认": 2, "🔨 执行中": 0, "🔄 需返工": 0},
                }
            ]
        }
        rc_arch = cli.cmd_archive(str(tmp_path))
        assert rc_arch == 1
        mock_status.assert_called_once_with(os.path.abspath(str(tmp_path)), verbosity="full")
        mock_archive.assert_not_called()
        out = capsys.readouterr().out
        assert "已确认:2" in out


def test_cli_reviewer_debug_execute_calls_client_complete(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """cmd_reviewer_debug(dry_run=False) 在客户端可用时发起有界 client.complete 探测。"""
    fake_cfg = MagicMock()
    fake_re_cfg = MagicMock(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://example.invalid/v1",
        thinking=False,
        timeout_seconds=5,
    )
    fake_cfg.reviewer_engine = fake_re_cfg

    fake_client = MagicMock()
    fake_client.is_available.return_value = True
    fake_client.resolve_api_key.return_value = "sk-test-1234567890"
    fake_client.complete.return_value = {"content": "pong"}

    with (
        patch("project_config.load_project_config", return_value=fake_cfg),
        patch("project_config.create_reviewer_client", return_value=fake_client),
        patch("reviewer_engine.ReviewerClient", return_value=fake_client),
    ):
        rc = cli.cmd_reviewer_debug(str(tmp_path), dry_run=False, query="health ping", plain=True, as_json=True)
    assert rc == 0
    fake_client.complete.assert_called_once()
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "execute_success"
    assert payload["response_preview"] == "pong"


def test_schema_validator_dry_run_requires_exact_relative_path_for_new_files(tmp_path: Path) -> None:
    """pytest dry-run 缺失文件豁免必须按规范化相对路径匹配，禁止裸 basename 误豁免。"""
    task_wrong_dir = {
        "id": "1.1",
        "title": "错误目录测试",
        "affected_files": ["[NEW] tests/unit/test_target.py"],
        "root_cause_and_goal": "根因",
        "type_contracts": "无",
        "steps": ["1. 一", "2. 二"],
        "defensive_checks": ["无"],
        "dod_commands": ["pytest other/dir/test_target.py -q"],
    }
    res_bad = lint_task_physical_feasibility(str(tmp_path), task_wrong_dir)
    assert res_bad.passed is False

    task_exact = dict(task_wrong_dir, dod_commands=["pytest tests/unit/test_target.py -q"])
    res_ok = lint_task_physical_feasibility(str(tmp_path), task_exact)
    assert res_ok.passed is True


def test_ide_schema_export_rejects_symlink_segment_before_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ide_schema_export.run_cli 在 resolve() 前检查路径各段 is_reparse_point_or_symlink。"""
    monkeypatch.setattr(ide_schema_export, "_REPO_ROOT", tmp_path)
    sub = tmp_path / "docs" / "architecture"
    sub.mkdir(parents=True)

    with patch.object(
        ide_schema_export,
        "is_reparse_point_or_symlink",
        side_effect=lambda p: Path(p).name == "architecture",
    ):
        rc = ide_schema_export.run_cli(
            ["--check", "--cache-dir", str(sub)],
            introspect=lambda: {},
        )
    assert rc == ide_schema_export.EXIT_INVALID


def test_check_prompt_surface_posonly_kwonly_fences_and_skip_dirs(tmp_path: Path) -> None:
    """check_prompt_surface 提取 posonly/kwonly 参数、跳过 .venv/node_modules、精确跟踪 ~~~ 与 ```` 围栏。"""
    srv = tmp_path / "server.py"
    srv.write_text(
        "@mcp.tool()\n"
        "def demo(a: str, /, b: int, *, c: bool = False) -> dict:\n"
        "    return {}\n",
        encoding="utf-8",
    )
    sigs = check_prompt_surface.extract_server_signatures(srv)
    assert sigs["demo"] == frozenset({"a", "b", "c"})

    # .venv 中的违规文件被跳过；~~~ 与 ```` 嵌套围栏正确闭合
    venv_md = tmp_path / ".venv" / "bad.md"
    venv_md.parent.mkdir(parents=True)
    venv_md.write_text("```python\ndemo(unknown=1)\n```\n", encoding="utf-8")

    doc_md = tmp_path / "guide.md"
    doc_md.write_text(
        "````markdown\n```python\nnot_executed(unknown=1)\n```\n````\n"
        "~~~python\ndemo(bad_kw=1)\n~~~\n",
        encoding="utf-8",
    )
    findings = check_prompt_surface.check_example_call_keywords([tmp_path], sigs)
    assert len(findings) == 1
    assert "bad_kw" in findings[0].message


def test_duration_baselines_warn_line_streak_and_iso_timestamp(tmp_path: Path) -> None:
    """check_test_duration_baselines 正确比较 warn_line、持久化 panic_streak 并写入 UTC ISO 时间戳。"""
    sidecar = tmp_path / "tier2_baseline.json"
    assert dur_gate.save_tier2_baseline(40.0, sidecar, panic_streak=0) is True
    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "T" in raw["updated_at"]

    # 42.0 > 40.0 但 <= warn_line (46.0) -> OK，不误报 warning
    ok1, _, logs1 = dur_gate.run_tier2_benchmark(
        tmp_path,
        runner_func=lambda cmd, env, timeout: (0, "10 passed in 42.0s", 42.0),
        assert_self_repo=False,
        baseline_path=sidecar,
    )
    assert ok1 is True
    assert any("Tier-2 baseline OK" in l for l in logs1)

    # 第一次 > panic_line (52.0) -> streak=1 降级放行，第二次连续超限 -> PANIC (False)
    ok2, _, _ = dur_gate.run_tier2_benchmark(
        tmp_path,
        runner_func=lambda cmd, env, timeout: (0, "10 passed in 55.0s", 55.0),
        assert_self_repo=False,
        baseline_path=sidecar,
    )
    assert ok2 is True
    ok3, _, logs3 = dur_gate.run_tier2_benchmark(
        tmp_path,
        runner_func=lambda cmd, env, timeout: (0, "10 passed in 55.0s", 55.0),
        assert_self_repo=False,
        baseline_path=sidecar,
    )
    assert ok3 is False
    assert any("panic threshold exceeded" in l for l in logs3)


def test_tiering_invariants_aligned_13_modules_and_python_env_scrubbed() -> None:
    """TIER1_TARGET_MODULES 必须与 conftest.TIER1_TARGET_REL_FILES 的 13 个模块完全对齐并清洗 PYTHONPATH。"""
    assert len(conftest.TIER1_TARGET_REL_FILES) == 13
    assert set(tier_gate.TIER1_TARGET_MODULES) == set(conftest.TIER1_TARGET_REL_FILES)

    cleaned = tier_gate.sanitized_env(
        {"PYTHONPATH": "/evil", "PYTHONHOME": "/bad", "PYTHONUSERBASE": "/u", "SAFE": "1"}
    )
    assert "PYTHONPATH" not in cleaned
    assert "PYTHONHOME" not in cleaned
    assert "PYTHONUSERBASE" not in cleaned
    assert cleaned["SAFE"] == "1"


def test_probe_sse_stream_and_install_rollback_confinement(tmp_path: Path) -> None:
    """probe_client_capabilities 支持 text/event-stream；install.rollback_configuration 拦截 ../ 越界。"""
    sse_lines = [
        b"event: message\n",
        b'data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","serverInfo":{"name":"sse-srv","version":"1.0"},"capabilities":{"tools":{}}}}\n',
        b"\n",
    ]
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Type": "text/event-stream"}
    mock_resp.readline.side_effect = sse_lines + [b""]
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_cm):
        rep = probe_cap.probe_client_capabilities("sse", "http://localhost:9000/sse", timeout_ms=1000)
    assert rep["status"] == "ok"
    assert rep["client_name"] == "sse-srv"

    # rollback path traversal guard
    plugin_dir = tmp_path / "plugins" / "quench-dev-tasks"
    plugin_dir.mkdir(parents=True)
    backup_file = tmp_path / "bad_backup.json"
    backup_file.write_text(json.dumps({"files": {"../../outside.txt": "pwned"}}), encoding="utf-8")
    assert install.rollback_configuration(str(plugin_dir), str(backup_file)) is False
    assert not (tmp_path.parent / "outside.txt").exists()

    # rules_exporter atomic write sanity
    RulesExporter.export_all(project_root=str(tmp_path), force=True)
    assert (tmp_path / ".cursorrules").is_file()
    assert (tmp_path / ".cursor" / "rules" / "quench-dev-tasks.mdc").is_file()


def test_template_quench_stack_and_docs_audit_gate_load_zero_warnings(tmp_path: Path) -> None:
    """templates/quench_stack.yaml 与 docs/configuration.md 中的 audit_gate 示例均可被 load_project_config 零错误零告警解析。"""
    import re
    import warnings
    import yaml
    from project_config import load_project_config

    # 1. Rendered templates/quench_stack.yaml
    ws_tpl = tmp_path / "ws_tpl"
    (ws_tpl / ".agents").mkdir(parents=True)
    tpl_text = (PLUGIN_DIR / "templates" / "quench_stack.yaml").read_text(encoding="utf-8")
    rendered = tpl_text.replace("__PROJECT_NAME__", "TemplateVerify")
    (ws_tpl / ".agents" / "quench_stack.yaml").write_text(rendered, encoding="utf-8")

    with warnings.catch_warnings(record=True) as rec1:
        warnings.simplefilter("always")
        cfg1 = load_project_config(str(ws_tpl))
    assert cfg1.project_name == "TemplateVerify"
    assert rec1 == [], f"Unexpected warnings loading templates/quench_stack.yaml: {[str(w.message) for w in rec1]}"

    # 2. docs/configuration.md §4.1 audit_gate YAML block
    conf_doc = (REPO_ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    sec_match = re.search(r"### 4\.1 .*?```yaml\n(.*?)```", conf_doc, flags=re.DOTALL)
    assert sec_match is not None
    audit_block = yaml.safe_load(sec_match.group(1))
    assert isinstance(audit_block, dict) and "audit_gate" in audit_block

    ws_doc = tmp_path / "ws_doc"
    (ws_doc / ".agents").mkdir(parents=True)
    doc_cfg_data = {
        "schema_version": "1.0",
        "project_name": "DocAuditVerify",
        "audit_gate": audit_block["audit_gate"],
    }
    (ws_doc / ".agents" / "quench_stack.yaml").write_text(yaml.safe_dump(doc_cfg_data), encoding="utf-8")

    with warnings.catch_warnings(record=True) as rec2:
        warnings.simplefilter("always")
        cfg2 = load_project_config(str(ws_doc))
    assert cfg2.audit_gate.enabled is True
    assert cfg2.audit_gate.accepted_sources == ("reviewer_client",)
    assert rec2 == [], f"Unexpected warnings loading docs/configuration.md audit_gate: {[str(w.message) for w in rec2]}"

