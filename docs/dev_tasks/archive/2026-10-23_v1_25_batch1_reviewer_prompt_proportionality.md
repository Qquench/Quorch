# 2026-10-23_v1_25_batch1_reviewer_prompt_proportionality Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-23

---

## Task List & Status / 任务清单与状态

### 任务 25.1 ✔️ 已完成 — 审查引擎、工具描述与 Skill 提示词去诱导化（Context-Proportional 重塑）

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/reviewer_engine.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md
[MODIFY] docs/architecture/ide_tool_schemas.json
[NEW] plugins/quench-dev-tasks/server/tests/test_reviewer_prompt_proportionality.py
```

#### 【缺陷根因与修改目标】
```
现有 reviewer_engine.py（L1181/L1226）、server.py（L2210 工具描述与 L2332 运行时提示词）及 dev-tasks-review/SKILL.md（L39）中包含 'No Upper Bounds'、'concurrency deadlocks / offline fallbacks'、'concurrency boundary defenses'、'ironclad' 等无差别强诱导措辞，诱发 Reviewer 模型对简单改动凭空捏造并发锁与冗余样板代码。本任务旨在摘除上述诱导源，确立上下文成比例（Context-Proportional）审查原则与代码片段“免写样板、写了即用”边界。
```

#### 【目标签名与类型契约】
```
# 函数签名保持完全向后兼容，无新增或破坏性参数变更：
class PromptAssembler:
    @staticmethod
    def build_static_system_prefix(workspace_root: str, config: QuenchStackConfig) -> str: ...
```

#### 【分步改造指引】
1. 在 `plugins/quench-dev-tasks/server/reviewer_engine.py` 的 `PromptAssembler.build_static_system_prefix`（L1180-L1230）中，移除无差别要求排查 `eliminate concurrency deadlocks` 及 `concurrent race conditions, boundary overflows, and offline fallbacks` 的措辞，改为上下文成比例（Context-Proportional）原则：聚焦客观缺陷、最小改动表面积（Minimal Diff Surface）与接口/测试契约，仅在目标代码客观涉及并发或外部 I/O 时审查并发与降级，并在 `steps` 中引导免写常规样板代码（保留关键代码片段直接复用）。
2. 在 `plugins/quench-dev-tasks/server/server.py` 的 `dev_tasks_refine_spec` 中，将 L2210 docstring 中的 `concurrency boundary defenses` / `并发边界` 改为 `proportional boundary checks` / `成比例的边界校验`，并将 L2332 `user_prompt` 中的 `red-team critique ... into an ironclad Quench DevTask` 改为成比例规约打磨表述；随后运行 `python scripts/export_ide_schemas.py --write` 同步 `docs/architecture/ide_tool_schemas.json`。
3. 在 `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md` 第 2 节质量分级表（L38-L44）中，移除 `★ Rigidly Enforced, No Upper Bounds`，替换为 `★ Context-Proportional (Bound to Actual Changed Paths)`，明确禁止凭空引入未请求的并发锁、缓存层或降级分支，并说明 `steps` 聚焦修改意图与锚点、不代写常规样板实现（若已给出关键代码片段则直接保留供 Runner 使用）。
4. 新建 `plugins/quench-dev-tasks/server/tests/test_reviewer_prompt_proportionality.py`，以负向断言验证组装后的 `build_static_system_prefix`、`dev_tasks_refine_spec` docstring/提示词及 `dev-tasks-review/SKILL.md` 中不再包含 `No Upper Bounds`、`eliminate concurrency deadlocks`、`concurrency boundary defenses`、`ironclad Quench DevTask` 等诱导词，并以正向断言验证成比例原则（如 `proportional` / `Minimal Diff Surface`）存在。

#### 【防御与边缘校验】
保持 PromptAssembler.build_static_system_prefix 纯静态纯洁性（严禁引入动态时间戳或会话随机数），确保提示词缓存稳定性测试继续通过
修改 server.py 中 dev_tasks_refine_spec 的 docstring 后同步执行 scripts/export_ide_schemas.py --write 更新 ide_tool_schemas.json，防止 B-04 工具面快照漂移

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_prompt_proportionality.py plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py plugins/quench-dev-tasks/server/tests/test_prompt_cache_stability.py plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py -q
python scripts/export_ide_schemas.py --check
```

---

