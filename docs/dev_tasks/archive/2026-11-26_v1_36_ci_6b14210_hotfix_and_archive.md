# 2026-11-26_v1_36_ci_6b14210_hotfix_and_archive Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-26

---

## Task List & Status / 任务清单与状态

### 任务 36.16 ✔️ 已完成 — 修复 6b14210 双平台 CI 失败并同步归档资产基线

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_dod_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_log_naming.py
[MODIFY] docs/architecture/over_engineering_inventory.md
[MODIFY] plugins/quench-dev-tasks/server/tests/fixtures/asset_inventory_default_golden.txt
```

#### 【缺陷根因与修改目标】
```
修复提交 6b14210 在 GitHub Actions CI（Run 45786190281）暴露的 2 处真实失败并在闭环后归档 CI 故障报告与旧反锚定路线图，同步资产黄金基线：(1) 无外部 API Key 环境下 dev_tasks_checkout 触发 auto_fallback inverted 生成 .agents/.quench_runtime_mode.json，在缺省 governance_scope 下被 QuenchStackConfig.is_path_governed 误判为受管生产代码变更，导致 test_dod_guard_natural_pass_on_docs_only 在 Windows+Ubuntu 双红；(2) test_gc_with_active_registry_zero_stat 在激活 os.stat 抛错桩期间调用 os.path.exists(pinned_path)，在 Ubuntu POSIX 下 genericpath.exists 调用 os.stat 自爆。
```

#### 【目标签名与类型契约】
```
保持所有工具与配置类签名不变；is_path_governed('.agents/.quench_runtime_mode.json') -> False，而 is_path_governed('.agents/quench_stack.yaml') 仍保持 True。
```

#### 【分步改造指引】
1. 在 project_config.py::QuenchStackConfig.is_path_governed 智能推断分支中将 .agents/.quench_* 内部运行态瞬态文件（如 .quench_runtime_mode.json / .quench_bypass.json / .quench_stop_guard.json 等）识别为非受管运行态元数据；同时在 server.py::dev_tasks_checkout 中仅当 cumulative_runner_tasks > 0 时执行归零写盘。
2. 在 test_dod_guard.py::test_dod_guard_natural_pass_on_docs_only 中补强无外部 API（_is_external_api_available=False）回归覆盖；在 test_log_naming.py::test_gc_with_active_registry_zero_stat 中改用 with monkeypatch.context() 隔离打桩范围并在桩内用 os.listdir 验证存活，桩外再校验 os.path.exists。
3. 归档 docs/ci_failure_report_2026-11-26_6b14210.md 至 docs/architecture/archive/，执行 scripts/asset_inventory.py --write 并同步 asset_inventory_default_golden.txt，验证 --check 与单测全绿。

#### 【防御与边缘校验】
is_path_governed 仅豁免 .agents/.quench_* 内部运行态瞬态文件，绝不豁免 quench_stack.yaml / quench_stack.local.yaml / hooks.json / mcp_config.json / plugins.json
test_gc_with_active_registry_zero_stat 使用 monkeypatch.context() 与 os.listdir，在 POSIX 与 Windows 下均满足零 stat 断言且不污染 pytest teardown
严守 SPDX 54 文件冻结集与资产清单黄金基线零漂移

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_dod_guard.py plugins/quench-dev-tasks/server/tests/test_log_naming.py plugins/quench-dev-tasks/server/tests/test_asset_inventory.py plugins/quench-dev-tasks/server/tests/test_license_header_consistency.py -q
```

---

