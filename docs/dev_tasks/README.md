# Quench Dev-Orchestrator Task Management

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
| **DoD Standards** | Full unit test suite passes 100%, zero hardcoded local machine paths, cross-platform UTF-8 encoding |

---

## Active & Archived Tasks

- **Active Tasks**: Tracked in current task documents in this directory (e.g. `2026-09-XX_*.md`).
- **Archived Tasks**: Completed tasks are archived in [`archive/`](./archive/) and automatically indexed in [`CHANGELOG.md`](../../CHANGELOG.md).
- **Inspecting Status**: Run `quench status` or invoke `dev_tasks_status` to view real-time state.
