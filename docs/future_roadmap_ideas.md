# 💡 Future Roadmap Ideas & Prospective Proposals (未来路线构想与灵感暂存)

<!-- quench-doc-meta: {"normative": false, "generates_tasks": false} -->

> ⚠️ **Non-Normative Brainstorm Pool / 非当期排期承诺**  
> This document serves as a dedicated holding area for future architectural brainstorms, exploratory RFCs, and prospective feature ideas not scheduled for the active version milestone.  
> **Notice for Agents & Reviewer**: Ideas documented here represent exploratory proposals. Do NOT automatically decompose entries from this file into DevTasks until they are formally matured and scheduled into an active roadmap under `docs/roadmap/`.

---

## 🧭 How to Use This Idea Pool (使用指引)

- **Adding a new idea**: When a spontaneous idea or future feature comes up that does not belong in the current milestone, simply append a new section below with:
  - `## YYYY-MM-DD — <Idea Title>`
  - **Motivation & Background (背景与契机)**
  - **Why not now? (为什么当期不做)**
  - **Key Architecture & Preconditions (核心构想与前置条件)**
- **No catalog maintenance**: You do NOT need to maintain a separate README index or table for this file.
- **Graduating an idea**: When an idea matures and is scheduled into a release cycle, move it to `docs/roadmap/` as part of that stage's roadmap.
- **Rejecting an idea**: If an idea is evaluated and rejected, mark it as `❌ Rejected: <Reason>` and keep the record to prevent future AI agents or maintainers from repeatedly revisiting the same dead-end.

---

## 🔀 Hybrid Reviewer: Native Subagent & External API Dynamic Routing
*(Originally drafted for Stage 5 exploratory research)*

### 1. Motivation & Context
Developers frequently have access to multiple complementary reviewer capabilities:
1. **Host-Native Subagents**: Built-in IDE agents (Antigravity, Claude Code) with native access to IDE workspace state, browser simulators, and zero external API token costs.
2. **External / Local Deep Reasoning APIs**: Frontier thinking models (DeepSeek-Reasoner / Flash, OpenAI o-series, local Ollama models) with strong deadlock detection and exhaustive branch reasoning.

The current system relies on a static priority waterfall (`strategy_order: ["subagent", "engine", "manual"]`). A future dynamic router would allow intelligent, context-aware traffic splitting.

### 2. Core Architecture: Dynamic Reviewer Router
- **Task-Aware Semantic Routing**:
  - *UI / Visual / Accessibility Tasks*: Route preferentially to native subagents with DOM/screenshot inspection capabilities.
  - *Concurrency / State Machine / Crypto Core*: Route to external thinking reasoning models to exhaustively probe race conditions and edge states.
  - *Documentation / Configuration Tweaks*: Rapid pass-through or lightweight local check.
- **Red-Team Duel (Adversarial Cross-Validation)**:
  - For high-risk refactorings (`[P0-CRITICAL]`), employ host subagents for readability and architectural design review, combined with external reasoning models acting as an adversarial red-team to search for boundary flaws before task checkout.
- **Quota & Cost Elasticity**:
  - Dynamically fallback between host quotas and external API tokens when encountering 429 rate limits or context window exhaustion.

---

## 🛡️ Cross-Language Zoning Governance & Anti-Degradation Guards
*(Originally drafted for multi-language enterprise codebases)*

### 1. Motivation & Context
File-path whitelists alone do not prevent semantic degradation inside allowed files:
1. AI models may silently prune error handling branches or weaken assertions during refactoring.
2. AI may lower assertion strictness in unit tests to artificially turn DoD green.
3. AI tends to rewrite multi-thousand-line files from scratch, accidentally destroying concurrency locks and performance optimizations.

### 2. Core Architecture: Four-Zone Model & Frozen Overlay
- **`Z-KERNEL` (Logic Microkernel)**: Core state machines, critical algorithms. Rule: error handling branches and assertion counts must never net-decrease.
- **`Z-CONTRACT` (Interface Layer)**: Public APIs, Protocol/Trait definitions, `.d.ts`. Rule: breaking changes mandate companion migration tests and task records.
- **`Z-TEST` (Adversarial Test Suite)**: Unit and integration tests. Rule: test coverage and assertion strength must not be diluted.
- **`Z-GLUE` (Glue & Wiring)**: CLI wiring, adapter glue. Rule: business logic expansion inside glue code is intercepted.
- **`⊕ FROZEN` (Frozen Overlay)**: Machine-generated code, lockfiles. Rule: immutable, any write triggers physical DENY.
- **Pluggable Adapters (`LanguageZoningAdapter`)**: AST-based auditing for Python and TypeScript, with lexical fallback for Go, Rust, and C++.
