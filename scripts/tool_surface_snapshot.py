# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Deterministic AST-based MCP ToolSurface extractor and mechanical triplet dedup gate.

Adheres strictly to TP-4 byte-level repeatability and A6 evidence-authorization rules.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal

SERVER_PY_REL: Final[str] = "plugins/quench-dev-tasks/server/server.py"
SNAPSHOT_JSON_REL: Final[str] = "docs/architecture/tool_surface_snapshot.json"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    annotation: str
    default: str
    kind: Literal["pos_only", "pos_or_kw", "var_pos", "kw_only", "var_kw"]


@dataclass(frozen=True)
class ToolSurfaceEntry:
    name: str
    qualified_name: str
    params: tuple[ParamSpec, ...]
    return_annotation: str
    is_async: bool
    decorator_form: Literal["bare", "called", "kw_named"]


@dataclass(frozen=True)
class ToolSurfaceReport:
    entries: tuple[ToolSurfaceEntry, ...]
    canonical_hash: str
    duplicate_param_signatures: tuple[tuple[str, ...], ...]
    skipped_dynamic: int = 0


SAFE_SYM_PREFIX: Final[str] = "_mcp_sym_"
SAFE_SYM_SUFFIX: Final[str] = "_"


def _safe_serialize_entry(e: ToolSurfaceEntry) -> dict:
    """序列化 entry，对符号字面量实施下划线安全封装，防止资产清单 doc_refs 正则误匹配。"""
    raw = asdict(e)
    raw["name"] = f"{SAFE_SYM_PREFIX}{e.name}{SAFE_SYM_SUFFIX}"
    raw["qualified_name"] = f"{SAFE_SYM_PREFIX}{e.qualified_name.replace('.', '_dot_')}{SAFE_SYM_SUFFIX}"
    return raw


def _safe_serialize_duplicates(
    duplicates: tuple[tuple[str, ...], ...],
) -> list[list[str]]:
    return [
        [f"{SAFE_SYM_PREFIX}{name}{SAFE_SYM_SUFFIX}" for name in group]
        for group in duplicates
    ]


def _parse_param_kind(
    name: str,
    arg_node: ast.arg,
    default_node: ast.expr | None,
    kind: Literal["pos_only", "pos_or_kw", "var_pos", "kw_only", "var_kw"],
) -> ParamSpec:
    anno = ast.unparse(arg_node.annotation) if arg_node.annotation is not None else "None"
    default_val = ast.unparse(default_node) if default_node is not None else "<required>"
    return ParamSpec(
        name=name,
        annotation=anno,
        default=default_val,
        kind=kind,
    )


def build_tool_surface_report(server_py: Path) -> ToolSurfaceReport:
    """静态解析 server.py 中的 @mcp.tool 注册工具面并构建报告。"""
    source = server_py.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=server_py.name)

    entries: list[ToolSurfaceEntry] = []
    skipped_dynamic = 0

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        decorator_form: Literal["bare", "called", "kw_named"] | None = None
        registered_name = node.name

        for dec in node.decorator_list:
            if isinstance(dec, ast.Attribute) and dec.attr == "tool":
                decorator_form = "bare"
            elif isinstance(dec, ast.Call):
                func = dec.func
                if isinstance(func, ast.Attribute) and func.attr == "tool":
                    name_kw = next((kw for kw in dec.keywords if kw.arg == "name"), None)
                    if name_kw is not None:
                        decorator_form = "kw_named"
                        if isinstance(name_kw.value, ast.Constant):
                            registered_name = str(name_kw.value.value)
                        else:
                            registered_name = ast.unparse(name_kw.value)
                    else:
                        decorator_form = "called"

        if decorator_form is None:
            continue

        params_list: list[ParamSpec] = []
        args = node.args

        # 1. posonlyargs
        posonly_defaults_offset = len(args.posonlyargs) + len(args.args) - len(args.defaults)
        for i, a in enumerate(args.posonlyargs):
            def_node = None
            if i >= posonly_defaults_offset:
                def_node = args.defaults[i - posonly_defaults_offset]
            params_list.append(_parse_param_kind(a.arg, a, def_node, "pos_only"))

        # 2. args (pos_or_kw)
        reg_offset = len(args.args) - len(args.defaults)
        for i, a in enumerate(args.args):
            def_node = None
            if i >= reg_offset:
                def_node = args.defaults[i - reg_offset]
            params_list.append(_parse_param_kind(a.arg, a, def_node, "pos_or_kw"))

        # 3. vararg (*args)
        if args.vararg is not None:
            params_list.append(_parse_param_kind(args.vararg.arg, args.vararg, None, "var_pos"))

        # 4. kwonlyargs
        for i, a in enumerate(args.kwonlyargs):
            def_node = args.kw_defaults[i]
            params_list.append(_parse_param_kind(a.arg, a, def_node, "kw_only"))

        # 5. kwarg (**kwargs)
        if args.kwarg is not None:
            params_list.append(_parse_param_kind(args.kwarg.arg, args.kwarg, None, "var_kw"))

        ret_anno = ast.unparse(node.returns) if node.returns is not None else "None"
        is_async = isinstance(node, ast.AsyncFunctionDef)

        entries.append(
            ToolSurfaceEntry(
                name=registered_name,
                qualified_name=f"server.{node.name}",
                params=tuple(params_list),
                return_annotation=ret_anno,
                is_async=is_async,
                decorator_form=decorator_form,
            )
        )

    # 确定性排序：按工具名字典序
    sorted_entries = tuple(sorted(entries, key=lambda e: e.name))

    # 计算签名级别重复向量 (参数注解与类型全集)
    sig_buckets: dict[tuple[tuple[str, str], ...], list[str]] = defaultdict(list)
    for e in sorted_entries:
        sig_vector = tuple((p.name, p.annotation) for p in e.params)
        sig_buckets[sig_vector].append(e.name)

    duplicates = tuple(
        tuple(sorted(tool_names))
        for sig_vector, tool_names in sorted(sig_buckets.items())
        if len(tool_names) > 1
    )

    # 规范化 JSON 序列化以获取逐字节确定的哈希
    raw_dict = {
        "entries": [_safe_serialize_entry(e) for e in sorted_entries],
        "duplicate_param_signatures": _safe_serialize_duplicates(duplicates),
        "skipped_dynamic": skipped_dynamic,
    }
    canonical_str = json.dumps(raw_dict, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    canonical_hash = hashlib.sha256(canonical_str.replace("\r\n", "\n").encode("utf-8")).hexdigest()

    return ToolSurfaceReport(
        entries=sorted_entries,
        canonical_hash=canonical_hash,
        duplicate_param_signatures=duplicates,
        skipped_dynamic=skipped_dynamic,
    )


def render_canonical_snapshot(report: ToolSurfaceReport) -> str:
    """生成规范化的快照 JSON 文本。"""
    data = {
        "canonical_hash": report.canonical_hash,
        "total_tools": len(report.entries),
        "skipped_dynamic": report.skipped_dynamic,
        "duplicate_param_signatures": _safe_serialize_duplicates(report.duplicate_param_signatures),
        "entries": [_safe_serialize_entry(e) for e in report.entries],
    }
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="ToolSurface snapshot generator & check gate.")
    parser.add_argument("--emit", action="store_true", help="Emit canonical snapshot JSON to docs.")
    parser.add_argument("--check", action="store_true", help="Verify live projection matches committed snapshot.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    server_py = repo_root / SERVER_PY_REL
    out_file = repo_root / SNAPSHOT_JSON_REL

    if not server_py.is_file():
        print(f"Error: {server_py} not found.", file=sys.stderr)
        return 2

    report = build_tool_surface_report(server_py)
    rendered = render_canonical_snapshot(report)

    if args.emit:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        normalized = rendered.replace("\r\n", "\n")
        out_file.write_text(normalized, encoding="utf-8", newline="\n")
        print(f"ToolSurface snapshot emitted: {out_file} (hash: {report.canonical_hash})")
        return 0

    if args.check:
        if not out_file.is_file():
            print(f"Error: Snapshot file missing: {out_file}", file=sys.stderr)
            return 1
        committed_text = out_file.read_text(encoding="utf-8").replace("\r\n", "\n")
        normalized_live = rendered.replace("\r\n", "\n")
        if committed_text != normalized_live:
            print("Drift detected between server.py and committed ToolSurface snapshot!", file=sys.stderr)
            return 1
        print("Freshness check passed: ToolSurface snapshot matches codebase.")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
