# -*- coding: utf-8 -*-
"""Tests for DoD Rigid Test Guard and CLI Engine Health Check.

Covers:
1. _mask_secret security masking
2. DoD physical gate: rejection on governed changes without assertions
3. DoD physical gate: exemption whitelist handling
4. DoD physical gate: natural pass for non-governed / docs-only changes
5. DoD physical gate: untracked new test files assertion detection
6. DoD physical gate: tracked test file diff scanning (no false positives from legacy code)
7. DoD degradation on non-git environment
8. CLI check-engine execution, exit codes, JSON schema, and secret masking
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from cli import _mask_secret, cmd_check_engine, main
from project_config import QuenchStackConfig, ReviewerEngineConfig
from server import (
    _EXEMPTION_PATTERN,
    _TEST_FILE_PATTERN,
    _audit_test_changes,
    dev_tasks_checkout,
    dev_tasks_complete,
    dev_tasks_confirm,
    dev_tasks_propose,
    dev_tasks_status,
)


# ==============================================================================
# Helper fixtures
# ==============================================================================

@pytest.fixture
def git_workspace(tmp_path):
    """Create a temporary initialized git repository with Quench project configuration."""
    ws = tmp_path / "git_ws"
    ws.mkdir()
    ws_str = str(ws)

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=ws_str, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "QuenchTester"], cwd=ws_str, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@quench.local"], cwd=ws_str, capture_output=True, check=True)

    # Setup .agents/quench_stack.yaml
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    config_data = {
        "schema_version": "1.0",
        "project_name": "DoDGuardProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "changelog_path": "CHANGELOG.md",
        "test_dir": "tests",
        "test_runner": "pytest",
        "fast_track_rules": {"allow_untracked_patterns": []},
        "reviewer_engine": {
            "provider": "deepseek",
            "model": "deepseek-flash",
            "api_key_env": "DEEPSEEK_API_KEY_Quench",
            "thinking": True,
        },
    }
    with open(agents_dir / "quench_stack.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    # Create initial commit to establish HEAD
    init_readme = ws / "README.md"
    init_readme.write_text("# DoD Guard Project\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=ws_str, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=ws_str, capture_output=True, check=True)

    return ws


def _make_task_spec(task_id: str, title: str, affected_files: list[str]) -> dict:
    """Helper to create schema-compliant six core field task dictionary."""
    return {
        "id": task_id,
        "title": title,
        "affected_files": affected_files,
        "root_cause_and_goal": "Goal and root cause explained.",
        "type_contracts": "Contract definitions.",
        "steps": ["1. Execute step one", "2. Execute step two"],
        "defensive_checks": ["- Defend boundary"],
        "dod_commands": ["pytest"],
    }


# ==============================================================================
# 1. Mask secret tests
# ==============================================================================

def test_mask_secret_coverage():
    """Verify _mask_secret handles None, empty, short, and long secrets properly."""
    assert _mask_secret(None) == "NOT SET"
    assert _mask_secret("") == "NOT SET"
    assert _mask_secret("   ") == "NOT SET"
    assert _mask_secret("12345678") == "****"
    assert _mask_secret("short") == "****"
    assert _mask_secret("sk-1234567890abcdef") == "sk-1****cdef"
    assert _mask_secret("very_long_secret_api_key_quench_1234") == "very****1234"


# ==============================================================================
# 2. Exemption pattern regex tests
# ==============================================================================

def test_exemption_pattern_whitelist():
    """Verify strict whitelist of exemption tokens."""
    assert _EXEMPTION_PATTERN.search("[EXEMPTION: docs-only]")
    assert _EXEMPTION_PATTERN.search("[EXEMPTION: config-only]")
    assert _EXEMPTION_PATTERN.search("[EXEMPTION: non-behavioral-refactor]")
    assert _EXEMPTION_PATTERN.search("Fixed typo [EXEMPTION:   docs-only  ] thanks")

    # Invalid exemptions
    assert not _EXEMPTION_PATTERN.search("[EXEMPTION: bugfix]")
    assert not _EXEMPTION_PATTERN.search("[EXEMPTION: bypass]")
    assert not _EXEMPTION_PATTERN.search("No test needed")
    assert not _EXEMPTION_PATTERN.search("[EXEMPTION:]")


# ==============================================================================
# 3. Test File pattern regex tests
# ==============================================================================

def test_test_file_pattern_matches():
    """Verify _TEST_FILE_PATTERN matches standard test file layouts."""
    assert _TEST_FILE_PATTERN.search("tests/test_core.py")
    assert _TEST_FILE_PATTERN.search("plugins/server/tests/test_guard.py")
    assert _TEST_FILE_PATTERN.search("tests/sub/test_feature.py")
    assert _TEST_FILE_PATTERN.search("test/test_basic.py")
    assert _TEST_FILE_PATTERN.search("unit_test.py")

    # Non test files
    assert not _TEST_FILE_PATTERN.search("src/main.py")
    assert not _TEST_FILE_PATTERN.search("server/cli.py")
    assert not _TEST_FILE_PATTERN.search("docs/tests.md")


# ==============================================================================
# 4. DoD Rejection when governed code changes without test assertions
# ==============================================================================

def test_dod_guard_rejects_governed_changes_without_test(git_workspace):
    """When governed code is modified without test assertions, complete is rejected."""
    ws = str(git_workspace)

    # 1. Propose and confirm a task
    prop = dev_tasks_propose(
        workspace_root=ws,
        task_file_name="task_test.md",
        tasks=[_make_task_spec("1", "Unchecked feature", ["[NEW] src/logic.py"])],
    )
    assert prop["created"] is True
    task_file = prop["file_path"]
    dev_tasks_confirm(ws, task_file, ["1"], action="confirm")
    dev_tasks_checkout(ws, task_file, "1")

    # 2. Modify governed code (src/logic.py) without adding test assertions
    src_dir = git_workspace / "src"
    src_dir.mkdir()
    logic_file = src_dir / "logic.py"
    logic_file.write_text("def run():\n    return 42\n", encoding="utf-8")

    # 3. Attempt dev_tasks_complete without test files
    res = dev_tasks_complete(ws, task_file, "1", dod_output="Tests executed")

    assert res["status"] == "rejected"
    assert "audit" in res
    assert res["audit"]["passed"] is False
    assert len(res["audit"]["governed_code_changed"]) > 0
    assert "guidance" in res
    assert "【DoD 物理门禁拦截" in res["guidance"]

    # Check task status in file remains '🔨 执行中'
    status_res = dev_tasks_status(ws)
    assert status_res["active_task"] is not None
    assert status_res["active_task"]["id"] == "1"
    assert status_res["active_task"]["status"] == "🔨 执行中"

    # Check hook log was written
    hook_log = git_workspace / ".agents" / ".quench_hook.log"
    assert hook_log.exists()
    assert "[DOD GUARD REJECTED]" in hook_log.read_text(encoding="utf-8")


# ==============================================================================
# 5. DoD Exemption acceptance
# ==============================================================================

def test_dod_guard_accepts_exemption(git_workspace):
    """When governed code is changed but explicit [EXEMPTION: ...] is provided, task is accepted."""
    ws = str(git_workspace)

    prop = dev_tasks_propose(
        workspace_root=ws,
        task_file_name="task_test.md",
        tasks=[_make_task_spec("1", "Config refactor", ["[NEW] src/settings.py"])],
    )
    assert prop["created"] is True
    task_file = prop["file_path"]
    dev_tasks_confirm(ws, task_file, ["1"], action="confirm")
    dev_tasks_checkout(ws, task_file, "1")

    # Modify governed code
    src_dir = git_workspace / "src"
    src_dir.mkdir(exist_ok=True)
    settings_file = src_dir / "settings.py"
    settings_file.write_text("CONFIG_VERSION = 2\n", encoding="utf-8")

    # Complete with exemption
    res = dev_tasks_complete(
        ws,
        task_file,
        "1",
        dod_output="Manual verify",
        test_evidence="[EXEMPTION: config-only] Refactored constants only",
    )

    assert res["status"] == "completed"
    assert res["audit"]["passed"] is True
    assert res["audit"]["exempted"] is True
    assert res["audit"]["exemption_reason"] == "config-only"

    # Check task is completed in status
    status_res = dev_tasks_status(ws)
    assert status_res["active_task"] is None


# ==============================================================================
# 6. DoD Natural Pass on docs-only / unmanaged changes
# ==============================================================================

def test_dod_guard_natural_pass_on_docs_only(git_workspace):
    """When only documentation or unmanaged assets change, audit naturally passes without test assertions."""
    ws = str(git_workspace)

    prop = dev_tasks_propose(
        workspace_root=ws,
        task_file_name="task_test.md",
        tasks=[_make_task_spec("1", "Update markdown doc", ["[MODIFY] docs/guide.md"])],
    )
    assert prop["created"] is True
    task_file = prop["file_path"]
    dev_tasks_confirm(ws, task_file, ["1"], action="confirm")
    dev_tasks_checkout(ws, task_file, "1")

    # Modify only doc file
    docs_dir = git_workspace / "docs"
    docs_dir.mkdir(exist_ok=True)
    doc_file = docs_dir / "guide.md"
    doc_file.write_text("# User Guide\nUpdated.\n", encoding="utf-8")

    res = dev_tasks_complete(ws, task_file, "1", dod_output="Reviewed doc")
    assert res["status"] == "completed"
    assert res["audit"]["passed"] is True
    assert len(res["audit"]["governed_code_changed"]) == 0


# ==============================================================================
# 7. DoD Untracked test file with assertions is recognized
# ==============================================================================

def test_dod_guard_untracked_test_file_recognized(git_workspace):
    """Untracked (??) test file with assert is read and satisfies DoD gate."""
    ws = str(git_workspace)

    prop = dev_tasks_propose(
        workspace_root=ws,
        task_file_name="task_test.md",
        tasks=[_make_task_spec("1", "Feature with test", ["[NEW] src/calc.py", "[NEW] tests/test_calc.py"])],
    )
    assert prop["created"] is True
    task_file = prop["file_path"]
    dev_tasks_confirm(ws, task_file, ["1"], action="confirm")
    dev_tasks_checkout(ws, task_file, "1")

    # Modify governed code
    src_dir = git_workspace / "src"
    src_dir.mkdir(exist_ok=True)
    calc_file = src_dir / "calc.py"
    calc_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    # Add untracked test file with assertion
    tests_dir = git_workspace / "tests"
    tests_dir.mkdir(exist_ok=True)
    test_file = tests_dir / "test_calc.py"
    test_file.write_text(
        "from src.calc import add\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )

    res = dev_tasks_complete(ws, task_file, "1", dod_output="1 passed")

    assert res["status"] == "completed"
    assert res["audit"]["passed"] is True
    assert res["audit"]["assertions_found"] is True
    assert "assert " in res["audit"]["detected_markers"]
    assert any("test_calc.py" in tf for tf in res["audit"]["test_files_changed"])


# ==============================================================================
# 8. DoD Tracked test file diff inspection (prevents false positive from legacy)
# ==============================================================================

def test_dod_guard_tracked_test_diff_inspection(git_workspace):
    """Tracked test file only counts newly added assertion lines, not historical ones."""
    ws = str(git_workspace)

    # 1. Commit a test file with old assertions first
    tests_dir = git_workspace / "tests"
    tests_dir.mkdir(exist_ok=True)
    old_test = tests_dir / "test_legacy.py"
    old_test.write_text(
        "def test_legacy():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=ws, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Add legacy test"], cwd=ws, capture_output=True, check=True)

    # 2. Start a new task
    prop = dev_tasks_propose(
        workspace_root=ws,
        task_file_name="task_test.md",
        tasks=[_make_task_spec("1", "Needs new test", ["[NEW] src/service.py"])],
    )
    assert prop["created"] is True
    task_file = prop["file_path"]
    dev_tasks_confirm(ws, task_file, ["1"], action="confirm")
    dev_tasks_checkout(ws, task_file, "1")

    # 3. Modify governed code
    src_dir = git_workspace / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / "service.py").write_text("def serve(): pass\n", encoding="utf-8")

    # 4. Modify legacy test file with ONLY a comment (no new assert line added)
    old_test.write_text(
        "# Just a comment added, no new assert\n"
        "def test_legacy():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    # Attempt complete -> Should be rejected because no NEW assertion in diff!
    res_fail = dev_tasks_complete(ws, task_file, "1", dod_output="done")
    assert res_fail["status"] == "rejected"
    assert res_fail["audit"]["assertions_found"] is False

    # 5. Now add a new assertion line
    old_test.write_text(
        "# Just a comment added\n"
        "def test_legacy():\n"
        "    assert True\n"
        "    assert 1 == 1\n",
        encoding="utf-8",
    )

    res_ok = dev_tasks_complete(ws, task_file, "1", dod_output="done")
    assert res_ok["status"] == "completed"
    assert res_ok["audit"]["passed"] is True
    assert res_ok["audit"]["assertions_found"] is True


# ==============================================================================
# 9. DoD Non-git environment graceful degradation
# ==============================================================================

def test_dod_guard_degrades_gracefully_in_non_git(tmp_path):
    """In non-git directories, audit sets degraded=True and does not crash or block completion."""
    ws = tmp_path / "nongit_ws"
    ws.mkdir()
    ws_str = str(ws)

    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    config_data = {
        "project_name": "NonGitProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "changelog_path": "CHANGELOG.md",
        "test_dir": "tests",
        "test_runner": "pytest",
    }
    with open(agents_dir / "quench_stack.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    prop = dev_tasks_propose(
        workspace_root=ws_str,
        task_file_name="task_test.md",
        tasks=[_make_task_spec("1", "Offline code", ["[NEW] main.py"])],
    )
    assert prop["created"] is True
    task_file = prop["file_path"]
    dev_tasks_confirm(ws_str, task_file, ["1"], action="confirm")
    dev_tasks_checkout(ws_str, task_file, "1")

    # Modify code
    (ws / "main.py").write_text("print('hello')\n", encoding="utf-8")

    res = dev_tasks_complete(ws_str, task_file, "1", dod_output="offline ok")
    assert res["status"] == "completed"
    assert res["audit"]["degraded"] is True
    assert res["audit"]["passed"] is True


# ==============================================================================
# 10. CLI cmd_check_engine tests
# ==============================================================================

def test_cmd_check_engine_success(git_workspace, monkeypatch, capsys):
    """Test cmd_check_engine returns exit code 0 on healthy mock connection."""
    ws = str(git_workspace)
    monkeypatch.setenv("DEEPSEEK_API_KEY_Quench", "sk-abcdef1234567890")

    # Mock DeepSeekClient.complete to return valid response with thinking
    from reviewer_engine import DeepSeekClient

    def fake_complete(self, messages, timeout=30, total_deadline_s=None):
        return {
            "content": "pong",
            "thinking_content": "Deeply thinking...",
        }

    monkeypatch.setattr(DeepSeekClient, "complete", fake_complete)

    # 1. Test json mode
    exit_code = cmd_check_engine(ws, as_json=True)
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())

    assert data["provider"] == "deepseek"
    assert data["model"] == "deepseek-flash"
    assert data["api_key_present"] is True
    assert data["api_key_masked"] == "sk-a****7890"
    assert data["connectivity_ok"] is True
    assert data["thinking_supported"] is True
    assert data["thinking_probe"] == "live"
    assert data["exit_code"] == 0
    assert isinstance(data["latency_ms"], int)

    # 2. Test plain human mode
    exit_code_plain = cmd_check_engine(ws, plain=True, as_json=False)
    assert exit_code_plain == 0
    captured_plain = capsys.readouterr()
    assert "Quench ReviewerEngine 体检报告" in captured_plain.out
    assert "已配置 (sk-a****7890)" in captured_plain.out
    assert "连通正常" in captured_plain.out


def test_cmd_check_engine_missing_key(git_workspace, monkeypatch, capsys):
    """Test cmd_check_engine returns exit code 1 when API key is not set."""
    ws = str(git_workspace)
    monkeypatch.delenv("DEEPSEEK_API_KEY_Quench", raising=False)
    # Also patch Windows registry reader so it doesn't find the real machine's key
    monkeypatch.setattr("reviewer_engine._read_windows_env_var", lambda name: None)

    exit_code = cmd_check_engine(ws, as_json=True)
    assert exit_code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())

    assert data["api_key_present"] is False
    assert data["api_key_masked"] == "NOT SET"
    assert data["connectivity_ok"] is False
    assert data["exit_code"] == 1


def test_cmd_check_engine_probe_failure(git_workspace, monkeypatch, capsys):
    """Test cmd_check_engine returns exit code 1 on network / timeout exception."""
    ws = str(git_workspace)
    monkeypatch.setenv("DEEPSEEK_API_KEY_Quench", "sk-validkey123456789")

    from reviewer_engine import DeepSeekClient

    def fake_failing_complete(self, messages, timeout=30, total_deadline_s=None):
        raise RuntimeError("Connection timed out after 5000ms")

    monkeypatch.setattr(DeepSeekClient, "complete", fake_failing_complete)

    exit_code = cmd_check_engine(ws, as_json=True)
    assert exit_code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())

    assert data["api_key_present"] is True
    assert data["connectivity_ok"] is False
    assert data["exit_code"] == 1


# ==============================================================================
# 11. CLI main dispatcher tests
# ==============================================================================

def test_cli_main_check_engine_dispatch(git_workspace, monkeypatch, capsys):
    """Test CLI main properly dispatches 'check-engine --json' and 'check --engine'."""
    ws = str(git_workspace)
    monkeypatch.setenv("DEEPSEEK_API_KEY_Quench", "sk-dispatchkey12345678")

    from reviewer_engine import DeepSeekClient
    monkeypatch.setattr(DeepSeekClient, "complete", lambda self, m, **k: {"content": "ok"})

    # 1. quorch check-engine --json
    code1 = main(["-w", ws, "check-engine", "--json"])
    assert code1 == 0
    out1 = capsys.readouterr().out
    assert json.loads(out1)["connectivity_ok"] is True

    # 2. quorch check --engine --json
    code2 = main(["-w", ws, "check", "--engine", "--json"])
    assert code2 == 0
    out2 = capsys.readouterr().out
    assert json.loads(out2)["connectivity_ok"] is True
