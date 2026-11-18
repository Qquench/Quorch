# 2026-11-18_fix_shell_bypass_false_positives_and_bilingual_guards Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-18

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — Fix detect_shell_write_bypass false positives on Python inline scripts and add bilingual status guard messages

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_shell_write_bypass.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py
```

#### 【缺陷根因与修改目标】
```
Root cause: detect_shell_write_bypass() matches any substring 'dev_tasks' (triggering on identifiers like 'dev_tasks_status') and matches bare '>' (triggering on Python type arrows '->' or '>='). Additionally, check_task_status_guard() and diff_task_statuses() only emit Chinese messages. Goal: Tighten path-boundary and redirection matching in file_scope_guard.py to eliminate false positives on Python inline scripts, and make task-status guard messages bilingual (English + Chinese).
```

#### 【目标签名与类型契约】
```
def _is_task_dir_token(token: str, clean_dir: str) -> bool
def detect_shell_write_bypass(command: str, workspace_root: str, dev_tasks_dir: str = "docs/dev_tasks") -> Optional[str]
def diff_task_statuses(old: TaskHeaderScan, new: TaskHeaderScan) -> List[dict]
def check_task_status_guard(target_file: str, tool_name: str, args: dict) -> Optional[dict]
```

#### 【分步改造指引】
1. Add _is_task_dir_token(token: str, clean_dir: str) -> bool in file_scope_guard.py using path-boundary regex (?:^|[/\\])dev_tasks(?:$|[/\\]) and exact/prefix/subpath clean_dir checks.
2. Update SHELL_WRITE_PATTERN redirection branch to (?:(?<![-\w=])>{1,2}|[&12]>{1,2})(?!=) so ->, =>, >=, <= are never treated as shell redirection.
3. Update detect_shell_write_bypass() short-circuit, step 1, and step 2 heuristic to use _is_task_dir_token and non-arrow redirection regex.
4. Upgrade diff_task_statuses() and check_task_status_guard() violation/reason strings to bilingual English + Chinese while preserving all existing Chinese keywords and avoiding literal status emojis.
5. Add regression tests in test_shell_write_bypass.py (false-positive python -c commands) and test_file_scope_guard_status.py (bilingual guard headers), then run pytest.

#### 【防御与边缘校验】
Ensure _is_task_dir_token uses path-boundary matching so tool/function identifiers like dev_tasks_status do not trigger false positives; ensure SHELL_WRITE_PATTERN and fail-closed heuristic exclude ->, =>, >=, <=; ensure zero literal status emoji strings in file_scope_guard.py (use STATUS_PENDING etc. from task_status.py to pass test_ast_zero_status_emoji_constants); preserve all existing Chinese phrases tested by test_file_scope_guard_status.py while adding bilingual English headers/messages.

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_shell_write_bypass.py plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py -q
```

---

