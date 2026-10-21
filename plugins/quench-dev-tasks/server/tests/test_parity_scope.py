# -*- coding: utf-8 -*-
"""Parity comparator test suite enforcing TP-3 zero net coverage loss."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from typing import Final

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
    EXPANSION_ELIGIBLE_RULES,
    MERGED_EXPANSION_ALLOWLIST,
    MERGED_FILE_SCOPE_ALLOWLIST,
    RULE_IDS,
    RULE_SCOPE,
    SCAN_ROOTS,
    derive_expansion_allowlist,
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
    """[E4] 路径约定基准同构断言：统一为 plugin 根相对 POSIX 路径（server/...），无反斜杠且不以斜杠开头。"""
    for item in baseline_data["entries"]:
        rel_path = item[1]
        assert "\\" not in rel_path, f"Path must not contain backslash: {rel_path}"
        assert not rel_path.startswith("/"), f"Path must not start with slash: {rel_path}"
        assert rel_path.startswith("server/"), f"Path must be plugin-root relative (server/...): {rel_path}"

    for rule_id, rel_path, token in scanner.scope_report():
        assert "\\" not in rel_path, f"Path must not contain backslash: {rel_path}"
        assert not rel_path.startswith("/"), f"Path must not start with slash: {rel_path}"
        assert rel_path.startswith("server/"), f"Path must be plugin-root relative (server/...): {rel_path}"


def test_canonical_bytes_bom_and_crlf_normalization():
    """断言 canonical_bytes 对真实 BOM 与 CRLF 载荷的消除与归一化幂等性。"""
    raw_with_bom_crlf = b"\xef\xbb\xbfhello\r\nworld\r\n"
    normalized = canonical_bytes(raw_with_bom_crlf)
    assert normalized == b"hello\nworld\n"
    assert canonical_bytes(normalized) == normalized


def test_expansion_allowlist_well_formed(scanner):
    """断言扩展白名单与词汇表契约严格良好成型。"""
    # 1. 字典三表齐平
    assert set(RULE_IDS) == set(RULE_SCOPE) == set(SCAN_ROOTS)
    # 2. 扩充资格子集律与禁忌规则双钥防护
    assert EXPANSION_ELIGIBLE_RULES <= set(RULE_IDS)
    assert "lease_symbol_removal" not in EXPANSION_ELIGIBLE_RULES
    # 3. 白名单物理文件真实存在与扫描器前缀判定同构
    for rule_id, rel_path in MERGED_FILE_SCOPE_ALLOWLIST:
        target_file = PLUGIN_ROOT / rel_path
        assert target_file.is_file(), f"Allowlisted file does not exist physically: {rel_path}"
        assert scanner._applies_rule_to_path(rule_id, rel_path, is_isolated_file_scan=False), (
            f"Rule {rule_id} does not apply to path {rel_path} according to scanner"
        )
    # 4. 派生函数恒等性
    derived = derive_expansion_allowlist(MERGED_FILE_SCOPE_ALLOWLIST, EXPANSION_ELIGIBLE_RULES, RULE_SCOPE)
    assert derived == MERGED_EXPANSION_ALLOWLIST


def test_derive_expansion_allowlist_error_branches():
    """断言 derive_expansion_allowlist 纯函数的四重 fail-closed 校验分支。"""
    # 1. 空集合
    with pytest.raises(ValueError, match="empty file_scope"):
        derive_expansion_allowlist(frozenset(), EXPANSION_ELIGIBLE_RULES, RULE_SCOPE)

    # 2. 规则不具备扩充资格（如禁忌规则 lease_symbol_removal）
    with pytest.raises(ValueError, match="ineligible rule"):
        derive_expansion_allowlist(
            frozenset({("lease_symbol_removal", "server/workspace_lease.py")}),
            EXPANSION_ELIGIBLE_RULES,
            RULE_SCOPE,
        )

    # 3. 规则不存在于 scope
    with pytest.raises(ValueError, match="out_of_scope rule"):
        derive_expansion_allowlist(
            frozenset({("fake_rule", "server/workspace_lease.py")}),
            frozenset({"fake_rule"}),
            RULE_SCOPE,
        )

    # 4. 路径不属于规则根域
    with pytest.raises(ValueError, match="out_of_scope path"):
        derive_expansion_allowlist(
            frozenset({("api_bypass", "server/sub/nested.py")}),
            EXPANSION_ELIGIBLE_RULES,
            RULE_SCOPE,
        )


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

    # 3. 白名单杜绝死条目：重基线为文件级双向对齐，且每个具体三元组均可派生
    exp_files = frozenset((r, p) for (r, p, _t) in expansions)
    allow_files = MERGED_FILE_SCOPE_ALLOWLIST
    sym_diff = sorted(exp_files ^ allow_files)
    assert not (exp_files - allow_files), f"unauthorized file-scope expansion: {sym_diff}"
    assert not (allow_files - exp_files), f"D-17 Violation: dead file-scope allowlist entry: {sym_diff}"
    assert not (expansions - MERGED_EXPANSION_ALLOWLIST), "unauthorized concrete token expansion"


def test_scope_projection_matches_inspected_tokens(scanner):
    """断言每条规则 scope_report 的 (path, token) 投影与 inspected_tokens 严格恒等。"""
    full_report = scanner.scope_report()
    for rule_id in RULE_IDS:
        proj = {(path_str, token) for (r, path_str, token) in full_report if r == rule_id}
        actual_inspected = scanner.inspected_tokens(rule_id)
        assert proj == actual_inspected, f"Projection mismatch for rule '{rule_id}'"

