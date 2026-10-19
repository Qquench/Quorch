"""test_ide_schema_export.py - Tier-1 Fast Pure Function Tests for IDE Schema Export.

Strictly zero import of server / fastmcp / subprocess / network.
Tests sentinel identity, envelope parsing, validation constraints, volatile key stripping,
and ternary default accessors.
"""

from __future__ import annotations

import copy
import json
import pickle
import sys
from pathlib import Path
from typing import Any

import pytest

import ide_schema_export as exporter
import tool_surface_constants as const


@pytest.mark.tier1_fast
def test_missing_sentinel_identity_and_pickle() -> None:
    sentinel = const.MISSING
    assert repr(sentinel) == "<MISSING>"
    assert sentinel is const.MISSING

    # Pickle preserves identity
    dumped = pickle.dumps(sentinel)
    reloaded = pickle.loads(dumped)
    assert reloaded is const.MISSING

    # Copy and deepcopy preserve identity
    assert copy.copy(sentinel) is const.MISSING
    assert copy.deepcopy(sentinel) is const.MISSING

    # Prohibited in boolean context
    with pytest.raises(TypeError, match="MISSING 禁止用于布尔上下文"):
        if sentinel:
            pass


@pytest.mark.tier1_fast
def test_ternary_default_accessors() -> None:
    # 1. Parameter with default: None
    data_none = {"tool_a": {"param_p": {"default": None}}}
    assert const.has_default(data_none, "tool_a", "param_p") is True
    assert const.get_default(data_none, "tool_a", "param_p") is None

    # 2. Parameter with no default key
    data_empty = {"tool_a": {"param_p": {}}}
    assert const.has_default(data_empty, "tool_a", "param_p") is False
    assert const.get_default(data_empty, "tool_a", "param_p") is const.MISSING

    # 3. Missing parameter or tool
    assert const.has_default(data_empty, "tool_a", "nonexistent") is False
    assert const.get_default(data_empty, "tool_a", "nonexistent") is const.MISSING
    assert const.has_default(data_empty, "nonexistent", "param_p") is False
    assert const.get_default(data_empty, "nonexistent", "param_p") is const.MISSING

    # 4. Standard properties hierarchy
    data_props = {
        "tool_b": {
            "parameters": {
                "properties": {
                    "count": {"default": 10, "type": "integer"},
                    "flag": {"default": False, "type": "boolean"},
                    "unspecified": {"type": "string"},
                }
            }
        }
    }
    assert const.has_default(data_props, "tool_b", "count") is True
    assert const.get_default(data_props, "tool_b", "count") == 10
    assert const.has_default(data_props, "tool_b", "flag") is True
    assert const.get_default(data_props, "tool_b", "flag") is False
    assert const.has_default(data_props, "tool_b", "unspecified") is False
    assert const.get_default(data_props, "tool_b", "unspecified") is const.MISSING

    param_names = const.iter_param_names(data_props, "tool_b")
    assert param_names == frozenset({"count", "flag", "unspecified"})


@pytest.mark.tier1_fast
def test_sentinel_leak_detection() -> None:
    # Clean structures pass
    exporter.assert_no_sentinel_leak({"a": 1, "b": [None, False, "str"]})

    # Leaks in values
    with pytest.raises(exporter.SentinelLeakError):
        exporter.assert_no_sentinel_leak({"a": const.MISSING})

    with pytest.raises(exporter.SentinelLeakError):
        exporter.assert_no_sentinel_leak([1, 2, const.MISSING])

    # Leaks in keys
    with pytest.raises(exporter.SentinelLeakError):
        exporter.assert_no_sentinel_leak({const.MISSING: 1})


@pytest.mark.tier1_fast
def test_strip_volatile_keys_recursive() -> None:
    doc = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "TopTitle",
        "nested": {
            "title": "ParamTitle",
            "type": "string",
            "inner_list": [
                {"$schema": "nested_schema", "name": "foo"},
                {"title": "ListItemTitle", "value": 42},
            ],
        },
    }
    cleaned = exporter._strip_volatile_keys(doc)
    assert "$schema" not in cleaned
    assert "title" not in cleaned
    assert "title" not in cleaned["nested"]
    assert cleaned["nested"]["type"] == "string"
    assert "$schema" not in cleaned["nested"]["inner_list"][0]
    assert cleaned["nested"]["inner_list"][0]["name"] == "foo"
    assert "title" not in cleaned["nested"]["inner_list"][1]
    assert cleaned["nested"]["inner_list"][1]["value"] == 42


def _make_valid_doc() -> dict[str, Any]:
    doc: dict[str, Any] = {
        const.SCHEMA_META_KEY: {
            "schema_version": const.SNAPSHOT_SCHEMA_VERSION,
        }
    }
    for name in sorted(const.EXPECTED_TOOL_NAMES):
        doc[name] = {
            "description": f"Description for {name}",
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_arg": {"type": "string", "default": "val"},
                },
            },
        }
    return doc


@pytest.mark.tier1_fast
def test_validate_schema_doc_invariants() -> None:
    valid = _make_valid_doc()
    exporter.validate_schema_doc(valid)

    # Missing meta
    no_meta = dict(valid)
    del no_meta[const.SCHEMA_META_KEY]
    with pytest.raises(exporter.SchemaExportError, match="Schema keys mismatch"):
        exporter.validate_schema_doc(no_meta)

    # Invalid meta version
    bad_meta = _make_valid_doc()
    bad_meta[const.SCHEMA_META_KEY] = {"schema_version": 999}
    with pytest.raises(exporter.SchemaExportError, match="schema_version"):
        exporter.validate_schema_doc(bad_meta)

    # Missing a required tool
    missing_one = _make_valid_doc()
    del missing_one["dev_tasks_status"]
    with pytest.raises(exporter.SchemaExportError, match="Missing.*dev_tasks_status"):
        exporter.validate_schema_doc(missing_one)

    # Extra tool
    extra = _make_valid_doc()
    extra["extra_tool"] = {}
    with pytest.raises(exporter.SchemaExportError, match="Extra.*extra_tool"):
        exporter.validate_schema_doc(extra)

    # Tool starting with underscore
    bad_tool = _make_valid_doc()
    bad_tool["_invalid_tool"] = {}
    del bad_tool["dev_tasks_status"]
    with pytest.raises(exporter.SchemaExportError):
        exporter.validate_schema_doc(bad_tool)


@pytest.mark.tier1_fast
def test_canonicalize_schemas_idempotence_and_format() -> None:
    doc = _make_valid_doc()
    # Add volatile keys to verify they get stripped
    doc["title"] = "ShouldBeStripped"
    doc["dev_tasks_status"]["title"] = "ToolTitle"

    text1 = exporter.canonicalize_schemas(doc)
    text2 = exporter.canonicalize_schemas(json.loads(text1))

    assert text1 == text2
    assert "ShouldBeStripped" not in text1
    assert "ToolTitle" not in text1

    raw_bytes = text1.encode("utf-8")
    assert exporter.CR not in raw_bytes
    assert raw_bytes.endswith(exporter.LF)
    assert not raw_bytes.endswith(exporter.LF * 2)


@pytest.mark.tier1_fast
def test_parse_envelope_states() -> None:
    valid_doc = _make_valid_doc()
    canonical_body = exporter.canonicalize_schemas(valid_doc)

    # 1. Valid envelope
    valid_envelope = f"{exporter.ENVELOPE_BEGIN}\n{canonical_body}{exporter.ENVELOPE_END}\n"
    parsed = exporter.parse_envelope(valid_envelope)
    assert parsed[const.SCHEMA_META_KEY] == {"schema_version": 1}

    # 2. Missing begin marker
    with pytest.raises(exporter.EnvelopeError, match="Expected exactly 1.*BEGIN"):
        exporter.parse_envelope(f"{canonical_body}{exporter.ENVELOPE_END}\n")

    # 3. Missing end marker
    with pytest.raises(exporter.EnvelopeError, match="Expected exactly 1.*END"):
        exporter.parse_envelope(f"{exporter.ENVELOPE_BEGIN}\n{canonical_body}")

    # 4. Duplicate begin marker
    dup_begin = f"{exporter.ENVELOPE_BEGIN}\n{exporter.ENVELOPE_BEGIN}\n{canonical_body}{exporter.ENVELOPE_END}\n"
    with pytest.raises(exporter.EnvelopeError, match="Expected exactly 1.*BEGIN"):
        exporter.parse_envelope(dup_begin)

    # 5. Invalid JSON inside envelope
    bad_json = f"{exporter.ENVELOPE_BEGIN}\n{'{ invalid json'}\n{exporter.ENVELOPE_END}\n"
    with pytest.raises(exporter.EnvelopeError, match="Failed to decode JSON"):
        exporter.parse_envelope(bad_json)

    # 6. Exceeding max bytes
    huge_payload = f"{exporter.ENVELOPE_BEGIN}\n" + ("x" * (exporter.ENVELOPE_MAX_BYTES + 10)) + f"\n{exporter.ENVELOPE_END}"
    with pytest.raises(exporter.EnvelopeError, match="exceeds maximum"):
        exporter.parse_envelope(huge_payload)


@pytest.mark.tier1_fast
def test_export_ide_schemas_dry_run(tmp_path: Path) -> None:
    doc = _make_valid_doc()
    dest_dir = tmp_path / "non_existent_subdir"
    out = exporter.export_ide_schemas(dest_dir, doc, dry_run=True)
    assert len(out) == 1
    assert out[0] == str(dest_dir / exporter.SNAPSHOT_FILENAME)
    # Dry run must not touch or create directory
    assert not dest_dir.exists()
