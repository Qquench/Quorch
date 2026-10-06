# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Smoke tests for clean imports of production server modules under standard script-mode sys.path."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_clean_import_server_and_reporting():
    """Verify clean import of server and reporting modules in an isolated subshell."""
    server_dir = Path(__file__).resolve().parent.parent
    code = (
        "import sys\n"
        f"sys.path.insert(0, r'{server_dir}')\n"
        "import reporting\n"
        "import server\n"
        "assert hasattr(reporting, 'render_handoff_card')\n"
        "assert hasattr(reporting, 'append_changelog_entry')\n"
        "assert hasattr(server, 'mcp')\n"
        "print('CLEAN_IMPORT_OK')\n"
    )

    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert res.returncode == 0, f"Import smoke failed with stderr:\n{res.stderr}\nstdout:\n{res.stdout}"
    assert "CLEAN_IMPORT_OK" in res.stdout


def test_clean_import_all_core_modules():
    """Verify clean import of all core server modules without dual-branch shims or cyclic dependencies."""
    server_dir = Path(__file__).resolve().parent.parent
    modules = ["manifest", "manifest_lease", "state_machine", "path_guard", "project_config", "reporting"]

    for mod in modules:
        code = (
            "import sys\n"
            f"sys.path.insert(0, r'{server_dir}')\n"
            f"import {mod}\n"
            f"print('{mod}_OK')\n"
        )
        res = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert res.returncode == 0, f"Module {mod} import failed:\n{res.stderr}"
        assert f"{mod}_OK" in res.stdout
