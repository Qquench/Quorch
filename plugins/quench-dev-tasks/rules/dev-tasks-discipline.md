# Quench Dev-Tasks Resident Discipline (开发任务常驻执行纪律)

As an AI coding assistant operating within the Quench governance framework, you MUST strictly adhere to the following resident discipline tiers:  
（作为在 Quench 架构体系下工作的 AI 编程助手，你必须严格遵循以下三层纪律约束：）

---

## 1. State Machine Progression Discipline (状态机推进纪律)

- **Strictly Advance via MCP Tools / 严禁手动编辑状态 Emoji**：Task state transitions (e.g., from `[Pending] / ⬜ 待确认` to `[Confirmed] / ✅ 已确认`, or `[Confirmed]` to `[In Progress] / 🔨 执行中` and `[Completed] / ✔️ 已完成`) **MUST strictly be driven via quench-dev-tasks MCP Tools** (`dev_tasks_confirm`, `dev_tasks_checkout`, `dev_tasks_complete`, `dev_tasks_escalate`). Direct manual text replacement of task markdown status icons is prohibited.  
  （任务状态的流转必须严格调用 MCP Tools，不得通过 `replace_file_content` 或 `write_to_file` 手动篡改任务 Markdown 文件的状态图标。）
- **Single Active Task Serial Execution / 单核串行施工原则**：Globally, **only ONE task is permitted to be in `[In Progress] / 🔨 执行中` state at any given moment**. Before starting a new task, the active task must first be marked as `[Completed] / ✔️ 已完成` (with full DoD tests passing) or transitioned to `[Rework] / 🔄 需返工` / `[Confirmed] / ✅ 已确认`.  
  （同一时间内，只能有一个任务处于 `🔨 执行中` 状态。未领单严禁动源码 / 在未检出任务前不得修改代码。）
- **Session Startup Self-Check / 会话启动自检**：At the start of every new conversation or development session, the immediate mandatory action is to invoke `dev_tasks_status` to inspect the project task landscape.  
  （在新会话或新一轮开发启动时，首要动作是调用 `dev_tasks_status` 了解当前项目任务全景。）

---

## 2. Implementation Scope Discipline (执行阶段纪律)

- **Strict Adherence to Whitelist / 严格遵循【涉及文件】清单**：When making code modifications, you may only touch files explicitly listed under `[Affected Files] / 【涉及文件】` of the currently active `[In Progress] / 🔨 执行中` task.  
  （进行代码修改时，只能触碰当前 `🔨 执行中` 任务中【涉及文件】清单内列出的文件。）
- **Physical Interception & Explicit Approval / 物理拦截与例外确认**：Any tool call attempting to modify an out-of-scope file triggers a PreToolUse physical hook intercept. If modifications outside the whitelist are genuinely required, detail the rationale in the tool call `Description` and wait for explicit human authorization.
- **Mandatory Test Assertions / 改逻辑必加单测断言**：Any task modifying core business logic, algorithms, or API contracts MUST include or update accompanying unit test assertions in the test directory, validated via `[DoD Verification Commands] / 【DoD 验证命令】`.  
  （凡是修改核心业务逻辑、算法或接口行为，必须在测试目录追加单测断言，杜绝功能回归。）
- **Preserve Architecture & Comments / 保持代码风格与注释完整**：Preserve existing architectural explanations, design rationale, and docstrings. Strictly respect engineering constraints defined in the workspace `.agents/quench_stack.yaml`.

---

## 3. Review & Planning Discipline (审查与规划纪律)

- **Read-Only Analysis — Never Touch Source Code (审查阶段绝不碰源码)**: In review mode or solution planning, the AI's sole duty is to diagnose issues, analyze architecture, and draft DevTasks. Modifying production code during review is strictly prohibited.
- **Context & Docs First (先读文档与项目规范)**: Before reviewing, consult the project architectural documents specified in `.agents/quench_stack.yaml` (`architecture_doc`) and declared constraints (`constraints`).
- **Distinguish Objective Bugs from Preferences (严格区分客观缺陷与主观偏好)**:
  - *Objective Defects*: Memory leaks, race conditions, unhandled exceptions, data corruption risks, contract violations. Must be cited with concrete reproduction steps.
  - *Subjective Preferences*: Formatting inclinations or naming aesthetics. Treat only as non-blocking suggestions.
- **Respect Scope and Reject Overengineering (尊重项目定位，拒绝过度设计)**: Align strictly with practical project scope without introducing unnecessary high-complexity abstractions.

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
