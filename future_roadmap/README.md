# Quench DevTasks Future Roadmaps & Prospective Proposals

[English](README.md) | [简体中文](README_zh.md)

> **Two-Tier Roadmap Structure**:  
> The project organizes roadmap planning into two distinct scopes:  
> 1. 📋 **Active Development Roadmaps**:  
>    Located in **`docs/roadmap/`**, tracking actively developing engineering stages (such as Stage 2 Community Release and Stage 3 Cross-Tool Adaptation), which are moved to `docs/roadmap/archive/` upon stage closure.  
> 2. 🚀 **Future Prospective Proposals** (This directory):  
>    Houses long-term architectural explorations, frontier research, and non-immediate RFC proposals for future major milestones.

---

## Prospective Architecture Proposals

| Proposal Document | Theme & Core Vision | Target Audience | Key Architectural Ideas | Maturity |
| :--- | :--- | :--- | :--- | :---: |
| 🧠 **[automated_subagent_api_delegation_and_codebase_inspection.md](./automated_subagent_api_delegation_and_codebase_inspection.md)** | **Automated Subagent API Delegation & Dynamic Codebase Inspection** | Senior Architects / Automated CI/CD / Large Codebases | • **Agent-in-Tool Pattern**: Lightweight read-only execution sandbox launched via dedicated API key;<br>• **Autonomous ReAct Inspection**: Semantic symbol resolution and call-chain tracing;<br>• **Ultra-Low Token Overhead**: Multi-thousand line scanning summarized into structured conclusions before returning to main context. | Research / RFC |

---

## Active Stage Roadmaps

If you are looking for current engineering stages and immediate task breakdowns, please visit:  
👉 **[docs/roadmap/](../docs/roadmap/README.md)**

- ⚡ [Archived Stage 3: Cross-Tool Cursor Adaptation & CLI Tools](../docs/roadmap/archive/stage3_cross_tool_cursor_adaptation.md)
- 🌐 [Archived Stage 2: Antigravity Community Release & Out-of-the-Box Readiness](../docs/roadmap/archive/stage2_antigravity_community_ready.md)
- 📦 [Archived Stage 1: Seamless Multi-Project Governance & Lifecycle Closure](../docs/roadmap/archive/stage1_personal_seamless_multiproject.md)
