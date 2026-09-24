# Changelog

All notable changes and architectural evolutions of the **Quench Dev-Orchestrator (`quorch`)** project are documented here.
Unlike real-time specification documents (which reflect only the active design), this changelog tracks historical decisions, problem root causes, and version upgrades.

## [2026-09-25] 2026-09-24_v1.08_step02_lease_heartbeat_and_dual_process_cas.md

- **Task 2.1**: 隐式与显式租约心跳刷新及工作区沉浸防杀探针 (External Lease Heartbeat & Active Modifying Immersion Anti-Kill Probe)
  - Implemented high-level `touch_lease_heartbeat` and `is_workspace_actively_modifying` APIs in `manifest_lease.py`;
  - Injected immersion anti-kill probe into `reaper.py::probe_lease_health` to downgrade `STALE_SUSPECT` to `HEALTHY` when workspace files are actively modified.
- **Task 2.2**: 锁内重读 CAS (Read-Under-Lock CAS) 与双进程并发加固 (Read-Under-Lock CAS & Dual-Process Hardening)
  - Added `RetryableManifestError` and `ManifestConflictError` isolated from fatal `ManifestIntegrityError`;
  - Implemented `mutate_manifest_under_lock` generic transaction helper with re-entrancy deadlock guard, fresh-fd disk read, and underlying CAS detection;
  - Refactored `commit_lease`, `compare_and_swap`, `release_lease`, `touch_heartbeat`, and `register_proposal` through unified transaction helper.
- **Task 2.3**: 租约心跳与防杀探针失败语义、绑定校验与全量回归加固 (Heartbeat Failure Semantics & Binding Hardening)
  - Hardened `session_id ∧ holder_token ∧ generation` binding contract;
  - Added traversal path silent filtering, fail-safe conservative alive on all stat failures, max_scan truncation, and cold-start parent directory mtime fallback.
- **Task 2.4**: CAS 事务的异常安全、冲突语义与双进程测试确定性加固 (CAS Transaction Exception Safety & Deterministic Dual-Process Concurrency)
  - Verified exception safety ensuring disk state and hash are completely untouched on mutator failure;
  - Added `multiprocessing.Barrier` dual-process concurrent lease competition tests with strict single winner and zero dirty write assertions;
  - Validated same-directory temporary file placement for cross-platform atomic replacement.

## [2026-09-25] 2026-09-24_v1.08_step01_probe_and_scope_reconciliation.md

- **Task 1.1**: 客户端能力独立探针脚本与兼容性基线建立 (Client Capability Standalone Probe & Compatibility Baseline)
  - Implemented zero-dependency `probe_client_capabilities.py` script for stdio/HTTP/SSE MCP handshake probing;
  - Added baseline export with atomic tempfile replacement and circuit breaker timeout logic;
  - Documented client probe matrix and sampling breaker rules in `docs/ci_incident_tracker_and_compatibility_guide.md`.
- **Task 1.2**: 检出基线快照与工作树对账物理熔断门禁 (Checkout Baseline Snapshot & Scope Reconciliation Circuit Breaker)
  - Implemented `capture_baseline`, `load_baseline_snapshot`, and pure function `reconcile_workspace_against_whitelist` in `manifest.py`;
  - Injected physical `_verify_scope_reconciliation` check into `state_machine.py` before task completion;
  - Automated baseline snapshot capture on `dev_tasks_checkout`.
- **Task 1.3**: 跨平台工作树路径规范化与白名单子集校验 (Cross-Platform Path Normalization & Whitelist Subset Validation)
  - Added `canonicalize_path`, `comparison_key`, and `is_within_whitelist` with platform-aware case folding and recursive glob support in `path_guard.py`;
  - Built comprehensive unit test suite in `test_external_runner_scope_reconciliation.py`.

## [2026-09-24] 2026-09-24_v1.07_step02_decoupling_and_handoff.md

- **Task 2.1**: Reviewer 引擎配置厂商彻底解耦与明文密钥防御 (Reviewer Config Vendor Decoupling & Plaintext Secret Defense)
  - Decoupled `quench_stack.yaml` default provider to `"none"` with `quench_stack.sample.yaml` template;
  - Added `.agents/quench_stack.local.yaml` deep merge overlay and automated plaintext secret detection (`ConfigError`).
- **Task 2.2**: 交接卡片单一生成源抽取与 dev_tasks_export_handoff_card 工具开放 (SSOT Handoff Card & Export Tool)
  - Implemented pure function `render_handoff_card` in `handoff_card.py` with GFM alerts and collapsible task context;
  - Registered `dev_tasks_export_handoff_card` FastMCP tool (12 tools total).
- **Task 2.3**: 同模型自我验证软预警机制与审查透明度增强 (Same-Model Self-Verification Advisory Warning)
  - Added optional `runner_profile` configuration in `project_config.py` with model alias normalization;
  - Injected `reviewer_identity` and non-blocking `self_verification_warning` into consultation response.
- **Documentation Refinement & Path Consolidation**:
  - Moved `docs/architecture.md` into `docs/architecture/README.md` to eliminate file/directory path collision;
  - Cleaned up Chinese heading text in §3.2 interception diagram and established authoritative §3.4 Bilingual Task Specification Field Mappings table;
  - Synchronized pointers in `AGENTS.md`, `README.md`, `README_zh.md`, and roadmap artifacts.

## [2026-09-24] 2026-09-24_v1.07_step01_architecture_doc_integrity.md

- **Task 1.1**: 修复 docs/architecture.md 架构锚点失真与模块映射完整性 (Architecture Doc Anchor Integrity & Module Topology Sync)
- **Task 1.2**: 消除根 AGENTS.md 与 templates/AGENTS.md 孪生源漂移风险 (Twin-Source AGENTS.md Invariants Synchronization)
- **Task 1.3**: 项目官方定位术语规范化对齐（Enforcement-First 物理执法先行）(Terminology Alignment: Enforcement-First Dual-Model Governance)
  - Upgraded project tagline to **"Enforcement-First Dual-Model Governance for AI Coding Agents"** (中译："AI 编程智能体的物理执法先行双模型治理引擎");
  - Enforced dual-track subtitle: *"Physical enforcement where hooks are available; high-tension prompt discipline where they are not."* (有钩子处物理硬管控，无钩子处高张力提示词纪律);
  - Aligned `README.md`, `README_zh.md`, `AGENTS.md`, and `docs/architecture.md`.

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
