#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""scripts/check_prompt_surface.py — Pure AST static contract gate for Prompt Surface (P1~P5).

Guarantees:
1. P1: Tool set integrity against tool_surface_constants, complete Google-style Args: docstrings.
2. P2: Envelope metadata freshness and non-empty schema parameter descriptions (>= 8 chars).
3. P3: Live docs code fences have zero banned call keyword leaks.
4. P4: Example call keyword validity in markdown code blocks across the workspace.
5. P5: Historical allowlist discipline requiring explicit line-level exemption markers.

Zero third-party runtime dependencies, stdout purity reserved for JSON-RPC (INV-4).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterable, Mapping, Sequence

EXIT_OK: Final[int] = 0
EXIT_VIOLATION: Final[int] = 1
EXIT_INTERNAL: Final[int] = 2

# 历史/审计文档白名单：新增条目须经 Reviewer 批准，并受单测锚定（R3）
HISTORICAL_ALLOWLIST: Final[frozenset[str]] = frozenset({
    "CHANGELOG.md",
    "docs/ci_incident_tracker_and_compatibility_guide.md",
})

# 任务单与归档目录一律排除，防止门禁自锁（R2）
EXCLUDED_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "docs/dev_tasks/",
    "docs/archive/",
    "docs/roadmap/archive/",
)
EXEMPTION_MARKER: Final[str] = "quench-prompt-surface:historical"
CALL_KEYWORD_RE: Final[re.Pattern[str]] = re.compile(r"\braw_text\s*=\s*(?:True|False)\b")
MIN_PARAM_DESC_CHARS: Final[int] = 8

# FastMCP / 框架自动注入形参白名单（由框架在运行时提供，不暴露于 JSON Schema 输入且在文档检查中豁免）
INJECTED_FRAMEWORK_PARAMS: Final[frozenset[str]] = frozenset({"self", "ctx", "context"})

LIVE_DOCS: Final[frozenset[str]] = frozenset({
    "README.md",
    "README_zh.md",
    "docs/configuration.md",
    "dev_tasks_mcp_specification.md",
    "docs/architecture/README.md",
    "plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md",
    "plugins/quench-dev-tasks/rules/dev-tasks-discipline.md",
})


@dataclass(frozen=True)
class LintFinding:
    rule: str
    file_path: str
    line_number: int
    message: str


def _get_server_dir(repo_root: Path) -> Path:
    return repo_root / "plugins" / "quench-dev-tasks" / "server"


def _ensure_tool_surface_constants(repo_root: Path) -> None:
    server_dir = _get_server_dir(repo_root)
    s_str = str(server_dir)
    if s_str not in sys.path:
        sys.path.insert(0, s_str)


def extract_server_signatures(server_py: Path) -> dict[str, frozenset[str]]:
    """Extract tool names and their non-injected parameter names via pure AST."""
    if not server_py.is_file():
        return {}
    content = server_py.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(server_py))
    sigs: dict[str, frozenset[str]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_tool = any(
                (isinstance(d, ast.Attribute) and d.attr == "tool")
                or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool")
                for d in node.decorator_list
            )
            if is_tool:
                params = [a.arg for a in node.args.args if a.arg not in INJECTED_FRAMEWORK_PARAMS]
                sigs[node.name] = frozenset(params)
    return sigs


def extract_mcp_tool_names(server_py: Path) -> frozenset[str]:
    """Extract all @mcp.tool decorated function names via pure AST."""
    return frozenset(extract_server_signatures(server_py).keys())


def _parse_docstring_args(docstring: str) -> dict[str, str]:
    """Parse parameter descriptions from Google-style docstring Args: section."""
    if not docstring or "Args:" not in docstring:
        return {}
    after_args = docstring.split("Args:", 1)[1]

    section_stops = (
        "\n    Returns:", "\n    Raises:", "\n    Yields:",
        "\n    Examples:", "\n    Example:", "\n    Note:", "\n    Notes:",
        "\nReturns:", "\nRaises:", "\nYields:", "\nExamples:", "\nExample:",
    )
    for stop in section_stops:
        if stop in after_args:
            after_args = after_args.split(stop, 1)[0]

    params: dict[str, str] = {}
    curr_name: str | None = None
    curr_desc_lines: list[str] = []

    param_line_re = re.compile(r"^\s*([a-zA-Z_]\w*)\s*(?:\([^)]+\))?\s*:\s*(.*)$")

    for line in after_args.splitlines():
        match = param_line_re.match(line)
        if match:
            if curr_name is not None:
                params[curr_name] = " ".join(curr_desc_lines).strip()
            curr_name = match.group(1)
            curr_desc_lines = [match.group(2).strip()]
        elif curr_name is not None:
            stripped = line.strip()
            if stripped:
                curr_desc_lines.append(stripped)

    if curr_name is not None:
        params[curr_name] = " ".join(curr_desc_lines).strip()

    return params


def check_docstring_args(server_py: Path, expected_tools: frozenset[str]) -> list[LintFinding]:
    """P1: Inspect tool definitions for Args: completeness and length."""
    findings: list[LintFinding] = []
    if not server_py.is_file():
        findings.append(LintFinding("P1_SERVER_PY_MISSING", str(server_py), 1, "server.py not found"))
        return findings

    content = server_py.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(server_py))

    tools_in_ast: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_tool = any(
                (isinstance(d, ast.Attribute) and d.attr == "tool")
                or (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool")
                for d in node.decorator_list
            )
            if is_tool:
                tools_in_ast[node.name] = node

    ast_tool_names = frozenset(tools_in_ast.keys())
    if ast_tool_names != expected_tools:
        missing = expected_tools - ast_tool_names
        extra = ast_tool_names - expected_tools
        findings.append(
            LintFinding(
                "P1_TOOL_SET_DRIFT",
                str(server_py),
                1,
                f"Tool set mismatch between AST and expected. Missing: {sorted(missing)}, Extra: {sorted(extra)}",
            )
        )

    for tool_name, node in sorted(tools_in_ast.items()):
        doc = ast.get_docstring(node)
        if not doc or not doc.strip():
            findings.append(
                LintFinding("P1_DOCSTRING_MISSING", str(server_py), node.lineno, f"Tool '{tool_name}' lacks docstring")
            )
            continue

        if "Args:" not in doc:
            findings.append(
                LintFinding("P1_ARGS_BLOCK_MISSING", str(server_py), node.lineno, f"Tool '{tool_name}' lacks Google-style 'Args:' block")
            )
            continue

        documented = _parse_docstring_args(doc)
        sig_params = [a.arg for a in node.args.args if a.arg not in INJECTED_FRAMEWORK_PARAMS]

        for p in sig_params:
            if p not in documented:
                findings.append(
                    LintFinding(
                        "P1_PARAM_UNDOCUMENTED",
                        str(server_py),
                        node.lineno,
                        f"Tool '{tool_name}' parameter '{p}' is not documented in Args: block",
                    )
                )
            else:
                desc = documented[p]
                if len(desc) < MIN_PARAM_DESC_CHARS:
                    findings.append(
                        LintFinding(
                            "P1_PARAM_DESC_TOO_SHORT",
                            str(server_py),
                            node.lineno,
                            f"Tool '{tool_name}' parameter '{p}' description too short ({len(desc)} < {MIN_PARAM_DESC_CHARS})",
                        )
                    )

        for p in documented:
            if p not in sig_params and p not in INJECTED_FRAMEWORK_PARAMS:
                findings.append(
                    LintFinding(
                        "P1_PARAM_UNKNOWN",
                        str(server_py),
                        node.lineno,
                        f"Tool '{tool_name}' Args: documents unknown parameter '{p}' not in signature",
                    )
                )
            elif p in INJECTED_FRAMEWORK_PARAMS:
                desc = documented[p]
                if len(desc) < MIN_PARAM_DESC_CHARS:
                    findings.append(
                        LintFinding(
                            "P1_PARAM_DESC_TOO_SHORT",
                            str(server_py),
                            node.lineno,
                            f"Tool '{tool_name}' framework parameter '{p}' description too short ({len(desc)} < {MIN_PARAM_DESC_CHARS})",
                        )
                    )

    return findings


def check_schema_descriptions(snapshot: Path, expected_tools: frozenset[str]) -> list[LintFinding]:
    """P2: Validate envelope freshness and parameter description completeness in IDE schemas snapshot."""
    findings: list[LintFinding] = []
    if not snapshot.is_file():
        findings.append(LintFinding("P2_SNAPSHOT_MISSING", str(snapshot), 1, "Snapshot ide_tool_schemas.json not found"))
        return findings

    try:
        data = json.loads(snapshot.read_text(encoding="utf-8"))
    except Exception as e:
        findings.append(LintFinding("P2_SNAPSHOT_INVALID_JSON", str(snapshot), 1, f"Failed to parse JSON: {e}"))
        return findings

    repo_root = snapshot.parent.parent if snapshot.parent.name == "architecture" else snapshot.parent
    _ensure_tool_surface_constants(repo_root)
    from tool_surface_constants import SNAPSHOT_SCHEMA_VERSION, TOOL_COUNT

    meta = data.get("_meta")
    if not isinstance(meta, dict):
        findings.append(LintFinding("P2_ENVELOPE_DRIFT", str(snapshot), 1, "Snapshot missing '_meta' envelope object"))
        return findings

    if meta.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        findings.append(
            LintFinding(
                "P2_ENVELOPE_DRIFT",
                str(snapshot),
                1,
                f"schema_version mismatch: got {meta.get('schema_version')}, expected {SNAPSHOT_SCHEMA_VERSION}",
            )
        )

    tools_in_snapshot = frozenset(k for k in data.keys() if k != "_meta")
    if tools_in_snapshot != expected_tools or len(tools_in_snapshot) != TOOL_COUNT:
        findings.append(
            LintFinding(
                "P2_ENVELOPE_DRIFT",
                str(snapshot),
                1,
                f"Tool count or names mismatch: snapshot has {len(tools_in_snapshot)} tools, expected {TOOL_COUNT}",
            )
        )

    for tool_name in sorted(expected_tools):
        t_data = data.get(tool_name)
        if not isinstance(t_data, dict):
            continue
        props = None
        if "properties" in t_data and isinstance(t_data["properties"], dict):
            props = t_data["properties"]
        elif "parameters" in t_data and isinstance(t_data["parameters"], dict):
            p_obj = t_data["parameters"]
            if "properties" in p_obj and isinstance(p_obj["properties"], dict):
                props = p_obj["properties"]

        if props:
            for param_name, p_info in sorted(props.items()):
                if not isinstance(p_info, dict):
                    continue
                desc = p_info.get("description", "")
                if not isinstance(desc, str) or len(desc.strip()) < MIN_PARAM_DESC_CHARS:
                    findings.append(
                        LintFinding(
                            "P2_PARAM_DESC_TOO_SHORT",
                            str(snapshot),
                            1,
                            f"Tool '{tool_name}' parameter '{param_name}' description in ide_tool_schemas.json is too short ({len(desc.strip()) if isinstance(desc, str) else 0} < {MIN_PARAM_DESC_CHARS})",
                        )
                    )

    return findings


def check_live_doc_call_keywords(doc_roots: Sequence[Path]) -> list[LintFinding]:
    """P3: Inspect live doc whitelist code fences. Any occurrence of CALL_KEYWORD_RE is a violation."""
    findings: list[LintFinding] = []
    for root in doc_roots:
        for rel_path in sorted(LIVE_DOCS):
            target = root / rel_path
            if not target.is_file():
                continue
            lines = target.read_text(encoding="utf-8").splitlines()
            in_fence = False
            for line_no, line in enumerate(lines, start=1):
                stripped = line.strip()
                if stripped.startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence and CALL_KEYWORD_RE.search(line):
                    findings.append(
                        LintFinding(
                            "P3_LIVE_DOC_KEYWORD_LEAK",
                            str(target),
                            line_no,
                            f"Live doc '{rel_path}' contains banned keyword pattern in code fence: {line.strip()}",
                        )
                    )
    return findings


def check_example_call_keywords(
    doc_roots: Sequence[Path], signatures: Mapping[str, frozenset[str]]
) -> list[LintFinding]:
    """P4: Scan python code fences in markdown files across doc_roots for unknown keyword calls."""
    findings: list[LintFinding] = []
    for root in doc_roots:
        for md_file in sorted(root.rglob("*.md")):
            rel_str = md_file.relative_to(root).as_posix()
            if any(rel_str.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES):
                continue
            if rel_str in HISTORICAL_ALLOWLIST:
                continue

            lines = md_file.read_text(encoding="utf-8", errors="replace").splitlines()
            in_fence = False
            fence_lang = ""
            fence_start_line = 0
            fence_has_exemption = False
            fence_lines: list[str] = []

            for line_no, line in enumerate(lines, start=1):
                stripped = line.strip()
                if stripped.startswith("```"):
                    if not in_fence:
                        in_fence = True
                        fence_start_line = line_no
                        tag = stripped[3:].strip()
                        fence_lang = tag.split()[0].lower() if tag else ""
                        fence_has_exemption = EXEMPTION_MARKER in line
                        fence_lines = []
                    else:
                        in_fence = False
                        if fence_has_exemption:
                            continue
                        if fence_lines and EXEMPTION_MARKER in fence_lines[0]:
                            continue
                        if fence_lang not in ("python", "py", ""):
                            continue

                        code_str = "\n".join(fence_lines)
                        if not any(t in code_str for t in signatures):
                            continue

                        tree = None
                        try:
                            tree = ast.parse(code_str)
                        except SyntaxError:
                            try:
                                indented = "\n".join("    " + l for l in fence_lines)
                                wrapped = f"async def _quench_dummy():\n{indented}"
                                tree = ast.parse(wrapped)
                            except SyntaxError:
                                pass

                        if tree is not None:
                            for node in ast.walk(tree):
                                if isinstance(node, ast.Call):
                                    func_name = None
                                    if isinstance(node.func, ast.Name):
                                        func_name = node.func.id
                                    elif isinstance(node.func, ast.Attribute):
                                        func_name = node.func.attr

                                    if func_name and func_name in signatures:
                                        allowed = signatures[func_name]
                                        for kw in node.keywords:
                                            if kw.arg is not None and kw.arg not in allowed:
                                                call_lineno = fence_start_line + getattr(kw, "lineno", 1)
                                                findings.append(
                                                    LintFinding(
                                                        "P4_UNKNOWN_KEYWORD",
                                                        str(md_file),
                                                        call_lineno,
                                                        f"Call to '{func_name}' has unknown keyword argument '{kw.arg}'. Allowed: {sorted(allowed)}",
                                                    )
                                                )
                elif in_fence:
                    fence_lines.append(line)

    return findings


def check_historical_allowlist_discipline(doc_roots: Sequence[Path]) -> list[LintFinding]:
    """P5: Require explicit exemption marker on same or preceding line for banned keywords in historical files."""
    findings: list[LintFinding] = []
    for root in doc_roots:
        for rel_path in sorted(HISTORICAL_ALLOWLIST):
            target = root / rel_path
            if not target.is_file():
                continue
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            for idx, line in enumerate(lines):
                if CALL_KEYWORD_RE.search(line):
                    has_marker = (EXEMPTION_MARKER in line) or (idx > 0 and EXEMPTION_MARKER in lines[idx - 1])
                    if not has_marker:
                        findings.append(
                            LintFinding(
                                "P5_HISTORICAL_MISSING_EXEMPTION",
                                str(target),
                                idx + 1,
                                f"Historical file '{rel_path}' contains '{line.strip()}' without mandatory '{EXEMPTION_MARKER}' on same or preceding line",
                            )
                        )
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for Prompt-Surface contract gate. Zero stdout print (INV-4)."""
    parser = argparse.ArgumentParser(description="Prompt-Surface contract gate (P1~P5)")
    parser.add_argument("--check", action="store_true", help="Perform read-only verification")
    parser.add_argument("--workspace", type=str, default=None, help="Root path of workspace")
    args = parser.parse_args(argv)

    try:
        repo_root = Path(args.workspace).resolve() if args.workspace else Path.cwd().resolve()
        _ensure_tool_surface_constants(repo_root)
        from tool_surface_constants import EXPECTED_TOOL_NAMES, TOOL_COUNT

        server_py = repo_root / "plugins" / "quench-dev-tasks" / "server" / "server.py"
        snapshot_json = repo_root / "docs" / "architecture" / "ide_tool_schemas.json"

        signatures = extract_server_signatures(server_py)
        all_findings: list[LintFinding] = []

        # P1
        all_findings.extend(check_docstring_args(server_py, EXPECTED_TOOL_NAMES))
        # P2
        all_findings.extend(check_schema_descriptions(snapshot_json, EXPECTED_TOOL_NAMES))
        # P3
        all_findings.extend(check_live_doc_call_keywords([repo_root]))
        # P4
        all_findings.extend(check_example_call_keywords([repo_root], signatures))
        # P5
        all_findings.extend(check_historical_allowlist_discipline([repo_root]))

        if all_findings:
            print("\n" + "=" * 70, file=sys.stderr)
            print("🛑 [Prompt Surface Gate] Violations detected (P1~P5):", file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            for f in all_findings:
                print(f"  ❌ [{f.rule}] {f.file_path}:{f.line_number} — {f.message}", file=sys.stderr)
            print(f"\nTotal violations: {len(all_findings)}\n", file=sys.stderr)
            return EXIT_VIOLATION

        print("✅ Prompt-Surface contract check passed (P1~P5: 0 violations).", file=sys.stderr)
        return EXIT_OK
    except Exception as exc:
        print(f"💥 Internal error during prompt surface check: {exc}", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
