# 2026-11-26_v1_36_batch6_2_tier1_byte_precheck Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-26

---

## Task List & Status / 任务清单与状态

### 任务 36.14 ✔️ 已完成 — 修复 conftest.py 的 tier1_fast 预过滤以完整保留全部 210 项显式标记单测

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/conftest.py
```

#### 【缺陷根因与修改目标】
```
根因：Task 36.12 在 conftest.py 的 pytest_ignore_collect 中仅按 TIER1_TARGET_REL_FILES 过滤，遗漏了非白名单模块内显式标记 @pytest.mark.tier1_fast 的 91 项单测（使执行数从 210 降至 119）。目标：在 pytest_ignore_collect 中增加极轻量字节级预扫描 b'tier1_fast' in collection_path.read_bytes()，在不导入无关重型模块的前提下 100% 完整采集执行全部 210 项 tier1_fast 用例并保持 <5s 极速预算。
```

#### 【目标签名与类型契约】
```
def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None
```

#### 【分步改造指引】
1. 修改 plugins/quench-dev-tasks/server/tests/conftest.py 的 pytest_ignore_collect：当 markexpr == 'tier1_fast' 且文件不在 TIER1_TARGET_REL_FILES 时，先通过 try: if b'tier1_fast' in collection_path.read_bytes(): return None except OSError: return None 保留所有含显式 tier1_fast 装饰器的测试文件（注意排除 test_tiering_gate_contract.py / test_duration_baselines_contract.py 等仅在字符串参数里写 tier1_fast 而无 @pytest.mark.tier1_fast 的重型契约测试，精确匹配 b'mark.tier1_fast'！）。
2. 验证 pytest -m tier1_fast 精确执行全部 210 项通过且耗时 <= 5.0s，并运行 test_tiering_gate_contract.py、test_duration_baselines_contract.py 与 check_test_tiering_invariants.py 全绿。

#### 【防御与边缘校验】
- pytest -m tier1_fast 采集并执行的用例数必须 100% 恢复为完整 210 项（零遗漏显式装饰的 @pytest.mark.tier1_fast 用例），且总耗时严格 <= 5.0s 目标 / <= 8.0s 硬红线！
- test_duration_baselines_contract.py、test_tiering_gate_contract.py 与 check_test_tiering_invariants.py 全部 100% 通过！

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest -m tier1_fast -q --tb=short && .venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_tiering_gate_contract.py plugins/quench-dev-tasks/server/tests/test_duration_baselines_contract.py -q --tb=short && .venv\Scripts\python.exe scripts/check_test_tiering_invariants.py
```

---

