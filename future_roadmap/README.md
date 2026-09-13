# Quench MCP 未来演进路线图索引 (Roadmaps Index)

本目录收纳 Quench MCP 治理套件从当前基线逐步迈向开源与全生态适配的阶段性架构规划与演进路线图。

---

## 阶段演进路线总览

| 阶段文档 | 核心里程碑与主题 | 目标受众与生态 | 实施重点 |
| :--- | :--- | :---: | :--- |
| 📍 **[stage1_personal_seamless_multiproject.md](./stage1_personal_seamless_multiproject.md)** | **阶段一：个人无缝跨项目治理与实战闭环** | 开发者本人（当前多项目） | 会话锁并发加固、双轨边界识别调优、全局快捷脚手架、真实任务全生命周期归档实战 |
| 🌐 **[stage2_antigravity_community_ready.md](./stage2_antigravity_community_ready.md)** | **阶段二：Antigravity 社区通用开箱即用与开源准备** | 全体 Antigravity IDE 用户 | 消除机器绝对路径绑定、跨平台一键安装脚本 `install.py`、项目模板去特定化、开源门面资产 |
| ⚡ **[stage3_cross_tool_cursor_adaptation.md](./stage3_cross_tool_cursor_adaptation.md)** | **阶段三：以 Cursor 为切入点的跨开发工具适配** | Cursor / Windsurf / Git CLI | 适配器抽象层、`.cursorrules` 自动导出、Git Pre-commit 物理兜底防线、Quench CLI 工具 |
| 🧠 **[automated_subagent_api_delegation_and_codebase_inspection.md](./automated_subagent_api_delegation_and_codebase_inspection.md)** | **长期规划：基于独立 API 的全自动 Subagent 委派与代码库动态探查** | 高级架构师 / 自动化流 | Agent-in-Tool 模式、直连大模型 API、ReAct 沙箱只读探查代码库、极低 Token 深度诊断 |

---

## 如何通过本目录推进开发

当需要对本仓库进行功能演进或代码升级时，严格遵循以下流程：
1. 从上述对应阶段的路线图中提取特定史诗任务（Epic）；
2. 在 `docs/dev_tasks/` 目录中生成标准的六大字段开发任务单；
3. 执行双模型交接与任务确认；
4. Flash 主控领单实施、跑通 DoD 测试并通过审计；
5. 调用 `dev_tasks_archive` 归档并增量同步 `CHANGELOG.md`。
