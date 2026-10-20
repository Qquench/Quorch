"""_tool_surface_expectations.py - AST extractor and expectations helper for tool surface contracts.

MODULE-LEVEL INVARIANT: Zero import of server, fastmcp, yaml, or network. Pure AST inspection only.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping

from tool_surface_constants import (
    CTX_PARAM_ALIASES,
    EXPECTED_TOOL_NAMES,
    TOOL_ALLOWS_CTX,
    TOOL_COUNT,
)

SERVER_SOURCE_PATH: Final[Path] = Path(__file__).resolve().parents[1] / "server.py"
SNAPSHOT_PATH: Final[Path] = (
    Path(__file__).resolve().parents[4] / "docs" / "architecture" / "ide_tool_schemas.json"
)


class ToolSurfaceError(Exception):
    """Raised when tool surface extraction or validation fails."""
    pass


@dataclass(frozen=True, slots=True)
class ToolSurfaceEntry:
    name: str
    params: frozenset[str]
    non_ctx_params: frozenset[str]
    ctx_params: frozenset[str]
    defaults: tuple[tuple[str, Any], ...]

    @property
    def default_map(self) -> Mapping[str, Any]:
        return dict(self.defaults)

    def __hash__(self) -> int:
        def _to_hashable(v: Any) -> Any:
            if isinstance(v, list):
                return tuple(_to_hashable(x) for x in v)
            if isinstance(v, dict):
                return tuple(sorted((k, _to_hashable(val)) for k, val in v.items()))
            return v

        return hash((
            self.name,
            self.params,
            self.non_ctx_params,
            self.ctx_params,
            tuple((k, _to_hashable(v)) for k, v in self.defaults),
        ))


@dataclass(frozen=True, slots=True)
class ToolSurfaceReport:
    entries: tuple[ToolSurfaceEntry, ...]


def json_projection(value: Any) -> Any:
    """Normalize python values to JSON canonical types with ensure_ascii=False, allow_nan=False."""
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _is_tool_fn(fn: ast.AST) -> bool:
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if fn.name == "tool":
        return True
    for d in fn.decorator_list:
        if isinstance(d, ast.Call):
            d = d.func
        if isinstance(d, ast.Attribute) and d.attr == "tool":
            return True
        if isinstance(d, ast.Name) and d.id == "tool":
            return True
    return False


def _is_ctx_arg(arg: ast.arg) -> bool:
    if arg.arg in CTX_PARAM_ALIASES:
        return True
    if arg.annotation is not None:
        for node in ast.walk(arg.annotation):
            if isinstance(node, ast.Name) and node.id == "Context":
                return True
            if isinstance(node, ast.Attribute) and node.attr == "Context":
                return True
            if isinstance(node, ast.Constant) and node.value == "Context":
                return True
    return False


def extract_tool_surface_from_source(source: str, *, filename: str = "<server.py>") -> ToolSurfaceReport:
    tree = ast.parse(source, filename=filename)
    entries: list[ToolSurfaceEntry] = []

    for node in ast.walk(tree):
        if not _is_tool_fn(node):
            continue
        fn: ast.FunctionDef | ast.AsyncFunctionDef = node  # type: ignore

        if fn.args.vararg is not None or fn.args.kwarg is not None:
            raise ToolSurfaceError(
                f"{filename}:{fn.name} 不允许使用可变参数 (*args 或 **kwargs)"
            )

        posonly = [a for a in fn.args.posonlyargs]
        pos_or_kw = [a for a in fn.args.args]
        kwonly = [a for a in fn.args.kwonlyargs]
        all_args = posonly + pos_or_kw + kwonly

        param_names = [a.arg for a in all_args]
        params_set = frozenset(param_names)

        ctx_set = frozenset(a.arg for a in all_args if _is_ctx_arg(a))
        non_ctx_set = params_set - ctx_set

        # Extract defaults
        defaults_list: list[tuple[str, Any]] = []

        # Positional defaults match the end of posonly + pos_or_kw
        reg_args = posonly + pos_or_kw
        reg_defaults = fn.args.defaults
        if reg_defaults:
            default_start_idx = len(reg_args) - len(reg_defaults)
            for arg, def_node in zip(reg_args[default_start_idx:], reg_defaults):
                try:
                    val = ast.literal_eval(def_node)
                except Exception as exc:
                    raise ToolSurfaceError(
                        f"{filename}:{fn.name}.{arg.arg} 默认值非字面量: {exc}"
                    ) from exc
                defaults_list.append((arg.arg, json_projection(val)))

        # Keyword-only defaults
        if kwonly:
            for arg, def_node in zip(kwonly, fn.args.kw_defaults):
                if def_node is not None:
                    try:
                        val = ast.literal_eval(def_node)
                    except Exception as exc:
                        raise ToolSurfaceError(
                            f"{filename}:{fn.name}.{arg.arg} 默认值非字面量: {exc}"
                        ) from exc
                    defaults_list.append((arg.arg, json_projection(val)))

        entries.append(
            ToolSurfaceEntry(
                name=fn.name,
                params=params_set,
                non_ctx_params=non_ctx_set,
                ctx_params=ctx_set,
                defaults=tuple(defaults_list),
            )
        )

    # Sort entries by name for determinism
    entries.sort(key=lambda e: e.name)
    return ToolSurfaceReport(entries=tuple(entries))


def derive_live_tool_surface() -> ToolSurfaceReport:
    source = SERVER_SOURCE_PATH.read_text(encoding="utf-8")
    return extract_tool_surface_from_source(source, filename=str(SERVER_SOURCE_PATH))


def assert_surface_well_formed(report: ToolSurfaceReport, expected: frozenset[str]) -> None:
    names = frozenset(e.name for e in report.entries)
    if names != expected:
        raise AssertionError(f"工具集合不匹配: 期望 {sorted(expected)}, 实际 {sorted(names)}")
    if len(report.entries) != len(expected):
        raise AssertionError(f"工具条目数不匹配: 期望 {len(expected)}, 实际 {len(report.entries)}")
    for e in report.entries:
        if e.non_ctx_params & e.ctx_params:
            raise AssertionError(f"工具 {e.name} 的 non_ctx_params 与 ctx_params 存在交集: {e.non_ctx_params & e.ctx_params}")
        if e.non_ctx_params | e.ctx_params != e.params:
            raise AssertionError(f"工具 {e.name} 参数分解不守恒")


def assert_ctx_surface(report: ToolSurfaceReport) -> None:
    ctx_tools = frozenset(e.name for e in report.entries if e.ctx_params)
    if ctx_tools != TOOL_ALLOWS_CTX:
        raise AssertionError(f"允许 ctx 的工具集合不匹配: 期望 {sorted(TOOL_ALLOWS_CTX)}, 实际 {sorted(ctx_tools)}")
