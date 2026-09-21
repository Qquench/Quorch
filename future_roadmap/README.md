# Quench DevTasks Future Roadmaps & Prospective Proposals

[English](README.md) | [简体中文](README_zh.md)

> **Two-Tier Roadmap Structure**:  
> The project organizes roadmap planning into two distinct scopes:  
> 1. 📋 **Active Development Roadmaps**:  
>    Located in **`docs/roadmap/`**, tracking actively developing engineering stages, which are moved to `docs/roadmap/archive/` upon stage closure.  
> 2. 🚀 **Future Prospective Proposals** (This directory):  
>    Houses long-term architectural explorations, frontier research, and non-immediate RFC proposals for future major milestones.

---

## Prospective Architecture Proposals

| Proposal Document | Theme & Core Vision | Target Audience | Key Architectural Ideas | Maturity |
| :--- | :--- | :--- | :--- | :---: |
| 🔀 **[hybrid_reviewer_delegation_and_dynamic_routing.md](./hybrid_reviewer_delegation_and_dynamic_routing.md)** | **Hybrid Reviewer: Native Subagent & External API Dynamic Routing** | Multi-Model IDEs / Cross-Team Collaboration | • **Dynamic Reviewer Router**: Semantic routing based on task nature (UI vs Concurrency vs Config);<br>• **Red-Team Duel**: Adversarial cross-validation for critical refactorings;<br>• **Quota Elasticity**: Seamless overflow between host subscription and external API. | Planned / RFC |
| 🛡️ **[cross_language_zoning_and_anti_degradation.md](./cross_language_zoning_and_anti_degradation.md)** | **Cross-Language Zoning Governance & Anti-Degradation Guards** | Multi-Language Codebases (Python, TS, Rust, Go) | • **Four-Zone Semantic Model**: Z-KERNEL, Z-CONTRACT, Z-TEST, Z-GLUE + FROZEN overlay;<br>• **LanguageZoningAdapter**: AST and lexical fallback adapters;<br>• **Paste Guard**: PreToolUse assertion conservation and rewrite signal defense. | Planned / RFC |

---

## Completed & Executed Proposals

| Proposal Document | Original Theme | Execution & Delivery in v0.2.0 | Archived Location |
| :--- | :--- | :--- | :---: |
| ✔️ **[automated_subagent_api_delegation_and_codebase_inspection.md](./automated_subagent_api_delegation_and_codebase_inspection.md)** | **Automated Subagent API Delegation & Dynamic Codebase Inspection** | Implemented via `ReviewerClient` multi-tier decoupling, AST `CodeExplorer`, and `dev_tasks_refine_spec`. | [Archived Stage 4](../docs/roadmap/archive/stage4_automated_subagent_delegation_and_codebase_inspection.md) |


---

## Active & Archived Stage Roadmaps

If you are looking for current engineering stages and immediate task breakdowns, please visit:  
👉 **[docs/roadmap/](../docs/roadmap/README.md)**

- 🧠 [Archived Stage 4: Model Switching Optimization & Subagent Delegation](../docs/roadmap/archive/stage4_automated_subagent_delegation_and_codebase_inspection.md)
- ⚡ [Archived Stage 3: Cross-Tool Cursor Adaptation & CLI Tools](../docs/roadmap/archive/stage3_cross_tool_cursor_adaptation.md)
- 🌐 [Archived Stage 2: Antigravity Community Release & Out-of-the-Box Readiness](../docs/roadmap/archive/stage2_antigravity_community_ready.md)
- 📦 [Archived Stage 1: Seamless Multi-Project Governance & Lifecycle Closure](../docs/roadmap/archive/stage1_personal_seamless_multiproject.md)
