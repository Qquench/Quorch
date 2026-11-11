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
import warnings
from server import _get_recent_hook_logs, _read_hook_log_tail, dev_tasks_status
from tool_surface_constants import (
    HOOK_LOG_TAIL_BYTES,
    RESPONSE_BUDGET_BYTES,
    STATUS_COMPACT_MAX_TASKS,
)
from response_compactor import canonical_json


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

    # 1. Default (compact) mode
    status = dev_tasks_status(ws_str)
    assert "last_hook_log_entries_compact" in status
    assert len(status["last_hook_log_entries_compact"]) == 2
    assert "[OTHER]" in status["last_hook_log_entries_compact"][0]
    assert "[ASK_MODAL_BLOCKED]" in status["last_hook_log_entries_compact"][1]
    assert "log_ref" in status["last_hook_log_entries_compact"][0]

    # 2. Verbosity = full mode
    status_full = dev_tasks_status(ws_str, verbosity="full")
    assert "hook_log" in status_full
    assert len(status_full["hook_log"]) == 2
    assert "[ALLOW]" in status_full["hook_log"][0]
    assert "[ASK_MODAL]" in status_full["hook_log"][1]


def test_compact_status_discriminator_always_present(tmp_path_factory):
    """E1: In compact mode, harness_next_action['action'] is strictly guaranteed to exist."""
    tmp_path = tmp_path_factory.mktemp("e1_ws")
    ws_str = str(tmp_path)
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "quench_stack.yaml").write_text(
        "schema_version: '1.0'\nproject_name: 'E1Proj'\ndev_tasks_dir: 'docs/dev_tasks'\n",
        encoding="utf-8",
    )
    status = dev_tasks_status(ws_str)
    assert "harness_next_action" in status
    assert "action" in status["harness_next_action"]
    assert status["harness_next_action"]["action"]


def test_compact_status_40_tasks_bounded(tmp_path_factory):
    """E2: In a 40-task workspace, compact status is strictly bounded <= budget and marks truncation."""
    tmp_path = tmp_path_factory.mktemp("e2_ws")
    ws_str = str(tmp_path)
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "quench_stack.yaml").write_text(
        "schema_version: '1.0'\nproject_name: 'E2Proj'\ndev_tasks_dir: 'docs/dev_tasks'\n",
        encoding="utf-8",
    )
    tasks_dir = tmp_path / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    task_lines = ["# 2026-11-11 40-Task Stress File\n\n"]
    for i in range(1, 41):
        task_lines.append(
            f"### 任务 {i}.1 ⬜ 待确认 — Stress Task Number {i} With Long Specifications\n\n"
            f"#### 【涉及文件】\n```\nplugins/module_{i}/service.py\n```\n\n"
            f"#### 【缺陷根因与修改目标】\nRoot cause {i} target goal {i}.\n\n"
            f"#### 【目标签名与类型契约】\ndef fn_{i}(): pass\n\n"
            f"#### 【分步改造指引】\n1. Step {i}.\n\n"
            f"#### 【防御与边缘校验】\n- Edge {i}.\n\n"
            f"#### 【DoD 验证命令】\n```bash\npytest test_{i}.py\n```\n\n---\n\n"
        )
    (tasks_dir / "2026-11-11_stress_40_tasks.md").write_text("".join(task_lines), encoding="utf-8")

    status = dev_tasks_status(ws_str)
    raw_json = canonical_json(status)
    actual_bytes = len(raw_json.encode("utf-8"))

    assert actual_bytes <= RESPONSE_BUDGET_BYTES["dev_tasks_status"]
    assert "truncated_sections" in status
    assert "tasks" in status["truncated_sections"]
    assert status.get("tasks_total") == 40
    assert len(status.get("tasks", [])) <= STATUS_COMPACT_MAX_TASKS

    if actual_bytes > 1024:
        warnings.warn(
            f"Compact dev_tasks_status payload {actual_bytes}B > soft target 1024B "
            f"(strictly within hard ceiling {RESPONSE_BUDGET_BYTES['dev_tasks_status']}B)",
            UserWarning,
        )


def test_full_superset_invariant(tmp_path_factory):
    """E3 / D-03: Full superset invariant contract locking full vs compact symmetry."""
    tmp_path = tmp_path_factory.mktemp("e3_ws")
    ws_str = str(tmp_path)
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "quench_stack.yaml").write_text(
        "schema_version: '1.0'\nproject_name: 'E3Proj'\ndev_tasks_dir: 'docs/dev_tasks'\n",
        encoding="utf-8",
    )
    tasks_dir = tmp_path / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    task_lines = ["# 2026-11-11 10-Task File\n\n"]
    for i in range(1, 11):
        task_lines.append(
            f"### 任务 {i}.1 ⬜ 待确认 — Task {i}\n\n"
            f"#### 【涉及文件】\n```\nfile_{i}.py\n```\n\n"
            f"#### 【DoD 验证命令】\n```bash\npytest\n```\n\n---\n\n"
        )
    (tasks_dir / "2026-11-11_tasks.md").write_text("".join(task_lines), encoding="utf-8")

    log_file = agents_dir / ".quench_hook.log"
    log_file.write_text(
        "2026-09-13 12:00:01 [INFO] [ALLOW] decision=allow tool=write_to_file target=a.py\n",
        encoding="utf-8",
    )

    full = dev_tasks_status(ws_str, verbosity="full")
    compact = dev_tasks_status(ws_str, verbosity="compact")

    COMPACT_ONLY_KEYS = frozenset({
        "truncated_sections",
        "tasks_total",
        "entitlements_hash",
        "last_hook_log_entries_compact",
    })

    # 1. full extra keys strictly subset of {"session_role_contract", "governance_scope", "hook_log"}
    diff_full_compact = set(full.keys()) - set(compact.keys())
    assert diff_full_compact <= {"session_role_contract", "governance_scope", "hook_log"}, (
        f"Unexpected full-only keys: {diff_full_compact}"
    )

    # 2. compact extra keys strictly equal to COMPACT_ONLY_KEYS
    diff_compact_full = set(compact.keys()) - set(full.keys())
    assert diff_compact_full == COMPACT_ONLY_KEYS, (
        f"Compact-only mismatch: {diff_compact_full} vs {COMPACT_ONLY_KEYS}"
    )

    # 3. tasks prefix equality
    assert full["tasks"][: len(compact["tasks"])] == compact["tasks"]

    # 4. tasks_total equality
    assert len(full["tasks"]) == compact["tasks_total"]


def test_hook_log_tail_bounded_and_fail_open(tmp_path):
    """E4: Bounded tail read and fail-open resilience under oversized and corrupted files."""
    log_file = tmp_path / "oversized.log"

    target_size = HOOK_LOG_TAIL_BYTES * 10
    single_line = "2026-09-13 10:00:00 [INFO] [ALLOW] decision=allow tool=run_command target=log_stress_test\n"
    line_bytes = len(single_line.encode("utf-8"))
    repeat_count = target_size // line_bytes + 1

    with open(log_file, "wb") as f:
        f.write((single_line * repeat_count).encode("utf-8"))
        f.write(b"broken: \xe4\xb8\n2026-09-13 10:00:99 [INFO] [ALLOW] valid tail line\n")

    lines = _read_hook_log_tail(log_file, max_bytes=HOOK_LOG_TAIL_BYTES)
    assert len(lines) > 0
    total_read_bytes = sum(len(l.encode("utf-8")) for l in lines)
    assert total_read_bytes <= HOOK_LOG_TAIL_BYTES + 2048
    assert lines[-1] == "2026-09-13 10:00:99 [INFO] [ALLOW] valid tail line"

    # Non-existent file returns []
    assert _read_hook_log_tail(tmp_path / "non_existent.log") == []

    # Directory path returns [] (fail-open)
    assert _read_hook_log_tail(tmp_path) == []

    # Corrupt binary file returns list without raising
    corrupt_log = tmp_path / ".quench_hook.log"
    corrupt_log.write_bytes(b"\xff\xfe\x00\x00\x80\x81\x82\x83")
    res = _read_hook_log_tail(corrupt_log)
    assert isinstance(res, list)
