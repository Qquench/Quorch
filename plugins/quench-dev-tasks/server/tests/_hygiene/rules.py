# -*- coding: utf-8 -*-
"""Authoritative Single Source of Truth (SSOT) rule definitions for architecture hygiene."""

from typing import Final

RULE_IDS: Final[tuple[str, ...]] = (
    "lease_symbol_removal",
    "touch_outcome_truthiness",
    "vendor_literal_in_core",
    "api_bypass",
)

SCAN_ROOTS: Final[dict[str, tuple[str, ...]]] = {
    "lease_symbol_removal": (
        "server/workspace_lease.py",
        "server/reviewer_jobs.py",
    ),
    "touch_outcome_truthiness": (
        "server",
    ),
    "vendor_literal_in_core": (
        "server",
    ),
    "api_bypass": (
        "server",
    ),
}

RULE_SCOPE: Final[dict[str, tuple[str, ...]]] = {
    "lease_symbol_removal": (
        "_probe_posix",
        "_probe_windows",
        "_verify_disk_nonce_match",
        "heartbeat_healthy",
        "LeaseHeartbeatThread",
        "PeerLiveness",
        "probe_peer",
        "start_heartbeat_thread",
        "stop_heartbeat_thread",
    ),
    "touch_outcome_truthiness": (
        "touch",
    ),
    "vendor_literal_in_core": (
        "api.anthropic.com",
        "api.deepseek.com",
        "api.openai.com",
        "claude",
        "deepseek",
        "gemini",
        "generativelanguage.googleapis.com",
        "gpt-3",
        "gpt-4",
        "llama",
        "mistral",
        "o1-",
        "qwen",
    ),
    "api_bypass": (
        "ANTHROPIC_API_KEY",
        "anthropic",
        "api.anthropic.com",
        "api.deepseek.com",
        "api.openai.com",
        "cohere",
        "DeepSeekClient",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_KEY_QUENCH",
        "GEMINI_API_KEY",
        "generativelanguage.googleapis.com",
        "google.genai",
        "google.generativeai",
        "mistralai",
        "openai",
        "OPENAI_API_KEY",
    ),
}

# [R4-R-1] 修正：三元组集合，与 merged/baseline 同维 (rule_id, rel_posix_path, symbol_or_token)
MERGED_EXPANSION_ALLOWLIST: Final[frozenset[tuple[str, str, str]]] = frozenset()
