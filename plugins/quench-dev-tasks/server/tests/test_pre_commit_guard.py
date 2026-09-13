# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

# 导入待测试脚本中的纯标准库函数
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts",
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from git_pre_commit_guard import (
    _extract_yaml_field,
    is_file_unmanaged,
    find_active_task,
    check_violations,
    is_antigravity_environment,
    install_hook,
    main,
)


@pytest.fixture
def temp_git_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(root), check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(root), check=True)
        yield root


def test_extract_yaml_field():
    """测试不用 PyYAML 的正则轻量级提取"""
    content = (
        "project_name: 'MyProject'\n"
        "dev_tasks_dir: docs/dev_tasks\n"
        "changelog_path: \"CHANGELOG.md\"\n"
    )
    assert _extract_yaml_field(content, "project_name") == "MyProject"
    assert _extract_yaml_field(content, "dev_tasks_dir") == "docs/dev_tasks"
    assert _extract_yaml_field(content, "changelog_path") == "CHANGELOG.md"
    assert _extract_yaml_field(content, "nonexistent") is None


def test_is_file_unmanaged():
    """测试免管文件过滤规则"""
    assert is_file_unmanaged("docs/index.md") is True
    assert is_file_unmanaged("README.md") is True
    assert is_file_unmanaged("CHANGELOG.md") is True
    assert is_file_unmanaged("assets/logo.png") is True
    assert is_file_unmanaged("samples/example.py") is True
    assert is_file_unmanaged("data.csv") is True
    assert is_file_unmanaged("app.log") is True

    # 生产代码文件不免管
    assert is_file_unmanaged("src/main.py") is False
    assert is_file_unmanaged("package.json") is False
    assert is_file_unmanaged("Cargo.toml") is False


def test_find_active_task(temp_git_repo):
    """测试从 Markdown 任务单中解析当前处于执行中的任务"""
    tasks_dir = temp_git_repo / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task_file = tasks_dir / "2026-09-11_demo.md"

    content = """# 演进任务单

### 任务 1 🔨 执行中 — 核心引擎改造

#### 【涉及文件】
```
[MODIFY] src/engine.py
[NEW] src/models.py
```

### 任务 2 ⬜ 待确认 — 后续规划
"""
    task_file.write_text(content, encoding="utf-8")

    res = find_active_task(str(tasks_dir))
    assert res is not None
    task_id, title, allowed = res
    assert task_id == "1"
    assert "核心引擎改造" in title
    assert "src/engine.py" in allowed
    assert "src/models.py" in allowed


def test_check_violations():
    """测试白名单校验逻辑与越界识别"""
    allowed_files = ["src/main.py", "src/utils.py"]
    staged = [
        "src/main.py",       # 白名单内：放行
        "docs/guide.md",     # 免管文档：放行
        "src/evil.py",       # 白名单外代码：违规！
        "config/app.json",   # 白名单外代码/配置：违规！
    ]

    violations = check_violations(staged, allowed_files, "/mock/ws")
    assert "src/evil.py" in violations
    assert "config/app.json" in violations
    assert "src/main.py" not in violations
    assert "docs/guide.md" not in violations


def test_is_antigravity_environment(temp_git_repo):
    """测试 Antigravity IDE 环境特征检测与降级识别"""
    # 默认非 Antigravity
    with patch.dict(os.environ, {}, clear=True):
        assert is_antigravity_environment(str(temp_git_repo)) is False

    # 环境变量检测
    with patch.dict(os.environ, {"ANTIGRAVITY_APP_DIR": "/some/path"}):
        assert is_antigravity_environment(str(temp_git_repo)) is True

    # 插件配置文件检测
    agents_dir = temp_git_repo / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plugins_json = agents_dir / "plugins.json"
    plugins_json.write_text('{"installed": ["quench-dev-tasks"]}', encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True):
        assert is_antigravity_environment(str(temp_git_repo)) is True


def test_install_hook(temp_git_repo):
    """测试一键安装 hook 到 .git/hooks/pre-commit"""
    exit_code = install_hook(str(temp_git_repo))
    assert exit_code == 0

    hook_path = temp_git_repo / ".git" / "hooks" / "pre-commit"
    assert hook_path.is_file()
    assert "git_pre_commit_guard.py" in hook_path.read_text(encoding="utf-8")

    # 重复安装幂等性检查
    exit_code2 = install_hook(str(temp_git_repo))
    assert exit_code2 == 0


def test_main_workflow(temp_git_repo):
    """端到端验证 main() 流程：无活跃任务、Antigravity 降级、违规拦截"""
    agents_dir = temp_git_repo / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "quench_stack.yaml").write_text("project_name: 'test'\n", encoding="utf-8")

    # 1. 无活跃任务 -> 放行 (exit 0)
    with patch("sys.argv", ["git_pre_commit_guard.py", "--workspace", str(temp_git_repo)]):
        assert main() == 0

    # 2. 构造活跃任务
    tasks_dir = temp_git_repo / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task_file = tasks_dir / "2026-09-11_demo.md"
    task_file.write_text("""### 任务 1 🔨 执行中 — 任务标题\n#### 【涉及文件】\n```\n[MODIFY] src/app.py\n```\n""", encoding="utf-8")

    # 3. Antigravity 环境 -> 降级 warning-only 放行 (exit 0)
    with patch("git_pre_commit_guard.is_antigravity_environment", return_value=True):
        with patch("sys.argv", ["git_pre_commit_guard.py", "--workspace", str(temp_git_repo)]):
            assert main() == 0

    # 4. 非 Antigravity 环境下有越界文件 -> 拦截 (exit 1)
    with patch("git_pre_commit_guard.is_antigravity_environment", return_value=False):
        with patch("git_pre_commit_guard.get_staged_files", return_value=["src/outside.py"]):
            with patch("sys.argv", ["git_pre_commit_guard.py", "--workspace", str(temp_git_repo)]):
                assert main() == 1

    # 5. 非 Antigravity 环境下白名单文件 -> 放行 (exit 0)
    with patch("git_pre_commit_guard.is_antigravity_environment", return_value=False):
        with patch("git_pre_commit_guard.get_staged_files", return_value=["src/app.py"]):
            with patch("sys.argv", ["git_pre_commit_guard.py", "--workspace", str(temp_git_repo)]):
                assert main() == 0
