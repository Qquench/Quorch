# 2026-11-18_switch_license_to_apache2 Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-18

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 将项目开源协议从 MPL-2.0 切换为 Apache-2.0

#### 【涉及文件】
```
[MODIFY] LICENSE
[MODIFY] plugins/quench-dev-tasks/LICENSE
[MODIFY] README.md
[MODIFY] README_zh.md
[MODIFY] plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py
[MODIFY] plugins/quench-dev-tasks/server/adapters/base_adapter.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/manifest.py
[MODIFY] plugins/quench-dev-tasks/server/manifest_lease.py
[MODIFY] plugins/quench-dev-tasks/server/progress_bridge.py
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/reporting.py
[MODIFY] plugins/quench-dev-tasks/server/reviewer_jobs.py
[MODIFY] plugins/quench-dev-tasks/server/schema_validator.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/state_machine.py
[MODIFY] plugins/quench-dev-tasks/server/task_status.py
[MODIFY] plugins/quench-dev-tasks/server/workspace_lease.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_audit_gate.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_crashed_worker_ttl_recovery.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_global_config_layer.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_import_mode_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_import_topology_acyclic.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_install.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_lease_takeover_fencing.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_manifest_lease.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_no_deleted_module_refs.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_observability.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_poll_nonterminal_contract_v2.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_progress_bridge.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_prompt_cache_padding.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_python_floor_discipline.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reporting_render_golden.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_review_attestation_channel.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_watch.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_daemon_launch_canary.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_import_smoke.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_step_adjudication_invariants.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_templates.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_test_duration_gate.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_tool_surface_snapshot.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_touch_outcome_no_truthiness.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_workspace_lease.py
[MODIFY] scripts/check_prompt_surface.py
[MODIFY] scripts/install.py
[MODIFY] scripts/tool_surface_snapshot.py
[NEW] plugins/quench-dev-tasks/server/tests/test_license_header_consistency.py
```

#### 【缺陷根因与修改目标】
```
项目当前使用 Mozilla Public License 2.0 (MPL-2.0)，需将开源协议整体切换为更大众化的 Apache License 2.0 (Apache-2.0)，包括根目录与插件目录的 LICENSE 文件（两文件字节一致且为完整官方文本）、中英文 README 徽章与许可说明、全部 53 个含 MPL-2.0 头的 Python 源码文件，以及全仓只读零残留与集合等式回归守卫。
```

#### 【目标签名与类型契约】
```
FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "Mozilla" + " Public License", "MPL" + "-2.0", "MPL" + "_2.0", "MPL" + "--2.0",
    "MPL" + "%202.0", "MPL" + " 2.0", "MPL" + "2.0", "MPLv" + "2", "mozilla" + "." + "org",
)
APACHE_SPDX_LINE = "# SPDX-License-Identifier: Apache-2.0"
APACHE_NOTICE_LINE = "# Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)."
KNOWN_MPL_BEARING_FILES: tuple[str, ...] = (...)  # 53 .py relative paths only (excluding the 4 non-.py files)
SELF_REL_PATH = "plugins/quench-dev-tasks/server/tests/test_license_header_consistency.py"
EXPECTED_SPDX_SET: frozenset[str] = frozenset(KNOWN_MPL_BEARING_FILES) | {SELF_REL_PATH}  # 54 .py files
```

#### 【分步改造指引】
将根目录 LICENSE 与 plugins/quench-dev-tasks/LICENSE 替换为官方标准 Apache License, Version 2.0 全文（两文件字节一致）。
更新 README.md 与 README_zh.md 顶部 License 徽章为 Apache-2.0，移除 MPL-2.0 核心文件传染性描述，改为 Apache-2.0 宽松许可说明（仅陈述自本版本起采用 Apache-2.0，不提及既往协议名）。
对 KNOWN_MPL_BEARING_FILES（53 个 .py 文件）执行首块许可证注释清理并替换为 2 行 Apache-2.0 头（保留 shebang/encoding 行在前与原行尾 CRLF/LF）。
移除 test_reporting_render_golden.py 中的旧 MPL 许可证头断言（test_reporting_module_preserves_mpl2_license_header），四个 GOLDEN_*_SHA256 常量保持原值不动。
新增 test_license_header_consistency.py（自带 2 行 Apache-2.0 头，所有禁用词分片构造且注释/消息无禁用字面量）：实现全仓只读零残留断言、KNOWN_MPL_BEARING_FILES 逐文件块相等与 head[:5] 幂等断言、files_with_spdx == EXPECTED_SPDX_SET（54 个 .py）集合等式、has_spdx == has_notice 对称校验、双 LICENSE 与 README 正负向校验。

#### 【防御与边缘校验】
B-1 自引用防护：FORBIDDEN_FRAGMENTS 全部采用分片拼接（含 "mozilla" + "." + "org" 与 "MPL" + "--2.0"），且 test_license_header_consistency.py 的任何 docstring、注释与断言消息均严禁出现禁用字面量
B-2/H-2 实证无正文遗漏：已通过 git grep -n 验证全部 53 个 .py 文件仅首块（第 1-4 行）含 2 行 MPL 头，唯一正文命中为 test_reporting_render_golden.py:29-33（步骤 4 移除）；头替换定位到 shebang/encoding 之后并删除紧邻含旧头注释块后插入新 2 行头，保持 CRLF/LF 与 BOM 不变
B-3 Tier-1 预算安全：已核实 tests/conftest.py 采用 TIER1_TARGET_REL_FILES 显式白名单注入，test_license_header_consistency.py 不会进入 tier1_fast，无需修改 conftest.py
B-4 集合等式闭环：KNOWN_MPL_BEARING_FILES 仅包含【涉及文件】中的 53 个 .py 文件（不含 4 个非 .py 文件），且全仓事前无任何 SPDX-License-Identifier 声明，故 files_with_spdx == EXPECTED_SPDX_SET（共 54 项）精确成立
H-1/H-4 剪枝与锚点：全仓只读枚举剪枝 .git/.venv/__pycache__/node_modules/.pytest_cache/.agents/build/dist/.mypy_cache/.ruff_cache/.tox 以及 docs/dev_tasks 和任意 */archive/ 目录（排除 CHANGELOG.md 与 docs/roadmap/README.md）；REPO_ROOT 使用 docs/architecture/README.md 与 .agents/quench_stack.yaml 双锚点，缺失时 pytest.skip("not Quench core repo")；双 LICENSE 字节一致且 len > 10000；README 负向排除全部 FORBIDDEN_FRAGMENTS 且正向包含 {"Apache-2.0","Apache_2.0","Apache--2.0"}；严禁执行 export_ide_schemas.py --write

#### 【DoD 验证命令】
```bash
git grep -n -i -E "mozilla|mpl[-_ %]*2|mplv2" -- . ":(exclude)docs/dev_tasks" ":(exclude)*/archive" ":(exclude)CHANGELOG.md" ":(exclude)docs/roadmap/README.md" ; echo "exit=$? (expect 1)"
pytest plugins/quench-dev-tasks/server/tests/test_license_header_consistency.py -q --durations=1
pytest plugins/quench-dev-tasks/server/tests/test_reporting_render_golden.py -q
python -m compileall -q plugins/quench-dev-tasks/server plugins/quench-dev-tasks/scripts scripts
pytest plugins/quench-dev-tasks/server/tests -q -x
pytest -m tier1_fast -q
python scripts/check_test_tiering_invariants.py
python scripts/check_test_duration_baselines.py
python scripts/check_prompt_surface.py
python scripts/export_ide_schemas.py --check
```

---

