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

## 活跃任务与归档记录

- **活跃任务**：在当前目录下通过规范单据（如 `2026-09-XX_*.md`）跟踪。
- **归档任务**：已交付单据归档在 [`archive/`](./archive/)，并通过 `quench archive` 自动同步至 [`CHANGELOG.md`](../../CHANGELOG.md)。
- **查看状态**：运行 `quench status` 或调用 `dev_tasks_status` 即可查看当前实时全局状态。
