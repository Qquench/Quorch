"""_introspect_schemas_child.py - Sandboxed Child Process Schema Introspector.

Executes in an isolated subprocess, redirects stdout (fd 1) to stderr (fd 2) BEFORE importing
server to prevent any stdio pollution (INV-4), constructs the schema document from server.mcp,
and writes the enveloped canonical schemas directly to a private duplicated fd.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


def _bootstrap_sys_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    server_dir = repo_root / "plugins" / "quench-dev-tasks" / "server"
    server_dir_str = str(server_dir)
    if server_dir_str not in sys.path:
        sys.path.insert(0, server_dir_str)
    return repo_root


def main() -> None:
    # 1. Duplicate fd 1 to hold a private output file descriptor
    try:
        private_fd = os.dup(1)
    except OSError as e:
        sys.stderr.write(f"Failed to duplicate stdout fd: {e}\n")
        os._exit(1)

    # 2. Redirect fd 1 to fd 2, and sys.stdout to sys.stderr to capture any import banners
    try:
        os.dup2(2, 1)
        sys.stdout = sys.stderr
    except OSError as e:
        sys.stderr.write(f"Failed to redirect fd 1 to fd 2: {e}\n")
        os._exit(1)

    try:
        _bootstrap_sys_path()

        from ide_schema_export import ENVELOPE_BEGIN, ENVELOPE_END, canonicalize_schemas
        from tool_surface_constants import (
            EXPECTED_TOOL_NAMES,
            SCHEMA_META_KEY,
            SNAPSHOT_SCHEMA_VERSION,
        )
        import server

        tools = asyncio.run(server.mcp.list_tools())
        doc: dict[str, Any] = {
            SCHEMA_META_KEY: {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
            }
        }
        for tool in tools:
            if tool.name in EXPECTED_TOOL_NAMES:
                doc[tool.name] = {
                    "description": tool.description or "",
                    "parameters": tool.parameters,
                }

        canonical_text = canonicalize_schemas(doc)
        envelope_output = f"{ENVELOPE_BEGIN}\n{canonical_text}{ENVELOPE_END}\n"

        # 3. Write directly to private fd
        with os.fdopen(private_fd, "wb", closefd=True) as out_f:
            out_f.write(envelope_output.encode("utf-8"))
            out_f.flush()
    except Exception as e:
        sys.stderr.write(f"Child introspection error: {e}\n")
        import traceback
        traceback.print_exc(file=sys.stderr)
        os._exit(1)

    os._exit(0)


if __name__ == "__main__":
    main()
