# Quench Dev-Tasks Resident Discipline (开发任务常驻执行纪律)

As an AI coding assistant operating within Quench governance, you MUST adhere to the following resident discipline tiers:

---

## 1. State Machine Progression Discipline (状态机推进纪律)

- **Strictly Advance via MCP Tools / 严禁手动编辑状态 Emoji 与 CLI 代偿**：Task state transitions (`⬜ 待确认` -> `✅ 已确认` -> `🔨 执行中` -> `✔️ 已完成`) MUST strictly be driven via MCP tools (`dev_tasks_confirm`, `dev_tasks_checkout`, `dev_tasks_complete`, `dev_tasks_escalate`). Manual emoji edits or CLI scripts (`python -c ...`) bypassing FastMCP tools are prohibited.
- **Single Active Task Serial Execution / 单核串行施工原则 (INV-1)**：Globally, at most ONE task is in `🔨 执行中` state at any moment.
- **State Machine is MCP-Only (INV-2)**: Never hand-edit status in Markdown; use MCP tools only.
- **Session Startup Self-Check / 会话启动自检**：Call `dev_tasks_status` before modifying code.

---

## 2. Implementation Scope Discipline (执行阶段纪律)

- **Strict Adherence to Whitelist / 严格遵循【涉及文件】清单**：Only touch files listed in `[Affected Files] / 【涉及文件】` of the active `🔨 执行中` task.
- **Six Core Fields Preservation / 六核心字段规约**：Every task must define:
  1. `【任务目标】 / Objective`
  2. `【上下文与现状】 / Context & Status`
  3. `【涉及文件】 / Touched Files`
  4. `【改动计划】 / Implementation Plan`
  5. `【单测断言】 / Unit Test Assertions`
  6. `【交付物与验证】 / Deliverables & Verification`
- **Mandatory Test Assertions / 改逻辑必加单测断言**：Modifications to core logic, algorithms, or API contracts MUST include unit test assertions, verified via `【交付物与验证】 / Deliverables & Verification` commands.
- **Physical Feasibility Gate (INV-7)**: Draft tasks must pass path & test dry-runs before promotion.
- **Context Budget Cap (INV-8)**: Injection context is bounded by `max_total_injection_chars`.
- **Preserve Architecture & Comments / 保持代码风格与注释完整**：Preserve docstrings, architectural rationale, and system constraints.

---

## 3. Review & Planning Discipline (审查与规划纪律)

- **Read-Only Analysis (INV-6) / 审查阶段绝不碰源码**: In review mode, diagnose issues and plan DevTasks. Modifying production code during review is strictly prohibited.
- **Context & Docs First / 先读文档与规范**: Consult architecture documents and constraints before planning.
- **Vendor Neutrality (INV-5)**: No hard-coded model vendor literals in core modules.
- **Single Provider Egress (INV-9)**: All model calls must use the designated Reviewer client; zero raw API bypass.
- **Distinguish Objective Bugs from Preferences / 区分客观缺陷与主观偏好**: Objective bugs (races, leaks, violations) require reproduction; subjective preferences are non-blocking suggestions.
- **Language Layering & Mirroring Contract / 语言分层与镜像契约**: MCP tools and specs follow English SSOT; task descriptions support Chinese or English. Strictly mirror existing task language without unsolicited translation. Propose new tasks via `dev_tasks_propose` or Reviewer refinement.

---

## 4. Reviewer Handoff & Resume Discipline (架构审查交接与多会话复工纪律)

- **Automated In-Band Relay as Default (带内自动化审查为主通路)**: In standard development with Reviewer API (`dev_reviewer_submit`) or Reviewer subagent available, the entire lifecycle (`PROPOSE` -> `REVIEW` -> `CONFIRM` -> `CHECKOUT`) proceeds automatically in-band. Agents MUST NOT emit handoff cards or interrupt the relay flow.

### ① When to Halt (停机与上报触发条件)
Halt further development and output a handoff or delivery card ONLY when:
1. Terminal or stopping state is reached in Autopilot (`PAUSE_FOR_ACCEPTANCE`, `BLOCKED`, `ROADMAP_DONE`, or configured `stop_at` breakpoint stage reached);
2. Complex conflicts or interface breaks occur (`dev_tasks_escalate`) AND no automated reviewer channel is functional;
3. Manual/degraded mode where no Reviewer API / subagent is available (`strategy == "manual"` or offline).

**Continuous Relay Non-Braking Invariant (AGENTS.md §6)**:
In continuous relay states (`PROPOSE`, `REVIEW`, `CONFIRM`, `CHECKOUT`, `DISPATCH_RUNNER`, `SYNC_DOCS`, `ARCHIVE`, `NEXT_BATCH_PROPOSE`), agents MUST NOT prematurely end turns to dump handoff or C3 delivery cards. Development continues automatically via `harness_next_action`.

### ② Handoff Card Format (标准上报格式)
Upon reaching a stopping state or degraded fallback, halt and output a standard handoff card using `> [!IMPORTANT]`:
> [!IMPORTANT]
> ### ⏸️ Quench Task Handoff: Awaiting Architecture Review / Acceptance
> - **Target DevTask**: `docs/dev_tasks/<file>.md` (Task ID: <id>)
> - **Reason**: <Reason for pause or review>
> 
> **👉 Low-Token Handoff Steps (Offline/Manual Fallback Only):**
> 1. Open a fresh conversation session; switch to Strategic Reviewer Model (or check status via `dev_tasks_status`).
> 2. Submit prompt: `Please review and refine docs/dev_tasks/<file>.md`.
> 3. After tasks are marked `✅ 已确认`, switch back and continue.
*(Note: When Reviewer API or reviewer subagent is configured, the system executes this automatically via `dev_reviewer_submit` / subagent dispatch without manual session switching).*

### ③ Resume Verification (复工确认机制)
1. Check task status via `dev_tasks_status`;
2. Verify target task is `✅ 已确认` with all six core fields intact;
3. Checkout task via `dev_tasks_checkout` to transition to `🔨 执行中`.

---

## 5. Fast-Track & Anti-Abuse Discipline (快速通道与反滥用纪律)

### ① Three-Tier Progressive Protection
1. **Tier 1: Static Whitelist**: Declared in `quench_stack.yaml` (`allow_untracked_patterns`).
2. **Tier 2: Dynamic Session Bypass**: Activated via `dev_tasks_set_bypass` with physical lock and auto-expiry.
3. **Tier 3: Interactive Decision Prompt**: PreToolUse hook physical intercept (`force_ask`).

### ② Pre-Commit Guard (Git 提交物理防线配合)
Pre-commit guard blocks commits modifying out-of-scope files or without an active task.

---

## 6. 防自证偏见与严禁就地角色扮演纪律 (Strict Ban on In-Context Reviewer Impersonation)

### ① 触发意图识别 (Trigger Recognition)
当用户提出审查、评估、二审、复盘、挑刺、红队意图时，必须判定为审查类意图，受本纪律管辖。

### ② 唯一合法通道 (Mandatory External Channels)
- 异步主通路：`dev_reviewer_submit` 提交并由 `dev_reviewer_poll` 轮询获取结果（需止损时调用 `dev_reviewer_cancel`）；
- 规约打磨：`dev_tasks_refine_spec`；
- 执行受阻：`dev_tasks_escalate`。

### ③ 行为红线 (Hard Red Lines & INV-3 / INV-4)
- 严禁角色扮演：主模型不得伪装 Reviewer 输出评审结论；
- 严禁把主模型自身分析包装为「Reviewer 的意见 / 二审结论」；
- 严禁自证偏见：引擎未配置或离线时，严禁填充 `findings` 掩盖降级（INV-3 协议铁律：degraded 输出必须 `findings == ""`）；
- 严禁未经 MCP 物理调用声称已调 Reviewer；
- Stdio channel purity (INV-4): `stdout` 保留给 JSON-RPC，服务端零 `print()`。

### ④ 引擎缺失时的显式降级 (Mandatory Degraded Card)
当 `dev_reviewer_poll` 返回 `status="degraded"` 或 `degraded_reason="reviewer_not_configured"` 时，必须转呈降级卡，明确告知开发者审查引擎离线，当前会话实现模型不得代行审查职责。

---

## 7. Pre-Confirm 审计策略门禁纪律 (Pre-Confirm Audit Gate Discipline)

### ① 拦截目标与定位
在执行 `dev_tasks_confirm` 时，验证受管路径任务具备真实的外部审查记录（诚实成本 < 绕过成本）。

### ② 审查凭据通道与来源策略 (Attestation Channels & Accepted Sources)
- **审查凭据通道**:
  1. `dev_reviewer_poll`: 异步审查轮询终态记录；
  2. `dev_tasks_refine_spec`: 规约强化与 AST 审查引擎生成的审查记录 (`source="refine_spec"`)。
- **accepted_sources 来源控制**:
  由 `quench_stack.yaml` 中 `audit_gate.accepted_sources` 配置（默认 `["reviewer_poll", "refine_spec"]`）。仅受信任来源的审查记录被接纳为有效放行凭据。
- **SAFETY_DOWNGRADE_DENIED 防降级膨胀**:
  当审查记录来源不在 `accepted_sources` 时阻断（拒绝原因 `record_source_not_accepted`）；当自动回退来源不被接纳时阻断（拒绝原因 `record_auto_fallback_not_accepted`）；当审查判定包含需返工结论时阻断（拒绝原因 `record_rework`）。

### ③ 确定性守卫序阶梯 (R11 互斥完备)
1. **disabled**: 门禁未开启时放行；
2. **not_managed_scope**: 未涉及受管路径时放行；
3. **session_bypass_active**: Tier-2 旁路有效且 session_id 匹配时放行；
4. **explicit_inverted_orchestrator**: 当工作区处于显式委派编排模式（`effective_mode == "inverted"` 且 `mode_source == "explicit"`，旗舰主会话直接担任 `reviewer_orchestrator`）且无可读审计日志（`log_missing`）或可读尾部无匹配记录（`tail_window_exhausted` / `no_matching_record`）时安全放行；`auto_fallback` 模式绝不适用该放行；
5. **日志完整性与记录匹配**:
   - 降级族 (`log_missing`, `log_unparsable`, `record_degraded`, `record_timestamp_invalid`, `tail_window_exhausted`) 受 `effective_on_degraded` 策略控制；
   - 缺失族 (`record_stale`, `no_matching_record`, `record_source_not_accepted`, `record_auto_fallback_not_accepted`, `record_rework`) 受 `on_missing_record` 控制；
   - 内部错误 (`internal_error`) fail-open 放行；
6. **matched**: 尾部记录逆序扫描匹配到未过期的有效审查记录时放行。

### ④ 锁内重校验与 precondition_changed
`dev_tasks_confirm` 获锁后重算 `canonical_artifact_ref` 并断言状态仍为 `⬜ 待确认`，不满足时阻断。

---

## 8. Runner Completion Delivery Card Contract (C3 完工交付卡契约)

- **Output Timing / 交付卡输出时机**:
  - The C3 delivery card MUST ONLY be output at stopping points or terminal states (`PAUSE_FOR_ACCEPTANCE`, `BLOCKED`, `ROADMAP_DONE`).
  - In continuous relay states (`PROPOSE`, `REVIEW`, `CONFIRM`, `CHECKOUT`, `DISPATCH_RUNNER`, `SYNC_DOCS`, `ARCHIVE`, `NEXT_BATCH_PROPOSE`), agents MUST NOT prematurely end turns to dump C3 cards.
- **Compact 4-Line Output / 极简 4 行卡（≤5行）**：Upon reaching a stopping state or roadmap completion, final response MUST adhere to:
  1. `[Task ID] ✔️ Completed` / `[Task ID] ✔️ 已完成`
  2. **Affected Files / 涉及文件**：Compact list of touched files with clickable markdown links
  3. **Verification / 自动化验证**：Summary of passed assertions (`N passed, 0 failed`)
  4. **Anchor & Guidance / 锚点与指引**：Git rollback tag & pointer to updated roadmap/spec
- **Anti-Verbose Dumping**: Never dump raw deletion ledgers, full diff tables, or token recitations into chat turns.
- **Carve-Out & Mirroring**: Degraded states use §4 Handoff Card; language mirrors task/user language.
