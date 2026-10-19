"""export_ide_schemas.py - Thin CLI Wrapper for IDE Tool Schema Export.

Launches _introspect_schemas_child.py in a clean isolated subprocess to fetch
live schemas, and delegates CLI argument handling and operations to ide_schema_export.run_cli.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# B-01: Prohibit bytecode generation to ensure --check is strictly read-only
sys.dont_write_bytecode = True

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_DIR = _REPO_ROOT / "plugins" / "quench-dev-tasks" / "server"
_server_dir_str = str(_SERVER_DIR)
if _server_dir_str not in sys.path:
    sys.path.insert(0, _server_dir_str)

from ide_schema_export import parse_envelope, run_cli


def _child_flags() -> list[str]:
    flags = ["-B"]
    if sys.version_info >= (3, 11):
        flags.append("-P")
    return flags


def introspect_live_schemas() -> dict[str, Any]:
    child_script = _REPO_ROOT / "scripts" / "_introspect_schemas_child.py"
    clean_env = dict(os.environ)
    clean_env.pop("PYTHONPATH", None)
    clean_env["PYTHONUTF8"] = "1"
    clean_env["PYTHONIOENCODING"] = "utf-8"
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [sys.executable] + _child_flags() + [str(child_script)]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(_REPO_ROOT),
        env=clean_env,
        text=True,
        encoding="utf-8",
    )
    try:
        stdout, stderr = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise RuntimeError(f"Introspect child process timed out after 30s. stderr: {stderr}")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Introspect child process exited with code {proc.returncode}. stderr: {stderr}"
        )

    return parse_envelope(stdout)


def main() -> int:
    return run_cli(sys.argv[1:], introspect=introspect_live_schemas)


if __name__ == "__main__":
    sys.exit(main())
