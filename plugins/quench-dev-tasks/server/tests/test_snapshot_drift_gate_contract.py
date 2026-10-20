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
