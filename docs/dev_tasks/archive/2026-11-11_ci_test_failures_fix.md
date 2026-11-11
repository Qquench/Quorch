# 2026-11-11_ci_test_failures_fix Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-11

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 修复跨平台路径拒绝、安装模板键名、Poll测试签名及卫生审计白名单

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/code_explorer.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_code_explorer_cursor_and_progressive.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_install.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_ctx_schema_invariance.py
[MODIFY] plugins/quench-dev-tasks/server/tests/_hygiene/rules.py
```

#### 【缺陷根因与修改目标】
```
根因：1. code_explorer 在 POSIX 系统下由于 os.path.isabs('C:/Windows') == False 被误当做相对路径拼接到工作区内部导致逃逸。2. v1.31 将 mcp_config.json.template 的 server 名更新为 'core'，test_install.py 仍旧断言旧名 'quench-dev-tasks'。3. v1.31 删减了 dev_reviewer_poll 文档中的双语冗余，而 test_reviewer_poll_ctx_schema_invariance 中的测试签名未同步精简。4. v1.33 新增的 response_compactor.py 未在 rules.py 的 MERGED_FILE_SCOPE_ALLOWLIST 中登记。目标：修复上述4项缺陷，确保跨平台根路径防御、安装模板、Shadow Schema 与 Hygiene Allowlist 全部对齐通过。
```

#### 【目标签名与类型契约】
```
resolve_within_roots(workspace_root: str, target_path: str, allowed_roots: Optional[Sequence[str]] = None) -> Optional[Tuple[str, str]] 契约不变；MERGED_FILE_SCOPE_ALLOWLIST 包含 3 项新条目；pending_dev_reviewer_poll 参数签名完全对准 Context。
```

#### 【分步改造指引】
1. 在 code_explorer.py 中引入 from pathlib import PureWindowsPath，在既有盘符根拒绝分支后加入语义差分判据：if not os.path.isabs(norm) and PureWindowsPath(norm).is_absolute(): return None。并在 test_code_explorer_cursor_and_progressive.py 中强化跨平台测试用例。
2. 修改 test_install.py 中 test_render_configs_success 断言，将其由 'quench-dev-tasks' 更新为 'core'。
3. 同步 test_reviewer_poll_ctx_schema_invariance.py 中 pending_dev_reviewer_poll 的 docstring 为英文紧凑契约，匹配 server.py 与 ide_tool_schemas.json。
4. 在 tests/_hygiene/rules.py 的 MERGED_FILE_SCOPE_ALLOWLIST 中登记 ('api_bypass', 'server/response_compactor.py')、('touch_outcome_truthiness', 'server/response_compactor.py')、('vendor_literal_in_core', 'server/response_compactor.py')。

#### 【防御与边缘校验】
- PureWindowsPath(norm).is_absolute() 仅在 not os.path.isabs(norm) 时生效，Windows 平台原生绝对路径（如 C:/ws/...）不被误伤。
- test_install.py 针对 core 单一标准键断言，拒绝模糊 fallback 兜底。
- rules.py 中 MERGED_FILE_SCOPE_ALLOWLIST 登记的 response_compactor.py 经由 test_parity_scope 双向对齐校验，且通过 test_architecture_hygiene 扫描（0 vendor literal, 0 api bypass）。
- pending_dev_reviewer_poll 的 docstring 与 server.py 完全一致，通过 test_shadow_schema_matches_pending_poll_signature 物理字节级相等校验。

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_code_explorer_cursor_and_progressive.py::test_a6_root_rejection_family -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_install.py::test_render_configs_success -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_reviewer_poll_ctx_schema_invariance.py::test_shadow_schema_matches_pending_poll_signature -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_parity_scope.py::test_tp3_zero_net_coverage_loss_and_allowlist -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -v
```

---

### 任务 1.2 ✔️ 已完成 — 修复响应压缩截断保留、RefineSpec核心键保全及可观测性测试鲁棒性

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/response_compactor.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_task_file_write_guarded.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_observability.py
```

#### 【缺陷根因与修改目标】
```
根因：1. dev_tasks_refine_spec 的 fit_to_budget 遗漏了 'refined' 字段于 always_keep，当离线降级字典超预算触发 Tier-2 截断时导致 'refined' 被删除。2. test_manifest_reconciliation 默认调用 compact 模式，当 CI 临时目录路径较长时触发 files 截断导致 KeyError: 'files'。3. fit_to_budget 中 truncated_sections 在候选项超预算时被直接丢弃，导致截断透明度丢失。4. test_observability 中 test_full_superset_invariant 与 test_compact_status_40_tasks_bounded 在 CI 环境下因长路径导致 compact keys 差异。目标：修复截断保留逻辑与 refine_spec 核心保留契约，完善测试调用契约，消除 CI 失败。
```

#### 【目标签名与类型契约】
```
fit_to_budget(tool_name: str, payload: Any, *, drop_order: Sequence[str] | None = None, always_keep: Sequence[str] | None = None, phase: str = 'default') -> dict[str, Any] 纯函数契约；dev_tasks_status 紧凑与全量模式契约对齐。
```

#### 【分步改造指引】
1. 在 server.py 的 dev_tasks_refine_spec 中，为 fit_to_budget 的 always_keep 添加 'refined', 'degraded', 'persisted'。并在 test_task_file_write_guarded.py 中验证断言。
2. 在 response_compactor.py 中优化 fit_to_budget：截断发生时确保 truncated_sections 作为必要元数据注入并参与最终尺寸校验，保持在 budget 门禁内。
3. 在 test_manifest_reconciliation.py 中将 test_dev_tasks_status_reports_bypass_queue 的 dev_tasks_status 调用显式设置为 verbosity='full'。
4. 在 test_observability.py 中审视并加固 test_compact_status_40_tasks_bounded 和 test_full_superset_invariant 对环境路径长度波动的鲁棒性。

#### 【防御与边缘校验】
- dev_tasks_refine_spec 中 always_keep 包含 refined, degraded, persisted，确保紧凑模式降级时不丢失核心状态。降级路径下 findings == '' 满足 INV-3。
- fit_to_budget 确保 truncated_sections 作为可观测性必要元数据，在截断发生时予以保留，同时最终总字节 len(canonical_json(result).encode('utf-8')) <= budget 满足 INV-10。
- test_manifest_reconciliation.py 明确以 verbosity='full' 模式断言全量 files 队列，契合审计业务场景。
- test_observability.py 全量超集与紧凑边界测试适配动态环境下的路径长度，同时保持 INV-10 硬性字节门禁。

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_task_file_write_guarded.py::test_refine_spec_persist_success_async_thread -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py::test_dev_tasks_status_reports_bypass_queue -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_observability.py::test_compact_status_40_tasks_bounded plugins/quench-dev-tasks/server/tests/test_observability.py::test_full_superset_invariant -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_response_compactor.py -v
```

---

