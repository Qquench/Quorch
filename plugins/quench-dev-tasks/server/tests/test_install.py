# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
import pytest

# 动态引入 scripts/install.py
SCRIPTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
)
sys.path.insert(0, SCRIPTS_DIR)

import install  # type: ignore


@pytest.fixture
def mock_plugin_env(tmp_path):
    """创建隔离的模拟插件环境，包含模板文件"""
    plugin_dir = tmp_path / "plugins" / "quench-dev-tasks"
    plugin_dir.mkdir(parents=True)
    server_dir = plugin_dir / "server"
    hooks_dir = server_dir / "hooks"
    hooks_dir.mkdir(parents=True)

    # 伪造脚本文件
    (server_dir / "server.py").write_text("# server stub", encoding="utf-8")
    (hooks_dir / "file_scope_guard.py").write_text("# guard stub", encoding="utf-8")
    (hooks_dir / "context_injector.py").write_text("# injector stub", encoding="utf-8")

    # 复制真实模板内容
    real_plugin_dir = install.get_plugin_dir()
    with open(os.path.join(real_plugin_dir, "mcp_config.json.template"), "r", encoding="utf-8") as f:
        (plugin_dir / "mcp_config.json.template").write_text(f.read(), encoding="utf-8")

    with open(os.path.join(real_plugin_dir, "hooks.json.template"), "r", encoding="utf-8") as f:
        (plugin_dir / "hooks.json.template").write_text(f.read(), encoding="utf-8")

    return plugin_dir


def test_render_configs_success(mock_plugin_env):
    """测试模板动态渲染成功且正确处理 Windows 反斜杠"""
    python_exe = r"C:\Users\tester\AppData\Local\Programs\Python\Python312\python.exe"
    mcp_path, hooks_path = install.render_configs(str(mock_plugin_env), python_exe)

    assert os.path.isfile(mcp_path)
    assert os.path.isfile(hooks_path)

    with open(mcp_path, "r", encoding="utf-8") as f:
        mcp_data = json.load(f)

    assert mcp_data["mcpServers"]["quench-dev-tasks"]["command"] == python_exe

    with open(hooks_path, "r", encoding="utf-8") as f:
        hooks_data = json.load(f)

    guard_cmd = hooks_data["quench-file-guard"]["PreToolUse"][0]["hooks"][0]["command"]
    assert f'"{python_exe}"' in guard_cmd


def test_render_configs_missing_template(tmp_path):
    """测试缺失模板时抛出明确的 FileNotFoundError"""
    empty_plugin = tmp_path / "empty_plugin"
    empty_plugin.mkdir()
    with pytest.raises(FileNotFoundError):
        install.render_configs(str(empty_plugin), sys.executable)


def test_run_preflight_and_backup_creation(mock_plugin_env, tmp_path):
    """测试 Pre-flight 检查通过并生成合规快照备份"""
    # 先写入初始配置
    mcp_file = mock_plugin_env / "mcp_config.json"
    hooks_file = mock_plugin_env / "hooks.json"
    mcp_file.write_text('{"initial": "mcp"}', encoding="utf-8")
    hooks_file.write_text('{"initial": "hooks"}', encoding="utf-8")

    backup_path = str(tmp_path / ".agents" / ".quench_path_backup.json")
    passed, msgs = install.run_preflight(str(mock_plugin_env), backup_path)

    assert passed is True
    assert any("快照备份完成" in m for m in msgs)
    assert os.path.isfile(backup_path)

    with open(backup_path, "r", encoding="utf-8") as f:
        snapshot = json.load(f)

    assert snapshot["snapshot_version"] == "1.0"
    assert "plugins/quench-dev-tasks/mcp_config.json" in snapshot["files"]
    assert snapshot["files"]["plugins/quench-dev-tasks/mcp_config.json"] == '{"initial": "mcp"}'


def test_rollback_success(mock_plugin_env, tmp_path):
    """测试从快照文件成功回滚恢复配置"""
    mcp_file = mock_plugin_env / "mcp_config.json"
    hooks_file = mock_plugin_env / "hooks.json"
    mcp_file.write_text('{"original": "mcp_data"}', encoding="utf-8")
    hooks_file.write_text('{"original": "hooks_data"}', encoding="utf-8")

    backup_path = str(tmp_path / ".agents" / ".quench_path_backup.json")
    # 生成备份
    passed, _ = install.run_preflight(str(mock_plugin_env), backup_path)
    assert passed is True

    # 篡改配置
    mcp_file.write_text('{"corrupted": true}', encoding="utf-8")
    if hooks_file.exists():
        hooks_file.unlink()

    # 执行回滚
    success = install.rollback_configuration(str(mock_plugin_env), backup_path)
    assert success is True

    # 验证原样恢复
    assert mcp_file.read_text(encoding="utf-8") == '{"original": "mcp_data"}'
    assert hooks_file.read_text(encoding="utf-8") == '{"original": "hooks_data"}'


def test_rollback_missing_and_corrupted_backup(mock_plugin_env, tmp_path):
    """测试快照缺失或损坏时的容错处理"""
    non_existent = str(tmp_path / "non_existent.json")
    assert install.rollback_configuration(str(mock_plugin_env), non_existent) is False

    corrupted = tmp_path / "corrupted.json"
    corrupted.write_text("{ broken json content", encoding="utf-8")
    assert install.rollback_configuration(str(mock_plugin_env), str(corrupted)) is False


def test_max_path_audit_limits(tmp_path):
    """测试 Windows MAX_PATH 审计规则（>200 警告，>250 阻断）"""
    safe_backup = str(tmp_path / "backup.json")
    with patch("sys.platform", "win32"):
        # 正常长度
        passed, msgs = install.run_preflight("C:\\short_path\\plugin", safe_backup)
        assert any("安全审计通过" in m for m in msgs)

        # > 200 字符警告
        long_210 = "C:\\" + "a" * 210
        passed, msgs = install.run_preflight(long_210, safe_backup)
        assert any("MAX_PATH 警告" in m for m in msgs)
        assert passed is True

        # > 250 字符阻断
        long_255 = "C:\\" + "a" * 255
        passed, msgs = install.run_preflight(long_255, safe_backup)
        assert any("MAX_PATH 阻断" in m for m in msgs)
        assert passed is False


def test_cli_preflight_flag():
    """测试命令行 --preflight 标志调用"""
    repo_root = install.get_repo_root()
    install_script = os.path.join(repo_root, "scripts", "install.py")
    res = subprocess.run(
        [sys.executable, install_script, "--preflight"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=repo_root,
        timeout=15,
    )
    assert res.returncode == 0
    assert "Pre-flight" in res.stdout
