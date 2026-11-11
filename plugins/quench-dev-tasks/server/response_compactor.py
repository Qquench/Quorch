"""response_compactor.py - Pure-Function Response Clamping & Compaction Pipeline.

Implements:
- 3-tier empty value compaction (compact_mapping)
- Canonical sorted compact JSON serialization (canonical_json)
- Deterministic response clamping to leaf SSOT budgets (fit_to_budget)
- Closed-vocabulary hook log entry classification (classify_hook_log_entry)
- Response budget test-time assertion (assert_response_budget)
- Static configuration short-hash ETag generation (compute_entitlements_hash)

Invariants:
- INV-3: Zero model-generated summarization. Clamping is purely rule-based and deterministic.
- INV-9: Zero provider network egress or LLM invocation.
- INV-10: Response payload clamping adheres strictly to RESPONSE_BUDGET_BYTES SSOT.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from tool_surface_constants import (
    HOOK_LOG_CODES,
    HOOK_LOG_TAIL_BYTES,
    MAX_NONTERMINAL_SNAPSHOT_BYTES,
    RESPONSE_BUDGET_BYTES,
    STATUS_COMPACT_MAX_HOOK_ENTRIES,
    STATUS_COMPACT_MAX_TASKS,
    measure_payload_bytes,
)

STATUS_COMPACT_DROP_ORDER: Final[tuple[str, ...]] = (
    "last_hook_log_entries_compact",
    "files",
    "tasks",
)

STATUS_COMPACT_ALWAYS_KEEP: Final[tuple[str, ...]] = (
    "ok",
    "harness_next_action",
    "entitlements_hash",
)

# Closed-vocabulary code references derived from leaf SSOT HOOK_LOG_CODES
_CODE_OTHER: Final[str] = next(c for c in HOOK_LOG_CODES if c == "OTHER")
_CODE_ASK_MODAL_BLOCKED: Final[str] = next(c for c in HOOK_LOG_CODES if c.startswith("ASK_MODAL"))
_CODE_SCOPE_VIOLATION: Final[str] = next(c for c in HOOK_LOG_CODES if c == "SCOPE_VIOLATION")
_CODE_BYPASS_ACTIVE: Final[str] = next(c for c in HOOK_LOG_CODES if c.startswith("BYPASS"))
_CODE_TASK_STATUS_TAMPER: Final[str] = next(c for c in HOOK_LOG_CODES if "TAMPER" in c)
_CODE_PATH_OUT_OF_SCOPE: Final[str] = next(c for c in HOOK_LOG_CODES if c.startswith("PATH"))


class ResponseBudgetExceeded(AssertionError):
    """Raised when an MCP tool response payload exceeds its declared response budget."""


def canonical_json(data: Any) -> str:
    """Canonical sorted JSON serialization with compact separators and UTF-8 characters."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_entitlements_hash(canonical_cfg: Any) -> str:
    """Compute 16-hex short SHA256 ETag hash for static entitlement configuration."""
    canonical_bytes = canonical_json(canonical_cfg).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()[:16]


def compact_mapping(
    data: Mapping[str, Any] | None,
    *,
    always_keep: Iterable[str] = (),
    drop_if_empty: Iterable[str] = (),
) -> dict[str, Any]:
    """Single-layer ordered dictionary compaction with 3-tier empty value semantics.

    Semantics:
      1. None is dropped by default unless key is present in always_keep.
      2. "", [], {} are dropped ONLY if key is present in drop_if_empty (never drops int 0 or bool False).
      3. Preserves original insertion order without mutating the input mapping.
    """
    if not isinstance(data, Mapping):
        return {}

    keep_set = frozenset(always_keep)
    drop_empty_set = frozenset(drop_if_empty)

    result: dict[str, Any] = {}
    for k, v in data.items():
        if k in keep_set:
            result[k] = v
            continue
        if v is None:
            continue
        if k in drop_empty_set:
            if isinstance(v, (str, list, dict, set, tuple)) and len(v) == 0:
                continue
        result[k] = v
    return result


def classify_hook_log_entry(raw_line: str) -> str:
    """Classify a raw hook log line into a member of HOOK_LOG_CODES."""
    if not raw_line or not isinstance(raw_line, str):
        return _CODE_OTHER

    line_upper = raw_line.upper()
    code: str = _CODE_OTHER

    # 1. Direct match against known codes
    for cand in sorted(HOOK_LOG_CODES):
        if cand != _CODE_OTHER and cand in line_upper:
            code = cand
            break
    else:
        # 2. Pattern-based rule classifications
        if "ASK_MODAL" in line_upper:
            code = _CODE_ASK_MODAL_BLOCKED
        elif "TAMPER" in line_upper or "篡写" in raw_line:
            code = _CODE_TASK_STATUS_TAMPER
        elif "BYPASS" in line_upper:
            code = _CODE_BYPASS_ACTIVE
        elif (
            "PATH_OUT_OF_SCOPE" in line_upper
            or "PATH OUT OF SCOPE" in line_upper
            or "ESCAPES WORKSPACE" in line_upper
            or "CONFINEMENT" in line_upper
        ):
            code = _CODE_PATH_OUT_OF_SCOPE
        elif (
            "SCOPE_VIOLATION" in line_upper
            or "SCOPE VIOLATION" in line_upper
            or "WHITELIST" in line_upper
            or "OUTSIDE ACTIVE TASK" in line_upper
        ):
            code = _CODE_SCOPE_VIOLATION
        else:
            code = _CODE_OTHER

    return code if code in HOOK_LOG_CODES else _CODE_OTHER


def fit_to_budget(
    tool_name: str,
    payload: Any,
    *,
    drop_order: Sequence[str] | None = None,
    always_keep: Sequence[str] | None = None,
    phase: str = "default",
) -> dict[str, Any]:
    """Single-pass deterministic clamping to guarantee response payload budget.

    Clamping pipeline:
      Step 1: Cap list fields (tasks, compact hook logs) to their respective constants.
      Step 2: Drop keys according to drop_order until payload fits within budget.
      Step 3: If drop_order is exhausted and payload still exceeds budget:
              - Tier-2: Reduce harness_next_action to discriminator-only ({'action': ...}),
                and strip all remaining non-always_keep keys.
              - Tier-3: If still over budget, inject an over_budget_bytes observability marker.
              Never raises; always_keep keys are never stripped.
    """
    if not isinstance(payload, Mapping):
        return payload if isinstance(payload, dict) else {"payload": payload}

    budget = RESPONSE_BUDGET_BYTES.get(tool_name)
    if budget is None:
        return dict(payload)

    # dev_reviewer_poll in terminal phase is exempt from non-terminal 1024B budget
    if tool_name == "dev_reviewer_poll" and phase == "terminal":
        return dict(payload)

    result = dict(payload)
    effective_drop_order = list(drop_order) if drop_order is not None else (
        list(STATUS_COMPACT_DROP_ORDER) if tool_name == "dev_tasks_status" else []
    )
    effective_always_keep = set(always_keep) if always_keep is not None else (
        set(STATUS_COMPACT_ALWAYS_KEEP) if tool_name == "dev_tasks_status" else set()
    )

    truncated_sections: list[str] = []

    # Step 1: Cap list fields
    if tool_name == "dev_tasks_status":
        if "tasks" in result and isinstance(result["tasks"], list):
            if len(result["tasks"]) > STATUS_COMPACT_MAX_TASKS:
                if "tasks_total" not in result:
                    result["tasks_total"] = len(result["tasks"])
                result["tasks"] = result["tasks"][:STATUS_COMPACT_MAX_TASKS]
                truncated_sections.append("tasks")

        for hook_key in ("last_hook_log_entries_compact", "last_hook_log_entries"):
            if hook_key in result and isinstance(result[hook_key], list):
                if len(result[hook_key]) > STATUS_COMPACT_MAX_HOOK_ENTRIES:
                    result[hook_key] = result[hook_key][:STATUS_COMPACT_MAX_HOOK_ENTRIES]
                    truncated_sections.append(hook_key)

    if measure_payload_bytes(result) <= budget:
        if truncated_sections:
            cand = dict(result)
            cand["truncated_sections"] = list(dict.fromkeys(truncated_sections))
            if measure_payload_bytes(cand) <= budget:
                result = cand
        return result

    # Step 2: Drop keys according to drop_order
    for key in effective_drop_order:
        if key in effective_always_keep:
            continue
        if key in result:
            del result[key]
            truncated_sections.append(key)
            if measure_payload_bytes(result) <= budget:
                break

    if measure_payload_bytes(result) <= budget:
        if truncated_sections:
            cand = dict(result)
            cand["truncated_sections"] = list(dict.fromkeys(truncated_sections))
            if measure_payload_bytes(cand) <= budget:
                result = cand
        return result

    # Step 3: Tier-2 discriminator guarantee & Tier-3 observability marker
    # Tier-2: Minimize harness_next_action to action-only and drop any remaining non-always_keep keys
    if "harness_next_action" in result and isinstance(result["harness_next_action"], dict):
        action_val = result["harness_next_action"].get("action")
        result["harness_next_action"] = {"action": action_val} if action_val is not None else {}

    keys_to_drop = [k for k in result.keys() if k not in effective_always_keep]
    for k in keys_to_drop:
        del result[k]
        truncated_sections.append(k)

    current_bytes = measure_payload_bytes(result)
    if current_bytes > budget:
        # Tier-3: inject observability marker
        result["over_budget_bytes"] = current_bytes - budget
    elif truncated_sections:
        cand = dict(result)
        cand["truncated_sections"] = list(dict.fromkeys(truncated_sections))
        if measure_payload_bytes(cand) <= budget:
            result = cand

    return result


def assert_response_budget(
    tool_name: str,
    payload: Any,
    *,
    phase: str = "default",
) -> None:
    """Assert that payload does not exceed RESPONSE_BUDGET_BYTES for tool_name."""
    if tool_name not in RESPONSE_BUDGET_BYTES:
        return

    if tool_name == "dev_reviewer_poll" and phase == "terminal":
        return

    budget = RESPONSE_BUDGET_BYTES[tool_name]
    size = measure_payload_bytes(payload)
    if size > budget:
        raise ResponseBudgetExceeded(
            f"Payload for '{tool_name}' (phase='{phase}') byte size {size} exceeds declared budget {budget}"
        )
