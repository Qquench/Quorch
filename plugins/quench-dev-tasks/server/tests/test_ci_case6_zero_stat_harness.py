# -*- coding: utf-8 -*-
"""test_ci_case6_zero_stat_harness.py - Static AST gate for Case 6 / W10 scandir zero-stat harness.

Verifies:
1. Locates FunctionDef for `_snapshot_business_state_scandir` in `reviewer_jobs.py`.
2. AST walks strictly inside this FunctionDef node.
3. Asserts zero explicit calls to os.stat, os.lstat, Path.stat, Path.lstat.
4. Explicitly permits entry.stat(follow_symlinks=False).
"""

from __future__ import annotations

import ast
from pathlib import Path
import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
REVIEWER_JOBS_PATH = SERVER_DIR / "reviewer_jobs.py"


def _get_function_def(module_path: Path, func_name: str) -> ast.FunctionDef:
    content = module_path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(module_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    raise AssertionError(f"Function {func_name} not found in {module_path}")


def test_scandir_zero_explicit_os_stat_in_ast():
    """Case 6 / Blocker F: _snapshot_business_state_scandir contains zero explicit os.stat calls."""
    func_node = _get_function_def(REVIEWER_JOBS_PATH, "_snapshot_business_state_scandir")

    violations: list[str] = []
    entry_stat_calls = 0

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue

        fn = node.func
        if isinstance(fn, ast.Attribute):
            attr_name = fn.attr
            if attr_name in {"stat", "lstat"}:
                if isinstance(fn.value, ast.Name):
                    if fn.value.id in {"os", "Path"}:
                        violations.append(f"Forbidden call: {fn.value.id}.{attr_name} at line {node.lineno}")
                    elif fn.value.id == "entry":
                        entry_stat_calls += 1
                    else:
                        violations.append(f"Forbidden call: {fn.value.id}.{attr_name} at line {node.lineno}")
                elif isinstance(fn.value, ast.Attribute):
                    violations.append(f"Forbidden attribute call ending in .{attr_name} at line {node.lineno}")

    assert violations == [], f"Found forbidden stat calls in _snapshot_business_state_scandir: {violations}"
    assert entry_stat_calls >= 1, "Expected at least one entry.stat call in _snapshot_business_state_scandir"
