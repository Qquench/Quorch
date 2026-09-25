# {{PROJECT_NAME}} — Quench DevTasks Agent Governance Card

> You are operating within the **Quench-governed codebase (`{{PROJECT_NAME}}`)**.  
> All engineering activities are **strictly bound by the Quench DevTasks lifecycle**.  
> This file is the authoritative cross-IDE entry point (Antigravity · Cursor · Claude Code · Windsurf).

---

<!-- QUENCH-CORE-INVARIANTS:BEGIN -->
## 1. Session Startup Protocol (MANDATORY FIRST STEP)

**Before writing a single line of code**, call:

```
dev_tasks_status
```

- If active tasks exist → read the task file, proceed to `dev_tasks_checkout`.
- If no active tasks exist → **do NOT touch source code**. Propose a task via `dev_tasks_propose` or ask the user.

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

| Resource | Location |
|----------|----------|
| Workflow guide (full lifecycle) | `.agents/` plugin skills — `dev-tasks-workflow/SKILL.md` |
| Execution discipline rules | `.agents/` plugin rules — `dev-tasks-discipline.md` |
| Coding standards | `.agents/` plugin rules — `coding-standards.md` |
| Project config | `.agents/quench_stack.yaml` |

> For the exact plugin paths, check `.agents/plugins.json` to locate the installed `quench-dev-tasks` plugin directory.

---

## 4. Precedence Hierarchy

```
plugin rules files  ←  Authoritative canonical source (highest priority)
        ↑
plugin skills files ←  Workflow playbooks (operational detail)
        ↑
AGENTS.md           ←  Router card only (this file — no redundant rule bodies)
```

When any conflict arises, the **plugin rules files win**.

---

<!-- QUENCH-CORE-INVARIANTS:BEGIN -->
## 5. Reminder: What You Must NOT Do

- ❌ Modify files outside the active task's `【涉及文件】` whitelist  
- ❌ Self-claim "task complete" without executing DoD verification commands  
- ❌ Impersonate the Reviewer model in-context  
- ❌ Bypass `dev_tasks_checkout` and edit code directly  
- ❌ Hard-code any model vendor names or API endpoint strings in core modules  
- ❌ Write ad-hoc raw scripts calling LLM provider APIs bypassing ReviewerClient
<!-- QUENCH-CORE-INVARIANTS:END -->
