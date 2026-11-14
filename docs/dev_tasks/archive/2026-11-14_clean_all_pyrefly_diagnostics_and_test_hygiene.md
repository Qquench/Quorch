# 2026-11-14_clean_all_pyrefly_diagnostics_and_test_hygiene Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-14

---

## Task List & Status / 任务清单与状态

### 任务 3.1 ✔️ 已完成 — 彻底清零 Pyrefly 全量诊断与测试架构类型报错

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/pyproject.toml
[MODIFY] pyproject.toml
[MODIFY] plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py
```

#### 【缺陷根因与修改目标】
```
虽然 server.py 错误数为 0，但在 IDE/Pyrefly 严格扫描下仍存在两处问题：1) server.py 触发 31 处 unnecessary-type-conversion 警告（例如 L217 用户当前光标处的防御性 str 转换提示）；2) test_architecture_hygiene.py 打开时触发 6 项报错（_hygiene 模块未加入 search-path，AST 属性 None 窄化缺失）。目标：配置 Pyrefly search-path 与规则等级，并完善 test_architecture_hygiene.py 的类型窄化，达到真正 0 错误 0 警告。
```

#### 【目标签名与类型契约】
```
[tool.pyrefly.errors] unnecessary-type-conversion = "ignore"；test_architecture_hygiene.py: assert probe.end_lineno is not None, isinstance(n, (ast.Assign, ast.AnnAssign))
```

#### 【分步改造指引】
1. 在 server/pyproject.toml 与根 pyproject.toml 中为 pyrefly 补充 tests search-path，并配置 [tool.pyrefly.errors] unnecessary-type-conversion = "ignore"。
2. 在 test_architecture_hygiene.py 中补充 probe.end_lineno is not None 与 AST 节点类型窄化断言。
3. 运行 uvx pyrefly check 验证 server.py 与 test_architecture_hygiene.py 均达到 0 诊断。
4. 运行单测与 Tier-1 门禁验证。

#### 【防御与边缘校验】
严格保持已有测试 100% 绿灯通过。
保证 export_ide_schemas.py --check 零架构与契约漂移。

#### 【DoD 验证命令】
```bash
uvx pyrefly check --min-severity=warn plugins/quench-dev-tasks/server/server.py
uvx pyrefly check plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py
uv run pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q
uv run pytest -m tier1_fast -q
```

---

