# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Zero dangling reference static assertions for deleted modules (changelog_writer, handoff_card)."""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath
import pytest

DELETED_MODULES = frozenset({"changelog_writer", "handoff_card"})
NON_CONSUMER_DOC_PREFIXES = ("docs/dev_tasks",)


def _is_non_consumer_path(p: Path, repo_root: Path) -> bool:
    """复用 step01.1 目录分量隔离语义排除 docs/dev_tasks/ 下的任务单及历史归档文件。"""
    try:
        rel = p.relative_to(repo_root).as_posix()
    except ValueError:
        return False
    pure = PurePosixPath(rel)
    for prefix in NON_CONSUMER_DOC_PREFIXES:
        prefix_parts = PurePosixPath(prefix).parts
        if pure.parts[:len(prefix_parts)] == prefix_parts:
            return True
    return False


def test_no_dangling_refs_including_dynamic(root: Path | None = None) -> None:
    """[F1 契约] 扫描根覆盖 server/、hooks/、scripts/、adapters/、cli.py 以及全仓代码。

    联合扫描 AST Import/ImportFrom 以及 import_module(<str>)/__import__(<str>) 动态调用，
    断言对已删模块（changelog_writer, handoff_card）的引用集恒为空。
    """
    repo_root = root or Path(__file__).resolve().parents[4]

    scan_targets = [
        repo_root / "plugins" / "quench-dev-tasks" / "server",
        repo_root / "plugins" / "quench-dev-tasks" / "server" / "hooks",
        repo_root / "plugins" / "quench-dev-tasks" / "scripts",
        repo_root / "plugins" / "quench-dev-tasks" / "adapters",
        repo_root / "scripts",
    ]

    # Also include top-level cli.py or any python scripts
    cli_py = repo_root / "plugins" / "quench-dev-tasks" / "server" / "cli.py"

    files_to_scan: set[Path] = set()
    if cli_py.is_file():
        files_to_scan.add(cli_py)

    for target in scan_targets:
        if target.is_dir():
            for py_path in target.rglob("*.py"):
                files_to_scan.add(py_path)
        elif target.is_file():
            files_to_scan.add(target)

    # Filter out virtualenvs and docs/dev_tasks
    filtered_files: list[Path] = []
    for f in sorted(files_to_scan):
        if any(part.startswith(".") or part == "venv" for part in f.parts):
            continue
        if _is_non_consumer_path(f, repo_root):
            continue
        filtered_files.append(f)

    dangling_refs: list[str] = []

    for py_file in filtered_files:
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except Exception as e:
            pytest.fail(f"Failed to parse AST for {py_file}: {e}")

        for node in ast.walk(tree):
            # 1. Direct Import
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod_base = alias.name.split(".")[-1]
                    if mod_base in DELETED_MODULES or alias.name in DELETED_MODULES:
                        dangling_refs.append(f"{py_file.relative_to(repo_root)}:{node.lineno} -> import {alias.name}")

            # 2. ImportFrom
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                mod_base = mod_name.split(".")[-1]
                if mod_base in DELETED_MODULES or mod_name in DELETED_MODULES:
                    dangling_refs.append(f"{py_file.relative_to(repo_root)}:{node.lineno} -> from {mod_name} import ...")
                for alias in node.names:
                    if alias.name in DELETED_MODULES:
                        dangling_refs.append(f"{py_file.relative_to(repo_root)}:{node.lineno} -> from {mod_name} import {alias.name}")

            # 3. Dynamic import: importlib.import_module(...) or __import__(...)
            elif isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                if func_name in ("import_module", "__import__") and node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        target_str = first_arg.value.strip()
                        target_base = target_str.split(".")[-1]
                        if target_base in DELETED_MODULES or target_str in DELETED_MODULES:
                            dangling_refs.append(
                                f"{py_file.relative_to(repo_root)}:{node.lineno} -> {func_name}('{target_str}')"
                            )

    assert not dangling_refs, (
        f"Found {len(dangling_refs)} dangling references to deleted modules {DELETED_MODULES}:\n"
        + "\n".join(dangling_refs)
    )
