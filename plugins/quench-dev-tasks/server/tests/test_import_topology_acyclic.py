# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Static AST assertions for acyclic import topology and zero reaper references.

Enforces:
1. C-2: FORBIDDEN_REVERSE_IMPORTERS (state_machine, manifest, project_config) do NOT import manifest_lease or reaper.
2. M-2: Zero references to the decommissioned reaper module across production code.
3. C-1: All reclaim CAS and lease probe test files contain the keyword 'reclaim_cas' for hard-gate inclusion.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Set

import pytest

FORBIDDEN_REVERSE_IMPORTERS = frozenset({"state_machine", "manifest", "project_config"})


def _extract_imported_modules(py_file: Path) -> Set[str]:
    """Parse a Python file and extract all imported module names and base symbols."""
    content = py_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(py_file))
    imported: Set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # Handle relative and absolute imports
                clean_module = node.module.lstrip(".")
                if clean_module:
                    imported.add(clean_module.split(".")[0])
            for alias in node.names:
                imported.add(alias.name)

    return imported


def test_no_reverse_import_into_manifest_lease() -> None:
    """AST 断言：FORBIDDEN_REVERSE_IMPORTERS (state_machine, manifest, project_config)

    各模块 import 节点集合 ∩ {manifest_lease, reaper} 为空 (C-2)。
    """
    server_dir = Path(__file__).resolve().parent.parent
    forbidden_targets = {"manifest_lease", "reaper"}

    for mod_name in FORBIDDEN_REVERSE_IMPORTERS:
        target_file = server_dir / f"{mod_name}.py"
        assert target_file.is_file(), f"Target module file {target_file} must exist"

        imported = _extract_imported_modules(target_file)
        intersection = imported & forbidden_targets
        assert not intersection, (
            f"Reverse import violation in {mod_name}.py: imports {intersection}. "
            f"Import topology must remain strictly DAG acyclic."
        )


def test_reaper_module_references_are_zero() -> None:
    """AST 断言：全仓生产模块（server/**、scripts/**）无 import reaper / from ... import reaper。"""
    repo_root = Path(__file__).resolve().parents[4]  # tests -> server -> quench-dev-tasks -> plugins -> repo_root

    production_dirs = [
        repo_root / "plugins" / "quench-dev-tasks" / "server",
        repo_root / "scripts",
        repo_root / "plugins" / "quench-dev-tasks" / "scripts",
    ]

    reaper_references: list[str] = []

    for pdir in production_dirs:
        if not pdir.is_dir():
            continue
        for py_path in pdir.rglob("*.py"):
            # Exclude tests directories and fixtures
            if "tests" in py_path.parts or "test" in py_path.name:
                continue

            try:
                tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            except Exception as e:
                pytest.fail(f"Failed to parse AST for {py_path}: {e}")

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "reaper" or alias.name.startswith("reaper."):
                            reaper_references.append(f"{py_path.relative_to(repo_root)}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    clean_mod = mod.lstrip(".")
                    if clean_mod == "reaper" or clean_mod.startswith("reaper."):
                        reaper_references.append(f"{py_path.relative_to(repo_root)}: from {mod} import ...")
                    for alias in node.names:
                        if alias.name == "reaper":
                            reaper_references.append(f"{py_path.relative_to(repo_root)}: from {mod} import reaper")

    assert not reaper_references, (
        f"Found {len(reaper_references)} residual references to decommissioned reaper module in production code:\n"
        + "\n".join(reaper_references)
    )


def test_reclaim_cas_gate_coverage_consistency() -> None:
    """契约断言：test_reclaim_cas 与 test_reclaim_cas_lease_probe 均包含 reclaim_cas 关键字，恒被硬门禁捕获 (C-1)。"""
    tests_dir = Path(__file__).resolve().parent

    test_reclaim_cas = tests_dir / "test_reclaim_cas.py"
    test_probe = tests_dir / "test_reclaim_cas_lease_probe.py"
    old_test_reaper = tests_dir / "test_reaper.py"

    assert test_reclaim_cas.is_file(), "test_reclaim_cas.py must exist"
    assert test_probe.is_file(), "test_reclaim_cas_lease_probe.py must exist"
    assert not old_test_reaper.exists(), "Old test_reaper.py must be removed"

    assert "reclaim_cas" in test_reclaim_cas.name, "test_reclaim_cas.py must contain keyword 'reclaim_cas'"
    assert "reclaim_cas" in test_probe.name, "test_reclaim_cas_lease_probe.py must contain keyword 'reclaim_cas'"


def _is_dual_branch_import_shim(node: ast.Try) -> bool:
    """Detect dual-branch import shim shape: Try(Import/ImportFrom) -> except(ImportError/ValueError) -> fallback Import."""
    if not (node.body and all(isinstance(x, (ast.ImportFrom, ast.Import)) for x in node.body)):
        return False

    caught_exceptions: set[str] = set()
    has_fallback_import = False
    for handler in node.handlers:
        if handler.type is not None:
            if isinstance(handler.type, ast.Name):
                caught_exceptions.add(handler.type.id)
            elif isinstance(handler.type, ast.Tuple):
                for elt in handler.type.elts:
                    if isinstance(elt, ast.Name):
                        caught_exceptions.add(elt.id)
        if handler.body and any(isinstance(x, (ast.ImportFrom, ast.Import)) for x in handler.body):
            has_fallback_import = True

    if ("ImportError" in caught_exceptions or "ValueError" in caught_exceptions) and has_fallback_import:
        return True
    return False


def test_zero_import_shims_in_production_code() -> None:
    """[D7] AST 断言：全仓生产代码中双分支导入垫片（Try->ImportFrom + except ImportError/ValueError）残留数量为 0。"""
    repo_root = Path(__file__).resolve().parents[4]
    target_dirs = [
        repo_root / "plugins" / "quench-dev-tasks" / "server",
        repo_root / "plugins" / "quench-dev-tasks" / "scripts",
        repo_root / "scripts",
    ]

    residual_shims: list[str] = []
    for tdir in target_dirs:
        if not tdir.is_dir():
            continue
        for py_path in tdir.rglob("*.py"):
            if "tests" in py_path.parts or any(p.startswith(".") or p == "venv" for p in py_path.parts):
                continue
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Try) and _is_dual_branch_import_shim(node):
                    residual_shims.append(f"{py_path.relative_to(repo_root)}:{node.lineno}")

    assert len(residual_shims) == 0, f"Found residual dual-branch import shims in production code: {residual_shims}"


def test_import_shim_detector_adversarial_injection() -> None:
    """[D7 对抗注入单测] 验证 _is_dual_branch_import_shim 准确命中垫片形状，且不误伤非垫片代码。"""
    shim_code = """
try:
    from .manifest_lease import reclaim_stale_task
except (ImportError, ValueError):
    from manifest_lease import reclaim_stale_task
"""
    shim_tree = ast.parse(shim_code)
    shim_tries = [n for n in ast.walk(shim_tree) if isinstance(n, ast.Try)]
    assert len(shim_tries) == 1
    assert _is_dual_branch_import_shim(shim_tries[0]) is True

    # 对抗样本 1：普通业务异常处理
    normal_code = """
try:
    val = int("123")
except ValueError:
    val = 0
"""
    normal_tree = ast.parse(normal_code)
    normal_tries = [n for n in ast.walk(normal_tree) if isinstance(n, ast.Try)]
    assert _is_dual_branch_import_shim(normal_tries[0]) is False

    # 对抗样本 2：单纯的单分支可选依赖探测（无 fallback import 结构）
    probe_code = """
try:
    import uvloop
except ImportError:
    pass
"""
    probe_tree = ast.parse(probe_code)
    probe_tries = [n for n in ast.walk(probe_tree) if isinstance(n, ast.Try)]
    assert _is_dual_branch_import_shim(probe_tries[0]) is False

