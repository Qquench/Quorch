# 2026-11-27_ci_tier1_fast_budget_fix Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-27

---

## Task List & Status / 任务清单与状态

### 任务 36.17 ✔️ 已完成 — 修复 Windows CI Tier-1 耗时红灯：重型用例归位 Tier-2、无损优化 AST 扫描并收敛 TIER1_HARD_FAIL_S 为 10.0s SSOT

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch1_gateway_contracts.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_missing_sentinel_singleton.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_import_mode_contract.py
[MODIFY] scripts/check_test_duration_baselines.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_tiering_gate_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_duration_baselines_contract.py
```

#### 【缺陷根因与修改目标】
```
根因：GitHub Actions Run 45822381023 (commit ab5f6b5) 在 Windows 3.12 上因 test_tiering_gate_contract.py::test_tier1_fast_budget_execution 耗时 8.77s (> 8.0s) 失败（本地稳定复现 8.28s / 均值 8.23s）。根本原因有三：(1) v1.36 Batch 1 新增的 test_v1_36_batch1_gateway_contracts.py 给 7 个含 7 次 git 子进程与完整 MCP 落盘生命周期的重型集成测试打上了 @pytest.mark.tier1_fast，在 Task 36.14 恢复 b'mark.tier1_fast' 全量采集后单文件拉高约 2.1~2.7s；(2) test_missing_sentinel_singleton.py (0.70s) 与 test_import_mode_contract.py (0.49s) 无预过滤全量 ast.parse；(3) 8.0s 硬红线在 test_tiering_gate_contract.py 与 check_test_duration_baselines.py 两处重复硬编码，相对 Windows 固有 ~3.3s 冷启动基座与 5.0s 目标线余量过窄。目标：零测试覆盖损失前提下，将重型集成用例归位 Tier-2、无损优化两处 AST 扫描并加正负单测验证、将 TIER1_HARD_FAIL_S 单一事实源调整为 10.0s（2x 目标线，保持 5.0s WARN 不变），彻底消除 Windows CI 红灯。
```

#### 【目标签名与类型契约】
```
def _scan_missing_sentinel_violations(scan_dirs: Sequence[Path]) -> list[str]
def test_missing_sentinel_scanner_catches_synthetic_violations(tmp_path: Path) -> None
def test_production_imports_scanner_catches_relative_imports(tmp_path: Path) -> None
TIER1_HARD_FAIL_S: Final[float] = 10.0
```

#### 【分步改造指引】
1. 修改 plugins/quench-dev-tasks/server/tests/test_v1_36_batch1_gateway_contracts.py：移除 7 处 @pytest.mark.tier1_fast 装饰器，使这 7 项含 git 子进程与完整 MCP 落盘生命周期的重型集成测试归位 Tier-2 全量回归（保持与 test_v1_36_batch2~5 一致，用例体与断言零改动）。
2. 修改 plugins/quench-dev-tasks/server/tests/test_missing_sentinel_singleton.py：抽离 _scan_missing_sentinel_violations(scan_dirs: Sequence[Path]) -> list[str]，使用 os.walk 剪枝忽略以 '.' 开头目录、__pycache__、site-packages、.venv/venv，并在调用 ast.parse 前前置无损文本检查（if 'MISSING' not in source_text or 'object' not in source_text: continue）；新增单测 test_missing_sentinel_scanner_catches_synthetic_violations(tmp_path) 验证 Assign 与 AnnAssign 合成违规均被捕获且干净文件放行。
3. 修改 plugins/quench-dev-tasks/server/tests/test_import_mode_contract.py：优化 test_production_imports_are_absolute_only，使用 os.walk 剪枝 tests/__pycache__/venv/点目录，并在 ast.parse 前前置符合 Python PEG 语法的无损正则预过滤 re.search(r'\bfrom(?:[ \t]|\\\r?\n)*\.', source_text)；新增单测 test_production_imports_scanner_catches_relative_imports(tmp_path) 覆盖 from .foo、from.foo、from ..pkg、续行 from \\\n .foo 均被拦截且合法绝对导入放行。
4. 修改 scripts/check_test_duration_baselines.py：将 TIER1_HARD_FAIL_S 调整为 10.0（保持 TIER1_TARGET_S = 5.0 与 TIER1_FAST_GOAL_S = 3.0 不变），同步更新模块顶部 docstring 退出码矩阵中的硬红线说明。
5. 修改 plugins/quench-dev-tasks/server/tests/test_tiering_gate_contract.py：从 check_test_duration_baselines 导入 TIER1_HARD_FAIL_S 作为单一事实源，更新 test_tier1_fast_budget_execution 断言 elapsed <= TIER1_HARD_FAIL_S 与 docstring。
6. 修改 plugins/quench-dev-tasks/server/tests/test_duration_baselines_contract.py：更新 test_synthetic_budget_overrun_fails_closed，将模拟耗时与 docstring 对齐至 bench_tool.TIER1_HARD_FAIL_S + 0.5（杜绝硬编码 8.5）。
7. 执行全部 DoD 验证命令并确认全绿、Tier-1 耗时显著回落至 <= 5.5s 区间。

#### 【防御与边缘校验】
- test_v1_36_batch1_gateway_contracts.py 全部 7 项用例必须在 Tier-2 / 全量测试中 100% 保留并通过（零覆盖损失），仅移出 tier1_fast 标记。
- test_missing_sentinel_singleton.py 与 test_import_mode_contract.py 的文本/正则前置过滤必须通过合成违规夹具（正负双测）证明零漏报：包括 Assign/AnnAssign 形式的 MISSING = object()，以及 from .foo、from.foo、from ..pkg、反斜杠续行 from \\n .foo 等所有合法 Python 相对导入语法。
- TIER1_HARD_FAIL_S 单一事实源收敛于 scripts/check_test_duration_baselines.py (10.0s)，同时严格保持 TIER1_TARGET_S = 5.0s 与 TIER1_FAST_GOAL_S = 3.0s 不变；test_tiering_gate_contract.py 与 test_duration_baselines_contract.py 严禁再硬编码 8.0/8.5 魔法数字。
- pytest -m tier1_fast -q 必须实际压回 <= 5.5s（远低于 10.0s 硬红线），且 scripts/check_test_tiering_invariants.py、scripts/check_test_duration_baselines.py --check 与全量测试套件 100% 通过。

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest -m tier1_fast -q --tb=short && .venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch1_gateway_contracts.py plugins/quench-dev-tasks/server/tests/test_missing_sentinel_singleton.py plugins/quench-dev-tasks/server/tests/test_import_mode_contract.py plugins/quench-dev-tasks/server/tests/test_tiering_gate_contract.py plugins/quench-dev-tasks/server/tests/test_duration_baselines_contract.py plugins/quench-dev-tasks/server/tests/test_test_duration_gate.py -v --tb=short && .venv\Scripts\python.exe scripts/check_test_tiering_invariants.py --check && .venv\Scripts\python.exe scripts/check_test_duration_baselines.py --check
```

---

