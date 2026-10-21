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


class SpecFormatError(Exception):
    """Raised when the machine-readable defaults block in specification is missing or corrupted."""
    pass


def extract_documented_defaults(spec_markdown: str) -> dict[str, dict[str, JSONLiteral]]:
    """Extract documented defaults dictionary from the QUENCH-PARAM-DEFAULTS marker block."""
    begin_count = spec_markdown.count(DEFAULTS_BLOCK_BEGIN)
    end_count = spec_markdown.count(DEFAULTS_BLOCK_END)

    if begin_count == 0 or end_count == 0:
        raise SpecFormatError(f"Missing QUENCH-PARAM-DEFAULTS marker: begin={begin_count}, end={end_count}")
    if begin_count > 1 or end_count > 1:
        raise SpecFormatError(f"Duplicate QUENCH-PARAM-DEFAULTS markers: begin={begin_count}, end={end_count}")

    begin_idx = spec_markdown.find(DEFAULTS_BLOCK_BEGIN)
    end_idx = spec_markdown.find(DEFAULTS_BLOCK_END)
    if end_idx < begin_idx:
        raise SpecFormatError("Disordered QUENCH-PARAM-DEFAULTS markers in spec")

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
        raise SpecFormatError(f"Malformed JSON in QUENCH-PARAM-DEFAULTS block: {exc}") from exc

    if not isinstance(data, dict):
        raise SpecFormatError("QUENCH-PARAM-DEFAULTS root must be a JSON object")

    for tool_name, params in data.items():
        if not isinstance(tool_name, str) or not isinstance(params, dict):
            raise SpecFormatError(f"Invalid tool mapping in QUENCH-PARAM-DEFAULTS for {tool_name}")
        for param_name in params:
            if not isinstance(param_name, str):
                raise SpecFormatError(f"Invalid parameter name in {tool_name}")

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
    del corrupted_snapshot["dev_reviewer_poll"]["parameters"]["properties"]["wait_max_s"]["default"]

    diffs = compare_documented_with_snapshot(documented, corrupted_snapshot)
    assert len(diffs) == 1
    diff = diffs[0]
    assert diff.tool == "dev_reviewer_poll"
    assert diff.param == "wait_max_s"
    assert diff.kind == "missing_in_snapshot"
    assert diff.snapshot is _MISSING


def test_spec_defaults_block_missing_tags_raises() -> None:
    """Verify that missing BEGIN or END marker raises SpecFormatError."""
    with pytest.raises(SpecFormatError, match="Missing QUENCH-PARAM-DEFAULTS"):
        extract_documented_defaults(f"content without begin\n{DEFAULTS_BLOCK_END}")
    with pytest.raises(SpecFormatError, match="Missing QUENCH-PARAM-DEFAULTS"):
        extract_documented_defaults(f"{DEFAULTS_BLOCK_BEGIN}\n{{}}\n")
    with pytest.raises(SpecFormatError, match="Missing QUENCH-PARAM-DEFAULTS"):
        extract_documented_defaults("no tags at all")


def test_spec_defaults_block_duplicate_tags_raises() -> None:
    """Verify that duplicate BEGIN or END markers raise SpecFormatError."""
    with pytest.raises(SpecFormatError, match="Duplicate QUENCH-PARAM-DEFAULTS"):
        extract_documented_defaults(f"{DEFAULTS_BLOCK_BEGIN}\n{DEFAULTS_BLOCK_BEGIN}\n{{}}\n{DEFAULTS_BLOCK_END}")
    with pytest.raises(SpecFormatError, match="Duplicate QUENCH-PARAM-DEFAULTS"):
        extract_documented_defaults(f"{DEFAULTS_BLOCK_BEGIN}\n{{}}\n{DEFAULTS_BLOCK_END}\n{DEFAULTS_BLOCK_END}")


def test_spec_defaults_block_invalid_json_raises() -> None:
    """Verify that invalid JSON within markers raises SpecFormatError."""
    with pytest.raises(SpecFormatError, match="Malformed JSON"):
        extract_documented_defaults(f"{DEFAULTS_BLOCK_BEGIN}\n{{not json\n{DEFAULTS_BLOCK_END}")
    with pytest.raises(SpecFormatError, match="Malformed JSON"):
        extract_documented_defaults(f"{DEFAULTS_BLOCK_BEGIN}\n```json\n{{invalid: 123}}\n```\n{DEFAULTS_BLOCK_END}")


def test_spec_defaults_block_top_level_non_dict_raises() -> None:
    """Verify that top-level non-dict JSON or invalid mappings raise SpecFormatError."""
    with pytest.raises(SpecFormatError, match="root must be a JSON object"):
        extract_documented_defaults(f"{DEFAULTS_BLOCK_BEGIN}\n[1, 2, 3]\n{DEFAULTS_BLOCK_END}")
    with pytest.raises(SpecFormatError, match="root must be a JSON object"):
        extract_documented_defaults(f"{DEFAULTS_BLOCK_BEGIN}\n\"string\"\n{DEFAULTS_BLOCK_END}")
    with pytest.raises(SpecFormatError, match="Invalid tool mapping"):
        extract_documented_defaults(f"{DEFAULTS_BLOCK_BEGIN}\n{{\"dev_tasks_status\": [1, 2]}}\n{DEFAULTS_BLOCK_END}")

