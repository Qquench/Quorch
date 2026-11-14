# 2026-11-14_fix_pyrefly_bad_function_definition_ctx_context Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-14

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 修复 ctx 参数 bad-function-definition 并物理锚定 FastMCP Context 注入、空值守卫与 Schema 零漂移

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_ctx_schema_invariance.py
```

#### 【缺陷根因与修改目标】
```
根因（PEP 484 隐式 Optional 废弃）：
server.py 的 dev_reviewer_poll 与 test_reviewer_poll_ctx_schema_invariance.py 的 probe_with_ctx / pending_dev_reviewer_poll 均使用 ctx: Context = None，触发 pyrefly bad-function-definition: Default None is not assignable to parameter ctx with type Context。

修改目标：
1. 三处 ctx 签名规范化为 ctx: Context | None = None；
2. 测试断言改为 set(get_args(get_type_hints(fn)["ctx"])) == {Context, type(None)} 的集合断言，同时锚定生产签名 server.dev_reviewer_poll 与影子 probe；
3. 物理锚定 FastMCP DI 契约：ctx 不出现在对外 JSON Schema properties 与 required 中；
4. 物理锚定运行期空值守卫 ProgressBridge.from_context(None) is None；
5. golden schema 字节级零漂移。
```

#### 【目标签名与类型契约】
```
签名契约：ctx: Context | None = None
DI 契约：ctx 为注入态，不出现在对外 JSON Schema properties 与 required 中；export_ide_schemas.py --check 为 DI 识别真值的唯一物理闸门。
可空性契约：None 仅用于直接调用兼容（Fail-Open）；FastMCP 调用路径由 DI 注入 Context 实例。
断言契约：注解在 from __future__ import annotations 下为字符串，必须以 get_type_hints + get_args 还原，禁止直接与 Context 身份比较。
```

#### 【分步改造指引】
1. server.py：将 dev_reviewer_poll 的 ctx: Context = None 改为 ctx: Context | None = None，保留原有 docstring 中 ctx: 的 Args 说明。
2. test_reviewer_poll_ctx_schema_invariance.py：将 probe_with_ctx 与 pending_dev_reviewer_poll 的 ctx: Context = None 改为 ctx: Context | None = None。
3. 将现有 ctx_anno is Context or ctx_anno == "Context" 断言替换为 get_type_hints 集合断言，并新增生产签名锚定。
4. 新增运行期空值守卫断言：ProgressBridge.from_context(None) is None 与直接调用兼容断言。
5. 执行 DoD 验证命令：schema 零漂移、目标单测、tier1 快速门禁。

#### 【防御与边缘校验】
- DI 注入契约：FastMCP is_class_member_of_type(Context | None, Context) 恒为 True；以 export_ide_schemas.py --check 作为 fail-closed 物理真值，禁止仅以口头证据放行。
- Schema 零漂移：ide_tool_schemas.json 字节级一致；任何 ctx 泄漏进 properties/required 即视为 DI 失效。
- 运行期空值守卫：ProgressBridge.from_context(None) 必须返回 None（Fail-Open，不阻塞轮询）。
- 断言健壮性：from __future__ import annotations 下禁止直接身份比较；统一走 get_type_hints。

#### 【DoD 验证命令】
```bash
uv run python scripts/export_ide_schemas.py --check
uv run pytest plugins/quench-dev-tasks/server/tests/test_reviewer_poll_ctx_schema_invariance.py -q
uv run pytest -m tier1_fast -q
```

---

