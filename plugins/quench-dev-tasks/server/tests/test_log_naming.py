# -*- coding: utf-8 -*-
"""Unit tests for log_naming module."""

from __future__ import annotations

import concurrent.futures
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from log_naming import (
    MAX_DAILY_SEQUENCE,
    SLUG_MAX_LEN,
    HEADER_VERSION,
    SequenceExhaustedError,
    InvalidSlugError,
    LogFileName,
    normalize_utc_date,
    sanitize_slug,
    allocate_log_file,
    list_log_files,
    gc_by_filename_order,
    enforce_unified_log_quota,
    _LOG_FILENAME_REGEX,
)


def test_render_format():
    name = LogFileName("20260924", 1, "topology_inversion").render()
    assert re.match(r"^\d{8}_\d{3}_[a-z0-9_]+\.log$", name)
    assert name == "20260924_001_topology_inversion.log"


def test_sequential_allocation(tmp_path: Path):
    path1, _ = allocate_log_file(tmp_path, "session_a")
    path2, _ = allocate_log_file(tmp_path, "session_b")
    path3, _ = allocate_log_file(tmp_path, "session_c")

    assert os.path.basename(path1).startswith(f"{normalize_utc_date()}_001_")
    assert os.path.basename(path2).startswith(f"{normalize_utc_date()}_002_")
    assert os.path.basename(path3).startswith(f"{normalize_utc_date()}_003_")


def test_header_contract(tmp_path: Path):
    path, header_bytes = allocate_log_file(
        tmp_path,
        "critique_audit",
        header_metadata={"mode": "critique", "consult_id": "ab12cd"},
    )
    with open(path, "r", encoding="utf-8") as f:
        first_line = f.readline()

    assert first_line.startswith(f"# {HEADER_VERSION}")
    assert "date=" in first_line
    assert "seq=001" in first_line
    assert "slug=critique_audit" in first_line
    assert "utc=" in first_line
    assert "mode=critique" in first_line
    assert "consult_id=ab12cd" in first_line
    assert first_line.encode("utf-8") == header_bytes


def test_sequence_exhaustion_raises_and_never_wraps(tmp_path: Path):
    date_str = normalize_utc_date()
    # Pre-seed slots 001 to 999
    for i in range(1, MAX_DAILY_SEQUENCE + 1):
        p = tmp_path / f"{date_str}_{i:03d}_stub.log"
        p.write_text("stub", encoding="utf-8")

    with pytest.raises(SequenceExhaustedError):
        allocate_log_file(tmp_path, "overflow_test")

    # Assert no _000_ or _1000_ exists
    assert not (tmp_path / f"{date_str}_000_stub.log").exists()
    assert not (tmp_path / f"{date_str}_1000_stub.log").exists()


def test_slug_lowercasing_and_sanitization():
    raw = "My-Feature.Test#01!"
    clean = sanitize_slug(raw)
    assert clean == "my_feature_test_01"


def test_slug_truncation_no_trailing_underscore():
    raw = "a_very_long_feature_name_that_exceeds_twenty_characters"
    clean = sanitize_slug(raw)
    assert len(clean) <= SLUG_MAX_LEN
    assert not clean.endswith("_")
    assert clean == "a_very_long_feature"


def test_slug_empty_fallback():
    assert sanitize_slug("") == "consult"
    assert sanitize_slug(None) == "consult"
    assert sanitize_slug("   ") == "consult"
    assert sanitize_slug("!@#$%^") == "consult"


def test_slug_reserved_words():
    for word in ("CON", "prn", "AUX", "NUL", "com1", "lpt1"):
        cleaned = sanitize_slug(word)
        assert cleaned.startswith("_")
        assert word.lower() in cleaned


def test_slug_path_separator_raises():
    with pytest.raises(InvalidSlugError):
        sanitize_slug("dir/file")
    with pytest.raises(InvalidSlugError):
        sanitize_slug("dir\\file")
    with pytest.raises(InvalidSlugError):
        sanitize_slug("..")
    with pytest.raises(InvalidSlugError):
        sanitize_slug(".")


def test_naive_datetime_normalized_to_utc():
    naive = datetime(2026, 9, 24, 12, 0, 0)
    assert normalize_utc_date(naive) == "20260924"


def test_aware_datetime_converted_to_utc():
    # Tokyo is UTC+9. 2026-09-24 02:00:00 JST is 2026-09-23 17:00:00 UTC
    jst = timezone(timedelta(hours=9))
    aware_jst = datetime(2026, 9, 24, 2, 0, 0, tzinfo=jst)
    assert normalize_utc_date(aware_jst) == "20260923"


def test_multithreaded_concurrent_allocation_unique(tmp_path: Path):
    count = 20

    def _alloc(idx: int) -> str:
        path, _ = allocate_log_file(tmp_path, f"thread_{idx}")
        return os.path.basename(path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(_alloc, range(count)))

    assert len(results) == count
    assert len(set(results)) == count
    # All files exist and match sequence pattern
    for r in results:
        assert (tmp_path / r).exists()


def test_header_utc_is_iso8601(tmp_path: Path):
    path, _ = allocate_log_file(tmp_path, "iso_test")
    with open(path, "r", encoding="utf-8") as f:
        line = f.readline()
    match = re.search(r"utc=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)", line)
    assert match is not None


def test_list_log_files_ascending_order(tmp_path: Path):
    f3 = tmp_path / "20260924_003_c.log"
    f1 = tmp_path / "20260924_001_a.log"
    f2 = tmp_path / "20260924_002_b.log"
    for f in (f3, f1, f2):
        f.write_text("x", encoding="utf-8")

    listed = list_log_files(tmp_path)
    assert listed == [
        "20260924_001_a.log",
        "20260924_002_b.log",
        "20260924_003_c.log",
    ]


def test_gc_deletes_oldest_by_name(tmp_path: Path):
    for i in range(1, 10):
        p = tmp_path / f"20260924_{i:03d}_test.log"
        p.write_text("content", encoding="utf-8")

    pruned = gc_by_filename_order(tmp_path, keep=3)
    assert len(pruned) == 6
    remaining = list_log_files(tmp_path)
    assert remaining == [
        "20260924_007_test.log",
        "20260924_008_test.log",
        "20260924_009_test.log",
    ]


def test_gc_cascades_rotation_file(tmp_path: Path):
    base = tmp_path / "20260924_001_test.log"
    base.write_text("base", encoding="utf-8")
    rot = tmp_path / "20260924_001_test.1.log"
    rot.write_text("rot", encoding="utf-8")

    for i in range(2, 6):
        (tmp_path / f"20260924_{i:03d}_test.log").write_text("x", encoding="utf-8")

    pruned = gc_by_filename_order(tmp_path, keep=4)
    assert "20260924_001_test.log" in pruned
    assert not base.exists()
    assert not rot.exists()


def test_gc_zero_stat_guarantee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for i in range(1, 6):
        (tmp_path / f"20260924_{i:03d}_test.log").write_text("x", encoding="utf-8")

    real_stat = os.stat
    real_lstat = getattr(os, "lstat", real_stat)
    real_getmtime = os.path.getmtime

    def _guarded_stat(path, *args, **kwargs):
        base = os.path.basename(os.fspath(path))
        if _LOG_FILENAME_REGEX.match(base) or base.endswith(".1.log"):
            raise RuntimeError(f"os.stat was called on {base}! Zero-stat violation!")
        return real_stat(path, *args, **kwargs)

    def _guarded_lstat(path, *args, **kwargs):
        base = os.path.basename(os.fspath(path))
        if _LOG_FILENAME_REGEX.match(base) or base.endswith(".1.log"):
            raise RuntimeError(f"os.lstat was called on {base}! Zero-stat violation!")
        return real_lstat(path, *args, **kwargs)

    def _guarded_getmtime(path, *args, **kwargs):
        base = os.path.basename(os.fspath(path))
        if _LOG_FILENAME_REGEX.match(base) or base.endswith(".1.log"):
            raise RuntimeError(f"os.path.getmtime was called on {base}! Zero-stat violation!")
        return real_getmtime(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", _guarded_stat)
    monkeypatch.setattr(os, "lstat", _guarded_lstat)
    monkeypatch.setattr(os.path, "getmtime", _guarded_getmtime)

    # gc_by_filename_order must succeed purely on string sorting
    pruned = gc_by_filename_order(tmp_path, keep=2)
    assert len(pruned) == 3


def test_gc_zero_stat_guarantee_subprocess(tmp_path: Path):
    """子进程强隔离验证：在子进程中将 os.stat/os.lstat 全局抛出异常，断言 GC 仍然完全成功。"""
    import subprocess
    import textwrap

    script = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {server_dir!r})
        import log_naming
        target_dir = sys.argv[1]
        for i in range(1, 6):
            open(os.path.join(target_dir, f"20260924_{{i:03d}}_test.log"), "w", encoding="utf-8").close()
        
        def _boom(*a, **k):
            raise RuntimeError("os.stat was invoked!")
        os.stat = _boom
        if hasattr(os, "lstat"):
            os.lstat = _boom
        
        pruned = log_naming.gc_by_filename_order(target_dir, keep=2)
        assert len(pruned) == 3, f"Expected 3 pruned, got {{len(pruned)}}"
        print("OK")
    """)
    res = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert res.returncode == 0, f"Subprocess failed with stderr: {res.stderr}"
    assert "OK" in res.stdout


def test_gc_tolerates_vanished_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """并发容错：模拟待清理文件在调用 os.remove 时已被外部删除（FileNotFoundError），GC 不得崩溃。"""
    for i in range(1, 6):
        (tmp_path / f"20260924_{i:03d}_test.log").write_text("x", encoding="utf-8")

    real_remove = os.remove

    def _flaky_remove(path):
        if "001" in str(path):
            raise FileNotFoundError("Simulated external deletion")
        return real_remove(path)

    monkeypatch.setattr(os, "remove", _flaky_remove)
    pruned = gc_by_filename_order(tmp_path, keep=2)
    assert len(pruned) == 2


def test_gc_tolerates_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Windows 句柄占用容错：模拟文件被进程锁定（PermissionError），GC 优雅跳过，不中断批次。"""
    for i in range(1, 6):
        (tmp_path / f"20260924_{i:03d}_test.log").write_text("x", encoding="utf-8")

    real_remove = os.remove

    def _locked_remove(path):
        if "001" in str(path):
            raise PermissionError("[WinError 32] File in use")
        return real_remove(path)

    monkeypatch.setattr(os, "remove", _locked_remove)
    pruned = gc_by_filename_order(tmp_path, keep=2)
    assert len(pruned) == 2
    assert "20260924_001_test.log" not in pruned


def test_gc_source_has_no_stat_calls():
    """静态 AST 门禁：gc_by_filename_order 与 list_log_files 函数体内严禁包含任何 stat/exists/getmtime/isfile 等调用。"""
    import ast
    import log_naming

    forbidden_attrs = {"exists", "isfile", "isdir", "getmtime", "getsize", "stat", "lstat"}
    with open(log_naming.__file__, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=log_naming.__file__)

    checked_funcs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("gc_by_filename_order", "list_log_files"):
            checked_funcs.add(node.name)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and sub.attr in forbidden_attrs:
                    pytest.fail(f"Forbidden stat-family attribute .{sub.attr} invoked inside {node.name}")

    assert checked_funcs == {"gc_by_filename_order", "list_log_files"}, f"Expected to check both functions, got {checked_funcs}"



def test_no_persistent_state_counter_created(tmp_path: Path):
    allocate_log_file(tmp_path, "state_test_1")
    allocate_log_file(tmp_path, "state_test_2")

    all_files = os.listdir(tmp_path)
    for f in all_files:
        assert not f.endswith(".state")
        assert not f.startswith(".seq")
        assert not f.endswith(".json")


def test_gc_invalid_keep_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        gc_by_filename_order(tmp_path, keep=0)
    with pytest.raises(ValueError):
        gc_by_filename_order(tmp_path, keep=-5)


def test_allocator_retries_on_eexist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Simulate race condition where slot 001 exists right when opening
    date_str = normalize_utc_date()
    slot1 = tmp_path / f"{date_str}_001_retry_test.log"
    slot1.write_text("already here", encoding="utf-8")

    path, _ = allocate_log_file(tmp_path, "retry_test")
    assert os.path.basename(path).startswith(f"{date_str}_002_")
    assert slot1.read_text(encoding="utf-8") == "already here"


def test_enforce_unified_log_quota_purges_legacy_first(tmp_path: Path):
    """验证统一限额清理优先淘汰最老的旧格式 latest-*.log，且连带清理 .1.log。"""
    # Create 5 legacy logs with staggered mtimes
    base_time = 1700000000.0
    for i in range(1, 6):
        legacy = tmp_path / f"latest-session_{i}.log"
        legacy.write_text(f"legacy {i}", encoding="utf-8")
        os.utime(legacy, (base_time + i * 10, base_time + i * 10))
        # Add a rotation backup for session_1
        if i == 1:
            rot = tmp_path / f"latest-session_{i}.1.log"
            rot.write_text("rot 1", encoding="utf-8")

    # Create 3 new-format logs
    for i in range(1, 4):
        new_log = tmp_path / f"20260924_{i:03d}_task.log"
        new_log.write_text(f"new {i}", encoding="utf-8")

    # Pointer latest.log (must never be deleted)
    pointer = tmp_path / "latest.log"
    pointer.write_text("pointer", encoding="utf-8")

    # Total counted logs = 5 legacy + 3 new = 8 logs.
    # Set keep=5 -> excess = 3. Oldest 3 legacy logs (1, 2, 3) must be purged.
    pruned = enforce_unified_log_quota(tmp_path, keep=5)

    assert len(pruned) == 3
    assert "latest-session_1.log" in pruned
    assert "latest-session_2.log" in pruned
    assert "latest-session_3.log" in pruned

    # Verify files on disk
    assert not (tmp_path / "latest-session_1.log").exists()
    assert not (tmp_path / "latest-session_1.1.log").exists()  # rotation file cascade deleted
    assert not (tmp_path / "latest-session_2.log").exists()
    assert not (tmp_path / "latest-session_3.log").exists()

    assert (tmp_path / "latest-session_4.log").exists()
    assert (tmp_path / "latest-session_5.log").exists()
    assert (tmp_path / "20260924_001_task.log").exists()
    assert (tmp_path / "20260924_002_task.log").exists()
    assert (tmp_path / "20260924_003_task.log").exists()
    assert pointer.exists()  # latest.log preserved


def test_enforce_unified_log_quota_purges_new_format_when_legacy_exhausted(tmp_path: Path):
    """当旧格式日志清理殆尽后，超额部分按字典序零 stat 淘汰新格式日志。"""
    # 2 legacy logs
    for i in range(1, 3):
        legacy = tmp_path / f"latest-old_{i}.log"
        legacy.write_text("old", encoding="utf-8")

    # 4 new format logs
    for i in range(1, 5):
        (tmp_path / f"20260924_{i:03d}_task.log").write_text("new", encoding="utf-8")

    # Total = 2 + 4 = 6. keep = 3 -> excess = 3.
    # Must purge 2 legacy logs, then 1 oldest new log (001).
    pruned = enforce_unified_log_quota(tmp_path, keep=3)

    assert len(pruned) == 3
    assert "latest-old_1.log" in pruned
    assert "latest-old_2.log" in pruned
    assert "20260924_001_task.log" in pruned

    assert (tmp_path / "20260924_002_task.log").exists()
    assert (tmp_path / "20260924_003_task.log").exists()
    assert (tmp_path / "20260924_004_task.log").exists()


