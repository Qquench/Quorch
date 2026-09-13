# Quench DevTasks 未来演进与前沿架构探索区 (Future Roadmaps & Proposals)

> **双区路线图划分定位说明**：
> 本项目的路线图规划明确区分为两个独立工作区：
> 1. 📋 **当前分步开发任务路线图 (Active Development Roadmaps)**：
>    存放于 **`docs/roadmap/`**，包含当前正在推进的具体阶段（如 Stage 2 开源开箱即用、Stage 3 跨工具适配），并在阶段闭环后移入 `docs/roadmap/archive/` 归档。
> 2. 🚀 **面向未来版本探索性架构提案 (Future Prospective Proposals)**（即本目录）：
>    存放面向未来长期版本可能演进方向的深度预研、前沿架构构想与非即时交付型 RFC 提案。

---

## 未来前沿架构提案清单

| 提案文档 | 核心愿景与主题 | 适用场景与受众 | 关键技术构想 | 预期成熟度 |
| :--- | :--- | :--- | :--- | :---: |
| 🧠 **[automated_subagent_api_delegation_and_codebase_inspection.md](./automated_subagent_api_delegation_and_codebase_inspection.md)** | **基于独立 API 的全自动 Subagent 委派与代码库动态探查** | 高级架构师 / CI/CD 自动化流水线 / 跨团队大型代码库治理 | • **Agent-in-Tool 模式**：通过独立模型 API Key 启动轻量只读沙箱；<br>• **ReAct 自主代码库探查**：智能检索符号、追溯调用链路；<br>• **极低 Token 消耗**：在沙箱内完成万行代码扫描，仅将结构化结论返还给主控模型。 | 长期探索 (Research / RFC) |

---

## 正在进行的阶段任务？

若您需要查阅当前阶段正在施工或即将推进的工程开发任务，请前往：
👉 **[docs/roadmap/](../docs/roadmap/README.md)**

- 🌐 [阶段二：Antigravity 社区通用开箱即用与开源准备](../docs/roadmap/stage2_antigravity_community_ready.md)
- ⚡ [阶段三：以 Cursor 为切入点的跨开发工具适配](../docs/roadmap/stage3_cross_tool_cursor_adaptation.md)
- 📦 [已归档阶段一：个人无缝跨项目治理与实战闭环](../docs/roadmap/archive/stage1_personal_seamless_multiproject.md)
