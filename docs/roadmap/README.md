# Development Roadmaps Index

> **Overview**:  
> This directory houses the **stage-based development roadmaps** actively advancing within current project cycles.  
> Each stage plans and breaks down epic-level tasks, which are subsequently instantiated into task documents under `docs/dev_tasks/`.  
> Once a stage reaches full closure, its roadmap is moved to `archive/`.  
> 
> For **long-term exploratory proposals and prospective architectural research**, please refer to 🚀 [docs/future_roadmap_ideas.md](../future_roadmap_ideas.md).

---

## Active & Upcoming Stage Overview

| Stage | Roadmap Document | Key Milestones & Themes | Focus Area | Current Status |
| :--- | :--- | :--- | :--- | :---: |
| **Stage 5** | 🚀 **[stage5_vendor_neutral_reviewer_and_adhoc_consultation.md](./stage5_vendor_neutral_reviewer_and_adhoc_consultation.md)** | **Vendor-Neutral Reviewer, Ad-Hoc Consultation (`dev_reviewer_consult`) & Anti-Role-Playing Governance** | Clean vendor-specific hardcoding, ad-hoc architectural inquiry without DevTasks, stream thinking sink, and strict anti-impersonation rules | 🔨 **In Progress** |
| **Stage 6** | 📋 **[stage6_microkernel_adaptive_observability_and_governance_interlock.md](./stage6_microkernel_adaptive_observability_and_governance_interlock.md)** | **Microkernel Elevation: Adaptive Observability, Smart Conditional Reaper & Task Directory Two-Way Interlock** | Dynamic stream policy & verdict snapshot, Fencing Token CAS task lease reaper, and physical whitelist + manifest authority two-way interlock | 📋 **Planned** |

---

## Completed & Archived Stages

| Stage | Archived Document | Key Deliverables | Archived Date |
| :--- | :--- | :--- | :---: |
| **Stage 4** | ✔️ **[stage4_automated_subagent_delegation_and_codebase_inspection.md](./archive/stage4_automated_subagent_delegation_and_codebase_inspection.md)** | **Model Switching Optimization & Multi-Tier Reviewer Decoupling**:<br>• Multi-provider `ReviewerClient` (DeepSeek with thinking/cache detection, OpenAI, Ollama, native Subagent, Manual fallback);<br>• AST `CodeExplorer` & `dev_tasks_refine_spec` specification refinement closed-loop;<br>• `RotatingFileSink` stream logging (1024KB cap) & 1.0s low-frequency progress heartbeat;<br>• `Draft` task state & `lint_task_physical_feasibility` path traversal/pytest dry-run lint gate;<br>• 167/167 full automated unit test suite with 100% green coverage across Linux and Windows. | 2026-09-21 |
| **Stage 3** | ✔️ **[stage3_cross_tool_cursor_adaptation.md](./archive/stage3_cross_tool_cursor_adaptation.md)** | **Cross-Tool Cursor Adaptation & Quench CLI Suite**:<br>• Cursor MCP automated rendering with safe preservation of existing tools;<br>• Git Pre-commit Guard physical interception with chained append installation;<br>• High-density Cursor Rules / MDC spec exporter (`.cursorrules` and `.cursor/rules/quench-dev-tasks.mdc`);<br>• Unified lightweight terminal CLI (`quench status/check/init/archive`, adaptive ANSI color fallback);<br>• 105/105 full automated unit test suite with 100% green coverage. | 2026-09-13 |
| **Stage 2** | ✔️ **[stage2_antigravity_community_ready.md](./archive/stage2_antigravity_community_ready.md)** | **Antigravity Community Release & Out-of-the-Box Readiness**:<br>• Eliminated hardcoded machine paths (template-driven config, JSON-safe path escaping);<br>• Cross-platform self-healing installer (`scripts/install.py` with pre-flight check and `--rollback` snapshot recovery);<br>• Neutralized project config templates and decoupled logical roles (Reviewer / Runner);<br>• Open-source community assets (bilingual READMEs, CONTRIBUTING, FAQ, MPL-2.0);<br>• Hardened lifecycle hook contract (`force_ask` physical intercept, Windows Node.js compatibility). | 2026-09-13 |
| **Stage 1** | ✔️ **[stage1_personal_seamless_multiproject.md](./archive/stage1_personal_seamless_multiproject.md)** | **Seamless Multi-Project Governance & Lifecycle Closure**:<br>• Session lock concurrency hardening (UTC normalization, atomic writes, FileLock protection);<br>• Dual-track boundary engine (smart multi-language unmanaged paths);<br>• Observable hook logging (`SafeRotatingFileHandler` 1MB×3, structured logs, eliminated silent pass);<br>• Smooth config migration (`schema_version: "1.0"`, zero-comment-damage patch writes);<br>• Lightweight scaffolding & health diagnostics (`init_project.py --check`, `quench-init.ps1`). | 2026-09-13 |

---

## Development Lifecycle Protocol

1. **Stage Roadmap Planning**: Decompose epic-level requirements and architectures in `docs/roadmap/stage<N>_*.md`;
2. **DevTask Generation & Confirmation**: Instantiate Epics into `docs/dev_tasks/<date>_<name>.md` via `dev_tasks_propose`;
3. **Architectural Review & Handover**: Frontier reasoning model (Reviewer) audits and approves the task document;
4. **Implementation & Verification**: Agile Runner claims tasks, implements core logic, and verifies via DoD test commands;
5. **Auditing & Archival**: Validate physical code changes and assertions via `dev_tasks_complete`, then archive via `dev_tasks_archive`;
6. **Stage Closure**: When all epics within a stage are delivered, move the stage roadmap into `docs/roadmap/archive/`.
