# Quench Dev-Orchestrator — System Architecture

> **Document Type**: Architecture SSOT (High-Level System Design)  
> **Scope**: Answers *Why* (design philosophy) and *Topology* (components, lifecycles, invariants).  
> **Not covered here**: Individual tool parameters, field regex syntax, return-value types → see [`dev_tasks_mcp_specification.md`](../../dev_tasks_mcp_specification.md) (FastMCP Tool & Protocol Specification SSOT).

---

## 0. Trust Model & Scope Declarations

### 0.1 Trust Model & Non-Security Boundary Declaration

Quench governance enforces **operational hygiene, collaborative consensus, and workflow reliability**, rather than cryptographic or hostile-process isolation:
- **Collaborative Hygiene**: Role declarations, verdict audit logs, and whitelist guards are mechanisms to prevent accidental developer errors, state drift, and AI hallucination loops.
- **Process Boundaries**: Quench does NOT sandbox unconfined hostile operating system subprocesses. Security must be established via host operating system controls, containerization, and repository permissions.
- **Audit Trails**: Verdict logs (`verdicts.jsonl`) provide structured replayability and accidental degradation detection rather than zero-trust cryptographic proofs.

---

## 1. System Vision & Core Problem

### 1.1 The Dual-Model Decoupling Philosophy

Modern AI-assisted development faces an irreconcilable tension: **frontier reasoning models** (capable of deep architectural analysis) are expensive; **agile runner models** (cheap, fast) lack the depth for complex contract design. Quench resolves this by enforcing an **explicit, tool-enforced role separation**:

| Role | Model Tier | Responsibility |
|------|-----------|----------------|
| **Strategic Reviewer** | Frontier reasoning (e.g., DeepSeek R2, o3) | Architecture analysis, root cause investigation, six-field task contract authoring, escalation arbitration |
| **Agile Runner** | Lightweight daily driver | Sequential step execution, physical file edits within whitelist, DoD test verification |

The Reviewer is never called for routine implementation. The Runner is never allowed to self-promote to Reviewer. These constraints are enforced both by discipline rules and by physical server-side guards.

### 1.2 Soft Constraints → Physical Hard Gateways

A core design axiom: **verbal promises are not guarantees**. Every critical invariant in Quench is backed by a physical enforcement mechanism:

- "Don't touch out-of-scope files" → `PreToolUse` hook intercepts at the OS level  
- "Only one task at a time" → cross-process `filelock` on the manifest  
- "State changes only via MCP" → server validates every transition; Markdown is write-only output  
- "Vendor neutrality" → static AST scan gate runs in CI  

### 1.3 Dual-Mode Orchestration & Autopilot Harness (双模编排与 Autopilot 接力棒)

To adapt to both single-model agile development and multi-agent team workflows, Quench v1.25+ establishes a dual-mode orchestration topology:

1. **Standard Mode (`standard`)**:
   - Primary IDE session acts as the agile **Runner**, executing sequential task implementations.
   - Architectural review is delegated on demand to an external model endpoint (`direct_api`) or an isolated subagent (`subagent_delegate`).

2. **Inverted Mode (`inverted`)**:
   - Primary IDE session acts as the strategic **Reviewer / Orchestrator**, coordinating tasks, assessing risks, and planning evolution.
   - Code reading, AST exploration, and implementation are delegated to specialized subagents via `[QUENCH-DISPATCH: ...]` envelopes.

3. **Dynamic Mode Switching (`runtime_mode.py`)**:
   - Orchestration mode and reviewer channel are switched dynamically without server restarts via `.quench_runtime_mode.json`.
   - Controlled via `dev_tasks_status(switch_mode="...", switch_reviewer_channel="...")`.

4. **Autopilot Continuous Relay (`autopilot_harness.py`)**:
   - Driven by the `harness_next_action` baton returned by operational MCP tools (`dev_tasks_status`, `dev_tasks_propose`, `dev_tasks_confirm`, `dev_tasks_checkout`, `dev_tasks_complete`, `dev_tasks_archive`, `dev_reviewer_poll`, `dev_tasks_refine_spec`).
   - States: `PROPOSE` -> `REVIEW` -> `CONFIRM` -> `CHECKOUT` -> `DISPATCH_RUNNER` -> `SYNC_DOCS` -> `ARCHIVE` -> `NEXT_BATCH_PROPOSE` -> `PAUSE_FOR_ACCEPTANCE` / `BLOCKED` / `ROADMAP_DONE`.
   - Continuous non-stop relay: The agent executes sequential phases without stopping across tasks and batches (`NEXT_BATCH_PROPOSE`).
   - Stopping points: Execution pauses and presents a concise C3 delivery card or status report only at `PAUSE_FOR_ACCEPTANCE`, `BLOCKED`, or `ROADMAP_DONE`.

---

## 2. Four-Tier Layered Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Tier 1: Client Awareness & Interception Layer                   │
│  (IDE Adapters & Hooks)                                          │
│  • Antigravity PreToolUse / PostToolUse hooks                    │
│  • Cursor MCP Rules injection (rules_exporter.py)                │
│  • Git Pre-Commit Guard (git_pre_commit_guard.py)                │
│  • Cross-IDE AGENTS.md router card                               │
└─────────────────────────┬────────────────────────────────────────┘
                          │ stdio JSON-RPC (MCP protocol)
┌─────────────────────────▼────────────────────────────────────────┐
│  Tier 2: Protocol Communication Gateway                          │
│  (FastMCP stdio JSON-RPC Daemon)                                 │
│  • Independent daemon process (server.py)                        │
│  • Cross-platform path safety (path_guard.py)                    │
│  • Handle isolation & stdout purity contract                     │
│  • 16 registered MCP tool endpoints (tool_surface_constants)     │
└─────────────────────────┬────────────────────────────────────────┘
                          │ in-process calls
┌─────────────────────────▼────────────────────────────────────────┐
│  Tier 3: Core Domain Governance Engine                           │
│  (State Machine & Validators)                                    │
│  • filelock-backed CAS atomic state transitions (state_machine)  │
│  • Task status SSOT & fence-aware scanner (task_status.py)       │
│  • Six-field schema validator (schema_validator.py)              │
│  • Guarded atomic task revision & partition identity (task_writer)│
│  • Physical feasibility lint gate (draft_lint)                   │
│  • DoD output auditor (dod_guard)                                │
│  • Manifest bounds & compaction (manifest.py)                    │
└─────────────────────────┬────────────────────────────────────────┘
                          │ async / subprocess
┌─────────────────────────▼────────────────────────────────────────┐
│  Tier 4: Model Abstraction & Thinking-Stream Engine              │
│  (ReviewerClient & Observability)                                │
│  • Vendor-neutral adapter (reviewer_engine.py, adapters/)        │
│  • Provider presets: DeepSeek, OpenAI, Ollama, vLLM, Subagent   │
│  • 1024KB safe-rotation log stream (log_naming.py)               │
│  • Adaptive heartbeat liveness guard                             │
│  • Observability policy & verdict sink (observability_policy.py) │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Lifecycles & Data Flow

### 3.1 Task State Machine

```
                     ┌─────────────────┐
                     │   User Intent   │
                     └────────┬────────┘
                              │ dev_tasks_propose
                              ▼
                    ┌──────────────────┐
                    │  📝 Draft        │  ← Feasibility not yet verified;
                    │  (unverified)    │    safe staging area for ideas
                    └────────┬─────────┘
                             │ dev_tasks_promote_draft
                             │ (path check + pytest dry-run)
                             ▼
                    ┌──────────────────┐
                    │  ⬜ Pending       │  ← In review queue; awaiting
                    │  (awaiting conf) │    human or Reviewer sign-off
                    └────────┬─────────┘
                             │ dev_tasks_confirm(action="confirm")
                             ▼
                    ┌──────────────────┐
                    │  ✅ Confirmed    │  ← Approved for execution;
                    │                  │    physically feasible contract
                    └────────┬─────────┘
                             │ dev_tasks_checkout
                             ▼
                    ┌──────────────────┐
                    │  🔨 In Progress  │  ← Single active slot (filelock)
                    │                  │    Runner executes step-by-step
                    └────┬────────┬────┘
               DoD pass  │        │  Major conflict / regression
                         ▼        ▼
              ┌──────────────┐  ┌──────────────────┐
              │  ✔️ Completed │  │  🚨 Escalated    │
              │              │  │  (Reviewer Card) │
              └──────────────┘  └──────────────────┘
```

**Additional terminal states**: `⏭️ Skipped` (via `confirm action=skip`), `🔄 Rework` (via `confirm action=rework`), `🚫 Revoked` (via `confirm action=revoke`).

### 3.2 Physical Interception & Workspace Scope Reconciliation

Quench provides defense-in-depth against unauthorized source code modifications across both native IDE hosts and headless/external runners (Codex CLI, Claude Code):

1. **PreToolUse Hook Interception (IDE Host)**:

```
IDE tool call (file write / shell exec)
        │
        ▼ PreToolUse hook (file_scope_guard.py)
  ┌──────────────────────────────────────────┐
  │ Is path in active task whitelist?        │
  │ ([Affected Files] list + unmanaged)      │
  └──────────┬───────────────────────────────┘
      YES    │    NO
      │      │──→ Interactive confirmation dialog → user decides
      ▼
  Tool executes normally
```

Latency target: **< 50ms** per hook invocation.

2. **Workspace Baseline Snapshot & Scope Reconciliation (Server-Side Gate)**:
- At `dev_tasks_checkout`, the server captures a physical snapshot (`BaselineSnapshot`) with file fingerprints (`size`, `mtime_ns`, `inode`, `sha256`);
- At `dev_tasks_complete` / `dev_tasks_escalate`, the state machine runs `reconcile_workspace_against_whitelist` (pure function with dual fast-path / slow-path comparison and deterministic slow-path hash quota);
- Any modified or created files outside the declared `【涉及文件】` whitelist are rejected with `ScopeViolationError`, preventing external runners from bypassing file boundaries.

3. **Pre-Confirm Audit Gate (Server-Side Discipline Function)**:
- At `dev_tasks_confirm`, when transitioning tasks from `⬜ 待确认` to `✅ 已确认` for Tier-1 managed files, the server validates against the audit ledger (`verdicts.jsonl`) that a genuine, fresh, undegraded review record exists for the task (`canonical_artifact_ref`);
- Evaluated strictly outside the manifest lock; re-validated under lock with `precondition_changed` fail-closed protection;
- Controlled by converged `AuditGatePolicy`: degraded reading family (`log_missing`, `log_unparsable`, `record_timestamp_invalid`, `record_degraded`, `tail_window_exhausted`) unified under single-point `effective_on_degraded` with `most_restrictive_policy` (block > warn > allow); missing/stale records strictly guarded by `on_missing_record: block`.

### 3.3 Unified Asynchronous Reviewer Job Pipeline

Quench establishes a unified asynchronous Reviewer execution path, converging all heavy reasoning onto a background worker daemon:

1. **Unified Asynchronous Long-Running Jobs (`dev_reviewer_submit`, `dev_reviewer_poll`, `dev_reviewer_cancel`)**:
   Decouples architectural reasoning into detached background worker jobs with pre-flight fail-closed sandbox checks, context budget caps, durable `JobRecord` tracking, and strict tri-state discriminated union return contracts (prompt shim retired in v1.23, converging FastMCP surface to 16 tools):

```
[Runner / Caller]
       │ dev_reviewer_submit
       ▼
 ┌────────────────────────────────────────────────────────┐
 │ ReviewerJobSupervisor                                  │
 │ • CapacityLimiter admission check                      │
 │ • Background worker coroutine spawned                  │
 │ • Durable JobRecord written to disk                    │
 └─────────────────────────┬──────────────────────────────┘
                           │
                           ▼ ReviewerClient.run_async()
 ┌────────────────────────────────────────────────────────┐
 │ Execution & Observability                              │
 │ • Streaming chunks → latest-<session_id>.log           │
 │ • 1024KB hard-cap rotation (log_naming)                │
 │ • File-based heartbeat logging (Pull Model)            │
 └─────────────────────────┬──────────────────────────────┘
                           │
       ┌───────────────────┴───────────────────┐
       ▼ (in-flight)                           ▼ (terminal)
dev_reviewer_poll()                     dev_reviewer_poll()
V2 6-field non-terminal snapshot        Full structured verdict
(job_id, session_id, state,             (40k char budget cap dict)
 retry_after_seconds, log_ref,
 elapsed_s) + notifications/progress
```

- **Structured-Only Return Contract (V2 Non-Terminal 6 Fields)**: `dev_reviewer_poll` returns a structured contract dictionary in all states. In-flight states return a V2 6-field non-terminal snapshot (`{job_id, session_id, state, retry_after_seconds, log_ref, elapsed_s}` strictly bounded under 1024 bytes via `POLL_NONTERMINAL_FIELDS`, removing nested progress objects); terminal states return the complete structured dictionary capped by 40k char findings budget; code is authoritative, JSON snapshot is derived mirror evidence; see [`dev_tasks_mcp_specification.md`](../../dev_tasks_mcp_specification.md). Elapsed time is generated via monotonic clock (`time.monotonic`).
- **Native MCP Progress Channel (`notifications/progress`)**: Active reasoning progress is streamed out-of-band via FastMCP native `ProgressBridge`, delivering formatted, single-line (≤ 120 bytes) progress notifications directly to the IDE progress channel with monotonic counter and 1.0s coalescing (with force penetration on state/phase delta). Progress notifications fail-open and never block or fail the polling loop.
- **Deterministic Cancellation**: `dev_reviewer_cancel` aborts active HTTP transports immediately, records final billed tokens, and marks state as `CANCELLED`.
- **Zero-Poll Long Polling (`wait_max_s`)**: `dev_reviewer_poll` supports server-side long polling via `ReviewerJobSupervisor.watch()` with `wait_max_s` (recommended default 20s, clamped to [0.0, 25.0s]), consuming zero Reviewer capacity tokens (`_REVIEWER_LIMITER`) and zero disk writes (W10). Fast-path short-circuits in < 250ms for terminal tasks or `wait_max_s <= 0`. Terminal tasks return directly to the caller without emitting progress notifications, preventing client UI flicker.
- **Snapshot Drift Gate Policy**: CI strictly executes `python scripts/export_ide_schemas.py --check` (read-only verification); `--write` is strictly reserved for local developer execution upon intentional changes, and any snapshot diff requires Reviewer approval. Pre-commit guard monitors `SCHEMA_TRIGGER_PATHS` (`plugins/quench-dev-tasks/server/server.py`, `plugins/quench-dev-tasks/server/tool_surface_constants.py`, `scripts/export_ide_schemas.py`, `docs/architecture/ide_tool_schemas.json`) and blocks drift fail-closed.

### 3.3.1 W10 Exclusion Domain (锁原语豁免域)

为了确保跨平台 CI 矩阵与高并发环境下的确定性运行，Quench 对 **W10 (零磁盘写入/Zero Disk Write)** 契约实施精确的作用域隔离：
- **业务状态域 (Business State Domain)**: 轮询、监控或只读推演调用期间，绝对禁止向磁盘刷入任何业务推演日志、审计条目或持久化任务快照；
- **锁原语豁免域 (W10 Exclusion Domain)**: 进程间跨进程同步原语（如 Unix 环境下 `filelock` 创建的 `*.lock` 锁文件及已登记的无写漂移 inode 描述符）属于系统底层并发安全屏障，显式排除在业务写入审计之外，杜绝假红阻断。
- **单次轮询作用域约束**: `_ExemptInodeTracker` 追踪器严格绑定单次 `dev_reviewer_poll` / `watch` 调用生命周期，严禁将其提升为全局或常驻单例，彻底杜绝内存与句柄泄漏。

### 3.4 Task Contract & Bilingual Headings SSOT

DevTask specifications are strictly validated against the Six-Core-Field structured contract. Both English (`#### [Affected Files]`, etc.) and Chinese (`#### 【涉及文件】`, etc.) heading aliases are natively accepted and physically enforced by `schema_validator.py`.

> For the authoritative canonical bilingual field mapping table, regex definitions, and authoring rules, see [`dev_tasks_mcp_specification.md` §2.2](../../dev_tasks_mcp_specification.md#22-the-six-core-field-structured-contract) and [`dev-tasks-workflow/SKILL.md` §2](../../plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md#2-the-six-core-fields-standard-任务六大字段编写规范).

### 3.5 Test Tiering Gate Contract (`tier1_fast` vs Full Regression)

Quench enforces a bifurcated test execution contract designed for fast developer feedback loops while preserving full regression safety:

1. **Tier-1 Fast Gate (`pytest -m tier1_fast`)**:
   - Executes the core fast regression suite within **≤ 5s** budget across Tier-1/Tier-2/Tier-3 foundation units (pure contracts, schema validators, path guards, fast CLI checks, formatters).
   - Marker injection is strictly decoupled from individual test files via centralized `conftest.py` hook (`pytest_collection_modifyitems`).
   - Root `pyproject.toml` configures `pythonpath = ["plugins/quench-dev-tasks/server"]` and registers `tier1_fast` without overriding default `testpaths`.

2. **Heavy Concurrency Moat Isolation ($H \cap \text{Tier-1} = \emptyset$)**:
   - Heavy state-machine concurrency tests, multi-threaded CAS lease races (`reclaim_cas`), and inter-process workspace lock races (`workspace_lease`) remain strictly isolated from Tier-1 fast gate.
   - Preserves 100% of concurrency test assertions without dilution or pruning.

3. **Physical Verification Gate (`scripts/check_test_tiering_invariants.py`)**:
   - Automated physical gate validating three core invariants:
     - Disjointness: $H \cap \text{Tier-1} = \emptyset$
     - Superset coverage: $\text{Full} \supseteq \text{Tier-1} \cup H$
     - Execution budget: Tier-1 suite completes well within ≤ 5.0s target with non-empty item count.

4. **Duration Baseline Freeze & Variance Gate (`scripts/check_test_duration_baselines.py`)**:
   - Enforces timing budgets, variance stability, and regression envelopes (TR-3 / TR-4):
     - **Tier-1 Baseline**: 1 warmup + 3 measured iterations; hard-fail threshold **≤ 8.0s**, target warning threshold **≤ 5.0s**, ultra-fast aspirational goal **≤ 3.0s**.
     - **Tier-2 Dynamic Budget Envelope & Panic Line (单向下移 + 双向假红防护)**: Dynamic convergence envelope with single-directional ratcheting: $\text{Baseline}_{\text{next}} = \max(\text{TIER2\_ABSOLUTE\_FLOOR\_S}, \min(\text{Baseline}_{\text{prev}}, \text{robust\_estimate}))$, $\text{TIER2\_WARN\_S} = \text{Baseline}_{\text{next}} \times 1.15$, $\text{TIER2\_PANIC\_S} = \text{Baseline}_{\text{next}} \times 1.30$. Enforces 30s safety floor (`TIER2_ABSOLUTE_FLOOR_S = 30.0`), in-run 3-sample confirmation (`RATCHET_CONFIRM_ROUNDS = 3`), bidirectional false-red guard (`PANIC_DOWNGRADE_STREAK = 2`), and optional fail-safe sidecar (`.agents/bench/tier2_baseline.json`).
     - **Sample Variance Guard**: Sample Coefficient of Variation ($CV = \sigma / \mu \le 15\%$ with $ddof=1$ sample Bessel correction) with bounded 1-round retry (`MAX_CV_RETRY_ROUNDS = 1`).
     - **Dual-Layer Anti-Reentrancy Protection**: Subprocess isolation with `QUENCH_TEST_DURATION_BENCH_ACTIVE=quench-bench-v1` magic-value environment guard plus `--tier2` runner `--deselect` on contract test harness, preventing recursive test invocation or timing self-pollution.
     - **Self-Repository Anchor**: Validates workspace root contains core Quench marker files (`docs/architecture/README.md` and `.agents/quench_stack.yaml`), failing closed in untrusted directories.

### 3.6 Prompt-Surface Contract Gate (P1~P5 AST Enforcement)

To permanently guard against model prompt surface drift, IDE schema divergence, and stale documentation call examples, Quench implements `scripts/check_prompt_surface.py`:
- **P1 (Docstring Completeness)**: AST verification guaranteeing all FastMCP tools have complete Google-style `Args:` sections.
- **P2 (Snapshot Freshness & Descriptions)**: Asserts envelope metadata freshness and enforces that every tool parameter in `docs/architecture/ide_tool_schemas.json` has an informative description (≥ 8 chars).
- **P3 (Live Documentation Hygiene)**: Rejects deprecated parameters in live documentation code blocks.
- **P4 (Workspace Example Call Legality)**: AST check ensuring all markdown Python code fences call MCP tools with valid keywords, protected by R2 anti-self-lock exclusions (`docs/dev_tasks/`, `docs/archive/`).
- **P5 (Historical Allowlist Exemption Discipline)**: Strictly enforces line-level exemption markers (`<!-- quench-prompt-surface:historical -->`) for audited historical references in `CHANGELOG.md` and compatibility guides.
- **Pre-commit Guard Integration**: Physical intercept in `git_pre_commit_guard.py` before any commit touches code or documentation.
- **Host Boundary**: This gate is active only in the Quench core repository; identified via strong anchor probes (`scripts/check_prompt_surface.py`, `scripts/check_test_tiering_invariants.py`, `scripts/check_test_duration_baselines.py`, `docs/architecture/ide_tool_schemas.json`). Downstream repositories that vendor the guard but lack strong anchors transparently `SKIP` with sub-millisecond overhead.

---

## 4. Architectural Invariants (9 Core — All Test-Anchored)

> These invariants are non-negotiable. Each has at least one automated test asserting its physical enforcement.

| ID | Name | Enforcement Mechanism | Test File |
|----|------|-----------------------|-----------|
| **INV-1** | Single-core serial execution | Cross-process `filelock` on manifest; second `checkout` rejected | `test_state_machine.py`, `test_reclaim_cas.py`, `test_architecture_hygiene.py` |
| **INV-2** | State machine is MCP-only | Server validates every transition; Markdown emoji never parsed as state source | `test_server_tools.py` |
| **INV-3** | Anti-roleplay (no in-context Reviewer impersonation) | `findings == ""` in degraded fallback card; schema enforced | `test_anti_roleplay_discipline_contract.py` |
| **INV-4** | Stdio channel purity (`stdout` = JSON-RPC only) | No `print()` in server modules; CI grep gate | `test_anti_roleplay_discipline_contract.py` |
| **INV-5** | Vendor neutrality | `PROVIDER_PRESETS` declarative registry; static AST neutrality scan | `test_reviewer_factory_neutrality.py`, `test_architecture_hygiene.py`, `test_no_vendor_literals_in_core.py` |
| **INV-6** | Review is read-only (no production file writes during review) | Consultation sandbox guard; read-only path assertions | `test_consultation_context_guard.py` |
| **INV-7** | Physical feasibility gate (path + pytest dry-run before promotion) | `dev_tasks_promote_draft` enforces checks; lint gate blocks invalid paths | `test_draft_lint.py` |
| **INV-8** | Context budget cap (`max_total_injection_chars`) | `project_config.py` enforces cap before injection; truncation tested | `test_consultation_context_guard.py` |
| **INV-9** | Single Provider Egress (no raw API bypass) | CI & test static AST scanner (`check_no_api_bypass.py`) asserts all Reviewer model calls transit through `ReviewerClient` | `test_architecture_hygiene.py`, `test_no_api_bypass.py` |

---

## 5. Source Code Mapping (Module Topology)

Production modules are organized under `plugins/quench-dev-tasks/` across `server/` (MCP daemon, domain governance engine, reviewer engine), `server/hooks/` (IDE hooks), `server/adapters/` (vendor adapters), and `scripts/` (client-side export and pre-commit guards).

| Module | Tier | Responsibility | Key Constraints |
|--------|------|----------------|-----------------|
| `server.py` | T2 | FastMCP tool endpoint definitions; request routing; DoD output auditor (`dod_guard`) | Must not import vendor SDK directly; delegates to Tier 3/4 |
| `state_machine.py` | T3 | CAS atomic state transitions backed by `filelock` | Single writer at a time; idempotent on repeated calls |
| `task_status.py` | T3 | SSOT for 6 canonical statuses, pure ASCII sentinel `"?? UNKNOWN"`, fence-aware status extraction, and `is_task_file` predicate | Zero regex duplication; zero emoji hardcoding in guards |
| `task_writer.py` | T3 | Lossless partition roundtrip, guarded task file writes (`write_task_file_guarded`) with directory confinement, pre-lock manifest check & atomic fsync | Single writer via FileLock; preserves BOM & CRLF; blocks status smuggling |
| `schema_validator.py` | T3 | Six-field contract validation; physical feasibility lint gate (`draft_lint`) | No file writes; pure validation |
| `manifest.py` | T3 | Manifest read/write/compaction; bounds enforcement; CAS TTL lease management (`manifest_lease`) | Single lock holder per task; lease expiration safety |
| `reviewer_jobs.py` | T4 | `ReviewerJobSupervisor`, unified async job state machine, tri-state union contract, `PollSnapshot` freeze contract, 1KB non-terminal snapshot V2, cancellation, log pin & retention quota | Durable atomic writes; memory-leak-free |
| `progress_bridge.py` | T4 | FastMCP `notifications/progress` bridge (`ProgressBridge`), coalescing, token detection, message formatting | Read-only consumer of `PollSnapshot`; zero job scheduling authority |
| `workspace_lease.py` | T3/T4 | Reviewer workspace mutex lease guard, TTL + generation CAS takeover, touch checkpoint contract | FileLock-backed; pure TTL timeout & generation CAS |
| `reviewer_engine.py` | T4 | `ReviewerClient`; streaming adapter dispatch; `format_heartbeat_line` SSOT | Vendor-neutral; sole authorized provider network egress |
| `consultation.py` | T4 | Reviewer sandbox guards (`assert_read_only_sandbox`) & context slice assembly (`assemble_reviewer_context`) | Read-only guard enforced before any context injection |
| `manifest_lease.py` | T3 | Lease management, liveness probing (`probe_lease_health`), and CAS stale task reclamation (`reclaim_stale_task`) | Strict lock ordering (Markdown -> Manifest); generation CAS |
| `log_naming.py` | T4 | Reviewer log naming, rotation, and zero-stat GC primitives (`gc_by_filename_order`, `enforce_unified_log_quota`) | Zero-stat contract; strict slug sanitization; deterministic quota |
| `runtime_mode.py` | T2/T3 | Dynamic runtime mode state management (`.quench_runtime_mode.json`), mode & reviewer channel switching | In-memory atomic cache; fallback-safe |
| `autopilot_harness.py` | T2/T3 | Autopilot baton transitions, `harness_next_action` evaluation, stopping states | Pure state machine; deterministic action resolution |
| `path_guard.py` | T2 | Cross-platform path safety; traversal defenses | Called on every tool invocation involving file paths |
| `project_config.py` | T2/T3 | `quench_stack.yaml` loading, validation, migration | Single parse per session; cached after first load |
| `observability_policy.py` | T4 | Verdict sink policy; log rotation policy | Append-only verdicts; policy-driven, not hard-coded |
| `reporting.py` | T2/T3 | Consolidated delivery artifacts and status reporting: pure handoff card rendering (T2) & atomic CHANGELOG append (T3) | Pure rendering for handoff card; non-destructive header-preserving updates for CHANGELOG |
| `cli.py` | T2 | Unified developer CLI entrypoint (`status`, `check`, `init`, `archive`, `reviewer debug`) | Interactive ANSI formatting; non-AI operator gateway |
| `hooks/file_scope_guard.py` | T1 | PreToolUse whitelist enforcement | Must respond in < 50ms; no network calls |
| `hooks/context_injector.py` | T1 | PostToolUse context enrichment | Read-only; non-blocking |
| `scripts/check_no_api_bypass.py` | T1 | Static AST scanner enforcing zero provider API bypasses (INV-9) | Zero third-party runtime dependencies |
| `scripts/check_test_tiering_invariants.py` | T1 | Physical test tiering gate invariant scanner asserting H ∩ Tier-1 = ∅ and collection integrity | Clean subprocess invocation with sanitized environment |
| `scripts/check_test_duration_baselines.py` | T1 | Test suite timing baseline & variance benchmark gate ($CV \le 15\%$, 8s hard fail / 5s warn, Tier-2 1.15x warn / 1.30x panic dynamic envelope with 30s floor) | 1 warmup + 3 measured iterations, ddof=1, reentrancy-safe subprocess runner |
| `scripts/rules_exporter.py` | T1 | Cursor MCP rules and IDE instruction exporter | Pure export; idempotent |
| `plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py` | T1 | Pre-commit hook enforcing Quench discipline & active task checks | Standalone script; zero external framework deps |
| `scripts/init_project.py` | T1 | Project onboarding, environment diagnostics & hook installer | Idempotent; supports `--ide` and `--install-git-hook` |
| `adapters/` | T4 | Per-vendor HTTP adapter implementations | Each adapter: stateless, vendor-isolated |
| `tool_surface_constants.py` | T2 | Single Source of Truth for tool names, counts, versions, and MISSING sentinel | Zero third-party dependencies; immutable frozensets |
| `ide_schema_export.py` | T2 | Pure functions for schema canonicalization, validation, envelope parsing & CLI | Zero dependencies on fastmcp/yaml/subprocess |
| `scripts/export_ide_schemas.py` | T1 | Thin CLI entrypoint spawning child process to introspect live schemas | Enforces byte-level determinism, PYTHONDONTWRITEBYTECODE=1 |
| `scripts/_introspect_schemas_child.py` | T1 | Sandboxed child probe redirecting stdout to private fd before server import | Prevents stdio channel pollution (INV-4) |

### Call Constraint Summary

```
server.py → state_machine.py   (read/write state)
server.py → schema_validator.py (validate before write)
server.py → task_writer.py     (guarded atomic propose/refine_spec persist)
server.py → task_status.py     (task status SSOT)
server.py → runtime_mode.py    (read/switch runtime mode and reviewer channel)
server.py → autopilot_harness.py (evaluate harness_next_action baton)
server.py → consultation.py    (Reviewer consult path)
server.py → reviewer_engine.py (ReviewerClient factory)
server.py → manifest.py        (task CRUD)
server.py → code_explorer.py   (AST slice for refine_spec)
server.py → reporting.py       (handoff card rendering & CHANGELOG append)
server.py → tool_surface_constants.py (SSOT tool constants)
server.py → progress_bridge.py (ProgressBridge.from_context & emit)

progress_bridge.py → reviewer_jobs.py (read PollSnapshot, SnapshotContractViolation)

task_writer.py → task_status.py (canonical statuses & extract_header_task_statuses)
task_writer.py → path_guard.py  (directory confinement)
task_writer.py → schema_validator.py (six-field format validation)

reviewer_engine.py → adapters/* (vendor-specific HTTP)
reviewer_engine.py → log_naming.py (session log paths)

hooks/* → path_guard.py  (path safety)
hooks/* → project_config.py (stack config read)

scripts/export_ide_schemas.py → scripts/_introspect_schemas_child.py (subprocess)
scripts/export_ide_schemas.py → ide_schema_export.py (run_cli)
scripts/_introspect_schemas_child.py → server.py (mcp.list_tools)
scripts/_introspect_schemas_child.py → tool_surface_constants.py
ide_schema_export.py → tool_surface_constants.py
ide_schema_export.py → path_guard.py (assert_dir_contained)
```

---

## 6. Cross-Reference & Architectural Sub-Contracts

- **Manifest Compaction & Generational Archiving Contract**: [`manifest_compaction_contract.md`](manifest_compaction_contract.md)  
- **FastMCP Tool & Protocol Specification** (tool parameters, field regex, return types): [`dev_tasks_mcp_specification.md`](../../dev_tasks_mcp_specification.md)  
- **Configuration Reference** (`quench_stack.yaml` fields): [`docs/configuration.md`](../configuration.md)  
- **CI Incident Tracker** (known compatibility cases, mitigation playbooks): [`docs/ci_incident_tracker_and_compatibility_guide.md`](../ci_incident_tracker_and_compatibility_guide.md)  
- **Execution Discipline Rules**: [`plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`](../../plugins/quench-dev-tasks/rules/dev-tasks-discipline.md)
