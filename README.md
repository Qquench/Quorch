# Quench Dev-Orchestrator (`quorch`)

[English](README.md) | [简体中文](README_zh.md)

[![License: MPL-2.0](https://img.shields.io/badge/License-MPL_2.0-blue.svg)](https://opensource.org/licenses/MPL-2.0)
[![Python: >=3.11](https://img.shields.io/badge/python-3.11+-brightgreen.svg)](https://www.python.org/)
[![FastMCP: >=2.0](https://img.shields.io/badge/FastMCP-2.0+-orange.svg)](https://github.com/jlowin/fastmcp)
[![CI](https://github.com/Qquench/Quorch/actions/workflows/ci.yml/badge.svg)](https://github.com/Qquench/Quorch/actions/workflows/ci.yml)

> **Dual-Model Orchestration & Task Governance Suite for AI-Augmented IDEs** (Antigravity, Cursor, Windsurf, Claude Code)  
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
- **Pluggable Multi-Provider Reviewer Engine (`ReviewerClient`)**: Supports direct API connections to DeepSeek (with real-time Thinking streams and Prompt Cache token detection), OpenAI standard endpoints, local offline Ollama, IDE native subagents, and graceful manual fallback.
- **AST Codebase Explorer & Spec Refiner (`dev_tasks_refine_spec`)**: Extracts precise AST symbols and call-chains without dumping whole codebases, automatically upgrading draft specifications into hardened six-field contracts.
- **Observable Thinking Stream & Low-Frequency Heartbeats**: Dedicated streaming logs under `.agents/logs/reviewer/thinking.log` with a 1024KB hard-cap safe rotation, cross-boundary pre-write redaction, and ~1.0s low-frequency progress notifications to keep MCP stdio JSON-RPC transport pristine.
- **Draft Task State & Physical Feasibility Lint Gate (`📝 Draft`)**: Isolates unready architectural ideas; enforces path traversal defenses, physical file existence checks, overwrite hazard prevention, and pytest dry-run syntax verification before task promotion.
- **Physical PreToolUse Guard**: Intercepts any file modifications outside the active task's `【Affected Files】` whitelist, prompting interactive user confirmation before any out-of-scope edit is permitted.
- **Atomic State Machine**: Backed by cross-process `filelock`, strictly enforcing single-active-task execution, preventing multi-subagent race conditions.
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

The `quench-dev-tasks` MCP Server provides a suite of 10 specialized tools:

| Tool | Purpose | Typical Invocation |
| :--- | :--- | :--- |
| `dev_tasks_status` | Query active task overview, queue distributions (`include_drafts`), and hook audit logs | At session startup or after completing milestones |
| `dev_tasks_propose` | Propose new tasks adhering to the six-field schema (`⬜ Pending` or `📝 Draft`) | During architecture planning or backlog triage |
| `dev_tasks_refine_spec` | Refine a task spec with AST codebase symbol analysis & Reviewer reasoning | Upgrading draft tasks into executable contracts |
| `dev_tasks_promote_draft`| Lint physical feasibility (path defenses, dry-run) and promote draft to pending | Promoting verified drafts to the execution queue |
| `dev_tasks_confirm` | Transition task states (`confirm`, `rework`, `skip`, `revoke`) | After Reviewer verification before execution |
| `dev_tasks_checkout` | Check out confirmed tasks and set status to `🔨 In Progress` | Runner claiming the next verified task |
| `dev_tasks_complete` | Complete a task with DoD test output audit (`✔️ Completed`) | Runner upon passing all automated DoD commands |
| `dev_tasks_escalate` | Escalate a stuck task and generate a multi-tier Reviewer Handoff Card | Runner encountering design deadlocks or regressions |
| `dev_tasks_set_bypass`| Activate time-bounded, session-locked fast-track bypass | Light touch edits (e.g. documentation, typos) |
| `dev_tasks_archive` | Archive closed tasks and append to `CHANGELOG.md` | Once all tasks in a file are completed |

## 💡 Project Origin & Note from the Author

> **Note from the Author / Transparency Notice**  
> This project originated from my personal workflow and real-world engineering needs while building software on **Windows using Google Antigravity IDE**. The core state machine, task governance engine, and Antigravity hook integration have been thoroughly developed, battle-tested, and verified locally.
> 
> However, extending this framework to other developer tools (such as **Cursor**, Windsurf, etc.) or cross-platform operating systems was generated by AI models based on the existing architecture abstractions, as I do not have personal development experience with those environments. While comprehensive automated unit test suites (167+ tests) are in place, real-world edge cases or platform quirks may still surface.
> 
> Community feedback, bug reports, and Pull Requests from experienced users of Cursor and non-Windows platforms are warmly appreciated to help test and harden these integrations!

---

## 📖 Documentation Directory

- ⚙️ [docs/configuration.md](docs/configuration.md): Complete configuration reference for `quench_stack.yaml`.
- 🌐 [CHANGELOG.md](CHANGELOG.md): Historical releases and evolution milestones.
- 🤝 [CONTRIBUTING.md](CONTRIBUTING.md): Contribution guidelines and testing instructions.
- ❓ [docs/FAQ.md](docs/FAQ.md): Troubleshooting common environment, path, proxy, and encoding questions.
- 📐 [dev_tasks_mcp_specification.md](dev_tasks_mcp_specification.md): Technical architecture specification.
- 📜 [LICENSE](LICENSE): Mozilla Public License 2.0 (MPL-2.0).

---

## 📄 License

This project is licensed under the [Mozilla Public License 2.0 (MPL-2.0)](LICENSE).  
Modifications to covered core files must remain open-source, while allowing frictionless commercial use and integration with proprietary downstream codebases.
