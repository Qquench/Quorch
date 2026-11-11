"""test_snapshot_drift_gate_contract.py - Tier-1 snapshot drift gate pre-commit contract tests.

Verifies:
1. .gitattributes rules for line endings;
2. should_run_schema_check truth table;
3. 5-branch evaluation contract of evaluate_schema_check with zero-subprocess defense;
4. Antigravity hard-gate precedence (schema drift is never bypassed).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence
from unittest.mock import MagicMock

import pytest

import sys

# Ensure scripts directory is on sys.path for importing git_pre_commit_guard
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from git_pre_commit_guard import (
    SCHEMA_TRIGGER_PATHS,
    SchemaCheckOutcome,
    evaluate_schema_check,
    main as guard_main,
    should_run_schema_check,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_gitattributes_enforces_lf_for_json_and_code() -> None:
    """Verify that .gitattributes explicitly declares LF line endings for JSON and Python."""
    gitattributes_path = REPO_ROOT / ".gitattributes"
    assert gitattributes_path.is_file(), ".gitattributes must exist at repository root"
    content = gitattributes_path.read_text(encoding="utf-8")

    assert "*.json text eol=lf" in content, ".gitattributes must lock *.json to LF"
    assert "*.py text eol=lf" in content, ".gitattributes must lock *.py to LF"


@pytest.mark.parametrize("trigger_path", sorted(SCHEMA_TRIGGER_PATHS))
def test_should_run_schema_check_hits(trigger_path: str) -> None:
    """Verify should_run_schema_check hits all defined trigger paths and path variations."""
    # Exact match
    assert should_run_schema_check([trigger_path]) is True

    # Windows backslash variation
    assert should_run_schema_check([trigger_path.replace("/", "\\")]) is True

    # Leading ./ variation
    assert should_run_schema_check([f"./{trigger_path}"]) is True

    # Multiple paths including trigger path
    assert should_run_schema_check(["README.md", trigger_path, "docs/notes.md"]) is True


@pytest.mark.parametrize(
    "non_trigger_paths",
    [
        [],
        ["README.md"],
        ["docs/architecture/README.md"],
        ["plugins/quench-dev-tasks/server/path_guard.py"],
        ["plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md"],
    ],
)
def test_should_run_schema_check_misses(non_trigger_paths: Sequence[str]) -> None:
    """Verify should_run_schema_check returns False for non-trigger paths."""
    assert should_run_schema_check(non_trigger_paths) is False


def test_evaluate_schema_check_skip_zero_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that non-trigger paths return SKIP with strictly zero subprocess invocations (<50ms)."""
    mock_run = MagicMock()
    monkeypatch.setattr(subprocess, "run", mock_run)

    outcome = evaluate_schema_check(["docs/architecture/README.md"], repo_root=REPO_ROOT)
    assert outcome == SchemaCheckOutcome.SKIP
    mock_run.assert_not_called()


def test_evaluate_schema_check_guard_error_on_none_staged() -> None:
    """Verify that when staged_files is None (error obtaining staged files), GUARD_ERROR is returned."""
    outcome = evaluate_schema_check(None, repo_root=REPO_ROOT)
    assert outcome == SchemaCheckOutcome.GUARD_ERROR


@pytest.mark.parametrize(
    "ret_code,expected_outcome",
    [
        (0, SchemaCheckOutcome.PASS),
        (1, SchemaCheckOutcome.DRIFT),
        (2, SchemaCheckOutcome.UNVERIFIABLE),
        (3, SchemaCheckOutcome.UNVERIFIABLE),
    ],
)
def test_evaluate_schema_check_return_codes(
    monkeypatch: pytest.MonkeyPatch, ret_code: int, expected_outcome: SchemaCheckOutcome
) -> None:
    """Verify mapping of subprocess return codes to SchemaCheckOutcome."""
    mock_proc = MagicMock(returncode=ret_code, stdout=b"", stderr=b"")
    mock_run = MagicMock(return_value=mock_proc)
    monkeypatch.setattr(subprocess, "run", mock_run)

    trigger = next(iter(SCHEMA_TRIGGER_PATHS))
    outcome = evaluate_schema_check([trigger], repo_root=REPO_ROOT)
    assert outcome == expected_outcome
    mock_run.assert_called_once()


def test_evaluate_schema_check_timeout_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that subprocess timeout produces UNVERIFIABLE outcome (fail-closed)."""
    mock_run = MagicMock(side_effect=subprocess.TimeoutExpired(cmd=["check"], timeout=30))
    monkeypatch.setattr(subprocess, "run", mock_run)

    trigger = next(iter(SCHEMA_TRIGGER_PATHS))
    outcome = evaluate_schema_check([trigger], repo_root=REPO_ROOT)
    assert outcome == SchemaCheckOutcome.UNVERIFIABLE


def test_antigravity_precedence_schema_drift_is_not_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that even when in Antigravity environment, DRIFT blocks pre-commit with exit code 1."""
    # Force is_antigravity_environment to True
    monkeypatch.setattr("git_pre_commit_guard.is_antigravity_environment", lambda ws: True)
    # Force get_staged_files to return a schema trigger path
    trigger = next(iter(SCHEMA_TRIGGER_PATHS))
    monkeypatch.setattr("git_pre_commit_guard.get_staged_files", lambda ws: [trigger])
    # Force evaluate_schema_check to return DRIFT
    monkeypatch.setattr("git_pre_commit_guard.evaluate_schema_check", lambda files, repo_root: SchemaCheckOutcome.DRIFT)
    # Bypass find_active_task
    monkeypatch.setattr("git_pre_commit_guard.find_active_task", lambda d: ("1.5", "test", []))
    monkeypatch.setattr("sys.argv", ["git_pre_commit_guard.py", "--workspace", str(REPO_ROOT)])

    rc = guard_main()
    assert rc == 1, "Schema drift MUST block commit even under Antigravity environment"


def test_tool_schema_physical_size_hard_gate() -> None:
    """Verify that every tool schema in snapshot strictly adheres to MAX_TOOL_SCHEMA_BYTES (1000B)
    and total eager schema strictly adheres to MAX_TOTAL_SCHEMA_BYTES (12000B).
    """
    import json
    from ide_schema_export import SNAPSHOT_FILENAME, validate_schema_size_budget
    from tool_surface_constants import (
        MAX_TOOL_SCHEMA_BYTES,
        MAX_TOTAL_SCHEMA_BYTES,
        TOOL_COUNT,
        measure_tool_schema_bytes,
    )

    # F-2: Trinary inequality constant assertion
    assert (
        MAX_TOOL_SCHEMA_BYTES < MAX_TOTAL_SCHEMA_BYTES < TOOL_COUNT * MAX_TOOL_SCHEMA_BYTES
    ), "Trinary invariant broken: MAX_TOOL_SCHEMA_BYTES < MAX_TOTAL_SCHEMA_BYTES < TOOL_COUNT * MAX_TOOL_SCHEMA_BYTES"

    snapshot_path = REPO_ROOT / "docs" / "architecture" / SNAPSHOT_FILENAME
    assert snapshot_path.is_file(), f"Snapshot file not found: {snapshot_path}"

    with open(snapshot_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    tools = {k: v for k, v in data.items() if k != "_meta"}
    assert len(tools) == TOOL_COUNT, f"Expected {TOOL_COUNT} tools, got {len(tools)}"

    total_bytes = 0
    for name, schema in tools.items():
        sz = measure_tool_schema_bytes(schema)
        assert sz <= MAX_TOOL_SCHEMA_BYTES, (
            f"Tool '{name}' schema size {sz}B exceeds physical ceiling {MAX_TOOL_SCHEMA_BYTES}B"
        )
        total_bytes += sz

    assert total_bytes <= MAX_TOTAL_SCHEMA_BYTES, (
        f"Total schema size {total_bytes}B exceeds cumulative ceiling {MAX_TOTAL_SCHEMA_BYTES}B"
    )

    # P-4: Validate snapshot through production validator
    assert validate_schema_size_budget(data) == [], "Snapshot has size budget violations"


def test_validate_schema_size_budget_pure_aggregation() -> None:
    """P-1: Pure validator deterministic aggregation with overridden small thresholds."""
    from ide_schema_export import SizeViolation, format_size_violations, validate_schema_size_budget
    from tool_surface_constants import measure_tool_schema_bytes

    # Tool A (120B > 100B), Tool B (110B > 100B), Tool C (50B <= 100B)
    # Total = 120 + 110 + 50 = 280B > 150B
    fixture = {
        "a": {"name": "a", "description": "A" * 90},
        "b": {"name": "b", "description": "B" * 80},
        "c": {"name": "c", "description": "C" * 20},
    }
    sz_a = measure_tool_schema_bytes(fixture["a"])
    sz_b = measure_tool_schema_bytes(fixture["b"])
    sz_c = measure_tool_schema_bytes(fixture["c"])
    assert sz_a > 100
    assert sz_b > 100
    assert sz_c <= 100
    assert (sz_a + sz_b + sz_c) > 150

    vs = validate_schema_size_budget(fixture, max_tool_bytes=100, max_total_bytes=150)
    assert len(vs) == 3
    assert sorted((v.kind, v.tool_name) for v in vs) == [("tool", "a"), ("tool", "b"), ("total", "")]

    # Assert exact fields
    by_key = {(v.kind, v.tool_name): v for v in vs}
    assert by_key[("tool", "a")].measured_bytes == sz_a
    assert by_key[("tool", "a")].limit_bytes == 100
    assert by_key[("tool", "b")].measured_bytes == sz_b
    assert by_key[("tool", "b")].limit_bytes == 100
    assert by_key[("total", "")].measured_bytes == (sz_a + sz_b + sz_c)
    assert by_key[("total", "")].limit_bytes == 150

    lines = format_size_violations(vs)
    assert len(lines) == 3
    for line in lines:
        assert line.startswith("SCHEMA_SIZE_VIOLATION: ")


def test_validate_schema_size_budget_boundary_helper() -> None:
    """P-2: Convergent pad helper for exact == pass and +1 fail boundaries."""
    import copy
    from ide_schema_export import validate_schema_size_budget
    from tool_surface_constants import MAX_TOOL_SCHEMA_BYTES, SCHEMA_META_KEY, measure_tool_schema_bytes

    def _pad_to_exact_bytes(base_tool: dict, target: int) -> dict:
        t = copy.deepcopy(base_tool)
        for _ in range(10):
            d = target - measure_tool_schema_bytes(t)
            if d == 0:
                break
            if d > 0:
                t["description"] = t.get("description", "") + ("x" * d)
            else:
                t["description"] = t["description"][:d]
        assert measure_tool_schema_bytes(t) == target, f"Failed to pad to {target}"
        return t

    base = {"type": "object", "properties": {}, "description": "base"}

    # == MAX_TOOL_SCHEMA_BYTES passes
    tool_exact = _pad_to_exact_bytes(base, MAX_TOOL_SCHEMA_BYTES)
    assert validate_schema_size_budget({"tool1": tool_exact}) == []

    # == MAX_TOOL_SCHEMA_BYTES + 1 fails with exactly 1 tool violation
    tool_plus_one = _pad_to_exact_bytes(base, MAX_TOOL_SCHEMA_BYTES + 1)
    vs_plus_one = validate_schema_size_budget(
        {"tool1": tool_plus_one}, max_total_bytes=MAX_TOOL_SCHEMA_BYTES + 100
    )
    assert len(vs_plus_one) == 1
    assert vs_plus_one[0].kind == "tool"
    assert vs_plus_one[0].measured_bytes == MAX_TOOL_SCHEMA_BYTES + 1

    # Total boundary
    # 2 tools of 50 bytes = 100 bytes
    t1 = _pad_to_exact_bytes(base, 50)
    t2 = _pad_to_exact_bytes(base, 50)
    assert validate_schema_size_budget({"t1": t1, "t2": t2}, max_total_bytes=100) == []
    vs_total_plus = validate_schema_size_budget({"t1": t1, "t2": t2}, max_total_bytes=99)
    assert len(vs_total_plus) == 1
    assert vs_total_plus[0].kind == "total"
    assert vs_total_plus[0].measured_bytes == 100

    # Empty snapshot and _meta-only return []
    assert validate_schema_size_budget({}) == []
    assert validate_schema_size_budget({SCHEMA_META_KEY: {"schema_version": 1}}) == []


def test_validate_schema_size_budget_idempotent_volatile_strip() -> None:
    """P-5: Volatile keys ($schema, title) are stripped internally without mutating inputs."""
    import copy
    from ide_schema_export import _strip_volatile_keys, validate_schema_size_budget

    raw = {
        "tool_with_volatile": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "VolatileTitle",
            "type": "object",
            "description": "Clean description",
            "properties": {
                "param1": {"title": "ParamTitle", "type": "string"},
            },
        }
    }
    raw_copy = copy.deepcopy(raw)

    vs1 = validate_schema_size_budget(raw)
    vs2 = validate_schema_size_budget(_strip_volatile_keys(raw))
    assert vs1 == vs2, "validate_schema_size_budget must produce identical result on raw vs pre-stripped schema"
    assert raw == raw_copy, "validate_schema_size_budget must not mutate input dictionary"


def test_run_cli_size_gate_positive_and_negative_direct(capsys: pytest.CaptureFixture) -> None:
    """P-3: run_cli direct test verifying positive pass and negative fail-closed without side effects."""
    import copy
    import shutil
    from ide_schema_export import (
        EXIT_INVALID,
        EXIT_OK,
        SNAPSHOT_FILENAME,
        run_cli,
    )
    from tool_surface_constants import (
        EXPECTED_TOOL_NAMES,
        MAX_TOOL_SCHEMA_BYTES,
        SCHEMA_META_KEY,
        SNAPSHOT_SCHEMA_VERSION,
    )

    test_cache_dir = REPO_ROOT / ".agents" / "_test_cache_run_cli"
    if test_cache_dir.exists():
        shutil.rmtree(test_cache_dir, ignore_errors=True)
    test_cache_dir.mkdir(parents=True, exist_ok=True)
    target_snapshot = test_cache_dir / SNAPSHOT_FILENAME

    try:
        # 1. Construct valid live schemas
        valid_live = {
            tool_name: {"description": f"Tool {tool_name}", "parameters": {"type": "object", "properties": {}}}
            for tool_name in EXPECTED_TOOL_NAMES
        }
        valid_live[SCHEMA_META_KEY] = {"schema_version": SNAPSHOT_SCHEMA_VERSION}

        # Positive test: --write
        rc_write = run_cli(["--write", "--cache-dir", str(test_cache_dir)], introspect=lambda: valid_live)
        assert rc_write == EXIT_OK, "Valid live schema must succeed on --write"
        assert target_snapshot.is_file(), "Snapshot file must be generated"
        valid_snapshot_bytes = target_snapshot.read_bytes()
        initial_dir_entries = sorted(p.name for p in test_cache_dir.iterdir())

        # Positive test: --check
        rc_check = run_cli(["--check", "--cache-dir", str(test_cache_dir)], introspect=lambda: valid_live)
        assert rc_check == EXIT_OK, "Matching snapshot must succeed on --check"

        # Negative test: Oversized tool schema
        oversized_live = copy.deepcopy(valid_live)
        first_tool = sorted(EXPECTED_TOOL_NAMES)[0]
        oversized_live[first_tool]["description"] = "X" * (MAX_TOOL_SCHEMA_BYTES + 50)

        capsys.readouterr()  # clear buffer
        rc_neg_write = run_cli(["--write", "--cache-dir", str(test_cache_dir)], introspect=lambda: oversized_live)
        assert rc_neg_write == EXIT_INVALID, "Oversized schema must fail with EXIT_INVALID on --write"

        captured = capsys.readouterr()
        assert "SCHEMA_SIZE_VIOLATION:" in captured.err, "stderr must contain SCHEMA_SIZE_VIOLATION prefix"
        assert "SCHEMA_SIZE_VIOLATION:" not in captured.out, "stdout must remain clean of size violations"

        # Verify zero side-effects on target file and directory
        assert target_snapshot.read_bytes() == valid_snapshot_bytes, "Target snapshot must remain untouched on violation"
        assert sorted(p.name for p in test_cache_dir.iterdir()) == initial_dir_entries, "No temporary files may remain in target directory"
    finally:
        if test_cache_dir.exists():
            shutil.rmtree(test_cache_dir, ignore_errors=True)
