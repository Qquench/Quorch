#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quench DevTasks - 测试分级不变量硬门禁校验工具.

基于 pytest --collect-only 采集物理真值，验证：
1. ★并发不变量硬门禁★ 与 Tier-1 互斥 (H ∩ Tier-1 = ∅)
2. 真仓 --check 锚点 (test_asset_inventory) 恒留 Tier-2 (nodeid 隔离)
3. 集合拓扑完整性 (Full ⊇ Tier1 ∪ H) 与非空断言
4. 环境变量与 addopts 物理净化，异常一律 fail-closed
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Final, Mapping, Sequence

CONCURRENCY_SELECTOR_EXPR: Final[str] = "state_machine or reclaim_cas or workspace_lease"
TIER1_MARKER: Final[str] = "tier1_fast"
TIER2_ANCHOR_TOKEN: Final[str] = "test_asset_inventory"

ENV_SCRUB_KEYS: Final[tuple[str, ...]] = (
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTEST_CURRENT_TEST",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTEST_DEBUG",
)
ENV_SCRUB_PREFIXES: Final[tuple[str, ...]] = ("PYTEST_XDIST_",)
NEUTRALIZE_ARGS: Final[tuple[str, ...]] = ("-o", "addopts=", "-p", "no:cacheprovider")

TIER1_TARGET_MODULES: Final[tuple[str, ...]] = (
    "test_python_floor_discipline.py",
    "test_touch_outcome_no_truthiness.py",
    "test_import_mode_contract.py",
    "test_schema_validator.py",
    "test_agents_md_sync.py",
    "test_anti_roleplay_discipline_contract.py",
    "test_forgery_prevention_contract.py",
)


def sanitized_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """物理净化子进程环境变量，剔除所有干扰采集集语义的 PYTEST_* 变量。"""
    source = dict(os.environ if base is None else base)
    cleaned: dict[str, str] = {}
    for k, v in source.items():
        if k in ENV_SCRUB_KEYS:
            continue
        if any(k.startswith(prefix) for prefix in ENV_SCRUB_PREFIXES):
            continue
        cleaned[k] = v
    return cleaned


def collect_selection(
    repo_root: Path,
    *,
    expr: str | None = None,
    marker: str | None = None,
    env: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """委托 pytest --collect-only 采集 ground-truth nodeids。"""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *NEUTRALIZE_ARGS,
        "--collect-only",
        "-q",
    ]
    if expr:
        cmd.extend(["-k", expr])
    if marker:
        cmd.extend(["-m", marker])

    scrubbed = sanitized_env(env)
    res = subprocess.run(
        cmd,
        cwd=str(repo_root),
        env=scrubbed,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if res.returncode != 0:
        err_msg = (res.stderr or res.stdout or "").strip()
        raise RuntimeError(
            f"pytest collection failed with exit code {res.returncode}:\n{err_msg}"
        )

    nodeids: set[str] = set()
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # 仅保留包含 '::' 的用例 nodeid 行，过滤汇总行及提示
        if "::" in line:
            nodeids.add(line.replace("\\", "/"))

    return frozenset(nodeids)


def check_tiering_invariants(repo_root: Path) -> tuple[bool, list[str]]:
    """核心不变量校验函数。禁止短路布尔，多点违规全量上报。"""
    violations: list[str] = []

    try:
        full_nodes = collect_selection(repo_root)
        tier1_nodes = collect_selection(repo_root, marker=TIER1_MARKER)
        h_nodes = collect_selection(repo_root, expr=CONCURRENCY_SELECTOR_EXPR)
    except Exception as exc:
        violations.append(f"Fail-closed collection error: {exc}")
        return False, violations

    # 1. 非空与退出码安全断言 (R5)
    if not full_nodes:
        violations.append("Full collection is empty (no tests discovered)")
    if not tier1_nodes:
        violations.append(
            f"Tier-1 collection is empty (no tests marked with '{TIER1_MARKER}')"
        )
    if not h_nodes:
        violations.append(
            f"Concurrency collection H is empty (no tests matched expr '{CONCURRENCY_SELECTOR_EXPR}')"
        )

    # 2. 拓扑包含断言 Full ⊇ Tier1 ∪ H (R1)
    if full_nodes and tier1_nodes:
        missing_t1 = tier1_nodes - full_nodes
        if missing_t1:
            violations.append(f"Tier-1 contains nodeids not in Full: {sorted(missing_t1)}")
    if full_nodes and h_nodes:
        missing_h = h_nodes - full_nodes
        if missing_h:
            violations.append(f"H contains nodeids not in Full: {sorted(missing_h)}")

    # 3. ★并发不变量硬门禁★ 互斥判定: H ∩ Tier-1 = ∅
    intersection = tier1_nodes & h_nodes
    if intersection:
        violations.append(
            f"★并发不变量硬门禁★ 违规: H ∩ Tier-1 != ∅ (违规用例: {sorted(intersection)})"
        )

    # 4. 真仓锚点隔离断言 (H-7)
    anchor_in_tier1 = [n for n in tier1_nodes if TIER2_ANCHOR_TOKEN in n]
    if anchor_in_tier1:
        violations.append(
            f"真仓锚点隔离违规: '{TIER2_ANCHOR_TOKEN}' 测试落入 Tier-1 ({anchor_in_tier1})"
        )
    anchor_in_full = [n for n in full_nodes if TIER2_ANCHOR_TOKEN in n]
    if not anchor_in_full:
        violations.append(
            f"真仓锚点缺失: '{TIER2_ANCHOR_TOKEN}' 测试未在 Full 套件中发现"
        )

    # 5. 白名单漂移断言 (R6)
    if full_nodes and tier1_nodes:
        for mod in TIER1_TARGET_MODULES:
            if not any(mod in n for n in tier1_nodes):
                violations.append(
                    f"Tier-1 白名单模块漂移: '{mod}' 未产生任何 Tier-1 用例"
                )

    return len(violations) == 0, violations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check test tiering invariants")
    parser.add_argument("--repo-root", default=None, help="Explicit repository root")
    parser.add_argument(
        "--check", action="store_true", help="Perform invariant checks and exit with status code"
    )

    args = parser.parse_args(argv)
    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = Path(__file__).resolve().parent.parent

    try:
        ok, violations = check_tiering_invariants(repo_root)
        if not ok:
            err_lines = ["[Tiering Gate] [FAIL] Violations detected:\n"]
            for v in violations:
                err_lines.append(f"  * {v}\n")
            msg = "".join(err_lines)
            try:
                sys.stderr.write(msg)
            except UnicodeEncodeError:
                sys.stderr.write(msg.encode("ascii", "replace").decode("ascii"))
            sys.stderr.flush()
            return 1

        success_msg = "[Tiering Gate] [OK] All invariants satisfied (H & Tier-1 = empty).\n"
        try:
            sys.stdout.write(success_msg)
        except UnicodeEncodeError:
            sys.stdout.write(success_msg.encode("ascii", "replace").decode("ascii"))
        sys.stdout.flush()
        return 0
    except Exception as exc:
        err_msg = f"[Tiering Gate] [FAIL] Fail-closed uncaught exception: {exc}\n"
        try:
            sys.stderr.write(err_msg)
        except UnicodeEncodeError:
            sys.stderr.write(err_msg.encode("ascii", "replace").decode("ascii"))
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    sys.exit(main())
