# 🧊 quench-dev-tasks

[English](README.md) | [简体中文](README_zh.md)

> **Dual-Model Orchestration & Task Governance Suite for Modern AI IDEs**  
> (Google Antigravity, Cursor, Windsurf, Claude Code)  
> Engineered for agile execution (Runner) paired with on-demand strategic architecture review (Reviewer).

---

## 🌟 Key Features

1. **Dual-Model Decoupled Collaboration (Runner + Reviewer)**:
   - **Agile Runner**: Handles daily implementation, small fixes, and incremental feature delivery, saving expensive frontier reasoning model tokens.
   - **Strategic Reviewer**: Awoken on demand (or through self-escalation) to perform deep architectural reviews, diagnose deadlocks, and draft rigorous DevTasks.
2. **Deterministic State Machine**:
   - Strict unidirectional state progression: `📝 DRAFT` ➔ `⬜ PROPOSED` ➔ `✅ CONFIRMED` ➔ `🔨 IN_PROGRESS` ➔ `✔️ COMPLETED` (with `🔄 REWORK` and `⏭️ SKIPPED` branches).
   - **Single-Core Execution**: Globally restricts the workspace to at most one task in progress at any time.
   - **Multi-Process FileLock**: Prevents file corruption caused by concurrent subagent writes or external git operations.
3. **Physical Interception Layers (PreToolUse Hook & Git Pre-commit Guard)**:
   - Verifies attempted file modifications against the task's whitelist before edits touch disk in Antigravity.
   - Triggers interactive confirmation dialogs with agent justification when edits fall outside scope.
   - Provides physical hard defense via Git Pre-commit Hooks for editors without PreToolUse hooks (e.g. Cursor).
4. **The Six-Core-Field Standard**:
   - Mandates: Affected Files, Root Cause & Target, Type Contracts, Step-by-Step Instructions, Defensive Checks, and DoD Verification Commands.
5. **3-Tier Fast-Track Architecture**:
   - **Layer 1: Static Whitelist**: Configurable `allow_untracked_patterns` for files naturally exempt from governance.
   - **Layer 2: Session Bypass**: `dev_tasks_set_bypass` grants temporary authorization for quick style/doc tweaks with a 4-hour hard expiry.
   - **Layer 3: Interactive Ask Modal**: Prompts developers for one-off manual decisions when unexpected files are touched.
6. **Language-Agnostic Project Decoupling**:
   - The engine is completely decoupled from domain business code, configured purely through `.agents/quench_stack.yaml`.

---

## 📁 Directory Structure

```text
quench-dev-tasks/
├── plugin.json                 # Antigravity plugin manifest
├── mcp_config.json.template    # MCP configuration template
├── hooks.json.template         # Lifecycle hook guard template
├── rules/                      # System prompt rules injection
│   └── dev-tasks-discipline.md
├── skills/                     # Progressive workflow manuals
│   ├── dev-tasks-workflow/
│   └── dev-tasks-review/
├── agents/                     # Specialized subagents
│   └── reviewer/
├── server/                     # FastMCP server implementation
│   ├── server.py               # 10 core governance tools
│   ├── reviewer_engine.py      # Pluggable ReviewerClient & Thinking Log Sink
│   ├── code_explorer.py        # AST Codebase Explorer
│   ├── state_machine.py        # State machine engine + FileLock
│   ├── schema_validator.py     # Six-core-field validator & Draft physical lint gate
│   ├── project_config.py       # Project manifest parser & schema migration
│   ├── changelog_writer.py     # Automated CHANGELOG sync
│   ├── cli.py                  # Unified terminal CLI (`quench status/check/archive`)
│   ├── adapters/               # Multi-client adapter layer
│   ├── hooks/                  # PreToolUse guard & context injector
│   └── tests/                  # Automated test suite (167/167 passed)
├── scripts/                    # Utility scripts
│   ├── init_project.py         # Project scaffolding script
│   ├── git_pre_commit_guard.py # Git pre-commit hard guard
│   └── rules_exporter.py       # Cursor rules / MDC exporter
└── templates/                  # Configuration templates
    └── quench_stack.yaml
```

---

## 🚀 Quick Start

### 1. Environment Setup
```bash
cd server
python -m venv venv
# Windows:
.\venv\Scripts\pip install -r requirements.txt
# Linux/macOS:
source venv/bin/activate && pip install -r requirements.txt
```

### 2. Scaffold a Project
Initialize task governance in any codebase:
```bash
# Antigravity IDE setup
python scripts/init_project.py /path/to/your/project --name "YourProject"

# Cursor IDE setup (generates .cursor/mcp.json, MDC rules, and installs Git Hook)
python scripts/init_project.py /path/to/your/project --ide cursor --install-git-hook
```

---

## 🛠️ MCP Tools Reference

| Tool Name | Description |
| :--- | :--- |
| `dev_tasks_status` | Returns task status overview (`include_drafts`), active session bypasses, and recent audit logs |
| `dev_tasks_propose` | Submits a new task proposal with six-core-field validation (`⬜ Pending` or `📝 Draft`) |
| `dev_tasks_refine_spec` | Refines a task spec with AST codebase symbol analysis and Reviewer reasoning |
| `dev_tasks_promote_draft`| Lints physical feasibility (path traversal, syntax dry-run) and promotes a draft to pending |
| `dev_tasks_confirm` | Confirms task documents (`confirm`, `rework`, `skip`, `revoke`) |
| `dev_tasks_checkout` | Checks out a task for execution with single-core FileLock acquisition |
| `dev_tasks_complete` | Marks a task completed after auditing DoD test verification |
| `dev_tasks_escalate` | Escalates blocked tasks to a multi-tier Reviewer handoff card |
| `dev_tasks_archive` | Archives closed tasks and synchronizes summaries into CHANGELOG.md |
| `dev_tasks_set_bypass` | Authorizes temporary session bypasses for minor stylistic/doc adjustments |

---

## 📄 License

This project is licensed under the [Mozilla Public License 2.0 (MPL-2.0)](LICENSE).
