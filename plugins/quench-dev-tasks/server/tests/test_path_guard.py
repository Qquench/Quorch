# -*- coding: utf-8 -*-
"""Comprehensive Cross-Platform Path Guard & Workspace Sandboxing Tests.

Verifies host-invariant behavior of sanitize_workspace_path and to_workspace_relative_path
across POSIX and Windows separator semantics, Win32 aliases, and attack vectors.
"""
import os
from pathlib import Path
import sys
import tempfile
import pytest

# Ensure server directory is in sys.path regardless of execution root
server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from path_guard import (
    sanitize_workspace_path,
    to_workspace_relative_path,
    PathTraversalError,
)

ATTACK_VECTORS = [
    # 1. Backslash Windows-style traversal (the exact vector that bypassed Ubuntu CI)
    "..\\..\\windows\\system32\\cmd.exe",
    # 2. Forward slash POSIX-style traversal
    "../../etc/passwd",
    # 3. Windows drive-relative and drive-absolute paths
    "C:foo",
    "C:\\windows\\system32",
    "d:/work/quorch",
    # 4. UNC network share
    "\\\\srv\\share\\x",
    "//srv/share/x",
    # 5. Root absolute paths
    "/abs/path",
    "/etc/shadow",
    # 6. URL / Percent-encoded traversal attempts
    "%2e%2e%2f",
    "%2e%2e%5c",
    "foo/%2e%2e/bar",
    # 7. NUL byte injection
    "a\x00/..",
    "file.txt\x00.exe",
    # 8. Multi-dot sequences (Win32 evasions)
    "....//....//",
    "..../foo",
    ".../bar",
    # 9. Direct parent references
    "..",
    "../",
    "..\\",
    # 10. Win32 trailing dot / space evasions (causes Win32 alias mutation)
    "a. ",
    "folder. ",
    "file.txt. ",
    "foo.txt.",
    "bar ",
    # 11. Nested traversal bouncing out and back
    "a\\..\\..\\b",
    "a/../../b",
    "sub/../../outside.py",
    # 12. Windows reserved device names
    "CON",
    "con.txt",
    "PRN",
    "aux.log",
    "COM1",
    "com3.py",
    "LPT2",
    # 13. Empty or null values
    "",
    "   ",
    "  \t\n  ",
]


@pytest.mark.parametrize("vec", ATTACK_VECTORS)
def test_attack_vectors_rejected_host_invariant(tmp_path: Path, vec: str):
    """Every traversal, UNC, drive, or Win32 evasion vector must fail-closed with PathTraversalError."""
    ws = str(tmp_path)
    with pytest.raises(PathTraversalError):
        sanitize_workspace_path(ws, vec)

    with pytest.raises(PathTraversalError):
        to_workspace_relative_path(ws, vec)


def test_none_candidate_rejected(tmp_path: Path):
    """None candidate must raise PathTraversalError."""
    ws = str(tmp_path)
    with pytest.raises(PathTraversalError):
        sanitize_workspace_path(ws, None)  # type: ignore[arg-type]


def test_valid_in_tree_paths(tmp_path: Path):
    """Valid in-tree relative paths with slashes or backslashes must resolve cleanly."""
    ws = str(tmp_path)

    # 1. Forward slash relative path
    p1 = sanitize_workspace_path(ws, "src/components/button.py")
    assert p1 == os.path.realpath(os.path.join(ws, "src", "components", "button.py"))
    assert to_workspace_relative_path(ws, "src/components/button.py") == "src/components/button.py"

    # 2. Backslash relative path (must be normalized to '/' in relative output)
    p2 = sanitize_workspace_path(ws, "docs\\dev_tasks\\task.md")
    assert p2 == os.path.realpath(os.path.join(ws, "docs", "dev_tasks", "task.md"))
    assert to_workspace_relative_path(ws, "docs\\dev_tasks\\task.md") == "docs/dev_tasks/task.md"

    # 3. In-tree parent navigation that stays confined
    p3 = sanitize_workspace_path(ws, "sub/dir/../file.py")
    assert p3 == os.path.realpath(os.path.join(ws, "sub", "file.py"))
    assert to_workspace_relative_path(ws, "sub/dir/../file.py") == "sub/file.py"


def test_must_exist_flag(tmp_path: Path):
    """must_exist=True requires physical presence on disk."""
    ws = str(tmp_path)
    existing_file = tmp_path / "valid.txt"
    existing_file.write_text("hello", encoding="utf-8")

    # Existing file passes both checks
    assert sanitize_workspace_path(ws, "valid.txt", must_exist=False) == str(existing_file.resolve())
    assert sanitize_workspace_path(ws, "valid.txt", must_exist=True) == str(existing_file.resolve())

    # Non-existent file succeeds when must_exist=False, fails when must_exist=True
    assert sanitize_workspace_path(ws, "missing.txt", must_exist=False)
    with pytest.raises(PathTraversalError, match="does not exist"):
        sanitize_workspace_path(ws, "missing.txt", must_exist=True)


def test_workspace_root_resolution_guard(tmp_path: Path):
    """Paths resolving to workspace root itself are rejected unless allow_workspace_root=True."""
    ws = str(tmp_path)

    # By default, pointing to the root itself is rejected
    with pytest.raises(PathTraversalError, match="workspace root itself"):
        sanitize_workspace_path(ws, ".")

    with pytest.raises(PathTraversalError, match="workspace root itself"):
        sanitize_workspace_path(ws, "sub/..")

    # With allow_workspace_root=True, resolves to real_ws
    assert sanitize_workspace_path(ws, ".", allow_workspace_root=True) == str(tmp_path.resolve())
    assert to_workspace_relative_path(ws, ".", allow_workspace_root=True) == "."


def test_dual_engine_posix_and_windows_invariance(tmp_path: Path):
    """Assert that paths with mixed or reversed slashes behave identically regardless of host OS."""
    ws = str(tmp_path)

    # Mixed separators in safe path
    mixed_safe = "a/b\\c/d.py"
    rel_norm = to_workspace_relative_path(ws, mixed_safe)
    assert rel_norm == "a/b/c/d.py"

    # Mixed separators in traversal path
    mixed_evil = "a/..\\..\\evil.py"
    with pytest.raises(PathTraversalError):
        sanitize_workspace_path(ws, mixed_evil)


def test_symlink_escape_defense(tmp_path: Path):
    """Symlink pointing outside workspace root must be caught by realpath + commonpath."""
    outside_dir = tempfile.mkdtemp(prefix="quench_outside_")
    outside_file = os.path.join(outside_dir, "secret.txt")
    with open(outside_file, "w", encoding="utf-8") as f:
        f.write("confidential")

    link_path = tmp_path / "leak_link"
    try:
        os.symlink(outside_dir, str(link_path))
    except (OSError, NotImplementedError):
        # On Windows without developer mode/privileges, symlink creation might fail
        pytest.skip("Symlink creation not supported in this environment")

    # Attempting to access file through symlink pointing outside workspace must be blocked
    with pytest.raises(PathTraversalError):
        sanitize_workspace_path(str(tmp_path), "leak_link/secret.txt")
