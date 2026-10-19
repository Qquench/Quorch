"""ide_schema_export.py - Pure Logic Exporter for IDE Tool Schemas.

Pure functions for schema validation, canonicalization, envelope parsing, and CLI runner.
MODULE-LEVEL INVARIANT: Strictly zero import of server, fastmcp, yaml, or subprocess.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Final

from path_guard import PathTraversalError, assert_dir_contained
from tool_surface_constants import (
    EXPECTED_TOOL_NAMES,
    META_ALLOWED_KEYS,
    MISSING,
    SCHEMA_META_KEY,
    SNAPSHOT_SCHEMA_VERSION,
    TOOL_COUNT,
    _MissingSentinel,
)

CR: Final[bytes] = bytes([13])
LF: Final[bytes] = bytes([10])
ENVELOPE_BEGIN: Final[str] = "@@QUENCH-SCHEMA-BEGIN@@"
ENVELOPE_END: Final[str] = "@@QUENCH-SCHEMA-END@@"
ENVELOPE_MAX_BYTES: Final[int] = 8 * 1024 * 1024
_VOLATILE_SCHEMA_KEYS: Final[frozenset[str]] = frozenset({"$schema", "title"})
SNAPSHOT_FILENAME: Final[str] = "ide_tool_schemas.json"

EXIT_OK: Final[int] = 0
EXIT_DRIFT: Final[int] = 1
EXIT_INVALID: Final[int] = 2

# Repository root anchor: 3 levels up from this file (server -> quench-dev-tasks -> plugins -> repo)
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]


class SchemaExportError(Exception):
    """Base exception for schema export failures."""
    pass


class SentinelLeakError(SchemaExportError):
    """Raised when MISSING sentinel leaks into exportable data structures."""
    pass


class EnvelopeError(SchemaExportError):
    """Raised when envelope parsing fails."""
    pass


def assert_no_sentinel_leak(obj: Any) -> None:
    """Recursively verify that no MISSING sentinel object is present."""
    if obj is MISSING or isinstance(obj, _MissingSentinel) or repr(obj) == "<MISSING>":
        raise SentinelLeakError("MISSING sentinel leaked into schema data")

    if isinstance(obj, dict):
        for k, v in obj.items():
            if k is MISSING or isinstance(k, _MissingSentinel):
                raise SentinelLeakError("MISSING sentinel leaked into dict key")
            assert_no_sentinel_leak(v)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            assert_no_sentinel_leak(item)


def _strip_volatile_keys(obj: Any) -> Any:
    """Recursively strip volatile schema keys ($schema, title) from schema dictionaries."""
    if isinstance(obj, dict):
        return {
            k: _strip_volatile_keys(v)
            for k, v in obj.items()
            if k not in _VOLATILE_SCHEMA_KEYS
        }
    if isinstance(obj, list):
        return [_strip_volatile_keys(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_strip_volatile_keys(item) for item in obj)
    return obj


def validate_schema_doc(schemas: dict[str, Any]) -> None:
    """Validate schema document structure against SSOT contracts.

    Invariants:
    1. Must be dict
    2. Keys must exactly equal EXPECTED_TOOL_NAMES | {_meta}
    3. _meta must equal {"schema_version": 1}
    4. No tool name starts with underscore
    5. Zero sentinel leaks
    6. All defaults and contents must be JSON serializable without NaN
    """
    if not isinstance(schemas, dict):
        raise SchemaExportError("Schemas document must be a dictionary")

    expected_keys = set(EXPECTED_TOOL_NAMES) | {SCHEMA_META_KEY}
    actual_keys = set(schemas.keys())
    if actual_keys != expected_keys:
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        raise SchemaExportError(
            f"Schema keys mismatch. Expected {len(expected_keys)} keys, got {len(actual_keys)}. "
            f"Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        )

    meta = schemas.get(SCHEMA_META_KEY)
    if not isinstance(meta, dict):
        raise SchemaExportError(f"'{SCHEMA_META_KEY}' must be a dictionary")
    if set(meta.keys()) != set(META_ALLOWED_KEYS):
        raise SchemaExportError(f"'{SCHEMA_META_KEY}' keys must be {sorted(META_ALLOWED_KEYS)}, got {sorted(meta.keys())}")
    if meta.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise SchemaExportError(
            f"Expected schema_version {SNAPSHOT_SCHEMA_VERSION}, got {meta.get('schema_version')}"
        )

    for tool_name, tool_data in schemas.items():
        if tool_name == SCHEMA_META_KEY:
            continue
        if tool_name.startswith("_"):
            raise SchemaExportError(f"Tool name '{tool_name}' must not start with '_'")
        if not isinstance(tool_data, dict):
            raise SchemaExportError(f"Tool schema for '{tool_name}' must be a dictionary")

    assert_no_sentinel_leak(schemas)

    try:
        json.dumps(schemas, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise SchemaExportError(f"Schemas document contains non-JSON-serializable content: {e}")


def canonicalize_schemas(schemas: dict[str, Any]) -> str:
    """Canonicalize schema dictionary into deterministic JSON string.

    Strips volatile keys, enforces sorting, 2-space indent, ensure_ascii=False,
    prohibits NaN, appends exactly one LF, and asserts no CR bytes.
    """
    cleaned = _strip_volatile_keys(schemas)
    validate_schema_doc(cleaned)
    assert_no_sentinel_leak(cleaned)

    body = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    canonical = body + "\n"

    encoded = canonical.encode("utf-8")
    if CR in encoded:
        raise SchemaExportError("CR byte detected in canonical schema output")
    if not encoded.endswith(LF):
        raise SchemaExportError("Canonical schema output must end with LF")
    if encoded.endswith(LF * 2):
        raise SchemaExportError("Canonical schema output must not end with multiple LFs")

    return canonical


def parse_envelope(stdout: str) -> dict[str, Any]:
    """Parse schema document from introspect child process envelope.

    Expects exactly one begin tag, one end tag, bounded byte length, and valid JSON.
    """
    encoded = stdout.encode("utf-8")
    if len(encoded) > ENVELOPE_MAX_BYTES:
        raise EnvelopeError(
            f"Stdout envelope size {len(encoded)} exceeds maximum {ENVELOPE_MAX_BYTES} bytes"
        )

    begin_count = stdout.count(ENVELOPE_BEGIN)
    end_count = stdout.count(ENVELOPE_END)

    if begin_count != 1:
        raise EnvelopeError(f"Expected exactly 1 '{ENVELOPE_BEGIN}', found {begin_count}")
    if end_count != 1:
        raise EnvelopeError(f"Expected exactly 1 '{ENVELOPE_END}', found {end_count}")

    begin_idx = stdout.find(ENVELOPE_BEGIN)
    end_idx = stdout.find(ENVELOPE_END)

    if end_idx <= begin_idx:
        raise EnvelopeError("Envelope end marker appears before begin marker")

    payload = stdout[begin_idx + len(ENVELOPE_BEGIN) : end_idx].strip()
    if not payload:
        raise EnvelopeError("Envelope payload is empty")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise EnvelopeError(f"Failed to decode JSON from envelope payload: {e}")

    validate_schema_doc(data)
    return data


def _atomic_write(dest_file: Path, content: str) -> None:
    """Atomically write content to dest_file using binary mode and temporary file replace.

    Uses dir=dest_dir to prevent EXDEV, writes UTF-8 bytes directly to prevent CRLF translation,
    applies mode 0o644 on POSIX, and cleans temporary file in finally block.
    """
    dest_dir = dest_file.parent
    dest_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{dest_file.name}.", suffix=".tmp", dir=str(dest_dir)
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content.encode("utf-8"))
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass

        if sys.platform != "win32":
            try:
                os.chmod(tmp_path, 0o644)
            except OSError:
                pass

        os.replace(tmp_path, dest_file)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def export_ide_schemas(
    dest_dir: Path, schemas: dict[str, Any], *, dry_run: bool = False
) -> list[str]:
    """Export ide_tool_schemas.json into destination directory.

    Returns list containing the path of generated file. Length is always <= 1.
    """
    canonical_text = canonicalize_schemas(schemas)
    dest_file = dest_dir / SNAPSHOT_FILENAME

    if dry_run:
        return [str(dest_file)]

    _atomic_write(dest_file, canonical_text)
    return [str(dest_file)]


def run_cli(
    argv: list[str] | None = None,
    *,
    introspect: Callable[[], dict[str, Any]],
) -> int:
    """Run schema export CLI with --write, --check, and --cache-dir options.

    Returns exit code:
      0: consistent / write success
      1: drift detected / snapshot missing in check mode
      2: invalid arguments / non-existent directory / corrupted json / validation failure
    """
    parser = argparse.ArgumentParser(
        description="Quench IDE Tool Schema SSOT Export and Verification Tool"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--write", action="store_true", help="Atomically write canonical schemas to snapshot file"
    )
    group.add_argument(
        "--check", action="store_true", help="Verify snapshot file matches live surface without modifying disk"
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=str(_REPO_ROOT / "docs" / "architecture"),
        help="Target directory for ide_tool_schemas.json (defaults to docs/architecture)",
    )

    args = parser.parse_args(argv)
    cache_dir_cand = Path(args.cache_dir)

    # Confinement assertion: must be within repo root
    try:
        # If cache_dir does not exist, resolve its parent or path to check containment
        cand_resolved = cache_dir_cand.resolve()
        assert_dir_contained(_REPO_ROOT, cand_resolved)
    except (PathTraversalError, ValueError, OSError) as e:
        sys.stderr.write(f"Error: cache-dir escapes repository root or violates path safety: {e}\n")
        return EXIT_INVALID

    dest_dir = cand_resolved
    target_file = dest_dir / SNAPSHOT_FILENAME

    if args.check:
        # Check mode must be strictly read-only: no mkdir, no writes
        if not dest_dir.is_dir():
            sys.stderr.write(f"Error: Target directory does not exist: {dest_dir}\n")
            return EXIT_INVALID

        if not target_file.is_file():
            sys.stderr.write(f"Drift: Target snapshot file does not exist: {target_file}\n")
            return EXIT_DRIFT

        try:
            disk_bytes = target_file.read_bytes()
        except OSError as e:
            sys.stderr.write(f"Error: Cannot read snapshot file: {e}\n")
            return EXIT_INVALID

        try:
            disk_text = disk_bytes.decode("utf-8")
            disk_data = json.loads(disk_text)
            validate_schema_doc(disk_data)
        except Exception as e:
            sys.stderr.write(f"Error: Snapshot file is corrupted or fails schema contract: {e}\n")
            return EXIT_INVALID

        try:
            live_schemas = introspect()
            validate_schema_doc(live_schemas)
            expected_canonical_bytes = canonicalize_schemas(live_schemas).encode("utf-8")
        except Exception as e:
            sys.stderr.write(f"Error: Failed to introspect live schemas: {e}\n")
            return EXIT_INVALID

        # B-04: strict byte equality with raw disk bytes
        if expected_canonical_bytes != disk_bytes:
            sys.stderr.write("Drift: In-memory live schema diverges from disk snapshot bytes.\n")
            return EXIT_DRIFT

        return EXIT_OK

    if args.write:
        try:
            live_schemas = introspect()
            validate_schema_doc(live_schemas)
            export_ide_schemas(dest_dir, live_schemas, dry_run=False)
            return EXIT_OK
        except Exception as e:
            sys.stderr.write(f"Error during schema export write: {e}\n")
            return EXIT_INVALID

    return EXIT_INVALID
