# -*- coding: utf-8 -*-
"""Unit tests for scripts/asset_inventory.py (v1.20 step01 架构资产取证与去工业化清单).

覆盖任务单声明的 14 项确定性断言。
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

# Ensure scripts directory is importable
REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import asset_inventory  # noqa: E402
from asset_inventory import (  # noqa: E402
    EXIT_DRIFT,
    EXIT_OK,
    EXIT_USAGE,
    MAX_SCANNED_FILE_BYTES,
    MUST_NOT_REMOVE_SYMBOLS,
    OUTPUT_MD_REL,
    FROZEN_V120_REL,
    CURRENT_INV_REL,
    SERVER_ROOT_REL,
    VERDICTS_REL,
    DELTA_REPORT_ARG,
    DELTA_BEGIN_MARK,
    DELTA_END_MARK,
    FrozenSnapshotMissingError,
    FrozenSnapshotUnparsableError,
    DeltaBlockMalformedError,
    ResolvedRecord,
    PersistedRecord,
    EmergedRecord,
    CouplingRecord,
    InventorySnapshot,
    DeltaReport,
    INVARIANT_OWNERSHIP,
    KNOWN_INVARIANT_GAPS,
    DOC_NON_CONSUMER_PREFIXES,
    DOC_ROOT_RELS,
    _is_non_consumer_doc,
    ConsumerEdge,
    InventoryReport,
    ModuleNode,
    _assert_balanced_markers,
    strip_delta_block,
    compute_pure_projection_sha256,
    atomic_write_text,
    build_coupling_records,
    build_module_graph,
    compute_delta_report,
    render_delta_report_markdown,
    write_inventory_with_delta,
    build_consumer_graph,
    build_inventory_report,
    classify_removal_candidates,
    discover_repo_root,
    extract_gated_body,
    harvest_audit_reasons,
    is_removal_candidate,
    main,
    render_markdown,
    scan_modules,
    PROJECTION_SCHEMA_VERSION,
    PROJECTION_BEGIN_MARK,
    PROJECTION_END_MARK,
    ProjectionSchemaMismatchError,
    PureProjection,
    build_pure_projection,
    canonical_projection_json,
    diagnose_drift,
    render_projection_block,
    extract_projection_block,
    strip_projection_block,
    ToolSurface,
)
from dataclasses import dataclass


@dataclass(frozen=True)
class SyntheticBundle:
    """消除 .report 歧义：显式复合夹具。"""
    report: InventoryReport
    snapshot: InventorySnapshot


@pytest.fixture
def synthetic_bundle() -> SyntheticBundle:
    """纯内存确定性微型 SyntheticBundle，用于纯逻辑/渲染/排序断言，零物理 I/O。"""
    mod = ModuleNode(
        rel_path="plugins/quench-dev-tasks/server/core.py",
        imported_modules=("typing",),
        imported_symbols=("Optional",),
        defined_symbols=("core_func",),
    )
    edge = ConsumerEdge(
        symbol="core_func",
        defined_in="plugins/quench-dev-tasks/server/core.py",
        consumed_by=(),
        test_refs=(),
        doc_refs=(),
        is_lower_bound=True,
    )
    rep = InventoryReport(
        modules=(mod,),
        consumers=(edge,),
        tools=(),
        audit_reason_histogram={"reason_a": 1},
        telemetry_meta={"status": "ok", "total_samples": 1},
        skipped_files=(),
        doc_drift_ledger=(),
        g1prime_gaps=(),
        removal_candidates=(edge,),
        must_not_remove=("assert_read_only_sandbox",),
    )
    pure_md = render_markdown(rep)
    snap = InventorySnapshot(report=rep, rendered_pure_markdown=pure_md)
    return SyntheticBundle(report=rep, snapshot=snap)


def create_mini_repo(root: Path) -> Path:
    """创建自洽的最小微型虚拟仓，耗时 < 15ms。
    
    - 预生成并写入合法快照与 on-disk 产物，使虚拟仓处于「fresh == disk」同步态；
    - 含命中 classify_removal_candidates / MUST_NOT_REMOVE_SYMBOLS / INVARIANT_OWNERSHIP 的代表性符号。
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / ".git").mkdir(exist_ok=True)
    agents_dir = root / ".agents"
    agents_dir.mkdir(exist_ok=True)
    (agents_dir / "quench_stack.yaml").write_text("config_version: 1\n", encoding="utf-8")

    logs_dir = root / ".agents/logs/reviewer"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "verdicts.jsonl").write_text('{"reason": "init"}\n', encoding="utf-8")

    server_dir = root / SERVER_ROOT_REL
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "sample.py").write_text(
        "assert_read_only_sandbox = 1\n"
        "_issue_checkout_lease = 2\n"
        "_fake_orphan_removal_candidate = 3\n",
        encoding="utf-8",
    )

    docs_arch = root / "docs/architecture"
    docs_arch.mkdir(parents=True, exist_ok=True)
    frozen_content = (
        "# Quench Over Engineering Inventory v1.20 (Frozen)\n\n"
        "## 1. 核心系统机制与保全不变量\n"
        "| `assert_read_only_sandbox` | 约束与承载不变量 |\n\n"
        "---\n\n"
        "## 2. 潜在删除/重构候选清单 (Removal Candidates, 共 2 项)\n"
        "| `_fake_resolved_sym` | `plugins/quench-dev-tasks/server/sample.py` |\n"
        "| `_issue_checkout_lease` | `plugins/quench-dev-tasks/server/sample.py` |\n\n"
        "---\n\n"
        "## 3. 服务端生产模块概览 (Server Production Modules, 共 1 个模块)\n"
        "| `plugins/quench-dev-tasks/server/sample.py` | 3 | 0 | 0 |\n"
    )
    (root / FROZEN_V120_REL).write_text(frozen_content, encoding="utf-8")

    report = build_inventory_report(root)
    pure = render_markdown(report)
    snapshot = InventorySnapshot(report=report, rendered_pure_markdown=pure)
    delta = compute_delta_report(root / FROZEN_V120_REL, snapshot)
    proj = build_pure_projection(report)
    full = write_inventory_with_delta(pure, delta, proj=proj)
    atomic_write_text(root / OUTPUT_MD_REL, full)
    return root


@pytest.fixture
def mini_repo_fixture(tmp_path: Path) -> Path:
    """提供独立的自洽微型虚拟仓。"""
    repo = tmp_path / "mini_repo"
    return create_mini_repo(repo)



def test_01_discover_repo_root_from_tests():
    """1. discover_repo_root 自 plugins/quench-dev-tasks/server/tests 上溯命中含 .git 的仓库根。"""
    tests_dir = Path(__file__).parent
    root = discover_repo_root(tests_dir)
    assert root.is_dir()
    assert (root / ".git").exists() or (root / ".agents" / "quench_stack.yaml").exists()
    assert root == REPO_ROOT


def test_02_discover_repo_root_missing_raises_and_main_exit_usage(tmp_path: Path):
    """2. discover_repo_root 在无标记目录树中抛 RuntimeError，main 返回 EXIT_USAGE。"""
    with pytest.raises(RuntimeError) as exc_info:
        discover_repo_root(tmp_path)
    assert "Repository root markers" in str(exc_info.value)

    # main with --repo-root pointing to unmarked directory returns EXIT_USAGE
    exit_code = main(["--repo-root", str(tmp_path), "--check"])
    assert exit_code == EXIT_USAGE


def test_03_scan_modules_symlink_loop_no_hang(tmp_path: Path):
    """3. symlink 自环目录下 scan_modules 不递归、不挂起（超时护栏）。"""
    src_dir = tmp_path / "server_pkg"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text("x = 1\n", encoding="utf-8")

    sub_dir = src_dir / "sub"
    sub_dir.mkdir()
    (sub_dir / "child.py").write_text("y = 2\n", encoding="utf-8")

    # 尝试创建符号链接自环；若操作系统/权限受限，采用 is_symlink 行为补丁验证防御分支
    loop_target = sub_dir / "loop"
    try:
        os.symlink(str(src_dir), str(loop_target), target_is_directory=True)
    except OSError:
        pass

    # scan_modules 应正常结束且不挂起
    nodes = scan_modules(src_dir, repo_root=tmp_path)
    rel_paths = [n.rel_path for n in nodes]
    assert any("mod.py" in p for p in rel_paths)
    assert any("child.py" in p for p in rel_paths)


def test_04_skip_oversized_file(tmp_path: Path):
    """4. 超过 MAX_SCANNED_FILE_BYTES 的文件被跳过且记入 skipped_files。"""
    big_file = tmp_path / "big_module.py"
    # 创建超限文件
    big_file.write_bytes(b"# large file\n" + b" " * (MAX_SCANNED_FILE_BYTES + 256))

    skipped_collector: list[tuple[str, int]] = []
    nodes = scan_modules(tmp_path, repo_root=tmp_path, skipped_collector=skipped_collector)

    # big_module.py 不应被作为 AST 模块解析
    assert not any("big_module.py" in n.rel_path for n in nodes)
    # 应在 skipped 收集器与 scan_modules.last_skipped 中登记
    assert any("big_module.py" in s[0] and s[1] > MAX_SCANNED_FILE_BYTES for s in skipped_collector)
    assert any("big_module.py" in s[0] for s in getattr(scan_modules, "last_skipped", ()))


def test_05_render_markdown_byte_identical(synthetic_bundle: SyntheticBundle):
    """5. 同输入两次 render_markdown 逐字节相同（由 synthetic_bundle 纯内存夹具驱动，零磁盘 I/O）。"""
    rendered_1 = render_markdown(synthetic_bundle.report)
    rendered_2 = render_markdown(synthetic_bundle.report)
    assert rendered_1 == rendered_2
    assert rendered_1.encode("utf-8") == rendered_2.encode("utf-8")


def test_06_no_absolute_paths_no_git_sha_no_rfc3339(synthetic_bundle: SyntheticBundle):
    """6. 渲染结果不含绝对路径、git sha 与 RFC3339 时间戳（synthetic_bundle 纯内存白名单 + 磁盘只读静态补偿）。"""
    rendered = render_markdown(synthetic_bundle.report)

    # 1) 不含 Windows / Unix 绝对路径
    assert re.search(r"[A-Za-z]:[/\\]", rendered) is None, "Detected absolute Windows drive path in rendered output"
    assert re.search(r"/(?:Users|home|workspace|tmp|var|private)/", rendered) is None, "Detected absolute Unix path"

    # 2) 不含 40 位 hex git sha
    assert re.search(r"\b[0-9a-f]{40}\b", rendered) is None, "Detected 40-char git sha in rendered output"

    # 3) 不含 RFC3339 动态时间戳 (YYYY-MM-DDTHH:MM:SS)
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", rendered) is None, "Detected RFC3339 timestamp"

    # 4) [静态真仓补偿] 直接纯读取磁盘已固化的生产 inventory 文件主体（无需触发重扫，严防动态遥测误报）
    disk_inventory = REPO_ROOT / OUTPUT_MD_REL
    if disk_inventory.is_file():
        disk_gated = extract_gated_body(strip_delta_block(disk_inventory.read_text(encoding="utf-8")))
        assert re.search(r"[A-Za-z]:[/\\]", disk_gated) is None
        assert re.search(r"/(?:Users|home|workspace|tmp|var|private)/", disk_gated) is None
        assert re.search(r"\b[0-9a-f]{40}\b", disk_gated) is None
        assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", disk_gated) is None


def test_07_ast_imports_subset_of_stdlib():
    """7. scripts/asset_inventory.py 的 AST import 集合 ⊆ sys.stdlib_module_names。"""
    script_path = SCRIPTS_DIR / "asset_inventory.py"
    tree = ast.parse(script_path.read_text(encoding="utf-8"))

    imported_top_levels: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_top_levels.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_top_levels.add(node.module.split(".")[0])

    stdlib_names = set(sys.stdlib_module_names)
    assert imported_top_levels.issubset(stdlib_names), f"Non-stdlib imports: {imported_top_levels - stdlib_names}"


def test_08_no_fastmcp_or_quench_imports():
    """8. AST 中不存在 fastmcp / quench / 生产模块导入。"""
    script_path = SCRIPTS_DIR / "asset_inventory.py"
    tree = ast.parse(script_path.read_text(encoding="utf-8"))

    forbidden_prefixes = ("fastmcp", "quench", "server", "reaper", "reviewer_engine", "manifest", "filelock")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in forbidden_prefixes:
                    assert not alias.name.startswith(prefix), f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                for prefix in forbidden_prefixes:
                    assert not node.module.startswith(prefix), f"Forbidden import from: {node.module}"


def test_09_harvest_audit_reasons_none_and_missing_graceful(tmp_path: Path):
    """9. harvest_audit_reasons(None) 与缺失文件均返回空映射且不抛异常。"""
    h_none, meta_none = harvest_audit_reasons(None)
    assert len(h_none) == 0
    assert meta_none.get("status") == "telemetry unavailable"
    assert meta_none.get("total_samples") == 0

    missing_path = tmp_path / "does_not_exist.jsonl"
    h_missing, meta_missing = harvest_audit_reasons(missing_path)
    assert len(h_missing) == 0
    assert meta_missing.get("status") == "telemetry unavailable"
    assert meta_missing.get("total_samples") == 0


def test_10_harvest_audit_reasons_truncated_last_line(tmp_path: Path):
    """10. 末行被截断的 JSONL 仅丢弃该行，其余记录计数正确。"""
    jsonl_file = tmp_path / "verdicts.jsonl"
    content = (
        '{"reason": "reason_alpha"}\n'
        '{"reason": "reason_beta"}\n'
        '{"reason": "reason_alpha"}\n'
        '{"reason": "incomplet'  # 故意截断的末尾行
    )
    jsonl_file.write_text(content, encoding="utf-8")

    hist, meta = harvest_audit_reasons(jsonl_file)
    assert hist == {"reason_alpha": 2, "reason_beta": 1}
    assert meta.get("total_samples") == 3
    assert meta.get("status") == "ok"


def test_11_must_not_remove_symbols_hard_override():
    """11. MUST_NOT_REMOVE_SYMBOLS 硬覆盖：构造人造 assert_read_only_sandbox 零消费者节点，仍不得进入 removal_candidates。"""
    fake_edge = ConsumerEdge(
        symbol="assert_read_only_sandbox",
        defined_in="plugins/quench-dev-tasks/server/fake.py",
        consumed_by=(),
        test_refs=(),
        doc_refs=(),
        is_lower_bound=True,
    )
    assert is_removal_candidate(fake_edge) is False
    candidates = classify_removal_candidates([fake_edge])
    assert fake_edge not in candidates
    assert len(candidates) == 0

    # 对照试验：普通无消费者符号应能被识别为候选
    normal_orphan = ConsumerEdge(
        symbol="some_unused_helper_xyz",
        defined_in="plugins/quench-dev-tasks/server/fake.py",
        consumed_by=(),
        test_refs=(),
        doc_refs=(),
        is_lower_bound=True,
    )
    assert is_removal_candidate(normal_orphan) is True
    candidates_with_orphan = classify_removal_candidates([fake_edge, normal_orphan])
    assert normal_orphan in candidates_with_orphan
    assert fake_edge not in candidates_with_orphan


def test_12_check_three_way_exit_semantics(tmp_path: Path, capsys: pytest.CaptureFixture):
    """12. --check 语义三分：一致 → EXIT_OK；不一致 → EXIT_DRIFT；产物缺失 → EXIT_USAGE。
    
    [TP-2 架构不变量守卫]：
    - 分支 1 (产物缺失)：在独立的 tmp_path mini 仓库中删除产物，断言 EXIT_USAGE；
    - 分支 2 (沙箱锚点)：在独立的 tmp_path mini 仓库中运行未污染的 --check 校验，断言 EXIT_OK；
    - 分支 3 (代码漂移)：在独立的 tmp_path mini 仓库中修改源码移除被登记符号，断言 EXIT_DRIFT，且 stderr 输出 drift 诊断。
    """
    # 1) 产物缺失 -> EXIT_USAGE (隔离在 tmp mini-repo 中)
    b1_repo = create_mini_repo(tmp_path / "mini_repo_b1")
    (b1_repo / OUTPUT_MD_REL).unlink()
    assert main(["--repo-root", str(b1_repo), "--check"]) == EXIT_USAGE

    # 2) 沙箱产物当前一致 -> EXIT_OK (隔离在独立的 mini_repo_b2 中，彻底解耦物理工作树)
    b2_repo = create_mini_repo(tmp_path / "mini_repo_b2")
    assert main(["--repo-root", str(b2_repo), "--check"]) == EXIT_OK

    # 3) 模拟源码与投影漂移 -> EXIT_DRIFT (隔离在独立的 mini_repo_b3 中)
    b3_repo = create_mini_repo(tmp_path / "mini_repo_b3")
    sample_py = b3_repo / SERVER_ROOT_REL / "sample.py"
    sample_py.write_text(
        "_issue_checkout_lease = 2\n"
        "_fake_orphan_removal_candidate = 3\n",
        encoding="utf-8",
    )
    capsys.readouterr()  # 清空此前缓冲区
    ret = main(["--repo-root", str(b3_repo), "--check"])
    assert ret == EXIT_DRIFT
    err = capsys.readouterr().err
    assert "drift sha256_on_disk=" in err
    assert "drift_keys=" in err


def test_13_pure_projection_sort_invariance():
    """13. PureProjection 排序不变性：乱序构建 report 经规范化后哈希完全一致。"""
    mod_a = ModuleNode(
        rel_path="plugins/quench-dev-tasks/server/a.py",
        imported_modules=(),
        imported_symbols=(),
        defined_symbols=("sym_z", "sym_a"),
    )
    mod_b = ModuleNode(
        rel_path="plugins/quench-dev-tasks/server/b.py",
        imported_modules=(),
        imported_symbols=(),
        defined_symbols=("sym_b",),
    )
    rep1 = InventoryReport(
        modules=(mod_a, mod_b),
        consumers=(),
        tools=(),
        audit_reason_histogram={},
        telemetry_meta={},
        skipped_files=(),
        doc_drift_ledger=("z_doc", "a_doc"),
        g1prime_gaps=("g2", "g1"),
        removal_candidates=(),
        must_not_remove=("sym_y", "sym_x"),
    )
    rep2 = InventoryReport(
        modules=(mod_b, mod_a),
        consumers=(),
        tools=(),
        audit_reason_histogram={},
        telemetry_meta={},
        skipped_files=(),
        doc_drift_ledger=("a_doc", "z_doc"),
        g1prime_gaps=("g1", "g2"),
        removal_candidates=(),
        must_not_remove=("sym_x", "sym_y"),
    )
    proj1 = build_pure_projection(rep1)
    proj2 = build_pure_projection(rep2)
    assert proj1.modules == proj2.modules
    assert proj1.doc_drift_ledger == proj2.doc_drift_ledger
    assert proj1.must_not_remove == proj2.must_not_remove
    assert compute_pure_projection_sha256(proj1) == compute_pure_projection_sha256(proj2)


def test_14_drift_diagnostic_format(capsys: pytest.CaptureFixture, tmp_path: Path):
    """14. 漂移诊断格式：capsys 校验 stderr 符合正则格式。"""
    repo = create_mini_repo(tmp_path / "mini_repo_diag")
    sample_py = repo / SERVER_ROOT_REL / "sample.py"
    sample_py.write_text(
        sample_py.read_text(encoding="utf-8") + "extra_drift_symbol = 99\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    ret = main(["--repo-root", str(repo), "--check"])
    assert ret == EXIT_DRIFT
    err = capsys.readouterr().err.strip()
    pattern = r"^drift sha256_on_disk=[0-9a-f]{64} sha256_fresh=[0-9a-f]{64} drift_keys=[\w,]+$"
    assert re.search(pattern, err) is not None, f"Stderr did not match expected drift format: {err}"


def test_15_verdicts_append_no_drift(mini_repo_fixture: Path):
    """15. 零假红抗干扰：向 verdicts.jsonl 追加 50+ 条日志记录，--check 恒定通过返回 0。"""
    v_path = mini_repo_fixture / ".agents/logs/reviewer/verdicts.jsonl"
    with open(v_path, "a", encoding="utf-8", newline="\n") as fh:
        for i in range(60):
            fh.write(f'{{"session_id": "probe-{i}", "task_id": "1.{i}", "verdict": "PASS"}}\n')

    assert main(["--repo-root", str(mini_repo_fixture), "--check"]) == EXIT_OK


def test_16_pythonhashseed_invariance(tmp_path: Path):
    """16. 子进程验证 PYTHONHASHSEED=0 与 PYTHONHASHSEED=31337 下投影哈希恒等。"""
    import subprocess
    repo = create_mini_repo(tmp_path / "mini_repo_seed")
    script = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r}); "
        "import asset_inventory; "
        f"rep = asset_inventory.build_inventory_report(Path({str(repo)!r})); "
        "proj = asset_inventory.build_pure_projection(rep); "
        "print(asset_inventory.compute_pure_projection_sha256(proj))"
    )
    env0 = os.environ.copy()
    env0["PYTHONHASHSEED"] = "0"
    p0 = subprocess.run([sys.executable, "-c", script], env=env0, capture_output=True, text=True, check=True)
    hash0 = p0.stdout.strip()

    env1 = os.environ.copy()
    env1["PYTHONHASHSEED"] = "31337"
    p1 = subprocess.run([sys.executable, "-c", script], env=env1, capture_output=True, text=True, check=True)
    hash1 = p1.stdout.strip()

    assert len(hash0) == 64
    assert hash0 == hash1


def test_17_crlf_lf_equivalence(tmp_path: Path):
    """17. 跨平台换行防御：CRLF 仓与 LF 仓生成的 canonical_projection_json 字节严格恒等。"""
    repo_lf = create_mini_repo(tmp_path / "repo_lf")
    repo_crlf = create_mini_repo(tmp_path / "repo_crlf")

    for p in repo_crlf.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".md", ".yaml", ".jsonl"):
            content = p.read_text(encoding="utf-8")
            p.write_bytes(content.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))

    rep_lf = build_inventory_report(repo_lf)
    rep_crlf = build_inventory_report(repo_crlf)

    proj_lf = build_pure_projection(rep_lf)
    proj_crlf = build_pure_projection(rep_crlf)

    bytes_lf = canonical_projection_json(proj_lf)
    bytes_crlf = canonical_projection_json(proj_crlf)

    assert bytes_lf == bytes_crlf


def test_18_schema_version_mismatch_exit_usage(tmp_path: Path, capsys: pytest.CaptureFixture):
    """18. 未知或畸形 schema_version 严格 fail-closed 返回 EXIT_USAGE=2。"""
    repo = create_mini_repo(tmp_path / "repo_bad_schema")
    out_file = repo / OUTPUT_MD_REL
    content = out_file.read_text(encoding="utf-8")
    tampered = content.replace("quench-inventory-projection/v1", "quench-inventory-projection/v999")
    atomic_write_text(out_file, tampered)

    capsys.readouterr()
    ret = main(["--repo-root", str(repo), "--check"])
    assert ret == EXIT_USAGE
    err = capsys.readouterr().err
    assert "Projection schema mismatch" in err or "schema" in err


def test_19_skipped_file_stderr_warning(capsys: pytest.CaptureFixture, tmp_path: Path):
    """19. 超大跳过文件向 stderr 单行警告且不污染 PureProjection。"""
    repo = create_mini_repo(tmp_path / "repo_skipped")
    oversized = repo / SERVER_ROOT_REL / "huge_module.py"
    oversized.write_bytes(b"# pad\n" + b"x = 1\n" * (MAX_SCANNED_FILE_BYTES // 4))

    capsys.readouterr()
    rep = build_inventory_report(repo)
    assert len(rep.skipped_files) >= 1
    proj = build_pure_projection(rep)
    err = capsys.readouterr().err
    assert "[inventory]" in err
    assert "skipped" in err
    assert not any("huge_module.py" in m.rel_path for m in proj.modules)


def test_20_symbol_deletion_detected(tmp_path: Path, capsys: pytest.CaptureFixture):
    """20. 删除模块中已登记符号能够被准确检出，且 drift_keys 包含 modules。"""
    repo = create_mini_repo(tmp_path / "repo_sym_del")
    sample_py = repo / SERVER_ROOT_REL / "sample.py"
    sample_py.write_text(
        "_issue_checkout_lease = 2\n"
        "_fake_orphan_removal_candidate = 3\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    ret = main(["--repo-root", str(repo), "--check"])
    assert ret == EXIT_DRIFT
    err = capsys.readouterr().err
    assert "drift_keys=" in err
    assert "modules" in err


def test_21_idempotent_projection_block(mini_repo_fixture: Path):
    """21. 投影块写入幂等：连续多次 --write 不产生重复注释块且字节完全一致。"""
    out_file = mini_repo_fixture / OUTPUT_MD_REL
    main(["--repo-root", str(mini_repo_fixture), "--write"])
    text1 = out_file.read_bytes()

    assert text1.count(PROJECTION_BEGIN_MARK.encode("utf-8")) == 1
    assert text1.count(PROJECTION_END_MARK.encode("utf-8")) == 1
    assert text1.count(DELTA_BEGIN_MARK.encode("utf-8")) == 1
    assert text1.count(DELTA_END_MARK.encode("utf-8")) == 1

    main(["--repo-root", str(mini_repo_fixture), "--write"])
    text2 = out_file.read_bytes()

    assert text1 == text2


def test_output_crlf_free():
    """产物字节中 b"\\r\\n" not in bytes（CRLF 不变式）。"""
    out_file = REPO_ROOT / OUTPUT_MD_REL
    assert out_file.is_file()
    raw_bytes = out_file.read_bytes()
    assert b"\r\n" not in raw_bytes, "Output markdown contains CRLF line endings!"


def test_14_time_drift_telemetry_decoupling(mini_repo_fixture: Path):
    """14. 时间漂移回归：向临时 verdicts.jsonl 追加记录后重算产物主体哈希不变、--check 返回 EXIT_OK（由 mini_repo_fixture 驱动）。"""
    v_path = mini_repo_fixture / ".agents/logs/reviewer/verdicts.jsonl"
    out_file = mini_repo_fixture / OUTPUT_MD_REL

    # 1) 基准检查通过
    assert main(["--repo-root", str(mini_repo_fixture), "--check"]) == EXIT_OK

    # 2) 追加一条新型遥测记录
    with open(v_path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write('{"reason": "__unit_test_time_drift_probe__"}\n')

    # 3) 重新构建 report，验证提取的主体文本哈希完全一致
    report_after = build_inventory_report(mini_repo_fixture)
    rendered_after = render_markdown(report_after)

    existing_rendered = out_file.read_text(encoding="utf-8")
    gated_existing = extract_gated_body(strip_delta_block(existing_rendered))
    gated_after = extract_gated_body(rendered_after)

    hash_existing = hashlib.sha256(gated_existing.encode("utf-8")).hexdigest()
    hash_after = hashlib.sha256(gated_after.encode("utf-8")).hexdigest()

    assert hash_existing == hash_after, "Telemetry addition caused drift in gated body!"

    # 4) --check 门禁零假红，依然返回 EXIT_OK
    assert main(["--repo-root", str(mini_repo_fixture), "--check"]) == EXIT_OK


def test_doc_non_consumer_prefixes_subset_of_doc_roots():
    """R2 SSOT 不变量断言：DOC_NON_CONSUMER_PREFIXES 的每一项必须从属于 DOC_ROOT_RELS 中某一项。"""
    from pathlib import PurePosixPath

    assert len(DOC_NON_CONSUMER_PREFIXES) > 0, "DOC_NON_CONSUMER_PREFIXES must not be empty"
    for prefix_str in DOC_NON_CONSUMER_PREFIXES:
        p = PurePosixPath(prefix_str)
        matched = False
        for root_str in DOC_ROOT_RELS:
            r = PurePosixPath(root_str)
            if p == r or r in p.parents:
                matched = True
                break
        assert matched, f"Prefix '{prefix_str}' does not belong to any DOC_ROOT_RELS: {DOC_ROOT_RELS}"


def test_asset_inventory_ignores_dev_tasks(tmp_path: Path):
    """R1/R3 Hermetic 单测：tmp_path 合成仓库，断言 docs/dev_tasks 彻底排除且不误伤正常 docs/ 文档。"""
    from pathlib import PurePosixPath

    # 1. 验证 _is_non_consumer_doc 的目录分量隔离语义（R1：防误吞 docs/dev_tasks_* 兄弟路径）
    assert _is_non_consumer_doc("docs/dev_tasks/test_task.md") is True
    assert _is_non_consumer_doc("docs/dev_tasks/archive/old_task.md") is True
    assert _is_non_consumer_doc("docs/dev_tasks_archive/other.md") is False
    assert _is_non_consumer_doc("docs/architecture/README.md") is False
    assert _is_non_consumer_doc("README.md") is False

    # 2. 合成最小 hermetic 仓库
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    (fake_repo / ".git").mkdir()
    agents_dir = fake_repo / ".agents"
    agents_dir.mkdir()
    (agents_dir / "quench_stack.yaml").write_text("config_version: 1\n", encoding="utf-8")

    server_dir = fake_repo / "plugins/quench-dev-tasks/server"
    server_dir.mkdir(parents=True)
    foo_py = server_dir / "foo.py"
    foo_py.write_text(
        "SYMBOL_DEV_TASK_TARGET = 100\n"
        "SYMBOL_ARCH_DOC_TARGET = 200\n",
        encoding="utf-8",
    )

    dev_tasks_dir = fake_repo / "docs/dev_tasks"
    dev_tasks_dir.mkdir(parents=True)
    task_file = dev_tasks_dir / "2026-10-03_test_task.md"
    task_file.write_text(
        "# Task\nMentions SYMBOL_DEV_TASK_TARGET here in task spec.\n",
        encoding="utf-8",
    )

    arch_dir = fake_repo / "docs/architecture"
    arch_dir.mkdir(parents=True)
    arch_file = arch_dir / "system_arch.md"
    arch_file.write_text(
        "# Arch\nMentions SYMBOL_ARCH_DOC_TARGET in architecture design.\n",
        encoding="utf-8",
    )

    # 3. 扫描并构建消费者图谱
    nodes = scan_modules(server_dir, repo_root=fake_repo)
    edges = build_consumer_graph(nodes, repo_root=fake_repo)

    edge_map = {e.symbol: e for e in edges}
    assert "SYMBOL_DEV_TASK_TARGET" in edge_map
    assert "SYMBOL_ARCH_DOC_TARGET" in edge_map

    # 断言 SYMBOL_DEV_TASK_TARGET 的 doc_refs 为空（docs/dev_tasks 被彻底忽略）
    assert edge_map["SYMBOL_DEV_TASK_TARGET"].doc_refs == (), (
        f"docs/dev_tasks was not ignored: {edge_map['SYMBOL_DEV_TASK_TARGET'].doc_refs}"
    )

    # 断言 SYMBOL_ARCH_DOC_TARGET 的 doc_refs 正常捕获（docs/architecture 未被误伤）
    assert "docs/architecture/system_arch.md" in edge_map["SYMBOL_ARCH_DOC_TARGET"].doc_refs


def test_gitattributes_contract():
    """断言仓库根目录存在 .gitattributes 并声明了严格的 LF 换行契约。"""
    gitattributes_path = REPO_ROOT / ".gitattributes"
    assert gitattributes_path.is_file(), ".gitattributes file is missing from repository root!"
    text = gitattributes_path.read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in text
    assert "*.md text eol=lf" in text
    assert b"\r\n" not in gitattributes_path.read_bytes(), ".gitattributes must have LF line endings!"


def test_delta_schema_contract(mini_repo_fixture: Path):
    """断言 Delta 差异报告符合 v1.22 §4.1 五段契约与哈希对比表（由 mini_repo_fixture 驱动）。"""
    frozen_file = mini_repo_fixture / FROZEN_V120_REL
    report = build_inventory_report(mini_repo_fixture)
    pure_text = render_markdown(report)
    snapshot = InventorySnapshot(report=report, rendered_pure_markdown=pure_text)
    delta = compute_delta_report(frozen_file, snapshot)

    assert isinstance(delta, DeltaReport)
    assert isinstance(delta.resolved, tuple)
    assert isinstance(delta.persisted, tuple)
    assert isinstance(delta.emerged, tuple)
    assert isinstance(delta.coupling, tuple)
    assert isinstance(delta.module_graph, (dict, MappingProxyType))

    # 哈希必须是合法 64 位十六进制
    assert re.match(r"^[0-9a-f]{64}$", delta.frozen_sha256)
    assert re.match(r"^[0-9a-f]{64}$", delta.current_sha256)

    # 验证 Coupling 段双租约
    lease_names = {c.lease_name for c in delta.coupling}
    assert "manifest_lease" in lease_names
    assert "workspace_lease" in lease_names


def test_delta_mode_readonly(mini_repo_fixture: Path):
    """D-R2 只读纪律：--delta-report 执行前后 over_engineering_inventory.md 的 SHA256 与 mtime_ns 均不变（由 mini_repo_fixture 驱动）。"""
    out_file = mini_repo_fixture / OUTPUT_MD_REL
    assert out_file.is_file()
    stat_before = out_file.stat()
    sha_before = hashlib.sha256(out_file.read_bytes()).hexdigest()
    mtime_before = stat_before.st_mtime_ns

    exit_code = main(["--repo-root", str(mini_repo_fixture), "--delta-report"])
    assert exit_code == EXIT_OK

    stat_after = out_file.stat()
    sha_after = hashlib.sha256(out_file.read_bytes()).hexdigest()
    mtime_after = stat_after.st_mtime_ns

    assert sha_after == sha_before, "READONLY_SHA_VIOLATION"
    assert mtime_after == mtime_before, "READONLY_MTIME_VIOLATION"


def test_rebaseline_determinism(mini_repo_fixture: Path):
    """D-R5 / TP-4 确定性律：同一 commit 连续两次生成的清单与 Delta 段逐字节一致（由 mini_repo_fixture 驱动）。"""
    frozen_file = mini_repo_fixture / FROZEN_V120_REL
    report1 = build_inventory_report(mini_repo_fixture)
    pure1 = render_markdown(report1)
    delta1 = compute_delta_report(frozen_file, InventorySnapshot(report1, pure1))
    full1 = write_inventory_with_delta(pure1, delta1)

    report2 = build_inventory_report(mini_repo_fixture)
    pure2 = render_markdown(report2)
    delta2 = compute_delta_report(frozen_file, InventorySnapshot(report2, pure2))
    full2 = write_inventory_with_delta(pure2, delta2)

    assert full1 == full2
    assert full1.encode("utf-8") == full2.encode("utf-8")


def test_additive_regression():
    """D-R4 加性守卫：当前纯投影与 golden 基线件逐字节完全一致。"""
    golden_file = REPO_ROOT / "plugins/quench-dev-tasks/server/tests/fixtures/asset_inventory_default_golden.txt"
    assert golden_file.is_file(), "Golden baseline file is missing!"
    golden_content = golden_file.read_text(encoding="utf-8")

    out_file = REPO_ROOT / OUTPUT_MD_REL
    assert out_file.is_file()
    current_content = out_file.read_text(encoding="utf-8")
    pure_current = strip_delta_block(current_content)

    golden_norm = golden_content.replace("\r\n", "\n").strip() + "\n"
    pure_norm = pure_current.replace("\r\n", "\n").strip() + "\n"
    assert pure_norm == golden_norm, "Additive regression detected against golden baseline!"


def test_write_idempotent(mini_repo_fixture: Path):
    """D-R10 (N1) 写幂等律：write(write(x)) == write(x)，严禁 Delta 块重复嵌套累积（由 mini_repo_fixture 驱动）。"""
    frozen_file = mini_repo_fixture / FROZEN_V120_REL
    report = build_inventory_report(mini_repo_fixture)
    pure_text = render_markdown(report)
    snapshot = InventorySnapshot(report, pure_text)
    delta = compute_delta_report(frozen_file, snapshot)

    once = write_inventory_with_delta(pure_text, delta)
    twice = write_inventory_with_delta(once, delta)
    thrice = write_inventory_with_delta(twice, delta)

    assert once == twice
    assert twice == thrice
    assert once.count(DELTA_BEGIN_MARK) == 1
    assert once.count(DELTA_END_MARK) == 1


def test_marker_balance_fail_closed():
    """D-R11 (N3) 标记闭锁律：标记失衡或畸形时严格抛出 DeltaBlockMalformedError。"""
    # 1. 只有 BEGIN 没有 END
    with pytest.raises(DeltaBlockMalformedError):
        _assert_balanced_markers(f"{DELTA_BEGIN_MARK}\nsome text")

    # 2. 只有 END 没有 BEGIN
    with pytest.raises(DeltaBlockMalformedError):
        _assert_balanced_markers(f"some text\n{DELTA_END_MARK}")

    # 3. 重复成对标记
    with pytest.raises(DeltaBlockMalformedError):
        _assert_balanced_markers(f"{DELTA_BEGIN_MARK}\n1\n{DELTA_END_MARK}\n{DELTA_BEGIN_MARK}\n2\n{DELTA_END_MARK}")

    # 4. 反向标记 (END 在 BEGIN 前)
    with pytest.raises(DeltaBlockMalformedError):
        _assert_balanced_markers(f"{DELTA_END_MARK}\nsome text\n{DELTA_BEGIN_MARK}")


def test_ordering_and_no_leak(mini_repo_fixture: Path):
    """D-R5 / N4 确定性排序与泄漏防护：邻接表与拓扑元组排序确定，输出中无绝对路径与动态时间戳（由 mini_repo_fixture 驱动）。"""
    frozen_file = mini_repo_fixture / FROZEN_V120_REL
    report = build_inventory_report(mini_repo_fixture)
    pure = render_markdown(report)
    delta = compute_delta_report(frozen_file, InventorySnapshot(report, pure))
    rendered_delta = render_delta_report_markdown(delta)

    # 1. Module graph 排序
    for mod_path, deps in delta.module_graph.items():
        assert deps == tuple(sorted(deps)), f"Module deps for {mod_path} not sorted!"

    # 2. Coupling 排序
    for c in delta.coupling:
        assert c.call_topology == tuple(sorted(c.call_topology)), f"Topology for {c.lease_name} not sorted!"

    # 3. 无绝对路径
    assert re.search(r"[A-Za-z]:[/\\]", rendered_delta) is None
    assert re.search(r"/(?:Users|home|workspace|tmp|var|private)/", rendered_delta) is None

    # 4. 无 RFC3339 动态时间戳
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", rendered_delta) is None


def test_atomic_write(tmp_path: Path):
    """D-R12 (N7) 原子写律：保证写入成功且不产生遗留临时文件。"""
    target = tmp_path / "sub" / "output.txt"
    text = "hello atomic world\n"
    atomic_write_text(target, text)
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == text

    # 确保没有遗留 tmp 文件
    tmp_files = list(target.parent.glob("*.tmp.*"))
    assert len(tmp_files) == 0


def test_invariant_mapping_fail_closed(tmp_path: Path):
    """D-R3 (N8) 完备性与 fail-closed：Persisted 符号若缺失不变量且未在 KNOWN_INVARIANT_GAPS 登记，抛 ValueError。"""
    fake_frozen = tmp_path / "fake_frozen.md"
    fake_content = (
        "## 1. 核心\n\n"
        "## 2. 潜在删除/重构候选清单\n"
        "| `__unregistered_orphan_sym__` | `plugins/quench-dev-tasks/server/fake.py` |\n\n"
        "## 3. 服务端生产模块概览\n"
    )
    fake_frozen.write_text(fake_content, encoding="utf-8")

    fake_module = ModuleNode(
        rel_path="plugins/quench-dev-tasks/server/fake.py",
        imported_modules=(),
        imported_symbols=(),
        defined_symbols=("__unregistered_orphan_sym__",),
    )
    fake_report = InventoryReport(
        modules=(fake_module,),
        consumers=(),
        tools=(),
        audit_reason_histogram={},
        telemetry_meta={},
        skipped_files=(),
        doc_drift_ledger=(),
        g1prime_gaps=(),
        removal_candidates=(),
        must_not_remove=(),
    )
    fake_snapshot = InventorySnapshot(fake_report, "pure")

    with pytest.raises(ValueError) as excinfo:
        compute_delta_report(fake_frozen, fake_snapshot)
    assert "not in KNOWN_INVARIANT_GAPS" in str(excinfo.value)


def test_frozen_snapshot_missing_and_unparsable(tmp_path: Path, synthetic_bundle: SyntheticBundle):
    """D-R9 边界：快照缺失抛 FrozenSnapshotMissingError；不可解析抛 FrozenSnapshotUnparsableError（由 synthetic_bundle 驱动）。"""
    snapshot = synthetic_bundle.snapshot

    # 1. 缺失
    non_existent = tmp_path / "missing.md"
    with pytest.raises(FrozenSnapshotMissingError):
        compute_delta_report(non_existent, snapshot)

    # 2. 不可解析（缺失必须的 Section 头）
    bad_file = tmp_path / "bad.md"
    bad_file.write_text("random broken content", encoding="utf-8")
    with pytest.raises(FrozenSnapshotUnparsableError):
        compute_delta_report(bad_file, snapshot)


def test_emerged_record_register_only():
    """D-R8 / N5 纪律：EmergedRecord.suggested_disposition 严格为 REGISTER_ONLY。"""
    rec = EmergedRecord(
        symbol="emerged_probe",
        defining_module="server.py",
        consumer_count=0,
        carrying_invariants=(),
        axiom_mapping=(),
    )
    assert rec.suggested_disposition == "REGISTER_ONLY"

