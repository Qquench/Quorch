---
name: dev-tasks-workflow
description: Guides how to adhere to the Quench DevTasks state machine lifecycle in development. Covers session startup protocols, six core field specifications, and task granularity guidelines. Use when inspecting task progress, checking out tasks, completing deliveries, or transitioning states. (指导如何在开发中遵循 Quench 任务状态机生命周期流转。涵盖会话启动协议、六大核心字段编写规范与任务粒度拆分原则。当需要查看任务进度、领取执行任务、完成交付或流转状态时使用。)
---

# Quench Dev-Tasks Workflow Guide (开发任务工作流指南)

This guide directs everyday development runners (agile execution models) on how to operate efficiently within the Quench task governance framework.

---

## 1. Session Startup Protocol (会话启动协议)

At the beginning of each session or after completing a phase of development, the model must follow this standard protocol:

```
                    ┌─────────────────────────┐
                    │  Call dev_tasks_status  │
                    └────────────┬────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
     [Task In Progress 🔨]            [No Task In Progress]
                 │                               │
                 ▼                               ▼
     Extract instructions from        Check for [Confirmed ✅] tasks
     the 6 core fields & resume       ┌───────────────┴───────────────┐
                                      ▼                               ▼
                            [Confirmed Tasks Exist]          [No Pending Work]
                                      │                               │
                                      ▼                               ▼
                            Call dev_tasks_checkout          Ask developer or
                            Enter [In Progress 🔨]           call dev_tasks_archive
```

1. **Step 1**: Invoke `dev_tasks_status(workspace_root)` to inspect queue status and active tasks.
2. **Step 2**:
   - If an `[In Progress] / 🔨 执行中` task exists: Immediately focus on it. Follow its `[Step-by-Step Instructions]` without deviation.
   - If no task is in progress:
     - If `[Confirmed] / ✅ 已确认` tasks exist: Call `dev_tasks_checkout(workspace_root)` to checkout the next item.
     - If only `[Pending] / ⬜ 待确认` or `[Rework] / 🔄 需返工` tasks exist: **Halt and present a Handoff Card** to hand off review to the Strategic Reviewer.
     - If all tasks are `[Completed] / ✔️ 已完成` (or `[Skipped] / ⏭️ 跳过`): Proceed to **Completion & Archiving (§5)**.

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

The Quench DevTasks MCP Server exposes 17 specialized tools (full specification in [`dev_tasks_mcp_specification.md`](../../../dev_tasks_mcp_specification.md)):

| Tool Name | Purpose | Usage Timing |
| :--- | :--- | :--- |
| `dev_tasks_status` | Query queue status, active task, and metrics | Session start, before/after checkouts |
| `dev_tasks_checkout` | Checkout task to `[In Progress]` | Claim confirmed tasks |
| `dev_tasks_complete` | Mark task as `[Completed]` with DoD proof | After DoD test verification |
| `dev_tasks_propose` | Propose new task as `[Pending]` | Planning new tasks or architectural reviews |
| `dev_tasks_confirm` | Transition task state (`confirm`/`rework`/`skip`) | Confirming batches or requesting rework |
| `dev_tasks_escalate` | Trigger Reviewer handoff card | Complex impasses or structural refactoring |
| `dev_tasks_export_handoff_card` | Export Reviewer handoff card without state mutation | Manual cross-session consultation |
| `dev_tasks_heartbeat` | Refresh active lease heartbeat | Long-running non-MCP execution turns |
| `dev_tasks_reclaim` | CAS-safe zombie task recovery | Recovering orphaned tasks across processes |
| `dev_tasks_refine_spec` | Refine draft spec with AST analysis & reasoning | Upgrading drafts into executable contracts |
| `dev_tasks_promote_draft`| Lint physical feasibility and promote draft | Promoting verified drafts to pending queue |
| `dev_reviewer_consult` | Synchronous direct architecture consultation | Quick spontaneous critique/evaluation/audit |
| `dev_reviewer_submit` | Submit async Reviewer background job | Long-running deep architectural reasoning |
| `dev_reviewer_poll` | Poll async job status (supports `raw_text=True`) | Polling reasoning progress & verdict |
| `dev_reviewer_cancel` | Deterministically cancel in-flight async job | Aborting in-progress background jobs |
| `dev_tasks_set_bypass` | Activate time-bounded bypass token | Urgent hotfixes, documentation, typos |
| `dev_tasks_archive` | Archive closed tasks and update changelog | All tasks in file closed |

---

## 5. Completion & Archiving Protocol (完工交付与归档闭环)

When all tasks in a DevTask file are `[Completed] / ✔️ 已完成`:

1. **Subjective / Visual / Hardware Tasks**: Provide an interactive inspection checklist for the developer.
2. **Automated Logic / Test-Covered Tasks**: Report full passing test results and propose archiving via `dev_tasks_archive`.
