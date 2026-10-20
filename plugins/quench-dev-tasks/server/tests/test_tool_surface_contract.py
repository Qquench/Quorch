"""test_tool_surface_contract.py - Tier-1 tool surface contract tests.

Guarantees 100% memory-based bidirectional AST vs Snapshot schema synchronization.
INVARIANT: Strictly zero import of server, fastmcp, yaml, or network.
"""

from __future__ import annotations

import json
import sys
from typing import Any
import pytest

from tool_surface_constants import (
    EXPECTED_TOOL_NAMES,
    MISSING,
    SCHEMA_META_KEY,
    TOOL_ALLOWS_CTX,
    TOOL_COUNT,
    get_default,
    has_default,
    iter_param_names,
)
from _tool_surface_expectations import (
    SERVER_SOURCE_PATH,
    SNAPSHOT_PATH,
    ToolSurfaceEntry,
    ToolSurfaceError,
    assert_ctx_surface,
    assert_surface_well_formed,
    derive_live_tool_surface,
    extract_tool_surface_from_source,
    json_projection,
)



@pytest.fixture(scope="module")
def snapshot_data() -> dict[str, Any]:
    """Single-pass deserialization of the frozen IDE tool schemas snapshot."""
    raw = SNAPSHOT_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict), "Snapshot must be a valid JSON dictionary"
    return data


@pytest.fixture(scope="module")
def live_surface():
    """Single-pass AST extraction of the live tool surface from server.py."""
    return derive_live_tool_surface()


def test_tool_set_matches_frozen_snapshot(snapshot_data: dict[str, Any]) -> None:
    """Verify tool names in snapshot match EXPECTED_TOOL_NAMES and count matches TOOL_COUNT."""
    snapshot_tools = set(snapshot_data.keys()) - {SCHEMA_META_KEY}
    assert snapshot_tools == EXPECTED_TOOL_NAMES
    assert len(snapshot_tools) == TOOL_COUNT


def test_tool_name_sets_agree_across_surfaces(
    snapshot_data: dict[str, Any], live_surface
) -> None:
    """Verify AST extracted live tool names agree with snapshot and SSOT constant."""
    ast_tool_names = {entry.name for entry in live_surface.entries}
    snapshot_tools = set(snapshot_data.keys()) - {SCHEMA_META_KEY}
    assert ast_tool_names == EXPECTED_TOOL_NAMES
    assert ast_tool_names == snapshot_tools
    assert_surface_well_formed(live_surface, EXPECTED_TOOL_NAMES)


def test_tool_allows_ctx_bidirectional(live_surface) -> None:
    """Verify context-allowing tools bidirectional agreement."""
    assert_ctx_surface(live_surface)
    ctx_tools = {entry.name for entry in live_surface.entries if entry.ctx_params}
    assert ctx_tools == TOOL_ALLOWS_CTX


@pytest.mark.parametrize(
    "src,expected_err",
    [
        ("@mcp.tool()\ndef bad_varargs(*args): pass\n", "可变参数"),
        ("@mcp.tool()\ndef bad_kwargs(**kwargs): pass\n", "可变参数"),
        ("@mcp.tool()\ndef bad_both(*args, **kwargs): pass\n", "可变参数"),
    ],
)
def test_no_varargs_tools_rejected(src: str, expected_err: str) -> None:
    """Verify that varargs (*args) and kwargs (**kwargs) in tool definitions are rejected."""
    with pytest.raises(ToolSurfaceError) as exc_info:
        extract_tool_surface_from_source(src, filename="<synthetic_test>")
    assert expected_err in str(exc_info.value)


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOL_NAMES))
def test_defaults_agree_between_ast_and_snapshot(
    tool_name: str, snapshot_data: dict[str, Any], live_surface
) -> None:
    """Bidirectional verification of parameters and default values between AST and snapshot."""
    entry_dict = {e.name: e for e in live_surface.entries}
    assert tool_name in entry_dict, f"Tool {tool_name} missing from AST live surface"
    entry = entry_dict[tool_name]

    snapshot_param_names = iter_param_names(snapshot_data, tool_name)
    assert entry.non_ctx_params == snapshot_param_names, (
        f"Parameter mismatch for {tool_name}: "
        f"AST non-ctx={sorted(entry.non_ctx_params)} vs Snapshot={sorted(snapshot_param_names)}"
    )

    ast_defaults = entry.default_map
    for param in entry.non_ctx_params:
        if param in ast_defaults:
            assert has_default(snapshot_data, tool_name, param) is True, (
                f"{tool_name}.{param} has default in AST but not in snapshot"
            )
            expected_val = json_projection(ast_defaults[param])
            actual_val = get_default(snapshot_data, tool_name, param)
            assert expected_val == actual_val, (
                f"{tool_name}.{param} default value mismatch: "
                f"AST={expected_val!r} vs Snapshot={actual_val!r}"
            )
        else:
            assert has_default(snapshot_data, tool_name, param) is False, (
                f"{tool_name}.{param} has no default in AST but snapshot reports default"
            )
            assert get_default(snapshot_data, tool_name, param) is MISSING


def test_live_surface_path_is_file_anchored() -> None:
    """Verify that paths are statically anchored, absolute, and exist as files."""
    assert SERVER_SOURCE_PATH.is_absolute()
    assert SERVER_SOURCE_PATH.is_file()
    assert SNAPSHOT_PATH.is_absolute()
    assert SNAPSHOT_PATH.is_file()


def test_entry_is_hashable(live_surface) -> None:
    """Verify that ToolSurfaceEntry objects are hashable and can form sets without error."""
    entry_set = set(live_surface.entries)
    assert len(entry_set) == len(live_surface.entries)
    for entry in live_surface.entries:
        h = hash(entry)
        assert isinstance(h, int)


def test_json_projection_five_boundary_types() -> None:
    """Verify explicit normalization for tuple, list, None, False, 0, and empty string."""
    assert json_projection((1, 2, "a")) == [1, 2, "a"]
    assert json_projection([1, 2, "a"]) == [1, 2, "a"]
    assert json_projection(None) is None
    assert json_projection(False) is False
    assert json_projection(True) is True
    assert json_projection(0) == 0
    assert json_projection("") == ""
