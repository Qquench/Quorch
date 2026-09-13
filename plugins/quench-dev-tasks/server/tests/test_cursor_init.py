import json
import os
import subprocess
import sys
import pytest

# Ensure scripts directory is in sys.path
SCRIPTS_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts",
    )
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from init_project import (
    generate_cursor_mcp_config,
    install_git_pre_commit_hook,
    init_project,
)

PYTHON_EXE = sys.executable
INIT_PROJECT_SCRIPT = os.path.join(SCRIPTS_DIR, "init_project.py")


def test_generate_cursor_mcp_config_new(tmp_path):
    """测试在未配置过 Cursor 的目录中生成 .cursor/mcp.json"""
    proj_dir = str(tmp_path / "cursor_test_proj")
    os.makedirs(proj_dir, exist_ok=True)

    out_path = generate_cursor_mcp_config(proj_dir, PYTHON_EXE)
    assert os.path.isfile(out_path)

    with open(out_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "mcpServers" in data
    assert "quench-dev-tasks" in data["mcpServers"]
    entry = data["mcpServers"]["quench-dev-tasks"]
    assert entry["command"] == PYTHON_EXE
    assert len(entry["args"]) == 1
    assert entry["args"][0].endswith("server.py")


def test_generate_cursor_mcp_config_merge(tmp_path):
    """测试已有其它工具的 .cursor/mcp.json 时，合并保留其它工具"""
    proj_dir = str(tmp_path / "cursor_merge_proj")
    cursor_dir = os.path.join(proj_dir, ".cursor")
    os.makedirs(cursor_dir, exist_ok=True)
    mcp_path = os.path.join(cursor_dir, "mcp.json")

    existing_content = {
        "mcpServers": {
            "custom-tool": {
                "command": "node",
                "args": ["index.js"],
            }
        }
    }
    with open(mcp_path, "w", encoding="utf-8") as f:
        json.dump(existing_content, f)

    out_path = generate_cursor_mcp_config(proj_dir, PYTHON_EXE)
    assert out_path == mcp_path

    with open(out_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "custom-tool" in data["mcpServers"]
    assert data["mcpServers"]["custom-tool"]["command"] == "node"
    assert "quench-dev-tasks" in data["mcpServers"]


def test_generate_cursor_mcp_config_idempotent(tmp_path):
    """测试多次生成时的幂等性"""
    proj_dir = str(tmp_path / "cursor_idempotent_proj")
    os.makedirs(proj_dir, exist_ok=True)

    out1 = generate_cursor_mcp_config(proj_dir, PYTHON_EXE)
    with open(out1, "r", encoding="utf-8") as f:
        c1 = f.read()

    out2 = generate_cursor_mcp_config(proj_dir, PYTHON_EXE)
    with open(out2, "r", encoding="utf-8") as f:
        c2 = f.read()

    assert c1 == c2


def test_install_git_pre_commit_hook_non_git(tmp_path):
    """测试非 Git 仓库下优雅跳过安装，返回 False 且不崩溃"""
    proj_dir = str(tmp_path / "non_git_proj")
    os.makedirs(proj_dir, exist_ok=True)

    result = install_git_pre_commit_hook(proj_dir)
    assert result is False
    assert not os.path.exists(os.path.join(proj_dir, ".git"))


def test_install_git_pre_commit_hook_new(tmp_path):
    """测试在标准 Git 仓库中全新安装 pre-commit 钩子"""
    proj_dir = str(tmp_path / "git_proj")
    git_dir = os.path.join(proj_dir, ".git")
    os.makedirs(git_dir, exist_ok=True)

    result = install_git_pre_commit_hook(proj_dir)
    assert result is True

    hook_file = os.path.join(git_dir, "hooks", "pre-commit")
    assert os.path.isfile(hook_file)

    with open(hook_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "git_pre_commit_guard.py" in content
    assert "#!/usr/bin/env bash" in content


def test_install_git_pre_commit_hook_chain_append(tmp_path):
    """测试目标已存在第三方钩子（如 lint-staged/husky）时，进行链式追加注入"""
    proj_dir = str(tmp_path / "git_chain_proj")
    hooks_dir = os.path.join(proj_dir, ".git", "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    target_hook = os.path.join(hooks_dir, "pre-commit")

    existing_hook = "#!/bin/sh\necho 'running lint-staged...'\nnpm run lint-staged\n"
    with open(target_hook, "w", encoding="utf-8") as f:
        f.write(existing_hook)

    result = install_git_pre_commit_hook(proj_dir, force=False)
    assert result is True

    with open(target_hook, "r", encoding="utf-8") as f:
        merged = f.read()

    # 原有内容必须被完整保留
    assert "running lint-staged" in merged
    assert "npm run lint-staged" in merged
    # 追加的 Quench 守卫必须存在
    assert "# === Quench Git Pre-commit Guard Injection ===" in merged
    assert "git_pre_commit_guard.py" in merged


def test_install_git_pre_commit_hook_force(tmp_path):
    """测试 force=True 时强制重写 hook"""
    proj_dir = str(tmp_path / "git_force_proj")
    hooks_dir = os.path.join(proj_dir, ".git", "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    target_hook = os.path.join(hooks_dir, "pre-commit")

    with open(target_hook, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nlegacy hook\n")

    result = install_git_pre_commit_hook(proj_dir, force=True)
    assert result is True

    with open(target_hook, "r", encoding="utf-8") as f:
        content = f.read()

    assert "legacy hook" not in content
    assert "Quench Git Pre-commit Guard Shim" in content


def test_install_git_pre_commit_hook_idempotent(tmp_path):
    """测试重复调用安装时不会重复注入追加"""
    proj_dir = str(tmp_path / "git_repeat_proj")
    hooks_dir = os.path.join(proj_dir, ".git", "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    target_hook = os.path.join(hooks_dir, "pre-commit")

    existing_hook = "#!/bin/sh\necho 'custom'\n"
    with open(target_hook, "w", encoding="utf-8") as f:
        f.write(existing_hook)

    assert install_git_pre_commit_hook(proj_dir) is True
    with open(target_hook, "r", encoding="utf-8") as f:
        once = f.read()

    assert install_git_pre_commit_hook(proj_dir) is True
    with open(target_hook, "r", encoding="utf-8") as f:
        twice = f.read()

    assert once == twice
    assert twice.count("Quench Git Pre-commit Guard Injection") == 1


def test_init_project_cursor_and_all_modes(tmp_path):
    """端到端测试 init_project 的 cursor 与 all 模式"""
    # 1. Cursor 模式
    cursor_proj = tmp_path / "cursor_full_proj"
    cursor_proj.mkdir()
    (cursor_proj / ".git").mkdir()

    init_project(str(cursor_proj), "CursorFull", ide="cursor", install_hook=True)
    assert (cursor_proj / ".cursor" / "mcp.json").is_file()
    assert (cursor_proj / ".git" / "hooks" / "pre-commit").is_file()
    assert (cursor_proj / ".agents" / "quench_stack.yaml").is_file()
    # Cursor 模式下不强制创建 plugins.json 与 hooks.json
    assert not (cursor_proj / ".agents" / "hooks.json").is_file()

    # 2. All 模式
    all_proj = tmp_path / "all_full_proj"
    all_proj.mkdir()
    (all_proj / ".git").mkdir()

    init_project(str(all_proj), "AllFull", ide="all", install_hook=True)
    assert (all_proj / ".cursor" / "mcp.json").is_file()
    assert (all_proj / ".git" / "hooks" / "pre-commit").is_file()
    assert (all_proj / ".agents" / "plugins.json").is_file()
    assert (all_proj / ".agents" / "hooks.json").is_file()
    assert (all_proj / ".agents" / "quench_stack.yaml").is_file()


def test_init_project_cli_cursor_flag(tmp_path):
    """测试 CLI 命令行 --cursor 与 --install-git-hook 参数透传"""
    proj_dir = tmp_path / "cli_cursor_proj"
    proj_dir.mkdir()
    (proj_dir / ".git").mkdir()

    p = subprocess.run(
        [PYTHON_EXE, INIT_PROJECT_SCRIPT, str(proj_dir), "--cursor", "--install-git-hook"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0
    assert "Cursor 接入初始化完成" in p.stdout
    assert (proj_dir / ".cursor" / "mcp.json").is_file()
    assert (proj_dir / ".git" / "hooks" / "pre-commit").is_file()
