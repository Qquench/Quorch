# 2026-09-30_fix_py311_fstring_backslash_ci Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-09-30

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 修复 consultation.py f-string 反斜杠语法错误并补齐最低 Python 3.11 版本兼容守护

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/consultation.py
[NEW] plugins/quench-dev-tasks/server/tests/test_python_version_compat.py
[MODIFY] .github/workflows/ci.yml
[MODIFY] docs/ci_incident_tracker_and_compatibility_guide.md
```

#### 【缺陷根因与修改目标】
```
【根因分析】
在 commit b19e981 中，plugins/quench-dev-tasks/server/consultation.py 第 1075 行引入了 f-string 内部表达式包含反斜杠的代码：
slice_blocks = [f"```\n{s.text.strip().replace('\\', '/')}\n```" for s in sorted_extra]
Python 3.12 (PEP 701) 放宽了 f-string 内反斜杠限制，但在 Python 3.11 中，f-string 表达式 {...} 内出现反斜杠（含 \\, \n 等）会在编译/收集期抛出 SyntaxError: f-string expression part cannot include a backslash。由于本地开发环境使用 Python 3.12，本地测试全绿，但 GitHub Actions CI 矩阵中的 Python 3.11 (Ubuntu-latest 与 Windows-latest) 在测试收集阶段因 import consultation.py 崩溃，导致两个 Python 3.11 job 报错失败 (INC-20260930-01)。

【修改目标】
1. 修复 consultation.py 第 1075 行，消除 f-string 表达式内的反斜杠，保证生成的切片块与原输出逐字节一致（保护 Prompt Cache 字节稳定性）；
2. 新增 test_python_version_compat.py 跨版本语法兼容守护单测，通过 AST 递归分析 FormattedValue 确保所有 Python 文件在 Python 3.11 约束下不引入 f-string 内反斜杠，并包含负向自证断言；
3. 在 .github/workflows/ci.yml 的 Run test suite 前置增加 python -m compileall -q 语法预检 fail-fast 步骤；
4. 在 docs/ci_incident_tracker_and_compatibility_guide.md 登记 INC-20260930-01 并在历史案例档案中新增【案例 9】。
```

#### 【目标签名与类型契约】
```
def test_all_server_modules_fstring_backslash_compat() -> None: ...
def test_guard_detects_fstring_backslash_regression() -> None: ...
```

#### 【分步改造指引】
1. 修改 plugins/quench-dev-tasks/server/consultation.py 第 1075 行：将 slice_blocks 构建方式改为不用 f-string 反斜杠表达式（如 ['```\n' + s.text.strip().replace('\\', '/') + '\n```' for s in sorted_extra]），保持输出逐字节完全等价；
2. 新增 plugins/quench-dev-tasks/server/tests/test_python_version_compat.py：遍历 plugins/quench-dev-tasks/server 源码，AST 扫描 FormattedValue 节点，断言表达式内部绝对不含反斜杠；同时编写包含反斜杠样本的负向用例确保守护有效；
3. 修改 .github/workflows/ci.yml：在 Run test suite 步骤前添加 compileall 预检，提前暴露最低版本语法错误；
4. 更新 docs/ci_incident_tracker_and_compatibility_guide.md：在 §2.1 故障总账登记 INC-20260930-01，在 §3 归档【案例 9】详细根因与长效防护措施。

#### 【防御与边缘校验】
确保 slice_blocks 输出逐字符与原逻辑等价，不破坏 Prompt Cache 哈希和后续断言；
确保 test_python_version_compat.py 仅使用标准库 (ast, pathlib) 与 pytest，测试执行快且无环境副作用；
确保 python -m compileall -q plugins/quench-dev-tasks/server 零报错；
全量单测 pytest plugins/quench-dev-tasks/server/tests 必须 100% 通过。

#### 【DoD 验证命令】
```bash
python -m compileall -q plugins/quench-dev-tasks/server
pytest plugins/quench-dev-tasks/server/tests/test_python_version_compat.py -v
pytest plugins/quench-dev-tasks/server/tests -v -rA --tb=short
```

---

