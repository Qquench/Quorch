# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import pathlib
import re
import tomllib
from typing import Final, List, Tuple
import yaml

MINIMUM_PYTHON: Final[Tuple[int, int]] = (3, 12)
SERVER_DIR = pathlib.Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SERVER_DIR.parents[2]


def parse_requires_python(pyproject_path: pathlib.Path) -> Tuple[int, int]:
    """Parse requires-python from pyproject.toml and return (major, minor) floor."""
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    req = data.get("project", {}).get("requires-python", "")
    match = re.search(r">=(\d+)\.(\d+)", req)
    assert match is not None, f"Could not parse valid >=X.Y floor from requires-python: '{req}'"
    return int(match.group(1)), int(match.group(2))


def parse_ci_matrix_python_versions(ci_yml_path: pathlib.Path) -> List[Tuple[int, int]]:
    """Parse matrix.python-version list from .github/workflows/ci.yml."""
    data = yaml.safe_load(ci_yml_path.read_text(encoding="utf-8"))
    test_job = data.get("jobs", {}).get("test", {})
    matrix = test_job.get("strategy", {}).get("matrix", {})
    versions = matrix.get("python-version", [])
    parsed: List[Tuple[int, int]] = []
    for v in versions:
        parts = str(v).split(".")
        parsed.append((int(parts[0]), int(parts[1])))
    return parsed


def test_pyproject_floor_is_at_least_312() -> None:
    """Verify that server pyproject.toml specifies requires-python floor >= 3.12."""
    pyproject_file = SERVER_DIR / "pyproject.toml"
    assert pyproject_file.exists(), f"pyproject.toml not found at {pyproject_file}"
    floor = parse_requires_python(pyproject_file)
    assert floor >= MINIMUM_PYTHON, f"Expected requires-python floor >= {MINIMUM_PYTHON}, got {floor}"


def test_ci_matrix_has_no_axis_below_floor() -> None:
    """Verify that .github/workflows/ci.yml does not run any Python version below 3.12."""
    ci_file = WORKSPACE_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists(), f"CI file not found at {ci_file}"
    versions = parse_ci_matrix_python_versions(ci_file)
    assert versions, "No python-version matrix entries found in CI config"
    for v in versions:
        assert v >= MINIMUM_PYTHON, f"Found CI matrix python-version {v} below minimum floor {MINIMUM_PYTHON}"


def test_legacy_fstring_backslash_guard_is_retired() -> None:
    """Negative discipline: verify that legacy 3.11 AST backslash guard is physically retired."""
    legacy_guard = SERVER_DIR / "tests" / "test_python_version_compat.py"
    assert not legacy_guard.exists(), (
        f"Legacy 3.11 compat guard file {legacy_guard.name} still exists! "
        "It must be permanently retired to prevent ghost constraints."
    )
