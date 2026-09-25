# Quench Dev-Orchestrator (`quorch`)

[English](README.md) | [简体中文](README_zh.md)

[![License: MPL-2.0](https://img.shields.io/badge/License-MPL_2.0-blue.svg)](https://opensource.org/licenses/MPL-2.0)
[![Python: >=3.11](https://img.shields.io/badge/python-3.11+-brightgreen.svg)](https://www.python.org/)
[![FastMCP: >=2.0](https://img.shields.io/badge/FastMCP-2.0+-orange.svg)](https://github.com/jlowin/fastmcp)
[![CI](https://github.com/Qquench/Quorch/actions/workflows/ci.yml/badge.svg)](https://github.com/Qquench/Quorch/actions/workflows/ci.yml)

> **Enforcement-First Dual-Model Governance for AI Coding Agents**  
> *Physical enforcement where hooks are available; high-tension prompt discipline where they are not.*  
> *Strategic Frontier Reasoning (Reviewer) for Architecture & Conflict Resolution • Agile Runner for Lightweight Implementation & Automated DoD Verification.*

---

## 🎯 The Problem

While AI-assisted coding tools have transformed modern software development, engineering teams frequently encounter four major bottlenecks in real-world codebases:

1. **High Token Costs of Frontier Reasoning Models**: Using expensive flagship reasoning models for full-cycle development quickly exhausts quotas; relying solely on lightweight models for complex architecture leads to costly rework and hallucinations.
2. **Scope Creep & Hallucinated File Edits**: Agents frequently make unsolicited modifications to unrelated files, breaking legacy contracts and introducing subtle regressions.
3. **Lack of Lifecycle Traceability**: Development often occurs informally in conversational chat windows without immutable state tracking, structured handoffs, or rollback paths.
4. **Verbal "Done" without Verified DoD**: Models casually claim "completed" without executing actual test commands or verifying physical assertions.

---

## 💡 The Solution

**Quench Dev-Orchestrator (`quorch`)** provides an out-of-the-box, dual-model governance framework that combines agile execution with rigorous architectural oversight:

```
                  ┌─────────────────────────────────────────┐
                  │   User Request / Feature Specification  │
                  └────────────────────┬────────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │   Strategic Reviewer (Frontier)   │
                     │  • Deep Architectural Analysis    │
                     │  • Root Cause & Contract Design   │
                     │  • Six-Field DevTask Formulation  │
                     └─────────────────┬─────────────────┘
                                       │ Task Handoff (✅ Confirmed)
                                       ▼
                     ┌───────────────────────────────────┐
                     │       Agile Runner (Runner)       │
                     │  • Sequential Step Implementation │
                     │  • PreToolUse Scope Enforcement   │
                     │  • Automated DoD Test Execution   │
                     └─────────────────┬─────────────────┘
                                       │
                 ┌─────────────────────┴─────────────────────┐
                 ▼                                           ▼
      [DoD All Tests Pass]                      [Major Conflict / Complexity]
                 │                                           │
                 ▼                                           ▼
      dev_tasks_complete                         dev_tasks_escalate
  (Changelog & Stage Archive)               (Handoff Back to Reviewer)
```

### Key Capabilities

- **Dual-Model Role Decoupling**: 90% of implementation is performed by cost-effective agile models (`Runner`). High-order reasoning models (`Reviewer`) are invoked only during task planning, architectural review, or conflict escalation.
- **Vendor-Neutral Reviewer Engine (`ReviewerClient`)**: Fully pluggable architecture powered by declarative `PROVIDER_PRESETS` supporting OpenAI, DeepSeek (with Prompt Cache detection), offline Ollama, vLLM, generic proxy endpoints, native IDE subagents, and graceful manual fallback—guaranteed by an automated source-level neutrality scan gate.
- **Asynchronous Reviewer Job System (`dev_reviewer_submit`, `dev_reviewer_poll`, `dev_reviewer_cancel`)**: Decouples long-running architecture reasoning into detached background worker jobs with durable persistence, deterministic cancellation, 1KB non-terminal snapshot bounds, and `wait_max_s` long polling.
- **Clean Raw-Text Heartbeat Projection**: Eliminates JSON notification clutter in IDE contexts by projecting non-terminal heartbeat lines (`[Reviewer thinking: 1,234 tokens | 12.3s]`) via `raw_text=True`, keeping token footprints minimal and conversations clean.
- **Ad-Hoc Architecture Consultation (`dev_reviewer_consult`)**: Dedicated tool for spontaneous design critique, trade-off evaluation, brainstorming, and contract auditing without requiring DevTask workflows, featuring read-only sandbox guards and byte-level stable prompt prefix caching.
- **Strict Single-Egress Invariant & AST Enforcement**: CI and development environments enforce zero ad-hoc provider API script bypasses via `scripts/check_no_api_bypass.py`, ensuring all upstream model traffic funnels through `ReviewerClient`.
- **Strict Anti-Roleplaying Protocol**: Forbids in-context impersonation of the Reviewer by executor models, enforcing explicit structured degraded fallback cards with empty findings whenever the external engine is unavailable.
- **AST Codebase Explorer & Spec Refiner (`dev_tasks_refine_spec`)**: Extracts precise AST symbols and call-chains without dumping whole codebases, automatically upgrading draft specifications into hardened six-field contracts.
- **Observable Thinking Stream & Low-Frequency Heartbeats**: Dedicated streaming logs under `.agents/logs/reviewer/` (`thinking.log` and `latest-<session_id>.log`) with a 1024KB hard-cap safe rotation, cross-boundary pre-write redaction, and bounded progress notifications to keep MCP stdio JSON-RPC transport pristine.
- **Draft Task State & Physical Feasibility Lint Gate (`📝 Draft`)**: Isolates unready architectural ideas; enforces path traversal defenses, physical file existence checks, overwrite hazard prevention, and pytest dry-run syntax verification before task promotion.
- **Physical PreToolUse Guard & Workspace Scope Reconciliation**: Intercepts unauthorized file modifications outside the active task's whitelist at both the IDE hook level (PreToolUse) and the server-side state machine level (Baseline Snapshot git diff reconciliation).
- **Atomic State Machine & Lease Governance**: Backed by cross-process `filelock` and heartbeat leases, strictly enforcing single-active-task execution, preventing multi-subagent race conditions.
- **Six-Core-Field Contract**: Every task must define Affected Files, Root Cause & Target, Type Contracts, Step-by-Step Instructions, Defensive Checks, and Executable DoD Verification Commands.
- **Zero Business Intrusion**: Completely language- and framework-agnostic. Configured per repository via `.agents/quench_stack.yaml`.

---

## ⚡ 30-Second Quickstart

### 1. Installation

Clone this repository and run the cross-platform installer:

```bash
git clone https://github.com/Qquench/Quorch.git
cd quorch
python scripts/install.py
```

The installer will:
- Detect or set up your virtual environment (`.venv` or `venv`);
- Verify required dependencies (`fastmcp`, `filelock`, `pyyaml`, `pytest`);
- Render platform-tailored `mcp_config.json` and `hooks.json` from templates;
- Perform a pre-flight handle and path safety audit.

### 2. Connect Your Project

Navigate to any project repository where you wish to activate Quench DevTasks:

```bash
python <path-to-quorch>/plugins/quench-dev-tasks/scripts/init_project.py <path-to-your-project>
```

This creates:
- `.agents/plugins.json`: Registers the `quench-dev-tasks` plugin;
- `.agents/quench_stack.yaml`: Custom project boundaries, constraints, test runners, and reviewer configuration;
- `docs/dev_tasks/`: Dedicated directory for devtask lifecycle workflows.

---

## 🛠️ MCP Tools & Capabilities

The `quench-dev-tasks` MCP Server provides a comprehensive suite of 17 specialized tools:

| Category | Tool | Purpose | Typical Invocation |
| :--- | :--- | :--- | :--- |
| **Task Lifecycle** | `dev_tasks_status` | Query active task overview, queue distributions (`include_drafts`), and hook audit logs | Session startup, triage, or milestone check |
| | `dev_tasks_propose` | Propose new tasks adhering to the six-field schema (`⬜ Pending` or `📝 Draft`) | Architecture planning or backlog creation |
| | `dev_tasks_confirm` | Transition task states (`confirm`, `rework`, `skip`, `revoke`) | After Reviewer verification before execution |
| | `dev_tasks_checkout` | Check out confirmed tasks and set status to `🔨 In Progress` | Runner claiming the next verified task |
| | `dev_tasks_complete` | Complete a task with DoD test output audit & scope reconciliation | Runner upon passing all automated DoD commands |
| | `dev_tasks_escalate` | Escalate a stuck task and generate a multi-tier Reviewer Handoff Card | Runner encountering design deadlocks or regressions |
| | `dev_tasks_export_handoff_card`| Export standalone Reviewer Handoff Card without mutating task state | Manual cross-session reviewer consultation |
| **Lease & Concurrency** | `dev_tasks_heartbeat` | Active heartbeat reporting and lease extension for long-running tasks | During long non-MCP tool execution turns |
| | `dev_tasks_reclaim` | Reclaim crashed or timed-out stale tasks safely with CAS fencing | Recovering orphaned tasks across processes |
| **Drafting & Feasibility**| `dev_tasks_refine_spec` | Refine a task spec with AST codebase symbol analysis & Reviewer reasoning | Upgrading draft tasks into executable contracts |
| | `dev_tasks_promote_draft`| Lint physical feasibility (path defenses, dry-run) and promote draft to pending | Promoting verified drafts to the execution queue |
| **Reviewer Consultation** | `dev_reviewer_consult` | Synchronous direct Reviewer consultation (critique / evaluate / brainstorm / audit) | Spontaneous architectural inquiry, trade-off analysis |
| | `dev_reviewer_submit` | Submit asynchronous Reviewer consultation job with detached background execution | Long-running architectural reasoning jobs |
| | `dev_reviewer_poll` | Poll async Reviewer job status and retrieve results with raw-text progress | Checking background reasoning progress & verdict |
| | `dev_reviewer_cancel` | Deterministically cancel an in-flight async Reviewer job | Aborting unwanted or stuck reasoning jobs |
| **Governance & Escape** | `dev_tasks_set_bypass` | Activate time-bounded, session-locked fast-track bypass | Light touch edits (e.g. documentation, typos) |
| | `dev_tasks_archive` | Archive closed tasks and append to `CHANGELOG.md` | Once all tasks in a file are completed |

## 🧑‍💻 3-Minute Interactive Walkthrough

### Two Operation Paradigms

| | Paradigm A — Zero-API IDE Mode *(Recommended for beginners)* | Paradigm B — API-Driven Automation |
|---|---|---|
| **Setup** | No third-party API key required | Configure `DeepSeek` / `OpenAI` / `Ollama` endpoint in `quench_stack.yaml` |
| **Reviewer invocation** | Switch IDE session to a frontier model; paste the Handoff Card | `ReviewerClient` calls the API automatically in the background |
| **Best for** | Getting started, occasional architectural review | Full automation, overnight batch planning |

### A 5-Step Dialogue Walkthrough (Paradigm A — IDE Mode)

**Step 1 — State your intent** (in your IDE chat window with the Runner model):
> *"I want to add a path whitelist validation feature to the config module."*

**Step 2 — Task drafted** (Reviewer or Runner with `dev_tasks_propose`):
> A task file with all six required fields is created in `docs/dev_tasks/` with status `📝 Draft` or `⬜ Pending`.

**Step 3 — Confirm the task**:
> After review, call `dev_tasks_confirm(action="confirm")` → status becomes `✅ Confirmed`.

**Step 4 — Check out & implement** (Runner):
> Runner calls `dev_tasks_checkout` → status becomes `🔨 In Progress`.  
> Runner edits **only** the files listed in `【Affected Files】`, following steps in sequence.

**Step 5 — DoD verification & close**:
> Runner executes the DoD commands from the task file. All tests pass → `dev_tasks_complete` → `✔️ Completed` → archived to `CHANGELOG.md`.

---

## 💡 Project Origin & Note from the Author

> **Note from the Author / Transparency Notice**  
> This project originated from my personal workflow and real-world engineering needs while building software on **Windows using Google Antigravity IDE**. The core state machine, task governance engine, and Antigravity hook integration have been thoroughly developed, battle-tested, and verified locally.
> 
> However, extending this framework to other developer tools (such as **Cursor**, Windsurf, etc.) or cross-platform operating systems was generated by AI models based on the existing architecture abstractions, as I do not have personal development experience with those environments. While comprehensive automated unit test suites (572+ tests) are in place, real-world edge cases or platform quirks may still surface.
> 
> Community feedback, bug reports, and Pull Requests from experienced users of Cursor and non-Windows platforms are warmly appreciated to help test and harden these integrations!

---

## 📖 Documentation Directory

- ⚙️ [docs/configuration.md](docs/configuration.md): Complete configuration reference for `quench_stack.yaml`.
- 🏛️ [docs/architecture/](docs/architecture/README.md): High-level system architecture (4-tier topology, invariants, module map).
- 🌐 [CHANGELOG.md](CHANGELOG.md): Historical releases and evolution milestones.
- 🤝 [CONTRIBUTING.md](CONTRIBUTING.md): Contribution guidelines and testing instructions.
- ❓ [docs/FAQ.md](docs/FAQ.md): Troubleshooting common environment, path, proxy, and encoding questions.
- 📐 [dev_tasks_mcp_specification.md](dev_tasks_mcp_specification.md): FastMCP Tool & Protocol Specification (tool parameters, field schema, return types).
- 📜 [LICENSE](LICENSE): Mozilla Public License 2.0 (MPL-2.0).

---

## 📄 License

This project is licensed under the [Mozilla Public License 2.0 (MPL-2.0)](LICENSE).  
Modifications to covered core files must remain open-source, while allowing frictionless commercial use and integration with proprietary downstream codebases.
