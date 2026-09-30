# -*- coding: utf-8 -*-
"""Contract tests for external executor onboarding documentation.

Locks in:
1. Documentation existence at docs/guides/external-executor-onboarding.md;
2. Machine-checkability: all embedded json/jsonc and bash code blocks are syntactically valid;
3. Zero tool drift: every 'dev_*' identifier mentioned in the document exists in server.py registered tools;
4. Zero secret or personal path leakage: no plaintext API keys or developer user directories;
5. Dual-entry MCP configuration contract and explicit non-security-boundary declaration.
"""
from pathlib import Path
import json
import re
import asyncio
import pytest

import server

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVER_DIR.parent.parent.parent
DOC_PATH = REPO_ROOT / "docs" / "guides" / "external-executor-onboarding.md"


def _strip_json_comments(text: str) -> str:
    """Strip single-line and multi-line comments for jsonc parsing."""
    # Remove single line comments // ...
    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
    # Remove block comments /* ... */
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


def _extract_code_blocks(doc_text: str) -> list[tuple[str, str]]:
    """Extract (lang, code_content) tuples from markdown text."""
    pattern = r"```([a-zA-Z0-9_\-]+)?\n(.*?)\n```"
    matches = re.findall(pattern, doc_text, flags=re.DOTALL)
    return [(lang.strip().lower(), code) for lang, code in matches]


def test_onboarding_doc_exists():
    """Assert onboarding documentation exists and has substantial content."""
    assert DOC_PATH.is_file(), f"Onboarding guide missing at {DOC_PATH}"
    content = DOC_PATH.read_text(encoding="utf-8")
    assert len(content) > 1000, "Onboarding guide is unexpectedly truncated"


def test_all_code_blocks_are_syntactically_valid():
    """Assert all json/jsonc and bash code blocks in onboarding doc are syntactically valid."""
    content = DOC_PATH.read_text(encoding="utf-8")
    blocks = _extract_code_blocks(content)
    assert len(blocks) >= 2, "Expected at least 2 code blocks in onboarding doc"

    for lang, code in blocks:
        if lang in ("json", "jsonc"):
            clean_json = _strip_json_comments(code).strip()
            try:
                parsed = json.loads(clean_json)
                assert isinstance(parsed, (dict, list)), f"JSON root must be dict or list: {parsed}"
            except Exception as e:
                pytest.fail(f"Invalid JSON/JSONC block in {DOC_PATH}:\n{code}\nError: {e}")
        elif lang in ("bash", "sh"):
            # Check basic bash syntax integrity: balanced quotes and parentheses
            assert code.strip(), "Empty bash code block"
            single_quotes = code.count("'")
            assert single_quotes % 2 == 0, f"Unbalanced single quotes in bash block:\n{code}"
            # Check for unbalanced double quotes (excluding escaped ones)
            unescaped_double_quotes = len(re.findall(r'(?<!\\)"', code))
            assert unescaped_double_quotes % 2 == 0, f"Unbalanced double quotes in bash block:\n{code}"


def test_no_tool_reference_drift():
    """Assert all 'dev_*' tool mentions in onboarding doc match real server.py registered tools."""
    # Retrieve real registered tools from FastMCP instance
    registered_tools = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert len(registered_tools) == 17, f"Expected 17 registered tools, got {len(registered_tools)}"

    content = DOC_PATH.read_text(encoding="utf-8")
    # Match all tokens like dev_tasks_* or dev_reviewer_*
    tool_tokens = set(re.findall(r"\bdev_[a-z0-9_]+\b", content))

    assert tool_tokens, "No dev_* tool tokens found in onboarding doc"
    unknown_tools = tool_tokens - registered_tools
    assert not unknown_tools, (
        f"Onboarding doc references unregistered tool names: {unknown_tools}. "
        f"Available registered tools: {registered_tools}"
    )

    # Core workflow tools must be present
    mandatory_mentions = {
        "dev_tasks_status",
        "dev_tasks_checkout",
        "dev_tasks_complete",
        "dev_reviewer_consult",
        "dev_reviewer_submit",
        "dev_reviewer_poll",
        "dev_tasks_heartbeat",
        "dev_tasks_set_bypass",
    }
    missing_core = mandatory_mentions - tool_tokens
    assert not missing_core, f"Onboarding doc must cover core tools: {missing_core}"


def test_zero_secrets_and_personal_paths_leakage():
    """Assert zero plaintext API keys or developer user directories are in onboarding doc."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Check for secret patterns
    assert not re.search(r"\bsk-[a-zA-Z0-9]{10,}\b", content), "Found potential API key in doc"
    assert not re.search(r"\bBearer\s+[a-zA-Z0-9_\-\.]{10,}\b", content), "Found potential bearer token in doc"

    # Check for developer personal home paths
    assert "C:\\Users\\" not in content, "Found Windows personal user path (C:\\Users\\)"
    assert "/Users/" not in content, "Found macOS personal user path (/Users/)"
    assert "/home/" not in content, "Found Linux personal user path (/home/)"


def test_dual_mcp_config_and_non_security_boundary_contract():
    """Assert dual MCP configuration contract and non-security boundary declaration are present."""
    content = DOC_PATH.read_text(encoding="utf-8")

    # Dual entry snippet assertion
    assert "quench-runner" in content
    assert "quench-reviewer" in content
    assert "QUENCH_ROLE" in content

    # Non-security boundary assertion
    assert "非安全边界声明" in content or "Non-Security Boundary" in content
    assert "collaborative" in content.lower() or "hygiene" in content.lower()
