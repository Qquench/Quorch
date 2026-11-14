# 2026-11-14_consolidate_micro_ast_and_doc_tests Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-14

---

## Task List & Status / 任务清单与状态

### 任务 2.1 ✔️ 已完成 — 精简整合历史碎片化 AST 与文档门禁测试脚本

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_doc_contract_hygiene.py
[DELETE] plugins/quench-dev-tasks/server/tests/test_ci_case6_zero_stat_harness.py
[DELETE] plugins/quench-dev-tasks/server/tests/test_no_global_os_stat_patch.py
[DELETE] plugins/quench-dev-tasks/server/tests/test_doc_invariants_case12.py
```

#### 【缺陷根因与修改目标】
```
代码库存在针对单次历史事故（Case 6 scandir 零 stat 门禁、全局 os.stat 猴子补丁静态检测、Case 12 W10 文档标题排查）创建的碎片化微型测试脚本。目标：将这些碎片化 AST 与文档守卫吸收整合至统一的 test_architecture_hygiene.py 与 test_doc_contract_hygiene.py 中，并安全移除 3 个独立冗余单测文件，消除重复夹具与索引负担。
```

#### 【目标签名与类型契约】
```
test_architecture_hygiene.py 新增 test_scandir_zero_explicit_os_stat_in_ast, test_no_unconditional_os_stat_monkeypatch, test_gate_self_test_detects_bad_snippet；test_doc_contract_hygiene.py 新增 test_readme_w10_exclusion_domain_heading_invariants, test_ci_guide_dense_case_coverage_and_incident_ids。
```

#### 【分步改造指引】
1. 将 test_ci_case6_zero_stat_harness.py 与 test_no_global_os_stat_patch.py 的 AST 门禁逻辑完整迁移吸收进 test_architecture_hygiene.py。
2. 将 test_doc_invariants_case12.py 的 W10 标题与 CI 指南覆盖率断言迁移吸收进 test_doc_contract_hygiene.py。
3. 运行 pytest 验证吸收后的测试全部绿灯通过。
4. 物理删除 test_ci_case6_zero_stat_harness.py、test_no_global_os_stat_patch.py、test_doc_invariants_case12.py 3 个独立测试文件。
5. 全量运行 Tier-1 测试套件，确保无断言丢失且耗时在预算内。

#### 【防御与边缘校验】
严格遵循 TP-1 独立断言协议，被吸收的断言逻辑必须 100% 等价迁移，不得丢失任何防御校验。
严禁删改 conftest.py 中 TIER1_TARGET_REL_FILES 管控的 13 个保护性核心基线文件。

#### 【DoD 验证命令】
```bash
uv run pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q
uv run pytest plugins/quench-dev-tasks/server/tests/test_doc_contract_hygiene.py -q
uv run pytest -m tier1_fast -q
```

---

