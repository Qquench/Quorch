# 💡 Future Roadmap Ideas & Evaluated Ledger (未来路线构想与去留评估账本)

<!-- quench-doc-meta: {"normative": false, "generates_tasks": false} -->

> ⚠️ **Non-Normative Brainstorm & Disposition Ledger / 非当期排期承诺**  
> This document serves two purposes:
> 1. **Active Candidate Pool (§1)**: High-value engineering directions that remain uniquely valuable on top of the **Gemini 4 Argon + `v1.25–v1.27` Standard/Inverted Dual-Mode + Antigravity 2.0** baseline.
> 2. **Evaluated Ledger (§2)**: Historical ideas marked `✔️ Graduated` or `❌ Rejected / Superseded` (retained intentionally so future AI agents and maintainers never re-propose dead-end designs).
>
> **Notice for Agents & Reviewer**: Do NOT automatically decompose entries from this file into DevTasks until they are formally scheduled into a versioned roadmap under `docs/roadmap/`.

---

## 🧭 Ledger Maintenance Rules (账本维护准则)

- **Adding a new idea**: Append under **§1 Active Candidate Pool** with `### YYYY-MM-DD — <Idea Title>`, **Motivation**, **Target Scope**, and **Guardrails**.
- **Graduating an idea**: When scheduled into `docs/roadmap/vX.YY_*.md` and delivered, move it to **§2 Evaluated Ledger** with `✔️ Graduated (vX.YY)`.
- **Rejecting / Superseding an idea**: Mark as `❌ Rejected / Superseded (YYYY-MM-DD): <Reason>` in **§2 Evaluated Ledger** and preserve the rationale.

---

## 1. Active Candidate Pool (待演进高价值方向 — Post-Gemini-4 & Antigravity 2.0)

### 1.1 [P1] Progressive Governance Tier (`minimal` Mode) & `frozen_paths` Overlay (渐进式轻量治理档位与冻结路径层)
*(Refined from 2026-09-21 & 2026-10-07 proposals)*

- **Motivation & Background (背景与契机)**:
  - Antigravity 2.0 now provides `/plan`, `/grill-me`, and Terminal Sandbox, **but still lacks task-scoped dynamic file-whitelist enforcement and Git-diff DoD physical verification**.
  - However, forcing all six verbose Markdown fields on small tasks creates high output-token friction—especially in `inverted` mode where flagship **Gemini 4 Argon** authors the task spec in the main session—and raises onboarding barriers for external projects.
- **Key Architecture (核心构想)**:
  - **`governance.level` in `quench_stack.yaml`**:
    - `strict` (default for `quorch` self-governance): Full six core fields + AST feasibility lint + strict audit gate.
    - `minimal` (recommended default for downstream business repos / small fixes): Requires **only the two physical enforcement fields**—`[Affected Files] / 【涉及文件】` and `[DoD Verification Commands] / 【DoD 验证命令】`—turning the four narrative fields optional while preserving **100% of `FileScopeGuard` and `dev_tasks_complete` physical guarantees**.
  - **`frozen_paths` Immutable Overlay**: Optional glob list in `quench_stack.yaml` (e.g., lockfiles, protocol snapshots, production migrations) where `FileScopeGuard` enforces hard `deny` regardless of active task scope unless explicitly unlocked by the human developer.

---

### 1.2 [P1] Anti-Reward-Hacking Deterministic Diff Audit (防伪造完工：测试断言净增量与 `skip` 拦截)
*(Distilled from Cross-Language Zoning & Cost/Hardening Epic A)*

- **Motivation & Background (背景与契机)**:
  - In both `inverted` mode (where lightweight `Flash` subagents act as code runners) and `standard` mode, agile execution models under pressure to pass DoD tests may weaken existing assertions, delete failing `assert` lines, or decorate tests with `@pytest.mark.skip` / `xfail`.
- **Key Architecture & Scope Restraint (核心构想与克制边界)**:
  - **Deterministic Static Diff Gate (Adopt)**: During `dev_tasks_complete` Git diff auditing on test files, enforce **non-negative assertion delta (`added_assertions >= removed_assertions`)** unless an explicit `test_evidence` rationale is supplied, and block newly introduced unconditional `skip` / `xfail` markers. Zero LLM token cost, sub-50ms execution.
  - **Runtime Semantic Mutation Testing (Defer)**: Automatically mutating production AST and re-running `pytest` on every `complete` is intentionally excluded from the synchronous lifecycle due to latency and Windows file-lock risks.

---

### 1.3 [P2] Standardized Packaging (`uvx quorch init`) & Thin `ClaudeCodeAdapter` (标准插件化一键分发与同构 Hook 宿主薄适配)
*(Refined from 2026-09-21 Onboarding & Cross-Host proposals)*

- **Motivation & Background (背景与契机)**:
  - Current external project setup still relies on `setup_workspace.py` path templating. Aligning with PyPI `[project.scripts]` (`uvx quorch init --minimal`) and Antigravity 2.0's native plugin layout (`~/.gemini/config/plugins/quench-dev-tasks/`) enables zero-boilerplate adoption across repositories.
- **Key Architecture (核心构想)**:
  - **`quorch init`**: Generates a clean `.agents/quench_stack.yaml` + minimal `AGENTS.md` pointer without polluting downstream repos with absolute-path scripts.
  - **`ClaudeCodeAdapter` Only (No Universal FS/LSP Shim)**: Restrict cross-host hard interception adapters strictly to hosts that natively expose `PreToolUse` / `Stop` JSON stdin/stdout hooks (such as Claude Code `.claude/settings.json`), reusing 95% of `file_scope_guard.py` and `context_injector.py`.

---

## 2. Evaluated Ledger: Graduated & Rejected / Superseded Ideas (已评估历史账本)

### ✔️ 2026-10-31 — Dual-Mode AuditGate Alignment, Single-Source Plugin Mounting & Hook Hardening — Graduated (v1.28)
- **Status**: **✔️ Graduated (v1.28)** — Delivered in roadmap `docs/roadmap/v1.28_dual_mode_audit_gate_and_agy2_single_mount_roadmap.md`.
- **Delivered Capabilities**:
  1. **Dual-Mode AuditGate Alignment**: Added `explicit_inverted_orchestrator` to `AuditGateReason` and `SAFETY_KEY_DOMAINS` (18 literals SSOT); enabled explicit inverted mode audit sign-off with audit logging and session bypass guardrails.
  2. **Job Supervisor GC & Hard Ceiling**: Defined `POLL_WAIT_MAX_S_HARD_CEILING = 25.0` in `tool_surface_constants.py`; added opportunistic `gc_terminal_jobs()` during new task submissions in `ReviewerJobSupervisor`.
  3. **Single-Source Plugin Deduplication**: Added `is_workspace_plugin_mounted` and auto-heal stripping of redundant `.agents/hooks.json` and `.agents/mcp_config.json` while preserving third-party configs.
  4. **Hook & Rules Hardening**: Extended `file_scope_guard` to intercept `edit_file`, `write_file`, and `run_command` with full `build_post_image` simulation; added 6-guardrail 1-shot circuit-breaker `Stop` Hook in `context_injector.py`; added `plugins/quench-dev-tasks/rules/AGENTS.md` with 3-way sentinel synchronization.

---

### ❌ 2026-10-07 — Antigravity Native Pro Subagent Reviewer Integration (从 Flash 主会话向上唤起原生 Pro/Argon 子代理审查)
- **Status**: **❌ Rejected / Superseded (2026-10-31)** — Superseded by `v1.25` **Inverted Mode (`inverted`)**.
- **Evaluation & Empirical Verification (`2026-10-31`)**:
  1. **Model Lineup Reality**: Gemini 4 shipped **Gemini 4 Argon** without a "Gemini 4 Pro" tier.
  2. **Live Antigravity 2.0 Subagent Probe (`2026-10-31`)**:
     - `invoke_subagent` `Model` enum remains strictly `["inherit", "flash_lite", "flash", "pro"]` (and custom subagent `.md` YAML frontmatter `model:` supports the exact same four values)—there is **no `"argon"` enum option**.
     - Controlled runtime probing confirmed that `invoke_subagent(..., Model="pro")` still routes to the legacy **Gemini 3.x Pro** tier (`input_tokens: 29,499` matching `Model="flash"`'s `29,480` tokenizer framing rather than Argon's `28,954`, with ~170s single-turn latency), so **a `Flash` main session still cannot invoke `Argon` upward as a Reviewer subagent**.
     - Conversely, when **Argon** is the main session, `invoke_subagent(..., Model="inherit")` **does cleanly spawn Argon subagents** (`input_tokens: 28,954`), and `Model="flash"` spawns fast `Flash` worker/research subagents.
  3. **Resolution**: `v1.25` Inverted Mode (Argon as Main Session orchestrator/reviewer + downward `Model="flash"` Runner/Research subagents) achieves the exact `$0` extra API cost goal cleanly without needing upward subagent elevation or custom subagent verdict-signing tools. Existing `reviewer_channel="host_subagent"` and `agents/reviewer/agent.md` remain frozen as minimal compatibility stubs only.

---

### ❌ Stage 5 Draft — Hybrid Reviewer: Native Subagent & External API Dynamic Routing (内外混合动态路由与双盲红队)
- **Status**: **❌ Rejected (2026-10-31)** — Unnecessary complexity under the explicit `Standard` vs `Inverted` binary architecture.
- **Reason**: `Standard` mode (`Flash` main + `external_api` `ReviewerClient` with `v1.26` 64-token aligned prefix caching) and `Inverted` mode (`Argon` main + `Flash` subagents) already provide clear, deterministic, user-selectable topologies. Adding a third dynamic router or dual-blind multi-reviewer voting doubles latency/cost and muddies failure attribution.

---

### ❌ 2026-09-24 — `quorch reviewer watch` Streaming TUI & VS Code Status Bar Extension (独立 TUI 监视器与底边状态栏扩展)
- **Status**: **❌ Rejected / Superseded (2026-10-31)** — Superseded by `v1.24` native MCP `notifications/progress` + Antigravity 2.0 Auxiliary Pane.
- **Reason**:
  1. `v1.24` delivered `ProgressBridge` (`notifications/progress`) in-place tool-card updates plus 20s long-polling (`_clamp_wait` 25s ceiling).
  2. Antigravity 2.0 is a standalone Electron desktop app (using `sidecar.json` Auxiliary Pane web panels rather than VS Code `vscode.window.createStatusBarItem`) and natively surfaces **Subagents, Background Tasks, Terminals, and Files Changed** in its right-hand Auxiliary Pane.
  3. In `inverted` mode, Argon reasons directly in the main session stream with zero background polling opacity.

---

### ❌ 2026-09-21 — Single-Worktree DAG Concurrency & Disjoint File Set Locking (`S_A ∩ S_B = ∅`) (单工作树并发状态机与不相交文件集合锁)
- **Status**: **❌ Rejected / Superseded (2026-10-31)** — Superseded by Antigravity 2.0 native `invoke_subagent(Workspace="share" | "branch")`.
- **Reason**: Running concurrent writers inside a single shared working tree corrupts `pytest` execution isolation and `reconcile_workspace_against_whitelist` baseline snapshots even when touched file sets are disjoint. Antigravity 2.0 now natively provides isolated Git worktrees/clones via `Workspace: "share"` and `Workspace: "branch"` plus `/teamwork`, solving parallel isolation at the OS/VCS layer while keeping `state_machine.py` (`INV-1`) simple and race-free.

---

### ❌ 2026-09-21 — Universal Pre-Tool LSP / Filesystem Interception Shim & Interactive CLI Task Wizard (通用文件系统拦截代理与 CLI 建单向导)
- **Status**: **❌ Rejected (2026-10-31)** — Over-engineered / superseded by host-native capabilities.
- **Reason**: Intercepting OS/LSP file writes for hosts without lifecycle hooks creates brittle false positives against compilers, formatters, and Git operations; Antigravity 2.0 natively provides Terminal Sandbox + `PreToolUse` hooks (and non-hook hosts remain covered by `git_pre_commit_guard.py` + `reconcile_workspace_against_whitelist`). Interactive requirement clarification is natively handled by Antigravity 2.0 `/plan` and `/grill-me`.

---

### ✔️ 2026-09-23 — Microkernel Decoupling, Control Inversion & Lease Reaper (微内核解耦、控制权反转与僵尸租约回收)
- **Status**: **✔️ Graduated (`v1.06`, `v1.08`, `v1.25–v1.27`)**.
- **Delivered Summary**: Fencing-token CAS task leases (`manifest_lease.py`), multi-dimensional liveness reaper (`reaper.py`), task-directory physical protection (`file_scope_guard.py`), two-way `.agents/.quorch/manifest.json` interlock, and `standard`/`inverted` Autopilot harness (`autopilot_harness.py`) are all in production.
