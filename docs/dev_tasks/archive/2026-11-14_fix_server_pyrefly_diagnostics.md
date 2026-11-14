# 2026-11-14_fix_server_pyrefly_diagnostics Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-14

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 全面修复 server.py 中 Pyrefly 静态类型与命名空间报错

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
```

#### 【缺陷根因与修改目标】
```
server.py 存在 28 项 Pyrefly 静态检查报错，涵盖命名空间冲突、数据类漏参、TypedDict 返回类型声明、None 窄化缺失及废弃属性调用。目标：全量修复 server.py 报错直到 pyrefly check 0 报错，且所有既有测试完全通过。
```

#### 【目标签名与类型契约】
```
1. server.py: 移除 import datetime，保留 from datetime import datetime, timezone, timedelta, date\n2. _is_external_api_available: re_cfg = getattr(config, 'reviewer_engine', None)\n3. _resolve_handoff_envelope: -> ReviewerHandoff\n4. dev_tasks_refine_spec: assert task_file is not None\n5. QuenchStackConfig(workspace_root=workspace_root, project_name=os.path.basename(workspace_root) or 'default')\n6. _poll_impl: 增加参数窄化保护\n7. dev_reviewer_poll: 移除 is_enabled 判断直接触发 _inject_harness_next_action
```

#### 【分步改造指引】
1. 在 server.py 顶部清理 redundant import datetime，消除 8 项 datetime 命名空间属性报错。
2. 修复 _is_external_api_available 中的 reviewer_engine 配置提取回退逻辑。
3. 修复 _resolve_handoff_envelope 的返回类型标注为 ReviewerHandoff。
4. 在 dev_tasks_refine_spec 中添加 task_file 的 assert 窄化。
5. 修复 QuenchStackConfig 异常回退构造传参。
6. 优化 _poll_impl 参数防御与类型窄化。
7. 清理 dev_reviewer_poll 中不存在的 is_enabled 属性访问。
8. 运行 uvx pyrefly check 与 pytest 验证。

#### 【防御与边缘校验】
严禁修改 server.py 导出的 MCP tool 契约与 IDE schema（运行 export_ide_schemas.py --check 零漂移）。
保持已有的 fastmcp 上下文与运行时逻辑完全一致。

#### 【DoD 验证命令】
```bash
uvx pyrefly check --output-format min-text plugins/quench-dev-tasks/server/server.py
uv run python scripts/export_ide_schemas.py --check
uv run pytest -m tier1_fast -q
```

---

