#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quench Dev Orchestrator (quorch) - 架构资产取证与去工业化清单生成工具.

纯标准库实现，零第三方运行时依赖，严禁导入任何 quench 生产模块。
提供机器生成、可重复、可校验新鲜度的架构资产与消费者依赖图谱。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final, Literal, Mapping, Sequence

REPO_ROOT_MARKERS: Final[tuple[str, ...]] = (".git", ".agents/quench_stack.yaml")
SERVER_ROOT_REL: Final[str] = "plugins/quench-dev-tasks/server"
TESTS_ROOT_REL: Final[str] = "plugins/quench-dev-tasks/server/tests"
OUTPUT_MD_REL: Final[str] = "docs/architecture/over_engineering_inventory.md"
FROZEN_V120_REL: Final[str] = "docs/architecture/over_engineering_inventory_v120_frozen.md"
CURRENT_INV_REL: Final[str] = "docs/architecture/over_engineering_inventory.md"
DELTA_REPORT_ARG: Final[str] = "--delta-report"
DELTA_BEGIN_MARK: Final[str] = "<!-- QUENCH-DELTA-BEGIN:v1.21 -->"
DELTA_END_MARK: Final[str] = "<!-- QUENCH-DELTA-END:v1.21 -->"


class FrozenSnapshotMissingError(Exception):
    """冻结快照文件缺失时抛出。"""
    pass


class FrozenSnapshotUnparsableError(Exception):
    """冻结快照文件格式异常或无法解析时抛出。"""
    pass


class DeltaBlockMalformedError(Exception):
    """Delta 分隔符失衡或格式畸形时抛出（Fail-closed 闭锁）。"""
    pass

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


@dataclass(frozen=True)
class ResolvedRecord:
    symbol: str
    defining_module: str
    protected_invariants: tuple[str, ...]


@dataclass(frozen=True)
class PersistedRecord:
    symbol: str
    defining_module: str
    consumer_count: int
    carrying_invariants: tuple[str, ...]


@dataclass(frozen=True)
class EmergedRecord:
    symbol: str
    defining_module: str
    consumer_count: int
    carrying_invariants: tuple[str, ...]
    axiom_mapping: tuple[str, ...]
    suggested_disposition: Literal["REGISTER_ONLY"] = "REGISTER_ONLY"


@dataclass(frozen=True)
class CouplingRecord:
    lease_name: Literal["manifest_lease", "workspace_lease"]
    semantic_domain: str
    call_topology: tuple[str, ...]


@dataclass(frozen=True)
class InventorySnapshot:
    report: InventoryReport
    rendered_pure_markdown: str


@dataclass(frozen=True)
class DeltaReport:
    resolved: tuple[ResolvedRecord, ...]
    persisted: tuple[PersistedRecord, ...]
    emerged: tuple[EmergedRecord, ...]
    coupling: tuple[CouplingRecord, ...]
    module_graph: Mapping[str, tuple[str, ...]]
    frozen_sha256: str
    current_sha256: str


INVARIANT_OWNERSHIP: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType({
    "reclaim_stale_task": ("INV-1",),
    "generation": ("INV-1", "A1"),
    "owner_boot_nonce": ("INV-1", "A1"),
    "probe_peer": ("INV-1",),
    "TERMINAL_RESULT_ALLOWED_FIELDS": ("INV-3",),
    "assert_read_only_sandbox": ("INV-6",),
    "filelock": ("INV-1",),
    "precondition_changed": ("INV-1", "A1"),
    "on_missing_record": ("INV-1",),
    "canonical_artifact_ref": ("INV-7",),
    "format_heartbeat_line": ("C2",),
    "IS_SOLE_PROVIDER_EGRESS": ("INV-9",),
    "ReviewerRateLimitError": ("INV-9",),
    "ReviewerTimeoutError": ("INV-9",),
    "AUDIT_LINE_MAX_BYTES": ("INV-6",),
    "DegradedReason": ("INV-3",),
    "assert_poll_authorized": ("INV-6",),
    "EMOJI_STATUS_OPTIONS": ("INV-2",),
    "STATUS_REGEX_PART": ("INV-2",),
    "StateMachineError": ("INV-2",),
    "VALID_TRANSITIONS": ("INV-2",),
    "_normalize_status": ("INV-2",),
    "_degraded_card": ("INV-3", "C3"),
    "_issue_checkout_lease": ("INV-1",),
})

KNOWN_INVARIANT_GAPS: Final[frozenset[str]] = frozenset({
    "BYPASS_PRESET_CATEGORIES",
    "CONTEXT_SPEC_PATTERN",
    "CRITICAL_CODE_MANIFESTS",
    "CodeExplorerError",
    "Colors",
    "ConsultMode",
    "DEFAULT_AFFECTED_FILES_MTIME_THRESHOLD_SECONDS",
    "DEFAULT_DEADLINE_SECONDS",
    "DEFAULT_HEARTBEAT_SILENCE_THRESHOLD_SECONDS",
    "DEFAULT_MAX_TOTAL_INJECTION_CHARS",
    "DEFAULT_UNMANAGED_DIRS",
    "DEFAULT_WINDOW_LINES",
    "DispatchStrategy",
    "EXCLUDED_WORKSPACE_DIRS",
    "FIELD_ALIASES",
    "FileVerdictAuditSink",
    "JOB_ID_PATTERN",
    "KNOWN_TOP_LEVEL_KEYS",
    "LOG_FILENAME_REGEX",
    "MAX_CONTEXT_FILES",
    "MAX_EXPLORE_FILES",
    "MAX_FILE_BYTES",
    "MAX_HOPS_LIMIT",
    "MAX_INJECTION_CHARS",
    "MAX_LINES_PER_SLICE",
    "MAX_LOG_FILES_QUOTA",
    "MAX_LOG_FILE_BYTES",
    "MAX_QUERY_CHARS",
    "MAX_REASONING_TOKENS_CEILING",
    "MAX_RESPONSE_BYTES",
    "MAX_SLICE_LINES",
    "MAX_TOTAL_INJECTION_CHARS_UPPER",
    "MIN_TOTAL_INJECTION_CHARS",
    "MIN_WINDOW_LINES",
    "MODE_INSTRUCTIONS",
    "NEED_FILES_PATTERN",
    "PROTECTED_CONFIG_NAMES",
    "QuotaResult",
    "REQUIRED_FIELDS",
    "ReadStatus",
    "ReasoningBudgetExceededError",
    "ReconcileEntry",
    "ReviewerHandoff",
    "SCRIPTS_DIR",
    "SENSITIVE_PATTERNS",
    "SERVER_DIR",
    "SSE_IDLE_TIMEOUT_S",
    "STATUS_PATTERN",
    "SkippedFile",
    "SlicedFile",
    "SymbolIface",
    "TASK_DRAFT_PATTERN",
    "TelemetryRecord",
    "UnsafePathError",
    "VALID_AFFECTED_PREFIXES",
    "VALID_MODES",
    "ValidationResult",
    "_ASSERTION_MARKERS",
    "_DEFAULT_CONFIG_VERSION_PATCH",
    "_DEFAULT_FAST_TRACK_PATCH",
    "_DEFAULT_SCHEMA_VERSION_PATCH",
    "_DRIVE",
    "_LOCKS_MUTEX",
    "_MULTI_DOT",
    "_NUL_BYTE_RE",
    "_PREFIX_LOCK",
    "_REVIEWER_LIMITER",
    "_SECRET_REDACTION_PATTERN",
    "_SEEN_DEPRECATED_PROVIDERS",
    "_SESSION_LOCKS",
    "_WINDOWS_RESERVED_NAMES",
    "_WIN_RESERVED_NAMES",
    "__all__",
    "__getattr__",
    "_append_hook_log",
    "_build_quench_stack_config",
    "_calculate_shannon_entropy",
    "_deep_merge_dict",
    "_derive_safety_key_domains",
    "_enforce_log_quota",
    "_evaluate_affected_files_mtime",
    "_extract_affected_files_from_task",
    "_extract_spec_section",
    "_extract_task_detail",
    "_get_git_head_commit",
    "_get_git_tracked_files",
    "_get_session_lock",
    "_glob_to_regex",
    "_is_local_endpoint",
    "_iter_sse_payloads",
    "_lock_local",
    "_match_glob",
    "_normalize_chat_endpoint",
    "_record_from_dict",
    "_render_task_markdown",
    "_resolve_namespaced_id",
    "_resolve_task_file_path",
    "_safe_baseline_filename",
    "_validate_credentials_security",
    "build_safe_slice",
    "check_task_status_guard",
    "cmd_archive",
    "cmd_check",
    "cmd_init",
    "cmd_reviewer_debug",
    "cmd_status",
    "compute_elapsed_s",
    "current_dir",
    "extract_statuses",
    "is_meta_file",
    "is_task_file",
    "is_whitelist_matched",
    "matches_pattern",
    "resolve_path",
    "server_dir",
    "should_enable_color",
})


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

            if rel_posix == OUTPUT_MD_REL or rel_posix.endswith("_frozen.md") or "over_engineering_inventory" in rel_posix:
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


def _assert_balanced_markers(inventory_text: str) -> None:
    """断言 Delta 标记在文本中恰好成对出现（0 对或 1 对），失衡即 fail-closed。"""
    begin_count = inventory_text.count(DELTA_BEGIN_MARK)
    end_count = inventory_text.count(DELTA_END_MARK)
    if begin_count != end_count:
        raise DeltaBlockMalformedError(
            f"Unbalanced delta markers: begin={begin_count}, end={end_count}"
        )
    if begin_count > 1:
        raise DeltaBlockMalformedError(
            f"Duplicate delta markers detected: {begin_count} pairs found"
        )
    if begin_count == 1:
        begin_idx = inventory_text.find(DELTA_BEGIN_MARK)
        end_idx = inventory_text.find(DELTA_END_MARK)
        if end_idx < begin_idx:
            raise DeltaBlockMalformedError(
                "Malformed delta markers: end marker appears before begin marker"
            )


def strip_delta_block(inventory_text: str) -> str:
    """剥离既有 Delta 块，返回纯投影文本。先校验标记平衡。"""
    _assert_balanced_markers(inventory_text)
    if DELTA_BEGIN_MARK not in inventory_text:
        return inventory_text
    pattern = re.compile(
        r"\n*" + re.escape(DELTA_BEGIN_MARK) + r".*?" + re.escape(DELTA_END_MARK) + r"\n*",
        flags=re.DOTALL,
    )
    return pattern.sub("\n\n", inventory_text).strip() + "\n"


def compute_pure_projection_sha256(inventory_text: str) -> str:
    """计算剔除 Delta 块与非门禁遥测段后的纯投影门禁主体 SHA256，保证时间漂移零假红。"""
    pure_text = strip_delta_block(inventory_text)
    gated_text = extract_gated_body(pure_text)
    pure_normalized = gated_text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(pure_normalized.encode("utf-8")).hexdigest()


def atomic_write_text(target_path: Path, text: str) -> None:
    """原子写入文本文件（tmp + os.replace），保证异常时原文件不被破坏。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    unique_suffix = hashlib.sha256(str(time.time_ns()).encode("utf-8")).hexdigest()[:8]
    tmp_path = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}.{unique_suffix}")
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(normalized)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def build_coupling_records(report: InventoryReport) -> tuple[CouplingRecord, ...]:
    """提取双租约调用拓扑结构（manifest_lease 与 workspace_lease）。"""
    records: list[CouplingRecord] = []

    # manifest_lease
    manifest_lease_path = "plugins/quench-dev-tasks/server/manifest_lease.py"
    ml_consumers: set[str] = set()
    for e in report.consumers:
        if e.defined_in == manifest_lease_path:
            ml_consumers.update(e.consumed_by)
    records.append(
        CouplingRecord(
            lease_name="manifest_lease",
            semantic_domain="task_coordination",
            call_topology=tuple(sorted(ml_consumers)),
        )
    )

    # workspace_lease
    workspace_lease_path = "plugins/quench-dev-tasks/server/workspace_lease.py"
    wl_consumers: set[str] = set()
    for e in report.consumers:
        if e.defined_in == workspace_lease_path:
            wl_consumers.update(e.consumed_by)
    records.append(
        CouplingRecord(
            lease_name="workspace_lease",
            semantic_domain="session_cleanup",
            call_topology=tuple(sorted(wl_consumers)),
        )
    )

    return tuple(sorted(records, key=lambda c: (c.lease_name, c.semantic_domain)))


def build_module_graph(report: InventoryReport) -> Mapping[str, tuple[str, ...]]:
    """构建模块依赖邻接表，键升序且邻接 tuple 字典序排序。"""
    prod_mod_map = {Path(m.rel_path).stem: m.rel_path for m in report.modules}
    graph: dict[str, tuple[str, ...]] = {}
    for m in report.modules:
        deps: set[str] = set()
        for imp in m.imported_modules:
            stem = imp.split(".")[-1]
            if stem in prod_mod_map and prod_mod_map[stem] != m.rel_path:
                deps.add(prod_mod_map[stem])
        graph[m.rel_path] = tuple(sorted(deps))
    return MappingProxyType({k: graph[k] for k in sorted(graph.keys())})


def compute_delta_report(
    frozen_path: Path, current_inventory: InventorySnapshot
) -> DeltaReport:
    """对比冻结快照与当前清单，生成五段决策就绪差异报告（Resolved/Persisted/Emerged/Coupling/ModuleGraph）。"""
    if not frozen_path.is_file():
        raise FrozenSnapshotMissingError(f"Frozen snapshot missing: {frozen_path}")

    frozen_bytes = frozen_path.read_bytes()
    frozen_sha256 = hashlib.sha256(frozen_bytes).hexdigest()

    frozen_text = frozen_bytes.decode("utf-8", errors="replace")
    if "## 2. 潜在删除/重构候选清单" not in frozen_text or "## 3. 服务端生产模块概览" not in frozen_text:
        raise FrozenSnapshotUnparsableError("Frozen snapshot missing required section headers")

    sec2 = frozen_text.split("## 2. 潜在删除/重构候选清单", 1)[1].split("## 3. 服务端生产模块概览", 1)[0]
    frozen_cands: list[tuple[str, str]] = []
    for line in sec2.splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", line.strip())
        if m:
            frozen_cands.append((m.group(1), m.group(2)))

    if not frozen_cands and "暂无零消费者候选符号" not in sec2:
        raise FrozenSnapshotUnparsableError("Frozen snapshot section 2 contains no recognizable candidate rows")

    report = current_inventory.report
    curr_defined: dict[tuple[str, str], bool] = {
        (s, m.rel_path): True for m in report.modules for s in m.defined_symbols
    }
    edge_map: dict[tuple[str, str], ConsumerEdge] = {
        (e.symbol, e.defined_in): e for e in report.consumers
    }

    resolved_records: list[ResolvedRecord] = []
    persisted_records: list[PersistedRecord] = []

    for sym, mod in frozen_cands:
        if (sym, mod) not in curr_defined:
            invariants = INVARIANT_OWNERSHIP.get(sym, ())
            resolved_records.append(
                ResolvedRecord(symbol=sym, defining_module=mod, protected_invariants=invariants)
            )
        else:
            edge = edge_map.get((sym, mod))
            consumer_count = len(edge.consumed_by) if edge else 0
            invariants = INVARIANT_OWNERSHIP.get(sym, ())
            if not invariants and sym not in KNOWN_INVARIANT_GAPS:
                raise ValueError(
                    f"Persisted symbol '{sym}' has no carrying invariants and is not in KNOWN_INVARIANT_GAPS (N8 fail-closed)"
                )
            persisted_records.append(
                PersistedRecord(
                    symbol=sym,
                    defining_module=mod,
                    consumer_count=consumer_count,
                    carrying_invariants=invariants,
                )
            )

    frozen_keys = set(frozen_cands)
    emerged_records: list[EmergedRecord] = []
    for cand in report.removal_candidates:
        if (cand.symbol, cand.defined_in) not in frozen_keys:
            invariants = INVARIANT_OWNERSHIP.get(cand.symbol, ())
            emerged_records.append(
                EmergedRecord(
                    symbol=cand.symbol,
                    defining_module=cand.defined_in,
                    consumer_count=len(cand.consumed_by),
                    carrying_invariants=invariants,
                    axiom_mapping=(),
                    suggested_disposition="REGISTER_ONLY",
                )
            )

    coupling_records = build_coupling_records(report)
    module_graph = build_module_graph(report)
    current_sha256 = compute_pure_projection_sha256(current_inventory.rendered_pure_markdown)

    return DeltaReport(
        resolved=tuple(sorted(resolved_records, key=lambda r: (r.defining_module, r.symbol))),
        persisted=tuple(sorted(persisted_records, key=lambda r: (r.defining_module, r.symbol))),
        emerged=tuple(sorted(emerged_records, key=lambda r: (r.defining_module, r.symbol))),
        coupling=tuple(sorted(coupling_records, key=lambda c: (c.lease_name, c.semantic_domain))),
        module_graph=module_graph,
        frozen_sha256=frozen_sha256,
        current_sha256=current_sha256,
    )


def render_delta_report_markdown(delta: DeltaReport) -> str:
    """渲染完全确定性的 v1.20 -> v1.21 架构资产差异报告 (Delta Report)。"""
    lines: list[str] = [
        DELTA_BEGIN_MARK,
        "## 10. v1.20 → v1.21 架构资产差异报告 (Delta Report)",
        "",
        "> **v1.22 授权依据声明**:",
        "> 本报告五段决策就绪维度对齐 v1.22 §4.1 握手规范。",
        "> 任何生产代码删除动作必须以本报告为唯一证据授权（A6 铁律）。",
        "",
        "### 10.1 资产快照哈希对比表 (Hash Parity Table)",
        "",
        "| 资产对象 | 相对路径 | SHA256 校验和 | 说明 |",
        "| :--- | :--- | :--- | :--- |",
        f"| 冻结基线 (v1.20) | `{FROZEN_V120_REL}` | `{delta.frozen_sha256}` | 纯静态冻结归档 |",
        f"| 当前纯投影 (v1.21) | `{CURRENT_INV_REL}` | `{delta.current_sha256}` | 剥离 Delta 段后的纯投影哈希 |",
        "",
        "---",
        "",
        f"### 10.2 已消灭符号清单 (Resolved Symbols, 共 {len(delta.resolved)} 项)",
        "",
        "| 符号 | 原定义模块 | 保护不变量确认 |",
        "| :--- | :--- | :--- |",
    ]

    if not delta.resolved:
        lines.append("| NONE | NONE | 暂无已消灭符号 |")
    else:
        for r in delta.resolved:
            inv_str = ", ".join(f"`{i}`" for i in r.protected_invariants) if r.protected_invariants else "NONE"
            lines.append(f"| `{r.symbol}` | `{r.defining_module}` | {inv_str} |")

    lines.extend([
        "",
        "---",
        "",
        f"### 10.3 延续符号清单 (Persisted Symbols, 共 {len(delta.persisted)} 项)",
        "",
        "| 符号 | 定义模块 | 消费者数 | 承载不变量 |",
        "| :--- | :--- | :--- | :--- |",
    ])

    if not delta.persisted:
        lines.append("| NONE | NONE | 0 | NONE |")
    else:
        for p in delta.persisted:
            inv_str = ", ".join(f"`{i}`" for i in p.carrying_invariants) if p.carrying_invariants else "NONE"
            lines.append(f"| `{p.symbol}` | `{p.defining_module}` | {p.consumer_count} | {inv_str} |")

    lines.extend([
        "",
        "---",
        "",
        f"### 10.4 新暴露候选清单 (Emerged Candidates, 共 {len(delta.emerged)} 项)",
        "",
        "| 符号 | 定义模块 | 消费者数 | 承载不变量 | 公理映射 | 建议裁决 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    if not delta.emerged:
        lines.append("| NONE | NONE | 0 | NONE | NONE | `REGISTER_ONLY` |")
    else:
        for e in delta.emerged:
            inv_str = ", ".join(f"`{i}`" for i in e.carrying_invariants) if e.carrying_invariants else "NONE"
            ax_str = ", ".join(f"`{a}`" for a in e.axiom_mapping) if e.axiom_mapping else "NONE"
            lines.append(f"| `{e.symbol}` | `{e.defining_module}` | {e.consumer_count} | {inv_str} | {ax_str} | `{e.suggested_disposition}` |")

    lines.extend([
        "",
        "---",
        "",
        f"### 10.5 双租约调用拓扑 (Coupling Topology, 共 {len(delta.coupling)} 项)",
        "",
        "| 租约名称 | 语义领域 | 调用拓扑 (`call_topology`) |",
        "| :--- | :--- | :--- |",
    ])

    if not delta.coupling:
        lines.append("| NONE | NONE | NONE |")
    else:
        for c in delta.coupling:
            top_str = _fmt_refs(c.call_topology)
            lines.append(f"| `{c.lease_name}` | `{c.semantic_domain}` | {top_str} |")

    lines.extend([
        "",
        "---",
        "",
        f"### 10.6 生产模块依赖图谱 (Module Import Graph, 共 {len(delta.module_graph)} 个模块)",
        "",
        "| 模块路径 | 依赖生产模块 (`imported_modules`) |",
        "| :--- | :--- |",
    ])

    for mod_path in sorted(delta.module_graph.keys()):
        deps = delta.module_graph[mod_path]
        deps_str = _fmt_refs(deps)
        lines.append(f"| `{mod_path}` | {deps_str} |")

    lines.extend([
        "",
        DELTA_END_MARK,
        "",
    ])

    return "\n".join(lines)


def write_inventory_with_delta(inventory_text: str, delta: DeltaReport) -> str:
    """在清单文本中嵌入 Delta 报告段。必须先剥离旧 Delta 段再嵌入，确保 write(write(x)) == write(x)。"""
    pure_text = strip_delta_block(inventory_text)
    delta_md = render_delta_report_markdown(delta)
    combined = pure_text.rstrip() + "\n\n" + delta_md.strip() + "\n"
    return combined


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口，支持 --write, --check, --delta-report 以及 --repo-root。"""
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
        help="生成并写入资产清单 Markdown 文件（包含纯投影与 Delta 段）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="校验现有资产清单的新鲜度（纯投影与 Delta 段双重一致性）",
    )
    parser.add_argument(
        "--delta-report",
        action="store_true",
        help="纯只读模式：仅向 stdout 打印差异报告，不触碰任何文件",
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
    frozen_file = repo_root / FROZEN_V120_REL

    if args.delta_report:
        if not frozen_file.is_file():
            print(f"Missing frozen snapshot file: {frozen_file}", file=sys.stderr)
            return EXIT_USAGE
        report = build_inventory_report(repo_root)
        rendered_pure = render_markdown(report)
        snapshot = InventorySnapshot(report=report, rendered_pure_markdown=rendered_pure)
        try:
            delta = compute_delta_report(frozen_file, snapshot)
        except Exception as e:
            print(f"Delta report calculation failed: {e}", file=sys.stderr)
            return EXIT_DRIFT
        delta_md = render_delta_report_markdown(delta)
        try:
            sys.stdout.write(delta_md)
        except UnicodeEncodeError:
            sys.stdout.buffer.write(delta_md.encode("utf-8"))
        return EXIT_OK

    elif args.check:
        if not out_file.is_file():
            print(f"Missing inventory file: {out_file}", file=sys.stderr)
            return EXIT_USAGE

        raw_bytes = out_file.read_bytes()
        if b"\r\n" in raw_bytes:
            print("CRLF line endings detected in inventory file!", file=sys.stderr)
            return EXIT_DRIFT

        existing_text = out_file.read_text(encoding="utf-8")
        try:
            _assert_balanced_markers(existing_text)
        except DeltaBlockMalformedError as e:
            print(f"Marker balance check failed: {e}", file=sys.stderr)
            return EXIT_DRIFT

        if not frozen_file.is_file():
            print(f"Missing frozen snapshot file: {frozen_file}", file=sys.stderr)
            return EXIT_USAGE

        report = build_inventory_report(repo_root)
        new_pure_text = render_markdown(report)
        snapshot = InventorySnapshot(report=report, rendered_pure_markdown=new_pure_text)
        try:
            delta = compute_delta_report(frozen_file, snapshot)
        except Exception as e:
            print(f"Delta report generation failed: {e}", file=sys.stderr)
            return EXIT_DRIFT

        existing_pure = strip_delta_block(existing_text)
        existing_gated = extract_gated_body(existing_pure)
        new_gated = extract_gated_body(new_pure_text)

        if existing_gated != new_gated:
            print("Drift detected between codebase and inventory report pure projection!", file=sys.stderr)
            return EXIT_DRIFT

        if DELTA_BEGIN_MARK not in existing_text:
            print("Delta report block missing in existing inventory file!", file=sys.stderr)
            return EXIT_DRIFT

        existing_delta_block = existing_text[
            existing_text.find(DELTA_BEGIN_MARK) : existing_text.find(DELTA_END_MARK) + len(DELTA_END_MARK)
        ]
        expected_delta_block = render_delta_report_markdown(delta).strip()

        if existing_delta_block != expected_delta_block:
            print("Drift detected in Delta report block!", file=sys.stderr)
            return EXIT_DRIFT

        print("Freshness check passed: inventory matches codebase.", file=sys.stdout)
        return EXIT_OK

    else:
        # 默认模式（或显式 --write）：生成并写入资产清单
        if not frozen_file.is_file():
            print(f"Missing frozen snapshot file: {frozen_file}", file=sys.stderr)
            return EXIT_USAGE

        report = build_inventory_report(repo_root)
        rendered_pure = render_markdown(report)
        snapshot = InventorySnapshot(report=report, rendered_pure_markdown=rendered_pure)
        try:
            delta = compute_delta_report(frozen_file, snapshot)
        except Exception as e:
            print(f"Delta report generation failed: {e}", file=sys.stderr)
            return EXIT_DRIFT

        full_content = write_inventory_with_delta(rendered_pure, delta)
        atomic_write_text(out_file, full_content)
        print(f"Successfully generated inventory: {out_file}", file=sys.stdout)
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
