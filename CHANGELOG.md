# Changelog

All notable changes and architectural evolutions of the **Quench Dev-Orchestrator (`quorch`)** project are documented here.
Unlike real-time specification documents (which reflect only the active design), this changelog tracks historical decisions, problem root causes, and version upgrades.

---

## [2026-09-24] 2026-09-24_ci_matrix_zero_stat_and_test_isolation_fix.md

- **Task 1.1**: 修复 gc_by_filename_order 的 TOCTOU 与零 stat 契约违反，消除测试全局 os.stat 毒化

## [2026-09-24] 2026-09-24_v1.06_step04_manifest_bounds_and_compaction_contract.md

- **Task 4.1**: 清单物理边界防护修复与分代归档契约冻结 (Manifest Bounds Protection & Compaction Contract Phase 0)

## [2026-09-24] 2026-09-23_v1.06_step03_directory_physical_hardening_and_two_way_interlock.md

- **Task 3.1**: FileScopeGuard 路径规范化硬化：跨驱动器与别名逃逸前置断绝 (Path Canonicalization & Cross-Drive Symlink Escape Defense)
- **Task 3.2**: Shell 写入重定向正则拦截与工具通道安全隔离 (Shell Redirection Interception & Write Channel Isolation)
- **Task 3.3**: 任务目录后置权威对账：Git 跟踪平滑迁移与未授权旁路隔离 (Manifest Reconcile, Git-Tracked Onboarding & Bypass Isolation)

## [2026-09-24] 2026-09-23_v1.06_step02_smart_reaper_and_lease_governance.md

- **Task 2.1**: 心跳续约与 Fencing Token 租约校验注入及清单 Fail-Closed 硬化 (Heartbeat Renewal, Fencing Token Lease Verification & Fail-Closed Manifest)
- **Task 2.2**: 智能回收器核心：多维健康探针与配置扩展 (Smart Reaper Multi-Dimensional Health Probe & Policy)
- **Task 2.3**: CAS 幂等回收工具 `dev_tasks_reclaim` 与跨文件锁序仲裁闭环 (CAS Idempotent Reclaim, Cross-File Lock Order & State Machine Gate)

## [2026-09-24] 2026-09-23_v1.06_step01_observability_and_manifest.md

- **Task 1.1**: 引入行聚合落盘 Sink，修复思考流单字分行破碎与测试保真度缺口 (CoalescingTextSink & Realistic Chunk Mock)
- **Task 1.2**: 声明 MCP 上下文并重构自适应心跳为能力分发 + FILE 常驻兜底 (AdaptiveHeartbeatSink Multi-Channel Dispatch & Last-Resort FILE)
- **Task 1.3**: 拓扑自适应观测分流：ObservabilityPolicy 与最终裁决快照通道 (Adaptive Observability & VerdictAuditSink)
- **Task 1.4**: Fencing Token 租约底座与 manifest.json 权威清单 (Fencing Token Lease & Manifest SSOT)
- **Task 1.5**: Reviewer 日志命名原子分配器（YYYYMMDD_NNN_slug 格式、O_EXCL 无状态探测、溢出硬失败、零 stat 字典序 GC）

## [2026-09-24] Consultation Context Guard & Declarative Budget Relaxation (议题一)

- **Task 1.1**: 咨询上下文预算契约同步与声明式配置域校验门 (Context Budget Relaxation, Line Range Syntax & Declarative Clamping)
  - **Declarative Budget & Line Range Slicing**: Introduced `max_total_injection_chars: 40000`, `default_window_lines: 200`, and `max_lines_per_slice: 600` in `ReviewerEngineConfig` with zero vendor lock-in and domain validation (`_coerce_positive_int`, `[512, 200000]`);
  - **Syntax & Windows Path Defense**: Greedily matched `path:start-end` syntax with Windows drive letter (`C:\...`) compatibility and boundary clamping;
  - **Unicode Safe Truncation & Early Short-Circuit**: Enforced global budget cap with string character slicing (no byte tearing), dynamic overhead subtraction, and pre-I/O short-circuit;
  - **Prompt Cache Prefix Preservation**: Preserved 100% byte stability of `build_static_prefix` system prompt with pure user-turn context slice injection;
  - **L1 SSOT Synchronization**: Updated `dev_tasks_mcp_specification.md` (§1.3, §2.5, §5) to eliminate cross-session contract drifts;
  - **308+ Unit Tests**: Added 12 comprehensive unit tests in `test_consultation_context_guard.py` with 100% passing rate.

## [2026-09-23] 2026-09-23_cross_platform_path_guard.md

- **Task 1.1**: 统一跨平台路径穿透防御与路径沙箱规范化 (Unified Cross-Platform Path Guard & Workspace Confinement)

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
