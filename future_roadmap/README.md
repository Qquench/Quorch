# Quench DevTasks MCP 未来演进路线图索引 (Roadmaps Index)

> **命名澄清与定位说明**：
> 本项目已正式定名为 **`quench-dev-orchestrator`**（Quench 智能开发编排器 / 任务调度中枢），插件核心标识为 `quench-dev-tasks`。
> 该命名精准兼顾了开发任务流转、双模型协同与全生命周期编排，彻底跳出单一 MCP 的狭隘定义，同时为未来 Quench 体系下可能衍生的其他垂直领域 MCP（如工业 PLC 通信、CAD 解析、MES 数据中台等）留出清晰独立的命名空间。

本目录收纳 Quench DevTasks MCP 从当前基线逐步迈向开源与全生态适配的阶段性架构规划与演进路线图。

---

## 阶段演进路线总览

| 阶段文档 | 核心里程碑与主题 | 目标受众与生态 | 实施重点 |
| :--- | :--- | :---: | :--- |
| 📍 **[stage1_personal_seamless_multiproject.md](./stage1_personal_seamless_multiproject.md)** | **阶段一：个人无缝跨项目治理与实战闭环** | 开发者本人（当前多项目） | 会话锁并发加固（UTC 统一/原子写入/输入净化）、双轨边界识别调优、全局快捷脚手架、Hook 可观测性日志、配置版本迁移、真实任务全生命周期归档实战 |
| 🌐 **[stage2_antigravity_community_ready.md](./stage2_antigravity_community_ready.md)** | **阶段二：Antigravity 社区通用开箱即用与开源准备** | 全体 Antigravity IDE 用户 | 消除机器绝对路径绑定（含代码错误消息）、跨平台一键安装脚本 `install.py`（含 Pre-flight 预检与回滚）、配置版本自动迁移、项目模板去特定化、开源门面资产 |
| ⚡ **[stage3_cross_tool_cursor_adaptation.md](./stage3_cross_tool_cursor_adaptation.md)** | **阶段三：以 Cursor 为切入点的跨开发工具适配** | Cursor / Windsurf / Git CLI | **单核多适配器通用架构**（Detector/Adapter 生命周期分离）、`.cursorrules` 自动导出、Git Pre-commit 物理兜底防线（零依赖+双拦截避免）、跨机器乐观锁指引、Quench CLI 工具 |
| 🧠 **[automated_subagent_api_delegation_and_codebase_inspection.md](./automated_subagent_api_delegation_and_codebase_inspection.md)** | **长期规划：基于独立 API 的全自动 Subagent 委派与代码库动态探查** | 高级架构师 / 自动化流 | Agent-in-Tool 模式、直连大模型 API、ReAct 沙箱只读探查代码库、极低 Token 深度诊断 |

---

## 架构核心原则：单核多适配器架构 (Core-Adapter Paradigm)

在推进跨工具适配（如阶段三）时，系统严格贯彻 **“坚决不维护多个 IDE 分叉版本”** 的工程原则：
1. **85% 通用内核共享**：FastMCP 服务端、任务状态机引擎、六大字段 Schema 校验器、CHANGELOG 增量写入器在所有 IDE 中完全共用同一套 Python 源码；
2. **15% 差异适配外壳**：针对 Antigravity 输出专有 Hook 拦截报文；针对 Cursor/Windsurf 输出 Rules 配置文件并启用 Git Pre-commit 物理硬防线；
3. **团队异构多工具协同**：支持不同开发者使用不同 IDE 对同一个 Git 仓库开展任务推进与审查，完全无冲突。

> [!NOTE]
> **2026-09-13 架构审查补充**：以上三阶段路线图已通过高阶架构审查模型的系统性诊断。各阶段均已纳入审查发现的风险修正项（时区安全、原子写入、符号链接防御、Pre-flight 预检、双拦截避免、跨机器乐观锁指引等），详见各阶段文档中标注为“架构审查新增”的条目。

---

## 如何通过本目录推进开发

当需要对本仓库进行功能演进或代码升级时，严格遵循以下流程：
1. 从上述对应阶段的路线图中提取特定史诗任务（Epic）；
2. 在 `docs/dev_tasks/` 目录中生成标准的六大字段开发任务单；
3. 执行双模型交接与任务确认；
4. Flash 主控领单实施、跑通 DoD 测试并通过审计；
5. 调用 `dev_tasks_archive` 归档并增量同步 `CHANGELOG.md`。
