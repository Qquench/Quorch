#!/usr/bin/env python3
"""measure_tool_response_sizes.py - Measure MCP Tool Response Payload Sizes Against SSOT Budgets.

Verifies that typical payloads for all 16 MCP tools comply with RESPONSE_BUDGET_BYTES.
Emits a tabular breakdown of byte counts, budgets, and margins.
Supports --check flag for CI gating with zero disk artifacts.
Only writes benchmark records when --record is explicitly passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add server and server/tests to sys.path to access constants and fixtures
REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "plugins" / "quench-dev-tasks" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

TESTS_DIR = SERVER_DIR / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fixtures.response_payloads import TYPICAL_PAYLOADS
from response_compactor import canonical_json
from tool_surface_constants import (
    EXPECTED_TOOL_NAMES,
    RESPONSE_BUDGET_BYTES,
    measure_payload_bytes,
)


def measure_all_tools() -> list[dict[str, Any]]:
    """Measure byte size for each tool typical payload against its budget."""
    results: list[dict[str, Any]] = []

    for tool in sorted(EXPECTED_TOOL_NAMES):
        payload = TYPICAL_PAYLOADS.get(tool, {})
        size_bytes = measure_payload_bytes(payload)
        budget_bytes = RESPONSE_BUDGET_BYTES.get(tool, 0)
        margin_bytes = budget_bytes - size_bytes
        passed = size_bytes <= budget_bytes

        results.append({
            "tool": tool,
            "size_bytes": size_bytes,
            "budget_bytes": budget_bytes,
            "margin_bytes": margin_bytes,
            "utilization_pct": round((size_bytes / budget_bytes * 100), 1) if budget_bytes > 0 else 0.0,
            "passed": passed,
        })

    return results


def print_table(results: list[dict[str, Any]]) -> None:
    """Print clean ASCII report table."""
    header = f"{'Tool Name':<32} {'Size (B)':<10} {'Budget (B)':<12} {'Margin (B)':<12} {'Util %':<8} {'Status'}"
    divider = "-" * len(header)
    print(divider)
    print(header)
    print(divider)

    for r in results:
        status = "PASS" if r["passed"] else "FAIL (OVER)"
        print(
            f"{r['tool']:<32} {r['size_bytes']:<10} {r['budget_bytes']:<12} "
            f"{r['margin_bytes']:<12} {r['utilization_pct']:<8.1f} {status}"
        )

    print(divider)


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure MCP tool response payload sizes against SSOT budgets.")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if any tool exceeds its budget.")
    parser.add_argument("--record", action="store_true", help="Persist benchmark results to .agents/bench/")
    args = parser.parse_args()

    results = measure_all_tools()
    print_table(results)

    all_passed = all(r["passed"] for r in results)

    if args.record:
        bench_dir = REPO_ROOT / ".agents" / "bench"
        bench_dir.mkdir(parents=True, exist_ok=True)
        bench_file = bench_dir / "tool_response_sizes.json"
        bench_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nBenchmark results recorded to {bench_file}")

    if args.check and not all_passed:
        failed_tools = [r["tool"] for r in results if not r["passed"]]
        print(f"\nERROR: The following tools exceeded response budget: {', '.join(failed_tools)}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

