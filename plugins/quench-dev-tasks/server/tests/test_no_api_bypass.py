# -*- coding: utf-8 -*-
"""Comprehensive tests for Reviewer API egress unification and AST bypass blocker.

Verifies:
1. Invariant: reviewer_engine.py is the sole authorized network egress for Reviewer providers.
2. AST Scanner detects all unauthorized provider SDK imports, endpoint literals, API key reads, and raw client imports.
3. AST Scanner passes clean compliant files with 0 violations.
4. CLI escape hatch `quorch reviewer debug` operates in governed dry-run mode.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure server and scripts directories are in sys.path
SERVER_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SERVER_DIR.parent / "scripts"
WORKSPACE_ROOT = SERVER_DIR.parent.parent.parent

sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import reviewer_engine
from check_no_api_bypass import (
    scan_file_for_bypass,
    scan_workspace_for_bypass,
    main as scanner_main,
)


def test_is_sole_provider_egress_flag():
    """reviewer_engine must explicitly declare IS_SOLE_PROVIDER_EGRESS as True."""
    assert hasattr(reviewer_engine, "IS_SOLE_PROVIDER_EGRESS"), (
        "reviewer_engine.py must define IS_SOLE_PROVIDER_EGRESS"
    )
    assert reviewer_engine.IS_SOLE_PROVIDER_EGRESS is True, (
        "IS_SOLE_PROVIDER_EGRESS must be True"
    )


def test_ast_scanner_clean_file(tmp_path: Path):
    """AST scanner must report 0 violations on clean compliant Python code."""
    clean_code = '''
# Governed script
import json
import os
from project_config import load_project_config

def do_work():
    cfg = load_project_config(".")
    return {"status": "ok"}
'''
    clean_file = tmp_path / "governed_module.py"
    clean_file.write_text(clean_code, encoding="utf-8")

    violations = scan_file_for_bypass(str(clean_file))
    assert violations == [], f"Expected 0 violations for clean code, got: {violations}"


def test_ast_scanner_catches_forbidden_sdk_import(tmp_path: Path):
    """AST scanner must catch unauthorized direct imports of provider SDKs."""
    bad_code_1 = "import openai\nclient = openai.OpenAI()\n"
    file_1 = tmp_path / "bad_openai.py"
    file_1.write_text(bad_code_1, encoding="utf-8")

    violations_1 = scan_file_for_bypass(str(file_1))
    assert any(v.rule == "FORBIDDEN_PROVIDER_IMPORT" for v in violations_1), (
        "Expected FORBIDDEN_PROVIDER_IMPORT for 'import openai'"
    )

    bad_code_2 = "from anthropic import Anthropic\nclient = Anthropic()\n"
    file_2 = tmp_path / "bad_anthropic.py"
    file_2.write_text(bad_code_2, encoding="utf-8")

    violations_2 = scan_file_for_bypass(str(file_2))
    assert any(v.rule == "FORBIDDEN_PROVIDER_IMPORT" for v in violations_2), (
        "Expected FORBIDDEN_PROVIDER_IMPORT for 'from anthropic import Anthropic'"
    )


def test_ast_scanner_catches_hardcoded_endpoint_literals(tmp_path: Path):
    """AST scanner must catch hardcoded provider endpoint string literals."""
    bad_code = '''
def send_request():
    url = "https://api.deepseek.com/chat/completions"
    return url
'''
    file_p = tmp_path / "bad_endpoint.py"
    file_p.write_text(bad_code, encoding="utf-8")

    violations = scan_file_for_bypass(str(file_p))
    assert any(v.rule == "FORBIDDEN_ENDPOINT_LITERAL" for v in violations), (
        "Expected FORBIDDEN_ENDPOINT_LITERAL for 'api.deepseek.com'"
    )


def test_ast_scanner_catches_direct_env_key_reads(tmp_path: Path):
    """AST scanner must catch direct reads of provider API key environment variables."""
    bad_code_call = '''
import os
def get_key():
    return os.environ.get("DEEPSEEK_API_KEY")
'''
    file_call = tmp_path / "bad_env_call.py"
    file_call.write_text(bad_code_call, encoding="utf-8")

    violations_call = scan_file_for_bypass(str(file_call))
    assert any(v.rule == "FORBIDDEN_ENV_KEY_READ" for v in violations_call), (
        "Expected FORBIDDEN_ENV_KEY_READ for os.environ.get('DEEPSEEK_API_KEY')"
    )

    bad_code_subscript = '''
import os
def get_key():
    return os.environ["OPENAI_API_KEY"]
'''
    file_sub = tmp_path / "bad_env_subscript.py"
    file_sub.write_text(bad_code_subscript, encoding="utf-8")

    violations_sub = scan_file_for_bypass(str(file_sub))
    assert any(v.rule == "FORBIDDEN_ENV_KEY_READ" for v in violations_sub), (
        "Expected FORBIDDEN_ENV_KEY_READ for os.environ['OPENAI_API_KEY']"
    )


def test_ast_scanner_catches_direct_client_import(tmp_path: Path):
    """AST scanner must catch direct import of DeepSeekClient outside authorized files."""
    bad_code = '''
from reviewer_engine import DeepSeekClient
def bypass():
    c = DeepSeekClient()
    return c
'''
    file_p = tmp_path / "bad_client_import.py"
    file_p.write_text(bad_code, encoding="utf-8")

    violations = scan_file_for_bypass(str(file_p))
    assert any(v.rule == "FORBIDDEN_PROVIDER_CLIENT_IMPORT" for v in violations), (
        "Expected FORBIDDEN_PROVIDER_CLIENT_IMPORT for DeepSeekClient"
    )


def test_cli_scanner_exit_codes(tmp_path: Path):
    """CLI scanner runner must exit 0 on clean file and 1 on violating file."""
    clean_file = tmp_path / "clean_sample.py"
    clean_file.write_text("x = 42\n", encoding="utf-8")

    bad_file = tmp_path / "bad_sample.py"
    bad_file.write_text("import openai\n", encoding="utf-8")

    # Clean file -> exit 0
    exit_clean = scanner_main(["--files", str(clean_file)])
    assert exit_clean == 0, f"Expected 0 exit code for clean file, got {exit_clean}"

    # Bad file -> exit 1
    exit_bad = scanner_main(["--files", str(bad_file)])
    assert exit_bad == 1, f"Expected 1 exit code for bad file, got {exit_bad}"

    # Bad file with --expect-exit 1 -> exit 0 (assertion passed)
    exit_assert_pass = scanner_main(["--files", str(bad_file), "--expect-exit", "1"])
    assert exit_assert_pass == 0


def test_quorch_reviewer_debug_dry_run_cli():
    """`quorch reviewer debug` should parse config and output dry-run success."""
    cmd = [
        sys.executable,
        str(SERVER_DIR / "cli.py"),
        "reviewer",
        "debug",
        "--workspace",
        str(WORKSPACE_ROOT),
        "--json",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, f"Command failed: {proc.stderr}"
    assert "dry_run_success" in proc.stdout, f"Unexpected stdout: {proc.stdout}"
