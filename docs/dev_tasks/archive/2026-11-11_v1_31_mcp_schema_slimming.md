# 2026-11-11_v1_31_mcp_schema_slimming Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-11

---

## Task List & Status / 任务清单与状态

### 任务 31.1 ✔️ 已完成 — MCP Tool Surface Docstring Slimming & Hard Cap under 600B

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] docs/architecture/ide_tool_schemas.json
```

#### 【缺陷根因与修改目标】
```
Quench 16 个 FastMCP 工具 docstring 包含长篇中英双语冗余堆砌，导致 8 个核心工具 Schema 体积超过 1,100 字节，在长会话触发 Context Truncation 时被 IDE 宿主判定超额暴力剔除，引发生命周期调用被 Cortex 拦截故障。目标是将 16 个工具的 docstring 统一优化为高信息密度的专业技术英文，彻底剔除 [中文对照] 与重复中文说明，确保单工具 Schema 物理体积严格控制在 600 字节以内，总预算降至 8KB 以下。
```

#### 【目标签名与类型契约】
```
单工具 Schema 物理字节数严格 <= 600 字节，全部 16 个工具总 Schema 物理字节数 <= 8500 字节。所有参数类型与必填约束完全不变。
```

#### 【分步改造指引】
重构 plugins/quench-dev-tasks/server/server.py 中全部 16 个 @mcp.tool() 的 docstring，移除冗余中文字段。
运行 python plugins/quench-dev-tasks/server/ide_schema_export.py 刷新快照 docs/architecture/ide_tool_schemas.json。
执行 DoD 测试套件验证漂移门禁与契约测试全绿。

#### 【防御与边缘校验】
- 保持全部 16 个工具的函数签名、入参名称、默认值语义 100% 不变。
- test_reviewer_prompt_proportionality.py 依赖的短语 'proportional boundary checks' 与 '成比例的边界校验' 必须保留在 dev_tasks_refine_spec 的 docstring 中。
- 回滚锚点：git checkout plugins/quench-dev-tasks/server/server.py docs/architecture/ide_tool_schemas.json

#### 【DoD 验证命令】
```bash
python plugins/quench-dev-tasks/server/ide_schema_export.py --check
python -m pytest plugins/quench-dev-tasks/server/tests/test_snapshot_drift_gate_contract.py plugins/quench-dev-tasks/server/tests/test_tool_surface_contract.py plugins/quench-dev-tasks/server/tests/test_reviewer_prompt_proportionality.py -v
```

---

