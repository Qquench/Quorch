import json
import os
import subprocess
import sys
import pytest
import yaml

PYTHON_EXE = sys.executable
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
INIT_PROJECT = os.path.join(SCRIPTS_DIR, "init_project.py")


def test_init_project_nonexistent_root():
    p = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, "D:/NonExistentPath_XYZ_123"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode != 0
    output = (p.stderr or "") + (p.stdout or "")
    assert "不存在" in output


def test_init_project_success(tmp_path):
    proj_dir = tmp_path / "my_project"
    proj_dir.mkdir()

    # First run with custom name
    p = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, str(proj_dir), "--name", "DemoProject"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0
    assert "初始化完成" in p.stdout

    agents_dir = proj_dir / ".agents"
    assert agents_dir.is_dir()

    # Check plugins.json
    plugins_json = agents_dir / "plugins.json"
    assert plugins_json.is_file()
    with open(plugins_json, "r", encoding="utf-8") as f:
        p_data = json.load(f)
    assert "entries" in p_data
    assert len(p_data["entries"]) >= 1

    # Check quench_stack.yaml
    stack_yaml = agents_dir / "quench_stack.yaml"
    assert stack_yaml.is_file()
    with open(stack_yaml, "r", encoding="utf-8") as f:
        y_data = yaml.safe_load(f)
    assert y_data["project_name"] == "DemoProject"

    # Check dev_tasks directories and README
    dev_tasks = proj_dir / "docs" / "dev_tasks"
    assert dev_tasks.is_dir()
    assert (dev_tasks / "archive").is_dir()
    assert (dev_tasks / "README.md").is_file()

    # Second run: test idempotency and non-overwriting
    stack_yaml.write_text("project_name: 'OverriddenProject'\n", encoding="utf-8")
    p2 = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, str(proj_dir), "--name", "NewNameShouldNotOverwrite"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p2.returncode == 0
    assert "跳过覆盖" in p2.stdout
    assert "已配置" in p2.stdout
    # Ensure manual modification was kept
    assert "OverriddenProject" in stack_yaml.read_text(encoding="utf-8")


def test_diagnose_environment_direct(tmp_path):
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    from init_project import diagnose_environment

    # 1. Non-git empty dir
    empty_dir = tmp_path / "empty_proj"
    empty_dir.mkdir()
    diag = diagnose_environment(str(empty_dir))
    assert diag["is_git_repo"] is False
    assert diag["has_quench_stack"] is False
    assert diag["has_plugins_json"] is False
    assert any("Git" in issue for issue in diag["issues"])
    assert any("git init" in sugg for sugg in diag["suggestions"])

    # 2. Fake git dir with initialized quench files
    git_dir = tmp_path / "git_proj"
    git_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(git_dir), capture_output=True, check=True)
    agents_dir = git_dir / ".agents"
    agents_dir.mkdir()
    (agents_dir / "quench_stack.yaml").write_text("project_name: 'Test'\n", encoding="utf-8")
    (agents_dir / "plugins.json").write_text('{"entries": []}\n', encoding="utf-8")

    diag_git = diagnose_environment(str(git_dir))
    assert diag_git["is_git_repo"] is True
    assert diag_git["has_quench_stack"] is True
    assert diag_git["has_plugins_json"] is True


def test_init_project_check_flag(tmp_path):
    # Test --check CLI output
    p = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, "--check", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0
    assert "体检报告" in p.stdout
    assert "Git 仓库有效性" in p.stdout


def test_init_project_force_flag(tmp_path):
    proj_dir = tmp_path / "force_proj"
    proj_dir.mkdir()

    # Initial run
    p1 = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, str(proj_dir), "--name", "OrigName"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p1.returncode == 0
    stack_yaml = proj_dir / ".agents" / "quench_stack.yaml"
    assert "OrigName" in stack_yaml.read_text(encoding="utf-8")

    # Run with --force and new name
    p2 = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, str(proj_dir), "--name", "ForcedName", "--force"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p2.returncode == 0
    assert "正在覆盖" in p2.stdout
    assert "ForcedName" in stack_yaml.read_text(encoding="utf-8")


def test_init_project_non_git_warning(tmp_path):
    proj_dir = tmp_path / "nongit_proj"
    proj_dir.mkdir()

    p = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, str(proj_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0
    assert "暂未初始化为 Git 仓库" in p.stdout
    assert (proj_dir / ".agents" / "quench_stack.yaml").is_file()

