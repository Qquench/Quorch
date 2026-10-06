# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Canary tests for FastMCP daemon script-mode launch, stdio initialization, process tree kill, and filelock isolation."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
import filelock
import pytest


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """Platform-forked hard process tree killer (Windows taskkill /T /F / POSIX killpg/kill)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


def test_server_daemon_launch_canary_and_lock_isolation() -> None:
    """Canary test: daemon script-mode launch, stdio handshake, process tree teardown, and lock freedom."""
    server_dir = Path(__file__).resolve().parent.parent
    server_py = server_dir / "server.py"
    repo_root = server_dir.parents[2]

    proc = subprocess.Popen(
        [sys.executable, str(server_py)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(repo_root),
        text=True,
        encoding="utf-8",
    )

    try:
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "canary-tester", "version": "1.0"},
            },
        }

        assert proc.stdin is not None
        proc.stdin.write(json.dumps(init_req) + "\n")
        proc.stdin.flush()

        assert proc.stdout is not None
        resp_line = proc.stdout.readline()
        assert resp_line, "Expected non-empty JSON-RPC response from daemon"

        resp_data = json.loads(resp_line)
        assert resp_data.get("jsonrpc") == "2.0"
        assert resp_data.get("id") == 1
        result = resp_data.get("result", {})
        server_info = result.get("serverInfo", {})
        assert server_info.get("name") == "quench-dev-tasks"
    finally:
        _terminate_process_tree(proc)

    # Lock freedom assertion: verify manifest filelock can be acquired immediately without contention
    manifest_lock_path = repo_root / ".agents" / ".quorch" / "manifest.lock"
    if manifest_lock_path.parent.is_dir():
        lock = filelock.FileLock(str(manifest_lock_path), timeout=0.5)
        with lock:
            pass  # Acquired cleanly, proving lock is in free state


def test_grandchild_pipe_fd_isolation_timeout_recovery() -> None:
    """Verify that timeout kill properly reclaims and returns even when child processes hold pipe handles."""
    # Spawn a dummy process tree where child spawns a grandchild holding open stdio handles
    helper_code = (
        "import sys, time, subprocess\n"
        "sub = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)\n"
        "sys.stdout.write('READY\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )

    proc = subprocess.Popen(
        [sys.executable, "-c", helper_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        assert line.strip() == "READY"
    finally:
        _terminate_process_tree(proc)

    # After _terminate_process_tree, proc must be terminated and not hung
    assert proc.poll() is not None
