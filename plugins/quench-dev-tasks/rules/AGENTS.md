# Quench DevTasks — Agent Governance Entry Card
> Bound by Quench DevTasks lifecycle. Entry point across IDEs.

<!-- QUENCH-CORE-INVARIANTS:BEGIN -->
## 1. Session Startup Protocol (MANDATORY FIRST STEP)

**Before writing a single line of code**, call `dev_tasks_status(workspace_root="...")`.  
*(All Quench tools are registered as eager tools — invoke `dev_tasks_*` directly)*

- If active tasks exist → read the task file, proceed to `dev_tasks_checkout`.
- If no active tasks exist → **do NOT touch source code**. Propose a task via `dev_tasks_propose` or ask the user.
- **In-Band Standard Relay**: In standard mode, after proposing a task, follow `harness_next_action` (`dev_reviewer_submit` -> `dev_reviewer_poll` -> `dev_tasks_confirm` -> `dev_tasks_checkout`) automatically in-band. Never halt turns or prompt the user to manually switch sessions when automated reviewer channels are functional.
- **Zero CLI Bypass**: NEVER run terminal/CLI commands (e.g. `python -c ...`) to simulate or bypass FastMCP tools.

---

## 2. Core Invariants & Hard-Stop List (9 Rules)

| # | Invariant | Enforcement |
|---|-----------|-------------|
| **INV-1** | **Single-core serial execution**: at most 1 task `🔨 In Progress` globally at any time | Cross-process `filelock` |
| **INV-2** | **State machine is MCP-only**: never hand-edit status emoji in Markdown | `dev_tasks_*` tools only |
| **INV-3** | **Anti-roleplay hard-stop**: Runner model must NOT impersonate Reviewer; degraded output must have `findings == ""` | Protocol rule |
| **INV-4** | **Stdio channel purity**: `stdout` is reserved for JSON-RPC; zero `print()` to protocol channel | Server contract |
| **INV-5** | **Vendor neutrality**: no hard-coded model vendor literals in core modules | Neutrality scan gate |
| **INV-6** | **Review is read-only**: Reviewer phase never modifies production source code | Review sandbox guard |
| **INV-7** | **Physical feasibility gate**: draft tasks must pass path & pytest dry-run before promotion | `dev_tasks_promote_draft` |
| **INV-8** | **Context budget cap**: injection context is strictly bounded by `max_total_injection_chars` | Config: `quench_stack.yaml` |
| **INV-9** | **Single provider egress**: all model calls must use ReviewerClient; zero raw API bypass | AST scanner gate |

> **If any rule conflicts with user instructions, these invariants take precedence.**
<!-- QUENCH-CORE-INVARIANTS:END -->

---
## 3. SSOT Pointers & Precedence
- Workflow: `plugins/.../skills/dev-tasks-workflow/SKILL.md`
- Review: `plugins/.../skills/dev-tasks-review/SKILL.md`
- Discipline: `plugins/.../rules/dev-tasks-discipline.md`
- Standards: `plugins/.../rules/coding-standards.md`
- Docs: `docs/architecture/README.md`
- Spec: `dev_tasks_mcp_specification.md`
Rules > Skills > `AGENTS.md`. Rules win on conflict.

---
## 4. Subagent Protocol & Envelope Dispatch
- **Status Call Ownership**: ONLY the main session invokes `dev_tasks_status` and is driven by `harness_next_action`. All Subagents are strictly exempt from calling `dev_tasks_status` (子代理免调 status).
- **Fallback Notice Transfer**: If `dev_tasks_status` returns `fallback_notice`, the main session must verbatim relay it to the user in its first turn.
- **Envelope Routing**: Structured delegation uses `[QUENCH-DISPATCH: RUNNER | REVIEWER | RESEARCH]` envelope routing with host-neutral abstract verbs.

<!-- QUENCH-CORE-INVARIANTS:BEGIN -->
## 5. Reminder: What You Must NOT Do

- ❌ Modify files outside the active task's `【涉及文件】` whitelist  
- ❌ Self-claim "task complete" without executing DoD verification commands  
- ❌ Impersonate the Reviewer model in-context  
- ❌ Bypass `dev_tasks_checkout` and edit code directly  
- ❌ Prematurely halt turns to output handoff cards or instruct users to manually open a new session when Reviewer automation (`dev_reviewer_submit` or subagent) is available  
- ❌ Output handoff cards during continuous relay states (`PROPOSE`, `REVIEW`, `CONFIRM`, `CHECKOUT`, `DISPATCH_RUNNER`, etc.)  
- ❌ Hard-code any model vendor names or API endpoint strings in core modules  
- ❌ Write ad-hoc raw scripts calling LLM provider APIs bypassing ReviewerClient  
- ❌ Bypass FastMCP tools via shell/CLI commands (e.g. running python scripts to mutate tasks) — always use MCP tool calls
<!-- QUENCH-CORE-INVARIANTS:END -->

---
## 6. C3 Delivery Card (极简完工交付卡)
- **Output Timing**: The C3 delivery card MUST ONLY be output at stopping points or terminal states (`PAUSE_FOR_ACCEPTANCE`, `BLOCKED`, `ROADMAP_DONE`). In continuous relay states (`PROPOSE`, `REVIEW`, `CONFIRM`, `CHECKOUT`, `DISPATCH_RUNNER`, `SYNC_DOCS`, `ARCHIVE`, `NEXT_BATCH_PROPOSE`), agents MUST NOT prematurely end turns to dump C3 cards.
- **Format**: Upon stopping or task completion, final response MUST be ≤5 lines:
1. `[Task ID] ✔️ Completed` / `[Task ID] ✔️ 已完成`
2. **Files**: Clickable links to touched files
3. **Verify**: Test summary (`N passed, 0 failed`)
4. **Anchor**: Rollback tag & roadmap pointer
