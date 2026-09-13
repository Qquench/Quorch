# Development Roadmaps Index

[English](README.md) | [简体中文](README_zh.md)

> **Overview**:  
> This directory houses the **stage-based development roadmaps** actively advancing within current project cycles.  
> Each stage plans and breaks down epic-level tasks, which are subsequently instantiated into task documents under `docs/dev_tasks/`.  
> Once a stage reaches full closure, its roadmap is moved to `archive/`.  
> 
> For **long-term exploratory proposals and prospective architectural research**, please refer to 🚀 [future_roadmap/](../../future_roadmap/README.md).

---

## Active & Upcoming Stage Overview

| Stage | Roadmap Document | Key Milestones & Themes | Focus Area | Current Status |
| :--- | :--- | :--- | :--- | :---: |
| **Stage 4** | 🚀 **TBD** | **Next Evolution Planning** | See [future_roadmap/](../../future_roadmap/README.md) for prospective architectural proposals | 💡 **In Planning** |

---

## Completed & Archived Stages

| Stage | Archived Document | Key Deliverables | Archived Date |
| :--- | :--- | :--- | :---: |
| **Stage 1** | ✔️ **[stage1_personal_seamless_multiproject.md](./archive/stage1_personal_seamless_multiproject.md)** | **Seamless Multi-Project Governance & Lifecycle Closure**:<br>• Session lock concurrency hardening (UTC normalization, atomic writes, FileLock protection);<br>• Dual-track boundary engine (smart multi-language unmanaged paths);<br>• Observable hook logging (`SafeRotatingFileHandler` 1MB×3, structured logs, eliminated silent pass);<br>• Smooth config migration (`schema_version: "1.0"`, zero-comment-damage patch writes);<br>• Lightweight scaffolding & health diagnostics (`init_project.py --check`, `quench-init.ps1`). | 2026-09-13 |
| **Stage 2** | ✔️ **[stage2_antigravity_community_ready.md](./archive/stage2_antigravity_community_ready.md)** | **Antigravity Community Release & Out-of-the-Box Readiness**:<br>• Eliminated hardcoded machine paths (template-driven config, JSON-safe path escaping);<br>• Cross-platform self-healing installer (`scripts/install.py` with pre-flight check and `--rollback` snapshot recovery);<br>• Neutralized project config templates and decoupled logical roles (Reviewer / Runner);<br>• Open-source community assets (bilingual READMEs, CONTRIBUTING, FAQ, MPL-2.0);<br>• Hardened lifecycle hook contract (`force_ask` physical intercept, Windows Node.js compatibility). | 2026-09-13 |
| **Stage 3** | ✔️ **[stage3_cross_tool_cursor_adaptation.md](./archive/stage3_cross_tool_cursor_adaptation.md)** | **Cross-Tool Cursor Adaptation & Quench CLI Suite**:<br>• Cursor MCP automated rendering with safe preservation of existing tools;<br>• Git Pre-commit Guard physical interception with chained append installation;<br>• High-density Cursor Rules / MDC spec exporter (`.cursorrules` and `.cursor/rules/quench-dev-tasks.mdc`);<br>• Unified lightweight terminal CLI (`quench status/check/init/archive`, adaptive ANSI color fallback);<br>• 105/105 full automated unit test suite with 100% green coverage. | 2026-09-13 |

---

## Development Lifecycle Protocol

1. **Stage Roadmap Planning**: Decompose epic-level requirements and architectures in `docs/roadmap/stage<N>_*.md`;
2. **DevTask Generation & Confirmation**: Instantiate Epics into `docs/dev_tasks/<date>_<name>.md` via `dev_tasks_propose`;
3. **Architectural Review & Handover**: Frontier reasoning model (Reviewer) audits and approves the task document;
4. **Implementation & Verification**: Agile Runner claims tasks, implements core logic, and verifies via DoD test commands;
5. **Auditing & Archival**: Validate physical code changes and assertions via `dev_tasks_complete`, then archive via `dev_tasks_archive`;
6. **Stage Closure**: When all epics within a stage are delivered, move the stage roadmap into `docs/roadmap/archive/`.
