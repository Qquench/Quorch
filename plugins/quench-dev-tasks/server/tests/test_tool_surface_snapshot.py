# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Test suite for ToolSurface snapshot extraction & mechanical triplet dedup gate.

Enforces:
1. Exactly 16 registered MCP tools matching architecture declarations.
2. 100% uniqueness of registered tool names (zero channel collision).
3. Deterministic canonical hash matching committed snapshot file (TP-4).
4. Negative assertion: zero duplicate parameter signatures (drives step22.4 COLLAPSE).
5. Zero skipped dynamic tools.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from tool_surface_snapshot import (
    build_tool_surface_report,
    SERVER_PY_REL,
    SNAPSHOT_JSON_REL,
)


def _get_workspace_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / ".agents" / "quench_stack.yaml").is_file():
            return parent
    raise RuntimeError("Workspace root not found")


@pytest.mark.tier1_fast
def test_tool_count_matches_architecture_declaration():
    """断言工具总数与 docs/architecture/README.md 声明的 16 个 MCP 端点完全一致。"""
    ws = _get_workspace_root()
    report = build_tool_surface_report(ws / SERVER_PY_REL)
    assert len(report.entries) == 16, f"Expected 16 tools, got {len(report.entries)}"


@pytest.mark.tier1_fast
def test_tool_names_unique():
    """断言 MCP 工具名唯一，杜绝路由通道冲突。"""
    ws = _get_workspace_root()
    report = build_tool_surface_report(ws / SERVER_PY_REL)
    names = [e.name for e in report.entries]
    assert len(names) == len(set(names)), "MCP 工具名存在冲突"


@pytest.mark.tier1_fast
def test_canonical_hash_is_deterministic():
    """断言独立解析两次产出的 canonical_hash 逐字节恒定。"""
    ws = _get_workspace_root()
    server_py = ws / SERVER_PY_REL
    rep1 = build_tool_surface_report(server_py)
    rep2 = build_tool_surface_report(server_py)
    assert rep1.canonical_hash == rep2.canonical_hash


@pytest.mark.tier1_fast
def test_committed_snapshot_hash_matches_live_projection():
    """断言已提交快照文件哈希与 live 解析结果逐字节相等 (TP-4)。"""
    ws = _get_workspace_root()
    snap_file = ws / SNAPSHOT_JSON_REL
    assert snap_file.is_file(), f"Snapshot file missing: {snap_file}"

    committed_data = json.loads(snap_file.read_text(encoding="utf-8"))
    live_report = build_tool_surface_report(ws / SERVER_PY_REL)
    assert live_report.canonical_hash == committed_data["canonical_hash"]


@pytest.mark.tier1_fast
def test_duplicate_param_signature_groups_empty():
    """硬性负向断言：机械提取的重复参数签名组为空集。

    若为空集，则驱动 step22.4 裁决为 COLLAPSED（镜像 step22.1 范式）。
    """
    ws = _get_workspace_root()
    report = build_tool_surface_report(ws / SERVER_PY_REL)
    assert len(report.duplicate_param_signatures) == 0, (
        f"Found duplicate parameter signatures: {report.duplicate_param_signatures}"
    )


@pytest.mark.tier1_fast
def test_no_silently_skipped_dynamic_tools():
    """断言无运行时动态注册未捕获工具。"""
    ws = _get_workspace_root()
    report = build_tool_surface_report(ws / SERVER_PY_REL)
    assert report.skipped_dynamic == 0
