# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple
import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]


def find_fstring_backslash_violations(source_code: str, filename: str = "<string>") -> List[Tuple[int, str]]:
    """Scan source code AST for f-string expressions containing backslashes (forbidden in Python <= 3.11)."""
    tree = ast.parse(source_code, filename=filename)
    violations: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FormattedValue):
            val = node.value
            expr_src = ast.get_source_segment(source_code, val)
            if expr_src is not None and "\\" in expr_src:
                violations.append((getattr(val, "lineno", 0), expr_src))
    return violations


def _get_server_py_files() -> List[Path]:
    return sorted(SERVER_DIR.rglob("*.py"))


@pytest.mark.parametrize(
    "py_path",
    _get_server_py_files(),
    ids=lambda p: str(p.relative_to(SERVER_DIR)).replace("\\", "/"),
)
def test_all_server_modules_fstring_backslash_compat(py_path: Path) -> None:
    """Verify all server python modules do not contain backslashes inside f-string expressions (PEP 701 backslash guard)."""
    content = py_path.read_text(encoding="utf-8")
    violations = find_fstring_backslash_violations(content, filename=str(py_path))
    assert not violations, (
        f"Found f-string expression containing backslash in {py_path.name}, "
        f"which raises SyntaxError under Python 3.11: {violations}"
    )


def test_guard_detects_fstring_backslash_regression() -> None:
    """Negative self-test: verify that the guard reliably flags f-string expressions containing backslashes."""
    bs = chr(92)
    bad_snippet = f's = "test"\nx = f"hello {{s.replace({chr(39)}{bs}{bs}{chr(39)}, {chr(39)}/{chr(39)})}}"\n'
    violations = find_fstring_backslash_violations(bad_snippet, filename="<bad_sample>")
    assert len(violations) == 1
    assert violations[0][0] == 2
    assert "\\" in violations[0][1]
