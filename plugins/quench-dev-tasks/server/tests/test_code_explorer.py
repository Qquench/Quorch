# -*- coding: utf-8 -*-
"""Security and sandbox tests for code_explorer.py (Task 36.5)."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from code_explorer import (
    UnsafePathError,
    explore_code_slices,
    grep,
    resolve_within_roots,
)


def test_resolve_within_roots_rejects_drive_relative(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert resolve_within_roots(str(ws), "C:foo.py") is None
    with pytest.raises(UnsafePathError):
        grep(str(ws), "hello", rel_path="C:foo.py")


def test_grep_blocks_external_and_sensitive_symlinks_and_stops_lazily(tmp_path: Path):
    ws = tmp_path / "ws"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()
    (ws / "normal.py").write_text("SECRET_MARKER = 1\n", encoding="utf-8")
    (ws / ".env").write_text("SECRET_MARKER = env\n", encoding="utf-8")
    ext_file = outside / "leak.py"
    ext_file.write_text("SECRET_MARKER = outside\n", encoding="utf-8")

    try:
        os.symlink(str(ext_file), str(ws / "escape.py"))
        os.symlink(str(ws / ".env"), str(ws / "alias.txt"))
        res = grep(str(ws), "SECRET_MARKER")
        assert [m.rel_path for m in res.matches] == ["normal.py"]
    except (OSError, NotImplementedError):
        (ws / "escape.py").write_text("SECRET_MARKER = fake\n", encoding="utf-8")
        (ws / "alias.txt").write_text("SECRET_MARKER = fake\n", encoding="utf-8")
        orig_realpath = os.path.realpath

        def _fake_realpath(p):
            s = str(p)
            if s.endswith("escape.py"):
                return str(ext_file)
            if s.endswith("alias.txt"):
                return str(orig_realpath(str(ws / ".env")))
            return orig_realpath(p)

        with patch("os.path.realpath", side_effect=_fake_realpath):
            res = grep(str(ws), "SECRET_MARKER")
        assert [m.rel_path for m in res.matches] == ["normal.py"]

    # Lazy max_files cap
    for i in range(5):
        (ws / f"extra_{i}.py").write_text("SECRET_MARKER = extra\n", encoding="utf-8")
    capped = grep(str(ws), "SECRET_MARKER", max_files=2)
    assert capped.files_scanned == 2
    assert capped.truncated is True


def test_explore_code_slices_logs_warning_on_import_inspection_error(tmp_path: Path, caplog):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "mod.py").write_text("import other\n", encoding="utf-8")

    with patch("code_explorer.extract_ast_interfaces", side_effect=[([], ["other"], True), RuntimeError("boom")]):
        with caplog.at_level(logging.WARNING, logger="code_explorer"):
            res = explore_code_slices(str(ws), ["mod.py"], max_hops=1)
    assert len(res.files) == 1
    assert any("Failed to inspect imports" in rec.message for rec in caplog.records)
