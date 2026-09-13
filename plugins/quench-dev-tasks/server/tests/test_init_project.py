import json
import os
import subprocess
import sys
import pytest
import yaml

PYTHON_EXE = sys.executable
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
INIT_PROJECT = os.path.join(SCRIPTS_DIR, "init_project.py")


def test_init_project_nonexistent_root(tmp_path):
    non_existent = str(tmp_path / "non_existent_path_xyz_123")
    p = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, non_existent],
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

    # Check hooks.json
    hooks_json = agents_dir / "hooks.json"
    assert hooks_json.is_file()
    with open(hooks_json, "r", encoding="utf-8") as f:
        h_data = json.load(f)
    assert "quench-file-guard" in h_data
    assert "quench-context-injector" in h_data

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
    assert diag["has_hooks_json"] is False
    assert diag["hooks_json_valid"] is False
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

    stub_script = git_dir / "guard_stub.py"
    stub_script.write_text("# stub", encoding="utf-8")
    fake_hooks = {
        "quench-file-guard": {
            "PreToolUse": [{
                "matcher": ".*",
                "hooks": [{"type": "command", "command": f'"{PYTHON_EXE}" "{stub_script}"'}]
            }]
        }
    }
    (agents_dir / "hooks.json").write_text(json.dumps(fake_hooks), encoding="utf-8")

    diag_git = diagnose_environment(str(git_dir))
    assert diag_git["is_git_repo"] is True
    assert diag_git["has_quench_stack"] is True
    assert diag_git["has_plugins_json"] is True
    assert diag_git["has_hooks_json"] is True
    assert diag_git["hooks_json_valid"] is True


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


def test_init_project_generates_hooks_json(tmp_path):
    proj_dir = tmp_path / "hooks_gen_proj"
    proj_dir.mkdir()
    p = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, str(proj_dir), "--name", "HooksGenDemo"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0
    hooks_json = proj_dir / ".agents" / "hooks.json"
    assert hooks_json.is_file()
    with open(hooks_json, "r", encoding="utf-8") as f:
        h_data = json.load(f)
    assert "quench-file-guard" in h_data
    assert "quench-context-injector" in h_data
    cmd = h_data["quench-file-guard"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "python" in cmd.lower() or "venv" in cmd.lower()


def test_init_project_hooks_json_idempotent_skip(tmp_path):
    proj_dir = tmp_path / "hooks_skip_proj"
    proj_dir.mkdir()
    p1 = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, str(proj_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p1.returncode == 0
    hooks_json = proj_dir / ".agents" / "hooks.json"
    assert hooks_json.is_file()

    # Manually modify hooks.json
    marker_content = '{"custom_marker": "keep_me"}\n'
    hooks_json.write_text(marker_content, encoding="utf-8")

    p2 = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, str(proj_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p2.returncode == 0
    assert "跳过覆盖" in p2.stdout
    assert hooks_json.read_text(encoding="utf-8") == marker_content


def test_init_project_hooks_json_force_overwrite(tmp_path):
    proj_dir = tmp_path / "hooks_force_proj"
    proj_dir.mkdir()
    p1 = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, str(proj_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p1.returncode == 0
    hooks_json = proj_dir / ".agents" / "hooks.json"
    assert hooks_json.is_file()

    # Manually modify hooks.json
    hooks_json.write_text('{"custom_marker": "will_be_overwritten"}\n', encoding="utf-8")

    p2 = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT, str(proj_dir), "--force"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p2.returncode == 0
    assert "正在覆盖" in p2.stdout
    new_content = hooks_json.read_text(encoding="utf-8")
    assert "custom_marker" not in new_content
    assert "quench-file-guard" in new_content


def test_diagnose_hooks_json_branches(tmp_path):
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    from init_project import diagnose_environment

    proj_dir = tmp_path / "diag_branches_proj"
    proj_dir.mkdir()
    agents_dir = proj_dir / ".agents"
    agents_dir.mkdir()
    (agents_dir / "quench_stack.yaml").write_text("project_name: 'Diag'\n", encoding="utf-8")
    (agents_dir / "plugins.json").write_text('{"entries": []}\n', encoding="utf-8")
    subprocess.run(["git", "init"], cwd=str(proj_dir), capture_output=True, check=True)

    # Branch A: hooks.json does not exist
    diag_a = diagnose_environment(str(proj_dir))
    assert diag_a["has_hooks_json"] is False
    assert diag_a["hooks_json_valid"] is False
    assert any("缺少生命周期 Hook" in issue for issue in diag_a["issues"])

    # Branch B: hooks.json exists but invalid JSON
    hooks_file = agents_dir / "hooks.json"
    hooks_file.write_text("{ broken json", encoding="utf-8")
    diag_b = diagnose_environment(str(proj_dir))
    assert diag_b["has_hooks_json"] is True
    assert diag_b["hooks_json_valid"] is False
    assert any("损坏" in issue for issue in diag_b["issues"])

    # Branch C: hooks.json exists, valid JSON, but references non-existent script/python path
    non_existent_py = str(proj_dir / "non_existent_script_123.py")
    bad_hooks = {
        "quench-file-guard": {
            "PreToolUse": [{
                "matcher": ".*",
                "hooks": [{"type": "command", "command": f'"{PYTHON_EXE}" "{non_existent_py}"'}]
            }]
        }
    }
    hooks_file.write_text(json.dumps(bad_hooks), encoding="utf-8")
    diag_c = diagnose_environment(str(proj_dir))
    assert diag_c["has_hooks_json"] is True
    assert diag_c["hooks_json_valid"] is False
    assert any("不存在" in issue for issue in diag_c["issues"])

    # Branch D: hooks.json valid and paths exist
    real_script = proj_dir / "valid_script.py"
    real_script.write_text("# valid", encoding="utf-8")
    good_hooks = {
        "quench-file-guard": {
            "PreToolUse": [{
                "matcher": ".*",
                "hooks": [{"type": "command", "command": f'"{PYTHON_EXE}" "{real_script}"'}]
            }]
        }
    }
    hooks_file.write_text(json.dumps(good_hooks), encoding="utf-8")
    diag_d = diagnose_environment(str(proj_dir))
    assert diag_d["has_hooks_json"] is True
    assert diag_d["hooks_json_valid"] is True
    assert not any("hooks.json" in issue for issue in diag_d["issues"])


def test_hooks_json_command_format(tmp_path):
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    from init_project import _render_hooks_json

    proj_dir = tmp_path / "cmd_format_proj"
    proj_dir.mkdir()
    hooks_path = proj_dir / ".agents" / "hooks.json"

    _render_hooks_json(str(proj_dir), force=True)
    assert hooks_path.is_file()
    with open(hooks_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cmd = data["quench-file-guard"]["PreToolUse"][0]["hooks"][0]["command"]

    # 验证标准格式：各路径独立带引号，最外层不额外嵌套无用的 ""
    assert not cmd.startswith('""')
    assert not cmd.endswith('""')
    assert cmd.startswith('"')
    assert cmd.endswith('"')
    # 验证包含 python 解释器和脚本路径两个独立双引号段落
    assert cmd.count('"') >= 4

