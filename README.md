# Quench Dev-Orchestrator (`quorch`)

[English](README.md) | [简体中文](README_zh.md)

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python: >=3.12](https://img.shields.io/badge/python-3.12+-brightgreen.svg)](https://www.python.org/)
[![FastMCP: >=2.0](https://img.shields.io/badge/FastMCP-2.0+-orange.svg)](https://github.com/jlowin/fastmcp)
[![CI](https://github.com/Qquench/Quorch/actions/workflows/ci.yml/badge.svg)](https://github.com/Qquench/Quorch/actions/workflows/ci.yml)

> **Deterministic physical guardrails and dual-mode governance for AI coding agents.**  
> *Stop scope creep before it hits disk. Block verbal "done" claims without real test assertions.*

---

## 🎯 Why Quorch?

Most AI coding tools rely on prompt politeness: *"please only edit `auth.py` and run tests."* On real codebases, models still refactor unrelated modules, bypass specs, or claim tests pass without writing real assertions.

**Quorch enforces three deterministic physical defenses** via IDE PreToolUse hooks and a cross-process MCP state machine:

1. **PreToolUse File Scope Guard**: Locks file writes to the active task's declared `[Affected Files]` whitelist. Out-of-scope edits, unmanaged writes, direct task-status tampering, and shell redirection bypasses are intercepted before touching disk.
2. **Deterministic DoD Test Audit**: Before closing a task, Quorch inspects `git diff` in the test directory for real added assertions and records executed verification output—rejecting completion if production code changed without test evidence.
3. **Dual-Mode Role Decoupling (`inverted` & `standard`)**:
   - **`inverted` (Delegated Mode — Frontier Main + Subagent Runner)**: Run your chosen frontier model in the main IDE window as orchestrator & reviewer, and delegate scoped coding steps to lightweight host-native subagents (`Runner`) with zero external API keys.
   - **`standard` (Standard Mode — Agile Main + On-Demand Frontier Reviewer)**: Run a fast agile model in the main window for everyday coding, and invoke a higher-tier Reviewer on demand—via a higher-tier IDE subagent, a same-IDE model switch, or an optional external frontier API (such as OpenAI or DeepSeek).

---

## 🧭 When to Use Quorch?

| Workflow | Best Choice | Why |
| :--- | :--- | :--- |
| Rapid UI prototypes, one-off scripts, exploratory spikes | Native IDE chat | Zero setup overhead |
| Cleanly separable multi-file tasks with generous token budgets | Parallel multi-agent swarms (e.g., native `swarm`) | High throughput when file-edit overlap is low |
| **Tightly coupled backends, state machines, legacy refactors, or shared contracts** | **Quorch** | **Prevents out-of-scope edits, enforces single-active-task serial locks, and blocks unverified completions** |

---

## ⚡ 30-Second Quickstart

### 1. Install Quorch

```bash
git clone https://github.com/Qquench/Quorch.git
cd quorch
python scripts/install.py
```

The installer detects or provisions a Python virtual environment, validates dependencies (`fastmcp`, `filelock`, `pyyaml`, `pytest`), renders `mcp_config.json` and `hooks.json` from templates, and runs a pre-flight safety audit.

### 2. Connect Your Target Repository

```bash
python <path-to-quorch>/plugins/quench-dev-tasks/scripts/init_project.py <path-to-your-project>
```

This creates `.agents/plugins.json`, `.agents/quench_stack.yaml`, and `docs/dev_tasks/` in your project.

### 3. One-Line Starter Prompts (No Ceremonial Prompting Needed)

Quorch's `AGENTS.md` rules and `harness_next_action` automate the full task lifecycle behind the scenes. Just name the mode and state your goal:

- **Delegated Mode (`inverted`, zero external API — recommended)**:
  > *"Use inverted mode to fix the token timeout bug in `src/auth.py`."*
- **Standard Mode (`standard` — agile main window + on-demand higher-tier review via subagent or API)**:
  > *"Use standard mode to refactor config loading."*
- **Quick Bypass (for trivial doc/typo edits without a task sheet)**:
  > *"Enable bypass and fix the typo in `src/cli.py`."*

---

## 🛡️ Real Interception Showcase

Sanitized excerpts recorded directly by `file_scope_guard.py` and the DoD audit gate in `.agents/.quench_hook.log`:

```text
# 1. Blocked out-of-scope file creation during an active task
2026-10-20 02:01:53 [INFO] [ASK_MODAL] decision=ask tool=write_to_file target=<repo>/plugins/quench-dev-tasks/server/path_safety_core.py
reason=[Out-of-Scope File Modification Warning] Active task (Task 1.1) does not include this file in its declared scope.
Agent Justification: Create path_safety_core.py for zero-dependency path safety checks
Click [Allow] if this was a planning omission; click [Reject] if unexpected.

# 2. Blocked premature completion without test assertions (DoD Audit Gate)
2026-11-11 11:27:33 [INFO] [DOD GUARD REJECTED] Task 31.1 completion blocked: governed code modified (1 files) but no test assertions found and no valid exemption.

# 3. Blocked unmanaged source edits when no task is active
2026-11-11 11:09:10 [INFO] [ASK_MODAL] decision=ask tool=edit_file target=<repo>/plugins/quench-dev-tasks/server/server.py
reason=[Unmanaged Code Modification Confirmation] No Quench task is currently in '🔨 执行中' state, and the target file did not match any fast-track whitelist or session bypass rule.
```

> Shell redirections attempting to overwrite `docs/dev_tasks/` (such as `echo '...' > docs/dev_tasks/task.md` or `tee` / `Out-File`) are also immediately denied (`[DENIED]`) by the hook's shell bypass guard.

---

## 🔍 Under the Hood (Optional Reference)

<details>
<summary>🛠️ Full Suite of 16 MCP Tools (Managed Automatically by Agent Rules)</summary>

| Category | Tool | Purpose | Typical Invocation |
| :--- | :--- | :--- | :--- |
| **Task Lifecycle** | `dev_tasks_status` | Query active task overview, queue distributions (`include_drafts`), mode switching, and hook audit logs | Session startup, triage, or milestone check |
| | `dev_tasks_propose` | Propose new tasks adhering to the six-field schema (`⬜ Pending` or `📝 Draft`) | Architecture planning or backlog creation |
| | `dev_tasks_confirm` | Transition task states (`confirm`, `rework`, `skip`, `revoke`) | After review before execution |
| | `dev_tasks_checkout` | Check out confirmed tasks and set status to `🔨 In Progress` | Runner claiming the next verified task |
| | `dev_tasks_complete` | Complete a task with DoD test output audit & scope reconciliation | Runner upon passing all automated DoD commands |
| | `dev_tasks_escalate` | Escalate a stuck task and generate a multi-tier Reviewer Handoff Card | Runner encountering design deadlocks or regressions |
| | `dev_tasks_export_handoff_card` | Export standalone Reviewer Handoff Card without mutating task state | Manual cross-session reviewer consultation |
| **Lease & Concurrency** | `dev_tasks_heartbeat` | Active heartbeat reporting and lease extension for long-running tasks | During long non-MCP tool execution turns |
| | `dev_tasks_reclaim` | Reclaim crashed or timed-out stale tasks safely with CAS fencing | Recovering orphaned tasks across processes |
| **Drafting & Feasibility** | `dev_tasks_refine_spec` | Refine a task spec with AST codebase symbol analysis & Reviewer reasoning | Upgrading draft tasks into executable contracts |
| | `dev_tasks_promote_draft` | Lint physical feasibility (path defenses, dry-run) and promote draft to pending | Promoting verified drafts to the execution queue |
| **Reviewer Consultation** | `dev_reviewer_submit` | Submit asynchronous Reviewer consultation job with detached background execution | Long-running architectural reasoning jobs |
| | `dev_reviewer_poll` | Poll async Reviewer job status and retrieve results (1KB snapshot & structured verdict) | Checking background reasoning progress & verdict |
| | `dev_reviewer_cancel` | Deterministically cancel an in-flight async Reviewer job | Aborting unwanted or stuck reasoning jobs |
| **Governance & Escape** | `dev_tasks_set_bypass` | Activate time-bounded, session-locked fast-track bypass | Light touch edits (e.g. documentation, typos) |
| | `dev_tasks_archive` | Archive closed tasks and append to `CHANGELOG.md` | Once all tasks in a file are completed |

</details>

<details>
<summary>🧱 Architecture, Workflows & Detailed Capabilities</summary>

```text
User Request ──▶ Strategic Plan & Spec (6 Core Fields) ──▶ ✅ Confirmed
                                                               │
                 PreToolUse Scope Guard ◀── 🔨 In Progress ◀───┘
                         │
                         ▼
                 DoD Test & Diff Audit ──▶ ✔️ Completed ──▶ CHANGELOG.md
```

- **Two Role Topologies (`inverted` & `standard`)**:
  - **Delegated Mode (`inverted`)**: Main IDE session holds frontier architectural context and dispatches `Runner` subagents with zero external API keys (ideal when the host subagent selector does not expose the top frontier tier).
  - **Standard Mode (`standard`)**: Main IDE session uses an agile model for fast execution and triggers a higher-tier `Reviewer` on demand—through a higher-tier IDE subagent, manual same-IDE model switch, or an external frontier API (`OpenAI` / `DeepSeek` / enterprise OpenAI-compatible clusters such as full-weight `vLLM` endpoints) configured in `.agents/quench_stack.local.yaml`.
- **Vendor-Neutral Reviewer Engine (`ReviewerClient`)**: Backed by an automated AST egress scan (`plugins/quench-dev-tasks/scripts/check_no_api_bypass.py`) ensuring zero ad-hoc provider API bypasses and zero hardcoded vendor literals in core modules.
- **Strict Anti-Roleplaying & Structured Contracts**: Non-terminal poll responses obey a strict <= 1KB snapshot contract; terminal verdicts are bounded at 40,000 characters; unavailable engines return explicit degraded cards with empty findings.
- **Observable Thinking Stream**: Streaming logs under `.agents/logs/reviewer/` with 1024KB hard-cap rotation and cross-chunk redaction while keeping MCP `stdout` strictly pure for JSON-RPC.
- **Atomic State Machine & Lease Governance**: Cross-process `filelock`, baseline git-diff reconciliation, and six-field schema validation (`Affected Files`, `Root Cause & Target`, `Type Contracts`, `Step-by-Step Instructions`, `Defensive Checks`, `DoD Verification Commands`).
- **Zero Business Intrusion**: Language- and framework-agnostic; configured per repository in `.agents/quench_stack.yaml`.

</details>

---

## 💡 Project Origin & Note from the Author

> **Transparency Notice**  
> This project originated from my personal engineering workflow while building software on **Windows using Google Antigravity IDE**. The core state machine, task governance engine, and Antigravity hook integration have been battle-tested in daily local development.
>
> Support for other host tools (such as **Cursor**, Windsurf, etc.) and POSIX platforms was built against the existing adapter abstractions by AI agents, as I do not actively use those environments day to day. Although the repository includes an automated test suite (**1,300+ collected tests** under `pytest`), real-world edge cases across other IDEs or operating systems may still surface.
>
> Community feedback, bug reports, and Pull Requests from users of Cursor, Linux, and macOS are warmly appreciated!

---

## 📖 Documentation Directory

- ⚙️ [docs/configuration.md](docs/configuration.md): Complete configuration reference for `quench_stack.yaml` (modes, `reviewer_engine`, `audit_gate`, boundaries).
- 🏛️ [docs/architecture/](docs/architecture/README.md): System architecture (4-tier topology, core invariants, module map).
- 📐 [dev_tasks_mcp_specification.md](dev_tasks_mcp_specification.md): FastMCP tool & protocol specification.
- 🌐 [CHANGELOG.md](CHANGELOG.md): Release history and architectural evolution.
- 🤝 [CONTRIBUTING.md](CONTRIBUTING.md): Contribution guidelines and test suite instructions.
- ❓ [docs/FAQ.md](docs/FAQ.md): Troubleshooting paths, encoding, proxies, and hooks.
- 📜 [LICENSE](LICENSE): Apache License 2.0 (Apache-2.0).

---

## 📄 License

This project is licensed under the [Apache License 2.0 (Apache-2.0)](LICENSE). It permits commercial and private use, modification, and distribution with an explicit patent grant and no copyleft obligations on your governed projects.
