"""Unit tests for probe_client_capabilities script and client compatibility baseline."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

# Ensure scripts directory is in path
SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from probe_client_capabilities import (
    ClientCapabilityReport,
    diff_against_baseline,
    emit_baseline,
    load_baseline,
    main,
    normalize_capabilities,
    probe_client_capabilities,
)


def test_normalize_capabilities_various_shapes():
    """Test normalizing raw MCP capabilities into dict[str, bool]."""
    raw = {
        "sampling": {},
        "roots": {"listChanged": True},
        "prompts": {"listChanged": False},
        "logging": True,
        "experimental": None,
        "tools": False,
    }
    normalized = normalize_capabilities(raw)
    assert normalized["sampling"] is True
    assert normalized["roots"] is True
    assert normalized["roots.listChanged"] is True
    assert normalized["prompts"] is True
    assert normalized["prompts.listChanged"] is False
    assert normalized["logging"] is True
    assert normalized["experimental"] is False
    assert normalized["tools"] is False


def test_normalize_capabilities_non_dict():
    assert normalize_capabilities(None) == {}
    assert normalize_capabilities("invalid") == {}


def test_probe_client_capabilities_normal_stdio():
    """Test standard MCP initialize handshake via stdio with a mock child process."""
    server_code = (
        "import sys, json\n"
        "line = sys.stdin.readline()\n"
        "req = json.loads(line)\n"
        "resp = {\n"
        "  'jsonrpc': '2.0',\n"
        "  'id': req.get('id', 1),\n"
        "  'result': {\n"
        "    'protocolVersion': '2024-11-05',\n"
        "    'clientInfo': {'name': 'mock-agent', 'version': '2.1.0'},\n"
        "    'capabilities': {'sampling': {}, 'tools': {'listChanged': True}}\n"
        "  }\n"
        "}\n"
        "sys.stdout.write(json.dumps(resp) + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    endpoint = f'"{sys.executable}" -c "{server_code}"'
    report = probe_client_capabilities(
        transport="stdio",
        endpoint=endpoint,
        timeout_ms=5000,
    )

    assert report["status"] == "ok"
    assert report["client_name"] == "mock-agent"
    assert report["client_version"] == "2.1.0"
    assert report["protocol_version"] == "2024-11-05"
    assert report["transports"] == ["stdio"]
    assert report["capabilities"]["sampling"] is True
    assert report["capabilities"]["tools"] is True
    assert report["capabilities"]["tools.listChanged"] is True
    assert report["probe_duration_ms"] >= 0


def test_probe_client_capabilities_timeout_stdio():
    """Test timeout circuit breaker when child process hangs."""
    server_code = "import time; time.sleep(5)\n"
    endpoint = f'"{sys.executable}" -c "{server_code}"'
    report = probe_client_capabilities(
        transport="stdio",
        endpoint=endpoint,
        timeout_ms=150,
    )
    assert report["status"] == "timeout"
    assert report["capabilities"] == {}


def test_probe_client_capabilities_malformed_json_stdio():
    """Test resilience against malformed non-JSON output from child process."""
    server_code = "import sys\nsys.stdout.write('MALFORMED NOT JSON\\n')\nsys.stdout.flush()\n"
    endpoint = f'"{sys.executable}" -c "{server_code}"'
    report = probe_client_capabilities(
        transport="stdio",
        endpoint=endpoint,
        timeout_ms=3000,
    )
    assert report["status"] == "error"
    assert report["capabilities"] == {}


def test_probe_client_capabilities_error_payload_stdio():
    """Test handling of JSON-RPC error responses."""
    server_code = (
        "import sys, json\n"
        "sys.stdin.readline()\n"
        "resp = {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32600, 'message': 'Unsupported'}}\n"
        "sys.stdout.write(json.dumps(resp) + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    endpoint = f'"{sys.executable}" -c "{server_code}"'
    report = probe_client_capabilities(
        transport="stdio",
        endpoint=endpoint,
        timeout_ms=3000,
    )
    assert report["status"] == "error"


def test_probe_client_capabilities_unavailable_binary():
    """Test nonexistent executable handles FileNotFoundError gracefully."""
    report = probe_client_capabilities(
        transport="stdio",
        endpoint="non_existent_binary_for_test_xyz_12345",
        timeout_ms=1000,
    )
    assert report["status"] == "unavailable"


def test_probe_client_capabilities_empty_endpoint():
    """Test empty endpoint returns status='unavailable'."""
    report = probe_client_capabilities(transport="stdio", endpoint=None)
    assert report["status"] == "unavailable"

    report_empty = probe_client_capabilities(transport="stdio", endpoint="")
    assert report_empty["status"] == "unavailable"


def test_probe_client_capabilities_invalid_transport():
    """Test invalid transport returns status='error'."""
    report = probe_client_capabilities(transport="invalid_mode", endpoint="foo")  # type: ignore
    assert report["status"] == "error"


def test_probe_client_capabilities_http_success():
    """Test HTTP transport successful probe."""
    mock_resp = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "remote-service", "version": "1.0"},
            "capabilities": {"sampling": False, "roots": {}},
        },
    }

    mock_urlopen = MagicMock()
    mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
        mock_resp
    ).encode("utf-8")

    with patch("urllib.request.urlopen", mock_urlopen):
        report = probe_client_capabilities(
            transport="http",
            endpoint="http://localhost:8080/mcp",
            timeout_ms=1000,
        )
        assert report["status"] == "ok"
        assert report["client_name"] == "remote-service"
        assert report["capabilities"]["sampling"] is False
        assert report["capabilities"]["roots"] is True


def test_probe_client_capabilities_http_unavailable_and_timeout():
    """Test HTTP transport failure states."""
    # Timeout
    with patch(
        "urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")
    ):
        report_to = probe_client_capabilities(
            transport="http", endpoint="http://localhost:8080/mcp", timeout_ms=500
        )
        assert report_to["status"] == "timeout"

    # ConnectionRefused
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError(ConnectionRefusedError("Refused")),
    ):
        report_un = probe_client_capabilities(
            transport="http", endpoint="http://localhost:8080/mcp", timeout_ms=500
        )
        assert report_un["status"] == "unavailable"


def test_diff_against_baseline():
    """Test diffing capability reports against baseline definitions."""
    baseline = {
        "capabilities": {
            "sampling": True,
            "tools": True,
            "logging": False,
        }
    }

    # Case 1: Exact match / compatible
    rep1: ClientCapabilityReport = {
        "schema_version": "1.0",
        "client_name": "test",
        "client_version": "1.0",
        "protocol_version": "2024-11-05",
        "transports": ["stdio"],
        "capabilities": {"sampling": True, "tools": True, "logging": False},
        "status": "ok",
        "probed_at_utc": "2026-09-24T00:00:00Z",
        "probe_duration_ms": 10,
    }
    d1 = diff_against_baseline(rep1, baseline)
    assert d1["added"] == []
    assert d1["missing"] == []
    assert d1["changed"] == []
    assert d1["compatible"] is True

    # Case 2: Added capability (upgraded)
    rep2 = dict(rep1, capabilities={"sampling": True, "tools": True, "logging": False, "roots": True})
    d2 = diff_against_baseline(rep2, baseline)  # type: ignore
    assert d2["added"] == ["roots"]
    assert d2["missing"] == []
    assert d2["compatible"] is True

    # Case 3: Missing required capability
    rep3 = dict(rep1, capabilities={"tools": True, "logging": False})
    d3 = diff_against_baseline(rep3, baseline)  # type: ignore
    assert d3["missing"] == ["sampling"]
    assert d3["compatible"] is False

    # Case 4: Degraded capability (sampling was True, now False)
    rep4 = dict(rep1, capabilities={"sampling": False, "tools": True, "logging": False})
    d4 = diff_against_baseline(rep4, baseline)  # type: ignore
    assert d4["changed"] == ["sampling"]
    assert d4["compatible"] is False

    # Case 5: Report status error
    rep5 = dict(rep1, status="timeout")
    d5 = diff_against_baseline(rep5, baseline)  # type: ignore
    assert d5["compatible"] is False


def test_emit_and_load_baseline_atomic(tmp_path):
    """Test atomic emission and reloading of baseline."""
    target_file = tmp_path / "baselines" / "client_baseline.json"
    report: ClientCapabilityReport = {
        "schema_version": "1.0",
        "client_name": "agent-x",
        "client_version": "1.2.3",
        "protocol_version": "2024-11-05",
        "transports": ["stdio"],
        "capabilities": {"sampling": True},
        "status": "ok",
        "probed_at_utc": "2026-09-24T12:00:00Z",
        "probe_duration_ms": 25,
    }

    emit_baseline(report, str(target_file))
    assert target_file.exists()

    loaded = load_baseline(str(target_file))
    assert loaded["client_name"] == "agent-x"
    assert loaded["capabilities"]["sampling"] is True

    # Overwrite atomically
    report_updated = dict(report, client_version="1.2.4")
    emit_baseline(report_updated, str(target_file))  # type: ignore
    loaded2 = load_baseline(str(target_file))
    assert loaded2["client_version"] == "1.2.4"


def test_cli_execution_with_baseline(tmp_path, monkeypatch, capsys):
    """Test CLI entrypoint with emit and diff options."""
    base_file = tmp_path / "base.json"
    emit_file = tmp_path / "emitted.json"

    base_data = {
        "schema_version": "1.0",
        "capabilities": {"sampling": True},
    }
    base_file.write_text(json.dumps(base_data), encoding="utf-8")

    server_code = (
        "import sys, json\n"
        "sys.stdin.readline()\n"
        "resp = {'jsonrpc': '2.0', 'id': 1, 'result': {'clientInfo': {'name': 'cli-test', 'version': '1.0'}, 'capabilities': {'sampling': True}}}\n"
        "sys.stdout.write(json.dumps(resp) + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    endpoint = f'"{sys.executable}" -c "{server_code}"'

    test_args = [
        "probe_client_capabilities.py",
        "--transport", "stdio",
        "--endpoint", endpoint,
        "--baseline", str(base_file),
        "--emit-baseline", str(emit_file),
    ]

    monkeypatch.setattr(sys, "argv", test_args)
    ret = main()
    assert ret == 0

    out, _ = capsys.readouterr()
    result = json.loads(out)
    assert result["report"]["status"] == "ok"
    assert result["diff"]["compatible"] is True
    assert emit_file.exists()
