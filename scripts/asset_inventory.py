#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quench Dev Orchestrator (quorch) - 架构资产取证与去工业化清单生成工具.

纯标准库实现，零第三方运行时依赖，严禁导入任何 quench 生产模块。
提供机器生成、可重复、可校验新鲜度的架构资产与消费者依赖图谱。
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final, Mapping, Sequence

REPO_ROOT_MARKERS: Final[tuple[str, ...]] = (".git", ".agents/quench_stack.yaml")
SERVER_ROOT_REL: Final[str] = "plugins/quench-dev-tasks/server"
TESTS_ROOT_REL: Final[str] = "plugins/quench-dev-tasks/server/tests"
OUTPUT_MD_REL: Final[str] = "docs/architecture/over_engineering_inventory.md"

CONSUMER_SCAN_ROOTS: Final[tuple[str, ...]] = (
    "plugins/quench-dev-tasks/server",
    "plugins/quench-dev-tasks/server/tests",
    "plugins/quench-dev-tasks/rules",
    "plugins/quench-dev-tasks/skills",
    "plugins/quench-dev-tasks/agents",
    "scripts",
    "docs",
    ".agents",
    "README.md",
    "CHANGELOG.md",
    "dev_tasks_mcp_specification.md",
)
DOC_ROOT_RELS: Final[tuple[str, ...]] = (
    "docs",
    "plugins/quench-dev-tasks/rules",
    "plugins/quench-dev-tasks/skills",
    "plugins/quench-dev-tasks/agents",
    "README.md",
    "CHANGELOG.md",
    "dev_tasks_mcp_specification.md",
)
DOC_NON_CONSUMER_PREFIXES: Final[tuple[str, ...]] = ("docs/dev_tasks",)


def _is_non_consumer_doc(rel_posix: str) -> bool:
    """判定文档相对路径是否属于非消费者文档（目录分量语义，PurePosixPath）。

    严禁使用裸字符串 startswith，防止误吞 docs/dev_tasks_* 等兄弟路径。
    """
    p = PurePosixPath(rel_posix)
    for prefix_str in DOC_NON_CONSUMER_PREFIXES:
        prefix = PurePosixPath(prefix_str)
        if p == prefix or prefix in p.parents:
            return True
    return False

MAX_SCANNED_FILE_BYTES: Final[int] = 1_000_000
SKIP_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {"__pycache__", ".venv", "venv", "node_modules", ".git", ".pytest_cache", ".mypy_cache"}
)

VERDICTS_REL: Final[str] = ".agents/logs/reviewer/verdicts.jsonl"
MAX_TELEMETRY_BYTES: Final[int] = 8 * 1024 * 1024
TELEMETRY_MIN_SAMPLES: Final[int] = 30
TELEMETRY_BEGIN: Final[str] = "<!-- BEGIN TELEMETRY (non-gated) -->"
TELEMETRY_END: Final[str] = "<!-- END TELEMETRY -->"

EXIT_OK: Final[int] = 0
EXIT_DRIFT: Final[int] = 1
EXIT_USAGE: Final[int] = 2


@dataclass(frozen=True)
class ModuleNode:
    rel_path: str
    imported_modules: tuple[str, ...]
    imported_symbols: tuple[str, ...]
    defined_symbols: tuple[str, ...]


@dataclass(frozen=True)
class ConsumerEdge:
    symbol: str
    defined_in: str
    consumed_by: tuple[str, ...]
    test_refs: tuple[str, ...]
    doc_refs: tuple[str, ...]
    is_lower_bound: bool = True


@dataclass(frozen=True)
class ToolSurface:
    name: str
    registered_name: str
    params: tuple[tuple[str, str | None], ...]
    returns_repr: str | None


@dataclass(frozen=True)
class InventoryReport:
    modules: tuple[ModuleNode, ...]
    consumers: tuple[ConsumerEdge, ...]
    tools: tuple[ToolSurface, ...]
    audit_reason_histogram: Mapping[str, int]
    telemetry_meta: Mapping[str, object]
    skipped_files: tuple[tuple[str, int], ...]
    doc_drift_ledger: tuple[str, ...]
    g1prime_gaps: tuple[str, ...]
    removal_candidates: tuple[ConsumerEdge, ...]
    must_not_remove: tuple[str, ...]


MUST_NOT_REMOVE_SYMBOLS: Final[tuple[str, ...]] = (
    "reclaim_stale_task",
    "generation",
    "owner_boot_nonce",
    "probe_peer",
    "TERMINAL_RESULT_ALLOWED_FIELDS",
    "assert_read_only_sandbox",
    "filelock",
    "precondition_changed",
    "on_missing_record",
    "canonical_artifact_ref",
    "format_heartbeat_line",
)

DEFAULT_DOC_DRIFT_LEDGER: Final[tuple[str, ...]] = (
    'README.md §5 将 reaper.py 仅描述为 "Session log GC"，遗漏了其承载的 reclaim_stale_task（INV-1 唯一实现），将在 step07 进行职责收敛与文档修正。',
    "docs/architecture/README.md §3.3 示例中心跳格式若为 Token 在前，与 C2 冻结契约（时间在前 | Token 在后）存在冲突，将在 step05 统一原子同步。",
)

DEFAULT_G1PRIME_GAPS: Final[tuple[str, ...]] = (
    "状态跃迁维度不可由静态 AST 机械推导：MCP 工具对任务状态机（如 ✅ 已确认 -> 🔨 执行中 -> ✔️ 已完成）的影响需结合运行时语义分析，供 roadmap §1.3 在后续 step 补齐。",
    "通道正交性与参数等价性需结合运行时业务模型深度校验，单机公理 A1~A5 映射关系需持续维护。",
)


def discover_repo_root(start: Path) -> Path:
    """自 start 路径向上回溯，命中 REPO_ROOT_MARKERS 即返回仓库根；耗尽则抛出 RuntimeError。"""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    while True:
        for marker in REPO_ROOT_MARKERS:
            parts = marker.split("/")
            candidate = current.joinpath(*parts)
            if candidate.exists():
                return current
        parent = current.parent
        if parent == current:
            raise RuntimeError(
                f"Repository root markers {REPO_ROOT_MARKERS} not found from {start}"
            )
        current = parent


def _extract_defined_symbols(tree: ast.AST) -> tuple[str, ...]:
    """提取模块顶层定义的符号 (ClassDef, FunctionDef, AsyncFunctionDef, Assign, AnnAssign)。"""
    symbols: set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                _collect_target_names(target, symbols)
        elif isinstance(node, ast.AnnAssign):
            _collect_target_names(node.target, symbols)
    return tuple(sorted(symbols))


def _collect_target_names(target: ast.AST, out: set[str]) -> None:
    if isinstance(target, ast.Name):
        out.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _collect_target_names(elt, out)


def _extract_imported_modules_and_symbols(
    tree: ast.AST,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """提取模块的所有导入模块与导入符号。"""
    mods: set[str] = set()
    syms: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module)
            for alias in node.names:
                syms.add(alias.name)
    return tuple(sorted(mods)), tuple(sorted(syms))


def scan_modules(
    server_root: Path,
    repo_root: Path | None = None,
    skipped_collector: list[tuple[str, int]] | None = None,
) -> tuple[ModuleNode, ...]:
    """静态解析 server_root 下的生产模块，忽略 SKIP_DIR_NAMES、symlink 目录与 tests。"""
    resolved_server_root = server_root.resolve()
    effective_repo_root = (
        repo_root.resolve() if repo_root else None
    )
    if effective_repo_root is None:
        try:
            effective_repo_root = discover_repo_root(resolved_server_root)
        except RuntimeError:
            effective_repo_root = resolved_server_root

    modules: list[ModuleNode] = []
    skipped: list[tuple[str, int]] = []
    visited_dirs: set[Path] = set()

    for root_str, dirs, files in os.walk(resolved_server_root, followlinks=False):
        current_dir = Path(root_str)
        try:
            canonical_dir = current_dir.resolve()
        except Exception:
            canonical_dir = current_dir

        if canonical_dir in visited_dirs:
            dirs.clear()
            continue
        visited_dirs.add(canonical_dir)

        # 过滤子目录：忽略 symlink 目录、SKIP_DIR_NAMES 以及 tests 目录
        kept_dirs: list[str] = []
        for d in dirs:
            dir_path = current_dir / d
            try:
                if dir_path.is_symlink():
                    continue
            except Exception:
                continue
            if d in SKIP_DIR_NAMES:
                continue
            if d == "tests" and (current_dir / d) != resolved_server_root:
                continue
            kept_dirs.append(d)
        dirs[:] = sorted(kept_dirs)

        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            file_path = current_dir / f
            try:
                rel_path = file_path.resolve().relative_to(effective_repo_root).as_posix()
            except ValueError:
                rel_path = file_path.as_posix()

            try:
                st = file_path.stat()
                file_size = st.st_size
            except Exception:
                file_size = 0

            if file_size > MAX_SCANNED_FILE_BYTES:
                skipped_item = (rel_path, file_size)
                skipped.append(skipped_item)
                if skipped_collector is not None:
                    skipped_collector.append(skipped_item)
                continue

            try:
                source = file_path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=rel_path)
                imp_mods, imp_syms = _extract_imported_modules_and_symbols(tree)
                def_syms = _extract_defined_symbols(tree)
                modules.append(
                    ModuleNode(
                        rel_path=rel_path,
                        imported_modules=imp_mods,
                        imported_symbols=imp_syms,
                        defined_symbols=def_syms,
                    )
                )
            except Exception:
                # 语法错误或不可解析文件静默跳过
                continue

    # 保存最后的跳过文件信息以便测试断言
    scan_modules.last_skipped = tuple(skipped)  # type: ignore[attr-defined]
    return tuple(sorted(modules, key=lambda m: m.rel_path))


scan_modules.last_skipped = ()  # type: ignore[attr-defined]


def scan_mcp_tools(server_py: Path) -> tuple[ToolSurface, ...]:
    """解析 server.py 中以 @mcp.tool 装饰的工具接口签名快照。"""
    tools: list[ToolSurface] = []
    if not server_py.is_file():
        return ()

    source = server_py.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=server_py.name)

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        is_tool = False
        registered_name = node.name
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "tool":
                is_tool = True
                for kw in dec.keywords:
                    if kw.arg == "name":
                        if isinstance(kw.value, ast.Constant):
                            registered_name = str(kw.value.value)
                        else:
                            registered_name = ast.unparse(kw.value)
            elif isinstance(dec, ast.Attribute) and dec.attr == "tool":
                is_tool = True

        if not is_tool:
            continue

        params_list: list[tuple[str, str | None]] = []
        args = node.args
        n_args = len(args.args)
        n_defaults = len(args.defaults)
        def_offset = n_args - n_defaults

        for i, arg in enumerate(args.args):
            p_name = arg.arg
            if i >= def_offset:
                d_node = args.defaults[i - def_offset]
                d_repr: str | None = ast.unparse(d_node)
            else:
                d_repr = None
            params_list.append((p_name, d_repr))

        for j, kwarg in enumerate(args.kwonlyargs):
            p_name = kwarg.arg
            d_node = args.kw_defaults[j]
            d_repr = ast.unparse(d_node) if d_node is not None else None
            params_list.append((p_name, d_repr))

        returns_repr = ast.unparse(node.returns) if node.returns else None

        tools.append(
            ToolSurface(
                name=node.name,
                registered_name=registered_name,
                params=tuple(params_list),
                returns_repr=returns_repr,
            )
        )

    return tuple(sorted(tools, key=lambda t: t.registered_name))


def build_consumer_graph(
    nodes: Sequence[ModuleNode], *, repo_root: Path
) -> tuple[ConsumerEdge, ...]:
    """构建符号消费者反向索引，扫描范围严格限于 CONSUMER_SCAN_ROOTS。"""
    resolved_repo_root = repo_root.resolve()

    # 1. 预加载所有 Python 消费者模块的 imported_symbols
    py_consumers: dict[str, set[str]] = {}
    doc_texts: dict[str, str] = {}

    for scan_root_rel in CONSUMER_SCAN_ROOTS:
        sr_path = (resolved_repo_root / scan_root_rel).resolve()
        if not sr_path.exists():
            continue

        targets = [sr_path] if sr_path.is_file() else list(sr_path.rglob("*"))
        for target in targets:
            if not target.is_file():
                continue
            if any(skip in target.parts for skip in SKIP_DIR_NAMES):
                continue
            try:
                rel_posix = target.relative_to(resolved_repo_root).as_posix()
            except ValueError:
                continue

            if rel_posix == OUTPUT_MD_REL:
                continue

            if target.suffix == ".py":
                try:
                    tree = ast.parse(target.read_text(encoding="utf-8"))
                    _, syms = _extract_imported_modules_and_symbols(tree)
                    py_consumers[rel_posix] = set(syms)
                except Exception:
                    pass
            elif any(
                rel_posix == dr or rel_posix.startswith(dr + "/") for dr in DOC_ROOT_RELS
            ):
                if _is_non_consumer_doc(rel_posix):
                    continue
                try:
                    doc_texts[rel_posix] = target.read_text(encoding="utf-8")
                except Exception:
                    pass

    # 2. 针对每个 node 中的 defined_symbols，构建 ConsumerEdge
    edges: list[ConsumerEdge] = []
    for node in nodes:
        defined_in = node.rel_path
        for symbol in node.defined_symbols:
            consumed_by: list[str] = []
            test_refs: list[str] = []
            doc_refs: list[str] = []

            for py_path, sym_set in py_consumers.items():
                if symbol in sym_set:
                    if "test" in py_path.lower():
                        test_refs.append(py_path)
                    elif py_path != defined_in:
                        consumed_by.append(py_path)

            sym_word_regex = re.compile(r"\b" + re.escape(symbol) + r"\b")
            for doc_path, text in doc_texts.items():
                if sym_word_regex.search(text):
                    doc_refs.append(doc_path)

            edges.append(
                ConsumerEdge(
                    symbol=symbol,
                    defined_in=defined_in,
                    consumed_by=tuple(sorted(set(consumed_by))),
                    test_refs=tuple(sorted(set(test_refs))),
                    doc_refs=tuple(sorted(set(doc_refs))),
                    is_lower_bound=True,
                )
            )

    return tuple(sorted(edges, key=lambda e: (e.defined_in, e.symbol)))


def is_removal_candidate(edge: ConsumerEdge) -> bool:
    """判定符号是否为潜在删除候选（零消费者、零单测、零文档提及，且未受 MUST_NOT_REMOVE 保护）。"""
    if edge.symbol in MUST_NOT_REMOVE_SYMBOLS:
        return False
    return (
        len(edge.consumed_by) == 0
        and len(edge.test_refs) == 0
        and len(edge.doc_refs) == 0
    )


def classify_removal_candidates(
    consumers: Sequence[ConsumerEdge],
) -> tuple[ConsumerEdge, ...]:
    """筛选出所有删除候选符号。"""
    candidates = [e for e in consumers if is_removal_candidate(e)]
    return tuple(sorted(candidates, key=lambda e: (e.defined_in, e.symbol)))


def harvest_audit_reasons(
    verdicts_jsonl: Path | None,
) -> tuple[Mapping[str, int], Mapping[str, object]]:
    """流式采集 reviewer 审阅审计理由频次与遥测元数据。"""
    if verdicts_jsonl is None or not verdicts_jsonl.is_file():
        return (
            MappingProxyType({}),
            MappingProxyType(
                {
                    "status": "telemetry unavailable",
                    "total_samples": 0,
                    "truncated": False,
                    "insufficient_samples": True,
                }
            ),
        )

    file_size = verdicts_jsonl.stat().st_size
    is_truncated = False
    histogram: dict[str, int] = {}
    total_samples = 0
    bytes_read = 0

    try:
        with verdicts_jsonl.open("rb") as fh:
            raw_bytes = fh.read(MAX_TELEMETRY_BYTES)
            bytes_read = len(raw_bytes)
            if file_size > MAX_TELEMETRY_BYTES:
                is_truncated = True

        text = raw_bytes.decode("utf-8", errors="replace")
        lines = text.splitlines()

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                rec = json.loads(line_str)
                if isinstance(rec, dict):
                    reason = str(rec.get("reason", "unknown"))
                    histogram[reason] = histogram.get(reason, 0) + 1
                    total_samples += 1
            except Exception:
                # 遇到截断行或畸形记录平稳跳过
                continue
    except Exception:
        return (
            MappingProxyType({}),
            MappingProxyType(
                {
                    "status": "telemetry unavailable",
                    "total_samples": 0,
                    "truncated": False,
                    "insufficient_samples": True,
                }
            ),
        )

    meta = {
        "status": "ok" if total_samples > 0 else "empty",
        "total_samples": total_samples,
        "bytes_read": bytes_read,
        "truncated": is_truncated,
        "insufficient_samples": total_samples < TELEMETRY_MIN_SAMPLES,
    }
    sorted_hist = {k: histogram[k] for k in sorted(histogram.keys())}
    return MappingProxyType(sorted_hist), MappingProxyType(meta)


def build_inventory_report(
    repo_root: Path,
    server_root: Path | None = None,
    verdicts_jsonl: Path | None = None,
) -> InventoryReport:
    """装配全量架构资产清单报告。"""
    resolved_root = repo_root.resolve()
    srv_root = (server_root or (resolved_root / SERVER_ROOT_REL)).resolve()
    v_path = (verdicts_jsonl or (resolved_root / VERDICTS_REL)).resolve()

    skipped: list[tuple[str, int]] = []
    modules = scan_modules(srv_root, repo_root=resolved_root, skipped_collector=skipped)
    consumers = build_consumer_graph(modules, repo_root=resolved_root)
    tools = scan_mcp_tools(srv_root / "server.py")
    hist, meta = harvest_audit_reasons(v_path if v_path.exists() else None)
    removal_candidates = classify_removal_candidates(consumers)

    return InventoryReport(
        modules=modules,
        consumers=consumers,
        tools=tools,
        audit_reason_histogram=hist,
        telemetry_meta=meta,
        skipped_files=tuple(sorted(set(skipped))),
        doc_drift_ledger=DEFAULT_DOC_DRIFT_LEDGER,
        g1prime_gaps=DEFAULT_G1PRIME_GAPS,
        removal_candidates=removal_candidates,
        must_not_remove=MUST_NOT_REMOVE_SYMBOLS,
    )


def _fmt_refs(refs: Sequence[str]) -> str:
    if not refs:
        return "NONE"
    return ", ".join(f"`{r}`" for r in refs)


def render_markdown(report: InventoryReport) -> str:
    """渲染机器生成、完全确定性、无绝对路径/git sha/时间戳的 Markdown 资产清单。"""
    lines: list[str] = [
        "# Quench 架构资产取证与去工业化清单 (Architecture Asset Inventory)",
        "",
        "> **取证铁律与下界声明**:",
        "> 1. 本图谱为下界，不覆盖 `mod.sym` 属性式访问与运行时反射。",
        "> 2. 只读取证铁律：不修改任何生产代码，作为 step02–step09 瘦身动作的许可依据与回滚判据。",
        "",
        "---",
        "",
        "## 1. 核心不可触碰清单 (Must-Not-Remove Invariants)",
        "",
        "| 关键符号 | 约束与承载不变量 |",
        "| :--- | :--- |",
    ]

    invariant_descriptions = {
        "reclaim_stale_task": "INV-1 陈旧租约回收唯一实现（仅允许原子迁移，禁止直接删除）",
        "generation": "工作区互斥锁 CAS 代际令牌（防 ABA 踩脚）",
        "owner_boot_nonce": "跨进程租约身份 CAS 判定",
        "probe_peer": "跨进程存活判定（必须在交付替代回收路径后方可移除）",
        "TERMINAL_RESULT_ALLOWED_FIELDS": "INV-3 反角色扮演与防思维链泄露白名单",
        "assert_read_only_sandbox": "INV-6 审查只读沙箱硬校验",
        "filelock": "manifest 级跨进程互斥锁",
        "precondition_changed": "任务状态并发 CAS 保护",
        "on_missing_record": "安全键 fail-closed 策略",
        "canonical_artifact_ref": "规范产物引用契约",
        "format_heartbeat_line": "C2 心跳行契约（时间在前 | Token 在后）",
    }

    for sym in report.must_not_remove:
        desc = invariant_descriptions.get(sym, "核心不变量机制")
        lines.append(f"| `{sym}` | {desc} |")

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 2. 潜在删除/重构候选清单 (Removal Candidates, 共 {len(report.removal_candidates)} 项)",
            "",
            "| 符号 | 定义模块 |",
            "| :--- | :--- |",
        ]
    )

    if not report.removal_candidates:
        lines.append("| NONE | 暂无零消费者候选符号 |")
    else:
        for cand in report.removal_candidates:
            lines.append(f"| `{cand.symbol}` | `{cand.defined_in}` |")

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 3. 服务端生产模块概览 (Server Production Modules, 共 {len(report.modules)} 个模块)",
            "",
            "| 模块路径 | 定义符号数 | 导入模块数 | 导入符号数 |",
            "| :--- | :--- | :--- | :--- |",
        ]
    )

    for m in report.modules:
        lines.append(
            f"| `{m.rel_path}` | {len(m.defined_symbols)} | {len(m.imported_modules)} | {len(m.imported_symbols)} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 4. 消费者依赖图谱 (Consumer Dependency Graph, 共 {len(report.consumers)} 项符号)",
            "",
            "| 符号 | 定义模块 | 业务消费者 (`consumed_by`) | 测试引用 (`test_refs`) | 文档提及 (`doc_refs`) |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
    )

    for c in report.consumers:
        consumed_str = _fmt_refs(c.consumed_by)
        tests_str = _fmt_refs(c.test_refs)
        docs_str = _fmt_refs(c.doc_refs)
        lines.append(
            f"| `{c.symbol}` | `{c.defined_in}` | {consumed_str} | {tests_str} | {docs_str} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 5. MCP 工具契约快照 (MCP Tool Surface Snapshot, 共 {len(report.tools)} 个工具)",
            "",
            "| 工具名称 | 注册名称 | 参数列表 (名称与默认值) | 返回类型契约 |",
            "| :--- | :--- | :--- | :--- |",
        ]
    )

    for t in report.tools:
        params_str = (
            ", ".join(
                f"{p[0]}={p[1]}" if p[1] is not None else p[0] for p in t.params
            )
            if t.params
            else "NONE"
        )
        ret_str = f"`{t.returns_repr}`" if t.returns_repr else "NONE"
        lines.append(
            f"| `{t.name}` | `{t.registered_name}` | `{params_str}` | {ret_str} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 6. G1' 语义正交门禁与待补维度登记 (G1' Gaps & Semantic Orthogonality)",
            "",
        ]
    )
    for gap in report.g1prime_gaps:
        lines.append(f"- {gap}")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 7. 文档漂移台账 (Documentation Drift Ledger)",
            "",
        ]
    )
    for drift in report.doc_drift_ledger:
        lines.append(f"- {drift}")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 8. 跳过与超限文件登记 (Skipped Files Ledger)",
            "",
            "| 文件路径 | 文件大小 (字节) | 原因 |",
            "| :--- | :--- | :--- |",
        ]
    )

    if not report.skipped_files:
        lines.append("| NONE | NONE | 暂无超过上限文件 |")
    else:
        for sf, sz in report.skipped_files:
            lines.append(f"| `{sf}` | {sz} | 超过大小上限限制 |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 9. 审计遥测直方图 (Audit Reasons Histogram)",
            "",
            TELEMETRY_BEGIN,
        ]
    )

    status = report.telemetry_meta.get("status", "unknown")
    total_samples = int(report.telemetry_meta.get("total_samples", 0))  # type: ignore[arg-type]
    eval_str = (
        f"INSUFFICIENT SAMPLE (n={total_samples})"
        if total_samples < TELEMETRY_MIN_SAMPLES
        else "样本充足"
    )

    lines.append(f"- 遥测状态: {status}")
    lines.append(f"- 样本总量: {total_samples}")
    lines.append(f"- 评估结论: {eval_str}")
    lines.append("")
    lines.append("### 审计理由分布:")
    if not report.audit_reason_histogram:
        lines.append("- NONE")
    else:
        for rk, rv in sorted(report.audit_reason_histogram.items()):
            lines.append(f"- `{rk}`: {rv}")

    lines.append(TELEMETRY_END)
    lines.append("")

    return "\n".join(lines)


def extract_gated_body(content: str) -> str:
    """提取产物中除非门禁遥测段之外的主体文本，保证时间漂移零假红。"""
    normalized = content.replace("\r\n", "\n")
    if TELEMETRY_BEGIN in normalized and TELEMETRY_END in normalized:
        before, rest = normalized.split(TELEMETRY_BEGIN, 1)
        _, after = rest.split(TELEMETRY_END, 1)
        return before + after
    return normalized


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口，支持 --write, --check 以及 --repo-root。"""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="asset_inventory",
        description="Quench Architecture Asset Inventory CLI",
    )
    parser.add_argument(
        "--repo-root",
        type=str,
        default=None,
        help="显式指定仓库根目录（默认自当前目录上溯发现）",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="生成并写入资产清单 Markdown 文件",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="校验现有资产清单的新鲜度（对比门禁主体）",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as se:
        return se.code if se.code is not None else EXIT_USAGE

    try:
        start_path = Path(args.repo_root) if args.repo_root else Path.cwd()
        repo_root = discover_repo_root(start_path)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return EXIT_USAGE

    out_file = repo_root / OUTPUT_MD_REL

    if args.check:
        if not out_file.is_file():
            print(f"Missing inventory file: {out_file}", file=sys.stderr)
            return EXIT_USAGE

        existing_text = out_file.read_text(encoding="utf-8")
        report = build_inventory_report(repo_root)
        new_text = render_markdown(report)

        existing_gated = extract_gated_body(existing_text)
        new_gated = extract_gated_body(new_text)

        if existing_gated != new_gated:
            print("Drift detected between codebase and inventory report!", file=sys.stderr)
            return EXIT_DRIFT

        print("Freshness check passed: inventory matches codebase.", file=sys.stdout)
        return EXIT_OK

    elif args.write:
        report = build_inventory_report(repo_root)
        rendered = render_markdown(report)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(rendered)
        print(f"Successfully generated inventory: {out_file}", file=sys.stdout)
        return EXIT_OK

    else:
        parser.print_help(sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
