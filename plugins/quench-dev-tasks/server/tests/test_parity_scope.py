# -*- coding: utf-8 -*-
"""Parity comparator test suite enforcing TP-3 zero net coverage loss."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SERVER_DIR = TESTS_DIR.parent
PLUGIN_ROOT = SERVER_DIR.parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from _hygiene.rules import (
    MERGED_EXPANSION_ALLOWLIST,
    RULE_IDS,
    RULE_SCOPE,
)
from _hygiene.scanner import ArchitectureHygieneScanner

LEGACY_RULE_MAP: Final[dict[str, str]] = {
    f"plugins/quench-dev-tasks/server/tests/test_{r}.py": r
    for r in (
        "lease_symbol_removal",
        "touch_outcome_truthiness",
        "vendor_literal_in_core",
        "api_bypass",
    )
}


def canonical_bytes(raw: bytes) -> bytes:
    """BOM strip (utf-8-sig) + CRLF->LF 归一化。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.replace(b"\r\n", b"\n")


@pytest.fixture(scope="module")
def scanner() -> ArchitectureHygieneScanner:
    return ArchitectureHygieneScanner(SERVER_DIR)


@pytest.fixture(scope="module")
def baseline_data() -> dict:
    baseline_path = TESTS_DIR / "_parity" / "isolated_scope_v120.json"
    assert baseline_path.is_file(), f"Fail-closed: frozen baseline file missing at {baseline_path}"
    raw = baseline_path.read_bytes()
    data = json.loads(canonical_bytes(raw).decode("utf-8"))
    return data


def test_ssot_rule_vocabulary_equivalence():
    """D-13 真源等价律：断言 LEGACY_RULE_MAP 的值集与 RULE_IDS 严格等价，杜绝词汇表漂移。"""
    assert set(LEGACY_RULE_MAP.values()) == set(RULE_IDS)


def test_baseline_entries_are_strictly_sorted(baseline_data):
    """D-16′ 升维去重排序律：断言基线 entries 按 (rule_id, rel_path, symbol_or_token) 升序。"""
    entries = baseline_data["entries"]
    expected_sorted = sorted(entries, key=lambda e: (e[0], e[1], e[2]))
    assert entries == expected_sorted, "Baseline entries are not canonically sorted"


def test_path_conventions_homomorphic(baseline_data, scanner):
    """[E4] 路径约定基准同构断言：统一为 plugin 根相对 POSIX 路径（server/...）。"""
    for item in baseline_data["entries"]:
        rel_path = item[1]
        assert "/" in rel_path or not rel_path.startswith("\\"), f"Path must be POSIX: {rel_path}"
        assert rel_path.startswith("server/"), f"Path must be plugin-root relative (server/...): {rel_path}"

    for rule_id, rel_path, token in scanner.scope_report():
        assert "/" in rel_path or not rel_path.startswith("\\"), f"Path must be POSIX: {rel_path}"
        assert rel_path.startswith("server/"), f"Path must be plugin-root relative (server/...): {rel_path}"


def test_tp3_zero_net_coverage_loss_and_allowlist(baseline_data, scanner):
    r"""D-3 / D-17 TP-3 覆盖守恒律与 allowlist 无死条目律：
    1. baseline.entries ⊆ merged (机械证明零覆盖损失)；
    2. merged \ baseline ⊆ MERGED_EXPANSION_ALLOWLIST；
    3. MERGED_EXPANSION_ALLOWLIST ⊆ (merged \ baseline) (杜绝死条目)。
    """
    baseline_set = frozenset(tuple(item) for item in baseline_data["entries"])
    merged_set = scanner.scope_report()

    # 1. 零净覆盖损失：baseline 必须是 merged 的子集
    missing_coverage = baseline_set - merged_set
    assert not missing_coverage, (
        f"TP-3 Violation: merged scope lost coverage on {len(missing_coverage)} entries:\n"
        + "\n".join(str(e) for e in sorted(missing_coverage)[:10])
    )

    # 2. 扩充范围必须受白名单约束
    expansions = merged_set - baseline_set
    unauthorized_expansions = expansions - MERGED_EXPANSION_ALLOWLIST
    assert not unauthorized_expansions, (
        f"Unauthorized expansion in merged scope not in allowlist:\n"
        + "\n".join(str(e) for e in sorted(unauthorized_expansions)[:10])
    )

    # 3. 白名单杜绝死条目：每个 allowlist 项必须在 expansions 中出现
    dead_allowlist_entries = MERGED_EXPANSION_ALLOWLIST - expansions
    assert not dead_allowlist_entries, (
        f"D-17 Violation: dead entries found in MERGED_EXPANSION_ALLOWLIST:\n"
        + "\n".join(str(e) for e in sorted(dead_allowlist_entries))
    )


def test_scope_projection_matches_inspected_tokens(scanner):
    """断言每条规则 scope_report 的 (path, token) 投影与 inspected_tokens 严格恒等。"""
    full_report = scanner.scope_report()
    for rule_id in RULE_IDS:
        proj = {(path_str, token) for (r, path_str, token) in full_report if r == rule_id}
        actual_inspected = scanner.inspected_tokens(rule_id)
        assert proj == actual_inspected, f"Projection mismatch for rule '{rule_id}'"
