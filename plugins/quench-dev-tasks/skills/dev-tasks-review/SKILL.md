---
name: dev-tasks-review
description: Guides senior architecture reviewer models (Reviewer) or architecture planners in code review, drafting architectural evolution DevTasks, and grading defect & resilience quality. Use when reviewing architecture, assessing refactoring plans, or escalating from executor models.
---

# Quench Architecture & Task Review Guide (架构与任务审查指南)

This guide directs senior architecture reviewers and strategic planners (the user-allocated Strategic Reviewer model) on how to conduct rigorous, context-grounded engineering reviews and DevTask decomposition.

---

## 1. Core Review Discipline (核心审查纪律)

When reviewing code or formulating architectural tasks, the Reviewer must adhere to four foundational principles:

1. **Read-Only Analysis — Zero Source Modifications (零源码修改原则)**:
   The value of the review phase lies in diagnosis, evaluation, and formulation of remediation plans. Reviewers must never directly edit production code; all suggestions must be formulated as standard six-core-field DevTasks and submitted via `dev_tasks_propose`.

2. **Context-First Reading (背景优先原则)**:
   Never conduct reviews in a vacuum. Before technical evaluation, always inspect:
   - `architecture_doc` declared in the workspace `.agents/quench_stack.yaml`;
   - `constraints` declared in `quench_stack.yaml` (environmental, concurrency, and security boundaries);
   - Recent tasks and `CHANGELOG.md`.

3. **Decouple Objective Defects from Preferences (缺陷与偏好解耦)**:
   - *Objective Defects (客观缺陷)*: Memory/resource leaks, race conditions, missing exception handling, or contract breaks. Must be highlighted as blocking items.
   - *Subjective Preferences (主观偏好)*: Stylistic choices, variable naming aesthetics, or optional design patterns. Record only as non-blocking suggestions.

4. **Anti-Overengineering (拒绝过度设计)**:
   Ground designs in the real operational context (e.g., local offline networks, embedded edge nodes, single-process CLI) without indiscriminately imposing internet-scale distributed overheads.

---

## 2. Graded Quality Auditing (质量弹性分级规范)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Defensive & Edge Checks (防御与边缘校验)                   │
│    ★ Context-Proportional (Bound to Actual Changed Paths)   │
│    • Bound to changed paths; no unrequested locks/fallbacks │
│    • Null / None / undefined & boundary overflow defense    │
│    • Steps focus on intent & anchors without boilerplate    │
│    • Preserve essential code snippets for runner reuse      │
│    • File handle, stream, and connection cleanup            │
├─────────────────────────────────────────────────────────────┤
│ 2. Implementation Scope (实现逻辑侵入度)                     │
│    ★ Localized and Minimal (keep patches tight)             │
│    • Prefer targeted fixes over wholesale rewrites          │
│    • Guarantee backward compatibility for active interfaces │
├─────────────────────────────────────────────────────────────┤
│ 3. Type Safety & Suggestions (类型定义与重构建议)             │
│    ★ Flexible Suggestions, Non-Blocking Delivery            │
│    • Progressive typing annotations                         │
│    • Future architectural suggestions recorded in roadmaps  │
└─────────────────────────────────────────────────────────────┘
```

> 💡 **Context-Proportional Review Discipline (成比例审查纪律)**:
> - **No Unrequested Defense Layers (禁止无端防御层)**: 严格绑定实际变更路径与代码上下文。禁止凭空引入未请求的并发锁、线程安全同步、缓存层或离线降级分支（仅当目标代码客观涉及并发或外部 I/O 时审查并发与降级）。
> - **Boilerplate-Free Steps (免写样板、写了即用)**: `steps` 聚焦修改意图与关键代码锚点，不代写常规样板代码；若任务单中已给出关键代码片段或类型定义，则直接完整保留供 Runner 执行模型复用。

---

## 3. Standard Task Proposal Format (任务交付标准模板)

> 🛡️ **Language Mirroring & Anti-Translation Rule (语言镜像与反翻译规范)**:  
> - **Mirror Active Language**: If the existing DevTask file is written in Chinese (e.g. using `#### 【涉及文件】`, `#### 【缺陷根因与修改目标】`, etc.), the Reviewer **MUST output the refined task and core fields in Chinese**.  
> - **Never Translate**: **NEVER translate Chinese task content or headings into English** (or vice versa). Always strictly mirror the developer's language choice.

When proposing remediation tasks, output valid DevTask markdown conforming to the six core fields (supporting either English or Chinese headings):

```markdown
### Task [Stage].[Num] ⬜ Pending / 待确认 — [Task Title]

#### [Affected Files]
```
[MODIFY] path/to/source_file.ext
[NEW] path/to/test_file.ext
```

#### [Root Cause & Target]
Root Cause: [Concise statement of underlying issue and trigger conditions]
Target: [Clear statement of intended engineering outcome]

#### [Type Contracts]
```[language]
[Key signatures, interfaces, or data models]
```

#### [Step-by-Step Instructions]
1. [Step 1: Underlying data structures or imports]
2. [Step 2: Core logic transformation]
3. [Step 3: Unit test assertions]

#### [Defensive & Edge Checks]
- [Invalid input handling]
- [Concurrency / resource boundaries]
- [Backward compatibility]

#### [DoD Verification Commands]
```bash
[Executable test commands]
```
```

---

## 4. Escalation Handling (升级处理流程)

When the agile runner model calls `dev_tasks_escalate` to awaken the Reviewer:
1. Thoroughly read files provided in `context_files` and the cited reason for escalation.
2. Formulate at least two viable options with clear trade-offs (Pros & Cons) for developer decision.
3. Once the path is approved, decompose it into standard DevTasks.

---

## 5. Review Channel Triage & Degraded Fallback (审查分流与降级卡片)

### 统一审查通路 (Unified Review Channels)
1. 自由问答 / 灵感评估 / 方案权衡 / 架构只读诊断 → 统一异步主通路：调用 `dev_reviewer_submit` 提交任务，通过 `dev_reviewer_poll` 轮询进度及获取结构化终态结果（以折叠结构防刷屏，详见规格 [`dev_tasks_mcp_specification.md`](../../../../dev_tasks_mcp_specification.md)），需止损时调用 `dev_reviewer_cancel`（无需任何 DevTask）；
2. 已有草案但六字段不达标 / 需拆分 / 需重估可行性 → `dev_tasks_refine_spec`；
3. 执行中反复失败 / 需要架构层面重新裁决 → `dev_tasks_escalate`；
4. 引擎不可用或异常终态 → 统一输出 `degraded` 降级卡片（`findings == ""`）并停机，**不得**在本会话内自行给出审查结论。

### 显式降级卡片样例 (Degraded Card Example)
当 `dev_reviewer_poll` 返回降级响应时，必须如实转呈给开发者，严禁由当前执行模型就地伪装 Reviewer 输出假评审：

```json
{
  "status": "degraded",
  "degraded_reason": "reviewer_not_configured",
  "findings": "",
  "handoff_prompt": "审查引擎未配置或当前离线。请开启新会话并切换到旗舰 Reviewer 模型后重新提问；当前会话的实现模型不会、也不得代行架构审查职责。"
}
```

