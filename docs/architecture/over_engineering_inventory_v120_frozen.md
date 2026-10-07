# Quench 架构资产取证与去工业化清单 (Architecture Asset Inventory)

> **取证铁律与下界声明**:
> 1. 本图谱为下界，不覆盖 `mod.sym` 属性式访问与运行时反射。
> 2. 只读取证铁律：不修改任何生产代码，作为 step02–step09 瘦身动作的许可依据与回滚判据。

---

## 1. 核心不可触碰清单 (Must-Not-Remove Invariants)

| 关键符号 | 约束与承载不变量 |
| :--- | :--- |
| `reclaim_stale_task` | INV-1 陈旧租约回收唯一实现（仅允许原子迁移，禁止直接删除） |
| `generation` | 工作区互斥锁 CAS 代际令牌（防 ABA 踩脚） |
| `owner_boot_nonce` | 跨进程租约身份 CAS 判定 |
| `probe_peer` | 跨进程存活判定（必须在交付替代回收路径后方可移除） |
| `TERMINAL_RESULT_ALLOWED_FIELDS` | INV-3 反角色扮演与防思维链泄露白名单 |
| `assert_read_only_sandbox` | INV-6 审查只读沙箱硬校验 |
| `filelock` | manifest 级跨进程互斥锁 |
| `precondition_changed` | 任务状态并发 CAS 保护 |
| `on_missing_record` | 安全键 fail-closed 策略 |
| `canonical_artifact_ref` | 规范产物引用契约 |
| `format_heartbeat_line` | C2 心跳行契约（时间在前 | Token 在后） |

---

## 2. 潜在删除/重构候选清单 (Removal Candidates, 共 138 项)

| 符号 | 定义模块 |
| :--- | :--- |
| `__all__` | `plugins/quench-dev-tasks/server/adapters/__init__.py` |
| `Colors` | `plugins/quench-dev-tasks/server/cli.py` |
| `SCRIPTS_DIR` | `plugins/quench-dev-tasks/server/cli.py` |
| `SERVER_DIR` | `plugins/quench-dev-tasks/server/cli.py` |
| `cmd_archive` | `plugins/quench-dev-tasks/server/cli.py` |
| `cmd_check` | `plugins/quench-dev-tasks/server/cli.py` |
| `cmd_init` | `plugins/quench-dev-tasks/server/cli.py` |
| `cmd_reviewer_debug` | `plugins/quench-dev-tasks/server/cli.py` |
| `cmd_status` | `plugins/quench-dev-tasks/server/cli.py` |
| `should_enable_color` | `plugins/quench-dev-tasks/server/cli.py` |
| `CodeExplorerError` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `DEFAULT_DEADLINE_SECONDS` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `MAX_EXPLORE_FILES` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `MAX_FILE_BYTES` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `MAX_HOPS_LIMIT` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `MAX_SLICE_LINES` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `SENSITIVE_PATTERNS` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `SkippedFile` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `SlicedFile` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `SymbolIface` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `UnsafePathError` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `build_safe_slice` | `plugins/quench-dev-tasks/server/code_explorer.py` |
| `CONTEXT_SPEC_PATTERN` | `plugins/quench-dev-tasks/server/consultation.py` |
| `ConsultMode` | `plugins/quench-dev-tasks/server/consultation.py` |
| `DEFAULT_WINDOW_LINES` | `plugins/quench-dev-tasks/server/consultation.py` |
| `JOB_ID_PATTERN` | `plugins/quench-dev-tasks/server/consultation.py` |
| `MAX_CONTEXT_FILES` | `plugins/quench-dev-tasks/server/consultation.py` |
| `MAX_INJECTION_CHARS` | `plugins/quench-dev-tasks/server/consultation.py` |
| `MAX_LINES_PER_SLICE` | `plugins/quench-dev-tasks/server/consultation.py` |
| `MAX_LOG_FILES_QUOTA` | `plugins/quench-dev-tasks/server/consultation.py` |
| `MAX_LOG_FILE_BYTES` | `plugins/quench-dev-tasks/server/consultation.py` |
| `MAX_QUERY_CHARS` | `plugins/quench-dev-tasks/server/consultation.py` |
| `MAX_REASONING_TOKENS_CEILING` | `plugins/quench-dev-tasks/server/consultation.py` |
| `MIN_WINDOW_LINES` | `plugins/quench-dev-tasks/server/consultation.py` |
| `MODE_INSTRUCTIONS` | `plugins/quench-dev-tasks/server/consultation.py` |
| `NEED_FILES_PATTERN` | `plugins/quench-dev-tasks/server/consultation.py` |
| `ReasoningBudgetExceededError` | `plugins/quench-dev-tasks/server/consultation.py` |
| `TASK_DRAFT_PATTERN` | `plugins/quench-dev-tasks/server/consultation.py` |
| `VALID_MODES` | `plugins/quench-dev-tasks/server/consultation.py` |
| `_LOCKS_MUTEX` | `plugins/quench-dev-tasks/server/consultation.py` |
| `_PREFIX_LOCK` | `plugins/quench-dev-tasks/server/consultation.py` |
| `_SESSION_LOCKS` | `plugins/quench-dev-tasks/server/consultation.py` |
| `_WINDOWS_RESERVED_NAMES` | `plugins/quench-dev-tasks/server/consultation.py` |
| `_enforce_log_quota` | `plugins/quench-dev-tasks/server/consultation.py` |
| `_get_session_lock` | `plugins/quench-dev-tasks/server/consultation.py` |
| `current_dir` | `plugins/quench-dev-tasks/server/hooks/context_injector.py` |
| `server_dir` | `plugins/quench-dev-tasks/server/hooks/context_injector.py` |
| `STATUS_PATTERN` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` |
| `check_task_status_guard` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` |
| `current_dir` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` |
| `extract_statuses` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` |
| `is_meta_file` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` |
| `is_task_file` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` |
| `is_whitelist_matched` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` |
| `matches_pattern` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` |
| `server_dir` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` |
| `LOG_FILENAME_REGEX` | `plugins/quench-dev-tasks/server/log_naming.py` |
| `QuotaResult` | `plugins/quench-dev-tasks/server/log_naming.py` |
| `_WINDOWS_RESERVED_NAMES` | `plugins/quench-dev-tasks/server/log_naming.py` |
| `EXCLUDED_WORKSPACE_DIRS` | `plugins/quench-dev-tasks/server/manifest.py` |
| `ReconcileEntry` | `plugins/quench-dev-tasks/server/manifest.py` |
| `_get_git_head_commit` | `plugins/quench-dev-tasks/server/manifest.py` |
| `_get_git_tracked_files` | `plugins/quench-dev-tasks/server/manifest.py` |
| `_lock_local` | `plugins/quench-dev-tasks/server/manifest.py` |
| `_resolve_namespaced_id` | `plugins/quench-dev-tasks/server/manifest.py` |
| `_safe_baseline_filename` | `plugins/quench-dev-tasks/server/manifest.py` |
| `_evaluate_affected_files_mtime` | `plugins/quench-dev-tasks/server/manifest_lease.py` |
| `_extract_affected_files_from_task` | `plugins/quench-dev-tasks/server/manifest_lease.py` |
| `FileVerdictAuditSink` | `plugins/quench-dev-tasks/server/observability_policy.py` |
| `_DRIVE` | `plugins/quench-dev-tasks/server/path_guard.py` |
| `_MULTI_DOT` | `plugins/quench-dev-tasks/server/path_guard.py` |
| `_NUL_BYTE_RE` | `plugins/quench-dev-tasks/server/path_guard.py` |
| `_WIN_RESERVED_NAMES` | `plugins/quench-dev-tasks/server/path_guard.py` |
| `_glob_to_regex` | `plugins/quench-dev-tasks/server/path_guard.py` |
| `CRITICAL_CODE_MANIFESTS` | `plugins/quench-dev-tasks/server/project_config.py` |
| `DEFAULT_AFFECTED_FILES_MTIME_THRESHOLD_SECONDS` | `plugins/quench-dev-tasks/server/project_config.py` |
| `DEFAULT_HEARTBEAT_SILENCE_THRESHOLD_SECONDS` | `plugins/quench-dev-tasks/server/project_config.py` |
| `DEFAULT_MAX_TOTAL_INJECTION_CHARS` | `plugins/quench-dev-tasks/server/project_config.py` |
| `DEFAULT_UNMANAGED_DIRS` | `plugins/quench-dev-tasks/server/project_config.py` |
| `DEFAULT_WINDOW_LINES` | `plugins/quench-dev-tasks/server/project_config.py` |
| `KNOWN_TOP_LEVEL_KEYS` | `plugins/quench-dev-tasks/server/project_config.py` |
| `MAX_LINES_PER_SLICE` | `plugins/quench-dev-tasks/server/project_config.py` |
| `MAX_TOTAL_INJECTION_CHARS_UPPER` | `plugins/quench-dev-tasks/server/project_config.py` |
| `MIN_TOTAL_INJECTION_CHARS` | `plugins/quench-dev-tasks/server/project_config.py` |
| `PROTECTED_CONFIG_NAMES` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_DEFAULT_CONFIG_VERSION_PATCH` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_DEFAULT_FAST_TRACK_PATCH` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_DEFAULT_SCHEMA_VERSION_PATCH` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_SEEN_DEPRECATED_PROVIDERS` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_build_quench_stack_config` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_calculate_shannon_entropy` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_deep_merge_dict` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_derive_safety_key_domains` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_match_glob` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_validate_credentials_security` | `plugins/quench-dev-tasks/server/project_config.py` |
| `resolve_path` | `plugins/quench-dev-tasks/server/project_config.py` |
| `_extract_spec_section` | `plugins/quench-dev-tasks/server/reporting.py` |
| `IS_SOLE_PROVIDER_EGRESS` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `MAX_RESPONSE_BYTES` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `ReviewerRateLimitError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `ReviewerTimeoutError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `SSE_IDLE_TIMEOUT_S` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `TelemetryRecord` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `_REVIEWER_LIMITER` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `_SECRET_REDACTION_PATTERN` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `__all__` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `__getattr__` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `_is_local_endpoint` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `_iter_sse_payloads` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `_normalize_chat_endpoint` | `plugins/quench-dev-tasks/server/reviewer_engine.py` |
| `AUDIT_LINE_MAX_BYTES` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` |
| `DegradedReason` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` |
| `JOB_ID_PATTERN` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` |
| `_WINDOWS_RESERVED_NAMES` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` |
| `_record_from_dict` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` |
| `assert_poll_authorized` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` |
| `compute_elapsed_s` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` |
| `FIELD_ALIASES` | `plugins/quench-dev-tasks/server/schema_validator.py` |
| `REQUIRED_FIELDS` | `plugins/quench-dev-tasks/server/schema_validator.py` |
| `VALID_AFFECTED_PREFIXES` | `plugins/quench-dev-tasks/server/schema_validator.py` |
| `ValidationResult` | `plugins/quench-dev-tasks/server/schema_validator.py` |
| `BYPASS_PRESET_CATEGORIES` | `plugins/quench-dev-tasks/server/server.py` |
| `DispatchStrategy` | `plugins/quench-dev-tasks/server/server.py` |
| `ReadStatus` | `plugins/quench-dev-tasks/server/server.py` |
| `ReviewerHandoff` | `plugins/quench-dev-tasks/server/server.py` |
| `_ASSERTION_MARKERS` | `plugins/quench-dev-tasks/server/server.py` |
| `__getattr__` | `plugins/quench-dev-tasks/server/server.py` |
| `_append_hook_log` | `plugins/quench-dev-tasks/server/server.py` |
| `_degraded_card` | `plugins/quench-dev-tasks/server/server.py` |
| `_extract_task_detail` | `plugins/quench-dev-tasks/server/server.py` |
| `_issue_checkout_lease` | `plugins/quench-dev-tasks/server/server.py` |
| `_render_task_markdown` | `plugins/quench-dev-tasks/server/server.py` |
| `_resolve_task_file_path` | `plugins/quench-dev-tasks/server/server.py` |
| `EMOJI_STATUS_OPTIONS` | `plugins/quench-dev-tasks/server/state_machine.py` |
| `STATUS_REGEX_PART` | `plugins/quench-dev-tasks/server/state_machine.py` |
| `StateMachineError` | `plugins/quench-dev-tasks/server/state_machine.py` |
| `VALID_TRANSITIONS` | `plugins/quench-dev-tasks/server/state_machine.py` |
| `_normalize_status` | `plugins/quench-dev-tasks/server/state_machine.py` |

---

## 3. 服务端生产模块概览 (Server Production Modules, 共 23 个模块)

| 模块路径 | 定义符号数 | 导入模块数 | 导入符号数 |
| :--- | :--- | :--- | :--- |
| `plugins/quench-dev-tasks/server/adapters/__init__.py` | 2 | 5 | 7 |
| `plugins/quench-dev-tasks/server/adapters/antigravity_adapter.py` | 1 | 3 | 4 |
| `plugins/quench-dev-tasks/server/adapters/base_adapter.py` | 3 | 5 | 6 |
| `plugins/quench-dev-tasks/server/adapters/cursor_adapter.py` | 1 | 6 | 4 |
| `plugins/quench-dev-tasks/server/adapters/generic_cli_adapter.py` | 1 | 5 | 4 |
| `plugins/quench-dev-tasks/server/cli.py` | 12 | 11 | 11 |
| `plugins/quench-dev-tasks/server/code_explorer.py` | 17 | 8 | 9 |
| `plugins/quench-dev-tasks/server/consultation.py` | 46 | 20 | 48 |
| `plugins/quench-dev-tasks/server/hooks/context_injector.py` | 3 | 7 | 5 |
| `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | 24 | 15 | 14 |
| `plugins/quench-dev-tasks/server/log_naming.py` | 25 | 9 | 9 |
| `plugins/quench-dev-tasks/server/manifest.py` | 39 | 20 | 20 |
| `plugins/quench-dev-tasks/server/manifest_lease.py` | 11 | 15 | 22 |
| `plugins/quench-dev-tasks/server/observability_policy.py` | 7 | 9 | 10 |
| `plugins/quench-dev-tasks/server/path_guard.py` | 13 | 9 | 5 |
| `plugins/quench-dev-tasks/server/project_config.py` | 55 | 18 | 17 |
| `plugins/quench-dev-tasks/server/reporting.py` | 3 | 6 | 6 |
| `plugins/quench-dev-tasks/server/reviewer_engine.py` | 49 | 28 | 33 |
| `plugins/quench-dev-tasks/server/reviewer_jobs.py` | 34 | 22 | 41 |
| `plugins/quench-dev-tasks/server/schema_validator.py` | 9 | 10 | 12 |
| `plugins/quench-dev-tasks/server/server.py` | 43 | 31 | 78 |
| `plugins/quench-dev-tasks/server/state_machine.py` | 24 | 9 | 10 |
| `plugins/quench-dev-tasks/server/workspace_lease.py` | 5 | 9 | 10 |

---

## 4. 消费者依赖图谱 (Consumer Dependency Graph, 共 427 项符号)

| 符号 | 定义模块 | 业务消费者 (`consumed_by`) | 测试引用 (`test_refs`) | 文档提及 (`doc_refs`) |
| :--- | :--- | :--- | :--- | :--- |
| `__all__` | `plugins/quench-dev-tasks/server/adapters/__init__.py` | NONE | NONE | NONE |
| `get_adapter` | `plugins/quench-dev-tasks/server/adapters/__init__.py` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | `plugins/quench-dev-tasks/server/tests/test_adapters.py` | NONE |
| `AntigravityAdapter` | `plugins/quench-dev-tasks/server/adapters/antigravity_adapter.py` | `plugins/quench-dev-tasks/server/adapters/__init__.py` | `plugins/quench-dev-tasks/server/tests/test_adapters.py` | `CHANGELOG.md` |
| `EnvironmentAdapter` | `plugins/quench-dev-tasks/server/adapters/base_adapter.py` | `plugins/quench-dev-tasks/server/adapters/__init__.py`, `plugins/quench-dev-tasks/server/adapters/antigravity_adapter.py`, `plugins/quench-dev-tasks/server/adapters/cursor_adapter.py`, `plugins/quench-dev-tasks/server/adapters/generic_cli_adapter.py` | `plugins/quench-dev-tasks/server/tests/test_adapters.py` | `docs/roadmap/archive/v1.03_cross_tool_cursor_adaptation.md` |
| `EnvironmentDetector` | `plugins/quench-dev-tasks/server/adapters/base_adapter.py` | `plugins/quench-dev-tasks/server/adapters/__init__.py`, `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | `plugins/quench-dev-tasks/server/tests/test_adapters.py` | `docs/roadmap/archive/v1.03_cross_tool_cursor_adaptation.md` |
| `EnvironmentType` | `plugins/quench-dev-tasks/server/adapters/base_adapter.py` | `plugins/quench-dev-tasks/server/adapters/__init__.py` | `plugins/quench-dev-tasks/server/tests/test_adapters.py` | `docs/roadmap/archive/v1.03_cross_tool_cursor_adaptation.md` |
| `CursorAdapter` | `plugins/quench-dev-tasks/server/adapters/cursor_adapter.py` | `plugins/quench-dev-tasks/server/adapters/__init__.py` | `plugins/quench-dev-tasks/server/tests/test_adapters.py` | NONE |
| `GenericCLIAdapter` | `plugins/quench-dev-tasks/server/adapters/generic_cli_adapter.py` | `plugins/quench-dev-tasks/server/adapters/__init__.py` | `plugins/quench-dev-tasks/server/tests/test_adapters.py` | NONE |
| `Colors` | `plugins/quench-dev-tasks/server/cli.py` | NONE | NONE | NONE |
| `SCRIPTS_DIR` | `plugins/quench-dev-tasks/server/cli.py` | NONE | NONE | NONE |
| `SERVER_DIR` | `plugins/quench-dev-tasks/server/cli.py` | NONE | NONE | NONE |
| `_mask_secret` | `plugins/quench-dev-tasks/server/cli.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dod_guard.py` | NONE |
| `cmd_archive` | `plugins/quench-dev-tasks/server/cli.py` | NONE | NONE | NONE |
| `cmd_check` | `plugins/quench-dev-tasks/server/cli.py` | NONE | NONE | NONE |
| `cmd_check_engine` | `plugins/quench-dev-tasks/server/cli.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dod_guard.py` | NONE |
| `cmd_init` | `plugins/quench-dev-tasks/server/cli.py` | NONE | NONE | NONE |
| `cmd_reviewer_debug` | `plugins/quench-dev-tasks/server/cli.py` | NONE | NONE | NONE |
| `cmd_status` | `plugins/quench-dev-tasks/server/cli.py` | NONE | NONE | NONE |
| `main` | `plugins/quench-dev-tasks/server/cli.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_asset_inventory.py`, `plugins/quench-dev-tasks/server/tests/test_dod_guard.py`, `plugins/quench-dev-tasks/server/tests/test_no_api_bypass.py`, `plugins/quench-dev-tasks/server/tests/test_pre_commit_guard.py`, `plugins/quench-dev-tasks/server/tests/test_probe_client_capabilities.py` | `docs/ci_incident_tracker_and_compatibility_guide.md`, `docs/roadmap/archive/v1.04_automated_subagent_delegation_and_codebase_inspection.md` |
| `should_enable_color` | `plugins/quench-dev-tasks/server/cli.py` | NONE | NONE | NONE |
| `CodeExplorerError` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `DEFAULT_DEADLINE_SECONDS` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `ExploreResult` | `plugins/quench-dev-tasks/server/code_explorer.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_spec_refine.py` | NONE |
| `MAX_EXPLORE_FILES` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `MAX_FILE_BYTES` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `MAX_HOPS_LIMIT` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `MAX_SLICE_LINES` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `SENSITIVE_PATTERNS` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `SkippedFile` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `SlicedFile` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `SymbolIface` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `UnsafePathError` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `build_safe_slice` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | NONE | NONE |
| `explore_code_slices` | `plugins/quench-dev-tasks/server/code_explorer.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_spec_refine.py` | NONE |
| `extract_ast_interfaces` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_spec_refine.py` | NONE |
| `is_path_safe` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_spec_refine.py` | NONE |
| `is_sensitive_file` | `plugins/quench-dev-tasks/server/code_explorer.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_spec_refine.py` | NONE |
| `AbortHandle` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE |
| `CONTEXT_SPEC_PATTERN` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `ConsultMode` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `ConsultRequest` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py` | NONE |
| `ConsultResult` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py`, `plugins/quench-dev-tasks/server/tests/test_forgery_prevention_contract.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py` | NONE |
| `DEFAULT_WINDOW_LINES` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `HopBudget` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py` | NONE |
| `JOB_ID_PATTERN` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `MAX_CONTEXT_FILES` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `MAX_INJECTION_CHARS` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `MAX_LINES_PER_SLICE` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `MAX_LOG_FILES_QUOTA` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `MAX_LOG_FILE_BYTES` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `MAX_QUERY_CHARS` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `MAX_REASONING_TOKENS_CEILING` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `MAX_TOTAL_INJECTION_CHARS` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py` | NONE |
| `MIN_TELEMETRY_SAMPLES` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py` | NONE |
| `MIN_WINDOW_LINES` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `MODE_INSTRUCTIONS` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `MULTI_HOP_DEMAND_PERCENT` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py` | NONE |
| `MULTI_HOP_DEMAND_THRESHOLD` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py` | NONE |
| `NEED_FILES_PATTERN` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `ReasoningBudgetExceededError` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `TASK_DRAFT_PATTERN` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `VALID_MODES` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `_LOCKS_MUTEX` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `_PREFIX_CACHE` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | `dev_tasks_mcp_specification.md`, `docs/roadmap/README.md` |
| `_PREFIX_LOCK` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `_SESSION_LOCKS` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `_WINDOWS_RESERVED_NAMES` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `_emit_consultation_audit` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py` | NONE |
| `_enforce_log_quota` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `_execute_consultation` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE |
| `_get_session_lock` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | NONE | NONE |
| `_read_telemetry_demand_sync` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py` | NONE |
| `assemble_reviewer_context` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py` | `docs/architecture/README.md` |
| `assert_read_only_sandbox` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py` | `docs/architecture/README.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md`, `docs/roadmap/v1.22_architecture_convergence_roadmap.md` |
| `build_static_prefix` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py` | `CHANGELOG.md` |
| `evaluate_multi_hop_gate` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py` | NONE |
| `render_mode_prompt` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_prompt_cache_stability.py`, `plugins/quench-dev-tasks/server/tests/test_prompt_layout_criterion.py` | NONE |
| `resolve_context_files` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py` | NONE |
| `run_consultation` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py` | NONE |
| `sanitize_session_id` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py` | NONE |
| `should_enable_multi_hop` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py` | NONE |
| `strip_reasoning_from_history` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py` | NONE |
| `validate_job_id` | `plugins/quench-dev-tasks/server/consultation.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | NONE |
| `current_dir` | `plugins/quench-dev-tasks/server/hooks/context_injector.py` | NONE | NONE | NONE |
| `main` | `plugins/quench-dev-tasks/server/hooks/context_injector.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_asset_inventory.py`, `plugins/quench-dev-tasks/server/tests/test_dod_guard.py`, `plugins/quench-dev-tasks/server/tests/test_no_api_bypass.py`, `plugins/quench-dev-tasks/server/tests/test_pre_commit_guard.py`, `plugins/quench-dev-tasks/server/tests/test_probe_client_capabilities.py` | `docs/ci_incident_tracker_and_compatibility_guide.md`, `docs/roadmap/archive/v1.04_automated_subagent_delegation_and_codebase_inspection.md` |
| `server_dir` | `plugins/quench-dev-tasks/server/hooks/context_injector.py` | NONE | NONE | NONE |
| `SESSION_ID_PATTERN` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/reviewer_jobs.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py` | `CHANGELOG.md`, `plugins/quench-dev-tasks/rules/coding-standards.md` |
| `SHELL_TOOL_NAMES` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_shell_write_bypass.py` | NONE |
| `SHELL_WRITE_PATTERN` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_shell_write_bypass.py` | NONE |
| `STATUS_PATTERN` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | NONE | NONE |
| `SafeRotatingFileHandler` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_observability.py` | `CHANGELOG.md`, `docs/roadmap/README.md` |
| `_LOGGER_CACHE` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_observability.py` | NONE |
| `_strip_long_path_prefix` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_file_scope_guard_hardening.py` | NONE |
| `check_task_status_guard` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | NONE | NONE |
| `current_dir` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | NONE | NONE |
| `detect_shell_write_bypass` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_shell_write_bypass.py` | NONE |
| `extract_statuses` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | NONE | NONE |
| `get_hook_logger` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_observability.py` | NONE |
| `is_governed_task_file` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_file_scope_guard_hardening.py` | NONE |
| `is_meta_file` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | NONE | NONE |
| `is_session_bypass_matched` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py` | NONE |
| `is_task_file` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | NONE | NONE |
| `is_whitelist_matched` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | NONE | NONE |
| `log_guard_event` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_observability.py` | NONE |
| `main` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_asset_inventory.py`, `plugins/quench-dev-tasks/server/tests/test_dod_guard.py`, `plugins/quench-dev-tasks/server/tests/test_no_api_bypass.py`, `plugins/quench-dev-tasks/server/tests/test_pre_commit_guard.py`, `plugins/quench-dev-tasks/server/tests/test_probe_client_capabilities.py` | `docs/ci_incident_tracker_and_compatibility_guide.md`, `docs/roadmap/archive/v1.04_automated_subagent_delegation_and_codebase_inspection.md` |
| `matches_pattern` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | NONE | NONE |
| `resolve_realpath_under` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_file_scope_guard_hardening.py` | NONE |
| `safe_clean_corrupted_bypass` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py` | NONE |
| `server_dir` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | NONE | NONE |
| `verify_session_integrity` | `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py` | NONE |
| `ActiveLogRegistry` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/reviewer_engine.py`, `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_cache_telemetry.py`, `plugins/quench-dev-tasks/server/tests/test_log_quota_cross_process.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py` | `CHANGELOG.md` |
| `HEADER_VERSION` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | NONE |
| `InvalidSlugError` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | NONE |
| `LOG_FILENAME_REGEX` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | NONE | NONE |
| `LogFileName` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | NONE |
| `MAX_DAILY_SEQUENCE` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | NONE |
| `MAX_LOG_REF_CHARS` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | NONE |
| `QuotaResult` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | NONE | NONE |
| `REVIEWER_LOG_QUOTA_KEEP` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py` | NONE |
| `REVIEWER_TERMINAL_LOG_RETENTION` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py` | NONE |
| `SESSION_ID_PATTERN` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/reviewer_jobs.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py` | `CHANGELOG.md`, `plugins/quench-dev-tasks/rules/coding-standards.md` |
| `SLUG_MAX_LEN` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | NONE |
| `SequenceExhaustedError` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | NONE |
| `_LOG_FILENAME_REGEX` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | `docs/ci_incident_tracker_and_compatibility_guide.md` |
| `_ROTATION_SUFFIX_REGEX` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | NONE |
| `_WINDOWS_RESERVED_NAMES` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | NONE | NONE |
| `allocate_log_file` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_log_naming.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py` | NONE |
| `enforce_unified_log_quota` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_log_naming.py`, `plugins/quench-dev-tasks/server/tests/test_log_quota_cross_process.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py` | `docs/architecture/README.md` |
| `gc_by_filename_order` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_log_naming.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py` | `CHANGELOG.md`, `docs/architecture/README.md`, `docs/ci_incident_tracker_and_compatibility_guide.md` |
| `list_log_files` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | `docs/ci_incident_tracker_and_compatibility_guide.md` |
| `norm_path_pure` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | NONE | `docs/roadmap/v1.22_architecture_convergence_roadmap.md` |
| `norm_registry_key` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/reviewer_engine.py`, `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_cache_telemetry.py`, `plugins/quench-dev-tasks/server/tests/test_log_naming.py`, `plugins/quench-dev-tasks/server/tests/test_log_quota_cross_process.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py` | `CHANGELOG.md` |
| `normalize_utc_date` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | NONE |
| `sanitize_slug` | `plugins/quench-dev-tasks/server/log_naming.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_naming.py` | NONE |
| `validate_log_ref` | `plugins/quench-dev-tasks/server/log_naming.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE |
| `BaselineSnapshot` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | `docs/architecture/README.md` |
| `EXCLUDED_WORKSPACE_DIRS` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | NONE | NONE |
| `FencedTokenError` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py` | NONE |
| `FileFingerprint` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | NONE |
| `MANIFEST_REL_PATH` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/manifest_lease.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py` | NONE |
| `Manifest` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/manifest_lease.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py` | `CHANGELOG.md`, `docs/architecture/README.md`, `docs/architecture/manifest_compaction_contract.md`, `docs/roadmap/archive/v1.06_microkernel_adaptive_observability_and_governance_interlock.md` |
| `ManifestConflictError` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py` | `CHANGELOG.md` |
| `ManifestIntegrityError` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/manifest_lease.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py` | `CHANGELOG.md` |
| `ManifestMetrics` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py` | NONE |
| `ManifestRecordOverflowError` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py` | NONE |
| `ReconcileClass` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py` | NONE |
| `ReconcileEntry` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | NONE | NONE |
| `ReconcileReport` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py` | NONE |
| `ReconciliationReport` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | NONE |
| `RetryableManifestError` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py` | `CHANGELOG.md` |
| `T` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | NONE | `docs/roadmap/archive/v1.08_reverse_topology_and_external_runner.md` |
| `TaskRecord` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/manifest_lease.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py` | NONE |
| `_get_git_head_commit` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | NONE | NONE |
| `_get_git_metadata` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | NONE |
| `_get_git_tracked_files` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | NONE | NONE |
| `_lock_local` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | NONE | NONE |
| `_resolve_namespaced_id` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | NONE | NONE |
| `_safe_baseline_filename` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | NONE | NONE |
| `atomic_replace_manifest` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/manifest_lease.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py` | NONE |
| `capture_baseline` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | `CHANGELOG.md` |
| `commit_lease` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py` | `CHANGELOG.md` |
| `compare_and_swap` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py` | `CHANGELOG.md` |
| `compute_manifest_metrics` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py` | NONE |
| `compute_normalized_md_hash` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py` | NONE |
| `get_baseline_path` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/server.py`, `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | NONE |
| `load_baseline_snapshot` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | `CHANGELOG.md` |
| `load_manifest` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/manifest_lease.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py` | NONE |
| `mutate_manifest_under_lock` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py` | `CHANGELOG.md` |
| `reconcile_workspace` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/server.py`, `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py` | `docs/architecture/manifest_compaction_contract.md` |
| `reconcile_workspace_against_whitelist` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | `CHANGELOG.md`, `docs/architecture/README.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.08_reverse_topology_and_external_runner.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `register_proposal` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py` | `CHANGELOG.md` |
| `release_lease` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py` | `CHANGELOG.md` |
| `save_baseline_snapshot` | `plugins/quench-dev-tasks/server/manifest.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | NONE |
| `touch_heartbeat` | `plugins/quench-dev-tasks/server/manifest.py` | `plugins/quench-dev-tasks/server/manifest_lease.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py` | `CHANGELOG.md` |
| `HealthVerdict` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py` | NONE |
| `LeaseContractError` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py` | NONE |
| `MAX_TTL` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py` | NONE |
| `ProbeEvidence` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py` | NONE |
| `_evaluate_affected_files_mtime` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | NONE | NONE |
| `_extract_affected_files_from_task` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | NONE | NONE |
| `extract_session_id_from_holder_token` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py` | NONE |
| `is_workspace_actively_modifying` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py` | `CHANGELOG.md` |
| `probe_lease_health` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py` | `CHANGELOG.md`, `docs/architecture/README.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `reclaim_stale_task` | `plugins/quench-dev-tasks/server/manifest_lease.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py` | `CHANGELOG.md`, `docs/architecture/README.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md`, `docs/roadmap/v1.22_architecture_convergence_roadmap.md` |
| `touch_lease_heartbeat` | `plugins/quench-dev-tasks/server/manifest_lease.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py` | `CHANGELOG.md` |
| `FileVerdictAuditSink` | `plugins/quench-dev-tasks/server/observability_policy.py` | NONE | NONE | NONE |
| `MAX_RECORD_BYTES` | `plugins/quench-dev-tasks/server/observability_policy.py` | `plugins/quench-dev-tasks/server/manifest.py`, `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py`, `plugins/quench-dev-tasks/server/tests/test_observability_policy.py` | NONE |
| `ObservabilityDecision` | `plugins/quench-dev-tasks/server/observability_policy.py` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/tests/test_observability_policy.py` | NONE |
| `SinkMode` | `plugins/quench-dev-tasks/server/observability_policy.py` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/tests/test_observability_policy.py` | NONE |
| `VerdictAuditSink` | `plugins/quench-dev-tasks/server/observability_policy.py` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/tests/test_observability_policy.py` | `CHANGELOG.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.06_microkernel_adaptive_observability_and_governance_interlock.md` |
| `make_verdict_sink` | `plugins/quench-dev-tasks/server/observability_policy.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/tests/test_forgery_prevention_contract.py`, `plugins/quench-dev-tasks/server/tests/test_observability_policy.py` | NONE |
| `resolve_observability_policy` | `plugins/quench-dev-tasks/server/observability_policy.py` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/tests/test_observability_policy.py` | NONE |
| `PathTraversalError` | `plugins/quench-dev-tasks/server/path_guard.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/schema_validator.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_path_guard.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py` | `docs/ci_incident_tracker_and_compatibility_guide.md` |
| `SubsetCheckResult` | `plugins/quench-dev-tasks/server/path_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | NONE |
| `_DRIVE` | `plugins/quench-dev-tasks/server/path_guard.py` | NONE | NONE | NONE |
| `_MULTI_DOT` | `plugins/quench-dev-tasks/server/path_guard.py` | NONE | NONE | NONE |
| `_NUL_BYTE_RE` | `plugins/quench-dev-tasks/server/path_guard.py` | NONE | NONE | NONE |
| `_WIN_RESERVED_NAMES` | `plugins/quench-dev-tasks/server/path_guard.py` | NONE | NONE | NONE |
| `_glob_to_regex` | `plugins/quench-dev-tasks/server/path_guard.py` | NONE | NONE | NONE |
| `canonicalize_path` | `plugins/quench-dev-tasks/server/path_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | `CHANGELOG.md` |
| `check_whitelist_subset` | `plugins/quench-dev-tasks/server/path_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | NONE |
| `comparison_key` | `plugins/quench-dev-tasks/server/path_guard.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | `CHANGELOG.md` |
| `is_within_whitelist` | `plugins/quench-dev-tasks/server/path_guard.py` | `plugins/quench-dev-tasks/server/manifest.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | `CHANGELOG.md` |
| `sanitize_workspace_path` | `plugins/quench-dev-tasks/server/path_guard.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/schema_validator.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_path_guard.py` | `docs/ci_incident_tracker_and_compatibility_guide.md` |
| `to_workspace_relative_path` | `plugins/quench-dev-tasks/server/path_guard.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_path_guard.py` | NONE |
| `AuditGatePolicy` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_project_config_migration.py` | `CHANGELOG.md`, `docs/architecture/README.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `AuditGateReason` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py` | NONE |
| `AuditGateResult` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py` | NONE |
| `CRITICAL_CODE_MANIFESTS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `CRITICAL_CODE_MANIFEST_PATTERNS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_project_config.py` | NONE |
| `CURRENT_CONFIG_VERSION` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_project_config_migration.py` | NONE |
| `CURRENT_SCHEMA_VERSION` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_config_migration.py` | NONE |
| `ConfigError` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_project_config.py`, `plugins/quench-dev-tasks/server/tests/test_project_config_migration.py` | `CHANGELOG.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `ConfigFault` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_project_config_migration.py` | NONE |
| `DEFAULT_AFFECTED_FILES_MTIME_THRESHOLD_SECONDS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `DEFAULT_HEARTBEAT_SILENCE_THRESHOLD_SECONDS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `DEFAULT_MAX_TOTAL_INJECTION_CHARS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `DEFAULT_UNMANAGED_DIRS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `DEFAULT_UNMANAGED_EXTENSIONS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_project_config.py` | NONE |
| `DEFAULT_WINDOW_LINES` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `DispatchStrategy` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE |
| `KNOWN_TOP_LEVEL_KEYS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `MAX_LINES_PER_SLICE` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `MAX_TOTAL_INJECTION_CHARS_UPPER` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `MIN_TOTAL_INJECTION_CHARS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `ObservabilityConfig` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py` | NONE |
| `PROTECTED_CONFIG_NAMES` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `PROVIDER_ALIASES` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py` | NONE |
| `PROVIDER_PRESETS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md`, `docs/roadmap/plan_cost_efficiency_and_governance_hardening.md` |
| `ProviderPreset` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py` | NONE |
| `QuenchStackConfig` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/reviewer_engine.py`, `plugins/quench-dev-tasks/server/reviewer_jobs.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_config_migration.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py`, `plugins/quench-dev-tasks/server/tests/test_dod_guard.py`, `plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py`, `plugins/quench-dev-tasks/server/tests/test_project_config.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py`, `plugins/quench-dev-tasks/server/tests/test_spec_refine.py` | NONE |
| `ReaperPolicyConfig` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py` | NONE |
| `ReviewerEngineConfig` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/reviewer_engine.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py`, `plugins/quench-dev-tasks/server/tests/test_dod_guard.py`, `plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py`, `plugins/quench-dev-tasks/server/tests/test_spec_refine.py` | `CHANGELOG.md`, `docs/roadmap/archive/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md` |
| `RunnerProfile` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py` | `docs/roadmap/archive/v1.07_architecture_doc_integrity_and_neutrality_decoupling.md` |
| `SAFETY_KEY_DOMAINS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_project_config_migration.py` | `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `_DEFAULT_CONFIG_VERSION_PATCH` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `_DEFAULT_FAST_TRACK_PATCH` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `_DEFAULT_SCHEMA_VERSION_PATCH` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `_SEEN_DEPRECATED_PROVIDERS` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `_build_quench_stack_config` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `_calculate_shannon_entropy` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `_coerce_positive_int` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | `CHANGELOG.md` |
| `_deep_merge_dict` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `_derive_safety_key_domains` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `_looks_like_plaintext_secret` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_project_config.py` | `docs/roadmap/README.md` |
| `_match_glob` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `_reject_inline_credentials` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_project_config.py` | `docs/roadmap/README.md` |
| `_validate_credentials_security` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `canonical_artifact_ref` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py` | `docs/architecture/README.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md` |
| `check_self_verification_warning` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py` | NONE |
| `create_reviewer_client` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/cli.py`, `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py` | NONE |
| `is_protected_config_path` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_project_config_migration.py` | NONE |
| `load_project_config` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/cli.py`, `plugins/quench-dev-tasks/server/hooks/context_injector.py`, `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py`, `plugins/quench-dev-tasks/server/manifest_lease.py`, `plugins/quench-dev-tasks/server/reviewer_jobs.py`, `plugins/quench-dev-tasks/server/server.py`, `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_config_migration.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py`, `plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py`, `plugins/quench-dev-tasks/server/tests/test_project_config.py`, `plugins/quench-dev-tasks/server/tests/test_project_config_migration.py`, `plugins/quench-dev-tasks/server/tests/test_prompt_cache_stability.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py` | `docs/roadmap/archive/v1.01_personal_seamless_multiproject.md`, `docs/roadmap/archive/v1.02_antigravity_community_ready.md` |
| `migrate_and_validate` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_project_config_migration.py` | NONE |
| `migrate_config_if_needed` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_config_migration.py` | NONE |
| `most_restrictive_policy` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py` | `docs/architecture/README.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `normalize_model_identity` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py` | NONE |
| `resolve_path` | `plugins/quench-dev-tasks/server/project_config.py` | NONE | NONE | NONE |
| `resolve_preset` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py` | NONE |
| `resolve_reviewer_log_dir` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE |
| `_extract_spec_section` | `plugins/quench-dev-tasks/server/reporting.py` | NONE | NONE | NONE |
| `append_changelog_entry` | `plugins/quench-dev-tasks/server/reporting.py` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE |
| `render_handoff_card` | `plugins/quench-dev-tasks/server/reporting.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_handoff_card.py` | `CHANGELOG.md`, `docs/roadmap/README.md` |
| `AdaptiveHeartbeatSink` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_heartbeat.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_heartbeat_format.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py` | `CHANGELOG.md` |
| `AssembledPrompt` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_prompt_cache_stability.py`, `plugins/quench-dev-tasks/server/tests/test_prompt_layout_criterion.py` | NONE |
| `CONSULT_MODE_INSTRUCTIONS` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_prompt_layout_criterion.py` | `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `CacheTelemetryRecord` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_cache_telemetry.py` | NONE |
| `CoalescingStats` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_coalescing_sink.py` | NONE |
| `CoalescingTextSink` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_coalescing_sink.py` | `CHANGELOG.md` |
| `CodeSlice` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py`, `plugins/quench-dev-tasks/server/tests/test_prompt_cache_stability.py`, `plugins/quench-dev-tasks/server/tests/test_prompt_layout_criterion.py` | NONE |
| `IS_SOLE_PROVIDER_EGRESS` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `MAX_RESPONSE_BYTES` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `OUTPUT_PROTOCOLS` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_prompt_layout_criterion.py` | NONE |
| `ProgressSink` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py` | NONE |
| `PromptAssembler` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_prompt_cache_stability.py`, `plugins/quench-dev-tasks/server/tests/test_prompt_layout_criterion.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py` | `CHANGELOG.md`, `docs/roadmap/archive/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `ReviewerAuthError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py` | NONE |
| `ReviewerAuthenticationError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py` | `docs/roadmap/archive/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md` |
| `ReviewerBadRequestError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_bad_request.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py` | `CHANGELOG.md` |
| `ReviewerClient` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/cli.py`, `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/project_config.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_bad_request.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_stream.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/future_roadmap_ideas.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.04_automated_subagent_delegation_and_codebase_inspection.md`, `docs/roadmap/archive/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md`, `docs/roadmap/archive/v1.06_microkernel_adaptive_observability_and_governance_interlock.md`, `docs/roadmap/archive/v1.07_architecture_doc_integrity_and_neutrality_decoupling.md`, `docs/roadmap/plan_cost_efficiency_and_governance_hardening.md` |
| `ReviewerEngineError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_bad_request.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py` | NONE |
| `ReviewerEngineUnavailableError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py` | NONE |
| `ReviewerError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_bad_request.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py` | NONE |
| `ReviewerNotConfiguredError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/project_config.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py` | NONE |
| `ReviewerRateLimitError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `ReviewerTimeoutError` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `RollingJsonlTelemetrySink` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_cache_telemetry.py` | NONE |
| `RotatingFileSink` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py` | `CHANGELOG.md`, `dev_tasks_mcp_specification.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.04_automated_subagent_delegation_and_codebase_inspection.md`, `docs/roadmap/archive/v1.06_microkernel_adaptive_observability_and_governance_interlock.md` |
| `SSE_IDLE_TIMEOUT_S` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `StreamChunk` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py`, `plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py`, `plugins/quench-dev-tasks/server/tests/test_forgery_prevention_contract.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_stream.py` | NONE |
| `TELEMETRY_RECORD_BYTES` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_cache_telemetry.py` | NONE |
| `TelemetryRecord` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `ThoughtChunk` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py` | NONE |
| `UsageSnapshot` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_stream.py` | NONE |
| `_REVIEWER_LIMITER` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `_SECRET_REDACTION_PATTERN` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `__all__` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `__getattr__` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `_dig` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py` | NONE |
| `_is_local_endpoint` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `_iter_sse_payloads` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `_normalize_chat_endpoint` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | NONE | NONE |
| `_open_sse_response` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_stream.py` | NONE |
| `_read_windows_env_var` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py` | NONE |
| `compute_prompt_hash` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_cache_telemetry.py` | NONE |
| `compute_repetition_score` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py` | NONE |
| `extract_cached_tokens` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py` | NONE |
| `extract_reasoning_text` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py` | NONE |
| `extract_usage` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py` | NONE |
| `format_heartbeat_line` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | `plugins/quench-dev-tasks/server/consultation.py`, `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_heartbeat.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_heartbeat_format.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py` | `CHANGELOG.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `heartbeat_template_expect` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_heartbeat_format.py` | NONE |
| `log_telemetry_event` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py` | NONE |
| `mode_anchor_token_budget_proxy` | `plugins/quench-dev-tasks/server/reviewer_engine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_prompt_layout_criterion.py` | NONE |
| `AUDIT_LINE_MAX_BYTES` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE | NONE |
| `CapacityExceeded` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py` | NONE |
| `DegradedReason` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE | NONE |
| `JOB_ID_PATTERN` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE | NONE |
| `JobProgress` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_log_quota_cross_process.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py`, `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `JobRecord` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_log_quota_cross_process.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py`, `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | `CHANGELOG.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `JobState` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py`, `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_log_quota_cross_process.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py`, `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | NONE |
| `MAX_NONTERMINAL_SNAPSHOT_BYTES` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | NONE |
| `PIN_RELEASABLE_STATES` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py` | NONE |
| `POLL_NONTERMINAL_FIELDS` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py`, `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | `CHANGELOG.md` |
| `POLL_TERMINAL_FIELDS` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py`, `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | `CHANGELOG.md` |
| `POLL_TERMINAL_STATES` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py` | `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `PollSnapshot` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | NONE |
| `ReviewerJobSupervisor` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py`, `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py`, `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | `CHANGELOG.md`, `docs/architecture/README.md`, `docs/roadmap/plan_cost_efficiency_and_governance_hardening.md` |
| `ReviewerPhase` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_log_quota_cross_process.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py`, `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | NONE |
| `SnapshotContractViolation` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py`, `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | `CHANGELOG.md` |
| `TERMINAL_RESULT_ALLOWED_FIELDS` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py` | `CHANGELOG.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `TERMINAL_STATES` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py` | NONE |
| `_WINDOWS_RESERVED_NAMES` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE | NONE |
| `_atomic_replace_json` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py` | NONE |
| `_durable_write_json` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md` |
| `_record_from_dict` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE | NONE |
| `_record_to_dict` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE |
| `assert_poll_authorized` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE | NONE |
| `build_peer_liveness_probe` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_quota_cross_process.py` | `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `canonical_snapshot_bytes` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | NONE |
| `compute_elapsed_s` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE | NONE |
| `compute_protected_logs` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_log_quota_cross_process.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py` | NONE |
| `format_progress` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | `CHANGELOG.md` |
| `is_record_orphaned` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | NONE | `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `project_nonterminal` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | NONE |
| `project_poll_result` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py` | NONE |
| `project_terminal` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py`, `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | NONE |
| `validate_job_id` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` | NONE |
| `FIELD_ALIASES` | `plugins/quench-dev-tasks/server/schema_validator.py` | NONE | NONE | NONE |
| `LintIssue` | `plugins/quench-dev-tasks/server/schema_validator.py` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE |
| `PhysicalLintResult` | `plugins/quench-dev-tasks/server/schema_validator.py` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE |
| `REQUIRED_FIELDS` | `plugins/quench-dev-tasks/server/schema_validator.py` | NONE | NONE | NONE |
| `VALID_AFFECTED_PREFIXES` | `plugins/quench-dev-tasks/server/schema_validator.py` | NONE | NONE | NONE |
| `ValidationResult` | `plugins/quench-dev-tasks/server/schema_validator.py` | NONE | NONE | NONE |
| `_parse_task_markdown_sections` | `plugins/quench-dev-tasks/server/schema_validator.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_spec_refine.py` | NONE |
| `lint_task_physical_feasibility` | `plugins/quench-dev-tasks/server/schema_validator.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_draft_lint.py` | `CHANGELOG.md`, `dev_tasks_mcp_specification.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.04_automated_subagent_delegation_and_codebase_inspection.md` |
| `validate_task_schema` | `plugins/quench-dev-tasks/server/schema_validator.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_schema_validator.py` | NONE |
| `BYPASS_PRESET_CATEGORIES` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `DispatchStrategy` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `ReadStatus` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `ReviewerHandoff` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `_ASSERTION_MARKERS` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `_EXEMPTION_PATTERN` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dod_guard.py` | NONE |
| `_TEST_FILE_PATTERN` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dod_guard.py` | NONE |
| `__getattr__` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `_append_hook_log` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `_atomic_write_json` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | `plugins/quench-dev-tasks/rules/coding-standards.md` |
| `_audit_test_changes` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dod_guard.py` | NONE |
| `_check_audit_gate` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py` | NONE |
| `_degraded_card` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `_extract_task_detail` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `_extract_task_scoped_files` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py` | NONE |
| `_freshness_ok` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py` | NONE |
| `_get_recent_hook_logs` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_observability.py` | NONE |
| `_issue_checkout_lease` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `_managed_path_matches` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py` | NONE |
| `_read_recent_audit_records` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py` | NONE |
| `_render_task_markdown` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `_resolve_handoff_envelope` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py` | `docs/ci_incident_tracker_and_compatibility_guide.md` |
| `_resolve_task_file_path` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | NONE |
| `_validate_session_id` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | `plugins/quench-dev-tasks/rules/coding-standards.md` |
| `check_shell_write_isolation` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_shell_write_bypass.py` | NONE |
| `dev_reviewer_cancel` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/guides/external-executor-onboarding.md`, `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_reviewer_consult` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/configuration.md`, `docs/future_roadmap_ideas.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_reviewer_poll` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_reviewer_submit` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_archive` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/cli.py` | `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/manifest_compaction_contract.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.01_personal_seamless_multiproject.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_checkout` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_dod_guard.py`, `plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/archive/v1.03_cross_tool_cursor_adaptation.md`, `docs/roadmap/archive/v1.08_reverse_topology_and_external_runner.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md`, `docs/roadmap/plan_cost_efficiency_and_governance_hardening.md`, `docs/roadmap/plan_frontiers_dag_and_dynamic_governance.md`, `docs/roadmap/v1.22_architecture_convergence_roadmap.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_complete` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_dod_guard.py`, `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.01_personal_seamless_multiproject.md`, `docs/roadmap/archive/v1.03_cross_tool_cursor_adaptation.md`, `docs/roadmap/archive/v1.08_reverse_topology_and_external_runner.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md`, `docs/roadmap/plan_cost_efficiency_and_governance_hardening.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_confirm` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_dod_guard.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/future_roadmap_ideas.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md`, `docs/roadmap/plan_cost_efficiency_and_governance_hardening.md`, `docs/roadmap/plan_frontiers_dag_and_dynamic_governance.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_escalate` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py`, `plugins/quench-dev-tasks/server/tests/test_spec_refine.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/archive/v1.04_automated_subagent_delegation_and_codebase_inspection.md`, `docs/roadmap/archive/v1.08_reverse_topology_and_external_runner.md`, `docs/roadmap/plan_cost_efficiency_and_governance_hardening.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_export_handoff_card` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_handoff_card.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.07_architecture_doc_integrity_and_neutrality_decoupling.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_heartbeat` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py` | `README.md`, `dev_tasks_mcp_specification.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/archive/v1.06_microkernel_adaptive_observability_and_governance_interlock.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_promote_draft` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_draft_lint.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/FAQ.md`, `docs/architecture/README.md`, `docs/guides/external-executor-onboarding.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_propose` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_dod_guard.py`, `plugins/quench-dev-tasks/server/tests/test_draft_lint.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_lease.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/README.md`, `docs/future_roadmap_ideas.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md`, `docs/roadmap/archive/v1.06_microkernel_adaptive_observability_and_governance_interlock.md`, `plugins/quench-dev-tasks/agents/reviewer/agent.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_reclaim` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/archive/v1.06_microkernel_adaptive_observability_and_governance_interlock.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_refine_spec` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_spec_refine.py` | `README.md`, `dev_tasks_mcp_specification.md`, `docs/future_roadmap_ideas.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/README.md`, `docs/roadmap/archive/v1.04_automated_subagent_delegation_and_codebase_inspection.md`, `docs/roadmap/archive/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_set_bypass` | `plugins/quench-dev-tasks/server/server.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `README.md`, `dev_tasks_mcp_specification.md`, `docs/FAQ.md`, `docs/configuration.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/archive/v1.01_personal_seamless_multiproject.md`, `docs/roadmap/plan_cost_efficiency_and_governance_hardening.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `dev_tasks_status` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/cli.py` | `plugins/quench-dev-tasks/server/tests/test_dod_guard.py`, `plugins/quench-dev-tasks/server/tests/test_draft_lint.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_observability.py`, `plugins/quench-dev-tasks/server/tests/test_server_tools.py` | `CHANGELOG.md`, `README.md`, `dev_tasks_mcp_specification.md`, `docs/architecture/manifest_compaction_contract.md`, `docs/guides/external-executor-onboarding.md`, `docs/roadmap/archive/v1.01_personal_seamless_multiproject.md`, `docs/roadmap/archive/v1.03_cross_tool_cursor_adaptation.md`, `docs/roadmap/archive/v1.06_microkernel_adaptive_observability_and_governance_interlock.md`, `docs/roadmap/archive/v1.08_reverse_topology_and_external_runner.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md`, `docs/roadmap/plan_cost_efficiency_and_governance_hardening.md`, `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`, `plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md` |
| `mcp` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE | `CHANGELOG.md`, `docs/FAQ.md`, `docs/roadmap/archive/v1.03_cross_tool_cursor_adaptation.md`, `docs/roadmap/archive/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md` |
| `ALL_STATUSES` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE |
| `EMOJI_STATUS_OPTIONS` | `plugins/quench-dev-tasks/server/state_machine.py` | NONE | NONE | NONE |
| `InvalidTransitionError` | `plugins/quench-dev-tasks/server/state_machine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | NONE |
| `SLOW_PATH_HASH_QUOTA_DEFAULT` | `plugins/quench-dev-tasks/server/state_machine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `STATUS_COMPLETED` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | NONE |
| `STATUS_CONFIRMED` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/manifest_lease.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py`, `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | NONE |
| `STATUS_IN_PROGRESS` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/hooks/context_injector.py`, `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py`, `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | NONE |
| `STATUS_PENDING` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/hooks/context_injector.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py`, `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | NONE |
| `STATUS_REGEX_PART` | `plugins/quench-dev-tasks/server/state_machine.py` | NONE | NONE | NONE |
| `STATUS_REWORK` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | NONE |
| `STATUS_SKIPPED` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | NONE |
| `ScopeViolationError` | `plugins/quench-dev-tasks/server/state_machine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | `docs/architecture/README.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `StateMachineError` | `plugins/quench-dev-tasks/server/state_machine.py` | NONE | NONE | NONE |
| `TASK_HEADER_PATTERN` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/server.py` | NONE | NONE |
| `TaskItem` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/reporting.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`, `plugins/quench-dev-tasks/server/tests/test_reporting_render_golden.py` | NONE |
| `TaskNotFoundError` | `plugins/quench-dev-tasks/server/state_machine.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | NONE |
| `VALID_TRANSITIONS` | `plugins/quench-dev-tasks/server/state_machine.py` | NONE | NONE | NONE |
| `_normalize_status` | `plugins/quench-dev-tasks/server/state_machine.py` | NONE | NONE | NONE |
| `_verify_scope_reconciliation` | `plugins/quench-dev-tasks/server/state_machine.py` | NONE | NONE | `CHANGELOG.md` |
| `assert_task_checkout_allowed` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py` | NONE |
| `extract_task_whitelist` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py` | NONE |
| `get_status_summary` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | NONE |
| `parse_task_file` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/hooks/context_injector.py`, `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py`, `plugins/quench-dev-tasks/server/manifest_lease.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py`, `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | NONE |
| `transition_task` | `plugins/quench-dev-tasks/server/state_machine.py` | `plugins/quench-dev-tasks/server/manifest_lease.py`, `plugins/quench-dev-tasks/server/server.py` | `plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py`, `plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py`, `plugins/quench-dev-tasks/server/tests/test_state_machine.py` | `docs/roadmap/archive/v1.01_personal_seamless_multiproject.md` |
| `LeaseGenerationLostError` | `plugins/quench-dev-tasks/server/workspace_lease.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_crashed_worker_ttl_recovery.py`, `plugins/quench-dev-tasks/server/tests/test_lease_takeover_fencing.py` | NONE |
| `LeaseTouchOutcome` | `plugins/quench-dev-tasks/server/workspace_lease.py` | NONE | `plugins/quench-dev-tasks/server/tests/test_crashed_worker_ttl_recovery.py`, `plugins/quench-dev-tasks/server/tests/test_lease_takeover_fencing.py`, `plugins/quench-dev-tasks/server/tests/test_touch_outcome_no_truthiness.py`, `plugins/quench-dev-tasks/server/tests/test_workspace_lease.py` | NONE |
| `WorkspaceLeaseGuard` | `plugins/quench-dev-tasks/server/workspace_lease.py` | `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_crashed_worker_ttl_recovery.py`, `plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py`, `plugins/quench-dev-tasks/server/tests/test_lease_takeover_fencing.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_touch_outcome_no_truthiness.py`, `plugins/quench-dev-tasks/server/tests/test_workspace_lease.py` | `CHANGELOG.md`, `docs/roadmap/archive/v1.20_architecture_slimming_roadmap.md` |
| `WorkspaceLeaseNotHeldError` | `plugins/quench-dev-tasks/server/workspace_lease.py` | `plugins/quench-dev-tasks/server/log_naming.py`, `plugins/quench-dev-tasks/server/reviewer_jobs.py` | `plugins/quench-dev-tasks/server/tests/test_crashed_worker_ttl_recovery.py`, `plugins/quench-dev-tasks/server/tests/test_lease_takeover_fencing.py`, `plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py`, `plugins/quench-dev-tasks/server/tests/test_workspace_lease.py` | `CHANGELOG.md` |
| `_atomic_write_json` | `plugins/quench-dev-tasks/server/workspace_lease.py` | NONE | NONE | `plugins/quench-dev-tasks/rules/coding-standards.md` |

---

## 5. MCP 工具契约快照 (MCP Tool Surface Snapshot, 共 17 个工具)

| 工具名称 | 注册名称 | 参数列表 (名称与默认值) | 返回类型契约 |
| :--- | :--- | :--- | :--- |
| `dev_reviewer_cancel` | `dev_reviewer_cancel` | `workspace_root, job_id, session_id` | `dict[str, Any]` |
| `dev_reviewer_consult` | `dev_reviewer_consult` | `workspace_root, query, context_files=None, mode='critique', max_hops=1, session_id=None, ctx=None` | `dict[str, Any]` |
| `dev_reviewer_poll` | `dev_reviewer_poll` | `workspace_root, job_id, session_id, wait_max_s=0, raw_text=True` | `Union[str, dict[str, Any]]` |
| `dev_reviewer_submit` | `dev_reviewer_submit` | `workspace_root, query, context_files=None, mode='evaluate', max_hops=1, session_id=None, idempotency_key=None` | `dict[str, Any]` |
| `dev_tasks_archive` | `dev_tasks_archive` | `workspace_root, task_file` | `Dict[str, Any]` |
| `dev_tasks_checkout` | `dev_tasks_checkout` | `workspace_root, task_file=None, task_id=None, session_id=None` | `Dict[str, Any]` |
| `dev_tasks_complete` | `dev_tasks_complete` | `workspace_root, task_file, task_id, dod_output, test_evidence='', holder_token=None, generation=None` | `Dict[str, Any]` |
| `dev_tasks_confirm` | `dev_tasks_confirm` | `workspace_root, task_file, task_ids, action='confirm', session_id=None` | `Dict[str, Any]` |
| `dev_tasks_escalate` | `dev_tasks_escalate` | `workspace_root, task_file, task_id, reason, context_files=None` | `Dict[str, Any]` |
| `dev_tasks_export_handoff_card` | `dev_tasks_export_handoff_card` | `workspace_root, task_id, include_context=False` | `Dict[str, Any]` |
| `dev_tasks_heartbeat` | `dev_tasks_heartbeat` | `workspace_root='.', task_id=None, holder_token=None, session_id=None` | `dict[str, Any]` |
| `dev_tasks_promote_draft` | `dev_tasks_promote_draft` | `workspace_root, task_file, task_id` | `Dict[str, Any]` |
| `dev_tasks_propose` | `dev_tasks_propose` | `workspace_root, task_file_name, tasks` | `Dict[str, Any]` |
| `dev_tasks_reclaim` | `dev_tasks_reclaim` | `workspace_root='.', task_id='', expected_generation=0, expected_holder_token='', force=False` | `dict[str, Any]` |
| `dev_tasks_refine_spec` | `dev_tasks_refine_spec` | `workspace_root, draft_task, context_files=None, max_hops=1, persist=False` | `Dict[str, Any]` |
| `dev_tasks_set_bypass` | `dev_tasks_set_bypass` | `workspace_root, action='enable', category='ui_styling', reason='', user_authorized=False, duration_hours=4, session_id=None, custom_patterns=None` | `Dict[str, Any]` |
| `dev_tasks_status` | `dev_tasks_status` | `workspace_root, include_drafts=False` | `Dict[str, Any]` |

---

## 6. G1' 语义正交门禁与待补维度登记 (G1' Gaps & Semantic Orthogonality)

- 状态跃迁维度不可由静态 AST 机械推导：MCP 工具对任务状态机（如 ✅ 已确认 -> 🔨 执行中 -> ✔️ 已完成）的影响需结合运行时语义分析，供 roadmap §1.3 在后续 step 补齐。
- 通道正交性与参数等价性需结合运行时业务模型深度校验，单机公理 A1~A5 映射关系需持续维护。

---

## 7. 文档漂移台账 (Documentation Drift Ledger)

- README.md §5 将 reaper.py 仅描述为 "Session log GC"，遗漏了其承载的 reclaim_stale_task（INV-1 唯一实现），将在 step07 进行职责收敛与文档修正。
- docs/architecture/README.md §3.3 示例中心跳格式若为 Token 在前，与 C2 冻结契约（时间在前 | Token 在后）存在冲突，将在 step05 统一原子同步。

---

## 8. 跳过与超限文件登记 (Skipped Files Ledger)

| 文件路径 | 文件大小 (字节) | 原因 |
| :--- | :--- | :--- |
| NONE | NONE | 暂无超过上限文件 |

---

## 9. 审计遥测直方图 (Audit Reasons Histogram)

<!-- BEGIN TELEMETRY (non-gated) -->
- 遥测状态: ok
- 样本总量: 83
- 评估结论: 样本充足

### 审计理由分布:
- `unknown`: 83
<!-- END TELEMETRY -->
