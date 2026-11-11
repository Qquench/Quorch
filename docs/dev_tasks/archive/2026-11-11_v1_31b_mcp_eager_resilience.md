# 2026-11-11_v1_31b_mcp_eager_resilience Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-11

---

## Task List & Status / 任务清单与状态

### 任务 31.2 ✔️ 已完成 — Slim Heavy MCP Tool Schemas under 850B for Antigravity Eager Resilience

#### 【涉及文件】
```
plugins/quench-dev-tasks/server/server.py
docs/architecture/ide_tool_schemas.json
```

#### 【缺陷根因与修改目标】
```
The 3 MCP tools (dev_reviewer_submit, dev_tasks_status, dev_tasks_set_bypass) currently exceed 1,024 bytes in schema size, causing Antigravity IDE to prune them from eager tool registration. Objective: slim their docstrings and parameter descriptions in server.py so all tool schemas are strictly under 850 bytes (comfortably below 1KB limit) and update the snapshot.
```

#### 【目标签名与类型契约】
```
All tool schemas <= 850 bytes, total snapshot size <= 8500 bytes. Functions, signatures, and runtime behavior unchanged.
```

#### 【分步改造指引】
Slim docstrings of dev_reviewer_submit, dev_tasks_status, dev_tasks_set_bypass in server.py.
Run export_ide_schemas.py --write to update docs/architecture/ide_tool_schemas.json.
Run DoD test suite to verify snapshot drift and contract gates pass.

#### 【防御与边缘校验】
Preserve all function signatures, parameter names, and default values. Ensure required phrases for test_reviewer_prompt_proportionality remain intact.
Rollback tag: git checkout plugins/quench-dev-tasks/server/server.py docs/architecture/ide_tool_schemas.json

#### 【DoD 验证命令】
```bash
python plugins/quench-dev-tasks/server/ide_schema_export.py --check
pytest plugins/quench-dev-tasks/server/tests/test_snapshot_drift_gate_contract.py plugins/quench-dev-tasks/server/tests/test_tool_surface_contract.py plugins/quench-dev-tasks/server/tests/test_reviewer_prompt_proportionality.py -v
```

---

