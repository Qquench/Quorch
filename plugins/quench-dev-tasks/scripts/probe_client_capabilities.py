#!/usr/bin/env python3
"""Quench DevTasks - Client Capability Probe Script.

Standalone, zero-external-dependency probe script for inspecting and verifying
downstream MCP client capabilities and establishing compatibility baselines.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
from datetime import datetime, timezone
import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Literal, Optional, TypedDict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class ClientCapabilityReport(TypedDict):
    schema_version: str
    client_name: str
    client_version: str
    protocol_version: str
    transports: list[str]  # ['stdio', 'sse', 'http']
    capabilities: dict[str, bool]
    status: Literal['ok', 'timeout', 'unavailable', 'error']
    probed_at_utc: str
    probe_duration_ms: int


def normalize_capabilities(raw: Any) -> dict[str, bool]:
    """Normalize raw MCP capabilities object into a flat dict[str, bool]."""
    normalized: dict[str, bool] = {}
    if not isinstance(raw, dict):
        return normalized

    for k, v in raw.items():
        if isinstance(v, bool):
            normalized[k] = v
        elif isinstance(v, dict):
            normalized[k] = True
            for sub_k, sub_v in v.items():
                compound_key = f"{k}.{sub_k}"
                if isinstance(sub_v, bool):
                    normalized[compound_key] = sub_v
                elif sub_v is not None:
                    normalized[compound_key] = bool(sub_v)
        elif v is None:
            normalized[k] = False
        else:
            normalized[k] = bool(v)
    return normalized


def _sanitize_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return endpoint
    try:
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme in ("http", "https"):
            qs = urllib.parse.parse_qs(parsed.query)
            redacted_qs = {}
            for k, vals in qs.items():
                if any(sec in k.lower() for sec in ("key", "token", "secret", "auth", "pwd")):
                    redacted_qs[k] = ["<REDACTED>"]
                else:
                    redacted_qs[k] = vals
            new_query = urllib.parse.urlencode(redacted_qs, doseq=True)
            return urllib.parse.urlunparse(parsed._replace(query=new_query))
    except Exception:
        pass
    return endpoint


async def _probe_stdio_async(
    cmd: list[str],
    timeout_sec: float,
) -> tuple[Literal['ok', 'timeout', 'unavailable', 'error'], dict[str, Any]]:
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, PermissionError, OSError):
        return "unavailable", {}

    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "quorch-probe",
                "version": "1.0.0",
            },
        },
    }

    try:
        init_payload = (json.dumps(init_req) + "\n").encode("utf-8")
        if proc.stdin:
            proc.stdin.write(init_payload)
            await proc.stdin.drain()

        if proc.stdout is None:
            return "error", {}

        line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_sec)
        if not line_bytes:
            return ("unavailable" if proc.returncode is not None and proc.returncode != 0 else "error"), {}

        line_str = line_bytes.decode("utf-8", errors="replace").strip()
        data = json.loads(line_str)
        if not isinstance(data, dict):
            return "error", {}

        if "error" in data:
            return "error", {}

        result = data.get("result")
        if not isinstance(result, dict):
            return "error", {}

        return "ok", result
    except asyncio.TimeoutError:
        return "timeout", {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "error", {}
    except Exception:
        return "error", {}
    finally:
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=0.5)
            except Exception:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)


def _split_command(cmd_str: str) -> list[str]:
    """Cross-platform command line splitter that strips enclosing quotes."""
    if sys.platform == "win32":
        try:
            tokens = shlex.split(cmd_str, posix=False)
        except Exception:
            tokens = [cmd_str]
        cleaned = []
        for t in tokens:
            if len(t) >= 2 and ((t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'"))):
                cleaned.append(t[1:-1])
            else:
                cleaned.append(t)
        return cleaned
    else:
        try:
            return shlex.split(cmd_str, posix=True)
        except Exception:
            return [cmd_str]


def probe_client_capabilities(
    transport: Literal['stdio', 'sse', 'http'],
    endpoint: str | None = None,
    *,
    timeout_ms: int = 5000,
) -> ClientCapabilityReport:
    """Probe downstream client capabilities via stdio, sse, or http."""
    start_time = time.monotonic()
    now_utc = datetime.now(timezone.utc).isoformat()
    timeout_sec = max(0.001, timeout_ms / 1000.0)

    if transport not in ("stdio", "sse", "http"):
        return ClientCapabilityReport(
            schema_version="1.0",
            client_name="unknown",
            client_version="unknown",
            protocol_version="unknown",
            transports=[str(transport)],
            capabilities={},
            status="error",
            probed_at_utc=now_utc,
            probe_duration_ms=int((time.monotonic() - start_time) * 1000),
        )

    if not endpoint:
        return ClientCapabilityReport(
            schema_version="1.0",
            client_name="unknown",
            client_version="unknown",
            protocol_version="unknown",
            transports=[transport],
            capabilities={},
            status="unavailable",
            probed_at_utc=now_utc,
            probe_duration_ms=int((time.monotonic() - start_time) * 1000),
        )

    if transport == "stdio":
        cmd = _split_command(endpoint)

        if not cmd:
            return ClientCapabilityReport(
                schema_version="1.0",
                client_name="unknown",
                client_version="unknown",
                protocol_version="unknown",
                transports=[transport],
                capabilities={},
                status="unavailable",
                probed_at_utc=now_utc,
                probe_duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        status, result = _run_async(_probe_stdio_async(cmd, timeout_sec))
        duration_ms = int((time.monotonic() - start_time) * 1000)

        if status != "ok":
            return ClientCapabilityReport(
                schema_version="1.0",
                client_name="unknown",
                client_version="unknown",
                protocol_version="unknown",
                transports=[transport],
                capabilities={},
                status=status,
                probed_at_utc=now_utc,
                probe_duration_ms=duration_ms,
            )

        client_info = result.get("clientInfo") or result.get("serverInfo") or {}
        client_name = str(client_info.get("name", "unknown"))
        client_version = str(client_info.get("version", "unknown"))
        protocol_version = str(result.get("protocolVersion", "unknown"))
        raw_caps = result.get("capabilities", {})
        caps = normalize_capabilities(raw_caps)

        return ClientCapabilityReport(
            schema_version="1.0",
            client_name=client_name,
            client_version=client_version,
            protocol_version=protocol_version,
            transports=[transport],
            capabilities=caps,
            status="ok",
            probed_at_utc=now_utc,
            probe_duration_ms=duration_ms,
        )

    elif transport in ("http", "sse"):
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "quorch-probe",
                    "version": "1.0.0",
                },
            },
        }
        payload = json.dumps(init_req).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "quorch-probe/1.0",
        }
        if transport == "sse":
            headers["Accept"] = "text/event-stream, application/json"

        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")

        status: Literal['ok', 'timeout', 'unavailable', 'error'] = "error"
        result: dict[str, Any] = {}

        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                body = response.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
                    status = "ok"
                    result = data["result"]
                else:
                    status = "error"
        except (socket.timeout, TimeoutError):
            status = "timeout"
        except urllib.error.HTTPError as e:
            if e.code in (404, 502, 503, 504):
                status = "unavailable"
            else:
                status = "error"
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                status = "timeout"
            elif isinstance(reason, (ConnectionRefusedError, ConnectionResetError, socket.gaierror)):
                status = "unavailable"
            else:
                status = "unavailable"
        except (ConnectionError, OSError):
            status = "unavailable"
        except json.JSONDecodeError:
            status = "error"
        except Exception:
            status = "error"

        duration_ms = int((time.monotonic() - start_time) * 1000)
        if status != "ok":
            return ClientCapabilityReport(
                schema_version="1.0",
                client_name="unknown",
                client_version="unknown",
                protocol_version="unknown",
                transports=[transport],
                capabilities={},
                status=status,
                probed_at_utc=now_utc,
                probe_duration_ms=duration_ms,
            )

        client_info = result.get("clientInfo") or result.get("serverInfo") or {}
        client_name = str(client_info.get("name", "unknown"))
        client_version = str(client_info.get("version", "unknown"))
        protocol_version = str(result.get("protocolVersion", "unknown"))
        raw_caps = result.get("capabilities", {})
        caps = normalize_capabilities(raw_caps)

        return ClientCapabilityReport(
            schema_version="1.0",
            client_name=client_name,
            client_version=client_version,
            protocol_version=protocol_version,
            transports=[transport],
            capabilities=caps,
            status="ok",
            probed_at_utc=now_utc,
            probe_duration_ms=duration_ms,
        )

    # Fallback
    return ClientCapabilityReport(
        schema_version="1.0",
        client_name="unknown",
        client_version="unknown",
        protocol_version="unknown",
        transports=[transport],
        capabilities={},
        status="error",
        probed_at_utc=now_utc,
        probe_duration_ms=int((time.monotonic() - start_time) * 1000),
    )


def diff_against_baseline(
    report: ClientCapabilityReport,
    baseline: Dict[str, Any],
) -> Dict[str, Any]:
    """Diff probed client capabilities against baseline."""
    if "capabilities" in baseline and isinstance(baseline["capabilities"], dict):
        base_caps = baseline["capabilities"]
    else:
        base_caps = baseline

    rep_caps = report.get("capabilities", {})

    added = sorted([k for k in rep_caps if k not in base_caps])
    missing = sorted([k for k in base_caps if k not in rep_caps])
    changed = sorted([k for k in base_caps if k in rep_caps and base_caps[k] != rep_caps[k]])

    is_ok = report.get("status") == "ok"
    missing_required = any(bool(base_caps.get(k)) for k in missing)
    degraded_changed = any(bool(base_caps.get(k)) and not bool(rep_caps.get(k)) for k in changed)
    compatible = is_ok and not missing_required and not degraded_changed

    return {
        "added": added,
        "missing": missing,
        "changed": changed,
        "compatible": compatible,
    }


def emit_baseline(report: ClientCapabilityReport, path: str) -> None:
    """Atomically write baseline to path via tempfile + os.replace."""
    target_path = os.path.abspath(path)
    target_dir = os.path.dirname(target_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    temp_fd, temp_path = tempfile.mkstemp(
        dir=target_dir or ".",
        prefix=".tmp_baseline_",
        suffix=".json",
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


def load_baseline(path: str) -> Dict[str, Any]:
    """Load baseline JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe MCP client capabilities and establish compatibility baselines.")
    parser.add_argument("--transport", choices=["stdio", "sse", "http"], default="stdio", help="Transport mode")
    parser.add_argument("--endpoint", type=str, default=None, help="Target command (stdio) or URL (http/sse)")
    parser.add_argument("--timeout-ms", type=int, default=5000, help="Probe timeout in milliseconds")
    parser.add_argument("--baseline", type=str, default=None, help="Path to baseline file to diff against")
    parser.add_argument("--emit-baseline", type=str, default=None, help="Save probed report to path as baseline")

    args = parser.parse_args()

    report = probe_client_capabilities(
        transport=args.transport,
        endpoint=args.endpoint,
        timeout_ms=args.timeout_ms,
    )

    diff_result = None
    if args.baseline and os.path.exists(args.baseline):
        baseline_data = load_baseline(args.baseline)
        diff_result = diff_against_baseline(report, baseline_data)

    if args.emit_baseline:
        emit_baseline(report, args.emit_baseline)

    output: dict[str, Any] = {"report": report}
    if diff_result is not None:
        output["diff"] = diff_result

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
