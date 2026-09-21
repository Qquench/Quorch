# -*- coding: utf-8 -*-
"""Unit tests for Multi-Tier Adaptive Reviewer Handoff Protocol & Model Decoupling (Task 5 / Milestone 4).

Validates:
1. R3 Invariant: strategies[-1]['strategy'] == 'manual' and available == True.
2. Multi-tier ability envelope negotiation (subagent -> engine -> manual fallback).
3. ReviewerClient generic decoupling & backward compatibility with DeepSeekClient.
4. Zero stdout pollution (capfd.readouterr().out == "") - P0#1 stdio guard.
5. Zero synchronous network I/O (<50ms execution budget).
6. Secret desensitization: no API key plaintext in serialized handoff envelope.
7. Path traversal defense on task_path and context_files.
8. Backward compatibility: existing top-level keys 100% preserved.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List
import pytest
import yaml

# Ensure server_dir is in sys.path regardless of execution cwd
server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from project_config import (
    QuenchStackConfig,
    ReviewerEngineConfig,
    load_project_config,
)
from reviewer_engine import (
    DeepSeekClient,
    ReviewerClient,
)
from server import (
    _resolve_handoff_envelope,
    dev_tasks_checkout,
    dev_tasks_escalate,
)


@pytest.fixture
def test_workspace(tmp_path):
    """Create a temporary initialized Quench workspace with basic config."""
    ws = tmp_path / "ws"
    ws.mkdir()
    ws_str = str(ws)

    agents_dir = ws / ".agents"
    agents_dir.mkdir()

    tasks_dir = ws / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True)

    config_data = {
        "schema_version": "1.0",
        "project_name": "HandoffTestProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "reviewer_engine": {
            "mode": "auto",
            "provider": "deepseek",
            "model": "deepseek-flash",
            "api_key_env": "DEEPSEEK_API_KEY_Quench",
            "strategy_order": ["subagent", "engine", "manual"],
        },
    }
    with open(agents_dir / "quench_stack.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    task_file = tasks_dir / "2026-09-21_test_task.md"
    task_file.write_text(
        "# Tasks\n\n### 任务 1 ⬜ 待确认 — Test Task Title\n\n#### 【涉及文件】\n```\n[NEW] foo.py\n```\n",
        encoding="utf-8",
    )

    return ws_str


def test_reviewer_client_decoupling():
    """Verify ReviewerClient is decoupled as generic client and backward-compatible with DeepSeekClient."""
    assert issubclass(ReviewerClient, DeepSeekClient)

    cfg = ReviewerEngineConfig(
        mode="engine",
        provider="openai",
        model="gpt-4o",
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
    )
    client = ReviewerClient(cfg)
    assert client.config.provider == "openai"
    assert client.config.model == "gpt-4o"


def test_reviewer_client_is_available_ollama(monkeypatch):
    """Verify is_available works for ollama even without an API key."""
    cfg = ReviewerEngineConfig(provider="ollama", model="qwen2.5-coder")
    client = ReviewerClient(cfg)
    monkeypatch.delenv("DEEPSEEK_API_KEY_Quench", raising=False)
    assert client.is_available() is True


def test_reviewer_client_is_available_none():
    """Verify is_available returns False when provider is 'none'."""
    cfg = ReviewerEngineConfig(provider="none")
    client = ReviewerClient(cfg)
    assert client.is_available() is False


def test_r3_invariant_manual_always_last_and_available(test_workspace):
    """R3 Invariant: strategies[-1]['strategy'] == 'manual' and available == True."""
    cfg = load_project_config(test_workspace)
    envelope = _resolve_handoff_envelope(
        workspace_root=test_workspace,
        config=cfg,
        task_id="1",
        task_path="docs/dev_tasks/2026-09-21_test_task.md",
        reason="batch_complete",
    )

    strategies = envelope["strategies"]
    assert len(strategies) >= 1
    last_strat = strategies[-1]
    assert last_strat["strategy"] == "manual"
    assert last_strat["available"] is True
    assert "card_markdown" in last_strat["payload"]


def test_ability_envelope_negotiation_tiers(test_workspace, monkeypatch):
    """Test capability negotiation across different modes and host capabilities."""
    cfg = load_project_config(test_workspace)

    # 1. Host supports subagent -> preferred == "subagent"
    monkeypatch.setenv("DEEPSEEK_API_KEY_Quench", "sk-mock-1234567890")
    env1 = _resolve_handoff_envelope(
        workspace_root=test_workspace,
        config=cfg,
        task_id="1",
        task_path="docs/dev_tasks/2026-09-21_test_task.md",
        reason="batch_complete",
        host_capabilities=["subagent"],
    )
    assert env1["preferred"] == "subagent"

    # 2. Host does NOT support subagent, engine key present -> fallback to "engine"
    env2 = _resolve_handoff_envelope(
        workspace_root=test_workspace,
        config=cfg,
        task_id="1",
        task_path="docs/dev_tasks/2026-09-21_test_task.md",
        reason="batch_complete",
        host_capabilities=[],
    )
    assert env2["preferred"] == "engine"

    # 3. Host does not support subagent, NO key -> fallback to "manual"
    monkeypatch.delenv("DEEPSEEK_API_KEY_Quench", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from unittest.mock import patch
    with patch("reviewer_engine._read_windows_env_var", return_value=None):
        env3 = _resolve_handoff_envelope(
            workspace_root=test_workspace,
            config=cfg,
            task_id="1",
            task_path="docs/dev_tasks/2026-09-21_test_task.md",
            reason="batch_complete",
            host_capabilities=[],
        )
        assert env3["preferred"] == "manual"


def test_mode_manual_override(test_workspace, monkeypatch):
    """When mode is explicitly 'manual', preferred is always 'manual'."""
    cfg = load_project_config(test_workspace)
    cfg.reviewer_engine.mode = "manual"
    monkeypatch.setenv("DEEPSEEK_API_KEY_Quench", "sk-mock-key")

    env = _resolve_handoff_envelope(
        workspace_root=test_workspace,
        config=cfg,
        task_id="1",
        task_path="docs/dev_tasks/2026-09-21_test_task.md",
        reason="escalation",
        host_capabilities=["subagent"],
    )
    assert env["preferred"] == "manual"


def test_zero_stdout_pollution(test_workspace, capfd, monkeypatch):
    """P0#1 Guard: Verify zero stdout pollution during envelope resolution and escalate/checkout."""
    cfg = load_project_config(test_workspace)
    monkeypatch.setenv("DEEPSEEK_API_KEY_Quench", "sk-secret123456789")

    # Clear prior stdout
    capfd.readouterr()

    # 1. Direct envelope resolution
    _resolve_handoff_envelope(
        workspace_root=test_workspace,
        config=cfg,
        task_id="1",
        task_path="docs/dev_tasks/2026-09-21_test_task.md",
        reason="escalation",
    )
    out1, _ = capfd.readouterr()
    assert out1 == "", f"Expected empty stdout, but got: {out1!r}"

    # 2. dev_tasks_checkout batch finished branch
    dev_tasks_checkout(workspace_root=test_workspace)
    out2, _ = capfd.readouterr()
    assert out2 == "", f"Expected empty stdout during checkout, but got: {out2!r}"

    # 3. dev_tasks_escalate
    dev_tasks_escalate(
        workspace_root=test_workspace,
        task_file="2026-09-21_test_task.md",
        task_id="1",
        reason="Deadlock encountered",
    )
    out3, _ = capfd.readouterr()
    assert out3 == "", f"Expected empty stdout during escalate, but got: {out3!r}"


def test_secret_desensitization(test_workspace, monkeypatch):
    """Verify raw API keys are NEVER exposed in serialized handoff envelope."""
    secret_key = "sk-super-secret-key-that-must-never-leak"
    monkeypatch.setenv("DEEPSEEK_API_KEY_Quench", secret_key)

    cfg = load_project_config(test_workspace)
    envelope = _resolve_handoff_envelope(
        workspace_root=test_workspace,
        config=cfg,
        task_id="1",
        task_path="docs/dev_tasks/2026-09-21_test_task.md",
        reason="escalation",
    )

    serialized = json.dumps(envelope, ensure_ascii=False)
    assert secret_key not in serialized

    engine_strat = next(s for s in envelope["strategies"] if s["strategy"] == "engine")
    assert engine_strat["payload"]["api_key_present"] is True
    assert "secret" not in json.dumps(engine_strat["payload"])


def test_zero_synchronous_network_budget(test_workspace):
    """Envelope resolution must complete within 50ms (pure memory operations)."""
    cfg = load_project_config(test_workspace)

    start = time.perf_counter()
    for _ in range(5):
        _resolve_handoff_envelope(
            workspace_root=test_workspace,
            config=cfg,
            task_id="1",
            task_path="docs/dev_tasks/2026-09-21_test_task.md",
            reason="batch_complete",
        )
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 50.0, f"Envelope resolution took {elapsed_ms:.2f}ms, exceeding 50ms budget"


def test_path_traversal_defense(test_workspace):
    """Test path traversal attempts in task_path and context_files are sanitized."""
    cfg = load_project_config(test_workspace)
    evil_context = [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\cmd.exe",
        "valid_sub/file.py",
    ]
    # Create the valid sub file
    sub_file = os.path.join(test_workspace, "valid_sub", "file.py")
    os.makedirs(os.path.dirname(sub_file), exist_ok=True)
    with open(sub_file, "w") as f:
        f.write("# valid code")

    envelope = _resolve_handoff_envelope(
        workspace_root=test_workspace,
        config=cfg,
        task_id="1",
        task_path="../../dangerous/path.md",
        reason="escalation",
        context_files=evil_context,
    )

    subagent_strat = next(s for s in envelope["strategies"] if s["strategy"] == "subagent")
    ctx_files = subagent_strat["payload"]["context_files"]

    assert "valid_sub/file.py" in ctx_files
    for f in ctx_files:
        assert not f.startswith("..")


def test_legacy_backward_compatibility_fields(test_workspace):
    """Verify checkout and escalate maintain 100% backward compatibility for legacy clients."""
    # 1. dev_tasks_checkout batch finished return schema
    res_checkout = dev_tasks_checkout(workspace_root=test_workspace)
    assert "reviewer_handoff" in res_checkout
    assert "handoff_card" in res_checkout
    assert res_checkout["handoff_card"] == res_checkout["reviewer_handoff"]["legacy_card_markdown"]
    assert res_checkout["batch_finished"] is True
    assert "instruction" in res_checkout

    # 2. dev_tasks_escalate return schema
    res_esc = dev_tasks_escalate(
        workspace_root=test_workspace,
        task_file="2026-09-21_test_task.md",
        task_id="1",
        reason="Test Escalation",
    )
    assert res_esc["status"] == "escalated"
    assert "reviewer_handoff" in res_esc
    assert "handoff_card" in res_esc
    assert res_esc["handoff_card"] == res_esc["reviewer_handoff"]["legacy_card_markdown"]
    assert "instruction" in res_esc
    assert "prompt_hint" in res_esc


def test_config_migration_auto(tmp_path):
    """Test legacy config migration: provider='none' -> mode='manual'."""
    ws = tmp_path / "legacy_ws"
    ws.mkdir()
    agents = ws / ".agents"
    agents.mkdir()

    # Legacy config without 'mode'
    legacy_data = {
        "project_name": "LegacyProject",
        "reviewer_engine": {
            "provider": "none",
        },
    }
    with open(agents / "quench_stack.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(legacy_data, f)

    cfg = load_project_config(str(ws))
    assert cfg.reviewer_engine.mode == "manual"
    assert cfg.reviewer_engine.provider == "none"
