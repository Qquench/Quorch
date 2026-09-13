# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import logging
import os
import subprocess
import sys
from unittest.mock import patch
import pytest

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
hooks_dir = os.path.join(server_dir, "hooks")
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)
if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)

from file_scope_guard import (
    SafeRotatingFileHandler,
    get_hook_logger,
    log_guard_event,
    _LOGGER_CACHE,
)
from server import _get_recent_hook_logs, dev_tasks_status


def test_safe_rotating_file_handler_basic(tmp_path):
    log_file = tmp_path / "test.log"
    handler = SafeRotatingFileHandler(str(log_file), maxBytes=100, backupCount=2, encoding="utf-8")
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)

    logger = logging.getLogger("test_safe_rot")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    # Write messages to trigger rollover
    for i in range(10):
        logger.info(f"Line {i:03d} padding to exceed hundred bytes limit")

    handler.close()
    logger.removeHandler(handler)

    assert os.path.isfile(str(log_file))
    # Rollover backup file should exist
    backup_1 = tmp_path / "test.log.1"
    assert backup_1.exists()


def test_safe_rotating_file_handler_permission_error_resilience(tmp_path):
    log_file = tmp_path / "test_perm.log"
    handler = SafeRotatingFileHandler(str(log_file), maxBytes=50, backupCount=2, encoding="utf-8")
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)

    # Mock super().doRollover to simulate Windows file lock PermissionError
    with patch("logging.handlers.RotatingFileHandler.doRollover", side_effect=PermissionError("File locked")):
        # Trigger rollover by calling doRollover directly or emitting
        handler.doRollover()
        # Ensure stream is restored and we can still write
        record = logging.LogRecord("test", logging.INFO, "", 0, "resilient message", (), None)
        handler.emit(record)

    handler.close()
    with open(str(log_file), "r", encoding="utf-8") as f:
        content = f.read()
    assert "resilient message" in content


def test_get_hook_logger_and_events(tmp_path):
    ws_str = str(tmp_path)
    _LOGGER_CACHE.clear()

    logger = get_hook_logger(ws_str)
    assert logger is not None
    assert len(logger.handlers) >= 1

    # Log various events
    log_guard_event(
        logger=logger,
        event_type="ALLOW",
        target_file="src/main.py",
        tool_name="replace_file_content",
        decision="allow",
        reason="whitelist hit",
        session_id="sess-001",
    )
    log_guard_event(
        logger=logger,
        event_type="ASK_MODAL",
        target_file="src/secret.py",
        tool_name="write_to_file",
        decision="ask",
        reason="out of scope",
        session_id="sess-001",
    )
    log_guard_event(
        logger=logger,
        event_type="DENIED",
        target_file="src/blocked.py",
        tool_name="replace_file_content",
        decision="deny",
        reason="critical violation",
        session_id="sess-001",
    )
    log_guard_event(
        logger=logger,
        event_type="BYPASS_CLEAN",
        target_file=str(tmp_path / ".agents" / ".quench_bypass.json"),
        tool_name="",
        decision="clean",
        reason="expired lease",
        session_id="sess-001",
    )
    log_guard_event(
        logger=logger,
        event_type="EXCEPTION",
        target_file="unknown",
        tool_name="",
        decision="allow",
        reason="fallback triggered",
        session_id="sess-001",
    )

    # Flush all handlers
    for h in logger.handlers:
        h.flush()

    log_path = tmp_path / ".agents" / ".quench_hook.log"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "[ALLOW]" in content
    assert "target=src/main.py" in content
    assert "[ASK_MODAL]" in content
    assert "[DENIED]" in content
    assert "[BYPASS_CLEAN]" in content
    assert "[EXCEPTION]" in content


def test_get_hook_logger_unwritable_fallback(tmp_path):
    _LOGGER_CACHE.clear()
    # Mock SafeRotatingFileHandler raising PermissionError on init
    with patch("file_scope_guard.SafeRotatingFileHandler", side_effect=PermissionError("Access denied")):
        logger = get_hook_logger(str(tmp_path))
        assert logger is not None
        assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)
        # Should not raise when logging
        log_guard_event(logger, "ALLOW", "test.py", "write_to_file", "allow")


def test_get_recent_hook_logs_validation(tmp_path):
    ws_str = str(tmp_path)
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    log_file = agents_dir / ".quench_hook.log"

    # 1. Non-existent log file returns []
    assert _get_recent_hook_logs(ws_str, max_lines=5) == []

    # 2. Fully formed log lines
    lines = [f"2026-09-13 10:00:{i:02d} [INFO] line {i}" for i in range(15)]
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recent = _get_recent_hook_logs(ws_str, max_lines=5)
    assert len(recent) == 5
    assert recent[-1] == lines[-1]
    assert recent[0] == lines[-5]

    # 3. Truncated last line (no trailing newline) should be omitted
    truncated_content = "\n".join(lines[:3]) + "\n2026-09-13 10:00:99 [INFO] in-flight-tru"
    log_file.write_text(truncated_content, encoding="utf-8")
    recent_trunc = _get_recent_hook_logs(ws_str, max_lines=10)
    assert len(recent_trunc) == 3
    assert "in-flight-tru" not in recent_trunc[-1]
    assert recent_trunc[-1] == lines[2]


def test_dev_tasks_status_integration(tmp_path):
    ws_str = str(tmp_path)
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text(
        "schema_version: '1.0'\nproject_name: 'ObsTestProj'\ndev_tasks_dir: 'docs/dev_tasks'\n",
        encoding="utf-8",
    )

    log_file = agents_dir / ".quench_hook.log"
    log_file.write_text(
        "2026-09-13 12:00:01 [INFO] [ALLOW] decision=allow tool=write_to_file target=a.py\n"
        "2026-09-13 12:00:02 [WARNING] [ASK_MODAL] decision=ask tool=write_to_file target=b.py\n",
        encoding="utf-8",
    )

    status = dev_tasks_status(ws_str)
    assert "last_hook_log_entries" in status
    assert len(status["last_hook_log_entries"]) == 2
    assert "[ALLOW]" in status["last_hook_log_entries"][0]
    assert "[ASK_MODAL]" in status["last_hook_log_entries"][1]
