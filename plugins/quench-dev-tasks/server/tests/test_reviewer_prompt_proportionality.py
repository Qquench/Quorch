# -*- coding: utf-8 -*-
"""Unit tests for Reviewer Prompt Proportionality (Context-Proportional Refactor).

Verifies the removal of indiscriminate overengineering lures:
- 'No Upper Bounds'
- 'eliminate concurrency deadlocks'
- 'concurrency boundary defenses'
- 'ironclad Quench DevTask'

And asserts positive presence of Context-Proportionality, Minimal Diff Surface,
and boilerplate-free step guidelines across:
1. PromptAssembler.build_static_system_prefix (reviewer_engine.py)
2. dev_tasks_refine_spec docstring & user prompt (server.py)
3. IDE tool schema export (docs/architecture/ide_tool_schemas.json)
4. dev-tasks-review skill contract (plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SERVER_DIR = TESTS_DIR.parent
PLUGIN_ROOT = SERVER_DIR.parent
REPO_ROOT = PLUGIN_ROOT.parent.parent

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from project_config import QuenchStackConfig, ReviewerEngineConfig
import reviewer_engine
from reviewer_engine import PromptAssembler
import server


@pytest.fixture
def sample_config(tmp_path: Path) -> tuple[str, QuenchStackConfig]:
    ws_dir = str(tmp_path)
    cfg = QuenchStackConfig(
        workspace_root=ws_dir,
        project_name="ProportionalityTestWS",
        architecture_doc=None,
        constraints=["Only modify declared files", "Zero regressions"],
        reviewer_engine=ReviewerEngineConfig(
            provider="custom",
            base_url="https://mock.ai/v1",
            model="reviewer-proportional-v1",
            api_key_env="MOCK_PROMPT_KEY",
            timeout_seconds=20,
        ),
    )
    return ws_dir, cfg


# ---------------------------------------------------------------------------
# 1. PromptAssembler.build_static_system_prefix assertions
# ---------------------------------------------------------------------------

def test_prompt_assembler_negative_lures_removed(sample_config: tuple[str, QuenchStackConfig]):
    ws_dir, cfg = sample_config
    prefix = PromptAssembler.build_static_system_prefix(ws_dir, cfg)

    # 负向断言：严禁出现强诱导过度设计词汇
    assert "eliminate concurrency deadlocks" not in prefix
    assert "concurrency deadlocks" not in prefix
    assert "concurrent race conditions, boundary overflows, and offline fallbacks" not in prefix
    assert "No Upper Bounds" not in prefix
    assert "concurrency boundary defenses" not in prefix
    assert "ironclad" not in prefix.lower()


def test_prompt_assembler_positive_proportionality_anchors(sample_config: tuple[str, QuenchStackConfig]):
    ws_dir, cfg = sample_config
    prefix = PromptAssembler.build_static_system_prefix(ws_dir, cfg)

    # 正向断言：成比例、最小改动表面积与免写样板引导
    assert "Minimal Diff Surface" in prefix
    assert "Context-Proportional" in prefix or "context-proportional" in prefix
    assert "proportional" in prefix.lower()
    assert "boilerplate" in prefix.lower()
    # 审查并发与离线降级仅在客观涉及并发或外部 I/O 时触发
    assert "objectively involves concurrency or external I/O" in prefix or "concurrency" in prefix.lower()


def test_prompt_assembler_static_purity_maintained(sample_config: tuple[str, QuenchStackConfig]):
    ws_dir, cfg = sample_config
    p1 = PromptAssembler.build_static_system_prefix(ws_dir, cfg)
    p2 = PromptAssembler.build_static_system_prefix(ws_dir, cfg)

    # 保持纯静态纯洁性（无时间戳、无随机数，哈希稳定）
    assert p1 == p2
    assert PromptAssembler.get_prefix_hash(p1) == PromptAssembler.get_prefix_hash(p2)
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", p1)


# ---------------------------------------------------------------------------
# 2. server.py dev_tasks_refine_spec docstring & prompt assertions
# ---------------------------------------------------------------------------

def test_refine_spec_docstring_proportionality():
    doc = server.dev_tasks_refine_spec.__doc__ or ""

    # 负向断言
    assert "concurrency boundary defenses" not in doc
    assert "并发边界与" not in doc

    # 正向断言
    assert "proportional boundary checks" in doc
    assert "成比例的边界校验" in doc


def test_refine_spec_source_prompt_proportionality():
    server_py_path = SERVER_DIR / "server.py"
    content = server_py_path.read_text(encoding="utf-8")

    # 负向断言：不再包含 ironclad 强诱导词汇
    assert "ironclad Quench DevTask" not in content
    assert "into an ironclad" not in content

    # 正向断言：包含 context-proportional 或 proportional
    assert "context-proportional" in content or "proportional" in content


# ---------------------------------------------------------------------------
# 3. docs/architecture/ide_tool_schemas.json assertions
# ---------------------------------------------------------------------------

def test_ide_tool_schemas_sync():
    schema_path = REPO_ROOT / "docs" / "architecture" / "ide_tool_schemas.json"
    data = json.loads(schema_path.read_text(encoding="utf-8"))

    refine_tool = data.get("dev_tasks_refine_spec", {})
    desc = refine_tool.get("description", "")

    # 负向断言
    assert "concurrency boundary defenses" not in desc
    assert "并发边界与" not in desc

    # 正向断言
    assert "proportional boundary checks" in desc
    assert "成比例的边界校验" in desc


# ---------------------------------------------------------------------------
# 4. SKILL.md assertions
# ---------------------------------------------------------------------------

def test_skill_md_proportionality():
    skill_path = PLUGIN_ROOT / "skills" / "dev-tasks-review" / "SKILL.md"
    skill_content = skill_path.read_text(encoding="utf-8")

    # 负向断言
    assert "No Upper Bounds" not in skill_content
    assert "Rigidly Enforced, No Upper Bounds" not in skill_content
    assert "concurrency boundary defenses" not in skill_content
    assert "ironclad" not in skill_content.lower()

    # 正向断言
    assert "★ Context-Proportional (Bound to Actual Changed Paths)" in skill_content
    assert "免写样板" in skill_content
    assert "proportional" in skill_content.lower()
