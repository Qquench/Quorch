# Quench Dev-Tasks Resident Discipline (开发任务常驻执行纪律)

As an AI coding assistant operating within the Quench governance framework, you MUST strictly adhere to the following resident discipline tiers:

---

## 1. State Machine Progression Discipline (状态机推进纪律)

- **Strictly Advance via MCP Tools / 严禁手动编辑状态 Emoji 与 CLI 代偿**：Task state transitions (e.g., from `[Pending] / ⬜ 待确认` to `[Confirmed] / ✅ 已确认`, or `[Confirmed]` to `[In Progress] / 🔨 执行中` and `[Completed] / ✔️ 已完成`) **MUST strictly be driven via quench-dev-tasks MCP Tools** (`dev_tasks_confirm`, `dev_tasks_checkout`, `dev_tasks_complete`, `dev_tasks_escalate`). Direct manual text replacement of task markdown status icons OR running ad-hoc terminal CLI scripts (e.g., `python -c ...`) to simulate or bypass MCP tools is strictly prohibited. In Lazy-MCP environments (such as Antigravity), tools MUST be invoked via the host's lazy interface: `call_mcp_tool(ServerName="quench-dev-tasks", ToolName="...", Arguments={...})`.
- **Single Active Task Serial Execution / 单核串行施工原则**：Globally, **only ONE task is permitted to be in `[In Progress] / 🔨 执行中` state at any given moment**. Before starting a new task, the active task must first be marked as `[Completed] / ✔️ 已完成` (with full DoD tests passing) or transitioned to `[Rework] / 🔄 需返工` / `[Confirmed] / ✅ 已确认`.
- **Session Startup Self-Check / 会话启动自检**：At the start of every new conversation or development session, the immediate mandatory action is to invoke `dev_tasks_status` to inspect the project task landscape.

---

## 2. Implementation Scope Discipline (执行阶段纪律)

- **Strict Adherence to Whitelist / 严格遵循【涉及文件】清单**：When making code modifications, you may only touch files explicitly listed under `[Affected Files] / 【涉及文件】` of the currently active `[In Progress] / 🔨 执行中` task (governed whitelist: `【涉及文件】`).
- **Physical Interception & Explicit Approval / 物理拦截与例外确认**：Any tool call attempting to modify an out-of-scope file triggers a PreToolUse physical hook intercept. If modifications outside the whitelist are genuinely required, detail the rationale in the tool call `Description` and wait for explicit human authorization.
- **Mandatory Test Assertions / 改逻辑必加单测断言**：Any task modifying core business logic, algorithms, or API contracts MUST include or update accompanying unit test assertions in the test directory, validated via `[DoD Verification Commands] / 【DoD 验证命令】`.
- **Preserve Architecture & Comments / 保持代码风格与注释完整**：Preserve existing architectural explanations, design rationale, and docstrings. Strictly respect engineering constraints defined in the workspace `.agents/quench_stack.yaml`.

---

## 3. Review & Planning Discipline (审查与规划纪律)

- **Read-Only Analysis — Never Touch Source Code (审查阶段绝不碰源码)**: In review mode or solution planning, the AI's sole duty is to diagnose issues, analyze architecture, and draft DevTasks. Modifying production code during review is strictly prohibited.
- **Context & Docs First (先读文档与项目规范)**: Before reviewing, consult the project architectural documents specified in `.agents/quench_stack.yaml` (`architecture_doc`) and declared constraints (`constraints`).
- **Distinguish Objective Bugs from Preferences (严格区分客观缺陷与主观偏好)**:
  - *Objective Defects*: Memory leaks, race conditions, unhandled exceptions, data corruption risks, contract violations. Must be cited with concrete reproduction steps.
  - *Subjective Preferences*: Formatting inclinations or naming aesthetics. Treat only as non-blocking suggestions.
- **Respect Scope and Reject Overengineering (尊重项目定位，拒绝过度设计)**: Align strictly with practical project scope without introducing unnecessary high-complexity abstractions.
- **Language Layering & Mirroring Contract (语言分层与镜像契约)**:
  - *L1 Protocol SSOT (English)*: MCP tool signatures, backend field validators, architecture specifications, and CHANGELOGs follow English as the single source of truth (SSOT).
  - *L3 Task Content Freedom (母语自由)*: DevTask markdown documents (`docs/dev_tasks/`) natively support and welcome the developer's preferred working language (Chinese, English, or bilingual). The schema validator natively accepts canonical English or Chinese headers (`【涉及文件】` ≡ `[Affected Files]`, `【缺陷根因与修改目标】` ≡ `[Root Cause & Target]`, etc.).
  - *Mandatory Mirroring (强制镜像)*: When reading, updating, or executing existing DevTasks, the AI **MUST strictly mirror** the task's existing language and heading style. **Never translate, normalize, or rewrite Chinese task descriptions or headers into English** (or vice versa) without explicit human request.
  - *New Task Generation (新建任务)*: When generating new tasks via `dev_tasks_propose` or Reviewer refinement, mirror the dominant language of active tasks in the workspace.

---

## 4. Reviewer Handoff & Resume Discipline (架构审查交接与多会话复工纪律)

To prevent long-session token bloat, safeguard flagship model budgets, and guarantee architectural quality:

> **Role Decoupling Definition**: The "Reviewer" represents the user-allocated flagship reasoning model chosen for high-level analysis and task decomposition. The Reviewer role is selected decoupled via user configuration or IDE selection.

### ① When to Halt (停机与上报触发条件)
The runner model **MUST immediately halt further development and code editing** when:
1. Tasks are `[Pending] / ⬜ 待确认` or `[Rework] / 🔄 需返工`, requiring architectural review or guideline revision;
2. Tasks previously marked `[Confirmed]` require rework (degrade via `dev_tasks_confirm(action="rework")`);
3. Batch completion is reached (current batch of confirmed tasks is done, remaining tasks are pending/rework);
4. Complex conflicts, breaking interface changes, or escalation via `dev_tasks_escalate` occur;
5. DevTask guidelines lack clarity.

### ② Handoff Card Format (标准上报格式)
Halt and output a standard handoff card using native GitHub Flavored Markdown blockquotes:

> [!IMPORTANT]
> ### ⏸️ Quench Task Handoff: Awaiting Architecture Review & Plan Revision
> - **Target DevTask**: `docs/dev_tasks/<file>.md` (Task ID: <id>)
> - **Reason**: <Clear reason why strategic review / rework is needed>
> 
> **👉 Low-Token Handoff Steps:**
> 1. Click `+` to open a **fresh conversation session** (clean context, minimal tokens);
> 2. Switch to your allocated **Strategic Reviewer Model**;
> 3. Submit prompt: `Please review and refine docs/dev_tasks/<file>.md`;
> 4. The Reviewer finalizes the plan and marks tasks as `[Confirmed] / ✅ 已确认`;
> 5. **Switch back to this session** and reply `Ready to proceed` or `Continue`.

### ③ Resume Verification (复工确认机制)
Upon developer confirmation:
1. Re-read disk status via `dev_tasks_status`;
2. Verify target task is `[Confirmed] / ✅ 已确认` with all six core fields intact;
3. Checkout task via `dev_tasks_checkout(task_id=...)` to transition to `[In Progress] / 🔨 执行中` and implement.

---

## 5. Fast-Track & Anti-Abuse Discipline (快速通道与反滥用纪律)

### ① Three-Tier Progressive Protection
1. **Tier 1: Static Whitelist (Configuration Tier)**: Declared in `.agents/quench_stack.yaml` (`fast_track_rules.allow_untracked_patterns`). Starts empty.
2. **Tier 2: Dynamic Session Bypass (Session Tier with Physical Lock)**: Activated via `dev_tasks_set_bypass`. Requires exact session ID matching; auto-expires (default 4h, max 8h).
3. **Tier 3: Interactive Decision Prompt (Interaction Tier)**: PreToolUse hook physical intercept (`decision: "ask"` / `force_ask`) returning ultimate control to the developer.

### ② Pre-Commit Guard (Git 提交物理防线配合)
- Pre-commit guard is enabled. Git commits modifying files outside the active task scope or without an active task will be physically blocked by `scripts/git_pre_commit_guard.py`.

---

## 6. 防自证偏见与严禁就地角色扮演纪律 (Strict Ban on In-Context Reviewer Impersonation)

### ① 触发意图识别 (Trigger Recognition)
当用户表达包含但不限于「审查 / 评估 / 二审 / 复盘 / 挑刺 / 红队 / 让 Reviewer 看一下 / 这个设计有没有问题」
等意图时，主模型必须判定为**审查类意图**，进入本纪律管辖范围。

### ② 唯一合法通道 (Mandatory External Channels)
审查类意图的结论只能来自异构外部推理通道，且必须通过 MCP 工具物理发起：
- 自由问答 / 灵感评估 / 方案权衡 / 只读诊断 → 统一异步主通路 `dev_reviewer_submit` 提交并由 `dev_reviewer_poll` 轮询获取结果（`dev_reviewer_consult` 提供非阻塞引导卡）；
- 任务规约强化 / 六字段草案打磨 → `dev_tasks_refine_spec`；
- 执行受阻上报 → `dev_tasks_escalate`。

### ③ 行为红线 (Hard Red Lines)
- 严禁在当前对话中以 Reviewer 口吻直接输出评审结论（就地伪装）；
- 严禁把主模型自身的分析包装为「Reviewer 的意见 / 二审结论」；
- 严禁在引擎未配置或离线时，用主模型输出填充 `findings` 掩盖降级事实；
- 严禁声称已调用 Reviewer 而实际未发起任何 MCP 工具调用。

### ④ 引擎缺失时的显式降级 (Mandatory Degraded Card)
`dev_reviewer_poll` 或 `dev_reviewer_consult` 返回 `status="degraded"` 或 `degraded_reason="reviewer_not_configured"` 时，
主模型必须原样转呈降级卡，并明确告知开发者：
> 审查引擎未配置或当前离线。请开启新会话并切换到旗舰 Reviewer 模型后重新提问；
> 当前会话的实现模型不会、也不得代行架构审查职责。

---

## 7. Pre-Confirm 审计策略门禁纪律 (Pre-Confirm Audit Gate Discipline)

### ① 拦截目标与定位
在执行模型调用 `dev_tasks_confirm` 将任务从 `⬜ 待确认` 推进至 `✅ 已确认` 时，物理门禁验证该任务在 Tier-1 受管路径生效范围内的审查真实性记录。审计门禁是【纪律强制函数】而非对抗性安全边界，核心目标是确保「诚实成本 < 绕过成本」。

### ② 确定性守卫序阶梯 (R11 互斥完备)
1. **Disabled 放行** (`disabled`): `audit_gate.enabled` 为 false 时放行。
2. **非受管资产放行** (`not_managed_scope`): 任务涉及文件均未命中 `managed_paths` 时天然豁免放行。
3. **会话旁路放行** (`session_bypass_active`): 当前会话在有效时间内具备 Tier-2 旁路时放行（`session_id=None` 绝不放行）。
4. **日志完整性与记录匹配**:
   - 降级族分支：日志缺失 (`log_missing`)、日志不可解析 (`log_unparsable`)、降级记录 (`record_degraded`)、时间戳异常 (`record_timestamp_invalid`) 及尾读窗口耗尽 (`tail_window_exhausted`)，统一受全局单点 `effective_on_degraded` 策略控制（`tail_window_exhausted_policy` 弃用为兼容别名，遵循 `block > warn > allow` 最严优先合并）；
   - 缺失族分支：记录过期 (`record_stale`)、无匹配记录 (`no_matching_record`) 恒受 `on_missing_record` 策略控制（默认 `block`）；
   - 内部错误 (`internal_error`) 遵循结构性 fail-open (永远放行)。
5. **最新有效审计匹配** (`matched`): 逆序扫描尾部记录，优先命中 canonical artifact_ref 且时间戳在容差内新鲜且未降级时允许流转（未命中且日志截断时，才落入 `tail_window_exhausted`，且排在 `no_matching_record` 之前判定）。

### ③ 锁内重校验与 precondition_changed
门禁在 manifest 锁外进行只读裁决。`dev_tasks_confirm` 获锁后，必须重算 `canonical_artifact_ref` 并断言任务仍处于 `⬜ 待确认` 状态；任一前置条件不满足时以 `precondition_changed` fail-closed 阻断，manifest 零写入。

---

## 8. Runner Completion Delivery Card Contract (C3 完工交付卡契约)

- **Compact 4-Line Output / 极简 4 行卡（≤5行）**：Upon calling `dev_tasks_complete`, the runner model's final response in the chat turn MUST strictly adhere to:
  1. `[Task ID] ✔️ Completed` / `[Task ID] ✔️ 已完成`
  2. **Affected Files / 涉及文件**：Compact list of touched files with clickable markdown links
  3. **Verification / 自动化验证**：Summary of passed test assertions (e.g. `N passed, 0 failed`)
  4. **Anchor & Guidance / 锚点与指引**：Git rollback tag & pointer to updated roadmap/spec
- **Anti-Verbose Dumping / 严禁正文倾倒大表**：Never dump raw deletion ledgers, full diff tables, or recitation of zero-delete token counts into chat turns. These details belong to task artifacts and automated gate assertions.
- **Carve-Out & Mirroring / 异常降级与语言镜像**：Degraded/escalation states use §4 Handoff Card; card language mirrors task/user language (L3 contract).
