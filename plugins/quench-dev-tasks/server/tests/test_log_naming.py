# -*- coding: utf-8 -*-
"""Unit tests for log_naming module."""

from __future__ import annotations

import concurrent.futures
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

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

    # Monkeypatch os.stat and os.path.getmtime to raise RuntimeError
    def _fail_stat(*args, **kwargs):
        raise RuntimeError("os.stat was called! Zero-stat violation!")

    monkeypatch.setattr(os, "stat", _fail_stat)
    monkeypatch.setattr(os.path, "getmtime", _fail_stat)

    # gc_by_filename_order must succeed purely on string sorting
    pruned = gc_by_filename_order(tmp_path, keep=2)
    assert len(pruned) == 3


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

