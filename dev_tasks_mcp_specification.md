# Quench-DevTasks MCP Service Architecture & Specification (DevTasks Orchestrator Spec)

> **Version**: v1.6.0 (Implemented & Verified)  
> **Implementation Status**: ✔️ Fully implemented and verified with 308+ automated unit tests (covering Google Antigravity, Cursor cross-tool adapters, vendor-neutral ReviewerClient engine & `PROVIDER_PRESETS` registry, source-level neutrality scan gate, ad-hoc architectural consultation `dev_reviewer_consult`, anti-roleplaying governance, RotatingFileSink observability, Draft task state & physical feasibility lint gate, and unified CLI)  
> **Source Specification**: `dev_tasks_mcp_specification.md`  
> **Workflow Reference**: [DevTasks Workflow Specification](plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md)  
> **Role & Purpose**: General-purpose development task governance and dual-model orchestration MCP server for engineering repositories.

---

## 1. Provenance & Core Architectural Philosophy

### 1.1 Provenance from Manual Protocols
This MCP service mechanizes and enforces the **"Dual-Model Task Governance Workflow"** established in the [DevTasks Workflow Specification](plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md). It transforms conversational, document-level soft conventions into an **external code-level supervisory daemon (MCP Server)** featuring strict lifecycle state machines, physical scope guards, and graded quality auditing.

### 1.2 Dual-Model Division of Labor: Strategic Reviewer + Everyday Runner
- **Agile Runner / Everyday Executor (Everyday Co-pilot)**:
  - Characterized by high token allowances and low-latency responses, resident in the primary development session.
  - Handles 80%+ of daily interactions, inspecting status, running terminal commands, executing focused file modifications, and running regression test suites.
  - **Avoids wasting scarce flagship reasoning budgets on routine implementation tasks**.
- **Strategic Reviewer (On-Demand Strategic Architect)**:
  - Frugally expends flagship reasoning budget, **awakened only under two conditions**:
    1. **Explicit Developer Instruction**: e.g., user requests: "Have the Reviewer inspect the current module and draft a comprehensive DevTask" or calls `dev_reviewer_consult`;
    2. **Self-Escalation**: Triggered when tackling multi-module refactoring, resolving architectural impasses, or encountering repeated test failures.
  - Upon completing task decomposition or architecture review, the Reviewer **immediately sleeps**, handing back execution to the runner model.

### 1.3 Model Decoupling & Pluggable ReviewerClient Architecture
The MCP server operates as an independent Python process (FastMCP over stdio JSON-RPC) and **never hardcodes specific model version strings or proprietary vendor literals**. Logical roles and external model dispatch are decoupled via workspace configuration (`.agents/quench_stack.yaml::reviewer_engine`) and governed by an automated static neutrality scan gate (`test_no_vendor_literals_in_core.py`):

```yaml
# Workspace .agents/quench_stack.yaml configuration
schema_version: "1.0"
project_name: "MyProject"

reviewer_engine:
  mode: "auto"                    # "auto" | "subagent" | "engine" | "manual"
  strategy_order:                 # Fallback strategy chain
    - "subagent"                  # 1. Native IDE subagent (Antigravity/Cursor)
    - "engine"                    # 2. Direct upstream API engine
    - "manual"                    # 3. Interactive manual review fallback
  provider: "none"                # "none" | "openai" | "deepseek" | "ollama" | "vllm" | "generic-openai" | "custom"
  model: "default"                # Model identifier or preset default
  api_key_env: null               # Secure env var (e.g. OPENAI_API_KEY)
  base_url: "https://api.openai.com/v1"
  thinking: true                  # Stream reasoning CoT via reasoning_content
  reasoning_effort: "high"        # High-depth reasoning budget
  timeout_seconds: 60
  max_retries: 2
  max_tool_hops: 3
  max_total_injection_chars: 40000 # Declarative context budget ceiling [512, 200000]
  default_window_lines: 200       # Default lines when no line range is given
  max_lines_per_slice: 600        # Maximum lines allowed per explicit slice
```

Upstream providers are instantiated via the declarative `PROVIDER_PRESETS` registry (`create_reviewer_client`):
- **`ReviewerClient`**: Unified, vendor-neutral abstract client supporting generic OpenAI-compatible `/chat/completions` streaming.
- **Generic CoT Protocol Probe**: Extracts reasoning thoughts from `delta.reasoning_content`, `message.reasoning_content`, or `delta.thought` without proprietary branching.
- **Offline Local Inference**: Full support for `ollama` and `vllm` endpoints without requiring cloud API keys.
- **Subagent Delegation**: Dispatches tasks to IDE-native subagents (e.g. Antigravity Reviewer).
- **Graceful Degraded Fallback**: Emits structured degraded cards with `findings == ""` if engine is unconfigured or unavailable, preventing in-context impersonation.

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

Every DevTask must adhere to the structured six core fields. The schema validator natively validates canonical English headers (while retaining backwards compatibility for localized aliases):

#### 1. `[Affected Files]` (`#### [Affected Files]`)
- **Format**: File paths prefixed with operation tags: `[MODIFY]`, `[NEW]`, `[DELETE]`, `[RENAME]`.
- **Granularity Guard**: If a single task touches more than 3 core files, a `TaskGranularityWarning` is issued suggesting decomposition.

#### 2. `[Root Cause & Target]` (`#### [Root Cause & Target]`)
- **Format**: 1–2 concise sentences stating the underlying root cause and the expected engineering outcome.

#### 3. `[Type Contracts]` (`#### [Type Contracts]`)
- **Principle**: Include only changed or introduced signatures; avoid duplicating entire classes.
- **Strict Typing**: Explicit interfaces, Pydantic schemas, or function signatures to eliminate implicit typing ambiguity.

#### 4. `[Step-by-Step Instructions]` (`#### [Step-by-Step Instructions]`)
- **Principle**: 3–5 numbered steps with sequential instructions.
- **Skeleton vs. Implementation**: Steps provide action verbs with key pseudo-code/skeletons, preventing over-specification.

#### 5. `[Defensive & Edge Checks]` (`#### [Defensive & Edge Checks]`)
- **Format**: Bulleted list detailing null checks, boundary overflows, concurrency locks, and fallback handling.

#### 6. `[DoD Verification Commands]` (`#### [DoD Verification Commands]`)
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

## 3. Task Lifecycle & Physical State Machine

```mermaid
stateDiagram-v2
    [*] --> Draft: Reviewer spec drafting / physical issues (dev_tasks_refine_spec)
    Draft --> Pending: Physical lint passes (dev_tasks_promote_draft)
    [*] --> Pending: Propose task (dev_tasks_propose)
    Pending --> Confirmed: Developer approval (dev_tasks_confirm action=confirm)
    Pending --> Skipped: Developer rejects item (dev_tasks_confirm action=skip)
    
    state "Physical Security Gate" as Gate {
        note right of Gate: Runner cannot obtain execution lock without Confirmed status
        Confirmed --> In_Progress: Checkout task (dev_tasks_checkout)
    }

    In_Progress --> Completed: Verification passed (dev_tasks_complete)
    In_Progress --> Rework: Verification failure (dev_tasks_confirm action=rework)
    Rework --> In_Progress: Re-checkout and correct
    
    Completed --> Archived: All items closed (dev_tasks_archive)
    Skipped --> Archived: Closed without action
```

---

## 4. MCP Tools Specification

The server exposes 11 atomic FastMCP tools:

1. **`dev_tasks_status`**: Scans the workspace task directory, returning structured queue metrics (active, confirmed, rework, pending, draft) with optional draft segregation.
2. **`dev_tasks_propose`**: Validates the six core fields and proposes a new task in formal `[Pending]` status.
3. **`dev_tasks_confirm`**: Advances tasks to `[Confirmed]`, `[Skipped]`, or transitions them to `[Rework]`.
4. **`dev_tasks_checkout`**: Checks out the next confirmed task, sets its state to `[In Progress]`, and provides step-by-step guidance.
5. **`dev_tasks_complete`**: Submits a completed task, requiring DoD test command output and physical test assertion auditing.
6. **`dev_tasks_escalate`**: Awakens the Reviewer role with focused contextual snippets when encountering roadblocks.
7. **`dev_tasks_refine_spec`**: Runs multi-turn architectural reasoning via `ReviewerClient`, streaming reasoning logs and enforcing the physical lint gate.
8. **`dev_tasks_promote_draft`**: Validates physical feasibility of a draft task and promotes it to formal `[Pending]` state.
9. **`dev_tasks_archive`**: Retires closed tasks to `archive/` and increments the changelog.
10. **`dev_tasks_set_bypass`**: Manages temporary time-bound bypass tokens with strict audit logging.
11. **`dev_reviewer_consult`**: Direct ad-hoc architecture consultation tool with read-only sandbox guards, 4 modes, and real-time streaming thinking logs.

---

## 5. Implementation Registry

All specifications are verified across the codebase:

| Spec Section | Implementation Files | Key Mechanism |
| :--- | :--- | :--- |
| **Review Protocols & Anti-Roleplay** | `rules/dev-tasks-discipline.md`<br>`skills/dev-tasks-review/` | Read-only planning constraints, anti-roleplay invariant (`findings == ""`), and triage decision tree |
| **State Machine** | `server/state_machine.py` | Strict enum transitions, cross-process `FileLock`, Unicode emoji regex normalization |
| **Six Core Fields** | `server/schema_validator.py` | Bilingual field aliases, markdown block parsing, granularity warnings |
| **Draft & Feasibility Gate** | `server/schema_validator.py`<br>`server/server.py` | Physical existence checks, dry-run `--collect-only`, atomic `dev_tasks_promote_draft` |
| **Reviewer Engine & Presets** | `server/reviewer_engine.py` | Pluggable vendor-neutral `ReviewerClient`, declarative `PROVIDER_PRESETS`, generic CoT probe |
| **Neutrality Gate** | `server/tests/test_no_vendor_literals_in_core.py` | Automated static source scan gate ensuring zero vendor literals in core modules |
| **Ad-Hoc Consultation** | `server/consultation.py`<br>`server/server.py` | `dev_reviewer_consult`, read-only path sandbox, default 40,000-char budget (declarative), stable prefix cache |
| **Observability Sinks** | `server/reviewer_engine.py`<br>`server/observability.py` | `RotatingFileSink`, bounded disk writes, 1.0s low-frequency MCP heartbeats, zero stdout pollution |
| **Physical Guards** | `server/hooks/file_scope_guard.py`<br>`server/hooks/context_injector.py`<br>`scripts/git_pre_commit_guard.py` | `PreToolUse` physical interception (`force_ask`), `PreInvocation` reminder injection, Git pre-commit barrier |
| **Decoupled Config** | `server/project_config.py`<br>`templates/quench_stack.yaml` | Workspace `.agents/quench_stack.yaml` integration with migration engine |
| **11 MCP Tools** | `server/server.py` | FastMCP tool registration with bilingual docstrings and argument descriptions |
| **Cross-Tool Adapters** | `server/adapters/` | Multi-host adapter layer supporting Antigravity, Cursor, and generic CLI |
| **Rules Exporter** | `scripts/rules_exporter.py` | Exports `.cursorrules` and modern `.cursor/rules/quench-dev-tasks.mdc` |
| **Unified CLI** | `server/cli.py` | Standalone `quorch status/check/init/archive` terminal command suite |
| **Installer** | `scripts/install.py`<br>`scripts/init_project.py` | Pre-flight health checks, snapshot backup/rollback, automated IDE configuration |
| **Test Matrix** | `server/tests/` (308+ tests) | 100% passing test coverage across Windows and Ubuntu environments |

