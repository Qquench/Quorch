"""test_export_ide_schemas_cli.py - Heavy CLI Integration Tests for export_ide_schemas.

Marked @pytest.mark.slow, excluded from Tier-1 fast tests.
Validates CLI execution, sub-process isolation, exit codes, and cross-platform byte determinism.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "export_ide_schemas.py"
_SNAPSHOT_PATH = _REPO_ROOT / "docs" / "architecture" / "ide_tool_schemas.json"

CR = bytes([13])
LF = bytes([10])


@pytest.mark.slow
def test_cli_write_and_check_clean() -> None:
    # 1. Run --write
    res_write = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--write"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert res_write.returncode == 0, f"Write failed: {res_write.stderr}"

    # 2. Verify snapshot file existence and byte properties
    assert _SNAPSHOT_PATH.is_file()
    data_bytes = _SNAPSHOT_PATH.read_bytes()
    assert CR not in data_bytes, "CR byte found in snapshot file"
    assert data_bytes.endswith(LF), "Snapshot file must end with LF"
    assert not data_bytes.endswith(LF * 2), "Snapshot file must not end with multiple LFs"
    assert data_bytes.count(LF) > 1

    # 3. Mode check (platform-aware)
    st = _SNAPSHOT_PATH.stat()
    mode = stat.S_IMODE(st.st_mode)
    if sys.platform != "win32":
        assert mode == 0o644, f"Expected 0o644, got {oct(mode)}"
    else:
        assert (mode & 0o600) == 0o600, f"Expected user rw permissions, got {oct(mode)}"

    # 4. No temporary files left behind
    tmp_files = list(_SNAPSHOT_PATH.parent.glob(".ide_tool_schemas.json.*.tmp"))
    assert not tmp_files, f"Temporary files leaked: {tmp_files}"

    # 5. Run --check
    res_check = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--check"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert res_check.returncode == 0, f"Check failed: {res_check.stderr}"


@pytest.mark.slow
def test_cli_check_drift_detection(tmp_path: Path) -> None:
    # Set up mock cache-dir within repo root to satisfy path containment
    test_cache_dir = _REPO_ROOT / "docs" / "architecture" / ".test_drift_cache"
    test_cache_dir.mkdir(parents=True, exist_ok=True)
    target = test_cache_dir / "ide_tool_schemas.json"

    try:
        # First write authentic schemas
        res_write = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--write", "--cache-dir", str(test_cache_dir)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert res_write.returncode == 0

        # Tamper with the snapshot file to induce drift (valid schema doc, but drifted content)
        content = target.read_text(encoding="utf-8")
        data = json.loads(content)
        data["dev_tasks_status"]["description"] = "Drifted Description for Test"
        target.write_bytes(json.dumps(data, indent=2).encode("utf-8") + b"\n")

        # Verify --check detects drift (exit code 1)
        res_check = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--check", "--cache-dir", str(test_cache_dir)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert res_check.returncode == 1, f"Expected exit code 1 (drift), got {res_check.returncode}"
    finally:
        if target.exists():
            target.unlink()
        if test_cache_dir.exists():
            test_cache_dir.rmdir()


@pytest.mark.slow
def test_cli_corrupted_json_returns_exit_2() -> None:
    test_cache_dir = _REPO_ROOT / "docs" / "architecture" / ".test_corrupted_cache"
    test_cache_dir.mkdir(parents=True, exist_ok=True)
    target = test_cache_dir / "ide_tool_schemas.json"

    try:
        target.write_text("{ not valid json at all", encoding="utf-8")
        res_check = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--check", "--cache-dir", str(test_cache_dir)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert res_check.returncode == 2, f"Expected exit code 2, got {res_check.returncode}"
    finally:
        if target.exists():
            target.unlink()
        if test_cache_dir.exists():
            test_cache_dir.rmdir()


@pytest.mark.slow
def test_cli_absent_directory_returns_exit_2() -> None:
    non_existent = _REPO_ROOT / "docs" / "architecture" / ".absent_dir_check"
    assert not non_existent.exists()

    res_check = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--check", "--cache-dir", str(non_existent)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert res_check.returncode == 2, f"Expected exit code 2, got {res_check.returncode}"
    # Must remain non-existent (strictly read-only)
    assert not non_existent.exists()


@pytest.mark.slow
def test_cli_cache_dir_reparse_point_rejected(tmp_path: Path) -> None:
    link_dir = _REPO_ROOT / "docs" / "architecture" / ".test_reparse_cache"
    target_dir = tmp_path / "actual_target"
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(str(target_dir), str(link_dir))
        else:
            link_dir.symlink_to(target_dir, target_is_directory=True)
    except (OSError, PermissionError, NotImplementedError, AttributeError):
        pytest.skip("Creating symlink / junction not supported in this test environment")

    try:
        res = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--check", "--cache-dir", str(link_dir)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert res.returncode == 2, f"Expected exit code 2 on reparse point, got {res.returncode}. stderr: {res.stderr}"
        assert not (target_dir / "ide_tool_schemas.json").exists()
    finally:
        if link_dir.exists():
            if sys.platform == "win32":
                try:
                    os.rmdir(link_dir)
                except Exception:
                    pass
            else:
                try:
                    link_dir.unlink()
                except Exception:
                    pass


@pytest.mark.slow
def test_cli_cache_dir_permission_denied_maps_to_exit_2(tmp_path: Path) -> None:
    ro_dir = _REPO_ROOT / "docs" / "architecture" / ".test_readonly_dir"
    ro_dir.mkdir(parents=True, exist_ok=True)
    target_file = ro_dir / "ide_tool_schemas.json"

    try:
        target_file.write_text("{}", encoding="utf-8")
        if sys.platform == "win32":
            os.chmod(target_file, stat.S_IREAD)
            os.chmod(ro_dir, stat.S_IREAD)
        else:
            os.chmod(ro_dir, 0o555)

        res_write = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--write", "--cache-dir", str(ro_dir)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert res_write.returncode == 2, f"Expected exit code 2, got {res_write.returncode}. stderr: {res_write.stderr}"
        stderr = res_write.stderr or ""
        assert "Traceback (most recent call last)" not in stderr
        assert "Error" in stderr or "Permission" in stderr or "拒绝访问" in stderr

    finally:
        try:
            if sys.platform == "win32":
                os.chmod(target_file, stat.S_IWRITE | stat.S_IREAD)
                os.chmod(ro_dir, stat.S_IWRITE | stat.S_IREAD)
            else:
                os.chmod(ro_dir, 0o755)
            if target_file.exists():
                target_file.unlink()
            if ro_dir.exists():
                ro_dir.rmdir()
        except Exception:
            pass


@pytest.mark.slow
def test_cli_isolated_pythonpath_does_not_pollute_probe() -> None:
    polluted_env = dict(os.environ)
    polluted_env["PYTHONPATH"] = "invalid_nonexistent_path_that_should_not_crash_isolated_probe"

    res = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--check"],
        cwd=str(_REPO_ROOT),
        env=polluted_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert res.returncode == 0, f"Check failed under polluted PYTHONPATH: {res.stderr}"


@pytest.mark.slow
def test_cli_repeated_write_is_strictly_idempotent(tmp_path: Path) -> None:
    test_cache_dir = _REPO_ROOT / "docs" / "architecture" / ".test_idempotent_cache"
    test_cache_dir.mkdir(parents=True, exist_ok=True)
    target_file = test_cache_dir / "ide_tool_schemas.json"

    try:
        res1 = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--write", "--cache-dir", str(test_cache_dir)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert res1.returncode == 0, f"First write failed: {res1.stderr}"
        assert target_file.is_file()
        st1 = target_file.stat()
        bytes1 = target_file.read_bytes()

        res2 = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), "--write", "--cache-dir", str(test_cache_dir)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert res2.returncode == 0, f"Second write failed: {res2.stderr}"
        bytes2 = target_file.read_bytes()

        assert bytes1 == bytes2
        st2 = target_file.stat()
        assert st2.st_size == st1.st_size
    finally:
        if target_file.exists():
            target_file.unlink()
        if test_cache_dir.exists():
            test_cache_dir.rmdir()

