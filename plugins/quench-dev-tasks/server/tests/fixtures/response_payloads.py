"""response_payloads.py - Shared Canonical Response Payload Fixtures (Task 33.1).

Provides:
- TYPICAL_PAYLOADS: Canonical response payloads for all 16 MCP tools conforming to EXPECTED_TOOL_NAMES.
- OVERLOAD_STATUS_PAYLOAD: 40-task overloaded dev_tasks_status payload for boundary clamp testing.
- CANONICAL_HOOK_LOG_FIXTURES: Canonical log string fixtures covering all members of HOOK_LOG_CODES.

All payloads MUST use native JSON primitive types (dict, list, str, int, float, bool, None).
No datetime, Path, or Decimal instances are permitted (INV-10 D-05 purity contract).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Final, Mapping

from tool_surface_constants import (
    EXPECTED_TOOL_NAMES,
    MAX_NONTERMINAL_SNAPSHOT_BYTES,
    RESPONSE_BUDGET_BYTES,
)

CANONICAL_HOOK_LOG_FIXTURES: Final[Mapping[str, str]] = MappingProxyType({
    "ASK_MODAL_BLOCKED": (
        "2026-11-11 15:48:20 [WARN] [ASK_MODAL] decision=ask tool=write_file target=foo.py "
        "session=sess1 reason=User confirmation prompt required before mutating governed path"
    ),
    "SCOPE_VIOLATION": (
        "2026-11-11 15:48:21 [WARN] [BLOCK] decision=deny tool=edit_file target=server/other.py "
        "session=sess1 reason=Scope violation: target path is outside active task whitelist"
    ),
    "BYPASS_ACTIVE": (
        "2026-11-11 15:48:22 [INFO] [BYPASS_CLEAN] decision=clean tool=run_command target=.agents/bypass.json "
        "session=sess1 reason=Session bypass active for authenticated operator session"
    ),
    "TASK_STATUS_TAMPER": (
        "2026-11-11 15:48:23 [WARN] [BLOCK] decision=deny tool=run_command target=docs/dev_tasks/plan.md "
        "session=sess1 reason=【Shell 任务单篡写重定向拦截】Task status tamper detected via shell stdout redirect"
    ),
    "PATH_OUT_OF_SCOPE": (
        "2026-11-11 15:48:24 [WARN] [BLOCK] decision=deny tool=delete_file target=../../external.txt "
        "session=sess1 reason=Path out of scope: Target path escapes workspace confinement boundary"
    ),
    "OTHER": (
        "2026-11-11 15:48:25 [INFO] [ALLOW] decision=allow tool=run_command target= "
        "session=sess1 reason=Shell 只读或非任务单操作放行"
    ),
})

UNKNOWN_HOOK_LOG_SAMPLE: Final[str] = "2026-11-11 15:48:26 [ERROR] unparsable raw stack trace line without structure"

# Typical payloads for each of the 16 MCP tools
_TYPICAL: dict[str, dict[str, Any]] = {
    "dev_tasks_status": {
        "ok": True,
        "project_name": "quench-dev-orchestrator",
        "dev_tasks_dir": "docs/dev_tasks",
        "entitlements_hash": "e1f2a3b4c5d67890",
        "harness_next_action": {
            "action": "CHECKOUT",
            "task_file": "docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md",
            "task_id": "33.1",
        },
        "tasks_total": 2,
        "tasks": [
            {
                "id": "33.1",
                "title": "Runtime Budget Clamp & Pipeline",
                "status": "🔨 执行中",
            },
            {
                "id": "33.2",
                "title": "Status v2 Slimming",
                "status": "✅ 已确认",
            },
        ],
        "last_hook_log_entries_compact": [
            "2026-11-11 15:48:25 [ALLOW] OTHER",
        ],
    },
    "dev_tasks_checkout": {
        "task_file": "docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md",
        "task_id": "33.1",
        "status": "🔨 执行中",
        "holder_token": "token_1794373837462_5456",
        "generation": 1,
        "harness_next_action": {
            "action": "CHECKOUT",
            "task_id": "33.1",
        },
    },
    "dev_tasks_refine_spec": {
        "task_id": "33.1",
        "path": "docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md",
        "content_sha256": "4a5b6c7d8e9f0123456789abcdef0123456789abcdef0123456789abcdef0123",
        "status": "refined",
    },
    "dev_tasks_promote_draft": {
        "task_file": "docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md",
        "task_id": "33.1",
        "old_status": "📝 草案",
        "new_status": "⬜ 待确认",
        "feasibility_passed": True,
    },
    "dev_tasks_escalate": {
        "task_file": "docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md",
        "task_id": "33.1",
        "escalated": True,
        "escalation_channel": "external_api",
        "reason": "Complex architectural trade-off requiring Reviewer guidance",
    },
    "dev_reviewer_submit": {
        "status": "ok",
        "job": {
            "job_id": "job_1794372638_294782da",
            "session_id": "becc5f1380c5",
            "state": "QUEUED",
        },
    },
    "dev_reviewer_poll": {
        "job_id": "job_1794372638_294782da",
        "session_id": "becc5f1380c5",
        "state": "RUNNING",
        "retry_after_seconds": 3,
        "elapsed_s": 8,
    },
    "dev_reviewer_cancel": {
        "status": "cancelled",
        "job_id": "job_1794372638_294782da",
        "session_id": "becc5f1380c5",
        "tokens_billed_after_cancel": 0,
    },
    "dev_tasks_propose": {
        "file": "docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md",
        "proposed": ["33.0", "33.1", "33.2", "33.3"],
        "count": 4,
    },
    "dev_tasks_confirm": {
        "file": "docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md",
        "action": "confirm",
        "updated": [
            {"id": "33.1", "new_status": "✅ 已确认"},
            {"id": "33.2", "new_status": "✅ 已确认"},
        ],
        "errors": [],
    },
    "dev_tasks_complete": {
        "task_file": "docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md",
        "task_id": "33.1",
        "status": "✔️ 已完成",
        "dod_output": "All 4 DoD checks passed without errors",
    },
    "dev_tasks_heartbeat": {
        "task_id": "33.1",
        "generation": 1,
        "alive": True,
        "heartbeat_at": "2026-11-11T16:10:00Z",
    },
    "dev_tasks_reclaim": {
        "task_id": "33.1",
        "reclaimed": True,
        "previous_status": "🔨 执行中",
        "new_status": "✅ 已确认",
        "new_generation": 2,
    },
    "dev_tasks_archive": {
        "archived": True,
        "task_file": "docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md",
        "archive_path": "docs/dev_tasks/archive/2026-11-11_v1_33_mcp_response_slimming.md",
    },
    "dev_tasks_set_bypass": {
        "action": "enable",
        "session_id": "becc5f1380c5",
        "active": True,
        "expires_at": "2026-11-11T18:00:00Z",
    },
    "dev_tasks_export_handoff_card": {
        "task_id": "33.1",
        "card": (
            "# Handoff Card - Task 33.1\n\n"
            "- Scope: Response compactor & pipeline\n"
            "- Status: Complete and verified\n"
        ),
    },
}

TYPICAL_PAYLOADS: Final[Mapping[str, dict[str, Any]]] = MappingProxyType(_TYPICAL)

# Construct a 40-task overloaded status payload
_overload_tasks: list[dict[str, Any]] = [
    {
        "id": f"task_{idx}.1",
        "title": f"Overloaded stress test benchmark task {idx} for runtime boundary clamp verification",
        "status": "⬜ 待确认",
        "affected_files": [f"plugins/quench-dev-tasks/server/module_{idx}.py"],
    }
    for idx in range(1, 41)
]

OVERLOAD_STATUS_PAYLOAD: Final[dict[str, Any]] = {
    "ok": True,
    "project_name": "quench-dev-orchestrator",
    "dev_tasks_dir": "docs/dev_tasks",
    "entitlements_hash": "0123456789abcdef",
    "harness_next_action": {
        "action": "REVIEW",
        "reason": "Overload test batch pending reviewer evaluation across multiple tasks",
        "task_file": "docs/dev_tasks/overload_stress_test.md",
        "task_id": "task_1.1",
    },
    "files": [
        {"name": f"task_batch_{idx}.md", "total_tasks": 10}
        for idx in range(1, 15)
    ],
    "tasks": _overload_tasks,
    "last_hook_log_entries_compact": [
        f"2026-11-11 15:48:{idx:02d} [ALLOW] OTHER"
        for idx in range(10)
    ],
}
