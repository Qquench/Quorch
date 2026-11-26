# 2026-11-26_v1_36_post_archival_ci_sync Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-26

---

## Task List & Status / 任务清单与状态

### 任务 36.15 ✔️ 已完成 — 路线图归档后资产清单黄金基线同步与跨平台 CI 测试固件加固

#### 【涉及文件】
```
[MODIFY] over_engineering_inventory.md
[MODIFY] plugins/quench-dev-tasks/server/tests/fixtures/asset_inventory_default_golden.txt
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch2_scope_and_config.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch4_reviewer_and_engine.py
```

#### 【缺陷根因与修改目标】
```
归档 docs/roadmap/v1.36_full_repo_audit_remediation_roadmap.md 至 docs/roadmap/archive/ 并更新 docs/roadmap/README.md 后，活跃消费文档引用集发生变化导致 scripts/asset_inventory.py --check 检测到 doc_refs 漂移；同时对照 docs/ci_incident_tracker_and_compatibility_guide.md 跨平台铁律 2（案例 1），收敛 test_v1_36_batch2_scope_and_config.py 中硬编码盘符/路径与 test_v1_36_batch4_reviewer_and_engine.py 中 tmp_path.parent 越界写文件问题，确保 Ubuntu/Windows 双矩阵 CI 100% 确定性全绿。
```

#### 【目标签名与类型契约】
```
纯测试夹具与资产盘点快照同步，不改变任何生产函数签名或运行时行为。
```

#### 【分步改造指引】
1. 在 test_v1_36_batch2_scope_and_config.py 中使用 tmp_path / 'ws' 与 tmp_path / 'outside' 构造宿主原生工作区外部路径及 brain 制品路径，同时消除 /tmp 与 Z:/ 硬编码字面量。
2. 在 test_v1_36_batch4_reviewer_and_engine.py::test_architecture_doc_path_traversal_confined 中将越界探针文件置于 tmp_path / 'outside_secret_arch.md'（对应 ws = tmp_path / 'ws' 的 ../outside_secret_arch.md），避免写入 tmp_path.parent 并确保真实相对穿透验证。
3. 运行 scripts/asset_inventory.py --write 更新 over_engineering_inventory.md，并将 strip_delta_block 后的纯投影同步至 asset_inventory_default_golden.txt，验证 --check 与 pytest 全绿。

#### 【防御与边缘校验】
严守 CI 兼容铁律 2（零硬编码盘符与 /tmp 路径，全部基于 tmp_path 派生）
严守 SPDX 54 文件冻结集（不在测试文件头部添加 SPDX 注释）
确保 scripts/asset_inventory.py --check 返回码为 0 且 golden 夹具零漂移

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch2_scope_and_config.py plugins/quench-dev-tasks/server/tests/test_v1_36_batch4_reviewer_and_engine.py plugins/quench-dev-tasks/server/tests/test_asset_inventory.py plugins/quench-dev-tasks/server/tests/test_license_header_consistency.py -q
```

---

