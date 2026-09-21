# Quench DevTasks 未来演进与前沿架构探索区 (Future Roadmaps & Proposals)

[English](README.md) | [简体中文](README_zh.md)

> **双区路线图划分定位说明**：
> 本项目的路线图规划明确区分为两个独立工作区：
> 1. 📋 **当前分步开发任务路线图 (Active Development Roadmaps)**：
>    存放于 **`docs/roadmap/`**，包含当前正在推进的具体阶段，并在阶段闭环后移入 `docs/roadmap/archive/` 归档。
> 2. 🚀 **面向未来版本探索性架构提案 (Future Prospective Proposals)**（即本目录）：
>    存放面向未来长期版本可能演进方向的深度预研、前沿架构构想与非即时交付型 RFC 提案。

---

## 未来前沿架构提案清单

| 提案文档 | 核心愿景与主题 | 适用场景与受众 | 关键技术构想 | 预期成熟度 |
| :--- | :--- | :--- | :--- | :---: |
| 🔀 **[hybrid_reviewer_delegation_and_dynamic_routing.md](./hybrid_reviewer_delegation_and_dynamic_routing.md)** | **混合审查：宿主原生 Subagent 与外部推理 API 动态路由** | 多模型 IDE 协同 / 复杂业务系统重构 | • **动态审查路由器**：根据任务语义自适应路由（UI/前端 vs 核心状态机 vs 文档）；<br>• **红方双模交叉对抗**：关键重构下双重审查把关；<br>• **配额与成本弹性**：宿主订阅额度与外部 API 优雅流转。 | 规划预研 (Planned / RFC) |
| 🛡️ **[cross_language_zoning_and_anti_degradation.md](./cross_language_zoning_and_anti_degradation.md)** | **跨语言分区治理与防退化守卫架构规划** | 多语言代码库 (Python, TS, Rust, Go) / 高并发系统 | • **四分区语义模型**：Z-KERNEL, Z-CONTRACT, Z-TEST, Z-GLUE 及 FROZEN 冻土层；<br>• **LanguageZoningAdapter**：可插拔 AST 语法与通用词法适配器；<br>• **Paste Guard**：PreToolUse 拦截无脑粘贴与全量覆写信号守恒防御。 | 规划预研 (Planned / RFC) |

---

## 已交付并执行归档提案

| 提案文档 | 原始构想主题 | v0.2.0 落地成果 | 正式归档路径 |
| :--- | :--- | :--- | :---: |
| ✔️ **[automated_subagent_api_delegation_and_codebase_inspection.md](./automated_subagent_api_delegation_and_codebase_inspection.md)** | **基于独立 API 的全自动 Subagent 委派与代码库动态探查** | 已通过 `ReviewerClient` 多厂商解耦、AST `CodeExplorer` 与 `dev_tasks_refine_spec` 闭环交付。 | [已归档阶段四](../docs/roadmap/archive/stage4_automated_subagent_delegation_and_codebase_inspection.md) |


---

## 正在进行的阶段任务？

若您需要查阅当前阶段正在施工或已完成归档的工程开发任务，请前往：
👉 **[docs/roadmap/](../docs/roadmap/README.md)**

- 🧠 [已归档阶段四：模型切换优化、多层审查解耦与探查规约闭环](../docs/roadmap/archive/stage4_automated_subagent_delegation_and_codebase_inspection.md)
- ⚡ [已归档阶段三：以 Cursor 为切入点的跨开发工具适配与 CLI 工具集](../docs/roadmap/archive/stage3_cross_tool_cursor_adaptation.md)
- 🌐 [已归档阶段二：Antigravity 社区通用开箱即用与开源准备](../docs/roadmap/archive/stage2_antigravity_community_ready.md)
- 📦 [已归档阶段一：个人无缝跨项目治理与实战闭环](../docs/roadmap/archive/stage1_personal_seamless_multiproject.md)
