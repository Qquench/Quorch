import os
import sys
import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import cli


def test_color_detection(monkeypatch):
    """测试 ANSI 彩色环境自适应与 NO_COLOR 环境变量降级"""
    assert cli.should_enable_color(plain=True) is False

    monkeypatch.setenv("NO_COLOR", "1")
    assert cli.should_enable_color(plain=False) is False

    monkeypatch.delenv("NO_COLOR", raising=False)
    # 非 TTY 环境兜底为 False
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert cli.should_enable_color(plain=False) is False


def test_cli_status_basic(tmp_path, capsys):
    """测试 status 子命令正常执行看板输出"""
    proj = tmp_path / "status_proj"
    proj.mkdir()
    agents = proj / ".agents"
    agents.mkdir()
    stack = agents / "quench_stack.yaml"
    with open(stack, "w", encoding="utf-8") as f:
        f.write('project_name: "CliStatusTest"\nschema_version: 2\n')

    code = cli.main(["status", "-w", str(proj), "--plain"])
    assert code == 0

    captured = capsys.readouterr()
    assert "Quench 任务状态看板" in captured.out
    assert "CliStatusTest" in captured.out


def test_cli_check_command(tmp_path, capsys):
    """测试 check 子命令环境诊断"""
    proj = tmp_path / "check_proj"
    proj.mkdir()

    code = cli.main(["check", "-w", str(proj)])
    # 因为 proj 不是标准 Git 和 Quench 项目，check 应返回 1
    assert code == 1

    captured = capsys.readouterr()
    assert "环境就绪状态诊断" in captured.out or "诊断发现" in captured.out


def test_cli_init_command(tmp_path, capsys):
    """测试 init 子命令薄封装转发至 init_project"""
    proj = tmp_path / "init_proj"
    proj.mkdir()
    (proj / ".git").mkdir()

    code = cli.main([
        "init",
        str(proj),
        "--ide", "cursor",
        "--install-git-hook",
        "--force",
    ])
    assert code == 0

    captured = capsys.readouterr()
    assert "Cursor 接入初始化完成" in captured.out
    assert (proj / ".cursor" / "mcp.json").is_file()
    assert (proj / ".git" / "hooks" / "pre-commit").is_file()


def test_cli_archive_empty_and_unclosed(tmp_path, capsys):
    """测试 archive 子命令在无任务或未闭环任务时的安全防御"""
    proj = tmp_path / "archive_proj"
    proj.mkdir()
    agents = proj / ".agents"
    agents.mkdir()
    with open(agents / "quench_stack.yaml", "w", encoding="utf-8") as f:
        f.write('project_name: "ArchiveTest"\nschema_version: 2\n')

    # 1. 没有任何任务单
    code = cli.main(["archive", "-w", str(proj)])
    assert code == 0
    captured = capsys.readouterr()
    assert "没有找到需要归档的任务单据" in captured.out

    # 2. 存在未完成任务
    dev_tasks = proj / "docs" / "dev_tasks"
    dev_tasks.mkdir(parents=True, exist_ok=True)
    task_file = dev_tasks / "sample_task.md"
    with open(task_file, "w", encoding="utf-8") as f:
        f.write("# 测试任务单\n\n### 任务 1 🔨 执行中 — 未完成任务\n")

    code = cli.main(["archive", "-w", str(proj)])
    assert code == 1
    captured = capsys.readouterr()
    assert "仍有未闭环任务" in captured.out


def test_cli_help_and_default(capsys):
    """测试不传子命令时默认展示 status 看板或帮助"""
    code = cli.main(["--help"])
    assert code == 0
    captured = capsys.readouterr()
    assert "quench" in captured.out
    assert "status" in captured.out
    assert "archive" in captured.out
