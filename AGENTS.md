# Quench DevTasks — Agent Governance Entry Card

> You are operating within the **Quench-governed codebase (`quorch`)**.  
> All engineering activities are **strictly bound by the Quench DevTasks lifecycle**.  
> This file is the authoritative cross-IDE entry point (Antigravity · Cursor · Claude Code · Windsurf).

---

<!-- QUENCH-CORE-INVARIANTS:BEGIN -->
## 1. Session Startup Protocol (MANDATORY FIRST STEP)

**Before writing a single line of code**, call `dev_tasks_status`.  
*(In Lazy-MCP environments like Antigravity, call: `call_mcp_tool(ServerName="quench-dev-tasks", ToolName="dev_tasks_status", Arguments={"workspace_root": "..."})`)*

- If active tasks exist → read the task file, proceed to `dev_tasks_checkout`.
- If no active tasks exist → **do NOT touch source code**. Propose a task via `dev_tasks_propose` or ask the user.
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

## 3. Authoritative SSOT Pointers

| Resource | Path |
|----------|------|
| Workflow guide (full lifecycle) | `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| Review discipline guide | `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md` |
| Execution discipline rules | `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md` |
| Coding standards | `plugins/quench-dev-tasks/rules/coding-standards.md` |
| System architecture | `docs/architecture/README.md` |
| FastMCP protocol & task schema spec | `dev_tasks_mcp_specification.md` |

---

## 4. Precedence Hierarchy

```
plugins/.../rules/  ←  Authoritative canonical source (highest priority)
        ↑
plugins/.../skills/ ←  Workflow playbooks (operational detail)
        ↑
AGENTS.md           ←  Router card only (this file — do NOT duplicate rule bodies)
```

When any conflict arises, the **plugin rules files win**. This file intentionally contains no redundant rule bodies.

---

<!-- QUENCH-CORE-INVARIANTS:BEGIN -->
## 5. Reminder: What You Must NOT Do

- ❌ Modify files outside the active task's `【涉及文件】` whitelist  
- ❌ Self-claim "task complete" without executing DoD verification commands  
- ❌ Impersonate the Reviewer model in-context  
- ❌ Bypass `dev_tasks_checkout` and edit code directly  
- ❌ Hard-code any model vendor names or API endpoint strings in core modules  
- ❌ Write ad-hoc raw scripts calling LLM provider APIs bypassing ReviewerClient  
- ❌ Bypass FastMCP tools via shell/CLI commands (e.g. running python scripts to mutate tasks) — always use MCP tool calls
<!-- QUENCH-CORE-INVARIANTS:END -->
- ❌ Dump verbose execution logs, large diff tables, or token recitations into chat upon task completion (strictly output the ≤5 line C3 Delivery Card)

---

## 6. Runner Completion Delivery Card Contract (C3 极简完工交付卡)

Upon calling `dev_tasks_complete`, the runner model's final response MUST strictly adhere to the compact 4-line card (≤5 lines):
1. **Header**: `[Task ID] ✔️ Completed` / `[Task ID] ✔️ 已完成`
2. **Affected Files**: Compact list of touched files with clickable markdown links
3. **Verification**: Automated test results summary (`N passed, 0 failed`)
4. **Anchor**: Git rollback tag & pointer to updated roadmap/spec

*Do NOT re-recite deletion ledgers, zero-delete token counts, or markdown tables in chat.*
