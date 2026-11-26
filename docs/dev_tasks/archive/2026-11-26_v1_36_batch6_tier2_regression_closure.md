# 2026-11-26_v1_36_batch6_tier2_regression_closure Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-26

---

## Task List & Status / 任务清单与状态

### 任务 36.12 ✔️ 已完成 — 收口全量 Tier-2 回归发现的 Tier-1 采集耗时、Form C 非终态、SPDX 头与 Shell 兜底标记

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/conftest.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_code_explorer.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch2_scope_and_config.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch3_state_and_leases.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch4_reviewer_and_engine.py
[MODIFY] plugins/quench-dev-tasks/server/reviewer_jobs.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] docs/architecture/over_engineering_inventory.md
[MODIFY] plugins/quench-dev-tasks/server/tests/fixtures/asset_inventory_default_golden.txt
```

#### 【缺陷根因与修改目标】
```
根因：全量 Tier-2 回归 (1417 项用例) 发现 4 处细节契约偏差：(1) pytest -m tier1_fast 采集阶段仍导入全部 135 个测试文件导致冷启动耗时 ~8.5s 触及 8.0s 硬红线；(2) test_v1_36_batch4_reviewer_and_engine.py 写了 SPDX 头但漏写第 2 行 Licensed under Apache-2.0 声明；(3) reviewer_jobs.py 将 CANCELLED_PENDING_REAP 纳入轮询期孤儿态导致 Form C 非终态契约测试被误投影为终态；(4) file_scope_guard.detect_shell_write_bypass 参数化 clean_dir 后移除了内置 'dev_tasks' 兜底标记。目标：精准修复上述 4 处偏差，达成全仓 Tier-2 零失败收口。
```

#### 【目标签名与类型契约】
```
def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None
```

#### 【分步改造指引】
1. 在 plugins/quench-dev-tasks/server/tests/conftest.py 新增 pytest_ignore_collect(collection_path, config)：当 getattr(config.option, 'markexpr', '').strip() == 'tier1_fast' 且 collection_path.suffix == '.py' 且 collection_path.name.startswith('test_') 且 collection_path.name not in TIER1_TARGET_REL_FILES 时返回 True，消除非 Tier-1 重型测试文件的采集导入开销。
2. 在 test_v1_36_batch4_reviewer_and_engine.py 第 2 行补齐标准 '# Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).' 头注释。
3. 在 reviewer_jobs.py 中保持 CANCELLED_PENDING_REAP 在 _read_snapshot_sync / poll 中作为 Form C 非终态 (POLL_NONTERMINAL_FIELDS) 返回（仅 QUEUED/RUNNING 在 poll/watch 探针中转为 ORPHANED；CANCELLED_PENDING_REAP 的异代超时清理仅在 reconcile_on_load 中执行）。
4. 在 hooks/file_scope_guard.py 的 detect_shell_write_bypass 兜底正则中同时匹配 (?:{re.escape(clean_dir)}|dev_tasks)，兼顾自定义任务目录与内置 dev_tasks 标记保护。
5. 运行 scripts/asset_inventory.py --write 并在发生变动时同步 asset_inventory_default_golden.txt，验证全部 6 个此前失败测试模块 100% 通过。

#### 【防御与边缘校验】
- conftest.py 的 pytest_ignore_collect 仅在 config.option.markexpr.strip() == 'tier1_fast' 时跳过非 TIER1_TARGET_REL_FILES 测试模块，确保全量回归与 -k 表达式采集 100% 不受影响，且 check_test_tiering_invariants.py 与 check_test_duration_baselines.py 全绿！
- CANCELLED_PENDING_REAP 在 supervisor.poll() / _read_snapshot_sync() 中严格保持 Form C 非终态投影 (POLL_NONTERMINAL_FIELDS)，仅在 reconcile_on_load() 跨进程启动对账时回收超时残留记录！
- detect_shell_write_bypass 的兜底正则同时包含 re.escape(clean_dir) 与默认 'dev_tasks' 标记，确保 test_shell_write_bypass.py 全量通过！

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe scripts/asset_inventory.py --write && .venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_duration_baselines_contract.py plugins/quench-dev-tasks/server/tests/test_tiering_gate_contract.py plugins/quench-dev-tasks/server/tests/test_license_header_consistency.py plugins/quench-dev-tasks/server/tests/test_reviewer_unified_async.py plugins/quench-dev-tasks/server/tests/test_shell_write_bypass.py plugins/quench-dev-tasks/server/tests/test_v1_36_batch4_reviewer_and_engine.py plugins/quench-dev-tasks/server/tests/test_asset_inventory.py -q --tb=short
```

---

