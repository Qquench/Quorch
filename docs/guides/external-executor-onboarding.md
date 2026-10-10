# External Executor Onboarding Guide (外部执行器接入指南)

> This document defines the engineering standards and protocol invariants for integrating external AI executors (Claude Code, OpenAI Codex CLI, Antigravity, Cursor, Windsurf, and custom autonomous agents) into the **Quench DevTasks Governance Ecosystem (`quorch`)**.

---

## 1. Architecture Overview & Core Invariants

The Quench DevTasks architecture enforces strict engineering discipline on automated and human-assisted development workflows. All external executors participating in code generation, refactoring, or reviewing within a Quench-governed workspace are bound by five core architectural constraints:

1. **INV-1: Single-Core Serial Execution**: Globally, at most one task may be in the `🔨 In Progress` (`🔨 执行中`) status at any time, secured by cross-process file-locking.
2. **INV-2: MCP-Only State Machine**: Task states can only transition through authenticated Quench FastMCP tool invocations. Markdown task status headings must never be hand-edited or synthesized by agent file edits.
3. **INV-3: Anti-Roleplay Hard Stop**: Execution models (Runners) must never roleplay or simulate Reviewer models in-context. Degraded review outputs must maintain empty findings (`findings == ""`).
4. **INV-4: Stdio Channel Purity**: When running over standard input/output (`stdio`), `stdout` is strictly reserved for JSON-RPC protocol frames. Diagnostics, telemetry, and debugging notices must be directed exclusively to `stderr` or structured log files.
5. **INV-9: Single Provider Egress**: All architectural evaluations and reasoning must pass through the governed `ReviewerClient` adapter pipeline. Raw, unmonitored HTTP/API script calls bypassing the governance layer are intercepted.

---

## 2. Environment Preparation & Host Configuration

### 2.1 Python Runtime Setup

Quench FastMCP server requires Python 3.10+ in a dedicated virtual environment.

```bash
# Initialize and activate project virtual environment
python -m venv .venv

# On POSIX:
source .venv/bin/activate

# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1

# Install core dependencies
pip install -r plugins/quench-dev-tasks/server/requirements.txt
```

### 2.2 Dual MCP Configuration Contract (双条目配置契约)

To separate implementation and architectural review capabilities without leaky runtime roleplay, the client configuration MUST declare **two distinct MCP server entries**: `quench-runner` and `quench-reviewer`.

```jsonc
{
  "mcpServers": {
    "quench-runner": {
      "command": "python",
      "args": ["-m", "quench_dev_tasks.server"],
      "env": { "QUENCH_ROLE": "runner" }
    },
    "quench-reviewer": {
      "command": "python",
      "args": ["-m", "quench_dev_tasks.server"],
      "env": { "QUENCH_ROLE": "reviewer" }
    }
  }
}
```

> 🛡️ **Explicit Non-Security Boundary Declaration (非安全边界声明)**:  
> Role declarations (`QUENCH_ROLE: runner` / `QUENCH_ROLE: reviewer`) and verdict logs are **collaborative convenience and operational hygiene mechanisms**, NOT hardened cryptographic or operating system security boundaries.  
> The physical capability separation is achieved by declaring **two independent MCP entries** in the host configuration and running single-role execution sessions. Quench does not sandbox unconfined hostile subprocesses. Verdict audit logs provide structured replayability and accidental degradation detection rather than adversarial zero-trust proofs.

---

## 3. Stdio Purity & Communication Protocol

When spawned by an IDE or CLI harness as a stdio child process:

- **JSON-RPC Reserved on `stdout`**: Any spurious byte written to `stdout` corrupts the MCP wire protocol and causes host process termination.
- **Diagnostics on `stderr`**: All operational notices, tracebacks, and warnings are streamed to `stderr`.
- **Structured File Sinks**: Reviewer thinking traces and evaluation snapshots are written to bounded append-only files under `.agents/` rather than standard output.

---

## 4. The 17 FastMCP Tools Reference

The Quench DevTasks MCP server exposes exactly 17 specialized tools:

| # | Tool Name | Scope / Role Hint | Primary Function |
|---|-----------|-------------------|------------------|
| 1 | `dev_tasks_status` | Runner & Reviewer | Inspect queue distribution, active lease, and health metrics |
| 2 | `dev_tasks_checkout` | Runner | Checkout confirmed task to `🔨 In Progress` and acquire lease |
| 3 | `dev_tasks_complete` | Runner | Deliver completed task with 100% verified DoD output |
| 4 | `dev_tasks_confirm` | Reviewer & Human | Transition task state (`confirm`, `rework`, `skip`) |
| 5 | `dev_tasks_propose` | Reviewer & Runner | Propose new task draft into `⬜ 待确认` queue |
| 6 | `dev_tasks_heartbeat` | Runner | Refresh active lease during long-running execution |
| 7 | `dev_tasks_reclaim` | Runner & Reviewer | CAS-safe recovery of orphaned or timed-out leases |
| 8 | `dev_tasks_refine_spec` | Reviewer | Refine draft task specification using AST static analysis |
| 9 | `dev_tasks_promote_draft` | Reviewer | Validate physical feasibility and promote draft task |
| 10 | `dev_tasks_escalate` | Runner | Trigger Reviewer escalation handoff card |
| 11 | `dev_tasks_export_handoff_card` | Runner | Export Reviewer handoff card markdown without state mutation |
| 12 | `dev_tasks_set_bypass` | Runner & Human | Activate time-bounded bypass token for hotfixes/typos |
| 13 | `dev_tasks_archive` | Runner & Reviewer | Archive fully closed tasks to `archive/` and update changelog |
| 14 | `dev_reviewer_submit` | Reviewer & Runner | Submit background asynchronous architectural review job |
| 15 | `dev_reviewer_poll` | Reviewer & Runner | Poll background review job progress and non-terminal snapshot |
| 16 | `dev_reviewer_cancel` | Reviewer & Runner | Deterministically cancel in-flight review job |

---

## 5. Standard Lifecycle Walkthrough

```
  ┌────────────────────────────────────────────────────────┐
  │ 1. Session Startup: dev_tasks_status                   │
  └───────────────────────────┬────────────────────────────┘
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
       [Active Task Found]           [No Active Task]
               │                             │
               ▼                             ▼
     Follow 6 Core Fields           Check Confirmed Tasks
     Resume Implementation                   │
               │              ┌──────────────┴──────────────┐
               │              ▼                             ▼
               │      [Confirmed Exists]             [None Pending]
               │              │                             │
               │              ▼                             ▼
               │      dev_tasks_checkout             Consult Developer or
               │      (Acquire CAS Lock)             dev_tasks_archive
               │              │
               └──────────────┬─────────────────────────────┘
                              ▼
  ┌────────────────────────────────────────────────────────┐
  │ 2. Implementation: Strictly Edit Whitelisted Files     │
  │    (Optional: dev_tasks_heartbeat if > 60s)            │
  └───────────────────────────┬────────────────────────────┘
                              ▼
  ┌────────────────────────────────────────────────────────┐
  │ 3. Automated Verification: Execute DoD Commands        │
  └───────────────────────────┬────────────────────────────┘
                              ▼
  ┌────────────────────────────────────────────────────────┐
  │ 4. Completion: dev_tasks_complete                      │
  └────────────────────────────────────────────────────────┘
```

### Step 1: Session Startup Protocol
Before inspecting or modifying application source code, every agent session MUST call:

```bash
# Step 1: Query queue status
dev_tasks_status
```

- If an `[In Progress] / 🔨 执行中` task exists, the runner must resume work on that task immediately.
- If no active task exists, look for `[Confirmed] / ✅ 已确认` items.

### Step 2: Task Checkout & Physical Baseline Snapshot
To claim a task, call:

```bash
# Step 2: Checkout task
dev_tasks_checkout
```

`dev_tasks_checkout` executes three critical operations:
1. Atomically updates task heading to `🔨 执行中` in the Markdown specification.
2. Captures a physical file hash baseline of the repository.
3. Issues a lease holder token and generation counter (`generation`).

### Step 3: Scope Enforcement & Heartbeat
During implementation:
- **File Scope Whitelist**: Edits are restricted strictly to files listed in the task's `【涉及文件】` / `[Affected Files]` block. Edits outside this scope trigger pre-tool interception and reconciliation circuit breaking.
- **Heartbeat Renewal**: For long compilation, test runs, or migrations exceeding lease duration, call:

```bash
# Step 3: Maintain lease
dev_tasks_heartbeat
```

### Step 4: Verification & Completion
Execute the commands specified in the task's `【DoD 验证命令】` / `[DoD Verification Commands]`. All commands must pass with zero failures. Once verified:

```bash
# Step 4: Mark task complete
dev_tasks_complete
```

---

## 6. Reviewer Integration & Anti-Forgery Governance

### 6.1 Asynchronous Review Jobs
For deep architectural review or large refactoring proposals, use asynchronous jobs:
1. Submit job via `dev_reviewer_submit`.
2. Poll progress via `dev_reviewer_poll`. While in progress, poll responses provide compact non-terminal status snapshots bounded to $\le 1024$ bytes.
3. If necessary, cancel jobs via `dev_reviewer_cancel`.

### 6.2 Asynchronous Consultation & Review
For architectural reviews and guidance, submit jobs via `dev_reviewer_submit` and poll via `dev_reviewer_poll`.

### 6.3 Anti-Forgery Protection
Quench enforces physical defenses against fabricated or roleplayed reviews:
- When no valid Reviewer engine is configured (`provider: none`), review calls return `status: degraded`, `degraded_reason: reviewer_not_configured`, and empty findings (`findings: ""`).
- When the runner model profile and reviewer profile are identical (homogeneous identity), `self_verification_warning` is tagged to flag homogeneous bias.
- Reviewer outputs are recorded to append-only audit sinks (`VerdictAuditSink`), preserving chronological integrity.

---

## 7. Troubleshooting & Recovery

| Issue | Root Cause | Remediation |
|---|---|---|
| Checkout Rejected: `Task is currently in 🔄 需返工` | Task was flagged for rework by Reviewer | Consult Reviewer or human via `dev_tasks_escalate` or `dev_reviewer_submit` to refine spec |
| Checkout Rejected: Task already checked out | Another session or stale process holds the lease | Check process status; if dead, call `dev_tasks_reclaim` |
| Pre-Tool Interception: Unmanaged file edit | Target file is outside `【涉及文件】` whitelist | Revert unwanted change, or update task scope through `dev_tasks_refine_spec` / `dev_tasks_propose` |
| Emergency Hotfix Blocked | Unmanaged emergency typo or CI fix | Activate time-bounded token via `dev_tasks_set_bypass` |
| State Machine Inconsistency | Manual Markdown edits bypassed MCP tools | Run `dev_tasks_status` to identify parsing errors and restore proper format |
