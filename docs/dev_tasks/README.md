# Quench Dev-Orchestrator Task Management

[English](README.md) | [简体中文](README_zh.md)

> This directory follows the **Quench Dual-Model DevTask Management Workflow (Architect Reviewer + Agile Runner)**.  
> All development conventions (status markers, the six core fields, session initiation protocols, architectural review guidelines, DoD verification standards) are defined in the built-in specifications:
> - Core Workflow: [`plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md`](../../plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md)
> - Reviewer Model Guidelines: [`plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`](../../plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md)
> - Coding & Testing Standards: [`plugins/quench-dev-tasks/rules/coding-standards.md`](../../plugins/quench-dev-tasks/rules/coding-standards.md)

---

## Technical Stack & Acceptance Criteria

| Attribute | Requirement |
| :--- | :--- |
| **Tech Stack** | Python (FastMCP) + Antigravity Plugin & Cursor Adapter Layer + CLI Tools |
| **Test Suite** | `$env:PYTHONPATH="plugins/quench-dev-tasks/server"; pytest plugins/quench-dev-tasks/server/tests -v` |
| **Architecture Spec** | [`dev_tasks_mcp_specification.md`](../../dev_tasks_mcp_specification.md) |
| **DoD Standards** | Full unit test suite passes 100% (105+ tests), zero hardcoded local machine paths, cross-platform UTF-8 encoding |

---

## Active DevTask

> Currently there is no task in progress (all stage tasks have been completed and moved to the archive).  
> New tasks can be initiated via `dev_tasks_propose` or guided by stage roadmaps under `docs/roadmap/`.

---

## Archive History

| Archived DevTask | Key Deliverables | Tasks | Status |
| :--- | :--- | :---: | :---: |
| [`archive/2026-09-13_stage3_cross_tool_cursor_adaptation.md`](./archive/2026-09-13_stage3_cross_tool_cursor_adaptation.md) | Cross-tool Cursor adaptation & Quench CLI suite (MDC exporter, chained Git hooks) | 3 | ✔️ 100% Closed |
| [`archive/2026-09-13_stage2_antigravity_community_ready.md`](./archive/2026-09-13_stage2_antigravity_community_ready.md) | Antigravity community release ready (dynamic config, self-healing installer, portal assets) | 4 | ✔️ 100% Closed |
| [`archive/2026-09-13_fix_external_hooks_and_diagnostics.md`](./archive/2026-09-13_fix_external_hooks_and_diagnostics.md) | External project Hook rendering fix & Windows cmd quote protection | 2 | ✔️ 100% Closed |
| [`archive/2026-09-13_stage1_scaffolding_observability_and_migration.md`](./archive/2026-09-13_stage1_scaffolding_observability_and_migration.md) | Observable logging, smooth config migration, template neutralization | 3 | ✔️ 100% Closed |
| [`archive/2026-09-11_governance_engine_and_cross_tool_adaptation.md`](./archive/2026-09-11_governance_engine_and_cross_tool_adaptation.md) | Deep governance engine (session bypass lock + dual-track boundaries) & cross-tool adaptation | 4 | ✔️ 100% Closed |
| [`archive/2026-09-11_plugin_development.md`](./archive/2026-09-11_plugin_development.md) | Full core mechanism development for quench-dev-tasks plugin (Phase 1 ~ 3) | 11 | ✔️ 100% Closed |
