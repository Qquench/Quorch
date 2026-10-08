#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture isolated test scope baseline and verify immutable parity proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Final

SCRIPTS_DIR: Final[Path] = Path(__file__).resolve().parent
PLUGIN_ROOT: Final[Path] = SCRIPTS_DIR.parent
SERVER_DIR: Final[Path] = PLUGIN_ROOT / "server"
TESTS_DIR: Final[Path] = SERVER_DIR / "tests"
REPO_ROOT: Final[Path] = PLUGIN_ROOT.parent.parent

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

LEGACY_RULE_MAP: Final[dict[str, str]] = {
    "plugins/quench-dev-tasks/server/tests/test_lease_symbol_removal.py": "lease_symbol_removal",
    "plugins/quench-dev-tasks/server/tests/test_touch_outcome_no_truthiness.py": "touch_outcome_truthiness",
    "plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py": "vendor_literal_in_core",
    "plugins/quench-dev-tasks/server/tests/test_no_api_bypass.py": "api_bypass",
}


def load_rule_ids() -> tuple[str, ...]:
    """运行期解析 _hygiene.rules.RULE_IDS（仅 --check-drift 与 --out 捕获期使用）。"""
    from _hygiene.rules import RULE_IDS
    return RULE_IDS


def canonical_bytes(raw: bytes) -> bytes:
    """BOM strip (utf-8-sig) + CRLF->LF 归一化。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.replace(b"\r\n", b"\n")


def check_worktree_consistency(base_ref: str, repo_root: Path) -> None:
    """写盘前 fail-closed 断言 git rev-parse HEAD == base_ref 且 git status --porcelain 为空。"""
    proc_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc_head.returncode != 0:
        raise RuntimeError(f"Failed to query git HEAD: {proc_head.stderr.strip()}")
    current_head = proc_head.stdout.strip()
    if current_head != base_ref:
        raise RuntimeError(
            f"Worktree consistency fail-closed: HEAD ({current_head}) does not match base_ref ({base_ref})"
        )

    proc_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc_status.returncode != 0:
        raise RuntimeError(f"Failed to query git status: {proc_status.stderr.strip()}")
    status_output = proc_status.stdout.strip()
    if status_output:
        raise RuntimeError(
            f"Worktree consistency fail-closed: dirty working tree detected:\n{status_output}"
        )


def _resolve_core_module_paths(server_dir: Path) -> list[str]:
    """获取 server 核心模块 plugin 根相对 POSIX 路径列表。"""
    paths: list[str] = []
    for p in sorted(server_dir.glob("*.py")):
        if p.is_file() and not p.name.startswith("."):
            paths.append(f"server/{p.name}")
    return paths


def generate_baseline_data(base_ref: str) -> dict[str, Any]:
    """生成隔离集范围基线字典结构。"""
    from _hygiene.rules import RULE_IDS, RULE_SCOPE, SCAN_ROOTS

    core_module_paths = _resolve_core_module_paths(SERVER_DIR)
    raw_entries: list[list[str]] = []

    for rule_id in RULE_IDS:
        tokens = RULE_SCOPE[rule_id]
        scan_spec = SCAN_ROOTS[rule_id]
        if scan_spec == ("server",):
            target_paths = core_module_paths
        else:
            target_paths = list(scan_spec)

        for path_str in target_paths:
            for token in tokens:
                raw_entries.append([rule_id, path_str, token])

    # 严格三元组排序：(rule_id, rel_path, symbol_or_token)
    entries = sorted(raw_entries, key=lambda e: (e[0], e[1], e[2]))

    # 计算 entries 规范序列化 SHA256
    entries_serialized = json.dumps(
        entries, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    entries_sha256 = hashlib.sha256(canonical_bytes(entries_serialized)).hexdigest()

    data: dict[str, Any] = {
        "schema_version": 1,
        "base_ref": base_ref,
        "generator": "scripts/capture_isolated_scope.py",
        "rule_ids": list(RULE_IDS),
        "source_files": sorted(LEGACY_RULE_MAP.keys()),
        "entry_count": len(entries),
        "entries": entries,
        "entries_sha256": entries_sha256,
    }
    return data


def verify_baseline_file(file_path: Path) -> None:
    """持久化校验基线文件：schema、排序、去重、覆盖 rule_ids、sha256 与整文件规范序列化。"""
    if not file_path.is_file():
        raise FileNotFoundError(f"Baseline file does not exist: {file_path}")

    raw_bytes = file_path.read_bytes()
    canon_bytes = canonical_bytes(raw_bytes)

    try:
        data = json.loads(canon_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to parse baseline JSON: {e}") from e

    # 1. Schema 契约校验
    if data.get("schema_version") != 1:
        raise ValueError(f"Invalid schema_version: {data.get('schema_version')}")
    if not isinstance(data.get("base_ref"), str) or not data["base_ref"]:
        raise ValueError("Missing or invalid base_ref")
    if data.get("generator") != "scripts/capture_isolated_scope.py":
        raise ValueError(f"Invalid generator: {data.get('generator')}")
    if not isinstance(data.get("rule_ids"), list) or not data["rule_ids"]:
        raise ValueError("Missing or invalid rule_ids")
    if not isinstance(data.get("source_files"), list) or not data["source_files"]:
        raise ValueError("Missing or invalid source_files")

    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Missing or empty entries list")

    if data.get("entry_count") != len(entries):
        raise ValueError(
            f"entry_count mismatch: header declares {data.get('entry_count')} but found {len(entries)}"
        )

    # 2. Entries 结构、唯一性与升序校验
    seen = set()
    for idx, item in enumerate(entries):
        if not isinstance(item, list) or len(item) != 3:
            raise ValueError(f"Entry at index {idx} is not a 3-element list: {item}")
        rule_id, rel_path, token = item
        if not (isinstance(rule_id, str) and isinstance(rel_path, str) and isinstance(token, str)):
            raise ValueError(f"Entry elements at index {idx} must all be str: {item}")
        tup = (rule_id, rel_path, token)
        if tup in seen:
            raise ValueError(f"Duplicate entry found in entries at index {idx}: {tup}")
        seen.add(tup)

    expected_sorted = sorted(entries, key=lambda e: (e[0], e[1], e[2]))
    if entries != expected_sorted:
        raise ValueError("Entries are not in canonical sorted order (rule_id, rel_path, symbol_or_token)")

    # 3. 覆盖 baseline 内嵌 rule_ids 校验
    covered_rule_ids = {e[0] for e in entries}
    declared_rule_ids = set(data["rule_ids"])
    if covered_rule_ids != declared_rule_ids:
        missing = declared_rule_ids - covered_rule_ids
        raise ValueError(f"Entries do not fully cover embedded rule_ids (missing: {missing})")

    # 4. entries_sha256 校验
    entries_serialized = json.dumps(
        entries, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    actual_entries_sha256 = hashlib.sha256(canonical_bytes(entries_serialized)).hexdigest()
    if actual_entries_sha256 != data.get("entries_sha256"):
        raise ValueError(
            f"entries_sha256 mismatch: expected {data.get('entries_sha256')}, computed {actual_entries_sha256}"
        )

    # 5. 整文件重序列化一致性判定
    re_serialized = (
        json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if canon_bytes != canonical_bytes(re_serialized):
        raise ValueError("File content deviates from canonical serialized bytes (LF / compact JSON)")


def check_drift(file_path: Path) -> None:
    """比对证物 rule_ids 与运行期 load_rule_ids()，漂移即红。"""
    if not file_path.is_file():
        raise FileNotFoundError(f"Baseline file does not exist: {file_path}")

    canon_bytes = canonical_bytes(file_path.read_bytes())
    data = json.loads(canon_bytes.decode("utf-8"))
    embedded_rule_ids = set(data.get("rule_ids", []))
    runtime_rule_ids = set(load_rule_ids())

    if embedded_rule_ids != runtime_rule_ids:
        raise ValueError(
            f"RULE_IDS drift detected! Baseline: {sorted(embedded_rule_ids)}, Runtime: {sorted(runtime_rule_ids)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture and verify isolated scope baseline.")
    parser.add_argument("--out", type=str, help="Target JSON path to write captured baseline")
    parser.add_argument("--base-ref", type=str, help="Git commit SHA for scaffold commit (required with --out)")
    parser.add_argument("--check", type=str, help="Validate specified baseline JSON against schema & parity contract")
    parser.add_argument("--check-drift", type=str, help="Verify that baseline embedded rule_ids match runtime RULE_IDS")

    args = parser.parse_args(argv)

    if args.out:
        if not args.base_ref:
            sys.stderr.write("Error: --base-ref <SHA> is required when using --out\n")
            return 1
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # 写盘前 fail-closed 断言工作树一致性
        check_worktree_consistency(args.base_ref, REPO_ROOT)

        data = generate_baseline_data(args.base_ref)
        content = (
            json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        out_path.write_bytes(content)
        sys.stdout.write(f"Successfully captured baseline ({data['entry_count']} entries) -> {out_path}\n")
        return 0

    if args.check:
        check_path = Path(args.check)
        try:
            verify_baseline_file(check_path)
            sys.stdout.write(f"Baseline validation PASSED -> {check_path}\n")
            return 0
        except Exception as e:
            sys.stderr.write(f"Baseline validation FAILED: {e}\n")
            return 1

    if args.check_drift:
        drift_path = Path(args.check_drift)
        try:
            check_drift(drift_path)
            sys.stdout.write(f"Baseline drift check PASSED -> {drift_path}\n")
            return 0
        except Exception as e:
            sys.stderr.write(f"Baseline drift check FAILED: {e}\n")
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
