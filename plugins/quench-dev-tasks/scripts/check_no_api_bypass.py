#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quench AST Static Scanner: Reviewer API Egress & Bypass Enforcer.

Enforces the core architectural invariant:
"reviewer_engine.py is the ONLY authorized external network egress for Reviewer model providers."

Detects and intercepts:
1. Unauthorized provider SDK imports (e.g. openai, anthropic, google.generativeai, google.genai, mistralai).
2. Direct provider API endpoint strings (e.g. api.deepseek.com, api.openai.com, api.anthropic.com).
3. Direct provider API key environment variable reads outside project_config/reviewer_engine.
4. Direct provider client instantiations (e.g. DeepSeekClient) outside reviewer_engine.py and test seams.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Set

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

FORBIDDEN_PROVIDER_MODULES = frozenset(
    {
        "openai",
        "anthropic",
        "google.generativeai",
        "google.genai",
        "mistralai",
        "cohere",
    }
)

FORBIDDEN_PROVIDER_ENDPOINTS = [
    re.compile(r"api\.deepseek\.com", re.IGNORECASE),
    re.compile(r"api\.openai\.com", re.IGNORECASE),
    re.compile(r"api\.anthropic\.com", re.IGNORECASE),
    re.compile(r"generativelanguage\.googleapis\.com", re.IGNORECASE),
]

FORBIDDEN_PROVIDER_ENV_VARS = frozenset(
    {
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_KEY_QUENCH",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
    }
)

ALLOWED_PROVIDER_EGRESS_FILES = frozenset(
    {
        "reviewer_engine.py",
        "project_config.py",
        "check_no_api_bypass.py",
        "test_no_api_bypass.py",
    }
)


@dataclass(frozen=True)
class Violation:
    file_path: str
    line: int
    col: int
    rule: str
    message: str
    snippet: str


class ApiBypassAstVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str, source_lines: Sequence[str]) -> None:
        self.file_path = file_path
        self.source_lines = source_lines
        self.violations: List[Violation] = []
        self._basename = os.path.basename(file_path)
        parts = Path(file_path).parts
        self._is_test_seam = "tests" in parts or self._basename in ("conftest.py", "test_no_api_bypass.py")

    def _get_snippet(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""

    def _add_violation(self, node: ast.AST, rule: str, msg: str) -> None:
        line = getattr(node, "lineno", 1)
        col = getattr(node, "col_offset", 0)
        snippet = self._get_snippet(line)
        self.violations.append(
            Violation(
                file_path=self.file_path,
                line=line,
                col=col,
                rule=rule,
                message=msg,
                snippet=snippet,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top_mod = alias.name.split(".")[0]
            if alias.name in FORBIDDEN_PROVIDER_MODULES or top_mod in FORBIDDEN_PROVIDER_MODULES:
                if self._basename not in ALLOWED_PROVIDER_EGRESS_FILES:
                    self._add_violation(
                        node,
                        "FORBIDDEN_PROVIDER_IMPORT",
                        f"Direct import of provider SDK '{alias.name}' is prohibited outside reviewer_engine.py.",
                    )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            top_mod = node.module.split(".")[0]
            if node.module in FORBIDDEN_PROVIDER_MODULES or top_mod in FORBIDDEN_PROVIDER_MODULES:
                if self._basename not in ALLOWED_PROVIDER_EGRESS_FILES:
                    self._add_violation(
                        node,
                        "FORBIDDEN_PROVIDER_IMPORT",
                        f"Direct import from provider SDK '{node.module}' is prohibited outside reviewer_engine.py.",
                    )
            # Check direct import of DeepSeekClient outside reviewer_engine and authorized tests
            if "DeepSeekClient" in [a.name for a in node.names]:
                if not self._is_test_seam and self._basename not in ("reviewer_engine.py",):
                    self._add_violation(
                        node,
                        "FORBIDDEN_PROVIDER_CLIENT_IMPORT",
                        "Direct import of provider client 'DeepSeekClient' is prohibited outside reviewer_engine.py.",
                    )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            val = node.value
            for pat in FORBIDDEN_PROVIDER_ENDPOINTS:
                if pat.search(val):
                    if not self._is_test_seam and self._basename not in ALLOWED_PROVIDER_EGRESS_FILES:
                        self._add_violation(
                            node,
                            "FORBIDDEN_ENDPOINT_LITERAL",
                            f"Hard-coded provider endpoint string '{val}' found. Reviewer providers must egress solely via reviewer_engine.py.",
                        )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check direct os.environ.get("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        fn_name = ""
        if isinstance(node.func, ast.Attribute):
            fn_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            fn_name = node.func.id

        if fn_name in ("get", "getenv") and node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                if first_arg.value.upper() in FORBIDDEN_PROVIDER_ENV_VARS:
                    if not self._is_test_seam and self._basename not in ("project_config.py", "reviewer_engine.py", "check_no_api_bypass.py"):
                        self._add_violation(
                            node,
                            "FORBIDDEN_ENV_KEY_READ",
                            f"Direct access to provider API key env var '{first_arg.value}' is prohibited. Use project_config.load_project_config().",
                        )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # Check os.environ["DEEPSEEK_API_KEY"]
        slice_node = node.slice
        if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
            if slice_node.value.upper() in FORBIDDEN_PROVIDER_ENV_VARS:
                if not self._is_test_seam and self._basename not in ("project_config.py", "reviewer_engine.py", "check_no_api_bypass.py"):
                    self._add_violation(
                        node,
                        "FORBIDDEN_ENV_KEY_READ",
                        f"Direct subscript access to provider API key '{slice_node.value}' is prohibited. Use project_config.load_project_config().",
                    )
        self.generic_visit(node)


def scan_file_for_bypass(file_path: str) -> List[Violation]:
    """Scan a single Python file for reviewer API bypasses via AST analysis."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        return []

    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError:
        return []

    lines = content.splitlines()
    visitor = ApiBypassAstVisitor(file_path, lines)
    visitor.visit(tree)
    return visitor.violations


def scan_workspace_for_bypass(
    workspace_root: str,
    target_dirs: Sequence[str] = (
        "plugins/quench-dev-tasks/server",
        "plugins/quench-dev-tasks/scripts",
        "scratch",
    ),
) -> List[Violation]:
    """Scan governed directories in workspace for unauthorized provider API bypasses."""
    real_ws = os.path.realpath(workspace_root)
    violations: List[Violation] = []

    for rel_d in target_dirs:
        abs_d = os.path.join(real_ws, rel_d.replace("/", os.sep))
        if not os.path.exists(abs_d):
            continue

        if os.path.isfile(abs_d) and abs_d.endswith(".py"):
            violations.extend(scan_file_for_bypass(abs_d))
            continue

        for root, dirs, files in os.walk(abs_d):
            dirs[:] = [d for d in dirs if d not in (".git", "venv", ".venv", "__pycache__", ".pytest_cache")]
            for f in files:
                if f.endswith(".py"):
                    full_p = os.path.join(root, f)
                    violations.extend(scan_file_for_bypass(full_p))

    return violations


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_no_api_bypass",
        description="Static AST scanner enforcing Reviewer API single network egress invariant.",
    )
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Workspace root path to scan (default: current directory)",
    )
    parser.add_argument(
        "--expect-exit",
        type=int,
        default=None,
        help="Assert expected exit code (e.g. 0 for clean pass)",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Explicit list of files to scan instead of directory walk",
    )

    args = parser.parse_args(argv)
    ws = os.path.abspath(args.workspace_root)

    violations: List[Violation] = []
    if args.files:
        for f in args.files:
            violations.extend(scan_file_for_bypass(f))
    else:
        violations = scan_workspace_for_bypass(ws)

    if violations:
        sys.stderr.write(f"\n❌ [AST Scanner] Found {len(violations)} Reviewer API bypass violation(s):\n")
        for v in violations:
            try:
                rel_f = os.path.relpath(v.file_path, ws).replace("\\", "/")
            except ValueError:
                rel_f = v.file_path.replace("\\", "/")
            sys.stderr.write(
                f"  - {rel_f}:{v.line}:{v.col} [{v.rule}]\n"
                f"    Message: {v.message}\n"
                f"    Snippet: {v.snippet}\n\n"
            )
        exit_code = 1
    else:
        sys.stdout.write("✅ [AST Scanner] Zero Reviewer API bypasses detected. Single-egress invariant verified.\n")
        exit_code = 0

    if args.expect_exit is not None:
        if exit_code != args.expect_exit:
            sys.stderr.write(
                f"❌ [AST Scanner] Expected exit code {args.expect_exit}, but actual exit code was {exit_code}.\n"
            )
            return 1
        return 0

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
