# -*- coding: utf-8 -*-
"""Unified Cross-Platform Path Confinement and Traversal Guard.

Provides host-invariant path sanitization and workspace sandboxing for Quench DevTasks.
Guarantees consistent security semantics across POSIX (Linux/macOS) and Windows (NT).
"""
from __future__ import annotations

import fnmatch
import os
import re
import sys
import unicodedata
import urllib.parse
from dataclasses import dataclass
from typing import Final, Optional, Sequence

_NUL_BYTE_RE: Final = re.compile(r"\x00")
_DRIVE: Final = re.compile(r"^[a-zA-Z]:")
_MULTI_DOT: Final = re.compile(r"^\.{3,}$")
_WIN_RESERVED_NAMES: Final = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class PathTraversalError(ValueError):
    """Raised when a candidate path violates workspace confinement or contains traversal vectors. / 当候选路径违反工作区沙箱约束或包含逃逸向量时抛出。"""
    pass


def sanitize_workspace_path(
    workspace_root: str,
    candidate: str | os.PathLike[str],
    *,
    must_exist: bool = False,
    allow_workspace_root: bool = False,
) -> str:
    """Sanitize and confine a candidate path within workspace_root, returning a canonical absolute realpath.

    Pipeline invariant:
    1. Null & empty string checks
    2. NUL byte injection check
    3. URL / percent-encoded traversal inspection
    4. Host-invariant separator normalization (replace '\\' with '/')
    5. Structural reject: absolute ('/'), UNC ('//'), drive / NTFS ADS (':')
    6. Component-level defense: Win32 reserved names, trailing space/dot, multi-dot
    7. Physical resolution via realpath(abspath(join(...)))
    8. Sandboxed confinement via commonpath with normcase comparison
    9. Relative path prefix traversal assertion
    10. Physical disk existence check (if must_exist=True)

    Args:
        workspace_root: Absolute or relative root of the managed workspace.
        candidate: Candidate path string or PathLike object.
        must_exist: If True, candidate must physically exist on disk.
        allow_workspace_root: If True, candidate may resolve to workspace_root itself ('.').

    Returns:
        Canonical absolute path (symlinks resolved, realpath).

    Raises:
        PathTraversalError: If path is None, empty, contains NUL, escapes workspace, or fails checks.
    """
    if candidate is None:
        raise PathTraversalError("Candidate path cannot be None")

    cand_str = str(candidate)
    if not cand_str.strip():
        raise PathTraversalError("Candidate path cannot be empty or whitespace only")

    # 1. NUL byte injection defense
    if _NUL_BYTE_RE.search(cand_str):
        raise PathTraversalError(f"NUL byte injection detected in path: {candidate!r}")

    # 2. URL / percent-encoded traversal defense
    if "%" in cand_str:
        try:
            unquoted = urllib.parse.unquote(cand_str)
            if unquoted != cand_str:
                norm_unquoted = unquoted.replace("\\", "/")
                if (
                    "/.." in norm_unquoted
                    or norm_unquoted.startswith("../")
                    or norm_unquoted == ".."
                    or _NUL_BYTE_RE.search(unquoted)
                    or norm_unquoted.startswith("/")
                    or _DRIVE.match(norm_unquoted)
                    or ":" in norm_unquoted
                ):
                    raise PathTraversalError(
                        f"Percent-encoded traversal vector detected: {candidate!r}"
                    )
        except PathTraversalError:
            raise
        except Exception:
            pass

    # 3. Host-invariant separator normalization (BEFORE any path operations)
    norm = cand_str.replace("\\", "/")

    # 4. Reject absolute / UNC / Windows drive / NTFS ADS formats pre-resolution
    if norm.startswith("/"):
        raise PathTraversalError(f"Absolute path escapes workspace: {candidate!r}")
    if norm.startswith("//"):
        raise PathTraversalError(f"UNC network path escapes workspace: {candidate!r}")
    if ":" in norm:
        raise PathTraversalError(f"Colon, Windows drive, or NTFS ADS path rejected: {candidate!r}")

    # 5. Component-level defense: Win32 aliases, multi-dots, trailing spaces/dots
    parts = norm.split("/")
    for part in parts:
        if not part:
            continue
        if _MULTI_DOT.match(part):
            raise PathTraversalError(f"Invalid multi-dot sequence detected: {candidate!r}")
        if part not in (".", "..") and (part.endswith(".") or part.endswith(" ")):
            raise PathTraversalError(
                f"Win32 trailing dot/space evasion detected: {candidate!r}"
            )
        stem = part.split(".")[0].upper()
        if stem in _WIN_RESERVED_NAMES:
            raise PathTraversalError(
                f"Windows reserved device name detected: {candidate!r}"
            )

    # 6. Resolve against absolute physical workspace root
    real_ws = os.path.realpath(os.path.abspath(workspace_root))
    joined = os.path.realpath(os.path.abspath(os.path.join(real_ws, *parts)))

    # 7. Confinement check via commonpath (catches parent traversal and cross-drive on Windows)
    try:
        common = os.path.commonpath([real_ws, joined])
    except ValueError:
        raise PathTraversalError(f"Cross-drive path escapes workspace: {candidate!r}")

    # Use normcase for host-safe case comparison (prevents Windows C: vs c: false positives)
    if os.path.normcase(common) != os.path.normcase(real_ws):
        raise PathTraversalError(f"Path escapes workspace root: {candidate!r}")

    # 8. Relative path check (extra defense against edge degenerate resolutions)
    rel = os.path.relpath(joined, real_ws).replace("\\", "/")
    if rel == ".":
        if not allow_workspace_root:
            raise PathTraversalError(
                f"Path resolves to workspace root itself: {candidate!r}"
            )
    elif rel.split("/")[0] == "..":
        raise PathTraversalError(
            f"Parent directory traversal escapes workspace: {candidate!r}"
        )

    # 9. Existence verification
    if must_exist and not os.path.exists(joined):
        raise PathTraversalError(f"Path does not exist in workspace: {candidate!r}")

    return joined


def to_workspace_relative_path(
    workspace_root: str,
    candidate: str | os.PathLike[str],
    *,
    must_exist: bool = False,
    allow_workspace_root: bool = False,
) -> str:
    """Sanitize candidate and return a relative path formatted with forward slashes ('/').

    Args:
        workspace_root: Absolute or relative root of the managed workspace.
        candidate: Candidate path string or PathLike object.
        must_exist: If True, candidate must physically exist on disk.
        allow_workspace_root: If True, candidate may resolve to workspace_root itself ('.').

    Returns:
        Relative path string with forward slashes (e.g. 'docs/dev_tasks/foo.md').

    Raises:
        PathTraversalError: If path is invalid or escapes workspace.
    """
    abs_path = sanitize_workspace_path(
        workspace_root=workspace_root,
        candidate=candidate,
        must_exist=must_exist,
        allow_workspace_root=allow_workspace_root,
    )
    real_ws = os.path.realpath(os.path.abspath(workspace_root))
    rel = os.path.relpath(abs_path, real_ws).replace("\\", "/")
    return rel


def canonicalize_path(
    raw_path: str | os.PathLike[str],
    *,
    base_dir: str | os.PathLike[str],
    follow_symlinks: bool = True,
) -> str:
    """Return a canonical POSIX-style relative path relative to base_dir.

    Normalizes Unicode (NFC), collapses redundant segments (./..), and verifies
    confinement within base_dir.
    Raises PathTraversalError on traversal attempts, NUL bytes, or invalid paths.
    """
    if raw_path is None:
        raise PathTraversalError("Path cannot be None")
    raw_str = str(raw_path)
    if not raw_str.strip():
        raise PathTraversalError("Path cannot be empty or whitespace only")
    if _NUL_BYTE_RE.search(raw_str):
        raise PathTraversalError(f"NUL byte injection detected in path: {raw_path!r}")

    # NFC normalization
    raw_str = unicodedata.normalize("NFC", raw_str)

    # Host-invariant separator normalization
    clean = raw_str.replace("\\", "/")

    # Check for direct escape prefixes
    if clean.startswith("../") or clean == "..":
        raise PathTraversalError(f"Parent directory traversal escapes base directory: {raw_path!r}")

    base_str = str(base_dir)
    real_base = os.path.realpath(os.path.abspath(base_str)) if follow_symlinks else os.path.abspath(base_str)

    if os.path.isabs(clean):
        target_abs = os.path.realpath(os.path.abspath(clean)) if follow_symlinks else os.path.abspath(clean)
    else:
        target_abs = os.path.realpath(os.path.abspath(os.path.join(real_base, clean))) if follow_symlinks else os.path.abspath(os.path.join(real_base, clean))

    try:
        common = os.path.commonpath([real_base, target_abs])
    except ValueError:
        raise PathTraversalError(f"Cross-drive path escapes base directory: {raw_path!r}")

    if os.path.normcase(common) != os.path.normcase(real_base):
        raise PathTraversalError(f"Path escapes base directory: {raw_path!r}")

    rel = os.path.relpath(target_abs, real_base).replace("\\", "/")
    if rel == "." or rel == "":
        return "."
    if rel.startswith(".."):
        raise PathTraversalError(f"Parent directory traversal escapes base directory: {raw_path!r}")

    return unicodedata.normalize("NFC", rel)


def comparison_key(canonical_path: str, *, case_sensitive: bool) -> str:
    """Generate platform-aware comparison key (casefold when case_sensitive=False)."""
    norm = unicodedata.normalize("NFC", str(canonical_path).replace("\\", "/"))
    if not case_sensitive:
        return norm.casefold()
    return norm


def _glob_to_regex(pattern: str, case_sensitive: bool = True) -> re.Pattern:
    """Translate glob pattern with ** (recursive) and * (single segment) into regex."""
    clean = pattern.replace("\\", "/").strip()
    res = []
    i = 0
    n = len(clean)
    while i < n:
        c = clean[i]
        if c == "*":
            if i + 1 < n and clean[i + 1] == "*":
                # '**'
                if i + 2 < n and clean[i + 2] == "/":
                    res.append("(?:.*/)?")
                    i += 3
                    continue
                else:
                    res.append(".*")
                    i += 2
                    continue
            else:
                # '*' single segment
                res.append("[^/]*")
                i += 1
                continue
        elif c == "?":
            res.append("[^/]")
            i += 1
        elif c in r".^$+-=!()[]{}\|":
            res.append(re.escape(c))
            i += 1
        else:
            res.append(c)
            i += 1
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(f"^{''.join(res)}$", flags)


def is_within_whitelist(
    canonical_rel_path: str,
    whitelist: Sequence[str | os.PathLike[str]],
    *,
    case_sensitive: bool = True,
) -> bool:
    """Check if canonical relative path matches any pattern or path in whitelist."""
    norm_path = unicodedata.normalize("NFC", str(canonical_rel_path).replace("\\", "/")).strip("/")
    basename = os.path.basename(norm_path)

    for item in whitelist:
        pat_str = unicodedata.normalize("NFC", str(item).replace("\\", "/")).strip()

        # Exact match
        if case_sensitive:
            if norm_path == pat_str:
                return True
        else:
            if norm_path.casefold() == pat_str.casefold():
                return True

        regex = _glob_to_regex(pat_str, case_sensitive=case_sensitive)
        if regex.match(norm_path):
            return True

        # If pattern has no directory separators (e.g. *.md), allow matching basename
        if "/" not in pat_str and regex.match(basename):
            return True

    return False


@dataclass(frozen=True)
class SubsetCheckResult:
    is_subset: bool
    violating_paths: tuple[str, ...]
    normalized_whitelist: frozenset[str]


def check_whitelist_subset(
    touched_paths: Sequence[str | os.PathLike[str]],
    whitelist: Sequence[str | os.PathLike[str]],
    *,
    base_dir: str | os.PathLike[str],
    case_sensitive: Optional[bool] = None,
) -> SubsetCheckResult:
    """Verify that all touched paths fall strictly within declared whitelist."""
    cs = (sys.platform != "win32") if case_sensitive is None else bool(case_sensitive)
    norm_whitelist = frozenset(
        comparison_key(str(w).replace("\\", "/"), case_sensitive=cs)
        for w in whitelist
    )

    violating: list[str] = []
    for p in touched_paths:
        try:
            can_rel = canonicalize_path(p, base_dir=base_dir)
        except PathTraversalError:
            violating.append(str(p).replace("\\", "/"))
            continue

        if not is_within_whitelist(can_rel, whitelist, case_sensitive=cs):
            violating.append(can_rel)

    return SubsetCheckResult(
        is_subset=len(violating) == 0,
        violating_paths=tuple(sorted(violating)),
        normalized_whitelist=norm_whitelist,
    )

