# Quench Dev-Orchestrator 开发任务管理

[English](README.md) | [简体中文](README_zh.md)

> 本目录遵循 **Quench 双模型协同开发任务管理工作流（架构审查 Reviewer + 敏捷执行 Runner）**。  
> 所有开发规则（状态标记、六大核心字段规范、会话启动协议、架构审查行为、DoD 验收标准）参见内置规范：
> - 核心工作流：[`plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md`](../../plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md)
> - 审查模型指引：[`plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`](../../plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md)
> - 编码与测试标准：[`plugins/quench-dev-tasks/rules/coding-standards.md`](../../plugins/quench-dev-tasks/rules/coding-standards.md)

---

## 本项目技术栈与验收规范

| 属性 | 规范要求 |
| :--- | :--- |
| **技术栈** | Python (FastMCP) + Antigravity Plugin & Cursor 适配层 + CLI 工具 |
| **单测套件** | `$env:PYTHONPATH="plugins/quench-dev-tasks/server"; pytest plugins/quench-dev-tasks/server/tests -v` |
| **设计规范** | [`dev_tasks_mcp_specification.md`](../../dev_tasks_mcp_specification.md) |
| **DoD 验收标准** | 全量单元测试 100% 通过（105+ 项）、零机器绝对路径硬编码、跨平台 UTF-8 编码兼容 |

---

## 当前活跃任务单 (Active Dev Task)

> 当前暂无进行中任务单（所有阶段性开发任务均已闭环并移入归档区）。  
> 新任务可通过调用 `dev_tasks_propose` 或在 `docs/roadmap/` 阶段路线图指引下创建。

---

## 归档记录 (Archive History)

| 归档任务单 | 核心交付内容 | 任务数 | 闭环状态 |
| :--- | :--- | :---: | :---: |
| [`archive/2026-09-13_stage3_cross_tool_cursor_adaptation.md`](./archive/2026-09-13_stage3_cross_tool_cursor_adaptation.md) | 跨工具 Cursor 适配与轻量统一 CLI 工具集（MDC 导出/链式 Git Hook） | 3 | ✔️ 100% 闭环 |
| [`archive/2026-09-13_stage2_antigravity_community_ready.md`](./archive/2026-09-13_stage2_antigravity_community_ready.md) | Antigravity 社区开源就绪（动态渲染/自愈脚手架/门面资产） | 4 | ✔️ 100% 闭环 |
| [`archive/2026-09-13_fix_external_hooks_and_diagnostics.md`](./archive/2026-09-13_fix_external_hooks_and_diagnostics.md) | 外部项目 Hook 闭环生成与 Windows cmd 引号保护 | 2 | ✔️ 100% 闭环 |
| [`archive/2026-09-13_stage1_scaffolding_observability_and_migration.md`](./archive/2026-09-13_stage1_scaffolding_observability_and_migration.md) | 可观测性日志/配置平滑升级/模板中立化 | 3 | ✔️ 100% 闭环 |
| [`archive/2026-09-11_governance_engine_and_cross_tool_adaptation.md`](./archive/2026-09-11_governance_engine_and_cross_tool_adaptation.md) | 治理引擎深化（旁路锁+双轨边界）与开源跨工具适配 | 4 | ✔️ 100% 闭环 |
| [`archive/2026-09-11_plugin_development.md`](./archive/2026-09-11_plugin_development.md) | quench-dev-tasks 插件全量核心机制开发（Phase 1 ~ Phase 3） | 11 | ✔️ 100% 闭环 |
