"""test_spec_param_defaults_contract.py - Tier-1 parameter defaults specification vs snapshot contract.

Pure in-memory assertion locking the 3-level chain:
Runtime (server.py) -> Snapshot (ide_tool_schemas.json) -> Specification (dev_tasks_mcp_specification.md).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import pytest

from tool_surface_constants import (
    EXPECTED_TOOL_NAMES,
    MISSING as _MISSING,
    TOOL_COUNT,
    get_default,
    has_default,
)

JSONLiteral = str | int | float | bool | None

DEFAULTS_BLOCK_BEGIN: Final[str] = "<!-- QUENCH-PARAM-DEFAULTS-BEGIN -->"
DEFAULTS_BLOCK_END: Final[str] = "<!-- QUENCH-PARAM-DEFAULTS-END -->"

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
SPEC_PATH: Final[Path] = REPO_ROOT / "dev_tasks_mcp_specification.md"
SNAPSHOT_PATH: Final[Path] = REPO_ROOT / "docs" / "architecture" / "ide_tool_schemas.json"


@dataclass(frozen=True)
class DefaultDiff:
    tool: str
    param: str
    documented: Any
    snapshot: Any
    kind: Literal["mismatch", "missing_in_snapshot", "not_documented"]


def extract_documented_defaults(spec_markdown: str) -> dict[str, dict[str, JSONLiteral]]:
    """Extract documented defaults dictionary from the QUENCH-PARAM-DEFAULTS marker block."""
    begin_idx = spec_markdown.find(DEFAULTS_BLOCK_BEGIN)
    end_idx = spec_markdown.find(DEFAULTS_BLOCK_END)
    if begin_idx == -1 or end_idx == -1 or end_idx < begin_idx:
        raise ValueError("Missing or disordered QUENCH-PARAM-DEFAULTS markers in spec")

    block = spec_markdown[begin_idx + len(DEFAULTS_BLOCK_BEGIN) : end_idx].strip()
    if block.startswith("```"):
        lines = block.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        block = "\n".join(lines).strip()

    try:
        data = json.loads(block)
    except Exception as exc:
        raise ValueError(f"Malformed JSON in QUENCH-PARAM-DEFAULTS block: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("QUENCH-PARAM-DEFAULTS root must be a JSON object")

    for tool_name, params in data.items():
        if not isinstance(tool_name, str) or not isinstance(params, dict):
            raise ValueError(f"Invalid tool mapping in QUENCH-PARAM-DEFAULTS for {tool_name}")
        for param_name in params:
            if not isinstance(param_name, str):
                raise ValueError(f"Invalid parameter name in {tool_name}")

    return data


def compare_documented_with_snapshot(
    documented: dict[str, dict[str, JSONLiteral]], snapshot: dict[str, Any]
) -> list[DefaultDiff]:
    """Compare documented defaults with snapshot defaults, detecting mismatches, omissions and extras."""
    diffs: list[DefaultDiff] = []

    # 1. Check all documented defaults against snapshot
    for tool, doc_params in sorted(documented.items()):
        for param, doc_val in sorted(doc_params.items()):
            if not has_default(snapshot, tool, param):
                diffs.append(
                    DefaultDiff(
                        tool=tool,
                        param=param,
                        documented=doc_val,
                        snapshot=_MISSING,
                        kind="missing_in_snapshot",
                    )
                )
            else:
                snap_val = get_default(snapshot, tool, param)
                if doc_val != snap_val:
                    diffs.append(
                        DefaultDiff(
                            tool=tool,
                            param=param,
                            documented=doc_val,
                            snapshot=snap_val,
                            kind="mismatch",
                        )
                    )

    # 2. Check all snapshot defaults to see if any are not documented
    for tool in sorted(snapshot.keys()):
        if tool == "_meta":
            continue
        props = snapshot[tool].get("parameters", {}).get("properties", {})
        if not props and "properties" in snapshot[tool]:
            props = snapshot[tool]["properties"]
        for param, p_info in sorted(props.items()):
            if "default" in p_info:
                if param not in documented.get(tool, {}):
                    diffs.append(
                        DefaultDiff(
                            tool=tool,
                            param=param,
                            documented=_MISSING,
                            snapshot=p_info["default"],
                            kind="not_documented",
                        )
                    )

    return diffs


@pytest.fixture(scope="module")
def snapshot_data() -> dict[str, Any]:
    raw = SNAPSHOT_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def spec_markdown() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def test_spec_documented_defaults_match_snapshot(
    spec_markdown: str, snapshot_data: dict[str, Any]
) -> None:
    """Tier-1 contract: Documented parameter defaults must 100% agree with controlled snapshot."""
    documented = extract_documented_defaults(spec_markdown)

    # Verify coverage across all 16 tools
    assert set(documented.keys()) == EXPECTED_TOOL_NAMES, (
        f"Documented tools set mismatch: missing {EXPECTED_TOOL_NAMES - set(documented.keys())}, "
        f"extra {set(documented.keys()) - EXPECTED_TOOL_NAMES}"
    )
    assert len(documented) == TOOL_COUNT

    diffs = compare_documented_with_snapshot(documented, snapshot_data)
    assert not diffs, (
        "Specification defaults drift detected against snapshot:\n"
        + "\n".join(f"  [{d.kind}] {d.tool}.{d.param}: doc={d.documented!r} vs snap={d.snapshot!r}" for d in diffs)
    )


def test_single_sentinel_identity_and_missing_detection(
    spec_markdown: str, snapshot_data: dict[str, Any]
) -> None:
    """Guard-of-the-guard test: verify that missing parameter in snapshot triggers 'missing_in_snapshot'."""
    documented = extract_documented_defaults(spec_markdown)

    # Clone snapshot and remove one parameter's default
    corrupted_snapshot = json.loads(json.dumps(snapshot_data))
    del corrupted_snapshot["dev_reviewer_poll"]["parameters"]["properties"]["raw_text"]["default"]

    diffs = compare_documented_with_snapshot(documented, corrupted_snapshot)
    assert len(diffs) == 1
    diff = diffs[0]
    assert diff.tool == "dev_reviewer_poll"
    assert diff.param == "raw_text"
    assert diff.kind == "missing_in_snapshot"
    assert diff.snapshot is _MISSING


def test_extract_documented_defaults_fail_closed_on_malformed_spec() -> None:
    """Verify that extract_documented_defaults fails closed on missing or corrupted blocks."""
    with pytest.raises(ValueError, match="Missing or disordered"):
        extract_documented_defaults("No markers here")

    with pytest.raises(ValueError, match="Malformed JSON"):
        extract_documented_defaults(f"{DEFAULTS_BLOCK_BEGIN}\n{{not json\n{DEFAULTS_BLOCK_END}")

    with pytest.raises(ValueError, match="root must be a JSON object"):
        extract_documented_defaults(f"{DEFAULTS_BLOCK_BEGIN}\n[1, 2, 3]\n{DEFAULTS_BLOCK_END}")
