# Changelog

All notable changes and architectural evolutions of the **Quench Dev-Orchestrator (`quorch`)** project are documented here.
Unlike real-time specification documents (which reflect only the active design), this changelog tracks historical decisions, problem root causes, and version upgrades.

## [2026-10-10] 2026-10-10_v1.23.1_minimal_slimming_patch.md

- **Task 23.6**: v1.23.1 极简收敛补丁：硬上限解耦、估计量定锚与退役残留清零 (Minimal Slimming Patch & Hard Limit Decoupling)
  - 解耦文档机械硬字节上限（取消 `test_doc_size_budget_ratchet` 9000B/3500B 断言并清理孤儿 `from typing import Final` 引用，反膨胀全面由审查纪律与 Git 审计链 A6 承接，留存 v1.23.1 时点基线快照：`dev-tasks-discipline.md`: 8,335 字节，`AGENTS.md`: 2,752 字节）；
  - 实证耗时估计量严格定锚 `statistics.median` 并补齐 fail-closed 边界单测验证；
  - 发现式彻底清零活跃引导、技能规则、配置模板中已退役的 `dev_reviewer_consult` 词条残留，全仓工具面统一标定为 16 个；
  - 源码实证 `_auto_reclaim_stale_leases` 在取锁前安全执行与无死锁保证。

## [2026-10-10] 2026-10-10_v1.23_step23.b_legacy_residue_retirement_and_dynamic_envelope.md

- **Task 23.4**: 历史化石资产归档、扫描器冻结基线解耦与悬空引用归零 (Legacy Residue Retirement & Scanner Decoupling)
- **Task 23.5**: Tier-2 动态性能信封单向下移收敛与双向假红防护 (Dynamic Envelope Convergence & False-Red Guards)

## [2026-10-10] 2026-10-10_v1.23_step23.a_foundation_compaction_and_fossil_decoupling.md

- **Task 23.1**: 化石门禁完全退役、自锁解锁与 v1.22 路线图归档
- **Task 23.2**: 规则文档促缩硬断言与机械性条款下沉
- **Task 23.3**: MCP 提示垫片退役与超时租约内聚回收 (17 -> 16)

## [2026-10-09] 2026-10-09_v1.22_step22.5_rebaseline_and_milestone_exit.md

- **Task 22.5**: v1.22 全量再基线收尾与里程碑退出检查 (Rebaseline & Milestone Exit Gate)

## [2026-10-09] 2026-10-09_v1.22_step22.2_dual_lease_primitives_slimming.md

- **Task 22.2**: 双 lease 独立失效域隔离与 fail-closed 契约门禁 (Dual Lease Isolation & Fail-Closed Contract Gate)

## [2026-10-09] 2026-10-09_v1.22_step22.1_emerged_vacuity_and_evidence_gate.md

- **Task 22.1**: Emerged 候选空集负向断言与证据闭合门禁 (Emerged Vacuity & Evidence Closed Gate)

## [2026-10-09] 2026-10-09_v1.22_step22.4a_tool_surface_snapshot_and_triplet_gate.md

- **Task 22.4a**: ToolSurface 快照生成与机械三元组去重证据门禁 (ToolSurface Snapshot & Mechanical Triplet Dedup Evidence Gate)

## [2026-10-09] 2026-10-09_v1.22_step22.0_evidence_consumption_and_instantiation_adjudication.md

- **Task 22.0**: v1.22 证据消费门禁与 PROVISIONAL 步骤实例化裁决 (Entry Gate & Evidence-Consumption Instantiation Adjudication)

## [2026-10-09] 2026-10-09_v1.21_step21.4_tier2_calibration_and_milestone_recertification.md

- **Task 21.4**: Tier-2 度量校准修订、跨版本预算信封与里程碑结项再认证 (TR-4 落地 · 终审定稿版)

## [2026-10-09] 2026-10-08_v1.21_step21.3_test_suite_duration_baseline_freeze_and_tier1_curation.md

- **Task 21.3**: 测试套件耗时基线冻结与 Tier-1/Tier-2 精准策展（TR-3 落地，三层阈值语义显式化 + 抗抖动方差守卫 + 测量自递归物理隔离 + 并发不变量硬门禁 H 互斥不变）［R3 架构审查终版］

## [2026-10-09] 2026-10-08_v1.21_step21.2_asset_inventory_test_unitization_and_io_deamplification.md

- **Task 21.2**: 资产扫描测试单元化隔离与 I/O 去放大（TR-2 落地，TP-2/TP-4 真仓唯一 anchor + 混合夹具，单次真仓扫描预算约束）［R4 终审放行核准版］

## [2026-10-09] 2026-10-08_v1.21_step21.1_ast_architecture_hygiene_consolidation.md

- **Task 21.1**: AST 架构卫生门禁归并（TR-1 落地，先取证后剪枝的 TP-1/TP-3 物理奇偶证明）［R4.1 终审放行版］

## [2026-10-09] 2026-10-08_v1.21_step21.0_asset_rebaseline_and_delta_report.md

- **Task 21.0**: 架构资产再基线与 v1.20→v1.21 差异报告（只读取证，落地 TP-4 与 §4.1 握手规范）

## [2026-10-07] 2026-10-07_v1.20_step10_test_tiering_and_retirement_unification.md

- **Task 1**: 测试分级执行规范与退役账本归一（落地 §1.6、pyproject 配置、conftest 集中打标与真值门禁硬加固）

## [2026-10-07] 2026-10-07_v1.20_step09c_reviewer_poll_progress_slimming.md

- **Task 1**: dev_reviewer_poll 进度桥奥卡姆削减（保留热旋修复，带外发射去机器化）

## [2026-10-07] 2026-10-07_v1.20_step09b_reviewer_poll_progress_bridge.md

- **Task 1**: dev_reviewer_poll 长轮询进度桥（MCP Progress Notification，best-effort）

## [2026-10-07] 2026-10-07_hotfix_ci_process_tree_isolation.md

- **Task 1**: CI 进程树回收跨平台隔离加固与 canary 防自杀 + 隔离性正向断言

## [2026-10-07] 2026-10-06_v1.20_step09_audit_gate_matrix_convergence.md

- **Task 1**: 审计门禁矩阵收敛（终审定稿版）：别名化 tail_window_exhausted、全局单点 effective_on_degraded、死字段退役、最严优先安全单调性与门禁契约锚定

## [2026-10-07] 2026-10-04_v1.20_step08_module_consolidation_and_shim_cleanup.md

- **Task 1**: 模块合并与垫片清理：合并 reporting 相关模块至 reporting.py，收敛双分支导入垫片与 budget_ms 废弃参数，闭环全仓零悬空引用与 daemon launch canary 门禁

## [2026-10-07] 2026-10-04_hotfix_crlf_and_gitattributes.md

- **Task 1**: 修复架构清单 CRLF 污染、落地 .gitattributes 换行契约与生成器加固

## [2026-10-07] 2026-10-03_v1.20_step07_session_log_single_domain_and_reaper_dismantle.md

- **Task 1**: Session 日志单域化与 reaper.py 拆解：原子迁移 reclaim_stale_task 至 manifest_lease，清理日志 GC 垫片与文档漂移

## [2026-10-07] 2026-10-03_v1.20_step06_workspace_lease_hardening.md

- **Task 1**: workspace_lease 单机硬化：删除探针与心跳线程，落地 TTL + generation CAS + 显式 touch 崩溃回收（Reviewer R1 修订）

## [2026-10-07] 2026-10-03_v1.20_step05_reviewer_jobs_convergence.md

- **Task 5.0**: step05 Reviewer 作业状态机收敛与模式协议剃刀化（Reviewer 修订版 R2）

## [2026-10-07] 2026-10-03_v1.20_step04_reconcile_perf_rework.md

- **Task 4.0**: step04 性能重做：工作区对账去时钟化（确定性哈希预算 + 快慢路径筛选 + mtime对抗）

## [2026-10-07] 2026-10-03_v1.20_step03_rule_doc_dedup.md

- **Task 3.0**: step03 瘦身归位：规则文档与规范去重（SSOT 单语正文 + 标题双语，含语义无损物理门禁）

## [2026-10-07] 2026-10-03_v1.20_step02_config_tolerance_and_versioning.md

- **Task 2.0**: step02 瘦身归位：配置版本门与未知键容错（修正 C-1/H-1/H-2 终局硬化版）

## [2026-10-07] 2026-10-03_v1.20_step01.1_asset_inventory_dev_tasks_isolation.md

- **Task 1.1**: step01.1 资产扫描器隔离治理与任务单噪声排除（DOC_NON_CONSUMER_PREFIXES）

## [2026-10-07] 2026-10-02_v1.20_step01_architecture_asset_inventory.md

- **Task 1.0**: v1.20 step01（修订版）：架构资产取证与消费者依赖图谱（P0，只读）

## [2026-10-02] 2026-10-02_v1.10_step03_job_record_cascade_reaper.md

- （无独立任务条目或全部跳过）

## [2026-10-02] 2026-09-30_v1.10_step01_pre_confirm_audit_gate.md

- **Task 1.1**: 引入 Pre-Confirm 审计策略门禁（AuditGatePolicy，非不变式，Tier-1 受管路径生效）〔R11 终审闭合版〕

## [2026-10-01] 2026-10-01_v1.10_step02_reviewer_supervisor_hardening.md

- **Task 1.1**: 配额裁决持久闭环：pin 生命周期、跨进程存活生产者与保护集 SSOT 统驭
- **Task 1.2**: 统一纯净异步主通路：三态判别联合契约、沙箱截断前置与全量文档 SSOT 同步

## [2026-10-01] 2026-10-01_ci_fix_reviewer_client_available.md

- **Task 1**: 修复 CI 本地端点可用性断言与状态机临时文件范围核对隔离

## [2026-10-01] 2026-10-01_fix_reviewer_observability_mock_url.md

- **Task 1**: 修复 test_reviewer_observability 模拟测试中的 base_url 与 dummy 模型名称

## [2026-10-01] 2026-10-01_retire_python311_compatibility.md

- **Task 1**: 提升 Python 最低支持基线至 3.12 并退役 3.11 语法守卫

## [2026-10-01] 2026-10-01_retire_python311_compatibility.md

- **Task 1**: 提升 Python 最低支持基线至 3.12+ 并物理退役 3.11 语法守卫与 CI 轴，彻底解放 PEP 701 语法约束

## [2026-10-01] 2026-09-30_bilingual_error_messages.md

- **Task 1.1**: 升级 project_config.py 中的错误与告警信息为双语/英文版

## [2026-10-01] 2026-09-30_remove_vendor_presets.md

- **Task 1.1**: 移除 project_config.py 中的厂商预注册表、默认模型与别名映射，实现纯声明式配置

## [2026-09-30] 2026-09-30_fix_negative_self_test_on_py311.md

- **Task 1.1**: 兼容 Python 3.11 原生解析器对负向用例 SyntaxError 的直接抛出行为

## [2026-09-30] 2026-09-30_fix_py311_fstring_backslash_ci.md

- **Task 1.1**: 修复 consultation.py f-string 反斜杠语法错误并补齐最低 Python 3.11 版本兼容守护

## [2026-09-30] 2026-09-30_v1.09_step03_multihop_need_files_guardrails.md

- **Task 3.1**: NEED-FILES 多跳护栏（数据门控 + reasoning 剥离 + 累积预算 + 400 幂等回退）

## [2026-09-30] 2026-09-30_v1.09_step02_prompt_cache_stability_gradient.md

- **Task 2.1**: PromptAssembler 四段式稳定梯度布局与架构文档路径修正

## [2026-09-30] 2026-09-30_v1.09_step01_cache_telemetry_and_rolling_retention.md

- **Task 1.1**: SSE 空闲看门狗消费者侧实施契约、可注入 Reader 接缝显式化与长流零回归护栏
- **Task 1.2**: cache_telemetry.jsonl 滚动保留生命周期与哈希非泄露
- **Task 1.3**: ReviewerBadRequestError 跨路径统一契约（stream + acomplete）与既有断言迁移

## [2026-09-30] 2026-09-24_v1.08_step03_capability_tokens_and_onboarding.md

- **Task 3.3**: 外部执行器接入规范与 SKILL.md 全面更新（主交付）
  - Authored comprehensive onboarding guide `docs/guides/external-executor-onboarding.md` covering runtime preparation, dual MCP entries configuration contract (`quench-runner` / `quench-reviewer`), stdio channel purity (INV-4), governance lifecycle (Steps 01~05), and anti-forgery defenses;
  - Added Section 6 to `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` specifying capability isolation, dual MCP entries, and non-security boundary declaration adhering to language mirroring contract;
  - Added machine-checkable documentation contract test `test_onboarding_doc_contract.py` validating zero tool reference drift across all 17 registered MCP tools, code block syntax validity, and zero credential/private path leakage;
  - Added anti-forgery regression test `test_forgery_prevention_contract.py` asserting degraded status, `self_verification_warning`, and empty findings (`findings == ""`, INV-3) when Reviewer engine is unconfigured or homogeneous.
- **Task 3.4**: Reviewer 心跳自适应降频与前台上报通道修复
  - Replaced dead fields `mcp_context` and `stderr` in `AdaptiveHeartbeatSink` with explicit `progress_emit` callback for FastMCP progress reporting;
  - Implemented adaptive stepped backoff `_should_emit` with 5s keepalive floor and token delta gating;
  - Covered in `test_reviewer_heartbeat.py` and `test_reviewer_heartbeat_format.py`.

## [2026-09-26] 2026-09-26_v1.08_step06_fix_timeout_flaky_ci.md

- **Task 6.1**: 消除超时熔断测试的紧约束时钟断言并闭环 CI Flaky 事故档案
  - Loosened brittle wall-clock assertion `assert elapsed < 2.5` to loose guard `assert elapsed < 5.0` in `test_timeout_breaker_returns_degraded_and_keeps_partial_log`, preventing intermittent CI failures on loaded multi-tenant virtual runners;
  - Decoupled behavior correctness invariants (degraded status, timeout reason, zero fabricated findings, partial log preservation) from physical scheduling jitter;
  - Documented CI Incident `INC-20260925-02` in `docs/ci_incident_tracker_and_compatibility_guide.md` with Case 8 and defensive coding Guideline 7 (asynchronous timeout assertion guard).

## [2026-09-25] 2026-09-25_v1.08_step05_fix_posix_lease_ctypes_ci.md

- **Task 5.1**: 修复 Windows 分支单测在 POSIX 平台因 ctypes.windll 缺失引发的 AttributeError 并闭环 CI 事故档案
  - Added `create=True` to `unittest.mock.patch("ctypes.windll", ...)` in `test_windows_api_exit_code_scenarios` preventing unhandled `AttributeError` on POSIX hosts;
  - Added cross-platform anti-residue assertion `test_windll_patch_leaves_no_residue` ensuring clean tear-down of mock attributes;
  - Documented CI Incident `INC-20260925-01` in `docs/ci_incident_tracker_and_compatibility_guide.md` with Case 7 and defensive coding Guideline 6 (platform-specific attribute mocking).

## [2026-09-25] 2026-09-25_v1.08_step04_corrections.md

- **Task 4.2**: 租约可判定性与并发安全硬化（心跳 fail-stop、TTL+Fencing 夺权、touch 枚举语义与破坏性门禁）
  - Strengthened `WorkspaceLeaseGuard` heartbeat fail-stop semantics, rejecting stale generations on renewals;
  - Hardened TTL expiry check and fencing generation takeover with atomic filelock;
  - Replaced ambiguous boolean truthiness on touch with explicit `TouchOutcome` enum;
  - Added destructive pre-flight gate on lease takeovers.
- **Task 4.3**: 双源状态一致性收口：JobRecord 单一 SSOT、durable write 与终态 allowlist
  - Unified `JobRecord` as sole authoritative state representation on disk (`.agents/logs/reviewer/jobs/`);
  - Added `_durable_write_json` with fsync and cross-platform atomic rename for all job transitions;
  - Implemented automatic idempotent self-healing reconciliation from `JobRecord` to `verdicts.jsonl`;
  - Enforced `TERMINAL_RESULT_ALLOWED_FIELDS` filtering raw reasoning and CoT leaks while preserving required consultation outputs.
- **Task 4.4**: Reviewer 出口单一化与旁路调用静态强制
  - Enforced single provider network egress invariant (INV-9) with `check_no_api_bypass.py` static AST scan gate;
  - Added CLI pre-flight diagnostic entry `quorch reviewer debug` (and `quorch check --engine`);
  - Replaced ad-hoc raw API scripts with standard MCP and CLI interfaces.
- **Task 4.5**: 异步心跳格式 SSOT 贯通、Poll 紧凑信封/纯文本投射、统一纯英文展示与无效推送彻底清除
  - Implemented pure function `format_heartbeat_line` SSOT returning `[Reviewer thinking: {tokens} tokens | {elapsed_s:.1f}s]`;
  - Added `raw_text=True` non-terminal poll projection directly returning clean single-line strings in FastMCP text blocks;
  - Added `wait_max_s` long polling (0–25s) suspending execution until status transitions;
  - Cleaned up obsolete push channels in `AdaptiveHeartbeatSink` and aligned with Pull Model.

## [2026-09-25] 2026-09-25_v1.08_step04_async_reviewer_jobs.md

- **Task 4.0**: Reviewer Workspace 进程互斥底座与跨进程存活性判定 (Reviewer Workspace Mutex & Cross-Process Liveness)
  - Implemented `WorkspaceLeaseGuard` in `workspace_lease.py` based on atomic `filelock` and heartbeat lease metadata (`.agents/logs/reviewer/workspace.lease.json`) ensuring single active reviewer service process per workspace;
  - Decoupled heartbeat renewal into a dedicated `LeaseHeartbeatThread` daemon thread, preventing lease expiration during long synchronous reasoning turns;
  - Built cross-platform `probe_peer` liveness detection supporting POSIX `EPERM` alive handling, PID reuse nonce mismatch conservative rejection, and Windows `GetExitCodeProcess` with `STILL_ACTIVE` verification;
  - Covered full lifecycle, mutex preemption, and edge cases in `test_workspace_lease.py`.
- **Task 4.1**: Reviewer 异步长推演任务制（Submit / Poll / Cancel）与 1KB 极简白名单契约 (Reviewer Async Long-Running Jobs & 1KB Snapshot Contract)
  - Implemented `ReviewerJobSupervisor` in `reviewer_jobs.py` managing async consultation jobs (`submit`, `poll`, `cancel`) with single-writer CAS state transitions and persistent background worker tasks surviving handler scopes;
  - Enforced 1KB strict non-terminal Poll whitelist contract (`POLL_NONTERMINAL_FIELDS`: 6 fields, monotonic diff elapsed/idle seconds, bounded log_ref, zero text/reasoning leakage, raising `SnapshotContractViolation` on overflow);
  - Enforced terminal symmetric snapshot contract (`POLL_TERMINAL_FIELDS`, 40,000-character findings budget cap, and strict invariant assertion against raw CoT / reasoning keys);
  - Implemented pure function `format_progress` resolving POSIX locale hierarchy (`locale > LC_ALL > LC_MESSAGES > LANG > 'en'`) with 3-phase, 2-language mappings;
  - Upgraded `ActiveLogRegistry` in `log_naming.py` with `norm_registry_key` stripping `.1.log` rotation suffixes to pin active logs and prevent GC teardown or permission errors during in-flight runs;
  - Added `WorkspaceLeaseNotHeldError` guard on Reviewer GC entry;
  - Unified `SESSION_ID_PATTERN` SSOT to 128 characters across modules;
  - Registered FastMCP tools `dev_reviewer_submit`, `dev_reviewer_poll`, `dev_reviewer_cancel`, and refactored `dev_reviewer_consult` into a bounded thin-shell preserving 100% backward compatibility;
  - Verified all 17 mandatory assertion functions in `test_reviewer_jobs.py` and `test_snapshot_contract.py` alongside full 544-test zero-regression suite.


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
