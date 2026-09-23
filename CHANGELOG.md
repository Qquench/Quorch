# Changelog

All notable changes and architectural evolutions of the **Quench Dev-Orchestrator (`quorch`)** project are documented here.
Unlike real-time specification documents (which reflect only the active design), this changelog tracks historical decisions, problem root causes, and version upgrades.

---

## [2026-09-23] 2026-09-21_stage5_vendor_neutrality_and_consultation.md

- **Task 1.1**: 将 DeepSeekClient 重构为厂商中立 ReviewerClient 并抽象通用推理草稿协议探针 (Vendor-Neutral ReviewerClient & Generic CoT Probe)
- **Task 1.2**: 引入 PROVIDER_PRESETS 声明式中立工厂并清除 server.py 厂商硬分支 (Declarative Provider Registry & Branch Removal)
- **Task 1.3**: 建立源码级中立性防回归扫描闸门并重构引擎既有测试为协议中立形态 (Neutrality Regression Gate)
- **Task 2.1**: 实现免任务单绑定的架构咨询原子工具 dev_reviewer_consult (Ad-Hoc Consultation Tool)
- **Task 2.2**: 硬化主模型防角色扮演红线与无引擎显式降级卡片 (Anti-Role-Playing Governance)
- **Task 2.3**: 新增 dev_reviewer_consult 全行为矩阵单测并完成 Stage 5 端到端验收 (Consultation E2E Matrix)

## [2026-09-21] 2026-09-21_model_switching_optimization.md

- **Task 1**: Milestone 0: 独立轻量验证脚本与 Thinking / Prompt Cache 探测
- **Task 2**: Milestone 1: Quench MCP 审查引擎与项目配置解耦接入
- **Task 3**: Milestone 2: 任务规约强化与智能升级工具闭环
- **Task 4**: Milestone 3: 刚性单测门禁与 CLI 终端体检集成
- **Task 5**: Milestone 4: 多层能力自适应交接协议与模型解耦 (Multi-Tier Adaptive Reviewer Handoff Protocol & Model Decoupling)
- **Task 6**: Milestone 5: 极简实时思考流落盘与环境自适应进度心跳 (Minimalist Real-time Thinking Log & Adaptive Progress Heartbeat)
- **Task 7**: Milestone 6: Draft 任务草案态与物理可行性 Lint 闸门 (Draft Task State & Physical Feasibility Lint Gate)
- **Task 8**: Milestone 7: 架构规约同步与端到端自举验证 (Documentation Sync & E2E Validation)
- **feat(optimization)**: Complete model decoupling, ReviewerClient thinking log streaming, adaptive heartbeat, and draft physical feasibility gate
  - **Model Decoupling (`ReviewerClient`)**: Pluggable multi-provider architecture supporting DeepSeek (with streaming reasoning content and Prompt Cache billing detection), OpenAI standard, Ollama local offline, IDE native subagents, and graceful manual fallback;
  - **Minimalist Real-time Thinking Log & Adaptive Heartbeat (`RotatingFileSink` / `AdaptiveHeartbeatSink`)**: Dedicated streaming logs under `.agents/logs/reviewer/` with 1024KB hard cap safe rotation and pre-write redaction across chunk boundaries; ~1.0s low-frequency MCP progress notifications with 100% clean `sys.stdout` JSON-RPC transport;
  - **Draft Task State & Physical Feasibility Lint Gate**: Segregated `📝 草案` state via `dev_tasks_status(include_drafts=False)`; `lint_task_physical_feasibility` enforces path traversal defenses, disk existence checks, overwrite hazard prevention, and pytest dry-run syntax verification; `dev_tasks_promote_draft` filelock atomic promotion;
  - **Full Test Matrix (167/167 Passing)**: 62 new high-precision unit tests, 100% green across Windows and Linux environments.

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
