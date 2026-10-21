# -*- coding: utf-8 -*-
"""test_reviewer_poll_ctx_schema_invariance.py - FastMCP Context Injection Zero-Schema-Drift Verification.

Enforces:
1. P0-1: Test strictly resides under plugins/quench-dev-tasks/server/tests/.
2. P0-2: Production shadow schema verification and pending dev_reviewer_poll signature anchoring.
3. C.6: Context class instance identity across server.py and probe.
4. E1: Precondition gate proving Context injection does not mutate inputSchema.
5. P1-3: Prompt surface static gate recognizes framework-injected Context without ambiguity.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import pytest
from fastmcp import Context, FastMCP

TEST_FILE = Path(__file__).resolve()
REPO_ROOT = TEST_FILE.parents[4]
SERVER_DIR = REPO_ROOT / "plugins" / "quench-dev-tasks" / "server"
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import server
import check_prompt_surface


def detect_report_progress_capabilities(ctx_cls: type) -> dict[str, bool]:
    """Inspect Context.report_progress signature to detect parameter support.
    
    Returns:
        dict with boolean keys 'supports_message' and 'supports_total'.
    """
    report_method = getattr(ctx_cls, "report_progress", None)
    if not report_method or not callable(report_method):
        return {"supports_message": False, "supports_total": False}
    try:
        sig = inspect.signature(report_method)
        return {
            "supports_message": "message" in sig.parameters,
            "supports_total": "total" in sig.parameters,
        }
    except (ValueError, TypeError):
        return {"supports_message": False, "supports_total": False}


def test_library_instance_identity_c6() -> None:
    """C.6: Assert test Context and server.Context are the identical class object."""
    assert Context is server.Context, "Context class must be identical across test and server.py"
    assert FastMCP is server.FastMCP, "FastMCP class must be identical across test and server.py"


def test_synthetic_probe_ctx_schema_invariance() -> None:
    """E1: Assert injecting ctx: Context does not alter inputSchema properties or required."""
    probe_mcp = FastMCP("schema_invariance_probe")

    @probe_mcp.tool()
    def probe_no_ctx(workspace_root: str, job_id: str, session_id: str, wait_max_s: int = 0) -> dict:
        """Tool without Context parameter."""
        return {}

    @probe_mcp.tool()
    def probe_with_ctx(
        workspace_root: str,
        job_id: str,
        session_id: str,
        wait_max_s: int = 0,
        ctx: Context = None,
    ) -> dict:
        """Tool with Context parameter."""
        return {}

    tools = asyncio.run(probe_mcp.list_tools())
    tool_map = {t.name: t for t in tools}

    assert "probe_no_ctx" in tool_map
    assert "probe_with_ctx" in tool_map

    no_ctx_params = tool_map["probe_no_ctx"].parameters
    with_ctx_params = tool_map["probe_with_ctx"].parameters

    # 1. Physical assertion: ctx must NOT appear in properties or required
    assert "ctx" not in with_ctx_params.get("properties", {}), "ctx must not appear in properties"
    assert "ctx" not in with_ctx_params.get("required", []), "ctx must not appear in required"

    # 2. Byte-for-byte schema equality
    no_ctx_bytes = json.dumps(no_ctx_params, sort_keys=True)
    with_ctx_bytes = json.dumps(with_ctx_params, sort_keys=True)
    assert no_ctx_bytes == with_ctx_bytes, "Schema with ctx must be byte-for-byte identical to schema without ctx"


def test_shadow_schema_matches_pending_poll_signature() -> None:
    """P0-2 / C-1: Production shadow schema verification anchoring pending dev_reviewer_poll signature.
    
    Anchors:
    - Signature parameters: {'workspace_root', 'job_id', 'session_id', 'wait_max_s', 'ctx'}
    - ctx annotation is Context
    - Generated schema bytes strictly match docs/architecture/ide_tool_schemas.json golden entry
    """
    # 1. Define pending production signature for dev_reviewer_poll
    def pending_dev_reviewer_poll(
        workspace_root: str,
        job_id: str,
        session_id: str,
        wait_max_s: int = 0,
        ctx: Context = None,
    ) -> dict:
        """Poll status or result of a background Reviewer task.
        Enforces 1KB non-terminal snapshot contract.

        轮询 Reviewer 异步推演任务：强约束 1KB 极简白名单契约，恒定返回结构化字典。

        Args:
            workspace_root: Root path of the target workspace / 项目根目录绝对路径。
            job_id: Target job ID to poll / 待轮询的任务ID。
            session_id: Caller session ID for multi-session authorization / 会话隔离标识符。
            wait_max_s: Server-side long polling wait timeout in seconds (0-25) / 服务端长轮询最大挂起等待秒数。
            ctx: FastMCP Context injected by server framework.
        """
        return {}

    sig = inspect.signature(pending_dev_reviewer_poll)
    param_names = set(sig.parameters.keys())
    assert param_names == {"workspace_root", "job_id", "session_id", "wait_max_s", "ctx"}, (
        f"Pending signature parameters mismatch: {param_names}"
    )
    # Under 'from __future__ import annotations', parameter annotation can be 'Context' string or Context type
    ctx_anno = sig.parameters["ctx"].annotation
    assert ctx_anno is Context or ctx_anno == "Context", f"ctx annotation must be Context, got {ctx_anno}"

    # 2. Register on shadow FastMCP instance
    shadow_mcp = FastMCP("shadow_probe")
    shadow_mcp.tool()(pending_dev_reviewer_poll)

    tools = asyncio.run(shadow_mcp.list_tools())
    shadow_tool = next(t for t in tools if t.name == "pending_dev_reviewer_poll")

    # 3. Load golden schema snapshot
    golden_path = REPO_ROOT / "docs" / "architecture" / "ide_tool_schemas.json"
    assert golden_path.is_file(), f"Golden schema file not found at {golden_path}"
    golden_doc = json.loads(golden_path.read_text(encoding="utf-8"))
    golden_poll = golden_doc.get("dev_reviewer_poll", {})
    golden_parameters = golden_poll.get("parameters", {})

    # 4. Assert shadow parameters equal golden parameters byte-for-byte
    shadow_bytes = json.dumps(shadow_tool.parameters, sort_keys=True)
    golden_bytes = json.dumps(golden_parameters, sort_keys=True)
    assert shadow_bytes == golden_bytes, (
        f"Shadow schema diverged from golden ide_tool_schemas.json!\nShadow: {shadow_bytes}\nGolden: {golden_bytes}"
    )


def test_detect_report_progress_capabilities() -> None:
    """Detect current fastmcp.Context capabilities."""
    caps = detect_report_progress_capabilities(Context)
    assert isinstance(caps, dict)
    assert "supports_message" in caps
    assert "supports_total" in caps
    # Log capabilities for inspection
    print(f"\n[Capabilities Probe] fastmcp.Context report_progress capabilities: {caps}")


def test_prompt_surface_recognizes_injected_framework_params() -> None:
    """P1-3: Prompt surface static gate deterministically handles ctx."""
    assert "ctx" in check_prompt_surface.INJECTED_FRAMEWORK_PARAMS
    assert "self" in check_prompt_surface.INJECTED_FRAMEWORK_PARAMS
