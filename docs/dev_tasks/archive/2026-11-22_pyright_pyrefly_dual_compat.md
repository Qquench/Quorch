# 2026-11-22_pyright_pyrefly_dual_compat Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-22

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 在根与服务端 pyproject.toml 中同步补充 [tool.pyright] extraPaths 与 PEP 562 兼容配置

#### 【涉及文件】
```
[MODIFY] pyproject.toml
[MODIFY] plugins/quench-dev-tasks/server/pyproject.toml
```

#### 【缺陷根因与修改目标】
```
Add [tool.pyright] extraPaths (mirroring [tool.pyrefly].search-path) and reportUnsupportedDunderAll = "none" in root and server pyproject.toml to resolve all 43 reportMissingImports and 1 PEP 562 __all__ warning in Pylance/Pyright.
```

#### 【目标签名与类型契约】
```
[tool.pyright] extraPaths: list[str], reportUnsupportedDunderAll: "none"
```

#### 【分步改造指引】
1. Append `[tool.pyright]` to `pyproject.toml` with `extraPaths` matching `[tool.pyrefly].search-path` (`["scripts", "plugins/quench-dev-tasks/scripts", "plugins/quench-dev-tasks/server", "plugins/quench-dev-tasks/server/hooks", "plugins/quench-dev-tasks/server/tests"]`) and `reportUnsupportedDunderAll = "none"`.
2. Append `[tool.pyright]` to `plugins/quench-dev-tasks/server/pyproject.toml` with `extraPaths = ["../../../scripts", "../scripts", "hooks", "tests"]` and `reportUnsupportedDunderAll = "none"`.

#### 【防御与边缘校验】
- Preserve all existing [tool.pytest.ini_options], [project], [tool.pyrefly], and [tool.pyrefly.errors] entries untouched
- Keep [tool.pyright].extraPaths identical in path entries to [tool.pyrefly].search-path so test_pyrefly_search_path_resolves_to_real_modules and Pyright stay aligned
- Do not suppress genuine type errors globally; only set extraPaths and reportUnsupportedDunderAll = "none" for PEP 562 __all__ compatibility

#### 【DoD 验证命令】
```bash
uvx pyright --pythonpath .\.venv\Scripts\python.exe
uvx pyrefly check --python-interpreter-path .\.venv\Scripts\python.exe --min-severity=warn --output-format min-text .
.\.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_python_floor_discipline.py plugins/quench-dev-tasks/server/tests/test_reviewer_poll_ctx_schema_invariance.py -q
```

---

### 任务 1.2 ✔️ 已完成 — 对齐负向单测忽略标记与测试契约访问以实现 Pyright/Pyrefly 双引擎零报错

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_tools.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_external_runner_scope_reconciliation.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_ctx_schema_invariance.py
```

#### 【缺陷根因与修改目标】
```
Align the remaining 14 Pyright test diagnostics (6 negative-test `# pyrefly: ignore` comments, 7 `ReviewerHandoff` `NotRequired` indexing assertions in test_handoff_protocol.py, and 1 `.fn` attribute access in test_reviewer_poll_ctx_schema_invariance.py) so both Pyright/Pylance and Pyrefly report 0 errors and 0 warnings across the entire workspace.
```

#### 【目标签名与类型契约】
```
uvx pyright -> 0 errors, 0 warnings; uvx pyrefly check -> 0 diagnostics
```

#### 【分步改造指引】
1. Replace `# pyrefly: ignore[unexpected-keyword]` / `# pyrefly: ignore[bad-argument-type]` with `# type: ignore` on the 6 negative-test call sites (`test_reviewer_jobs.py` lines 326 & 478; `test_server_tools.py` lines 436, 506 & 515; `test_external_runner_scope_reconciliation.py` line 366).
2. In `test_handoff_protocol.py` (lines 149, 171, 182, 197, 214, 269, 319), use `envelope.get("strategies", [])` and `env*.get("preferred")` instead of direct `TypedDict(total=False)` subscripting.
3. In `test_reviewer_poll_ctx_schema_invariance.py` line 134, use `getattr(server.dev_reviewer_poll, "fn", server.dev_reviewer_poll)` (matching `test_server_tools.py:430`).

#### 【防御与边缘校验】
- Only change negative-test call-site `# pyrefly: ignore` comments (never static gate import lines) to `# type: ignore`
- Preserve exact runtime assertions and pytest.raises behavior across all 5 test files
- Verify both `uvx pyright` (0 errors, 0 warnings) and `uvx pyrefly check` (0 diagnostics) pass simultaneously

#### 【DoD 验证命令】
```bash
uvx pyright --pythonpath .\.venv\Scripts\python.exe
uvx pyrefly check --python-interpreter-path .\.venv\Scripts\python.exe --min-severity=warn --output-format min-text .
.\.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests -q
```

---

