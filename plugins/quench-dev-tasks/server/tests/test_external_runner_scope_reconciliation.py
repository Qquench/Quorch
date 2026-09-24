"""Unit tests for checkout baseline snapshot, physical scope reconciliation, and path guard invariants.

Covers Task 1.2 and Task 1.3:
- Baseline capture and serialization
- Fast path (inode+mtime+size) and slow path (sha256)
- External runner scope violation rejection (deny)
- Whitelisted modifications allowance (allow)
- Budget timeout fail-closed circuit breaker (degraded)
- Path traversal defense (../../), NUL byte injection, and cross-platform case normalization
"""

from __future__ import annotations

import os
import sys
import time
from typing import Mapping
import pytest

from manifest import (
    BaselineSnapshot,
    FileFingerprint,
    ReconciliationReport,
    capture_baseline,
    get_baseline_path,
    load_baseline_snapshot,
    reconcile_workspace_against_whitelist,
    save_baseline_snapshot,
)
from path_guard import (
    PathTraversalError,
    SubsetCheckResult,
    canonicalize_path,
    check_whitelist_subset,
    comparison_key,
    is_within_whitelist,
)
from state_machine import (
    STATUS_CONFIRMED,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    ScopeViolationError,
    extract_task_whitelist,
    transition_task,
)


@pytest.fixture
def workspace_with_baseline(tmp_path):
    """Setup a mock workspace with a task file and source files."""
    ws = tmp_path / "mock_repo"
    ws.mkdir()
    (ws / ".agents" / ".quorch" / "baselines").mkdir(parents=True)
    (ws / "docs" / "dev_tasks").mkdir(parents=True)
    (ws / "src").mkdir(parents=True)

    # Source files
    (ws / "src" / "app.py").write_text("print('original')", encoding="utf-8")
    (ws / "src" / "helper.py").write_text("def help(): pass", encoding="utf-8")
    (ws / "README.md").write_text("# Readme", encoding="utf-8")

    task_file = ws / "docs" / "dev_tasks" / "2026-09-24_task.md"
    task_content = """# Dev Tasks
### 任务 1.1 🔨 执行中 — Test Task
#### 【涉及文件】
```
[MODIFY] src/app.py
```
"""
    task_file.write_text(task_content, encoding="utf-8")

    snapshot = capture_baseline(str(ws), task_id="1.1", session_id="test_sess")
    return ws, task_file, snapshot


def test_baseline_capture_and_serialization(tmp_path):
    """Test capturing baseline snapshot and reloading from disk."""
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "a.py").write_text("hello world", encoding="utf-8")

    snapshot = capture_baseline(str(ws), task_id="2.1", session_id="sess_123")
    assert snapshot.task_id == "2.1"
    assert snapshot.session_id == "sess_123"
    assert "a.py" in snapshot.fingerprints
    assert snapshot.fingerprints["a.py"].size > 0
    assert snapshot.snapshot_digest.startswith("sha256:")

    baseline_file = get_baseline_path(str(ws), "2.1")
    assert os.path.exists(baseline_file)

    loaded = load_baseline_snapshot(baseline_file)
    assert loaded.task_id == snapshot.task_id
    assert loaded.snapshot_digest == snapshot.snapshot_digest
    assert loaded.fingerprints["a.py"].digest == snapshot.fingerprints["a.py"].digest


def test_reconciliation_whitelisted_modification_allowed(workspace_with_baseline):
    """Test that modifying whitelisted files returns verdict='allow'."""
    ws, _, snapshot = workspace_with_baseline

    # Modify whitelisted file
    (ws / "src" / "app.py").write_text("print('modified')", encoding="utf-8")

    report = reconcile_workspace_against_whitelist(
        workspace_root=str(ws),
        snapshot=snapshot,
        whitelist_paths=["src/app.py"],
        unmanaged_patterns=["docs/**", "*.md"],
    )

    assert report.verdict == "allow"
    assert report.violating_files == ()
    assert report.checked_count > 0


def test_reconciliation_unmanaged_modification_allowed(workspace_with_baseline):
    """Test that modifying unmanaged files (e.g. docs, readme) is allowed."""
    ws, task_file, snapshot = workspace_with_baseline

    # Modify unmanaged file
    (ws / "README.md").write_text("# Updated Readme", encoding="utf-8")
    (ws / "docs" / "notes.md").write_text("Dev notes", encoding="utf-8")

    report = reconcile_workspace_against_whitelist(
        workspace_root=str(ws),
        snapshot=snapshot,
        whitelist_paths=["src/app.py"],
        unmanaged_patterns=["docs/**", "*.md"],
    )

    assert report.verdict == "allow"
    assert report.violating_files == ()


def test_reconciliation_out_of_scope_modification_denied(workspace_with_baseline):
    """Test that modifying files outside whitelist triggers verdict='deny'."""
    ws, _, snapshot = workspace_with_baseline

    # Rogue external runner modifies helper.py which is NOT in whitelist
    (ws / "src" / "helper.py").write_text("def rogue(): pass", encoding="utf-8")

    report = reconcile_workspace_against_whitelist(
        workspace_root=str(ws),
        snapshot=snapshot,
        whitelist_paths=["src/app.py"],
        unmanaged_patterns=["docs/**", "*.md"],
    )

    assert report.verdict == "deny"
    assert "src/helper.py" in report.violating_files


def test_reconciliation_new_rogue_file_denied(workspace_with_baseline):
    """Test that creating a new unwhitelisted code file triggers verdict='deny'."""
    ws, _, snapshot = workspace_with_baseline

    # Create new rogue file
    (ws / "src" / "rogue.py").write_text("import os; os.system('bad')", encoding="utf-8")

    report = reconcile_workspace_against_whitelist(
        workspace_root=str(ws),
        snapshot=snapshot,
        whitelist_paths=["src/app.py"],
        unmanaged_patterns=["docs/**", "*.md"],
    )

    assert report.verdict == "deny"
    assert "src/rogue.py" in report.violating_files


def test_reconciliation_fast_path_hits(workspace_with_baseline):
    """Test fast path hits when no files are modified."""
    ws, _, snapshot = workspace_with_baseline

    report = reconcile_workspace_against_whitelist(
        workspace_root=str(ws),
        snapshot=snapshot,
        whitelist_paths=["src/app.py"],
        unmanaged_patterns=["docs/**", "*.md"],
    )

    assert report.verdict == "allow"
    assert report.fast_path_hits > 0


def test_reconciliation_budget_timeout_degrades(workspace_with_baseline):
    """Test that exceeding time budget triggers verdict='degraded'."""
    ws, _, snapshot = workspace_with_baseline

    # Pass an impossible budget of 0.000001 ms to force degraded verdict
    report = reconcile_workspace_against_whitelist(
        workspace_root=str(ws),
        snapshot=snapshot,
        whitelist_paths=["src/app.py"],
        unmanaged_patterns=["docs/**", "*.md"],
        budget_ms=0.000001,
    )

    assert report.verdict == "degraded"
    assert report.degraded_reason is not None


def test_state_machine_transition_blocks_on_scope_violation(workspace_with_baseline):
    """Test state_machine transition_task throws ScopeViolationError on out-of-scope modifications."""
    ws, task_file, _ = workspace_with_baseline

    # Make out-of-scope edit
    (ws / "src" / "helper.py").write_text("# unexpected change", encoding="utf-8")

    with pytest.raises(ScopeViolationError) as exc_info:
        transition_task(
            filepath=str(task_file),
            task_id="1.1",
            new_status=STATUS_COMPLETED,
            workspace_root=str(ws),
        )

    assert "src/helper.py" in str(exc_info.value)

    # Now revert rogue change and only modify whitelisted file
    (ws / "src" / "helper.py").write_text("def help(): pass", encoding="utf-8")
    (ws / "src" / "app.py").write_text("print('valid change')", encoding="utf-8")

    updated = transition_task(
        filepath=str(task_file),
        task_id="1.1",
        new_status=STATUS_COMPLETED,
        workspace_root=str(ws),
    )
    assert updated.status == STATUS_COMPLETED


# ---------------------------------------------------------------------------
# Task 1.3: Path Guard, Canonicalization, and Whitelist Subset Tests
# ---------------------------------------------------------------------------

def test_canonicalize_path_normal_and_redundant(tmp_path):
    """Test collapsing ./ and ../ within base directory."""
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "src" / "a").mkdir(parents=True)
    target = ws / "src" / "a" / "b.py"
    target.write_text("test", encoding="utf-8")

    p1 = canonicalize_path("src/a/./b.py", base_dir=str(ws))
    p2 = canonicalize_path("src/a/../a/b.py", base_dir=str(ws))
    assert p1 == "src/a/b.py"
    assert p2 == "src/a/b.py"
    assert comparison_key(p1, case_sensitive=True) == comparison_key(p2, case_sensitive=True)


def test_canonicalize_path_traversal_rejection(tmp_path):
    """Test that escaping paths raise PathTraversalError."""
    ws = tmp_path / "repo"
    ws.mkdir()

    with pytest.raises(PathTraversalError):
        canonicalize_path("../../etc/passwd", base_dir=str(ws))

    with pytest.raises(PathTraversalError):
        canonicalize_path("..\\..\\windows\\system32", base_dir=str(ws))


def test_canonicalize_path_nul_byte_rejection(tmp_path):
    """Test that NUL bytes raise PathTraversalError."""
    ws = tmp_path / "repo"
    ws.mkdir()

    with pytest.raises(PathTraversalError):
        canonicalize_path("src/app.py\x00.evil", base_dir=str(ws))

    with pytest.raises(PathTraversalError):
        canonicalize_path("", base_dir=str(ws))


def test_comparison_key_case_sensitivity():
    """Test platform-aware casefold."""
    p_upper = "Src/App.Py"
    p_lower = "src/app.py"

    assert comparison_key(p_upper, case_sensitive=True) != comparison_key(p_lower, case_sensitive=True)
    assert comparison_key(p_upper, case_sensitive=False) == comparison_key(p_lower, case_sensitive=False)


def test_check_whitelist_subset_basic(tmp_path):
    """Test checking touched paths against whitelist."""
    ws = tmp_path / "repo"
    ws.mkdir()

    whitelist = ["src/app.py", "plugins/**", "*.md"]
    touched_allowed = ["src/./app.py", "plugins/foo/bar.py", "README.md"]

    result = check_whitelist_subset(touched_allowed, whitelist, base_dir=str(ws))
    assert result.is_subset is True
    assert result.violating_paths == ()

    touched_disallowed = ["src/app.py", "scripts/deploy.sh"]
    result2 = check_whitelist_subset(touched_disallowed, whitelist, base_dir=str(ws))
    assert result2.is_subset is False
    assert "scripts/deploy.sh" in result2.violating_paths


def test_check_whitelist_subset_traversal_attack(tmp_path):
    """Test that traversal candidates are caught as violating paths in check_whitelist_subset."""
    ws = tmp_path / "repo"
    ws.mkdir()

    whitelist = ["src/**"]
    candidates = ["../../etc/shadow", "src/good.py"]

    result = check_whitelist_subset(candidates, whitelist, base_dir=str(ws))
    assert result.is_subset is False
    assert len(result.violating_paths) == 1
    assert "../../etc/shadow" in result.violating_paths


def test_windows_drive_and_case_heterogeneity(tmp_path):
    """Test case insensitivity and drive mixing on Windows vs Linux."""
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "App.py").write_text("code", encoding="utf-8")

    # Lowercase in whitelist, mixed case in candidate
    whitelist = ["src/app.py"]
    candidate = "src/App.py"

    # When case_sensitive=False (Windows semantics), they must match
    res_win = check_whitelist_subset([candidate], whitelist, base_dir=str(ws), case_sensitive=False)
    assert res_win.is_subset is True

    # When case_sensitive=True (Linux semantics), they differ
    res_nix = check_whitelist_subset([candidate], whitelist, base_dir=str(ws), case_sensitive=True)
    assert res_nix.is_subset is False


def test_wildcard_glob_matching(tmp_path):
    """Test recursive glob (**) and single level (*) matching."""
    ws = tmp_path / "repo"
    ws.mkdir()

    whitelist = ["plugins/**", "scripts/*.py"]

    assert is_within_whitelist("plugins/a/b/c.py", whitelist) is True
    assert is_within_whitelist("plugins/server.py", whitelist) is True
    assert is_within_whitelist("scripts/test.py", whitelist) is True
    assert is_within_whitelist("scripts/sub/test.py", whitelist) is False
    assert is_within_whitelist("other/foo.py", whitelist) is False

