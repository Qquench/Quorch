# Quench Dev-Orchestrator — System Architecture

> **Document Type**: Architecture SSOT (High-Level System Design)  
> **Scope**: Answers *Why* (design philosophy) and *Topology* (components, lifecycles, invariants).  
> **Not covered here**: Individual tool parameters, field regex syntax, return-value types → see [`dev_tasks_mcp_specification.md`](../../dev_tasks_mcp_specification.md) (FastMCP Tool & Protocol Specification SSOT).

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
│  • 17 registered MCP tool endpoints                              │
└─────────────────────────┬────────────────────────────────────────┘
                          │ in-process calls
┌─────────────────────────▼────────────────────────────────────────┐
│  Tier 3: Core Domain Governance Engine                           │
│  (State Machine & Validators)                                    │
│  • filelock-backed CAS atomic state transitions (state_machine)  │
│  • Six-field schema validator (schema_validator.py)              │
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
- At `dev_tasks_complete` / `dev_tasks_escalate`, the state machine runs `reconcile_workspace_against_whitelist` (pure function with dual fast-path / slow-path comparison and 50ms timeout circuit breaker);
- Any modified or created files outside the declared `【涉及文件】` whitelist are rejected with `ScopeViolationError`, preventing external runners from bypassing file boundaries.

### 3.3 Synchronous Consultation & Asynchronous Reviewer Job Pipelines

Quench supports two complementary Reviewer execution paths:

1. **Synchronous Direct Consultation (`dev_reviewer_consult`)**:
   Thin-shell synchronous RPC wrapping quick architectural critiques, trade-off evaluations, or brainstorm sessions within active turns.

2. **Asynchronous Long-Running Jobs (`dev_reviewer_submit`, `dev_reviewer_poll`, `dev_reviewer_cancel`)**:
   Decouples deep architectural reasoning into background worker jobs:

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
dev_reviewer_poll(raw_text=True)        dev_reviewer_poll()
[Reviewer thinking: 1,234 tokens|12.3s]  Full structured verdict
(Zero JSON popup, 1KB bounded snapshot) (40k char budget cap)
```

- **Clean Raw-Text Projection**: Non-terminal poll calls with `raw_text=True` return a canonical single-line string (`[Reviewer thinking: ... tokens | ...s]`), eliminating JSON code-card clutter in IDE chat windows.
- **Deterministic Cancellation**: `dev_reviewer_cancel` aborts active HTTP transports immediately, records final billed tokens, and marks state as `CANCELLED`.
- **Zero-Poll Long Polling**: `dev_reviewer_poll` supports `wait_max_s` (0–25s) to suspend execution until state transition occurs, eliminating wasteful polling loops.

### 3.4 Task Contract & Bilingual Headings SSOT

DevTask specifications are strictly validated against the Six-Core-Field structured contract. Both English (`#### [Affected Files]`, etc.) and Chinese (`#### 【涉及文件】`, etc.) heading aliases are natively accepted and physically enforced by `schema_validator.py`.

> For the authoritative canonical bilingual field mapping table, regex definitions, and authoring rules, see [`dev_tasks_mcp_specification.md` §2.2](../../dev_tasks_mcp_specification.md#22-the-six-core-field-structured-contract) and [`dev-tasks-workflow/SKILL.md` §2](../../plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md#2-the-six-core-fields-standard-任务六大字段编写规范).

---

## 4. Architectural Invariants (9 Core — All Test-Anchored)

> These invariants are non-negotiable. Each has at least one automated test asserting its physical enforcement.

| ID | Name | Enforcement Mechanism | Test File |
|----|------|-----------------------|-----------|
| **INV-1** | Single-core serial execution | Cross-process `filelock` on manifest; second `checkout` rejected | `test_state_machine.py`, `test_reclaim_cas.py` |
| **INV-2** | State machine is MCP-only | Server validates every transition; Markdown emoji never parsed as state source | `test_server_tools.py` |
| **INV-3** | Anti-roleplay (no in-context Reviewer impersonation) | `findings == ""` in degraded fallback card; schema enforced | `test_anti_roleplay_discipline_contract.py` |
| **INV-4** | Stdio channel purity (`stdout` = JSON-RPC only) | No `print()` in server modules; CI grep gate | `test_anti_roleplay_discipline_contract.py` |
| **INV-5** | Vendor neutrality | `PROVIDER_PRESETS` declarative registry; static AST neutrality scan | `test_reviewer_factory_neutrality.py`, `test_no_vendor_literals_in_core.py` |
| **INV-6** | Review is read-only (no production file writes during review) | Consultation sandbox guard; read-only path assertions | `test_consultation_context_guard.py` |
| **INV-7** | Physical feasibility gate (path + pytest dry-run before promotion) | `dev_tasks_promote_draft` enforces checks; lint gate blocks invalid paths | `test_draft_lint.py` |
| **INV-8** | Context budget cap (`max_total_injection_chars`) | `project_config.py` enforces cap before injection; truncation tested | `test_consultation_context_guard.py` |
| **INV-9** | Single Provider Egress (no raw API bypass) | CI & test static AST scanner (`check_no_api_bypass.py`) asserts all Reviewer model calls transit through `ReviewerClient` | `test_no_api_bypass.py` |

---

## 5. Source Code Mapping (Module Topology)

Production modules are organized under `plugins/quench-dev-tasks/` across `server/` (MCP daemon, domain governance engine, reviewer engine), `server/hooks/` (IDE hooks), `server/adapters/` (vendor adapters), and `scripts/` (client-side export and pre-commit guards).

| Module | Tier | Responsibility | Key Constraints |
|--------|------|----------------|-----------------|
| `server.py` | T2 | FastMCP tool endpoint definitions; request routing; DoD output auditor (`dod_guard`) | Must not import vendor SDK directly; delegates to Tier 3/4 |
| `state_machine.py` | T3 | CAS atomic state transitions backed by `filelock` | Single writer at a time; idempotent on repeated calls |
| `schema_validator.py` | T3 | Six-field contract validation; physical feasibility lint gate (`draft_lint`) | No file writes; pure validation |
| `manifest.py` | T3 | Manifest read/write/compaction; bounds enforcement; CAS TTL lease management (`manifest_lease`) | Single lock holder per task; lease expiration safety |
| `reviewer_jobs.py` | T4 | `ReviewerJobSupervisor`, async job state machine, 1KB non-terminal snapshot, raw_text projection, cancellation | Durable atomic writes; memory-leak-free |
| `workspace_lease.py` | T3/T4 | Reviewer workspace mutex lease daemon, cross-process peer liveness detection (`probe_peer`) | FileLock-backed; POSIX & Windows liveness |
| `reviewer_engine.py` | T4 | `ReviewerClient`; streaming adapter dispatch; `format_heartbeat_line` SSOT | Vendor-neutral; sole authorized provider network egress |
| `consultation.py` | T4 | `dev_reviewer_consult` logic; context assembly; sandbox | Read-only guard enforced before any context injection |
| `reaper.py` | T4 | Session log GC (`gc_by_filename_order`) | **Zero-stat contract**: only `os.listdir` + `os.remove`; no `os.stat`/`os.path.exists` |
| `log_naming.py` | T4 | Log file naming, rotation, zero-stat GC primitives | `_guarded_stat` path-whitelist; see `ci_incident_tracker_and_compatibility_guide.md` Case 6 |
| `path_guard.py` | T2 | Cross-platform path safety; traversal defenses | Called on every tool invocation involving file paths |
| `project_config.py` | T2/T3 | `quench_stack.yaml` loading, validation, migration | Single parse per session; cached after first load |
| `observability_policy.py` | T4 | Verdict sink policy; log rotation policy | Append-only verdicts; policy-driven, not hard-coded |
| `code_explorer.py` | T3 | AST symbol extraction for `dev_tasks_refine_spec` | Read-only; no side effects |
| `handoff_card.py` | T2 | Single source of truth for handoff card rendering (GFM alerts, collapsible task context) | Pure function; zero side-effects; no network I/O |
| `cli.py` | T2 | Unified developer CLI entrypoint (`status`, `check`, `init`, `archive`, `reviewer debug`) | Interactive ANSI formatting; non-AI operator gateway |
| `changelog_writer.py` | T3 | Atomic append of completed task deliveries to `CHANGELOG.md` | Non-destructive header-preserving updates |
| `hooks/file_scope_guard.py` | T1 | PreToolUse whitelist enforcement | Must respond in < 50ms; no network calls |
| `hooks/context_injector.py` | T1 | PostToolUse context enrichment | Read-only; non-blocking |
| `scripts/check_no_api_bypass.py` | T1 | Static AST scanner enforcing zero provider API bypasses (INV-9) | Zero third-party runtime dependencies |
| `scripts/rules_exporter.py` | T1 | Cursor MCP rules and IDE instruction exporter | Pure export; idempotent |
| `scripts/git_pre_commit_guard.py` | T1 | Pre-commit hook enforcing Quench discipline & active task checks | Standalone script; zero external framework deps |
| `scripts/init_project.py` | T1 | Project onboarding, environment diagnostics & hook installer | Idempotent; supports `--ide` and `--install-git-hook` |
| `adapters/` | T4 | Per-vendor HTTP adapter implementations | Each adapter: stateless, vendor-isolated |

### Call Constraint Summary

```
server.py → state_machine.py   (read/write state)
server.py → schema_validator.py (validate before write)
server.py → consultation.py    (Reviewer consult path)
server.py → reviewer_engine.py (ReviewerClient factory)
server.py → manifest.py        (task CRUD)
server.py → code_explorer.py   (AST slice for refine_spec)
server.py → handoff_card.py    (pure handoff card rendering)

reviewer_engine.py → adapters/* (vendor-specific HTTP)
reviewer_engine.py → log_naming.py (session log paths)
reaper.py → log_naming.py (GC primitives)

hooks/* → path_guard.py  (path safety)
hooks/* → project_config.py (stack config read)
```

---

## 6. Cross-Reference & Architectural Sub-Contracts

- **Manifest Compaction & Generational Archiving Contract**: [`manifest_compaction_contract.md`](manifest_compaction_contract.md)  
- **FastMCP Tool & Protocol Specification** (tool parameters, field regex, return types): [`dev_tasks_mcp_specification.md`](../../dev_tasks_mcp_specification.md)  
- **Configuration Reference** (`quench_stack.yaml` fields): [`docs/configuration.md`](../configuration.md)  
- **CI Incident Tracker** (known compatibility cases, mitigation playbooks): [`docs/ci_incident_tracker_and_compatibility_guide.md`](../ci_incident_tracker_and_compatibility_guide.md)  
- **Execution Discipline Rules**: [`plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`](../../plugins/quench-dev-tasks/rules/dev-tasks-discipline.md)
