# 2026-11-26_v1_36_batch6_1_shell_test_alignment Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-26

---

## Task List & Status / 任务清单与状态

### 任务 36.13 ✔️ 已完成 — 对齐 test_v1_36_batch2_scope_and_config.py:184 Shell 兜底保护断言与既有契约

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch2_scope_and_config.py
```

#### 【缺陷根因与修改目标】
```
根因：test_v1_36_batch2_scope_and_config.py:184 对 'echo hi > docs/dev_tasks/a.md' (dev_tasks_dir='custom_tasks') 断言了 is None，与仓库既有契约 test_shell_write_bypass.py:102-105（标准 docs/dev_tasks 始终受保护返回非 None，无关目录才返回 None）直接冲突。目标：对齐 test_v1_36_batch2_scope_and_config.py:184 断言至既有契约，达成全仓 1415/1415 全绿。
```

#### 【目标签名与类型契约】
```
# Test assertion alignment with test_shell_write_bypass.py:102-105
```

#### 【分步改造指引】
1. 将 test_v1_36_batch2_scope_and_config.py:184 中负向放行用例改为无关目录 'echo hi > docs/notes/a.md' is None，并对 'echo hi > docs/dev_tasks/a.md' 断言 is not None（与 test_shell_write_bypass.py:105 一致）。
2. 运行 test_shell_write_bypass.py 与 test_v1_36_batch2_scope_and_config.py 验证全绿。

#### 【防御与边缘校验】
- 同时保持 test_shell_write_bypass.py 与 test_v1_36_batch2_scope_and_config.py 100% 通过！

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_shell_write_bypass.py plugins/quench-dev-tasks/server/tests/test_v1_36_batch2_scope_and_config.py -q --tb=short
```

---

