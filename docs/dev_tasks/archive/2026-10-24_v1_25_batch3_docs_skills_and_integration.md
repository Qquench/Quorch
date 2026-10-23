# 2026-10-24_v1_25_batch3_docs_skills_and_integration Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-24

---

## Task List & Status / 任务清单与状态

### 任务 25.5 ✔️ 已完成 — AGENTS.md、工作流 Skill 与纪律规范的三层隔离、双层探查及 Autopilot 闭环契约升级

#### 【涉及文件】
```
[MODIFY] AGENTS.md
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md
[MODIFY] plugins/quench-dev-tasks/rules/dev-tasks-discipline.md
[MODIFY] plugins/quench-dev-tasks/agents/reviewer/agent.md
[MODIFY] docs/guides/external-executor-onboarding.md
[NEW] plugins/quench-dev-tasks/server/tests/test_doc_contract_hygiene.py
```

#### 【缺陷根因与修改目标】
```
当前文档中仍存留单入口硬约束、过时的 QUENCH_ROLE 双入口方案，且缺少双模编排（standard / inverted）、Autopilot 接力棒（harness_next_action）执行纪律、三层隔离与子代理免调 status 协议，易导致执行模型混淆角色职责或中途输出 C3 卡中断跨批次接力。修改目标是全量对齐 v1.25 架构契约与执行规范：(1) 确立主会话调用 dev_tasks_status 与接力棒驱动，所有 Subagent 免调 status 铁律；(2) 固化 [QUENCH-DISPATCH: RUNNER | REVIEWER | RESEARCH] 信封路由；(3) 写入 inverted 双层代码探查流程、Autopilot 接力棒执行纪律（含 NEXT_BATCH_PROPOSE 跨批次不停车接力）、BLOCKED / PAUSE 停机规范，以及 AGENTS.md §6 C3 交付卡仅在停靠/终态（PAUSE_FOR_ACCEPTANCE / BLOCKED / ROADMAP_DONE）输出的修正规则与 fallback_notice 转述要求；(4) 将 dev-tasks-workflow/SKILL.md §6 QUENCH_ROLE 双入口方案标注为 Deprecated 并改写为 session_role_contract 驱动，同步清理 onboarding 指南模板；(5) 在纪律规范 §7 Pre-Confirm 门禁中补充 refine_spec 凭据提交与 accepted_sources 来源策略说明；(6) 编写 test_doc_contract_hygiene.py 物理断言上述文档契约一致性。
```

#### 【目标签名与类型契约】
```
1. AGENTS.md：主会话唯一调用 dev_tasks_status + 接力棒驱动；所有 Subagent 免调 status；C3 卡仅在停靠/终态（PAUSE_FOR_ACCEPTANCE / BLOCKED / ROADMAP_DONE）输出。
2. dev-tasks-workflow/SKILL.md：QUENCH_ROLE 环境变量方案标注 Deprecated，改由 session_role_contract 驱动；补齐 inverted 双层探查与接力棒状态转移流。
3. dev-tasks-discipline.md §7：补齐 refine_spec 审查凭据通道与 accepted_sources 来源策略。
4. reviewer/agent.md & external-executor-onboarding.md：固化 [QUENCH-DISPATCH: RUNNER | REVIEWER | RESEARCH] 信封与宿主中立抽象动词（INV-5，零宿主工具名/参数名）。
5. test_doc_contract_hygiene.py：物理断言 (a) Subagent 免调 status；(b) C3 卡三态触发；(c) QUENCH-DISPATCH 信封；(d) QUENCH_ROLE 已标记 Deprecated；(e) session_role_contract 不含宿主专属工具名（INV-5 白名单扫描）。该测试只读取 markdown 文本，不做网络/文件写操作；默认不打 tier1_fast marker（保护 §3.5 ≤5s 预算）。
```

#### 【分步改造指引】
1. 更新 AGENTS.md：主会话唯一调用 dev_tasks_status；Subagent 免调；§6 C3 卡仅在停靠/终态输出。
2. 更新 SKILL.md：废弃 QUENCH_ROLE，改 session_role_contract；记录 inverted 双层探查 + Autopilot 状态机。
3. 更新 dev-tasks-discipline.md §7：refine_spec 凭据通道 + accepted_sources。
4. 更新 reviewer/agent.md 与 external-executor-onboarding.md：固化 [QUENCH-DISPATCH: ...] 信封 + 宿主中立动词。
5. 新建 test_doc_contract_hygiene.py：五项断言（Subagent 免调 status、C3 卡三态触发、QUENCH-DISPATCH 信封、QUENCH_ROLE 废弃、session_role_contract 宿主中立动词），采用纯文本/正则匹配；不得导入 fastmcp；不得写盘。
6. 运行 DoD 命令验证。

#### 【防御与边缘校验】
仅修改规范/提示词/工作流文档 + 一个文档卫生测试；零生产核心 Python 改动
保留既有 9 条核心不可变量（INV-1 ~ INV-9），保持提示词表面契约合规（P1~P5 零违规）
C3 交付卡仅在停靠/终态 (PAUSE_FOR_ACCEPTANCE / BLOCKED / ROADMAP_DONE) 输出，确保连续接力态不中断回合
session_role_contract 仅使用宿主中立抽象动词，不得含任何宿主专属工具名/参数名（INV-5 约束）
test_doc_contract_hygiene.py 默认不进 tier1_fast，防止 §3.5 预算溢出

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_doc_contract_hygiene.py plugins/quench-dev-tasks/server/tests/test_architecture_doc_anchor_integrity.py -q
python scripts/check_prompt_surface.py
```

---

### 任务 25.6 ✔️ 已完成 — 架构规范、MCP 协议规格与配置文档同步及全量测试收口

#### 【涉及文件】
```
[MODIFY] docs/architecture/README.md
[MODIFY] dev_tasks_mcp_specification.md
[MODIFY] docs/configuration.md
[MODIFY] plugins/quench-dev-tasks/server/tests/test_architecture_doc_anchor_integrity.py
[MODIFY] plugins/quench-dev-tasks/server/tests/_hygiene/rules.py
```

#### 【缺陷根因与修改目标】
```
既有架构 SSOT、MCP 工具规格与配置文档缺失 v1.25 双模编排拓扑、运行时状态 (.quench_runtime_mode.json)、accepted_sources 门禁策略与 harness_next_action 接力棒说明；由于 dev_tasks_status 参数在规格中未同步导致 test_spec_param_defaults_contract.py 失败。本次修正闭合：(a) 双向漂移测试基于实时工具签名内省而非硬编码列表；(b) DoD 采用标准 fail-closed 语法；(c) 新增文档对 INV-5 供应商字面量的防回归约束。
```

#### 【目标签名与类型契约】
```
1. dev_tasks_mcp_specification.md：补齐 dev_tasks_status 四个参数（switch_mode, switch_reviewer_channel, stop_at, task_file）默认值与说明；同步 8 工具 harness_next_action 返回字段。
2. docs/architecture/README.md：双模拓扑、运行时切换、信任模型 §0.1、Autopilot 接力棒架构；新增内容严禁出现供应商字面量（INV-5）。
3. docs/configuration.md：audit_gate.accepted_sources 与 .quench_runtime_mode.json 字段。
4. test_spec_param_defaults_contract.py：双向漂移断言，(a) 规格书 ⊆ 工具签名；(b) 工具签名 ⊆ 规格书。
5. test_architecture_doc_anchor_integrity.py：校验新增文档锚点；test_prompt_cache_stability.py 100% 通过。
```

#### 【分步改造指引】
1. 更新 dev_tasks_mcp_specification.md：补齐 dev_tasks_status 四参数 (switch_mode, switch_reviewer_channel, stop_at, task_file) + harness_next_action 契约，与 snapshot 双向一致。
2. 更新 docs/architecture/README.md：同步双模、运行时、信任模型、Autopilot 闭环；自检无供应商字面量（INV-5）。
3. 更新 docs/configuration.md：audit_gate.accepted_sources + .quench_runtime_mode.json。
4. 更新 test_architecture_doc_anchor_integrity.py：新增锚点断言。
5. 更新 test_spec_param_defaults_contract.py：改造为实时签名内省双向断言，确保全量测试绿灯。
6. 运行 DoD 命令，验证 100% 绿灯收口。

#### 【防御与边缘校验】
文档与规格严格对齐现有实现，不改物理工具接口
文档锚点与快照 100% 同步，零悬空锚点
双向漂移防御：(a) 规格书 ⊆ 工具签名；(b) 工具签名 ⊆ 规格书；两侧来源均须为权威源，杜绝自洽假绿
docs/architecture/README.md 双模示例不得引入供应商字面量（INV-5）；check_no_vendor_literals_in_core.py 与 test_no_vendor_literals_in_core.py 必须保持通过
全量测试 100% 绿灯；test_prompt_cache_stability.py 与 test_spec_param_defaults_contract.py 修复漂移断言

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_spec_param_defaults_contract.py plugins/quench-dev-tasks/server/tests/test_architecture_doc_anchor_integrity.py plugins/quench-dev-tasks/server/tests/test_prompt_cache_stability.py plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q
python scripts/export_ide_schemas.py --check
python scripts/check_prompt_surface.py
```

---

