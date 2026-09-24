# -*- coding: utf-8 -*-
"""Static AST gate preventing destructive global monkeypatching of os.stat.

Prevents cross-platform CI crashes where global C-level monkeypatches
poison pytest's tmp_path cleanup, linecache, and internal reporting.
"""

from __future__ import annotations

import ast
from pathlib import Path
import pytest

_FORBIDDEN_STAT_ATTRS = frozenset({
    "stat",
    "lstat",
    "exists",
    "lexists",
    "isfile",
    "isdir",
    "islink",
    "getmtime",
    "getsize",
    "getctime",
    "getatime",
})


def _find_test_and_fixture_files() -> list[Path]:
    tests_dir = Path(__file__).parent
    files: list[Path] = []
    for p in tests_dir.rglob("*.py"):
        if "__pycache__" in p.parts or ".pytest_cache" in p.parts:
            continue
        if p.name.startswith("test_") or p.name == "conftest.py":
            files.append(p)
    return files


def _is_stat_attribute(node: ast.AST) -> bool:
    """Check if node refers to os.stat, os.lstat, os.path.exists, etc."""
    if isinstance(node, ast.Attribute):
        if node.attr in _FORBIDDEN_STAT_ATTRS:
            if isinstance(node.value, ast.Name) and node.value.id == "os":
                return True
            if isinstance(node.value, ast.Attribute) and node.value.attr == "path":
                if isinstance(node.value.value, ast.Name) and node.value.value.id == "os":
                    return True
    return False


def _check_ast_for_stat_poisoning(tree: ast.AST, filename: str) -> list[str]:
    violations: list[str] = []

    for node in ast.walk(tree):
        # 1. Detect direct assignment: os.stat = ... or os.lstat = ...
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if _is_stat_attribute(target):
                    violations.append(
                        f"{filename}:{node.lineno} directly rebinds os stat-family attribute"
                    )

        # 2. Detect function calls: monkeypatch.setattr, mock.patch, setattr(os, "stat", ...)
        elif isinstance(node, ast.Call):
            # Check builtin setattr(os, "stat", ...)
            if isinstance(node.func, ast.Name) and node.func.id == "setattr":
                if len(node.args) >= 2:
                    first = node.args[0]
                    second = node.args[1]
                    if isinstance(first, ast.Name) and first.id == "os":
                        if isinstance(second, ast.Constant) and second.value in _FORBIDDEN_STAT_ATTRS:
                            violations.append(
                                f"{filename}:{node.lineno} calls setattr(os, '{second.value}', ...)"
                            )

            # Check monkeypatch.setattr(...) or patch.object(...)
            is_patch_call = False
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in ("setattr", "patch", "object"):
                    is_patch_call = True

            if is_patch_call and len(node.args) >= 3:
                first_arg = node.args[0]
                second_arg = node.args[1]
                replacement_arg = node.args[2]

                is_stat_target = False
                if isinstance(first_arg, ast.Name) and first_arg.id == "os":
                    if isinstance(second_arg, ast.Constant) and second_arg.value in _FORBIDDEN_STAT_ATTRS:
                        is_stat_target = True
                elif isinstance(first_arg, ast.Attribute) and first_arg.attr == "path":
                    if isinstance(second_arg, ast.Constant) and second_arg.value in _FORBIDDEN_STAT_ATTRS:
                        is_stat_target = True
                elif isinstance(first_arg, ast.Constant) and any(
                    first_arg.value == f"os.{attr}" or first_arg.value == f"os.path.{attr}"
                    for attr in _FORBIDDEN_STAT_ATTRS
                ):
                    is_stat_target = True

                if is_stat_target:
                    # Check replacement
                    if isinstance(replacement_arg, ast.Lambda):
                        violations.append(
                            f"{filename}:{node.lineno} passes a lambda directly to monkeypatch os stat-family"
                        )
                    elif isinstance(replacement_arg, ast.Name):
                        # Inspect the named replacement function in the same module
                        rep_name = replacement_arg.id
                        for top in ast.walk(tree):
                            if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)) and top.name == rep_name:
                                has_return = any(isinstance(n, ast.Return) for n in ast.walk(top))
                                has_raise = any(isinstance(n, ast.Raise) for n in ast.walk(top))
                                if has_raise and not has_return:
                                    violations.append(
                                        f"{filename}:{node.lineno} patches os stat-family with '{rep_name}', "
                                        f"which unconditionally raises without returning"
                                    )

    return violations


def test_no_unconditional_os_stat_monkeypatch():
    """Ensure no test in tests/ registers an unconditional raising monkeypatch on os.stat or os.lstat."""
    violations: list[str] = []

    for test_file in _find_test_and_fixture_files():
        if test_file.name == Path(__file__).name:
            continue

        try:
            tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
        except Exception as e:
            pytest.fail(f"Failed to parse {test_file}: {e}")

        file_violations = _check_ast_for_stat_poisoning(tree, test_file.name)
        violations.extend(file_violations)

    assert not violations, (
        "Found unconditional destructive os.stat/lstat monkeypatching:\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\nUse targeted path filtering (returning real_stat) or run in a subprocess."
    )


def test_gate_self_test_detects_bad_snippet():
    """Verify that the static AST gate reliably catches offending snippets."""
    bad_code = """
def test_bad(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(os, "stat", _boom)
"""
    tree = ast.parse(bad_code, filename="bad_sample.py")
    violations = _check_ast_for_stat_poisoning(tree, "bad_sample.py")
    assert len(violations) >= 1
    assert "bad_sample.py:5" in violations[0]
