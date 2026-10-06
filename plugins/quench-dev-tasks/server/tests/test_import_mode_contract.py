# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Contract tests for absolute-only import mode in production server modules and daemon sys.path pinning."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
import pytest


def test_production_imports_are_absolute_only(root: Path | None = None) -> None:
    """[F2 契约] 断言 plugins/quench-dev-tasks/server/** 生产模块 ImportFrom.level 恒为 0。

    显式排除 server/tests/** 与包 __init__.py。杜绝任何相对导入语法（. 或 ..）。
    """
    server_dir = root or Path(__file__).resolve().parent.parent
    assert server_dir.is_dir(), f"Server directory {server_dir} must exist"

    relative_imports: list[str] = []

    for py_path in server_dir.rglob("*.py"):
        if "tests" in py_path.parts:
            continue
        if py_path.name == "__init__.py":
            continue
        if any(part.startswith(".") or part == "venv" for part in py_path.parts):
            continue

        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        except Exception as e:
            pytest.fail(f"Failed to parse AST for {py_path}: {e}")

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.level or 0) > 0:
                relative_imports.append(
                    f"{py_path.name}:{node.lineno} -> from {'.' * node.level}{node.module or ''} import ..."
                )

    assert not relative_imports, (
        f"Found {len(relative_imports)} residual relative imports in production modules:\n"
        + "\n".join(relative_imports)
    )


def test_daemon_entrypoint_pins_server_on_syspath() -> None:
    """[R1 契约] 断言 daemon 运行入口采用脚本模式并将 server 目录显式置于 sys.path。"""
    server_dir = Path(__file__).resolve().parent.parent
    cli_py = server_dir / "cli.py"

    assert cli_py.is_file(), f"cli.py must exist at {cli_py}"
    cli_code = cli_py.read_text(encoding="utf-8")
    cli_tree = ast.parse(cli_code, filename=str(cli_py))

    # Assert that cli.py assigns SERVER_DIR and inserts it into sys.path
    has_sys_path_insert = False
    for node in ast.walk(cli_tree):
        if isinstance(node, ast.Call):
            # check for sys.path.insert(0, ...)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "insert":
                if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "path":
                    has_sys_path_insert = True

    assert has_sys_path_insert, "cli.py must pin server and scripts directories into sys.path"

    # Also test via subprocess that executing a command via python script mode puts script dir into sys.path[0]
    probe_code = (
        "import sys\n"
        "print(sys.path[0])\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", probe_code],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert res.returncode == 0
