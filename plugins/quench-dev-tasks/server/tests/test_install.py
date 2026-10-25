# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional
from unittest.mock import patch
import pytest

# 动态引入 scripts/install.py 与 server/log_naming.py
SERVER_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

SCRIPTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import install  # type: ignore


def _synthetic_oserror(*, errno_val: int = 0, winerror: Optional[int] = None) -> OSError:
    """构建用于测试的合成 OSError"""
    err = OSError(errno_val, "synthetic os error")
    err.winerror = winerror
    return err


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


def test_classify_probe_error_pure():
    """测试 classify_probe_error 纯函数在各类 winerror 与 errno 下的分级矩阵"""
    # 1. winerror 判定优先（winerror 不为 None）
    assert install.classify_probe_error(_synthetic_oserror(winerror=32)) == "advisory"
    assert install.classify_probe_error(_synthetic_oserror(winerror=33)) == "advisory"
    assert install.classify_probe_error(_synthetic_oserror(winerror=5)) == "blocked"
    assert install.classify_probe_error(_synthetic_oserror(winerror=999)) == "blocked"

    # 2. errno 判定（winerror 为 None）
    assert install.classify_probe_error(_synthetic_oserror(errno_val=errno.ENOENT, winerror=None)) == "blocked"
    assert install.classify_probe_error(_synthetic_oserror(errno_val=errno.EACCES, winerror=None)) == "blocked"
    assert install.classify_probe_error(_synthetic_oserror(errno_val=errno.EPERM, winerror=None)) == "blocked"
    assert install.classify_probe_error(_synthetic_oserror(errno_val=errno.EROFS, winerror=None)) == "blocked"
    assert install.classify_probe_error(_synthetic_oserror(errno_val=errno.ENOSPC, winerror=None)) == "blocked"
    assert install.classify_probe_error(_synthetic_oserror(errno_val=errno.EIO, winerror=None)) == "blocked"
    assert install.classify_probe_error(_synthetic_oserror(errno_val=errno.ENOTDIR, winerror=None)) == "blocked"

    # 兜底未知错误（fail-closed 归入 blocked）
    assert install.classify_probe_error(_synthetic_oserror(errno_val=9999, winerror=None)) == "blocked"
    assert install.classify_probe_error(_synthetic_oserror(errno_val=0, winerror=None)) == "blocked"


def test_preflight_probe_is_non_mutating(tmp_path):
    """测试探测哨兵文件创建后自清理，以被测目录为根恒无任何残留"""
    test_dir = tmp_path / "probe_target"
    test_dir.mkdir()

    verdict, msg = install.probe_directory_writability(str(test_dir))
    assert verdict == "ok"
    assert "目录可写性探测通过" in msg

    # 严格断言测试目录内零哨兵残留
    residue = list(test_dir.rglob(f"{install._PROBE_PREFIX}*"))
    assert not residue, f"残留哨兵文件: {residue}"


def test_probe_directory_writability_advisory_retry(tmp_path):
    """测试探测遭遇 advisory 级错误时按退避策略重试 PREFLIGHT_PROBE_ATTEMPTS 轮"""
    test_dir = tmp_path / "retry_dir"
    test_dir.mkdir()

    calls = 0
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(*args, **kwargs):
        nonlocal calls
        prefix = kwargs.get("prefix", "")
        if str(prefix).startswith(install._PROBE_PREFIX):
            calls += 1
            e = OSError(errno.EACCES, "synthetic sharing violation")
            e.winerror = 32
            raise e
        return real_mkstemp(*args, **kwargs)

    with patch("tempfile.mkstemp", side_effect=fake_mkstemp):
        with patch("time.sleep") as mock_sleep:
            verdict, msg = install.probe_directory_writability(str(test_dir))
            assert verdict == "advisory"
            assert "轻微竞争或锁定" in msg
            assert calls == install.PREFLIGHT_PROBE_ATTEMPTS
            assert mock_sleep.call_count == install.PREFLIGHT_PROBE_ATTEMPTS - 1


def test_probe_directory_writability_blocked_no_retry(tmp_path):
    """测试探测遭遇 blocked 级权限错误时立即返回且不进行重试"""
    test_dir = tmp_path / "blocked_dir"
    test_dir.mkdir()

    calls = 0
    real_mkstemp = tempfile.mkstemp

    def fake_mkstemp(*args, **kwargs):
        nonlocal calls
        prefix = kwargs.get("prefix", "")
        if str(prefix).startswith(install._PROBE_PREFIX):
            calls += 1
            e = OSError(errno.EACCES, "synthetic permission denied")
            e.winerror = 5
            raise e
        return real_mkstemp(*args, **kwargs)

    with patch("tempfile.mkstemp", side_effect=fake_mkstemp):
        with patch("time.sleep") as mock_sleep:
            verdict, msg = install.probe_directory_writability(str(test_dir))
            assert verdict == "blocked"
            assert "无法写入或受阻" in msg
            assert calls == 1
            mock_sleep.assert_not_called()


def test_probe_directory_writability_remove_retry_failure(tmp_path):
    """测试哨兵删除重试失败时诚实降级为 advisory 并回传 residue 路径"""
    test_dir = tmp_path / "rm_fail_dir"
    test_dir.mkdir()

    real_remove = os.remove

    def fake_remove(path):
        if install._PROBE_PREFIX in os.path.basename(path):
            raise OSError(errno.EACCES, "file locked for deletion")
        return real_remove(path)

    with patch("os.remove", side_effect=fake_remove):
        with patch("time.sleep"):
            verdict, msg = install.probe_directory_writability(str(test_dir))
            assert verdict == "advisory"
            assert "哨兵文件删除失败" in msg
            assert "residue=" in msg

    # 清理残留供 pytest teardown
    for f in test_dir.glob(f"{install._PROBE_PREFIX}*"):
        try:
            real_remove(str(f))
        except Exception:
            pass


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
    assert python_exe in guard_cmd


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
    assert any("目录可写性探测通过" in m for m in msgs)
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
    """测试 Windows MAX_PATH 审计规则（动态反算填充字符，严防 CI 目录长度差异假红）"""
    safe_backup = str(tmp_path / "bak.json")
    repo_root = str(tmp_path)
    log_dir = str(tmp_path / "logs")

    with patch("sys.platform", "win32"):
        # Case 1 (正常长度 pass): 真实短目录
        short_dir = tmp_path / "short"
        short_dir.mkdir()
        passed, msgs = install.run_preflight(
            str(short_dir), safe_backup, repo_root=repo_root, log_dir=log_dir
        )
        assert any("安全审计通过" in m for m in msgs)
        assert passed is True

        # Case 2 (警告范围 warn: > 200 且 <= 250): 动态反算 pad
        target_len = install.MAX_PATH_WARN_CHARS + 25  # 225
        pad = target_len - len(str(tmp_path)) - 1
        assert 2 <= pad <= 200, f"pad 长度异常: {pad}"
        warn_dir = tmp_path / ("a" * pad)
        warn_dir.mkdir()

        # 验证哨兵文件总长度留有余量 (<= 259)
        probe_len = len(os.path.abspath(str(warn_dir))) + 1 + len(install._PROBE_PREFIX) + 8
        assert probe_len <= 259, f"哨兵路径溢出 Windows MAX_PATH: {probe_len}"
        assert install.MAX_PATH_WARN_CHARS < len(os.path.abspath(str(warn_dir))) <= install.MAX_PATH_BLOCK_CHARS

        passed, msgs = install.run_preflight(
            str(warn_dir), safe_backup, repo_root=repo_root, log_dir=log_dir
        )
        assert any("MAX_PATH 警告" in m for m in msgs)
        assert passed is True

        # Case 3 (阻断范围 block: > 250): 多段路径组件组合，全程不创建实体目录
        block_dir = tmp_path / ("x" * 100) / ("y" * 100) / ("z" * 100)
        assert len(os.path.abspath(str(block_dir))) > install.MAX_PATH_BLOCK_CHARS
        passed, msgs = install.run_preflight(
            str(block_dir), safe_backup, repo_root=repo_root, log_dir=log_dir
        )
        assert any("MAX_PATH 阻断" in m for m in msgs)
        assert passed is False


def test_cli_preflight_flag(tmp_path):
    """测试命令行 --preflight 标志调用（通过 --repo-root 与 --backup-path 实现沙箱隔离）"""
    # 构造隔离的插件 stub
    stub_plugin = tmp_path / "plugins" / "quench-dev-tasks"
    stub_plugin.mkdir(parents=True)
    real_plugin_dir = install.get_plugin_dir()

    shutil.copy(os.path.join(real_plugin_dir, "mcp_config.json.template"), stub_plugin)
    shutil.copy(os.path.join(real_plugin_dir, "hooks.json.template"), stub_plugin)

    backup_file = tmp_path / "cli_backup.json"
    install_script = os.path.join(install.get_repo_root(), "scripts", "install.py")

    res = subprocess.run(
        [
            sys.executable,
            install_script,
            "--preflight",
            "--repo-root",
            str(tmp_path),
            "--backup-path",
            str(backup_file),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(tmp_path),
        timeout=15,
    )
    assert res.returncode == 0, f"stdout: {res.stdout}, stderr: {res.stderr}"
    assert "Pre-flight" in res.stdout
    assert backup_file.is_file()


def test_log_artifact_reserve_chars_constant():
    """验证 scripts/install.py 中的 _LOG_ARTIFACT_RESERVE_CHARS 等于 40"""
    assert install._LOG_ARTIFACT_RESERVE_CHARS == 40


def test_enoent_semantics_asymmetric_contract():
    """验证 ENOENT 语义非对称性契约：写入侧判 blocked，清理侧判 ok（_is_enoent 幂等）。"""
    # 1. POSIX 分支 (errno=ENOENT, winerror=None)
    err_posix = OSError(errno.ENOENT, "No such file or directory")
    err_posix.winerror = None
    assert install.classify_probe_error(err_posix) == "blocked"
    assert install._is_enoent(err_posix) is True

    # 2. Windows 分支 (errno=0, winerror=2 或 3)
    err_win2 = OSError(0, "The system cannot find the file specified")
    err_win2.winerror = 2
    assert install.classify_probe_error(err_win2) == "blocked"
    assert install._is_enoent(err_win2) is True

    err_win3 = OSError(0, "The system cannot find the path specified")
    err_win3.winerror = 3
    assert install.classify_probe_error(err_win3) == "blocked"
    assert install._is_enoent(err_win3) is True


def test_probe_write_failure_leaves_no_residue(tmp_path):
    """测试当单字节写探测失败时，判定为 blocked 且外层及磁盘零残留。"""
    test_dir = tmp_path / "write_fail_dir"
    test_dir.mkdir()

    with patch("os.write", side_effect=OSError(errno.EIO, "simulated write failure")):
        verdict, msg = install.probe_directory_writability(str(test_dir))
        assert verdict == "blocked"
        assert "无法写入或受阻" in msg
        assert list(test_dir.rglob(f"{install._PROBE_PREFIX}*")) == []


def test_probe_close_failure_leaves_no_residue(tmp_path):
    """测试内层 close 抛错时，异常传递判定为 blocked 且不产生双 close。"""
    test_dir = tmp_path / "close_fail_dir"
    test_dir.mkdir()

    real_close = os.close
    close_calls = []

    def close_then_raise(fd):
        close_calls.append(fd)
        real_close(fd)
        raise OSError(errno.EIO, "simulated close error")

    with patch("os.close", side_effect=close_then_raise):
        verdict, msg = install.probe_directory_writability(str(test_dir))
        assert verdict == "blocked"
        assert "无法写入或受阻" in msg
        # 验证仅被调用 1 次，外层 finally 见 fd is None 不会双 close
        assert len(close_calls) == 1


def test_probe_remove_enoent_is_success(tmp_path):
    """清理侧首轮抛出 ENOENT 时，探测应判定为 ok 且零残留（S-3 忠实模拟）。"""
    test_dir = tmp_path / "enoent_first_dir"
    test_dir.mkdir()

    real_remove = os.remove
    def fake_remove(path):
        base = os.path.basename(path)
        if base.startswith(install._PROBE_PREFIX):
            real_remove(path)
            raise FileNotFoundError(errno.ENOENT, "vanished by indexer")
        return real_remove(path)

    with patch("os.remove", side_effect=fake_remove):
        verdict, msg = install.probe_directory_writability(str(test_dir))
        assert verdict == "ok"
        assert "目录可写性探测通过" in msg
        assert "residue=" not in msg
        assert list(test_dir.rglob(f"{install._PROBE_PREFIX}*")) == []


def test_probe_remove_enoent_on_retry_is_success(tmp_path):
    """清理侧首轮失败、第二轮抛 ENOENT 时，探测判定为 ok 且零残留（S-3 忠实模拟）。"""
    test_dir = tmp_path / "enoent_retry_dir"
    test_dir.mkdir()

    real_remove = os.remove
    call_count = 0

    def fake_remove(path):
        nonlocal call_count
        base = os.path.basename(path)
        if base.startswith(install._PROBE_PREFIX):
            call_count += 1
            if call_count == 1:
                raise PermissionError(errno.EACCES, "temporary sharing conflict")
            real_remove(path)
            raise FileNotFoundError(errno.ENOENT, "vanished on retry")
        return real_remove(path)

    with patch("os.remove", side_effect=fake_remove), patch("time.sleep"):
        verdict, msg = install.probe_directory_writability(str(test_dir))
        assert verdict == "ok"
        assert "目录可写性探测通过" in msg
        assert "residue=" not in msg
        assert call_count == 2
        assert list(test_dir.rglob(f"{install._PROBE_PREFIX}*")) == []


def test_is_enoent_predicate():
    """验证 _is_enoent 谓词矩阵（覆盖真异常与鸭子类型）。"""
    import types

    # 1. 真异常
    assert install._is_enoent(FileNotFoundError("not found")) is True
    assert install._is_enoent(OSError(errno.ENOENT, "gone")) is True
    assert install._is_enoent(PermissionError("denied")) is False
    assert install._is_enoent(OSError(errno.EACCES, "denied")) is False

    # 2. winerror 判定（鸭子类型）
    win_err2 = types.SimpleNamespace(errno=0, winerror=2)
    win_err3 = types.SimpleNamespace(errno=0, winerror=3)
    win_err5 = types.SimpleNamespace(errno=0, winerror=5)
    win_err_none = types.SimpleNamespace(errno=errno.ENOENT, winerror=None)
    assert install._is_enoent(win_err2) is True
    assert install._is_enoent(win_err3) is True
    assert install._is_enoent(win_err5) is False
    assert install._is_enoent(win_err_none) is True


def test_preflight_probe_doc_exists():
    """验证 ci_incident_tracker_and_compatibility_guide.md 包含 Preflight Probe 幂等语义锚点句。"""
    from pathlib import Path

    doc_path = (
        Path(__file__).resolve().parents[4]
        / "docs"
        / "ci_incident_tracker_and_compatibility_guide.md"
    )
    assert doc_path.is_file(), f"Document not found: {doc_path}"
    content = doc_path.read_text(encoding="utf-8-sig")
    anchors = [
        "### Preflight Probe — unlink ENOENT / winerror 2|3 幂等语义",
        "当 os.remove 返回 ENOENT 或 Windows winerror ∈ {2, 3} 时，视为目标文件已不存在，探测判定为 ok，不产生 residue。",
        "当 os.remove 返回 winerror ∈ {32, 33}（共享冲突）时，判定为 advisory 并保留 residue 路径以支持人工清理。",
    ]
    for anchor in anchors:
        assert anchor in content, f"missing anchor in {doc_path}: {anchor!r}"


def test_probe_writes_nonempty_bytes(tmp_path):
    """验证探针写入了单字节非空载荷且检查了短写。"""
    written_payloads = []
    real_write = os.write

    def fake_write(fd, data):
        written_payloads.append(data)
        return real_write(fd, data)

    with patch("os.write", side_effect=fake_write):
        verdict, _ = install.probe_directory_writability(str(tmp_path))
        assert verdict == "ok"
        assert len(written_payloads) == 1
        assert written_payloads[0] == b"\x00"


def test_probe_fd_closed_exactly_once(tmp_path):
    """验证即使 write 失败，fd 恰好被 close 1 次（防双 close 且不泄漏）。"""
    close_calls = []
    real_close = os.close

    def fake_close(fd):
        close_calls.append(fd)
        real_close(fd)

    with patch("os.write", side_effect=OSError(errno.EIO, "write error")), patch(
        "os.close", side_effect=fake_close
    ):
        verdict, msg = install.probe_directory_writability(str(tmp_path))
        assert verdict == "blocked"
        assert len(close_calls) == 1


def test_render_configs_generates_repo_agents_mcp_config(mock_plugin_env):
    """验证 render_configs 在检测到 repo_root/.agents 存在时，同步生成 .agents/mcp_config.json。"""
    repo_root = mock_plugin_env.parent.parent
    repo_agents = repo_root / ".agents"
    repo_agents.mkdir(parents=True, exist_ok=True)

    out_mcp, out_hooks = install.render_configs(str(mock_plugin_env), python_exe=sys.executable)
    assert os.path.isfile(out_mcp)
    assert os.path.isfile(out_hooks)

    repo_mcp = repo_agents / "mcp_config.json"
    assert repo_mcp.is_file()
    with open(repo_mcp, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "quench-dev-tasks" in data.get("mcpServers", {})


def test_preflight_and_rollback_covers_repo_mcp_config(mock_plugin_env, tmp_path):
    """验证 run_preflight 记录已有 .agents/mcp_config.json 快照并在 rollback 中准确恢复。"""
    repo_root = mock_plugin_env.parent.parent
    repo_agents = repo_root / ".agents"
    repo_agents.mkdir(parents=True, exist_ok=True)
    repo_mcp = repo_agents / "mcp_config.json"

    old_content = '{\n  "mcpServers": {\n    "old-server": {"command": "echo"}\n  }\n}'
    repo_mcp.write_text(old_content, encoding="utf-8")

    backup_path = str(tmp_path / "backup.json")
    passed, msgs = install.run_preflight(str(mock_plugin_env), backup_path, repo_root=str(repo_root))
    assert passed is True

    with open(backup_path, "r", encoding="utf-8") as f:
        snap = json.load(f)
    assert ".agents/mcp_config.json" in snap["files"]
    assert "old-server" in snap["files"][".agents/mcp_config.json"]

    # 模拟安装覆盖
    repo_mcp.write_text('{"mcpServers": {"quench-dev-tasks": {}}}', encoding="utf-8")

    # 执行回滚
    success = install.rollback_configuration(str(mock_plugin_env), backup_path)
    assert success is True

    # 验证恢复旧内容
    with open(repo_mcp, "r", encoding="utf-8") as f:
        restored = json.load(f)
    assert "old-server" in restored["mcpServers"]
    assert "quench-dev-tasks" not in restored["mcpServers"]


def test_rollback_removes_untracked_repo_mcp_config(mock_plugin_env, tmp_path):
    """验证当安装前 .agents/mcp_config.json 不存在时，rollback 准确清理生成的新文件。"""
    repo_root = mock_plugin_env.parent.parent
    repo_agents = repo_root / ".agents"
    repo_agents.mkdir(parents=True, exist_ok=True)
    repo_mcp = repo_agents / "mcp_config.json"
    if repo_mcp.exists():
        repo_mcp.unlink()

    backup_path = str(tmp_path / "backup.json")
    passed, msgs = install.run_preflight(str(mock_plugin_env), backup_path, repo_root=str(repo_root))
    assert passed is True

    with open(backup_path, "r", encoding="utf-8") as f:
        snap = json.load(f)
    assert snap["files"][".agents/mcp_config.json"] is None

    # 模拟安装生成了该文件
    repo_mcp.write_text('{"mcpServers": {}}', encoding="utf-8")
    assert repo_mcp.exists()

    # 执行回滚
    success = install.rollback_configuration(str(mock_plugin_env), backup_path)
    assert success is True

    # 验证未存在的文件被清理
    assert not repo_mcp.exists()


