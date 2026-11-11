# 2026-11-11_ci_fix_engine_key Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-11

---

## Task List & Status / 任务清单与状态

### 任务 1.3 ✔️ 已完成 — 补全 refine_spec 压缩保全中的 engine 关键字段

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
```

#### 【缺陷根因与修改目标】
```
根因：dev_tasks_refine_spec 中 fit_to_budget 的 always_keep 未包含 'engine'，导致超预算 Tier-2 截断时删除了 'engine' 字段，引起 test_spec_refine 中的 KeyError: 'engine'。目标：将 'engine' 补全至 always_keep 列表中。
```

#### 【目标签名与类型契约】
```
fit_to_budget 保持不变；dev_tasks_refine_spec 响应保全 engine 字段。
```

#### 【分步改造指引】
1. 在 server.py 的两处 fit_to_budget('dev_tasks_refine_spec', ...) 调用中，将 'engine' 加入 always_keep 元组。

#### 【防御与边缘校验】
- dev_tasks_refine_spec 中 always_keep 保留 engine 字段，确保离线降级与在线完成均可透明识别引擎类型。
- 总字节仍然在 dev_tasks_refine_spec 预算内（600B）。

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_spec_refine.py::test_dev_tasks_refine_spec_offline_fallback -v
```

---

