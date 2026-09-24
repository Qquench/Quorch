# Development Roadmaps Index

> **Overview**:  
> This directory houses the **versioned milestone development roadmaps** actively advancing within current project cycles.  
> Each roadmap plans and breaks down epic-level requirements for a minor version (`v{Major}.{Minor:02d}`), where the minor version number inherently represents the sequential evolution stage of that major epoch.  
> Once a milestone reaches full delivery and closure, its roadmap is archived under `archive/`.  
> 
> For **long-term exploratory proposals and prospective architectural research**, please refer to 🚀 [docs/future_roadmap_ideas.md](../future_roadmap_ideas.md).

---

## Active & Upcoming Version Roadmaps

| Milestone | Roadmap Document | Key Milestones & Themes | Focus Area | Current Status |
| :--- | :--- | :--- | :--- | :---: |
| **Prospective** | 📋 **[2026-09-24_reverse_topology_and_external_runner_roadmap.md](./2026-09-24_reverse_topology_and_external_runner_roadmap.md)** | **Reverse-Topology & External-Runner Governance: Asymmetric Dual-Host Architecture** | Hook-free whitelist sinking (B1), lease heartbeat (B3), dual-process CAS lock (B4), capability tokens & verdict provenance (B7) | 💡 **Planning / Red-Team Review** |

---

## Completed & Archived Milestones

| Milestone | Archived Document | Key Deliverables | Archived Date |
| :--- | :--- | :--- | :---: |
| **v1.06** | ✔️ **[v1.06_microkernel_adaptive_observability_and_governance_interlock.md](./archive/v1.06_microkernel_adaptive_observability_and_governance_interlock.md)** | **Microkernel Elevation: Adaptive Observability, Smart Conditional Reaper & Task Directory Two-Way Interlock**:<br>• Dynamic stream policy (`ObservabilityPolicy`) & verdict snapshot (`VerdictAuditSink`);<br>• Fencing Token CAS task lease reaper & multi-dimensional liveness probe (`reaper.probe`);<br>• Task directory physical protection (`FileScopeGuard` shell redirect/symlink hardening) & `.agents/.quorch/manifest.json` authority two-way interlock;<br>• 443/443 automated unit test suite with 100% green coverage across Linux and Windows. | 2026-09-24 |
| **v1.05** | ✔️ **[v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md](./archive/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md)** | **Vendor-Neutral Reviewer Architecture, Ad-Hoc Consultation (`dev_reviewer_consult`) & Anti-Role-Playing Governance**:<br>• Generic `ReviewerClient` base class with pluggable `PROVIDER_PRESETS` registry & zero core vendor literals;<br>• Automated static neutrality regression scan gate (`test_no_vendor_literals_in_core.py`);<br>• Ad-hoc atomic architectural consultation tool (`dev_reviewer_consult`) with 4 modes (`critique`, `evaluate`, `brainstorm`, `audit`), read-only sandbox guard, and 12,000-char context budget;<br>• Byte-level stable prefix cache (`_PREFIX_CACHE`) & real-time streaming thinking sink (`.agents/logs/reviewer/latest-<session_id>.log`);<br>• Strict anti-roleplaying governance (discipline rules, triage decision tree, degraded fallback cards with empty findings);<br>• 230/230 automated unit test suite with 100% green coverage across Linux and Windows. | 2026-09-23 |
| **v1.04** | ✔️ **[v1.04_automated_subagent_delegation_and_codebase_inspection.md](./archive/v1.04_automated_subagent_delegation_and_codebase_inspection.md)** | **Model Switching Optimization & Multi-Tier Reviewer Decoupling**:<br>• Multi-provider `ReviewerClient` (DeepSeek with thinking/cache detection, OpenAI, Ollama, native Subagent, Manual fallback);<br>• AST `CodeExplorer` & `dev_tasks_refine_spec` specification refinement closed-loop;<br>• `RotatingFileSink` stream logging (1024KB cap) & 1.0s low-frequency progress heartbeat;<br>• `Draft` task state & `lint_task_physical_feasibility` path traversal/pytest dry-run lint gate;<br>• 167/167 full automated unit test suite with 100% green coverage across Linux and Windows. | 2026-09-21 |
| **v1.03** | ✔️ **[v1.03_cross_tool_cursor_adaptation.md](./archive/v1.03_cross_tool_cursor_adaptation.md)** | **Cross-Tool Cursor Adaptation & Quench CLI Suite**:<br>• Cursor MCP automated rendering with safe preservation of existing tools;<br>• Git Pre-commit Guard physical interception with chained append installation;<br>• High-density Cursor Rules / MDC spec exporter (`.cursorrules` and `.cursor/rules/quench-dev-tasks.mdc`);<br>• Unified lightweight terminal CLI (`quench status/check/init/archive`, adaptive ANSI color fallback);<br>• 105/105 full automated unit test suite with 100% green coverage. | 2026-09-13 |
| **v1.02** | ✔️ **[v1.02_antigravity_community_ready.md](./archive/v1.02_antigravity_community_ready.md)** | **Antigravity Community Release & Out-of-the-Box Readiness**:<br>• Eliminated hardcoded machine paths (template-driven config, JSON-safe path escaping);<br>• Cross-platform self-healing installer (`scripts/install.py` with pre-flight check and `--rollback` snapshot recovery);<br>• Neutralized project config templates and decoupled logical roles (Reviewer / Runner);<br>• Open-source community assets (bilingual READMEs, CONTRIBUTING, FAQ, MPL-2.0);<br>• Hardened lifecycle hook contract (`force_ask` physical intercept, Windows Node.js compatibility). | 2026-09-13 |
| **v1.01** | ✔️ **[v1.01_personal_seamless_multiproject.md](./archive/v1.01_personal_seamless_multiproject.md)** | **Seamless Multi-Project Governance & Lifecycle Closure**:<br>• Session lock concurrency hardening (UTC normalization, atomic writes, FileLock protection);<br>• Dual-track boundary engine (smart multi-language unmanaged paths);<br>• Observable hook logging (`SafeRotatingFileHandler` 1MB×3, structured logs, eliminated silent pass);<br>• Smooth config migration (`schema_version: "1.0"`, zero-comment-damage patch writes);<br>• Lightweight scaffolding & health diagnostics (`init_project.py --check`, `quench-init.ps1`). | 2026-09-13 |

---

## Development Lifecycle Protocol

1. **Milestone Roadmap Planning**: Decompose epic-level requirements and architectures in `docs/roadmap/v<Major>.<Minor:02d>_*.md` (e.g. `v1.05_*.md`, `v2.01_*.md`);
2. **DevTask Generation & Confirmation**: Instantiate Epics into `docs/dev_tasks/<date>_<name>.md` via `dev_tasks_propose`;
3. **Architectural Review & Handover**: Frontier reasoning model (Reviewer) audits and approves the task document;
4. **Implementation & Verification**: Agile Runner claims tasks, implements core logic, and verifies via DoD test commands;
5. **Auditing & Archival**: Validate physical code changes and assertions via `dev_tasks_complete`, then archive via `dev_tasks_archive`;
6. **Milestone Closure**: When all epics within a milestone are delivered, move the roadmap into `docs/roadmap/archive/`.
