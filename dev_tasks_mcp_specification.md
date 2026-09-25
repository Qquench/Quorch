# Quench-DevTasks MCP Service Architecture & Specification (DevTasks Orchestrator Spec)

> **Version**: v1.7.0 (Implemented & Verified)  
> **Implementation Status**: ✔️ Fully implemented and verified with 572+ automated unit tests (covering Google Antigravity, Cursor cross-tool adapters, vendor-neutral ReviewerClient engine & `PROVIDER_PRESETS` registry, source-level neutrality scan gate, ad-hoc architectural consultation `dev_reviewer_consult`, async job system `dev_reviewer_submit`/`poll`/`cancel`, single-egress AST gate, anti-roleplaying governance, RotatingFileSink observability, Draft task state & physical feasibility lint gate, and unified CLI)  
> **Source Specification**: `dev_tasks_mcp_specification.md`  
> **Workflow Reference**: [DevTasks Workflow Specification](plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md)  
> **Role & Purpose**: General-purpose development task governance and dual-model orchestration MCP server for engineering repositories.

---

## 1. Provenance & Core Architectural Philosophy

### 1.1 Provenance from Manual Protocols
This MCP service mechanizes and enforces the **"Dual-Model Task Governance Workflow"** established in the [DevTasks Workflow Specification](plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md). It transforms conversational, document-level soft conventions into an **external code-level supervisory daemon (MCP Server)** featuring strict lifecycle state machines, physical scope guards, and graded quality auditing.

### 1.2 Dual-Model Division of Labor: Strategic Reviewer + Everyday Runner
Quench separates software development cognitive load into two complementary operational tiers:
- **Agile Runner (Everyday Executor)**: Resident in the primary IDE session, handling 80%+ of routine tasks (status inspections, file modifications, test executions) without expending flagship reasoning budgets.
- **Strategic Reviewer (On-Demand Architect)**: Activated only via explicit instruction (e.g. `dev_reviewer_consult`) or automated escalation for multi-module planning, architectural impasse resolution, and quality auditing. Sleeps immediately upon task decomposition.

> 📖 **Architectural SSOT**: For the deep cognitive model division and system vision, see [docs/architecture/README.md §1](docs/architecture/README.md#1-system-vision--core-problem).

### 1.3 Model Decoupling & Pluggable ReviewerClient Architecture
The MCP server operates as an independent daemon (FastMCP over stdio JSON-RPC) with strict vendor neutrality:
- **No Proprietary Vendor Literals**: Core modules contain zero hard-coded model strings (enforced by `test_no_vendor_literals_in_core.py` and `test_no_api_bypass.py`).
- **Pluggable Engine Presets**: Upstream providers (`openai`, `deepseek`, `ollama`, `vllm`, `generic-openai`, `custom`) are configured declaratively in `.agents/quench_stack.yaml` and resolved via the `PROVIDER_PRESETS` registry (`ReviewerClient`).
- **Generic Protocol Support**: Standardized OpenAI-compatible `/chat/completions` streaming, generic CoT extraction (`delta.reasoning_content` / `delta.thought`), and local offline inference.
- **Graceful Degraded Fallback**: Emits structured degraded cards with `findings == ""` when an external engine is unconfigured, preventing in-context hallucination or impersonation.

> 📖 **Configuration & Topology Reference**: For sample configuration and the 4-tier system topology, see [docs/architecture/README.md §2](docs/architecture/README.md#2-four-tier-architecture-topology) and [templates/quench_stack.yaml](plugins/quench-dev-tasks/templates/quench_stack.yaml).

---

## 2. Mechanized Core Governance Rules

### 2.1 Review Behavior Protocols
| Rule | Mechanized Enforcement & Guard Behavior |
| :--- | :--- |
| **Never edit source code during review** | When operating in Reviewer context, only read-only retrieval and task proposing tools (`dev_tasks_propose`) are permitted; code editing tools are physically blocked. |
| **Read documentation before code** | Context warnings are emitted if architectural guides are not consulted before task formulation. |
| **Distinguish bugs from style preferences** | Every proposed item must cite concrete risks (data corruption, crashes, boundary violations, performance regression) rather than superficial cosmetic styles. |
| **Respect environment boundaries** | Architectural rules forbid imposing public-internet constraints (e.g., public JWT rotations) on isolated offline or edge architectures. |
| **Every issue must be verifiable** | The `[Root Cause & Target]` field must present concrete trigger scenarios or collision points. |
| **Offer choices without arbitrary decisions** | When encountering architectural trade-offs, the Reviewer provides Option A/B and marks the task as `[Pending]`. |

---

### 2.2 The Six-Core-Field Structured Contract

Every DevTask must adhere to the structured six core fields. The schema validator (`schema_validator.py`) enforces these fields at the protocol boundary. To ensure complete developer freedom while maintaining strict physical enforcement, Quench establishes the canonical bilingual heading contract below:

| Canonical Field Key | English Heading | Chinese Heading | Purpose & Physical Governance Contract |
|---------------------|-----------------|-----------------|----------------------------------------|
| `affected_files` | `#### [Affected Files]` | `#### 【涉及文件】` | Whitelist of files allowed for modification by the Runner; enforced by PreToolUse hook (`file_scope_guard.py`). |
| `root_cause_target` | `#### [Root Cause & Target]` | `#### 【缺陷根因与修改目标】` | Architectural defect analysis, rationale, and target engineering state. |
| `type_contracts` | `#### [Type Contracts]` | `#### 【目标签名与类型契约】` | Target signatures, dataclasses, interfaces, and invariants to prevent implicit typing drift. |
| `step_by_step` | `#### [Step-by-Step Instructions]` | `#### 【分步改造指引】` | Ordered sequential execution steps with actionable verbs for the Runner. |
| `defensive_checks` | `#### [Defensive & Edge Checks]` | `#### 【防御与边缘校验】` | Boundary conditions, null checks, error handling, backward compatibility constraints. |
| `dod_commands` | `#### [DoD Verification Commands]` | `#### 【DoD 验证命令】` | Physical verification commands (pytest, lint) required to pass before `dev_tasks_complete`. |

> **Language Mirroring Contract**: When creating or editing tasks, the AI must mirror the language style of the existing task sheet (e.g. Chinese headings for Chinese tasks, English headings for English tasks). Never unilaterally translate headings.

#### 1. `[Affected Files]` (`#### [Affected Files]` / `#### 【涉及文件】`)
- **Format**: File paths prefixed with operation tags: `[MODIFY]`, `[NEW]`, `[DELETE]`, `[RENAME]`.
- **Granularity Guard**: If a single task touches more than 3 core files, a `TaskGranularityWarning` is issued suggesting decomposition.

#### 2. `[Root Cause & Target]` (`#### [Root Cause & Target]` / `#### 【缺陷根因与修改目标】`)
- **Format**: 1–2 concise sentences stating the underlying root cause and the expected engineering outcome.

#### 3. `[Type Contracts]` (`#### [Type Contracts]` / `#### 【目标签名与类型契约】`)
- **Principle**: Include only changed or introduced signatures; avoid duplicating entire classes.
- **Strict Typing**: Explicit interfaces, Pydantic schemas, or function signatures to eliminate implicit typing ambiguity.

#### 4. `[Step-by-Step Instructions]` (`#### [Step-by-Step Instructions]` / `#### 【分步改造指引】`)
- **Principle**: 3–5 numbered steps with sequential instructions.
- **Skeleton vs. Implementation**: Steps provide action verbs with key pseudo-code/skeletons, preventing over-specification.

#### 5. `[Defensive & Edge Checks]` (`#### [Defensive & Edge Checks]` / `#### 【防御与边缘校验】`)
- **Format**: Bulleted list detailing null checks, boundary overflows, concurrency locks, and fallback handling.

#### 6. `[DoD Verification Commands]` (`#### [DoD Verification Commands]` / `#### 【DoD 验证命令】`)
- **Principle**: Verifiable terminal test commands that must be executed and pass 100%.
- **Mandatory Assertion Rule**: Any alteration to business logic or interfaces must include accompanying unit test assertions.

### 2.3 Zero-Poll Observability & RotatingFileSink
To maintain full visibility during long-running architectural reasoning without flooding FastMCP stdio transport:
- **Low-Frequency MCP Heartbeats**: Context progress notifications are issued at a conservative ~1.0s interval, reporting estimated `progress_pct` and step counts.
- **Zero Stdout Pollution**: Standard output (`sys.stdout`) is strictly reserved for JSON-RPC frame delivery; arbitrary print statements are prohibited.
- **RotatingFileSink**: Real-time thinking and reasoning chunks are streamed directly into bounded log sinks (`.agents/.logs/reviewer_live.log`), enabling developers to inspect reasoning trajectories in real time via `tail -f` or terminal watchers.
- **Reasoning Loop Interruption**: Features a soft ceiling of 32,000 reasoning tokens and automated timeout interruption to guard against runaway hallucination loops.

### 2.4 Draft Task State & Physical Feasibility Lint Gate
To prevent hallucinated file paths and unverified commands from entering the formal task queue:
- **Draft State (`📝 草案`)**: Tasks marked with `(草案)` or `<!-- quench-task-meta: {"draft": true} -->` are segregated from active queues.
- **Queue Isolation**: By default (`include_drafts=False`), `dev_tasks_status` places draft items in `draft_queue` instead of `pending_queue`.
- **Physical Feasibility Linter (`lint_task_physical_feasibility`)**:
  1. *Path Traversal Defense*: Resolves paths relative to `workspace_root` and verifies `os.path.commonpath`.
  2. *Existence Validation*: `[MODIFY]` and `[DELETE]` files must physically exist on disk (`os.path.exists == True`).
  3. *Collision Guard*: `[NEW]` files must not already exist, and parent directories must be confined to the workspace.
  4. *DoD Command Sanity*: Dry-runs pytest commands (`pytest --collect-only -q -o pythonpath=.`) to ensure test syntax validity and blocks dangerous shell metacharacters (`;`, `&`, `|`, `$`, `` ` ``, `>`, `<`).
- **Atomic Promotion**: `dev_tasks_promote_draft` validates physical feasibility under cross-process file lock, removes draft annotations, and advances tasks to formal `⬜ 待确认` upon 100% green lint.

### 2.5 Anti-Roleplaying Protocol & Ad-Hoc Consultation (`dev_reviewer_consult`)
To address the "roleplaying loophole" and remove the requirement of task sheets for spontaneous architectural exploration:
- **Strict Anti-Roleplaying Invariant**: In-context impersonation of the Reviewer by the everyday executor model is strictly forbidden. When the external Reviewer engine is unconfigured or offline, tools MUST return a structured degraded card with **`findings == ""`**. Never fabricate critique text.
- **Atomic Ad-Hoc Consultation (`dev_reviewer_consult`)**: Exposes a direct read-only consultation tool supporting 4 modes (`critique`, `evaluate`, `brainstorm`, `audit`) without modifying tasks or creating files.
- **Read-Only Context Guard**: Enforces workspace path sandbox boundaries, line range window slices, and a default 40,000-character context budget (declaratively configurable via `.agents/quench_stack.yaml` up to 200,000 chars) to balance deep context inspection with token inflation defense.
- **Byte-Level Stable Prompt Prefix Caching**: System prompt prefixes are generated with thread-safe caching (`_PREFIX_CACHE`), maximizing upstream LLM Prompt Cache hit rates.

---

## 3. Task Lifecycle & State Transitions

The DevTasks state machine defines strict valid transitions enforced by `state_machine.py` under cross-process `filelock`.

> 📖 **Architectural State Diagram**: For the complete visual lifecycle flowchart and CAS concurrency rules, see [docs/architecture/README.md §3.1](docs/architecture/README.md#31-task-state-machine).

| State | Canonical Marker | Entry Condition / Tool | Next Allowed States |
| :--- | :--- | :--- | :--- |
| **Draft** | `📝 草案` / `(草案)` | Spec drafting (`dev_tasks_refine_spec`) | `Pending` (via `dev_tasks_promote_draft`) |
| **Pending** | `⬜ 待确认` / `[Pending]` | Propose task (`dev_tasks_propose`), or draft promotion | `Confirmed` (confirm), `Skipped` (skip) |
| **Confirmed** | `🟦 已确认` / `[Confirmed]` | Developer approval (`dev_tasks_confirm action=confirm`) | `In_Progress` (via `dev_tasks_checkout`) |
| **In Progress** | `🔨 进行中` / `[In Progress]` | Single task checkout (`dev_tasks_checkout`) [INV-1 locked] | `Completed` (`dev_tasks_complete`), `Rework` |
| **Rework** | `🔄 需返工` / `[Rework]` | Verification failure / rejection (`dev_tasks_confirm action=rework`) | `In_Progress` (re-checkout) |
| **Completed** | `✅ 已完成` / `[Completed]` | DoD commands pass 100% & scope clean (`dev_tasks_complete`) | `Archived` (via `dev_tasks_archive`) |
| **Skipped** | `⏭️ 已跳过` / `[Skipped]` | Developer bypass / cancellation | `Archived` (via `dev_tasks_archive`) |
| **Archived** | `📦 已归档` / `[Archived]` | Milestone batch retirement (`dev_tasks_archive`) | *(Terminal)* |

---

## 4. MCP Tools Specification

The server exposes 17 atomic FastMCP tools:

1. **`dev_tasks_status`**: Scans the workspace task directory, returning structured queue metrics (active, confirmed, rework, pending, draft) with optional draft segregation.
2. **`dev_tasks_propose`**: Validates the six core fields and proposes a new task in formal `[Pending]` status.
3. **`dev_tasks_confirm`**: Advances tasks to `[Confirmed]`, `[Skipped]`, or transitions them to `[Rework]`.
4. **`dev_tasks_checkout`**: Checks out the next confirmed task, sets its state to `[In Progress]`, captures a physical baseline snapshot, and provides step-by-step guidance.
5. **`dev_tasks_complete`**: Submits a completed task, requiring DoD test command output, physical test assertion auditing, and physical scope reconciliation against the declared whitelist.
6. **`dev_tasks_escalate`**: Awakens the Reviewer role with focused contextual snippets when encountering roadblocks.
7. **`dev_tasks_refine_spec`**: Runs multi-turn architectural reasoning via `ReviewerClient`, streaming reasoning logs and enforcing the physical lint gate.
8. **`dev_tasks_promote_draft`**: Validates physical feasibility of a draft task and promotes it to formal `[Pending]` state.
9. **`dev_tasks_archive`**: Retires closed tasks to `archive/` and increments the changelog.
10. **`dev_tasks_set_bypass`**: Manages temporary time-bound bypass tokens with strict audit logging.
11. **`dev_reviewer_consult`**: Direct ad-hoc architecture consultation tool with read-only sandbox guards, 4 modes, and real-time streaming thinking logs.
12. **`dev_tasks_heartbeat`**: Refreshes the active lease heartbeat for current or specified tasks, supporting multi-session isolation.
13. **`dev_tasks_reclaim`**: CAS-guaranteed zombie task reclamation with dual-process contention safety and monotonic generation increments.
14. **`dev_tasks_export_handoff_card`**: Generates a standard markdown Reviewer handoff card for a task.
15. **`dev_reviewer_submit`**: Submits an asynchronous long-running Reviewer consultation job with detached background worker execution and persistent `JobRecord`.
16. **`dev_reviewer_poll`**: Polls asynchronous Reviewer job status and retrieves results. Supports `raw_text=True` returning a single-line canonical string (`[Reviewer thinking: ... tokens | ...s]`) in non-terminal states, `wait_max_s` long polling, 1KB non-terminal snapshot contract, and terminal projection with 40,000-character findings budget.
17. **`dev_reviewer_cancel`**: Deterministically cancels an in-flight async Reviewer job, aborting network transfer and retaining token accounting.

---

## 5. Implementation Pointers & Verification Matrix

> 📖 **Full Module Architecture & Topology**: For the complete 4-tier module mapping, call constraint hierarchy, and physical isolation layers, see [docs/architecture/README.md §5](docs/architecture/README.md#5-source-code-mapping-module-topology).

All 17 FastMCP tools and 9 core invariants are verified across the codebase by the automated test suite (572+ tests):

| Verification Category | Primary Test Suites | Enforced Invariants & Key Mechanisms |
| :--- | :--- | :--- |
| **Core State Machine & CAS** | `server/tests/test_state_machine.py`<br>`server/tests/test_reclaim_cas.py` | **INV-1** (Single-core serial execution), **INV-2** (MCP-only state transitions) |
| **Anti-Roleplaying & Stdio Purity** | `server/tests/test_anti_roleplay_discipline_contract.py` | **INV-3** (Degraded `findings == ""`), **INV-4** (Stdio protocol purity) |
| **Vendor Neutrality & AST Egress** | `server/tests/test_reviewer_factory_neutrality.py`<br>`server/tests/test_no_vendor_literals_in_core.py`<br>`server/tests/test_no_api_bypass.py` | **INV-5** (Vendor neutrality), **INV-9** (Single provider egress through `ReviewerClient`) |
| **Physical Feasibility & Scope** | `server/tests/test_draft_lint.py`<br>`server/tests/test_path_guard.py`<br>`server/tests/test_server_tools.py` | **INV-6** (Review read-only), **INV-7** (Physical feasibility path & pytest dry-run) |
| **Context Injection Budget** | `server/tests/test_consultation_context_guard.py` | **INV-8** (Declarative context budget ceiling enforcement) |
| **Async Jobs, Heartbeat & Polling**| `server/tests/test_reviewer_jobs.py`<br>`server/tests/test_reviewer_consult.py` | Pull-model heartbeat SSOT (`format_heartbeat_line`), 1KB non-terminal snapshot whitelist |
| **IDE Entry Card Synchronization** | `server/tests/test_agents_md_sync.py` | Parity between workspace `AGENTS.md` and template `templates/AGENTS.md` (INV-1 to INV-9) |


