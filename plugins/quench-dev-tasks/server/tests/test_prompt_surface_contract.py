# -*- coding: utf-8 -*-
"""Unit and integration test suite for Prompt-Surface contract gate (P1~P5).

Adheres to:
- Pure AST validation without runtime server/fastmcp dependencies.
- INV-4 stdio channel purity (zero stdout print).
- C2 blackbox integration with git_pre_commit_guard.py.
- R2 anti-self-lock exclusions (docs/dev_tasks/, docs/archive/).
- R3 historical allowlist and P5 explicit exemption discipline.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SERVER_DIR = TESTS_DIR.parent
PLUGIN_ROOT = SERVER_DIR.parent
REPO_ROOT = PLUGIN_ROOT.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

PLUGIN_SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
if str(PLUGIN_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS_DIR))

import check_prompt_surface as checker
from git_pre_commit_guard import (
    QUENCH_CORE_STRONG_ANCHORS,
    PromptSurfaceOutcome,
    evaluate_prompt_surface_check,
    is_quorch_core_repo,
)
from tool_surface_constants import EXPECTED_TOOL_NAMES, TOOL_COUNT


# ---------------------------------------------------------------------------
# P1: Docstring & Args: block completeness tests
# ---------------------------------------------------------------------------

def test_p1_positive_real_server_py():
    """断言真实 server.py 的全部 MCP 工具均定义了规范的 Google-style Args: 块。"""
    server_py = SERVER_DIR / "server.py"
    findings = checker.check_docstring_args(server_py, EXPECTED_TOOL_NAMES)
    assert findings == [], f"Unexpected P1 findings in server.py: {findings}"


def test_p1_negative_missing_args_block(tmp_path: Path):
    """断言缺少 Args: 块的工具定义会产生 P1_ARGS_BLOCK_MISSING 违规。"""
    code = (
        "import fastmcp\n"
        "mcp = fastmcp.FastMCP('test')\n"
        "@mcp.tool()\n"
        "def sample_tool(workspace_root: str) -> dict:\n"
        "    '''A sample tool without Args block.'''\n"
        "    return {}\n"
    )
    fake_server = tmp_path / "server.py"
    fake_server.write_text(code, encoding="utf-8")
    findings = checker.check_docstring_args(fake_server, frozenset({"sample_tool"}))
    rules = [f.rule for f in findings]
    assert "P1_ARGS_BLOCK_MISSING" in rules


def test_p1_negative_undocumented_param(tmp_path: Path):
    """断言工具形参未在 Args: 中声明会产生 P1_PARAM_UNDOCUMENTED 违规。"""
    code = (
        "@mcp.tool()\n"
        "def sample_tool(workspace_root: str, extra_param: int) -> dict:\n"
        "    '''A sample tool.\n\n"
        "    Args:\n"
        "        workspace_root: Root path of the target workspace.\n"
        "    '''\n"
        "    return {}\n"
    )
    fake_server = tmp_path / "server.py"
    fake_server.write_text(code, encoding="utf-8")
    findings = checker.check_docstring_args(fake_server, frozenset({"sample_tool"}))
    rules = [f.rule for f in findings]
    assert "P1_PARAM_UNDOCUMENTED" in rules


def test_p1_negative_short_param_description(tmp_path: Path):
    """断言参数描述长度 < MIN_PARAM_DESC_CHARS (8) 会产生 P1_PARAM_DESC_TOO_SHORT 违规。"""
    code = (
        "@mcp.tool()\n"
        "def sample_tool(workspace_root: str) -> dict:\n"
        "    '''A sample tool.\n\n"
        "    Args:\n"
        "        workspace_root: Short\n"
        "    '''\n"
        "    return {}\n"
    )
    fake_server = tmp_path / "server.py"
    fake_server.write_text(code, encoding="utf-8")
    findings = checker.check_docstring_args(fake_server, frozenset({"sample_tool"}))
    rules = [f.rule for f in findings]
    assert "P1_PARAM_DESC_TOO_SHORT" in rules


def test_p1_negative_unknown_param_in_args(tmp_path: Path):
    """断言 Args: 中出现签名中不存在的参数会产生 P1_PARAM_UNKNOWN 违规。"""
    code = (
        "@mcp.tool()\n"
        "def sample_tool(workspace_root: str) -> dict:\n"
        "    '''A sample tool.\n\n"
        "    Args:\n"
        "        workspace_root: Root path of workspace.\n"
        "        ghost_param: An unknown parameter description.\n"
        "    '''\n"
        "    return {}\n"
    )
    fake_server = tmp_path / "server.py"
    fake_server.write_text(code, encoding="utf-8")
    findings = checker.check_docstring_args(fake_server, frozenset({"sample_tool"}))
    rules = [f.rule for f in findings]
    assert "P1_PARAM_UNKNOWN" in rules


# ---------------------------------------------------------------------------
# P2: Schema Descriptions & Envelope Freshness tests
# ---------------------------------------------------------------------------

def test_p2_positive_real_ide_schemas():
    """断言真实 docs/architecture/ide_tool_schemas.json 通过 P2 校验（0 违规）。"""
    snapshot = REPO_ROOT / "docs" / "architecture" / "ide_tool_schemas.json"
    findings = checker.check_schema_descriptions(snapshot, EXPECTED_TOOL_NAMES)
    assert findings == [], f"Unexpected P2 findings in ide_tool_schemas.json: {findings}"


def test_p2_negative_envelope_drift(tmp_path: Path):
    """断言 schema_version 漂移或缺失产生 P2_ENVELOPE_DRIFT。"""
    bad_data = {
        "_meta": {"schema_version": 999},
    }
    fake_json = tmp_path / "ide_tool_schemas.json"
    fake_json.write_text(json.dumps(bad_data), encoding="utf-8")
    findings = checker.check_schema_descriptions(fake_json, EXPECTED_TOOL_NAMES)
    rules = [f.rule for f in findings]
    assert "P2_ENVELOPE_DRIFT" in rules


def test_p2_negative_param_desc_too_short(tmp_path: Path):
    """断言参数 description 缺失或 < 8 字符产生 P2_PARAM_DESC_TOO_SHORT。"""
    bad_data = {
        "_meta": {"schema_version": 1},
        "dev_tasks_status": {
            "properties": {
                "workspace_root": {"description": "Tiny"}
            }
        }
    }
    fake_json = tmp_path / "ide_tool_schemas.json"
    fake_json.write_text(json.dumps(bad_data), encoding="utf-8")
    findings = checker.check_schema_descriptions(fake_json, frozenset({"dev_tasks_status"}))
    rules = [f.rule for f in findings]
    assert "P2_PARAM_DESC_TOO_SHORT" in rules


# ---------------------------------------------------------------------------
# P3: Live Docs Banned Keyword tests
# ---------------------------------------------------------------------------

def test_p3_positive_real_live_docs():
    """断言真实工作区中的全部活文档均无 raw_text 代码块调用残留。"""
    findings = checker.check_live_doc_call_keywords([REPO_ROOT])
    assert findings == [], f"Unexpected P3 findings in live docs: {findings}"


def test_p3_negative_keyword_leak_in_fence(tmp_path: Path):
    """断言活文档代码围栏中注入 raw_text=True 产生 P3_LIVE_DOC_KEYWORD_LEAK。"""
    live_doc = tmp_path / "docs" / "configuration.md"
    live_doc.parent.mkdir(parents=True, exist_ok=True)
    live_doc.write_text(
        "# Configuration\n\n```python\npoll_res = dev_reviewer_poll('ws', 'j1', 's1', raw_text=True)\n```\n",
        encoding="utf-8",
    )
    findings = checker.check_live_doc_call_keywords([tmp_path])
    rules = [f.rule for f in findings]
    assert "P3_LIVE_DOC_KEYWORD_LEAK" in rules


# ---------------------------------------------------------------------------
# P4: Example Call Unknown Keyword & R2 Exclusion tests
# ---------------------------------------------------------------------------

def test_p4_positive_real_docs():
    """断言真实工作区中的 Markdown 代码示例调用均为合法已知参数。"""
    server_py = SERVER_DIR / "server.py"
    sigs = checker.extract_server_signatures(server_py)
    findings = checker.check_example_call_keywords([REPO_ROOT], sigs)
    assert findings == [], f"Unexpected P4 findings across workspace: {findings}"


def test_p4_negative_unknown_keyword(tmp_path: Path):
    """断言非排除目录下的 Markdown 文件包含未知关键字产生 P4_UNKNOWN_KEYWORD。"""
    doc = tmp_path / "tutorial.md"
    doc.write_text(
        "# Guide\n\n```python\nres = dev_reviewer_poll('ws', 'job1', 'sess1', raw_text=True)\n```\n",
        encoding="utf-8",
    )
    sigs = {"dev_reviewer_poll": frozenset({"workspace_root", "job_id", "session_id", "wait_max_s"})}
    findings = checker.check_example_call_keywords([tmp_path], sigs)
    rules = [f.rule for f in findings]
    assert "P4_UNKNOWN_KEYWORD" in rules


def test_p4_exemption_marker_skips_fence(tmp_path: Path):
    """断言代码围栏首行或标签包含豁免标记时跳过该代码块。"""
    doc = tmp_path / "tutorial.md"
    doc.write_text(
        "# Guide\n\n```python <!-- quench-prompt-surface:historical -->\nres = dev_reviewer_poll('ws', 'job1', 'sess1', raw_text=True)\n```\n",
        encoding="utf-8",
    )
    sigs = {"dev_reviewer_poll": frozenset({"workspace_root", "job_id", "session_id", "wait_max_s"})}
    findings = checker.check_example_call_keywords([tmp_path], sigs)
    assert findings == []


def test_p4_r2_excluded_paths_skip(tmp_path: Path):
    """断言 docs/dev_tasks/ 与 docs/archive/ 目录下的任务单/归档天然豁免（R2 防自锁）。"""
    for folder in ("docs/dev_tasks", "docs/archive", "docs/roadmap/archive"):
        d = tmp_path / folder
        d.mkdir(parents=True, exist_ok=True)
        task_file = d / "task.md"
        task_file.write_text(
            "# Task\n\n```python\nres = dev_reviewer_poll('ws', 'job1', 'sess1', raw_text=True)\n```\n",
            encoding="utf-8",
        )
    sigs = {"dev_reviewer_poll": frozenset({"workspace_root", "job_id", "session_id", "wait_max_s"})}
    findings = checker.check_example_call_keywords([tmp_path], sigs)
    assert findings == []


# ---------------------------------------------------------------------------
# P5: Historical Allowlist Discipline tests
# ---------------------------------------------------------------------------

def test_p5_positive_real_historical_allowlist():
    """断言真实 CHANGELOG.md 与 ci_incident_tracker_and_compatibility_guide.md 满足 P5 豁免纪律。"""
    findings = checker.check_historical_allowlist_discipline([REPO_ROOT])
    assert findings == [], f"Unexpected P5 findings in historical allowlist: {findings}"


def test_p5_negative_missing_exemption_marker(tmp_path: Path):
    """断言历史白名单文件中存在 raw_text=True 但无豁免标记时触发 P5_HISTORICAL_MISSING_EXEMPTION。"""
    hist = tmp_path / "CHANGELOG.md"
    hist.write_text(
        "# Changelog\n\n- Historical entry mentioning raw_text=True without marker\n",
        encoding="utf-8",
    )
    findings = checker.check_historical_allowlist_discipline([tmp_path])
    rules = [f.rule for f in findings]
    assert "P5_HISTORICAL_MISSING_EXEMPTION" in rules


def test_p5_positive_with_preceding_exemption_marker(tmp_path: Path):
    """断言上一行存在豁免标记时合法放行。"""
    hist = tmp_path / "CHANGELOG.md"
    hist.write_text(
        "# Changelog\n\n<!-- quench-prompt-surface:historical -->\n- Historical entry mentioning raw_text=True with marker\n",
        encoding="utf-8",
    )
    findings = checker.check_historical_allowlist_discipline([tmp_path])
    assert findings == []


# ---------------------------------------------------------------------------
# Protocol Invariants & C2 Blackbox Pre-Commit Guard Integration
# ---------------------------------------------------------------------------

def test_stdout_purity_inv4(capsys: pytest.CaptureFixture):
    """断言 check_prompt_surface.py 遵循 INV-4 铁律，stdout 输出严格恒为空（输出定向 stderr）。"""
    rc = checker.main(["--check", "--workspace", str(REPO_ROOT)])
    captured = capsys.readouterr()
    assert captured.out == "", f"INV-4 violation: stdout must be empty, got {captured.out!r}"
    assert rc == 0


def test_is_quorch_core_repo_anchor_matrix(tmp_path: Path):
    """白盒矩阵断言：is_quorch_core_repo 对各类锚点存在性的判定。"""
    # 1. 真实核心仓库必定返回 True
    assert is_quorch_core_repo(REPO_ROOT) is True

    # 2. 空目录判定为 False (downstream)
    empty_dir = tmp_path / "empty_repo"
    empty_dir.mkdir()
    assert is_quorch_core_repo(empty_dir) is False

    # 3. 仅包含 vendored 插件路径的下游目录（非强锚点）判定为 False
    vendored_dir = tmp_path / "vendored_repo"
    vendored_guard = vendored_dir / "plugins" / "quench-dev-tasks" / "scripts" / "git_pre_commit_guard.py"
    vendored_guard.parent.mkdir(parents=True, exist_ok=True)
    vendored_guard.write_text("# Mock vendored guard\n", encoding="utf-8")
    assert is_quorch_core_repo(vendored_dir) is False

    # 4. 单强锚点 (scripts/check_prompt_surface.py) 判定为 True (core)
    single_dir_1 = tmp_path / "single_anchor_1"
    (single_dir_1 / "scripts").mkdir(parents=True)
    (single_dir_1 / "scripts" / "check_prompt_surface.py").write_text("", encoding="utf-8")
    assert is_quorch_core_repo(single_dir_1) is True

    # 5. 另一单强锚点 (docs/architecture/ide_tool_schemas.json) 判定为 True (core)
    single_dir_2 = tmp_path / "single_anchor_2"
    (single_dir_2 / "docs" / "architecture").mkdir(parents=True)
    (single_dir_2 / "docs" / "architecture" / "ide_tool_schemas.json").write_text("{}", encoding="utf-8")
    assert is_quorch_core_repo(single_dir_2) is True

    # 6. 全强锚点判定为 True (core)
    full_dir = tmp_path / "full_core_repo"
    for anchor in QUENCH_CORE_STRONG_ANCHORS:
        p = full_dir / anchor
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    assert is_quorch_core_repo(full_dir) is True


def test_evaluate_prompt_surface_check_downstream_skip_even_if_changed_paths_none(tmp_path: Path):
    """断言下游工程在各种变更集输入下（包括 None）恒定透明返回 SKIP。"""
    downstream_dir = tmp_path / "downstream_test"
    downstream_dir.mkdir()

    # 1. changed_paths 为 None 时，下游工程依然首行短路返回 SKIP（而非 GUARD_ERROR）
    assert evaluate_prompt_surface_check(None, repo_root=downstream_dir) == PromptSurfaceOutcome.SKIP

    # 2. changed_paths 命中 *.md 时，下游工程返回 SKIP（零开销透明放行）
    assert evaluate_prompt_surface_check(["README.md", "docs/guide.md"], repo_root=downstream_dir) == PromptSurfaceOutcome.SKIP

    # 3. changed_paths 命中 PROMPT_SURFACE_TRIGGER_PATHS 时，下游工程返回 SKIP
    assert evaluate_prompt_surface_check(["docs/architecture/ide_tool_schemas.json"], repo_root=downstream_dir) == PromptSurfaceOutcome.SKIP


def test_c2_git_pre_commit_guard_blackbox_intercept(tmp_path: Path):
    """断言 C2 黑盒接线：在核心仓库（含强锚点）预置违规 Markdown，subprocess 运行 git_pre_commit_guard.py，断言退出码非 0。"""
    guard_script = PLUGIN_ROOT / "scripts" / "git_pre_commit_guard.py"
    checker_script = SCRIPTS_DIR / "check_prompt_surface.py"

    # 建立临时 git 仓库与 quench_stack.yaml
    repo_dir = tmp_path / "temp_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), capture_output=True, check=True)

    agents_dir = repo_dir / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "quench_stack.yaml").write_text("project_name: test\ndev_tasks_dir: docs/dev_tasks\n", encoding="utf-8")

    # 拷贝必要的守卫与检查脚本（具备强锚点 scripts/check_prompt_surface.py）
    temp_scripts = repo_dir / "scripts"
    temp_scripts.mkdir(parents=True, exist_ok=True)
    temp_checker = temp_scripts / "check_prompt_surface.py"
    temp_checker.write_text(checker_script.read_text(encoding="utf-8"), encoding="utf-8")

    # 创建违规活文档 (例如 docs/configuration.md 含有 raw_text=True 代码围栏)
    conf_doc = repo_dir / "docs" / "configuration.md"
    conf_doc.parent.mkdir(parents=True, exist_ok=True)
    conf_doc.write_text(
        "# Configuration\n\n```python\npoll_res = dev_reviewer_poll('ws', 'j1', 's1', raw_text=True)\n```\n",
        encoding="utf-8",
    )
    # git add 暂存违规文件
    subprocess.run(["git", "add", "docs/configuration.md"], cwd=str(repo_dir), capture_output=True, check=True)

    # subprocess 运行 git_pre_commit_guard.py
    res = subprocess.run(
        [sys.executable, str(guard_script), "--workspace", str(repo_dir)],
        cwd=str(repo_dir),
        capture_output=True,
    )
    assert res.returncode == 1, f"Pre-commit guard must intercept violation with code 1, got {res.returncode}. Stderr: {res.stderr.decode('utf-8', errors='ignore')}"
    assert "Prompt Surface" in res.stderr.decode("utf-8", errors="ignore")


def test_c2_git_pre_commit_guard_downstream_passthrough(tmp_path: Path):
    """断言下游业务工程即使暂存了 Markdown 文件，Prompt Surface 门禁也透明降级 SKIP 并放行（exit code == 0）。"""
    guard_script = PLUGIN_ROOT / "scripts" / "git_pre_commit_guard.py"

    repo_dir = tmp_path / "downstream_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Downstream User"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "downstream@example.com"], cwd=str(repo_dir), capture_output=True, check=True)

    agents_dir = repo_dir / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "quench_stack.yaml").write_text("project_name: downstream\ndev_tasks_dir: docs/dev_tasks\n", encoding="utf-8")

    # 模拟下游工程 vendored 了 quench 插件脚本（非强锚点）
    vendored_guard = repo_dir / "plugins" / "quench-dev-tasks" / "scripts" / "git_pre_commit_guard.py"
    vendored_guard.parent.mkdir(parents=True, exist_ok=True)
    vendored_guard.write_text("# vendored\n", encoding="utf-8")

    # 下游工程暂存 Markdown 文件（即使包含 prompt surface 关键词）
    doc = repo_dir / "docs" / "user_guide.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# Downstream Doc\n\n```python\nraw_text=True\n```\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/user_guide.md"], cwd=str(repo_dir), capture_output=True, check=True)

    # subprocess 运行 git_pre_commit_guard.py
    res = subprocess.run(
        [sys.executable, str(guard_script), "--workspace", str(repo_dir)],
        cwd=str(repo_dir),
        capture_output=True,
    )
    assert res.returncode == 0, (
        f"Downstream repo must skip prompt surface check and exit 0, got {res.returncode}. "
        f"Stderr: {res.stderr.decode('utf-8', errors='ignore')}"
    )


def test_c2_git_pre_commit_guard_half_core_still_blocks(tmp_path: Path):
    """断言半核心场景：存在强锚点（判为 core）但 check_prompt_surface.py 缺失时 fail-closed 阻断（exit code != 0）。"""
    guard_script = PLUGIN_ROOT / "scripts" / "git_pre_commit_guard.py"

    repo_dir = tmp_path / "half_core_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), capture_output=True, check=True)

    agents_dir = repo_dir / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "quench_stack.yaml").write_text("project_name: test\ndev_tasks_dir: docs/dev_tasks\n", encoding="utf-8")

    # 放置单一强锚点使之被判定为 core 宿主
    schema_anchor = repo_dir / "docs" / "architecture" / "ide_tool_schemas.json"
    schema_anchor.parent.mkdir(parents=True, exist_ok=True)
    schema_anchor.write_text("{}", encoding="utf-8")

    # 暂存违规 Markdown 文档
    conf_doc = repo_dir / "docs" / "configuration.md"
    conf_doc.parent.mkdir(parents=True, exist_ok=True)
    conf_doc.write_text("# Test\n\n```python\nraw_text=True\n```\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/configuration.md"], cwd=str(repo_dir), capture_output=True, check=True)

    # 运行守卫脚本：因为判为 core 但缺少 check_prompt_surface.py 脚本且无法 import，fail-closed 返回 UNVERIFIABLE 阻断 (rc != 0)
    res = subprocess.run(
        [sys.executable, str(guard_script), "--workspace", str(repo_dir)],
        cwd=str(repo_dir),
        capture_output=True,
    )
    assert res.returncode != 0, f"Half-core repo must fail-closed and block commit, got {res.returncode}"


def test_constants_immutability():
    """断言历史白名单与排除前缀受单测锚定且为不可变集合。"""
    assert isinstance(checker.HISTORICAL_ALLOWLIST, frozenset)
    assert "CHANGELOG.md" in checker.HISTORICAL_ALLOWLIST
    assert "docs/ci_incident_tracker_and_compatibility_guide.md" in checker.HISTORICAL_ALLOWLIST

    assert isinstance(checker.EXCLUDED_PATH_PREFIXES, tuple)
    assert "docs/dev_tasks/" in checker.EXCLUDED_PATH_PREFIXES
    assert "docs/archive/" in checker.EXCLUDED_PATH_PREFIXES
