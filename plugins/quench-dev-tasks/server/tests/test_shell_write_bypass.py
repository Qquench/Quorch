# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys
import pytest

# Ensure hook and server modules can be imported
server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
hooks_dir = os.path.join(server_dir, "hooks")
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)
if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)

from file_scope_guard import (
    SHELL_TOOL_NAMES,
    SHELL_WRITE_PATTERN,
    detect_shell_write_bypass,
)
from server import check_shell_write_isolation

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


def test_shell_tool_names_membership():
    assert "run_command" in SHELL_TOOL_NAMES
    assert "execute_command" in SHELL_TOOL_NAMES
    assert "bash" in SHELL_TOOL_NAMES
    assert "shell" in SHELL_TOOL_NAMES


@pytest.mark.parametrize(
    "cmd,expected_substr",
    [
        ("echo '# Fake' > docs/dev_tasks/fake.md", "docs/dev_tasks/fake.md"),
        ("echo 'line' >> docs/dev_tasks/fake.md", "docs/dev_tasks/fake.md"),
        (r"echo 'line' > docs\dev_tasks\fake.md", r"docs\dev_tasks\fake.md"),
        ("echo 'line' > \"docs/dev_tasks/fake.md\"", "docs/dev_tasks/fake.md"),
        ("cat <<EOF > docs/dev_tasks/fake.md", "docs/dev_tasks/fake.md"),
        ("echo 'foo' | tee docs/dev_tasks/fake.md", "docs/dev_tasks/fake.md"),
        ("echo 'foo' | tee -a docs/dev_tasks/fake.md", "docs/dev_tasks/fake.md"),
        ("Out-File -FilePath docs/dev_tasks/fake.md", "docs/dev_tasks/fake.md"),
        ("Set-Content docs/dev_tasks/fake.md 'content'", "docs/dev_tasks/fake.md"),
        ("Add-Content -Path docs/dev_tasks/fake.md -Value 'content'", "docs/dev_tasks/fake.md"),
        ("New-Item -Path docs/dev_tasks/fake.md -ItemType File", "docs/dev_tasks/fake.md"),
        ("[IO.File]::WriteAllText('docs/dev_tasks/fake.md', 'content')", "docs/dev_tasks/fake.md"),
        ("cp /tmp/evil.md docs/dev_tasks/fake.md", "docs/dev_tasks/fake.md"),
        ("mv /tmp/evil.md docs/dev_tasks/fake.md", "docs/dev_tasks/fake.md"),
        ("sed -i 's/a/b/' docs/dev_tasks/fake.md", "docs/dev_tasks/fake.md"),
    ],
)
def test_detect_shell_write_bypass_matches(cmd, expected_substr):
    ws = "/workspace"
    detected = detect_shell_write_bypass(cmd, ws, dev_tasks_dir="docs/dev_tasks")
    assert detected is not None
    assert expected_substr.replace("\\", "/") in detected.replace("\\", "/")


@pytest.mark.parametrize(
    "cmd",
    [
        "cat docs/dev_tasks/2026-09-23_task.md",
        "Get-Content docs/dev_tasks/2026-09-23_task.md",
        "grep 'TODO' docs/dev_tasks/2026-09-23_task.md",
        "git status",
        "git diff docs/dev_tasks/2026-09-23_task.md",
        "git log -n 5 docs/dev_tasks/2026-09-23_task.md",
        "ls docs/dev_tasks",
        r"dir docs\dev_tasks",
        "pytest plugins/quench-dev-tasks/server/tests -q",
        "echo 'just echoing text without redirection'",
    ],
)
def test_detect_shell_write_bypass_read_only_allowed(cmd):
    ws = "/workspace"
    detected = detect_shell_write_bypass(cmd, ws, dev_tasks_dir="docs/dev_tasks")
    assert detected is None, f"Read-only command was falsely detected: {cmd}"


def test_detect_shell_write_bypass_custom_dev_tasks_dir():
    ws = "/workspace"
    cmd_custom = "echo evil > custom_tasks/fake.md"
    detected = detect_shell_write_bypass(cmd_custom, ws, dev_tasks_dir="custom_tasks")
    assert detected is not None
    assert "custom_tasks/fake.md" in detected.replace("\\", "/")

    cmd_default = "echo evil > docs/dev_tasks/fake.md"
    # When dev_tasks_dir is custom, standard docs/dev_tasks still contains dev_tasks marker
    detected_default = detect_shell_write_bypass(cmd_default, ws, dev_tasks_dir="custom_tasks")
    assert detected_default is not None


def test_detect_shell_write_bypass_fail_closed_heuristic():
    ws = "/workspace"
    # An unusual command containing dev_tasks and write operator
    obscure_cmd = "my_custom_tool --out > docs/dev_tasks/unknown.md"
    detected = detect_shell_write_bypass(obscure_cmd, ws, dev_tasks_dir="docs/dev_tasks")
    assert detected is not None


def test_server_check_shell_write_isolation():
    ws = "/workspace"
    assert check_shell_write_isolation("echo 1 > docs/dev_tasks/fake.md", ws) is not None
    assert check_shell_write_isolation("cat docs/dev_tasks/fake.md", ws) is None


def test_hook_blocks_shell_write_redirection(tmp_path):
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text("project_name: 'TestProj'\n", encoding="utf-8")

    ws_str = str(tmp_path)

    # 1. run_command with redirection
    res1 = run_hook(FILE_GUARD, {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "echo 'malicious' > docs/dev_tasks/fake.md"},
        },
        "workspacePaths": [ws_str],
    })
    assert res1["decision"] == "deny"
    assert "Shell" in res1.get("reason", "")

    # 2. bash tool with pipe to tee
    res2 = run_hook(FILE_GUARD, {
        "toolCall": {
            "name": "bash",
            "args": {"command": "echo 'malicious' | tee docs/dev_tasks/fake.md"},
        },
        "workspacePaths": [ws_str],
    })
    assert res2["decision"] == "deny"
    assert "Shell" in res2.get("reason", "")

    # 3. Read-only command is smoothly allowed
    res_allowed = run_hook(FILE_GUARD, {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "cat docs/dev_tasks/2026-09-23_task.md"},
        },
        "workspacePaths": [ws_str],
    })
    assert res_allowed["decision"] == "allow"

    # Verify audit log recorded [DENIED]
    log_file = agents_dir / ".quench_hook.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "[DENIED]" in content
    assert "decision=deny tool=run_command" in content
