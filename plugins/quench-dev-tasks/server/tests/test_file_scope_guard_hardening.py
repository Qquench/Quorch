# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys
from unittest.mock import patch
import pytest

# Ensure hook and server modules can be imported
server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
hooks_dir = os.path.join(server_dir, "hooks")
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)
if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)

from file_scope_guard import (
    resolve_realpath_under,
    is_governed_task_file,
    _strip_long_path_prefix,
)

PYTHON_EXE = sys.executable
FILE_GUARD = os.path.join(hooks_dir, "file_scope_guard.py")


def run_hook(hook_script: str, input_dict: dict) -> dict:
    proc = subprocess.Popen(
        [PYTHON_EXE, hook_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    stdout, stderr = proc.communicate(input=json.dumps(input_dict, ensure_ascii=False))
    assert proc.returncode == 0, f"Hook failed with stderr: {stderr}"
    return json.loads(stdout)


def test_strip_long_path_prefix():
    assert _strip_long_path_prefix(r"\\?\D:\workspace\file.txt") == r"D:\workspace\file.txt"
    assert _strip_long_path_prefix(r"\\?\UNC\server\share\file.txt") == r"\\server\share\file.txt"
    assert _strip_long_path_prefix(r"D:\normal\path.txt") == r"D:\normal\path.txt"


def test_resolve_realpath_under_basic(tmp_path):
    ws = str(tmp_path)
    test_file = tmp_path / "hello.txt"
    test_file.write_text("world", encoding="utf-8")

    # Absolute path
    res = resolve_realpath_under(ws, str(test_file))
    assert res is not None
    assert os.path.normcase(res) == os.path.normcase(str(test_file))

    # Relative path
    res_rel = resolve_realpath_under(ws, "hello.txt")
    assert res_rel is not None
    assert os.path.normcase(res_rel) == os.path.normcase(str(test_file))


def test_resolve_realpath_under_non_existent(tmp_path):
    ws = str(tmp_path)
    # File does not exist yet (e.g. creating new task file)
    new_file = tmp_path / "docs" / "dev_tasks" / "2026-09-24_new.md"
    res = resolve_realpath_under(ws, str(new_file))
    assert res is not None
    assert os.path.normcase(res) == os.path.normcase(str(new_file))

    # Deeply nested non-existent path
    deep_file = tmp_path / "a" / "b" / "c" / "d.txt"
    res_deep = resolve_realpath_under(ws, str(deep_file))
    assert res_deep is not None
    assert os.path.normcase(res_deep) == os.path.normcase(str(deep_file))


def test_resolve_realpath_under_dot_dot_escape(tmp_path):
    ws = str(tmp_path)
    # Attempting to jump out of workspace with ..
    escape_target = tmp_path / "docs" / ".." / ".." / "outside.txt"
    res = resolve_realpath_under(ws, str(escape_target))
    assert res is None

    # Direct parent traversal
    res2 = resolve_realpath_under(ws, "../../evil.md")
    assert res2 is None


def test_resolve_realpath_under_windows_cross_drive(tmp_path):
    ws = str(tmp_path)
    # Different drive letter or simulated ValueError in commonpath
    with patch("os.path.commonpath", side_effect=ValueError("Paths don't have the same drive")):
        res = resolve_realpath_under(ws, "file.txt")
        assert res is None


def test_resolve_realpath_under_symlink_escape(tmp_path):
    ws = str(tmp_path)
    link_path = str(tmp_path / "symlink_escape.txt")
    outside_target = os.path.abspath(os.path.join(ws, "..", "outside_target.txt"))

    # Mock realpath returning path outside workspace
    def fake_realpath(path):
        if os.path.normcase(path) == os.path.normcase(link_path):
            return outside_target
        return path

    with patch("os.path.realpath", side_effect=fake_realpath):
        res = resolve_realpath_under(ws, link_path)
        assert res is None


def test_is_governed_task_file_valid(tmp_path):
    ws = str(tmp_path)
    task_file = str(tmp_path / "docs" / "dev_tasks" / "2026-09-23_task.md")
    readme_file = str(tmp_path / "docs" / "dev_tasks" / "README.md")
    src_file = str(tmp_path / "src" / "main.py")

    assert is_governed_task_file(ws, task_file) is True
    assert is_governed_task_file(ws, readme_file) is False
    assert is_governed_task_file(ws, src_file) is False


def test_is_governed_task_file_custom_dir(tmp_path):
    ws = str(tmp_path)
    custom_task = str(tmp_path / "tasks" / "epic1.md")
    default_task = str(tmp_path / "docs" / "dev_tasks" / "epic1.md")

    assert is_governed_task_file(ws, custom_task, dev_tasks_dir="tasks") is True
    assert is_governed_task_file(ws, default_task, dev_tasks_dir="tasks") is False


def test_is_governed_task_file_symlink_into_task_dir(tmp_path):
    ws = str(tmp_path)
    alias_path = str(tmp_path / "src" / "alias_task.md")
    real_task = str(tmp_path / "docs" / "dev_tasks" / "real_task.md")

    def fake_realpath(path):
        if os.path.normcase(path) == os.path.normcase(alias_path):
            return real_task
        return path

    with patch("os.path.realpath", side_effect=fake_realpath):
        # Physical resolution detects that it targets dev_tasks
        assert is_governed_task_file(ws, alias_path) is True


def test_is_governed_task_file_symlink_escape(tmp_path):
    ws = str(tmp_path)
    fake_task = str(tmp_path / "docs" / "dev_tasks" / "fake_task.md")
    real_target_src = str(tmp_path / "src" / "main.py")

    def fake_realpath(path):
        if os.path.normcase(path) == os.path.normcase(fake_task):
            return real_target_src
        return path

    with patch("os.path.realpath", side_effect=fake_realpath):
        # Even though lexically in docs/dev_tasks, physically points to src/main.py
        assert is_governed_task_file(ws, fake_task) is False


def test_hook_denies_realpath_escape_dot_dot(tmp_path):
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text("project_name: 'TestProj'\n", encoding="utf-8")

    ws_str = str(tmp_path)
    escape_target = str(tmp_path / "docs" / "dev_tasks" / ".." / ".." / "outside.md")

    res = run_hook(FILE_GUARD, {
        "toolCall": {
            "name": "write_to_file",
            "args": {"TargetFile": escape_target},
        },
        "workspacePaths": [ws_str],
    })

    assert res["decision"] == "deny"
    assert res.get("reason") == "realpath_escape"


def test_hook_audit_log_records_realpath_escape(tmp_path):
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text("project_name: 'TestProj'\n", encoding="utf-8")

    ws_str = str(tmp_path)
    escape_target = str(tmp_path / "docs" / "dev_tasks" / ".." / ".." / "outside.md")

    run_hook(FILE_GUARD, {
        "toolCall": {
            "name": "write_to_file",
            "args": {"TargetFile": escape_target},
        },
        "workspacePaths": [ws_str],
    })

    log_file = agents_dir / ".quench_hook.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "[DENIED]" in content
    assert "reason=realpath_escape" in content
