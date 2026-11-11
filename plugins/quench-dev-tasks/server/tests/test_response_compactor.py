"""test_response_compactor.py - Comprehensive Unit Tests for Response Compactor Pipeline (Task 33.1).

Verifies:
- E1: AST scan of response_compactor.py: zero hardcoded literals (1024, 2048, "ASK_MODAL_BLOCKED").
- E2: Bounded clamping and 3-tier terminal convergence under 40-task overload.
- E3: Floor reachability: minimal compact payload <= 1024B.
- E4: Deterministic idempotence of fit_to_budget and canonical_json.
- E5: Closed-vocabulary classifier reconciliation across HOOK_LOG_CODES and unknown fallback.
- E6: Entitlements ETag hash cross-process stability & canonical measurement alignment.
- 3-tier empty value compaction semantics (None vs empty collections vs 0/False).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from fixtures.response_payloads import (
    CANONICAL_HOOK_LOG_FIXTURES,
    OVERLOAD_STATUS_PAYLOAD,
    TYPICAL_PAYLOADS,
    UNKNOWN_HOOK_LOG_SAMPLE,
)
from response_compactor import (
    STATUS_COMPACT_ALWAYS_KEEP,
    STATUS_COMPACT_DROP_ORDER,
    ResponseBudgetExceeded,
    assert_response_budget,
    canonical_json,
    classify_hook_log_entry,
    compact_mapping,
    compute_entitlements_hash,
    fit_to_budget,
)
from tool_surface_constants import (
    EXPECTED_TOOL_NAMES,
    HOOK_LOG_CODES,
    RESPONSE_BUDGET_BYTES,
    STATUS_COMPACT_MAX_TASKS,
    measure_payload_bytes,
)

SERVER_DIR = Path(__file__).resolve().parents[1]


def test_response_compactor_e1_no_hardcoded_literals() -> None:
    """E1: AST scan ensures no duplicate numerical or code literals in response_compactor.py."""
    source_file = SERVER_DIR / "response_compactor.py"
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))

    forbidden_ints = {1024, 2048}
    forbidden_strings = {"ASK_MODAL_BLOCKED"}

    found_ints: list[int] = []
    found_strings: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, int) and node.value in forbidden_ints:
                found_ints.append(node.value)
            elif isinstance(node.value, str) and node.value in forbidden_strings:
                found_strings.append(node.value)

    assert not found_ints, f"Hardcoded integer literals found in response_compactor.py: {found_ints}"
    assert not found_strings, f"Hardcoded code string literals found in response_compactor.py: {found_strings}"


def test_response_compactor_e2_bounded_clamping_and_three_tier_state() -> None:
    """E2: Clamping boundedness and 3-tier terminal convergence on 40-task overload."""
    budget = RESPONSE_BUDGET_BYTES["dev_tasks_status"]
    assert measure_payload_bytes(OVERLOAD_STATUS_PAYLOAD) > budget

    clamped = fit_to_budget("dev_tasks_status", OVERLOAD_STATUS_PAYLOAD)
    clamped_size = measure_payload_bytes(clamped)

    if "over_budget_bytes" in clamped:
        assert clamped_size <= budget + 64, (
            f"Over-budget marker payload size {clamped_size} exceeded budget {budget} + 64B overhead"
        )
    else:
        assert clamped_size <= budget, f"Clamped payload size {clamped_size} exceeded budget {budget}"

    # Verify tasks were capped
    assert "tasks" in clamped
    assert len(clamped["tasks"]) <= STATUS_COMPACT_MAX_TASKS
    assert clamped.get("tasks_total") == 40

    # Test extreme tier-2 and tier-3 overflow
    extreme_payload = {
        "ok": True,
        "entitlements_hash": "x" * 2500,  # Single key exceeds 2048 budget
        "harness_next_action": {
            "action": "REVIEW",
            "instruction": "Long instruction string " * 50,
            "verbose_data": [1, 2, 3] * 100,
        },
        "files": ["file1.py"] * 100,
    }
    extreme_clamped = fit_to_budget("dev_tasks_status", extreme_payload)
    # Never raises
    assert isinstance(extreme_clamped, dict)
    # Tier-2 preserves discriminator
    assert extreme_clamped["harness_next_action"] == {"action": "REVIEW"}
    # Tier-3 injects over_budget_bytes marker
    assert "over_budget_bytes" in extreme_clamped
    assert extreme_clamped["over_budget_bytes"] > 0
    # Non-always-keep files key was dropped
    assert "files" not in extreme_clamped


def test_response_compactor_e3_floor_reachability() -> None:
    """E3: Minimal status compact floor must measure <= 1024B."""
    floor_payload = {
        "ok": True,
        "harness_next_action": {
            "action": "CHECKOUT",
            "task_id": "33.1",
            "task_file": "docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md",
        },
        "entitlements_hash": "a1b2c3d4e5f67890",
        "tasks": [
            {
                "id": "33.1",
                "title": "Runtime Budget Clamp & Pipeline",
                "status": "🔨 执行中",
            }
        ],
    }
    floor_bytes = measure_payload_bytes(floor_payload)
    assert floor_bytes <= 1024, f"Minimal floor payload size {floor_bytes} exceeded soft target 1024B"


def test_response_compactor_e4_idempotent_determinism() -> None:
    """E4: fit_to_budget and canonical_json are strictly idempotent and deterministic."""
    res1 = fit_to_budget("dev_tasks_status", OVERLOAD_STATUS_PAYLOAD)
    res2 = fit_to_budget("dev_tasks_status", OVERLOAD_STATUS_PAYLOAD)
    assert canonical_json(res1) == canonical_json(res2)

    # Re-clamping an already clamped payload produces the identical JSON
    res3 = fit_to_budget("dev_tasks_status", res1)
    assert canonical_json(res3) == canonical_json(res1)


def test_response_compactor_e5_classifier_reconciliation() -> None:
    """E5: Closed-vocabulary classifier covers every code in HOOK_LOG_CODES and unknown lines."""
    # 1. Test canonical fixtures for all codes
    for code, sample_line in CANONICAL_HOOK_LOG_FIXTURES.items():
        classified = classify_hook_log_entry(sample_line)
        assert classified == code, f"Sample for {code} was classified as {classified}"
        assert classified in HOOK_LOG_CODES

    # 2. Test unknown line falls back to OTHER
    assert classify_hook_log_entry(UNKNOWN_HOOK_LOG_SAMPLE) == "OTHER"
    assert classify_hook_log_entry("") == "OTHER"
    assert classify_hook_log_entry("Some arbitrary text without governance tags") == "OTHER"

    # 3. AST recursive scan of classify_hook_log_entry return literal strings
    source_file = SERVER_DIR / "response_compactor.py"
    tree = ast.parse(source_file.read_text(encoding="utf-8"))

    func_node: ast.FunctionDef | None = None
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == "classify_hook_log_entry":
            func_node = stmt
            break

    assert func_node is not None, "Failed to find classify_hook_log_entry in AST"

    return_literals: set[str] = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Return) and node.value is not None:
            for subnode in ast.walk(node.value):
                if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                    return_literals.add(subnode.value)

    assert return_literals.issubset(HOOK_LOG_CODES), (
        f"Return string literals in classify_hook_log_entry {return_literals} not subset of HOOK_LOG_CODES {HOOK_LOG_CODES}"
    )


def test_response_compactor_e6_hash_stability_and_measurement() -> None:
    """E6: compute_entitlements_hash cross-process stability & canonical measurement alignment."""
    sample_cfg = {
        "project": "quench-dev-orchestrator",
        "governance_scope": {"managed_paths": ["plugins/**"], "unmanaged_paths": ["docs/**"]},
        "version": 1,
    }

    cmd = [
        sys.executable,
        "-c",
        (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0, r'{SERVER_DIR}'); "
            "from response_compactor import compute_entitlements_hash; "
            f"print(compute_entitlements_hash({sample_cfg}))"
        ),
    ]

    p1 = subprocess.run(cmd, capture_output=True, text=True, check=True)
    p2 = subprocess.run(cmd, capture_output=True, text=True, check=True)

    hash1 = p1.stdout.strip()
    hash2 = p2.stdout.strip()
    assert hash1 == hash2, f"Subprocess hashes diverged: '{hash1}' vs '{hash2}'"
    assert len(hash1) == 16
    assert compute_entitlements_hash(sample_cfg) == hash1

    # Canonical measurement identity
    test_dict = {"b": 2, "a": [1, 2, 3], "c": {"nested": True}}
    assert measure_payload_bytes(test_dict) == len(canonical_json(test_dict).encode("utf-8"))


def test_compact_mapping_three_tier_empty_semantics() -> None:
    """Test 3-tier empty value compaction rules."""
    raw = {
        "keep_none": None,
        "drop_none": None,
        "empty_str": "",
        "empty_list": [],
        "empty_dict": {},
        "int_zero": 0,
        "bool_false": False,
        "valid_str": "hello",
    }

    compacted = compact_mapping(
        raw,
        always_keep=("keep_none",),
        drop_if_empty=("empty_str", "empty_list", "empty_dict", "int_zero", "bool_false"),
    )

    # 1. None dropped by default unless in always_keep
    assert "keep_none" in compacted
    assert compacted["keep_none"] is None
    assert "drop_none" not in compacted

    # 2. Empty collections dropped if in drop_if_empty
    assert "empty_str" not in compacted
    assert "empty_list" not in compacted
    assert "empty_dict" not in compacted

    # 3. 0 and False are NEVER dropped even if specified in drop_if_empty
    assert "int_zero" in compacted
    assert compacted["int_zero"] == 0
    assert "bool_false" in compacted
    assert compacted["bool_false"] is False

    # 4. Valid non-empty values kept
    assert compacted["valid_str"] == "hello"

    # Non-mapping input safety
    assert compact_mapping(None) == {}  # type: ignore[arg-type]


def test_assert_response_budget_all_tools() -> None:
    """Assert all typical payloads pass budget assertion, and oversized payload raises."""
    for tool_name, payload in TYPICAL_PAYLOADS.items():
        assert_response_budget(tool_name, payload)

    # Oversized payload raises ResponseBudgetExceeded
    oversized = {"big_payload": "a" * 3000}
    with pytest.raises(ResponseBudgetExceeded) as exc_info:
        assert_response_budget("dev_tasks_status", oversized)
    assert "exceeds declared budget" in str(exc_info.value)

    # dev_reviewer_poll terminal phase exemption
    assert_response_budget("dev_reviewer_poll", {"findings": "x" * 20000}, phase="terminal")

