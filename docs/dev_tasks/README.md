# Quench MCP 开发任务管理

> 本目录遵循与 [JJW_MES docs/dev_tasks/](file:///d:/Work/JJW_MES/docs/dev_tasks/README.md) 相同的 **Opus → Flash 双模型开发任务管理工作流**。
> 所有规则（状态标记 §4、会话启动协议 §5、审查行为 §7、交付规则 §8）以原 README 为权威来源，此处不重复。

## 差异点

| 项目 | JJW_MES | Quench MCP |
|------|---------|------------|
| 技术栈 | FastAPI + Vue3 + SQLite | Python (FastMCP) + Antigravity Plugin API |
| 测试 | `python scripts/run_safe_tests.py` | `cd server && python -m pytest tests/` |
| 构建 | Nuitka standalone | 纯 Python 包，无构建 |
| 设计参考 | `docs/architecture/internal_system_design.md` | `dev_tasks_mcp_specification.md`（项目根） |

---

## 当前活跃任务单 (Active Dev Task)

| 任务单 | 核心目标 | 任务数 | 状态 | 审查重点 |
| :--- | :--- | :---: | :---: | :--- |
| [`2026-09-11_governance_engine_and_cross_tool_adaptation.md`](./2026-09-11_governance_engine_and_cross_tool_adaptation.md) | 治理引擎深化（旁路锁+双轨边界）与开源跨工具适配 | 3 | ⬜ 待 Opus 审查确认 | 安全防御加固、边界算法完备性、开源跨平台解耦 |

---

## 归档记录 (Archive History)

| 归档任务单 | 核心交付阶段 | 任务数 | 归档日期 | 闭环状态 |
| :--- | :--- | :---: | :---: | :--- |
| [`archive/2026-09-11_plugin_development.md`](./archive/2026-09-11_plugin_development.md) | quench-dev-tasks 插件全量开发（Phase 1 ~ Phase 3） | 11 | 2026-09-11 | ✔️ 100% 闭环 |


