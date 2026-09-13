# Changelog

[English](CHANGELOG.md) | [简体中文](CHANGELOG_zh.md)

All notable changes and architectural evolutions of the **Quench Dev-Orchestrator (`quorch`)** project are documented here.
Unlike real-time specification documents (which reflect only the active design), this changelog tracks historical decisions, problem root causes, and version upgrades.

---

## [0.1.0] - 2026-09-13 (Initial Public Release)

### 🚀 Cross-Tool Cursor Adaptation & Lightweight CLI Suite (Stage 3)
- **Automated Cursor MCP Setup with Collision Protection**: Added `--ide {antigravity,cursor,all}` flag to `init_project.py` and `install.py`. Automatically generates and safely merges `.cursor/mcp.json` without overwriting existing user-configured MCP servers.
- **Physical Git Pre-commit Guard Hook**: Implemented zero-dependency physical interception hook `scripts/git_pre_commit_guard.py`. Added `--install-git-hook` with chained append support to `.git/hooks/pre-commit`, preventing unauthorized out-of-scope commits in non-hook environments (Cursor, Windsurf, Claude Code, vanilla Git).
- **Rules Exporter & MDC Spec Generator**: Implemented `rules_exporter.py` to distill runtime governance rules into `.cursorrules` and modern Cursor MDC format (`.cursor/rules/quench-dev-tasks.mdc`).
- **Unified Terminal CLI (`quorch`)**: Added lightweight standalone CLI `cli.py` providing `status` dashboard, `check` environment diagnostics, `init` project onboarding, and `archive` task retirement with adaptive ANSI color fallbacks.
- **Comprehensive Test Suite (105/105 Passing)**: Added 22 dedicated test cases verifying cross-tool workflows, path defenses, and CLI commands.

### 🌐 Antigravity Community Readiness & Platform Hardening (Stage 2)
- **Eliminated Hardcoded Local Paths**: Decoupled all machine paths using dynamic project root detection (`os.path.dirname(os.path.abspath(__file__))`).
- **Cross-Platform Self-Healing Installer**: Implemented `scripts/install.py` with pre-flight safety audits (file handle lock detection, Windows MAX_PATH check) and automated `--rollback` snapshot recovery.
- **Decoupled Roles & Model Neutrality**: Abstracted the Reviewer role to an environment-neutral concept, allowing developers to allocate any flagship reasoning model without hardcoding model versions.
- **Physical Lifecycle Interception (`force_ask`)**: Upgraded AntigravityAdapter decision contract from `ask` to `force_ask`, penetrating IDE permission caches to guarantee human confirmation dialogs on out-of-scope modifications.
- **Open-Source Community Assets**: Prepared bilingual documentation (`README.md`, `CONTRIBUTING.md`, `FAQ.md`), GitHub Actions CI pipeline across Ubuntu and Windows, and MPL-2.0 open-source licensing.

### 🛡️ Multi-Project Governance & Observable Hook Engine (Stage 1)
- **Hardened Session Lock Concurrency**: Standardized on UTC-aware timestamps, atomic file writes, and `filelock.FileLock` protection to prevent concurrent Markdown corruptions.
- **Dual-Track Boundary Engine**: Implemented smart multi-language unmanaged path heuristics (automatically exempting documentation, media, and build artifacts from rigid task tracking).
- **Observable Hook Logging**: Built `SafeRotatingFileHandler` (1MB × 3 rotation) with resilience against Windows multi-process permission conflicts, recording structured decision events.
- **Smooth Configuration Migration**: Implemented `schema_version: "1.0"` with non-destructive patch writing to preserve user comments during YAML upgrades.
- **Scaffolding & Health Diagnostics**: Added `init_project.py` and PowerShell launcher `quench-init.ps1` for one-command onboarding.

### 🧊 Core Architecture & MCP Foundation
- **7 FastMCP Tools**: `dev_tasks_status`, `dev_tasks_propose`, `dev_tasks_confirm`, `dev_tasks_checkout`, `dev_tasks_complete`, `dev_tasks_escalate`, `dev_tasks_archive`.
- **The Six-Core-Field Schema Validator**: Mandatory validation of `[Affected Files]`, `[Root Cause & Target]`, `[Type Contracts]`, `[Step-by-Step Instructions]`, `[Defensive & Edge Checks]`, and `[DoD Verification Commands]`.
- **Dual-Model Collaboration Paradigm**: Strategic architectural reasoning by the Reviewer model paired with agile implementation and verified DoD execution by the runner model.
