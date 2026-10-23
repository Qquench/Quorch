# -*- coding: utf-8 -*-
"""Authoritative Single Source of Truth (SSOT) rule definitions for architecture hygiene."""

from typing import Final, Mapping

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

EXPANSION_ELIGIBLE_RULES: Final[frozenset[str]] = frozenset({
    "touch_outcome_truthiness",
    "vendor_literal_in_core",
    "api_bypass",
})

# 精确授权面：导入期与实测 exp_files 严格双向相等。
# 将授权下沉至 (rule, file) 粒度是为杜绝手工伪造 120 行三元组的既定安全设计。
MERGED_FILE_SCOPE_ALLOWLIST: Final[frozenset[tuple[str, str]]] = frozenset({
    ('api_bypass', 'server/autopilot_harness.py'),
    ('api_bypass', 'server/ide_schema_export.py'),
    ('api_bypass', 'server/progress_bridge.py'),
    ('api_bypass', 'server/runtime_mode.py'),
    ('api_bypass', 'server/task_status.py'),
    ('api_bypass', 'server/task_writer.py'),
    ('api_bypass', 'server/tool_surface_constants.py'),
    ('touch_outcome_truthiness', 'server/autopilot_harness.py'),
    ('touch_outcome_truthiness', 'server/ide_schema_export.py'),
    ('touch_outcome_truthiness', 'server/progress_bridge.py'),
    ('touch_outcome_truthiness', 'server/runtime_mode.py'),
    ('touch_outcome_truthiness', 'server/task_status.py'),
    ('touch_outcome_truthiness', 'server/task_writer.py'),
    ('touch_outcome_truthiness', 'server/tool_surface_constants.py'),
    ('vendor_literal_in_core', 'server/autopilot_harness.py'),
    ('vendor_literal_in_core', 'server/ide_schema_export.py'),
    ('vendor_literal_in_core', 'server/progress_bridge.py'),
    ('vendor_literal_in_core', 'server/runtime_mode.py'),
    ('vendor_literal_in_core', 'server/task_status.py'),
    ('vendor_literal_in_core', 'server/task_writer.py'),
    ('vendor_literal_in_core', 'server/tool_surface_constants.py'),
})


def derive_expansion_allowlist(
    file_scope: frozenset[tuple[str, str]],
    eligible: frozenset[str],
    scope: Mapping[str, tuple[str, ...]],
) -> frozenset[tuple[str, str, str]]:
    """纯函数：文件级授权面 × RULE_SCOPE 派生 token 三元组。

    校验（顺序固定，均抛 ValueError，message 含可 match 子串）：
      - file_scope 为空        -> "empty file_scope"
      - rule 不在 eligible     -> "ineligible rule: <rule>"
      - rule 不在 scope        -> "out_of_scope rule: <rule>"
      - path 不属 scope[rule]  -> "out_of_scope path: <rule>:<path>"
    """
    if not file_scope:
        raise ValueError("empty file_scope")

    for rule_id, path in file_scope:
        if rule_id not in eligible:
            raise ValueError(f"ineligible rule: {rule_id}")
        if rule_id not in scope:
            raise ValueError(f"out_of_scope rule: {rule_id}")
        spec = SCAN_ROOTS.get(rule_id, ())
        if spec == ("server",):
            applies = path.startswith("server/") and "/" not in path[len("server/"):]
        else:
            applies = path in spec
        if not applies:
            raise ValueError(f"out_of_scope path: {rule_id}:{path}")

    return frozenset(
        (rule_id, path, token)
        for (rule_id, path) in file_scope
        for token in scope[rule_id]
    )


# [R4-R-1] 修正：三元组集合，与 merged/baseline 同维 (rule_id, rel_posix_path, symbol_or_token)
MERGED_EXPANSION_ALLOWLIST: Final[frozenset[tuple[str, str, str]]] = derive_expansion_allowlist(
    MERGED_FILE_SCOPE_ALLOWLIST, EXPANSION_ELIGIBLE_RULES, RULE_SCOPE
)
