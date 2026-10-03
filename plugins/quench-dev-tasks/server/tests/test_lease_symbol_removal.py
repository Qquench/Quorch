# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import ast
from pathlib import Path
from typing import Final

FORBIDDEN_SYMBOLS: Final[set[str]] = {
    "probe_peer",
    "_probe_posix",
    "_probe_windows",
    "_verify_disk_nonce_match",
    "LeaseHeartbeatThread",
    "PeerLiveness",
    "start_heartbeat_thread",
    "stop_heartbeat_thread",
    "heartbeat_healthy",
}


def _collect_symbol_occurrences(file_path: Path) -> list[tuple[int, str, str]]:
    """扫描 Python 源文件 AST，收集 Name、Attribute、ClassDef、FunctionDef 中命中的符号。"""
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))
    findings: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_SYMBOLS:
            findings.append((getattr(node, "lineno", 0), "Name", node.id))
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_SYMBOLS:
            findings.append((getattr(node, "lineno", 0), "Attribute", node.attr))
        elif isinstance(node, ast.FunctionDef) and node.name in FORBIDDEN_SYMBOLS:
            findings.append((getattr(node, "lineno", 0), "FunctionDef", node.name))
        elif isinstance(node, ast.AsyncFunctionDef) and node.name in FORBIDDEN_SYMBOLS:
            findings.append((getattr(node, "lineno", 0), "AsyncFunctionDef", node.name))
        elif isinstance(node, ast.ClassDef) and node.name in FORBIDDEN_SYMBOLS:
            findings.append((getattr(node, "lineno", 0), "ClassDef", node.name))

    return findings


def test_workspace_lease_purged_of_all_forbidden_symbols():
    """断言 workspace_lease.py AST 中不存在任何已废弃的探针或心跳符号。"""
    server_dir = Path(__file__).resolve().parent.parent
    target_file = server_dir / "workspace_lease.py"
    assert target_file.is_file(), f"Target file not found: {target_file}"

    findings = _collect_symbol_occurrences(target_file)
    assert not findings, (
        f"Forbidden symbols found in {target_file.name} AST:\n"
        + "\n".join(f"  Line {line} ({kind}): {sym}" for line, kind, sym in findings)
    )


def test_reviewer_jobs_purged_of_all_forbidden_symbols():
    """断言 reviewer_jobs.py AST 中不存在任何已废弃的探针或心跳符号。"""
    server_dir = Path(__file__).resolve().parent.parent
    target_file = server_dir / "reviewer_jobs.py"
    assert target_file.is_file(), f"Target file not found: {target_file}"

    findings = _collect_symbol_occurrences(target_file)
    assert not findings, (
        f"Forbidden symbols found in {target_file.name} AST:\n"
        + "\n".join(f"  Line {line} ({kind}): {sym}" for line, kind, sym in findings)
    )


def test_required_hardened_symbols_present():
    """正向断言：硬化后的必要符号物理存在于源码 AST 中。"""
    server_dir = Path(__file__).resolve().parent.parent
    rj_file = server_dir / "reviewer_jobs.py"
    wl_file = server_dir / "workspace_lease.py"

    rj_tree = ast.parse(rj_file.read_text(encoding="utf-8"))
    rj_funcs = {node.name for node in ast.walk(rj_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "is_record_orphaned" in rj_funcs, "is_record_orphaned must exist in reviewer_jobs.py"

    wl_tree = ast.parse(wl_file.read_text(encoding="utf-8"))
    wl_funcs = {node.name for node in ast.walk(wl_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "is_held" in wl_funcs, "is_held must exist in workspace_lease.py"
    assert "touch" in wl_funcs, "touch must exist in workspace_lease.py"
    assert "acquire_or_probe" in wl_funcs, "acquire_or_probe must exist in workspace_lease.py"
