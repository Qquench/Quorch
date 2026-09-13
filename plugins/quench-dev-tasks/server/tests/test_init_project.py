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
