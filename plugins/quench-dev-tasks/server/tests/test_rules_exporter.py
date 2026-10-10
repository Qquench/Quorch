import os
from pathlib import Path
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

from rules_exporter import RulesExporter, DEFAULT_FALLBACK_RULES

PYTHON_EXE = sys.executable
EXPORTER_SCRIPT = os.path.join(SCRIPTS_DIR, "rules_exporter.py")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent




def test_resolve_discipline_path_default():
    """测试默认路径自动解析能够正确定位到插件目录下的 dev-tasks-discipline.md"""
    resolved = RulesExporter.resolve_discipline_path(None)
    assert resolved != ""
    assert os.path.isfile(resolved)
    assert resolved.endswith("dev-tasks-discipline.md")


def test_resolve_discipline_path_invalid_fallback():
    """测试当指定不存在的文件时返回空，且提取器平滑启用兜底模板"""
    resolved = RulesExporter.resolve_discipline_path("non_existent_discipline_xyz.md")
    assert resolved == ""

    rules = RulesExporter.extract_condensed_rules("non_existent_discipline_xyz.md")
    assert "核心常驻开发纪律" in rules
    assert "未检出任务" in rules
    assert "call_mcp_tool" in rules
    assert "bypass MCP" in rules or "绕过 MCP" in rules


def test_extract_condensed_rules_real_content():
    """测试从实际 discipline 文件中提炼的核心三板斧纪律"""
    rules = RulesExporter.extract_condensed_rules(None)
    assert "未领单严禁动源码" in rules or "未检出任务" in rules
    assert "涉及文件" in rules
    assert "单测断言" in rules or "单测" in rules
    assert "Pre-commit" in rules
    assert "call_mcp_tool" in rules
    assert "Zero CLI Bypass" in rules or "绕过 MCP" in rules


def test_export_cursorrules_and_mdc(tmp_path):
    """测试输出 .cursorrules 与 .cursor/rules/quench-dev-tasks.mdc"""
    proj_dir = str(tmp_path / "rules_proj")
    os.makedirs(proj_dir, exist_ok=True)

    results = RulesExporter.export_all(project_root=proj_dir)

    legacy_path = results["cursorrules"]
    mdc_path = results["cursor_mdc"]

    assert os.path.isfile(legacy_path)
    assert os.path.isfile(mdc_path)

    # 检查 .cursorrules
    with open(legacy_path, "r", encoding="utf-8") as f:
        legacy_content = f.read()
    assert "Quench" in legacy_content
    assert "call_mcp_tool" in legacy_content
    assert "Zero CLI Bypass" in legacy_content or "绕过 MCP" in legacy_content
    assert "---" not in legacy_content[:10]  # legacy rules 无需 YAML frontmatter

    # 检查 .cursor/rules/*.mdc
    with open(mdc_path, "r", encoding="utf-8") as f:
        mdc_content = f.read()
    assert mdc_content.startswith("---\n")
    assert "alwaysApply: true" in mdc_content
    assert 'globs: "*"' in mdc_content
    assert "Quench" in mdc_content
    assert "call_mcp_tool" in mdc_content
    assert "Zero CLI Bypass" in mdc_content or "绕过 MCP" in mdc_content


def test_export_idempotent_and_force(tmp_path):
    """测试默认跳过已有文件，--force 强制覆盖"""
    proj_dir = str(tmp_path / "rules_idempotent_proj")
    os.makedirs(proj_dir, exist_ok=True)

    legacy_path = os.path.join(proj_dir, ".cursorrules")
    with open(legacy_path, "w", encoding="utf-8") as f:
        f.write("custom user rules\n")

    # 1. 默认 force=False，不应被覆盖
    RulesExporter.export_cursorrules(None, legacy_path, force=False)
    with open(legacy_path, "r", encoding="utf-8") as f:
        assert f.read() == "custom user rules\n"

    # 2. force=True，应被覆盖为 Quench 规范
    RulesExporter.export_cursorrules(None, legacy_path, force=True)
    with open(legacy_path, "r", encoding="utf-8") as f:
        overwritten = f.read()
    assert "custom user rules" not in overwritten
    assert "Quench" in overwritten


def test_rules_exporter_cli(tmp_path):
    """测试 rules_exporter CLI 命令行执行生成"""
    proj_dir = str(tmp_path / "cli_rules_proj")
    os.makedirs(proj_dir, exist_ok=True)

    p = subprocess.run(
        [PYTHON_EXE, EXPORTER_SCRIPT, "--dest", proj_dir, "--force"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert p.returncode == 0
    assert "规则导出已顺利完成" in p.stdout

    assert os.path.isfile(os.path.join(proj_dir, ".cursorrules"))
    assert os.path.isfile(os.path.join(proj_dir, ".cursor", "rules", "quench-dev-tasks.mdc"))





def test_discipline_rules_zero_delete_symbols_preserved() -> None:
    """物理断言六核心字段双语标题与 INV-1~INV-9 符号名在精简后完好存在（Zero-Delete 不变量）。"""
    discipline_path = REPO_ROOT / "plugins" / "quench-dev-tasks" / "rules" / "dev-tasks-discipline.md"
    assert discipline_path.is_file()
    content = discipline_path.read_text(encoding="utf-8")

    six_fields = (
        ("【任务目标】", "Objective"),
        ("【上下文与现状】", "Context & Status"),
        ("【涉及文件】", "Touched Files"),
        ("【改动计划】", "Implementation Plan"),
        ("【单测断言】", "Unit Test Assertions"),
        ("【交付物与验证】", "Deliverables & Verification"),
    )
    for zh, en in six_fields:
        assert zh in content, f"Zero-delete violation: {zh} missing from discipline rules"
        assert en in content, f"Zero-delete violation: {en} missing from discipline rules"

    for i in range(1, 10):
        inv_marker = f"INV-{i}"
        assert inv_marker in content, f"Zero-delete violation: {inv_marker} missing from discipline rules"


def test_robust_baseline_edge_cases() -> None:
    """断言 robust_baseline 严格锚定 statistics.median 并在非法/边界样本时 fail-closed。"""
    import sys
    scripts_dir = REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from check_test_duration_baselines import robust_baseline

    assert robust_baseline([10.0, 20.0, 30.0]) == 20.0
    assert robust_baseline([5.0, 100.0, 5.0, 6.0]) == 5.5
    for invalid in ([float("nan")], [0.0], [-1.0], [float("inf")], []):
        with pytest.raises(ValueError):
            robust_baseline(invalid)

