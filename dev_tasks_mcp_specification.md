# Quench-DevTasks MCP Service Architecture & Specification (DevTasks Orchestrator Spec)

[English](dev_tasks_mcp_specification.md) | [简体中文](dev_tasks_mcp_specification_zh.md)

> **Version**: v1.3.0 (Implemented & Verified)  
> **Implementation Status**: ✔️ Fully implemented and verified with 105+ automated unit tests (covering Google Antigravity, Cursor cross-tool adapters, and unified CLI)  
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
    1. **Explicit Developer Instruction**: e.g., user requests: "Have the Reviewer inspect the current module and draft a comprehensive DevTask";
    2. **Self-Escalation**: Triggered when tackling multi-module refactoring, resolving architectural impasses, or encountering repeated test failures.
  - Upon completing task decomposition or architecture review, the Reviewer **immediately sleeps**, handing back execution to the runner model.

### 1.3 Model Decoupling & Logical Role Aliases
The MCP server operates as an independent Python process (FastMCP over stdio JSON-RPC) and **never hardcodes specific model version strings**. Logical roles are mapped decoupled via project configuration:

```yaml
# Configuration concept
version: "1.0"

roles:
  # Reviewer / Strategic Brain: Maps to user-selected frontier reasoning model
  REVIEWER:
    role_description: "Deep architectural analysis, conflict resolution, task planning"
    temperature: 0.2

  # Runner / Implementation Engine: Maps to fast everyday model
  RUNNER:
    role_description: "Step-by-step implementation, defensive coding, DoD test execution"
    temperature: 0.1
```

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

---

## 3. Task Lifecycle & Physical State Machine

```mermaid
stateDiagram-v2
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

The server exposes 8 atomic FastMCP tools:

1. **`dev_tasks_status`**: Scans the workspace `docs/dev_tasks/` directory, returning structured queue metrics (active, confirmed, rework, pending).
2. **`dev_tasks_propose`**: Validates the six core fields and proposes a new task in `[Pending]` status.
3. **`dev_tasks_confirm`**: Advances tasks to `[Confirmed]`, `[Skipped]`, or transitions them to `[Rework]`.
4. **`dev_tasks_checkout`**: Checks out the next confirmed task, sets its state to `[In Progress]`, and provides step-by-step guidance.
5. **`dev_tasks_complete`**: Submits a completed task, requiring DoD test command output and diff verification.
6. **`dev_tasks_escalate`**: Awakens the Reviewer role with focused contextual snippets when encountering roadblocks.
7. **`dev_tasks_archive`**: Retires closed tasks to `archive/` and increments the changelog.
8. **`dev_tasks_set_bypass`**: Manages temporary time-bound bypass tokens with strict audit logging.

---

## 5. Implementation Registry

All specifications are verified across the codebase:

| Spec Section | Implementation Files | Key Mechanism |
| :--- | :--- | :--- |
| **Review Protocols** | `rules/dev-tasks-discipline.md`<br>`skills/dev-tasks-review/` | Read-only planning constraints and graded quality auditing |
| **State Machine** | `server/state_machine.py` | Strict enum transitions, cross-process `FileLock`, Unicode emoji regex normalization |
| **Six Core Fields** | `server/schema_validator.py` | Bilingual field aliases, markdown block parsing, granularity warnings |
| **Physical Guards** | `server/hooks/file_scope_guard.py`<br>`server/hooks/context_injector.py`<br>`scripts/git_pre_commit_guard.py` | `PreToolUse` physical interception (`force_ask`), `PreInvocation` reminder injection, Git pre-commit barrier |
| **Decoupled Config** | `server/project_config.py`<br>`templates/quench_stack.yaml` | Workspace `.agents/quench_stack.yaml` integration with migration engine |
| **8 MCP Tools** | `server/server.py` | FastMCP tool registration with bilingual docstrings and argument descriptions |
| **Cross-Tool Adapters** | `server/adapters/` | Multi-host adapter layer supporting Antigravity, Cursor, and generic CLI |
| **Rules Exporter** | `scripts/rules_exporter.py` | Exports `.cursorrules` and modern `.cursor/rules/quench-dev-tasks.mdc` |
| **Unified CLI** | `server/cli.py` | Standalone `quorch status/check/init/archive` terminal command suite |
| **Installer** | `scripts/install.py`<br>`scripts/init_project.py` | Pre-flight health checks, snapshot backup/rollback, automated IDE configuration |
| **Test Matrix** | `server/tests/` (105 tests) | 100% passing test coverage across Windows and Ubuntu environments |
