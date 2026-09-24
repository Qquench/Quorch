# -*- coding: utf-8 -*-
"""Tests for synchronizing core invariants blocks between root AGENTS.md and templates/AGENTS.md.

Guards:
1. True twin-source synchronization: sections marked by <!-- QUENCH-CORE-INVARIANTS:BEGIN -->
   and <!-- QUENCH-CORE-INVARIANTS:END --> must be byte-for-byte/line-for-line equivalent.
2. Template {{PROJECT_NAME}} substitution compatibility.
3. Strict line budget enforcement (<= 120 lines) on both files.
4. Sentinel presence guard: tests fail explicitly if sentinels are missing or imbalanced.
"""
from __future__ import annotations

import re
from pathlib import Path
import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
PLUGIN_DIR = SERVER_DIR.parent
WORKSPACE_ROOT = PLUGIN_DIR.parent.parent

ROOT_AGENTS_PATH = WORKSPACE_ROOT / "AGENTS.md"
TEMPLATE_AGENTS_PATH = PLUGIN_DIR / "templates" / "AGENTS.md"

SENTINEL_BEGIN = "<!-- QUENCH-CORE-INVARIANTS:BEGIN -->"
SENTINEL_END = "<!-- QUENCH-CORE-INVARIANTS:END -->"


def _extract_core_blocks(text: str, filename: str) -> list[list[str]]:
    """Extract all blocks bounded by BEGIN and END sentinels, normalized to line lists."""
    lines = text.splitlines()
    blocks: list[list[str]] = []
    current_block: list[str] = []
    inside = False

    begin_count = 0
    end_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped == SENTINEL_BEGIN:
            begin_count += 1
            inside = True
            current_block = []
            continue
        elif stripped == SENTINEL_END:
            end_count += 1
            inside = False
            blocks.append(current_block)
            continue
        if inside:
            current_block.append(line)

    assert begin_count > 0, f"No '{SENTINEL_BEGIN}' sentinel found in {filename}"
    assert begin_count == end_count, (
        f"Imbalanced sentinels in {filename}: found {begin_count} BEGIN and {end_count} END"
    )
    return blocks


def test_agents_md_core_block_byte_sync() -> None:
    """提取两文件核心哨兵段落，排除项目名变量后断言内容逐字等价。"""
    assert ROOT_AGENTS_PATH.is_file(), f"Root AGENTS.md missing at {ROOT_AGENTS_PATH}"
    assert TEMPLATE_AGENTS_PATH.is_file(), f"Template AGENTS.md missing at {TEMPLATE_AGENTS_PATH}"

    root_text = ROOT_AGENTS_PATH.read_text(encoding="utf-8")
    template_text = TEMPLATE_AGENTS_PATH.read_text(encoding="utf-8")

    # Replace template placeholder {{PROJECT_NAME}} with current repository name 'quorch'
    template_normalized = template_text.replace("{{PROJECT_NAME}}", "quorch")

    root_blocks = _extract_core_blocks(root_text, "AGENTS.md")
    template_blocks = _extract_core_blocks(template_normalized, "templates/AGENTS.md")

    assert len(root_blocks) == len(template_blocks), (
        f"Block count mismatch between AGENTS.md ({len(root_blocks)}) and templates/AGENTS.md ({len(template_blocks)})"
    )

    for idx, (rb, tb) in enumerate(zip(root_blocks, template_blocks), start=1):
        assert len(rb) == len(tb), (
            f"Line count mismatch in core block {idx}: "
            f"root has {len(rb)} lines, template has {len(tb)} lines.\n"
            f"Root block:\n{rb}\n\nTemplate block:\n{tb}"
        )
        for line_no, (r_line, t_line) in enumerate(zip(rb, tb), start=1):
            assert r_line == t_line, (
                f"Content mismatch in core block {idx} at line {line_no}:\n"
                f"  root:     {r_line!r}\n"
                f"  template: {t_line!r}"
            )


def test_agents_md_line_budget_strict() -> None:
    """断言根文件与模板文件均 <= 120 行。"""
    assert ROOT_AGENTS_PATH.is_file(), f"Root AGENTS.md missing at {ROOT_AGENTS_PATH}"
    assert TEMPLATE_AGENTS_PATH.is_file(), f"Template AGENTS.md missing at {TEMPLATE_AGENTS_PATH}"

    root_lines = ROOT_AGENTS_PATH.read_text(encoding="utf-8").splitlines()
    template_lines = TEMPLATE_AGENTS_PATH.read_text(encoding="utf-8").splitlines()

    assert len(root_lines) <= 120, (
        f"Root AGENTS.md exceeds 120-line budget: currently {len(root_lines)} lines"
    )
    assert len(template_lines) <= 120, (
        f"Template AGENTS.md exceeds 120-line budget: currently {len(template_lines)} lines"
    )
