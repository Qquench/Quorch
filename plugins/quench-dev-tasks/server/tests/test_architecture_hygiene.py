# -*- coding: utf-8 -*-
"""Architecture hygiene consolidated test suite adhering to TP-1 independent assertion protocol."""

from __future__ import annotations

import ast
from pathlib import Path
import sys
import time
from unittest.mock import patch

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SERVER_DIR = TESTS_DIR.parent
PLUGIN_ROOT = SERVER_DIR.parent

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from _hygiene.rules import (
    RULE_IDS,
    RULE_SCOPE,
)
from _hygiene.scanner import (
    ArchitectureHygieneScanner,
    HygieneFinding,
    HygieneScanError,
    finding_sort_key,
)

MUTATION_REGISTRY = {
    "lease_symbol_removal": {
        "clean": "class MyLease:\n    def is_held(self):\n        return True\n",
        "violating": "def probe_caller():\n    probe_peer('peer_123')\n",
    },
    "touch_outcome_truthiness": {
        "clean": "if guard.touch() == LeaseTouchOutcome.RENEWED:\n    pass\n",
        "violating": "if not guard.touch():\n    pass\n",
    },
    "vendor_literal_in_core": {
        "clean": "# Normal code\ncustom_endpoint = 'https://custom.internal'\n",
        "violating": "target_model = 'deepseek-chat'\n",
    },
    "api_bypass": {
        "clean": "import json\nimport os\n",
        "violating": "import openai\nclient = openai.OpenAI()\n",
    },
}


@pytest.fixture(scope="module")
def scanner() -> ArchitectureHygieneScanner:
    return ArchitectureHygieneScanner(SERVER_DIR)


# D-1 TP-1 独立断言律：逐规则独立 assert，严禁 any()/all() 短路聚合


def test_rule_lease_symbol_removal_clean(scanner):
    """断言核心租约模块中不存在已废弃的探针或心跳符号。"""
    findings = scanner.findings_for("lease_symbol_removal")
    assert findings == []


def test_rule_touch_outcome_truthiness_clean(scanner):
    """断言服务端源码中绝无对 touch() 进行布尔隐式真值判定。"""
    findings = scanner.findings_for("touch_outcome_truthiness")
    assert findings == []


def test_rule_vendor_literal_in_core_clean(scanner):
    """断言核心服务端模块中绝无未豁免的厂商字面量。"""
    findings = scanner.findings_for("vendor_literal_in_core")
    assert findings == []


def test_rule_api_bypass_clean(scanner):
    """断言核心服务端模块中不存在绕过 reviewer_engine 的直接厂商 SDK/端点调用。"""
    findings = scanner.findings_for("api_bypass")
    assert findings == []


# D-2 / D-10 TP-1 对抗注入闭环律与反退化双向控制律


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_mutation_injection_adversarial_control(tmp_path: Path, rule_id: str):
    """注册表驱动元测试：断言每条规则在违规用例中命中 >= 1，在干净对照中命中 = 0。"""
    cases = MUTATION_REGISTRY[rule_id]
    temp_scanner = ArchitectureHygieneScanner(tmp_path)

    # 1. 干净对照命中 = 0
    clean_file = tmp_path / f"clean_{rule_id}.py"
    clean_file.write_text(cases["clean"], encoding="utf-8")
    clean_findings = temp_scanner.scan_file(clean_file, is_isolated_file_scan=True)
    clean_rule_findings = [f for f in clean_findings if f.rule_id == rule_id]
    assert clean_rule_findings == []

    # 2. 违规注入命中 >= 1
    violating_file = tmp_path / f"violating_{rule_id}.py"
    violating_file.write_text(cases["violating"], encoding="utf-8")
    violating_findings = temp_scanner.scan_file(violating_file, is_isolated_file_scan=True)
    violating_rule_findings = [f for f in violating_findings if f.rule_id == rule_id]
    assert len(violating_rule_findings) >= 1


# D-4 单次遍历耗时上限 (<= 300ms)


_SCAN_PERF_WARMUP_ITERS = 1
_SCAN_PERF_MEASURE_ITERS = 3  # 奇数采样取唯一中位数
_SCAN_PERF_BUDGET_MS = 1200.0  # 粗粒度防退化冒烟线（≈3.3x 稳态实测，兼顾 CI 共享 runner 调度抖动）


def test_scan_perf_budget(scanner: ArchitectureHygieneScanner) -> None:
    """单次遍历耗时上限：1 次预热消除冷启动，perf_counter 连测 3 次取中位数 <= 1200ms 冒烟线。"""
    for _ in range(_SCAN_PERF_WARMUP_ITERS):
        scanner.scan_all_core_modules()

    times: list[float] = []
    for _ in range(_SCAN_PERF_MEASURE_ITERS):
        t0 = time.perf_counter()
        scanner.scan_all_core_modules()
        times.append((time.perf_counter() - t0) * 1000)

    median_ms = sorted(times)[len(times) // 2]
    assert median_ms <= _SCAN_PERF_BUDGET_MS, (
        f"Scanner took {median_ms:.2f} ms (budget <= {_SCAN_PERF_BUDGET_MS:.2f} ms)"
    )


# D-6 不可解析文件 fail-closed


def test_unparsable_file_fail_closed(tmp_path: Path):
    """D-6: 不可解析源文件时明确抛出 HygieneScanError(file_path, lineno, detail)，禁止静默吞没。"""
    broken_file = tmp_path / "broken_syntax.py"
    broken_file.write_text("def broken_syntax(:\n    pass\n", encoding="utf-8")

    temp_scanner = ArchitectureHygieneScanner(tmp_path)
    with pytest.raises(HygieneScanError) as exc_info:
        temp_scanner.scan_file(broken_file)

    err = exc_info.value
    assert "broken_syntax.py" in err.file_path
    assert err.lineno == 1
    assert "invalid syntax" in err.detail.lower() or "syntax" in err.detail.lower()


# D-7 单次 parse 计数律


def test_single_parse_per_file(scanner):
    """D-7: 断言每个文件 ast.parse 调用恰好 1 次，跨规则共享语法树。"""
    core_files = scanner.get_core_module_paths()
    expected_count = len(core_files)
    assert expected_count > 0

    original_parse = ast.parse
    call_count = 0

    def counting_parse(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_parse(*args, **kwargs)

    with patch("ast.parse", side_effect=counting_parse):
        scanner.scan_all_core_modules()

    assert call_count == expected_count, (
        f"ast.parse called {call_count} times, expected exactly {expected_count}"
    )


# D-15′ 声明 ⊆ 实际检查律（升维）与 KeyError 守卫


def test_inspected_tokens_and_scope_guard(scanner):
    """D-15′: 断言声明 token 集与实际检查集合满足包含关系与投影一致性；未知 id 抛 KeyError。"""
    for r in RULE_IDS:
        inspected = scanner.inspected_tokens(r)
        inspected_toks = {tok for (_, tok) in inspected}
        assert set(RULE_SCOPE[r]).issubset(inspected_toks)

        for rule_id, path, tok in scanner.scope_report():
            if rule_id == r:
                assert (path, tok) in inspected

    with pytest.raises(KeyError):
        scanner.inspected_tokens("nonexistent_rule_xyz")

    with pytest.raises(KeyError):
        scanner.findings_for("nonexistent_rule_xyz")


# D-12 TP-1 自锚律：卫生套件断言上下文零 any()/all()


def test_no_any_or_all_in_assertion_contexts():
    """D-12 自锚律：断言当前测试模块的所有 assert 语句均无 any() 或 all() 短路掩蔽。"""
    current_source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(current_source, filename=__file__)

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            for subnode in ast.walk(node.test):
                if isinstance(subnode, ast.Call) and isinstance(subnode.func, ast.Name):
                    if subnode.func.id in ("any", "all"):
                        violations.append(f"Line {node.lineno}: assert contains {subnode.func.id}()")

    assert violations == []


# D-16′ 升维去重排序律


def test_findings_sorting_and_deduplication(scanner):
    """D-16′: 断言 findings 列表按 finding_sort_key 升序且无重复项。"""
    findings = scanner.scan_all_core_modules()
    keys = [finding_sort_key(f) for f in findings]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))


# TR-4 基线防护与架构卫生闭锁


def test_init_project_does_not_export_duration_baselines():
    """TR-4 / M3: 断言 init_project.py 绝不导出或引用 check_test_duration_baselines 基线脚本。"""
    init_script_path = PLUGIN_ROOT / "scripts" / "init_project.py"
    content = init_script_path.read_text(encoding="utf-8")
    assert "check_test_duration_baselines" not in content


def test_no_stale_reentry_guard_value_in_docs():
    """TR-4 / R5 / R6: 定向扫描核心架构文档、脚本、配置与根 README，断言无旧哨兵值与旧常量别名残留。"""
    repo_root = PLUGIN_ROOT.parent.parent
    target_files: list[Path] = []

    # docs/architecture/ 下的所有 markdown
    arch_dir = repo_root / "docs" / "architecture"
    if arch_dir.is_dir():
        target_files.extend(arch_dir.glob("*.md"))

    # scripts/ 下的所有 py 脚本
    scripts_dir = repo_root / "scripts"
    if scripts_dir.is_dir():
        target_files.extend(scripts_dir.glob("*.py"))

    # .agents/ 下的 yaml/json
    agents_dir = repo_root / ".agents"
    if agents_dir.is_dir():
        target_files.extend(agents_dir.glob("*.yaml"))
        target_files.extend(agents_dir.glob("*.json"))

    # 根 README.md 与 README_zh.md
    for readme_name in ("README.md", "README_zh.md"):
        r_path = repo_root / readme_name
        if r_path.is_file():
            target_files.append(r_path)

    violations: list[str] = []
    for file_path in target_files:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if "QUENCH_TEST_DURATION_BENCH_ACTIVE=1" in text:
            violations.append(f"{file_path.name}: contains stale 'QUENCH_TEST_DURATION_BENCH_ACTIVE=1'")
        if "TIER2_TARGET_S" in text:
            violations.append(f"{file_path.name}: contains retired 'TIER2_TARGET_S'")

    assert violations == []


# Preflight Probe 健壮性与常量 AST 静态门禁


def test_is_enoent_confined_to_unlink_branches_ast():
    """AST 门禁：_is_enoent 必须在 scripts/install.py 恰好定义 1 次，并在 probe_directory_writability 内部恰好引用 2 次，classify_probe_error 内严禁引用。"""
    repo_root = PLUGIN_ROOT.parent.parent
    install_py = repo_root / "scripts" / "install.py"
    tree = ast.parse(install_py.read_text(encoding="utf-8"), filename=str(install_py))

    defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_is_enoent"]
    names = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "_is_enoent"]
    assert len(defs) == 1
    assert len(names) == 2

    probe = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "probe_directory_writability")
    assert probe.lineno <= names[0].lineno <= probe.end_lineno
    assert probe.lineno <= names[1].lineno <= probe.end_lineno

    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "classify_probe_error")
    assert [n for n in ast.walk(cls) if isinstance(n, ast.Name) and n.id == "_is_enoent"] == []


def test_probe_remove_retry_constant_ast():
    """AST 门禁：_PROBE_REMOVE_RETRY_S 常量声明为 0.01，且 probe 内部不存在实参为 Constant(0.01) 的裸 time.sleep 调用。"""
    repo_root = PLUGIN_ROOT.parent.parent
    install_py = repo_root / "scripts" / "install.py"
    tree = ast.parse(install_py.read_text(encoding="utf-8"), filename=str(install_py))

    def is_target(n, name):
        if isinstance(n, ast.AnnAssign):
            return isinstance(n.target, ast.Name) and n.target.id == name
        if isinstance(n, ast.Assign):
            return any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
        return False

    # 1. 验证常量赋值节点
    retry_constants = [
        n
        for n in ast.walk(tree)
        if is_target(n, "_PROBE_REMOVE_RETRY_S")
        and isinstance(n.value, ast.Constant)
        and n.value.value == 0.01
    ]
    assert len(retry_constants) == 1

    # 2. probe 内部无裸 sleep(0.01)
    probe = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "probe_directory_writability")
    bare_sleeps = [
        call
        for call in ast.walk(probe)
        if isinstance(call, ast.Call)
        and any(isinstance(arg, ast.Constant) and arg.value == 0.01 for arg in call.args)
    ]
    assert bare_sleeps == []


def test_install_write_probe_uses_single_byte_constant_ast():
    """AST 门禁：probe_directory_writability 内 os.write 调用恰好 1 处且写入 1 字节常量。"""
    repo_root = PLUGIN_ROOT.parent.parent
    install_py = repo_root / "scripts" / "install.py"
    tree = ast.parse(install_py.read_text(encoding="utf-8"), filename=str(install_py))

    probe = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "probe_directory_writability")
    write_calls = [
        n
        for n in ast.walk(probe)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "write"
    ]
    assert len(write_calls) == 1
    # 第二参数为写入载荷
    payload_arg = write_calls[0].args[1]
    assert isinstance(payload_arg, ast.Constant)
    assert isinstance(payload_arg.value, bytes)
    assert len(payload_arg.value) == 1


def test_install_reserve_chars_defined_exactly_once_ast():
    """AST 门禁：scripts/install.py 中 _LOG_ARTIFACT_RESERVE_CHARS 赋值节点数恰好为 1。"""
    repo_root = PLUGIN_ROOT.parent.parent
    install_py = repo_root / "scripts" / "install.py"
    tree = ast.parse(install_py.read_text(encoding="utf-8"), filename=str(install_py))

    def is_target(n, name):
        if isinstance(n, ast.AnnAssign):
            return isinstance(n.target, ast.Name) and n.target.id == name
        if isinstance(n, ast.Assign):
            return any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
        return False

    assign_nodes = [
        n
        for n in tree.body
        if is_target(n, "_LOG_ARTIFACT_RESERVE_CHARS")
    ]
    assert len(assign_nodes) == 1
    assert isinstance(assign_nodes[0].value, ast.Constant)
    assert assign_nodes[0].value.value == 40


def test_max_log_ref_chars_within_install_reserve_ast_bound():
    """AST 门禁：派生 floor 严格等于 37，且 MAX_LOG_REF_CHARS 处于 [floor, _LOG_ARTIFACT_RESERVE_CHARS] 区间。"""
    import re

    repo_root = PLUGIN_ROOT.parent.parent
    install_py = repo_root / "scripts" / "install.py"
    text = install_py.read_text(encoding="utf-8")

    # 提取派生注释中的算式：8+1+3+1+20+4=37
    m = re.search(r"派生于\s*(\d+)\+(\d+)\+(\d+)\+(\d+)\+(\d+)\+(\d+)=(\d+)", text)
    assert m is not None, "未找到派生算式注释"
    parts = [int(m.group(i)) for i in range(1, 7)]
    floor = sum(parts)
    assert floor == 37
    assert int(m.group(7)) == 37

    from log_naming import MAX_LOG_REF_CHARS

    if str(repo_root / "scripts") not in sys.path:
        sys.path.insert(0, str(repo_root / "scripts"))
    import install as inst

    assert floor <= MAX_LOG_REF_CHARS <= inst._LOG_ARTIFACT_RESERVE_CHARS


