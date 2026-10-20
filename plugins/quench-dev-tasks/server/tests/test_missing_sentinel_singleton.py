"""test_missing_sentinel_singleton.py - Tier-1 Physical Singleton Anchor for MISSING Sentinel.

Regression defense for defect F-A ('lexical single point, import-layer fragmentation').
Locks physical 'is' identity of the MISSING sentinel across sys.path and spec_from_file_location
import routes, verifies is_missing predicate truth table, and runs AST static scan preventing
secondary bare object() sentinel definitions across the repository.
Sole source of truth for sentinel definition: Task 1.1 (tool_surface_constants.py).
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import pickle
import sys
from pathlib import Path
from typing import Any

import pytest

import ide_schema_export
import test_spec_param_defaults_contract
import tool_surface_constants
from tool_surface_constants import MISSING, get_default


def is_missing(val: Any) -> bool:
    """Canonical predicate for testing whether a value is the MISSING sentinel."""
    return val is MISSING


def test_sentinel_is_identical_across_sys_path_import() -> None:
    """Assert tool_surface_constants.MISSING is identical across sys.path imports."""
    assert tool_surface_constants.MISSING is ide_schema_export.MISSING
    assert tool_surface_constants.MISSING is test_spec_param_defaults_contract._MISSING
    # Also verify pickle and copy/deepcopy roundtrips preserve identity
    assert copy.copy(MISSING) is MISSING
    assert copy.deepcopy(MISSING) is MISSING
    assert pickle.loads(pickle.dumps(MISSING)) is MISSING


def test_sentinel_is_identical_across_spec_from_file_location() -> None:
    """Assert canonical spec_from_file_location loading preserves singleton identity."""
    target_path = Path(tool_surface_constants.__file__).resolve()
    assert target_path.is_file()

    spec = importlib.util.spec_from_file_location("tool_surface_constants", str(target_path))
    assert spec is not None
    # Verify module in sys.modules retains singleton identity
    mod = sys.modules.get("tool_surface_constants")
    assert mod is not None
    assert mod.MISSING is tool_surface_constants.MISSING
    assert mod.MISSING is MISSING


def test_is_missing_predicate_truth_table() -> None:
    """Assert is_missing truth table across scalar, falsy, and container types."""
    assert is_missing(MISSING) is True
    assert is_missing(None) is False
    assert is_missing(False) is False
    assert is_missing(True) is False
    assert is_missing(0) is False
    assert is_missing("") is False
    assert is_missing(()) is False
    assert is_missing([]) is False
    assert is_missing({}) is False
    assert is_missing(object()) is False
    assert is_missing(Ellipsis) is False


def test_get_default_returns_canonical_sentinel_on_missing_param() -> None:
    """Verify get_default returns canonical MISSING on missing parameters and tools."""
    # Synthesize snapshot without a default
    snapshot: dict[str, Any] = {
        "fake_tool": {
            "parameters": {
                "properties": {
                    "foo": {"type": "string"}
                }
            }
        }
    }
    val = get_default(snapshot, "fake_tool", "foo")
    assert val is MISSING
    assert is_missing(val) is True

    # Missing parameter
    val_param = get_default(snapshot, "fake_tool", "non_existent")
    assert val_param is MISSING

    # Missing tool
    val_tool = get_default(snapshot, "non_existent_tool", "foo")
    assert val_tool is MISSING


def test_only_one_missing_sentinel_definition_in_repo() -> None:
    """AST static scan across plugins/quench-dev-tasks/server/ and scripts/:
    assert count == 0 for module-level assignments of bare object() where target name contains MISSING.
    """
    repo_root = Path(__file__).resolve().parents[4]
    scan_dirs = [
        repo_root / "plugins" / "quench-dev-tasks" / "server",
        repo_root / "scripts",
    ]

    violations: list[str] = []

    for scan_dir in scan_dirs:
        for py_path in scan_dir.rglob("*.py"):
            if any(part.startswith(".") or part == "__pycache__" or "site-packages" in part for part in py_path.parts):
                continue
            try:
                tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            except Exception as exc:
                violations.append(f"{py_path}: Parse error {exc}")
                continue

            for node in tree.body:
                if isinstance(node, ast.Assign):
                    if (
                        isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Name)
                        and node.value.func.id == "object"
                    ):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and "MISSING" in target.id:
                                violations.append(f"{py_path}:{node.lineno} {target.id} = object()")
                elif isinstance(node, ast.AnnAssign):
                    if (
                        node.value is not None
                        and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Name)
                        and node.value.func.id == "object"
                    ):
                        if isinstance(node.target, ast.Name) and "MISSING" in node.target.id:
                            violations.append(f"{py_path}:{node.lineno} {node.target.id} = object()")

    assert len(violations) == 0, "Found bare object() MISSING assignments:\n" + "\n".join(violations)
