---
name: dev-tasks-workflow
description: Guides how to adhere to the Quench DevTasks state machine lifecycle in development. Covers session startup protocols, six core field specifications, and task granularity guidelines. Use when inspecting task progress, checking out tasks, completing deliveries, or transitioning states.
---

# Quench Dev-Tasks Workflow Guide (开发任务工作流指南)

This guide directs everyday development runners (agile execution models) on how to operate efficiently within the Quench task governance framework.

---

## 1. Session Startup Protocol & Autopilot Relay (会话启动协议与接力棒驱动)

At the beginning of each session or after completing a phase of development, the execution agent must adhere to the single-caller protocol:

- **Main Session Ownership**: Only the main session invokes `dev_tasks_status(workspace_root)` and is driven by the returned `harness_next_action`.
- **Subagent Status Call Ban (子代理免调 status)**: All Subagents spawned for code exploration, research, or reviews are strictly exempt from calling `dev_tasks_status`. Subagents receive their task scope and parameters directly via dispatch envelopes.
- **Fallback Notice Relay**: If `dev_tasks_status` returns a non-empty `fallback_notice`, the main session must relay it to the developer in the first turn.

```
                    ┌─────────────────────────┐
                    │  Call dev_tasks_status  │ (Main session only)
                    └────────────┬────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  ▼                             ▼
      [Task In Progress 🔨]            [No Task In Progress]
                  │                             │
                  ▼                             ▼
      Extract instructions from        Follow harness_next_action
      the 6 core fields & resume       ┌───────────────┴───────────────┐
                                       ▼                               ▼
                             [Confirmed Tasks Exist]          [No Pending Work]
                                       │                               │
                                       ▼                               ▼
                             Call dev_tasks_checkout          Follow Autopilot baton
                             Enter [In Progress 🔨]           (ARCHIVE / NEXT_BATCH / PAUSE)
```

1. **Step 1**: Main session invokes `dev_tasks_status(workspace_root)` to inspect queue status and read `harness_next_action`.
2. **Step 2**:
   - If an `[In Progress] / 🔨 执行中` task exists: Immediately focus on it. Follow its `[Step-by-Step Instructions]` without deviation.
   - If no task is in progress:
     - If `[Confirmed] / ✅ 已确认` tasks exist: Call `dev_tasks_checkout(workspace_root)` to checkout the next item.
     - If only `[Pending] / ⬜ 待确认` or `[Rework] / 🔄 需返工` tasks exist: Follow `harness_next_action` (e.g. `REVIEW` via `dev_reviewer_submit` in-band; do not stop or throw handoff cards unless offline/degraded).
     - If all tasks are `[Completed] / ✔️ 已完成` (or `[Skipped] / ⏭️ 跳过`): Proceed to **Completion & Archiving (§5)**.

### Inverted Dual-Layer Code Exploration (倒置双层代码探查流程)
In dual-mode inverted orchestration:
1. **Layer 1 (Subagent Isolation)**: Main session dispatches an isolated Subagent with `[QUENCH-DISPATCH: RESEARCH]` to perform AST code reading and symbol exploration. The Subagent strictly never calls `dev_tasks_status` or state transition tools.
2. **Layer 2 (Baton Handoff)**: The Subagent returns structured seed files and context to the main session. The main session then calls `dev_tasks_refine_spec` / `dev_tasks_propose` or `dev_reviewer_submit`.

### Autopilot State Machine & Continuous Relay (Autopilot 接力棒状态机)
The Autopilot harness orchestrates transitions through `harness_next_action`:
`PROPOSE` -> `REVIEW` -> `CONFIRM` -> `CHECKOUT` -> `DISPATCH_RUNNER` -> `SYNC_DOCS` -> `ARCHIVE` -> `NEXT_BATCH_PROPOSE` -> `PAUSE_FOR_ACCEPTANCE` / `BLOCKED` / `ROADMAP_DONE`.
- **Continuous Non-Stop Relay**: During progression across tasks or batches (`NEXT_BATCH_PROPOSE`), the agent proceeds seamlessly without stopping.
- **Stopping States**: The agent only pauses and requests user input when reaching `PAUSE_FOR_ACCEPTANCE`, `BLOCKED`, or `ROADMAP_DONE`.

### Runner Subagent Reuse vs. Fresh Spawn Policy (Runner 子代理复用与新建策略)
In dual-mode inverted orchestration, `DISPATCH_RUNNER` provides deterministic subagent dispatch recommendations:
- **Intra-Batch Atomic Execution (`reuse_active`)**: A single `task_file` (Batch) is the atomic unit of delegation; never split a batch across multiple Runner subagents mid-file. Rework iterations and ongoing batches always reuse the active runner subagent.
- **Cross-Batch Domain Overlap (`spawn_fresh` vs `reuse_active`)**: At batch boundaries, `DISPATCH_RUNNER` evaluates file/module overlap (`compute_batch_overlap_ratio`) with a 12-task safety ceiling:
  - **High overlap (>= 30%) -> `reuse_active`**: Message the active Runner via `send_message` to retain hot file context. Name Runner `Role` by domain/module (e.g. `Backend Auth Runner`) rather than batch numbers (e.g. `Batch 1`).
  - **Low overlap (< 30%) or initial batch -> `spawn_fresh`**: Launch a fresh Runner subagent to prevent cross-domain context pollution.
  - **Safety Fuse**: If cumulative executed tasks on the active runner reach or exceed 12 tasks, force `spawn_fresh` at the batch boundary to purge token context bloat.

---

## 2. The Six Core Fields Standard (任务六大字段编写规范)

Every DevTask must contain the standard six core fields (bilingual headings supported):

> 🛡️ **Language Mirroring Contract (语言分层与镜像契约)**:  
> - **Freedom of Language**: DevTasks fully support either Chinese (`#### 【涉及文件】`, etc.) or English (`#### [Affected Files]`, etc.). Both heading formats are natively accepted by `schema_validator.py`.  
> - **Mandatory Mirroring**: When reading or refining existing tasks, the AI **MUST strictly mirror** the task's existing language and heading format. **Never translate or normalize Chinese task content or headings into English** (or vice versa).

### ① `[Affected Files]` (`#### [Affected Files]` / `#### 【涉及文件】`)
- **Format**: Fenced code block (` ``` `) with one path per line.
- **Prefixes**: `[MODIFY]`, `[NEW]`, `[DELETE]`, `[RENAME]`.
- **Enforcement**: PreToolUse hook whitelists these files; unmanaged file edits are intercepted.

### ② `[Root Cause & Target]` (`#### [Root Cause & Target]` / `#### 【缺陷根因与修改目标】`)
- **Format**: Concise statement of underlying root cause and intended engineering objective.

### ③ `[Type Contracts]` (`#### [Type Contracts]` / `#### 【目标签名与类型契约】`)
- **Format**: Exact function signatures, interfaces, Pydantic schemas, or data models.

### ④ `[Step-by-Step Instructions]` (`#### [Step-by-Step Instructions]` / `#### 【分步改造指引】`)
- **Format**: Numbered sequential action steps ordered by dependency.

### ⑤ `[Defensive & Edge Checks]` (`#### [Defensive & Edge Checks]` / `#### 【防御与边缘校验】`)
- **Format**: Bulleted list of bounds, null-checks, race condition defenses, and fallback behaviors.

### ⑥ `[DoD Verification Commands]` (`#### [DoD Verification Commands]` / `#### 【DoD 验证命令】`)
- **Format**: Fenced executable code block containing verifiable terminal commands that must pass 100%.

---

## 3. Task Granularity (任务粒度拆分原则)

- **Single Responsibility (单一职责)**: Focus each task on a single coherent module or bug fix.
- **Testability (可验证性)**: Every task must feature an automated DoD verification command.
- **Controlled Scope (改动范围可控)**: Aim for 1–5 files per task to keep contexts manageable and rollback easy.

---

## 4. MCP Tools Cheatsheet (MCP 工具调用速查)

The Quench DevTasks MCP Server exposes 16 specialized tools (full specification in [`dev_tasks_mcp_specification.md`](../../../../dev_tasks_mcp_specification.md)):

| Tool Name | Purpose | Usage Timing |
| :--- | :--- | :--- |
| `dev_tasks_status` | Query queue status, active task, and metrics | Session start, before/after checkouts |
| `dev_tasks_checkout` | Checkout task to `[In Progress]` | Claim confirmed tasks |
| `dev_tasks_complete` | Mark task as `[Completed]` with DoD proof | After DoD test verification |
| `dev_tasks_propose` | Propose new task as `[Pending]` | Planning new tasks or architectural reviews |
| `dev_tasks_confirm` | Transition task state (`confirm`/`rework`/`skip`) | Confirming batches or requesting rework |
| `dev_tasks_escalate` | Trigger Reviewer escalation / audit | Complex impasses or structural refactoring (invokes dev_reviewer_submit or subagent) |
| `dev_tasks_export_handoff_card` | Export Reviewer handoff card without state mutation | Inspection or manual cross-session consultation fallback |
| `dev_tasks_heartbeat` | Refresh active lease heartbeat | Long-running non-MCP execution turns |
| `dev_tasks_reclaim` | CAS-safe zombie task recovery | Recovering orphaned tasks across processes |
| `dev_tasks_refine_spec` | Refine draft spec with AST analysis & reasoning | Upgrading drafts into executable contracts |
| `dev_tasks_promote_draft`| Lint physical feasibility and promote draft | Promoting verified drafts to pending queue |
| `dev_reviewer_submit` | Submit async Reviewer background job | Long-running deep architectural reasoning |
| `dev_reviewer_poll` | Poll async job status (long-polling with wait_max_s, V2 6-field non-terminal snapshot & native progress) | Polling reasoning progress & verdict (20s wait_max_s recommended) |
| `dev_reviewer_cancel` | Deterministically cancel in-flight async job | Aborting in-progress background jobs |
| `dev_tasks_set_bypass` | Activate time-bounded bypass token | Urgent hotfixes, documentation, typos |
| `dev_tasks_archive` | Archive closed tasks and update changelog | All tasks in file closed |

---

## 5. Completion, Archiving & Delivery Card Timing (完工交付、归档与交付卡时机)

When all tasks in a DevTask file are `[Completed] / ✔️ 已完成`:

1. **Subjective / Visual / Hardware Tasks**: Provide an interactive inspection checklist for the developer.
2. **Automated Logic / Test-Covered Tasks**: Report full passing test results and propose archiving via `dev_tasks_archive`.
3. **C3 Delivery Card Timing (C3 完工交付卡时机)**:
   - The C3 delivery card (`[Task ID] ✔️ Completed` / `[Task ID] ✔️ 已完成`) MUST ONLY be output at stopping points or terminal states (`PAUSE_FOR_ACCEPTANCE`, `BLOCKED`, `ROADMAP_DONE`).
   - In continuous relay states (`PROPOSE`, `REVIEW`, `CONFIRM`, `CHECKOUT`, `DISPATCH_RUNNER`, `SYNC_DOCS`, `ARCHIVE`, `NEXT_BATCH_PROPOSE`), agents MUST NOT prematurely end turns to dump C3 cards.

---

## 6. Capability Isolation & Session Role Contract (能力隔离与会话角色契约)

### [DEPRECATED] Static QUENCH_ROLE Dual Entry Contract
*(Historical note: Pre-v1.25 used static `QUENCH_ROLE=runner` and `QUENCH_ROLE=reviewer` environment variables across two separate MCP server configurations. This approach is marked `[DEPRECATED]` in favor of dynamic runtime contracts).*

### Dynamic Session Role Contract (动态会话角色契约)
In v1.25+, capability boundaries and tool dispatch are governed dynamically via `session_role_contract`:
- Uses **host-neutral abstract verbs** (`read`, `write`, `execute_test`, `search`, `mcp_call`, `consult_review`) with zero host-specific tool names.
- Role arbitration and permissions are coordinated at runtime, ensuring complete vendor neutrality (INV-5).
- Envelope routing `[QUENCH-DISPATCH: RUNNER | REVIEWER | RESEARCH]` dispatches instructions unambiguously across main session and subagents.

> 🛡️ **Explicit Non-Security Boundary Declaration (非安全边界声明)**:  
> Role declarations and verdict logs are **collaborative convenience and operational hygiene contracts**, NOT an adversarial security boundary or process-level sandbox. Detailed onboarding standards and configuration templates are documented in [`docs/guides/external-executor-onboarding.md`](../../../../docs/guides/external-executor-onboarding.md).


