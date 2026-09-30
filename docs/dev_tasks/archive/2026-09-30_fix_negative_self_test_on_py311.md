# 2026-09-30_fix_negative_self_test_on_py311 Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-09-30

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 兼容 Python 3.11 原生解析器对负向用例 SyntaxError 的直接抛出行为

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_python_version_compat.py
```

#### 【缺陷根因与修改目标】
```
【根因分析】
在 test_python_version_compat.py 中，负向用例 test_guard_detects_fstring_backslash_regression 动态构造了包含反斜杠的 bad_snippet 并调用 find_fstring_backslash_violations(bad_snippet)。
在 Python 3.12 中，ast.parse 不抛异常，由后续 AST 遍历逻辑捕获 FormattedValue 反斜杠违规；但在 Python 3.11 下，ast.parse 在词法/解析阶段就直接抛出 SyntaxError: f-string expression part cannot include a backslash，导致测试在 Python 3.11 CI 环境下未捕获该异常而报错。

【修改目标】
为 test_guard_detects_fstring_backslash_regression 增加 try...except SyntaxError 容错断言：在 Python <= 3.11 下断言原生解释器抛出 f-string 反斜杠 SyntaxError，在 Python 3.12+ 下断言由 AST 守卫检出违规，实现双版本无死角自证通过。
```

#### 【目标签名与类型契约】
```
def test_guard_detects_fstring_backslash_regression() -> None: ...
```

#### 【分步改造指引】
1. 修改 plugins/quench-dev-tasks/server/tests/test_python_version_compat.py 中的 test_guard_detects_fstring_backslash_regression；
2. 在调用 find_fstring_backslash_violations 时包裹 try...except SyntaxError，当捕获 SyntaxError 时断言错误信息包含 f-string 或 backslash，未抛异常时继续断言 AST 扫描违规项。

#### 【防御与边缘校验】
确保在 Python 3.11 下捕获原生 SyntaxError 并断言 f-string 报错信息；
确保在 Python 3.12+ 下正常进入 AST 扫描并由 find_fstring_backslash_violations 捕获；
单测在 3.11 与 3.12 下均 100% 通过。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_python_version_compat.py -v
```

---

