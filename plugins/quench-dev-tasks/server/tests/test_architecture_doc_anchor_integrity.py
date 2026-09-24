# -*- coding: utf-8 -*-
"""Tests for architecture document anchor integrity and module mapping physical existence.

Guards:
1. INV table in docs/architecture.md §4: all referenced test files physically exist on disk;
2. INV-4 anchor forgery regression guard: must not duplicate INV-5 test anchor;
3. §5 Module topology table: all source modules, hook scripts, and tool exports physically exist;
4. Elimination of the contradictory absolute claim 'All production modules live under plugins/quench-dev-tasks/server/'.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
PLUGIN_DIR = SERVER_DIR.parent
WORKSPACE_ROOT = PLUGIN_DIR.parent.parent
ARCH_DOC_PATH = WORKSPACE_ROOT / "docs" / "architecture.md"
TESTS_DIR = SERVER_DIR / "tests"


def _read_architecture_doc() -> str:
    assert ARCH_DOC_PATH.is_file(), f"Architecture doc missing at: {ARCH_DOC_PATH}"
    return ARCH_DOC_PATH.read_text(encoding="utf-8")


def _extract_markdown_table_rows(doc_text: str, section_header: str) -> list[list[str]]:
    """Extract table rows (excluding header and separator) under a given section."""
    lines = doc_text.splitlines()
    in_section = False
    table_rows: list[list[str]] = []
    header_passed = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            if in_section and section_header not in stripped:
                break
            if section_header in stripped:
                in_section = True
                continue

        if not in_section:
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            # Table row detected
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            # Skip separator row like |----|---|
            if all(set(c).issubset({"-", " ", ":"}) for c in cells):
                continue
            if header_passed < 1:
                header_passed += 1
                continue
            table_rows.append(cells)

    return table_rows


def test_architecture_inv_table_anchors_exist() -> None:
    """自动化解析 docs/architecture.md 表格，断言所有引用的测试文件与门禁脚本物理存在。"""
    doc_text = _read_architecture_doc()
    rows = _extract_markdown_table_rows(doc_text, "4. Architectural Invariants")
    assert len(rows) >= 8, f"Expected at least 8 invariant rows, found {len(rows)}"

    inv_ids_found = set()
    referenced_test_files: list[tuple[str, str]] = []

    for row in rows:
        assert len(row) >= 4, f"Malformed invariant row: {row}"
        inv_id_raw, inv_name, enforcement, test_file_cell = row[0], row[1], row[2], row[3]

        id_match = re.search(r"INV-\d+", inv_id_raw)
        assert id_match, f"Failed to extract INV ID from: {inv_id_raw}"
        inv_id = id_match.group(0)
        inv_ids_found.add(inv_id)

        # Extract backticked filenames in Test File cell
        test_matches = re.findall(r"`([^`]+\.py)`", test_file_cell)
        assert test_matches, f"No test files found in cell for {inv_id}: {test_file_cell}"

        # Specific regression guard: INV-4 must NOT duplicate test_no_vendor_literals_in_core.py
        if inv_id == "INV-4":
            assert "test_no_vendor_literals_in_core.py" not in test_matches, (
                "INV-4 Test File anchor is forged/duplicated from INV-5! "
                "Must point to test_anti_roleplay_discipline_contract.py or dedicated channel purity test."
            )

        for tm in test_matches:
            referenced_test_files.append((inv_id, tm))

    # Assert INV-1 through INV-8 are all present
    expected_invs = {f"INV-{i}" for i in range(1, 9)}
    assert expected_invs.issubset(inv_ids_found), f"Missing invariants: {expected_invs - inv_ids_found}"

    # Assert every referenced test file physically exists
    for inv_id, tf in referenced_test_files:
        test_path = TESTS_DIR / tf
        assert test_path.is_file(), (
            f"Broken anchor in docs/architecture.md for {inv_id}: "
            f"Test file '{tf}' does not physically exist at {test_path}"
        )


def test_architecture_module_mapping_files_exist() -> None:
    """依据基路径解析表，断言 §5 表格中所列出的源码文件真实存在于项目中。"""
    doc_text = _read_architecture_doc()
    rows = _extract_markdown_table_rows(doc_text, "5. Source Code Mapping")
    assert len(rows) >= 15, f"Expected at least 15 module mapping rows, found {len(rows)}"

    for row in rows:
        assert len(row) >= 4, f"Malformed module row: {row}"
        module_cell = row[0]
        mod_match = re.search(r"`([^`]+)`", module_cell)
        assert mod_match, f"No backticked module path in cell: {module_cell}"
        raw_mod = mod_match.group(1).strip()

        # Handle directory entries (e.g. adapters/)
        if raw_mod.endswith("/"):
            candidate_dirs = [
                SERVER_DIR / raw_mod,
                PLUGIN_DIR / raw_mod,
                WORKSPACE_ROOT / raw_mod,
            ]
            exists = any(cd.is_dir() for cd in candidate_dirs)
            assert exists, f"Directory module '{raw_mod}' does not exist in any expected directory."
            continue

        # Handle file entries
        candidates = [
            SERVER_DIR / raw_mod,
            PLUGIN_DIR / raw_mod,
            WORKSPACE_ROOT / raw_mod,
            # Fallback for scripts/ or hooks/ relative to PLUGIN_DIR
            PLUGIN_DIR / "scripts" / os.path.basename(raw_mod),
            SERVER_DIR / "hooks" / os.path.basename(raw_mod),
        ]

        exists = any(c.is_file() for c in candidates)
        assert exists, (
            f"Module mapping anchor '{raw_mod}' listed in docs/architecture.md does not physically exist. "
            f"Checked candidates: {[str(c) for c in candidates]}"
        )


def test_architecture_section5_heading_no_absolute_contradiction() -> None:
    """断言 §5 章节标题与描述消除了绝对化矛盾，准确反映 server/、hooks/、scripts/ 多目录拓扑。"""
    doc_text = _read_architecture_doc()
    contradictory_phrase = "All production modules live under `plugins/quench-dev-tasks/server/`."
    assert contradictory_phrase not in doc_text, (
        f"Found contradictory absolute statement in docs/architecture.md §5: '{contradictory_phrase}'"
    )
    # Check that multi-path topology is mentioned
    assert "plugins/quench-dev-tasks/" in doc_text
    assert "scripts/" in doc_text
    assert "hooks" in doc_text
