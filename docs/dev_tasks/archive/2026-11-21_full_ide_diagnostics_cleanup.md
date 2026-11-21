# 2026-11-21_full_ide_diagnostics_cleanup Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-21

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — Pyrefly 配置对齐与根目录 scripts/ 静态诊断清零

#### 【涉及文件】
```
[MODIFY] pyproject.toml
[MODIFY] plugins/quench-dev-tasks/server/pyproject.toml
[MODIFY] scripts/_introspect_schemas_child.py
[MODIFY] scripts/asset_inventory.py
[MODIFY] scripts/check_prompt_surface.py
[MODIFY] scripts/check_test_duration_baselines.py
[MODIFY] scripts/export_ide_schemas.py
[MODIFY] scripts/install.py
[MODIFY] scripts/measure_tool_response_sizes.py
```

#### 【缺陷根因与修改目标】
```
根因：pyproject.toml 与 server/pyproject.toml 中 [tool.pyrefly] search-path 缺失 plugins/quench-dev-tasks/scripts 与 plugins/quench-dev-tasks/server/hooks，导致 28 处合法运行时动态导入触发 missing-import；且 PyYAML 缺少 stub 触发 28 处 untyped-import 警告；此外 scripts/ 下存在未导入 Any、bad-return (int | str)、未使用导入/变量等诊断。目标：对齐 Pyrefly search-path 与错误过滤配置，并修复 scripts/ 全部静态诊断。
```

#### 【目标签名与类型契约】
```
pyproject.toml: [tool.pyrefly] search-path 包含 scripts, plugins/quench-dev-tasks/scripts, plugins/quench-dev-tasks/server, plugins/quench-dev-tasks/server/hooks, plugins/quench-dev-tasks/server/tests；[tool.pyrefly.errors] untyped-import = "ignore"
```

#### 【分步改造指引】
1. 在根 pyproject.toml 与 plugins/quench-dev-tasks/server/pyproject.toml 的 [tool.pyrefly] search-path 中补充 plugins/quench-dev-tasks/scripts 与 plugins/quench-dev-tasks/server/hooks（server/pyproject.toml 使用相对路径 ../scripts 与 hooks），并在 [tool.pyrefly.errors] 补充 untyped-import = "ignore"。
2. 修复 scripts/_introspect_schemas_child.py 与 scripts/measure_tool_response_sizes.py 缺失的 typing.Any 导入，并清理后者未使用的 os / canonical_json 导入。
3. 修复 scripts/asset_inventory.py:1643 返回类型 int | str 与声明 -> int 不一致的问题。
4. 清理 scripts/check_prompt_surface.py、scripts/check_test_duration_baselines.py、scripts/install.py 中的 F401/F841/E741 与 sys.std*.reconfigure 类型窄化问题，保持现有运行时行为不变。

#### 【防御与边缘校验】
- 保持 pyproject.toml 中已有 search-path 与 unnecessary-type-conversion 配置不丢失
- 不向 requirements.txt 新增额外运行期依赖；yaml stub 告警通过 untyped-import = "ignore" 消除
- 验证 scripts/export_ide_schemas.py --check 与 scripts/check_prompt_surface.py 仍 100% 通过

#### 【DoD 验证命令】
```bash
uvx pyrefly check --min-severity=warn --output-format min-text scripts/
uvx ruff check --isolated --select F821,F822,F811,F841,F541,E731,E741 scripts/
.\.venv\Scripts\python.exe scripts/export_ide_schemas.py --check && .\.venv\Scripts\python.exe scripts/check_prompt_surface.py
```

---

### 任务 1.2 ✔️ 已完成 — 插件脚本与 Hook 层 Pyrefly/Ruff 诊断修复

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/scripts/check_no_api_bypass.py
[MODIFY] plugins/quench-dev-tasks/scripts/config_sync.py
[MODIFY] plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py
[MODIFY] plugins/quench-dev-tasks/scripts/init_project.py
[MODIFY] plugins/quench-dev-tasks/scripts/probe_client_capabilities.py
[MODIFY] plugins/quench-dev-tasks/scripts/rules_exporter.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/context_injector.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
```

#### 【缺陷根因与修改目标】
```
根因：plugins/quench-dev-tasks/scripts 与 server/hooks 存在 TextIO.reconfigure 报错、config_sync str|None 入参、probe_client_capabilities 不可达 except TimeoutError、context_injector 向 ReviewerClient 传入 QuenchStackConfig 类型不匹配及未使用导入/变量。目标：全面修复脚本与 Hook 层 Pyrefly 与 Ruff 静态诊断。
```

#### 【目标签名与类型契约】
```
isinstance(sys.stdout, io.TextIOWrapper) 窄化后调用 .reconfigure(encoding="utf-8")；ReviewerClient(config=...) 接收 ReviewerEngineConfig | None
```

#### 【分步改造指引】
1. 为 check_no_api_bypass.py、git_pre_commit_guard.py、init_project.py、rules_exporter.py、context_injector.py、file_scope_guard.py 的 sys.stdin/stdout/stderr.reconfigure 添加 isinstance(..., io.TextIOWrapper) 类型窄化。
2. 修复 config_sync.py:391 project_root 为 str | None 的窄化保护。
3. 修复 probe_client_capabilities.py:317 不可达的 TimeoutError 捕获分支（按具体子类到基类顺序或合并处理）。
4. 修复 context_injector.py:81 传入 ReviewerClient 的 config 类型（应提取 ReviewerEngineConfig 或做类型窄化）。
5. 清理上述文件中的 F401 未使用导入与 F841 未使用变量（确认无副作用导入或对外再导出破坏）。

#### 【防御与边缘校验】
- sys.stdin/stdout/stderr reconfigure 必须使用 io.TextIOWrapper 类型窄化或安全属性检查，严禁破坏 Windows UTF-8 控制台输出与 stdio 契约
- hooks 变更后必须保证相关 hook / guard / sync 单测 100% 通过

#### 【DoD 验证命令】
```bash
uvx pyrefly check --min-severity=warn --output-format min-text plugins/quench-dev-tasks/scripts/ plugins/quench-dev-tasks/server/hooks/
uvx ruff check --isolated --select E7,E9,F plugins/quench-dev-tasks/scripts/ plugins/quench-dev-tasks/server/hooks/
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; .\.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_config_sync.py plugins/quench-dev-tasks/server/tests/test_init_project.py plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py plugins/quench-dev-tasks/server/tests/test_no_api_bypass.py plugins/quench-dev-tasks/server/tests/test_pre_commit_guard.py plugins/quench-dev-tasks/server/tests/test_probe_client_capabilities.py plugins/quench-dev-tasks/server/tests/test_rules_exporter.py -q
```

---

### 任务 1.3 ✔️ 已完成 — 核心服务端基础模块 Pyrefly 与 Ruff 诊断清零

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/cli.py
[MODIFY] plugins/quench-dev-tasks/server/code_explorer.py
[MODIFY] plugins/quench-dev-tasks/server/ide_schema_export.py
[MODIFY] plugins/quench-dev-tasks/server/log_naming.py
[MODIFY] plugins/quench-dev-tasks/server/manifest.py
[MODIFY] plugins/quench-dev-tasks/server/manifest_lease.py
[MODIFY] plugins/quench-dev-tasks/server/path_guard.py
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/response_compactor.py
[MODIFY] plugins/quench-dev-tasks/server/runtime_mode.py
[MODIFY] plugins/quench-dev-tasks/server/schema_validator.py
[MODIFY] plugins/quench-dev-tasks/server/state_machine.py
[MODIFY] plugins/quench-dev-tasks/server/task_writer.py
[MODIFY] plugins/quench-dev-tasks/server/workspace_lease.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
```

#### 【缺陷根因与修改目标】
```
根因：服务端核心模块存在未导入类型符号（manifest.Final、project_config.Sequence）、未初始化变量（cli source_label/local_override_loaded）、None 窄化缺失（code_explorer end_lineno）、重复定义（server DispatchStrategy）、不可达 except（manifest PermissionError）、contextlib.contextmanager 弃用重载警告（workspace_lease:242）及 F401/F841/F541/E741。目标：全面清零上述核心服务端模块 Pyrefly 与 Ruff 静态诊断。
```

#### 【目标签名与类型契约】
```
manifest.py 导入 Final；project_config.py 导入 Sequence；server.py 仅保留单一 DispatchStrategy 契约定义
```

#### 【分步改造指引】
1. 修复 cli.py：reconfigure 类型窄化、初始化 source_label/local_override_loaded、修正 -> int 返回类型、清理 F541 f-string。
2. 修复 code_explorer.py：为 end_lineno 提供 int 窄化/默认值，清理未使用导入/变量。
3. 修复 manifest.py：补充 typing.Final 导入，移除被 OSError 遮蔽的不可达 PermissionError 子句，清理未使用导入。
4. 修复 project_config.py：补充 Sequence 导入，修复 L526 int(...) 参数类型窄化。
5. 修复 runtime_mode.py:188 Literal['inverted', 'standard'] 类型窄化；修复 workspace_lease.py:242 contextlib.contextmanager 重载弃用告警；清理 server.py DispatchStrategy 重复定义及安全清理各文件 F401/F841/E741。

#### 【防御与边缘校验】
- 严禁改变 server.py 注册的 16 个 MCP 工具签名、schema 与返回值契约（必须通过 export_ide_schemas.py --check 与 test_tool_surface_snapshot.py）
- 严禁触发架构卫生门禁（vendor_literal_in_core / api_bypass / touch_outcome_truthiness）

#### 【DoD 验证命令】
```bash
uvx pyrefly check --min-severity=warn --output-format min-text plugins/quench-dev-tasks/server/cli.py plugins/quench-dev-tasks/server/code_explorer.py plugins/quench-dev-tasks/server/ide_schema_export.py plugins/quench-dev-tasks/server/log_naming.py plugins/quench-dev-tasks/server/manifest.py plugins/quench-dev-tasks/server/manifest_lease.py plugins/quench-dev-tasks/server/path_guard.py plugins/quench-dev-tasks/server/project_config.py plugins/quench-dev-tasks/server/response_compactor.py plugins/quench-dev-tasks/server/runtime_mode.py plugins/quench-dev-tasks/server/schema_validator.py plugins/quench-dev-tasks/server/state_machine.py plugins/quench-dev-tasks/server/task_writer.py plugins/quench-dev-tasks/server/workspace_lease.py plugins/quench-dev-tasks/server/server.py
uvx ruff check --isolated --select E7,E9,F plugins/quench-dev-tasks/server/cli.py plugins/quench-dev-tasks/server/code_explorer.py plugins/quench-dev-tasks/server/ide_schema_export.py plugins/quench-dev-tasks/server/log_naming.py plugins/quench-dev-tasks/server/manifest.py plugins/quench-dev-tasks/server/manifest_lease.py plugins/quench-dev-tasks/server/path_guard.py plugins/quench-dev-tasks/server/project_config.py plugins/quench-dev-tasks/server/response_compactor.py plugins/quench-dev-tasks/server/runtime_mode.py plugins/quench-dev-tasks/server/schema_validator.py plugins/quench-dev-tasks/server/state_machine.py plugins/quench-dev-tasks/server/task_writer.py plugins/quench-dev-tasks/server/workspace_lease.py plugins/quench-dev-tasks/server/server.py
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; .\.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py plugins/quench-dev-tasks/server/tests/test_tool_surface_snapshot.py plugins/quench-dev-tasks/server/tests/test_server_import_smoke.py plugins/quench-dev-tasks/server/tests/test_cli.py plugins/quench-dev-tasks/server/tests/test_workspace_lease.py plugins/quench-dev-tasks/server/tests/test_project_config.py plugins/quench-dev-tasks/server/tests/test_server_tools.py -q
```

---

### 任务 1.4 ✔️ 已完成 — consultation / reviewer_engine / reviewer_jobs 运行时隐患与静态诊断修复

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/consultation.py
[MODIFY] plugins/quench-dev-tasks/server/reviewer_engine.py
[MODIFY] plugins/quench-dev-tasks/server/reviewer_jobs.py
```

#### 【缺陷根因与修改目标】
```
根因：consultation.py 存在未导入 sys/Callable（F821）、filelock 可能未绑定、end_line 缺 None 窄化、findings 为 UsageSnapshot|dict|str 联合类型未收窄等 15 项 Pyrefly 错误；reviewer_engine.py 存在 file_msg 未初始化、create_task 接收 Awaitable、reconfigure 报错；reviewer_jobs.py 存在 JobState/JobProgress/mode 类型不匹配与不可达 FileNotFoundError 分支。目标：消除这 3 个核心引擎模块的运行期 NameError 隐患与全部 Pyrefly/Ruff 诊断。
```

#### 【目标签名与类型契约】
```
ConsultResult.findings: str；CodeSlice.end_line: int；JobRecord.state: JobState；JobRecord.progress: JobProgress
```

#### 【分步改造指引】
1. 修复 consultation.py：补充 import sys 与 Callable，保证 filelock 总是已定义（可为 None 判空），收窄 start_line/end_line 为 int，将 findings 提取为确定性 str 后再传给正则和 ConsultResult，并清理 F401。
2. 修复 reviewer_engine.py：reconfigure 类型窄化，在异常分支前初始化 file_msg，修正 create_task 入参为 Coroutine，保留 DeepSeekClient PEP 562 兼容层并为 __all__ 添加适当 Ruff 豁免注释（如需），清理 F401。
3. 修复 reviewer_jobs.py：修正 L671 dict 中 state 的 JobState 类型、L711 progress 默认 JobProgress、L1277 mode 的 Literal 校验/窄化，移除 L1869-1883 不可达的 FileNotFoundError 分支，清理 F401。

#### 【防御与边缘校验】
- consultation.py 缺失 sys / Callable 与未绑定 filelock 属于真实运行期 NameError/UnboundLocalError 隐患，必须完整导入并加防御性保护
- reviewer_engine.py 必须保留 PEP 562 __getattr__ 与 __all__ 中的 DeepSeekClient 弃用兼容别名（带 # vendor-literal: allow 与必要 noqa），不得破坏 test_handoff_protocol.py 等测试
- 严禁更改 ReviewerJobSupervisor 状态机与 PollSnapshot V2 契约

#### 【DoD 验证命令】
```bash
uvx pyrefly check --min-severity=warn --output-format min-text plugins/quench-dev-tasks/server/consultation.py plugins/quench-dev-tasks/server/reviewer_engine.py plugins/quench-dev-tasks/server/reviewer_jobs.py
uvx ruff check --isolated --select E7,E9,F plugins/quench-dev-tasks/server/consultation.py plugins/quench-dev-tasks/server/reviewer_engine.py plugins/quench-dev-tasks/server/reviewer_jobs.py
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; .\.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_watch.py plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py -q
```

---

### 任务 1.5 ✔️ 已完成 — 测试套件 Pyrefly 静态类型诊断全量清零

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_adapters.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_agents_md_template.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_audit_gate.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_coalescing_sink.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_config_sync.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_consultation_telemetry.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_cursor_init.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_file_scope_guard_hardening.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_init_project.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_install.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_log_quota_cross_process.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_no_api_bypass.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_observability.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_observability_policy.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_pre_commit_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_probe_client_capabilities.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_progress_bridge.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_project_config.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_project_config_migration.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_review_attestation_channel.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_bad_request.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_watch.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_rules_exporter.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_tools.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_shell_write_bypass.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_snapshot_drift_gate_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_workspace_lease.py
```

#### 【缺陷根因与修改目标】
```
根因：测试套件存在大量 Pyrefly 静态报错（如 test_reviewer_jobs_watch 74 处解包字典类型、test_audit_gate 36 处 TaskItem vs TaskEntry affected_files 属性差异、test_progress_bridge 10 处 None 窄化、test_reviewer_jobs 8 处 None 窄化与 PollSnapshot progress 类型、HTTPError hdrs=Message() 传参、以及 search-path 补充后可能暴露的新报错）。目标：实现全部测试文件 Pyrefly 0 错误 0 警告。
```

#### 【目标签名与类型契约】
```
保持原有测试语义与负向测试覆盖不变，uvx pyrefly check --min-severity=warn 全量 0 诊断
```

#### 【分步改造指引】
1. 先运行 uvx pyrefly check --min-severity=warn plugins/quench-dev-tasks/server/tests/ 获取更新 search-path 后的完整测试诊断列表。
2. 修复 test_reviewer_jobs_watch.py 等测试中字典解包构造 JobRecord 的类型标注、test_audit_gate.py 与 test_review_attestation_channel.py 中的 Task 模拟对象类型、test_reviewer_jobs.py / test_progress_bridge.py / test_dual_source_reconcile.py 的 assert is not None 窄化。
3. 修复 HTTPError(..., hdrs=Message(), ...)（test_reviewer_bad_request / test_reviewer_engine / test_reviewer_engine_probe）、test_install.py winerror/OSError 模拟、test_snapshot_contract.py PollSnapshot 参数类型、test_server_tools.py 等诊断。
4. 同步清理上述测试文件中的 Ruff F401/F841/F811/E731/E741。

#### 【防御与边缘校验】
- 严禁弱化任何测试断言；对于有意测试非法入参（如 test_server_tools 传 raw_text/not_a_number、test_project_config_migration 传 BadObj、test_coalescing_sink 测只读冻结）的负向测试，使用局部精确 # pyrefly: ignore[...] 或 typing.cast/setattr 保持测试真实攻击面
- 所有修改的测试文件必须 100% 通过 pytest

#### 【DoD 验证命令】
```bash
uvx pyrefly check --min-severity=warn --output-format min-text plugins/quench-dev-tasks/server/tests/
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; .\.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_watch.py plugins/quench-dev-tasks/server/tests/test_audit_gate.py plugins/quench-dev-tasks/server/tests/test_progress_bridge.py plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py plugins/quench-dev-tasks/server/tests/test_server_tools.py plugins/quench-dev-tasks/server/tests/test_install.py -q
```

---

### 任务 1.6 ✔️ 已完成 — 测试套件 Ruff 卫生清理与全仓零诊断终态验收

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/_hygiene/scanner.py
[MODIFY] plugins/quench-dev-tasks/server/tests/_tool_surface_expectations.py
[MODIFY] plugins/quench-dev-tasks/server/tests/fixtures/response_payloads.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_agents_md_sync.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_architecture_doc_anchor_integrity.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_asset_inventory.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_ast_slice_cache_determinism.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_cache_telemetry.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_cli.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_code_explorer_cursor_and_progressive.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_config_migration.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_consultation_multihop.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_crashed_worker_ttl_recovery.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_doc_contract_hygiene.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_dod_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_draft_lint.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_dual_mode_runtime_switch.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_duration_baselines_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_export_ide_schemas_cli.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_global_config_layer.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_hooks.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_ide_schema_export.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_lease_takeover_fencing.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_log_naming.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_manifest_lease.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_missing_sentinel_singleton.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_parity_scope.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_poll_nonterminal_contract_v2.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_prompt_cache_padding.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_prompt_cache_stability.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_prompt_layout_criterion.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_response_budget_ssot.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_response_compactor.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_engine_stream.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_heartbeat.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_heartbeat_format.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_ctx_schema_invariance.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_longpoll_v124.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_prompt_proportionality.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_schema_validator.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_daemon_launch_canary.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_import_smoke.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_spec_refine.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_state_machine.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_task_file_write_guarded.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_templates.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_test_duration_gate.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_tiering_gate_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_tool_response_slim.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_tool_surface_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_tool_surface_snapshot.py
```

#### 【缺陷根因与修改目标】
```
根因：剩余测试文件及辅助模块（含用户当前打开的 test_tool_surface_snapshot.py、test_templates.py、test_test_duration_gate.py、test_server_import_smoke.py）存在未使用导入（F401）、未使用局部变量（F841）、冗余 f-string（F541）与易混淆变量名 l（E741）。目标：完成全仓测试文件卫生清理并通过全仓 Pyrefly/Ruff/pytest 终态验收。
```

#### 【目标签名与类型契约】
```
全仓 Pyrefly check (--min-severity=warn) 0 errors / 0 warnings；全量 pytest 通过
```

#### 【分步改造指引】
1. 清理上述测试文件中的 F401 未使用导入、F841 未使用变量、F541 冗余 f-string 与 E741 变量名。
2. 运行全仓 uvx pyrefly check --min-severity=warn --output-format min-text . 确认 0 diagnostics。
3. 运行全仓 uvx ruff check --isolated --select E7,E9,F . 确认除有意 PEP 562 豁免外 0 违规。
4. 运行全量 pytest 与 export_ide_schemas.py --check 验收回归。

#### 【防御与边缘校验】
- 严禁删除任何具有副作用或探测模块可导入性的 try/except 导入语句；确认仅清理真正冗余未使用的导入与局部变量
- 完成全部清理后必须对全仓运行 Pyrefly 与 Ruff 检查以及全量 pytest 回归验收

#### 【DoD 验证命令】
```bash
uvx pyrefly check --min-severity=warn --output-format min-text .
uvx ruff check --isolated --select E7,E9,F .
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; .\.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests -q --tb=short
```

---

