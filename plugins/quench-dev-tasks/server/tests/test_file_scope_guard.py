import json
import os
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
import pytest

# Ensure hook and server modules can be imported
server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
hooks_dir = os.path.join(server_dir, "hooks")
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)
if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)

from file_scope_guard import (
    verify_session_integrity,
    safe_clean_corrupted_bypass,
    is_session_bypass_matched,
    SESSION_ID_PATTERN,
)


def test_verify_session_integrity_valid_utc():
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=2)
    bypass_data = {
        "active": True,
        "session_id": "test-uuid-1234",
        "expires_at": future.isoformat(),
    }
    is_valid, reason = verify_session_integrity(bypass_data, "test-uuid-1234")
    assert is_valid is True
    assert reason == ""


def test_verify_session_integrity_mixed_timezone_naive():
    # Naive ISO string (without +00:00) should be treated as UTC and not raise TypeError
    future = datetime.now() + timedelta(hours=2)
    naive_iso = future.strftime("%Y-%m-%dT%H:%M:%S")
    bypass_data = {
        "active": True,
        "session_id": "sess-abc",
        "expires_at": naive_iso,
    }
    is_valid, reason = verify_session_integrity(bypass_data, "sess-abc")
    assert is_valid is True
    assert reason == ""


def test_verify_session_integrity_expired():
    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    bypass_data = {
        "active": True,
        "session_id": "sess-abc",
        "expires_at": past.isoformat(),
    }
    is_valid, reason = verify_session_integrity(bypass_data, "sess-abc")
    assert is_valid is False
    assert "超时过期" in reason


def test_verify_session_integrity_mismatched_session():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    bypass_data = {
        "active": True,
        "session_id": "session-1",
        "expires_at": future.isoformat(),
    }
    is_valid, reason = verify_session_integrity(bypass_data, "session-2")
    assert is_valid is False
    assert "跨会话冲突" in reason


def test_safe_clean_corrupted_bypass(tmp_path):
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    bypass_file = agents_dir / ".quench_bypass.json"
    bypass_file.write_text("{corrupted json", encoding="utf-8")

    assert bypass_file.exists()
    safe_clean_corrupted_bypass(str(bypass_file))
    assert not bypass_file.exists()


def test_is_session_bypass_matched_corrupted_json_self_healing(tmp_path):
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    bypass_file = agents_dir / ".quench_bypass.json"
    # Write half-broken JSON
    bypass_file.write_text('{"active": true, "category": "ui', encoding="utf-8")

    ws_str = str(tmp_path)
    # Should not crash, should return False and auto-clean the broken file
    matched = is_session_bypass_matched(ws_str, "src/index.css")
    assert matched is False
    assert not bypass_file.exists()


def test_is_session_bypass_matched_valid_session(tmp_path):
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    bypass_file = agents_dir / ".quench_bypass.json"
    exp = datetime.now(timezone.utc) + timedelta(hours=2)
    bypass_file.write_text(
        json.dumps({
            "active": True,
            "session_id": "sess-uuid-001",
            "category": "ui_styling",
            "patterns": ["*.css", "src/ui/**"],
            "reason": "测试 bypass",
            "expires_at": exp.isoformat(),
        }),
        encoding="utf-8",
    )

    ws_str = str(tmp_path)
    # Same session ID matches
    assert is_session_bypass_matched(ws_str, "src/ui/Button.vue", "sess-uuid-001") is True
    # Different pattern does not match
    assert is_session_bypass_matched(ws_str, "src/core/main.py", "sess-uuid-001") is False
    # Cross session clean up
    assert is_session_bypass_matched(ws_str, "src/ui/Button.vue", "other-sess") is False
    assert not bypass_file.exists()


def test_concurrent_bypass_file_race(tmp_path):
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    bypass_file = agents_dir / ".quench_bypass.json"
    exp = datetime.now(timezone.utc) + timedelta(hours=2)
    valid_payload = json.dumps({
        "active": True,
        "session_id": "concurrent-sess",
        "category": "all",
        "patterns": ["*"],
        "reason": "并发竞争测试",
        "expires_at": exp.isoformat(),
    })
    bypass_file.write_text(valid_payload, encoding="utf-8")

    ws_str = str(tmp_path)
    errors = []

    def worker(worker_id: int):
        try:
            for _ in range(20):
                # Concurrently read/check bypass
                matched = is_session_bypass_matched(ws_str, f"file_{worker_id}.py", "concurrent-sess")
                time.sleep(0.005)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent workers encountered errors: {errors}"
