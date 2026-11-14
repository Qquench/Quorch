# 2026-11-14_fix_pyrefly_missing_import_check_prompt_surface Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-14

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 修复 pyrefly 对 check_prompt_surface 的 missing-import 报障（search-path 结构化修复 + 语义化配置契约守卫 + 静态验证闭环）

#### 【涉及文件】
```
[MODIFY] pyproject.toml
[MODIFY] plugins/quench-dev-tasks/server/pyproject.toml
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_ctx_schema_invariance.py
```

#### 【缺陷根因与修改目标】
```
根因（静态分析器缺失 search-path，非运行时问题）：
1. 根 pyproject.toml 的 [tool.pytest.ini_options] pythonpath 仅解决 pytest 运行时导入；
2. pyrefly 静态分析不读运行时 sys.path，且 check_prompt_surface.py 位于项目解析根之外 → missing-import；
3. 测试内 sys.path.insert 对静态分析不可见，故 pytest 恒绿而 pyrefly 仍报错。

修改目标：
- 通过 [tool.pyrefly] search-path 使 check_prompt_surface 与 server 在静态层可解析（真解析，非 Any 降级）；
- 严禁 # type: ignore / # pyrefly: ignore（掩盖配置错误并破坏 P1-3 类型语义）；
- search-path 相对路径必须物理可解析（指向真实存在且含目标模块的目录），并由语义化守卫测试断言；
- 追加配置契约守卫测试，防范双轨漂移；
- 零运行时行为变更，零 pytest 已有断言语义变更。
```

#### 【目标签名与类型契约】
```
1. 导入语句保持原样，不得改写：
   import server
   import check_prompt_surface

2. search-path 字面量契约（相对各自 pyproject.toml 所在目录）：
   <repo>/pyproject.toml: search-path = ["scripts", "plugins/quench-dev-tasks/server"]
   <repo>/plugins/quench-dev-tasks/server/pyproject.toml: search-path = ["../../../scripts"]
```

#### 【分步改造指引】
1. 根 pyproject.toml 追加：[tool.pyrefly] search-path = ["scripts", "plugins/quench-dev-tasks/server"]
2. plugins/quench-dev-tasks/server/pyproject.toml 追加：[tool.pyrefly] search-path = ["../../../scripts"]
3. 在 test_reviewer_poll_ctx_schema_invariance.py 追加语义化守卫测试 test_pyrefly_search_path_resolves_to_real_modules 与 test_no_type_ignore_on_static_gate_import
4. 执行 pytest DoD 验证

#### 【防御与边缘校验】
- 追加不覆盖：仅补 [tool.pyrefly]，不得改动既有 [tool.pytest.ini_options]
- 禁止 ignore 兜底，保持真实类型签名约束
- 语义化守卫：断言路径可解析到真实模块文件，而非硬编码字面量
- 保持运行时 sys.path.insert 顺序与内容不变

#### 【DoD 验证命令】
```bash
uv run pytest plugins/quench-dev-tasks/server/tests/test_reviewer_poll_ctx_schema_invariance.py -q
uv run pytest -m tier1_fast -q
```

---

