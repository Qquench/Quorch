# Quench DevTasks 阶段开发任务路线图索引 (Development Roadmaps Index)

> **定位说明**：
> 本目录收纳 **当前工程周期内分步推进的开发任务阶段性路线图 (Development Stage Roadmaps)**。
> 各阶段在此承接史诗级任务（Epic）的规划与拆解，进入开发后在 `docs/dev_tasks/` 中生成任务单执行。
> 阶段达成闭环后，路线图移入 `archive/` 归档。
> 
> 若查阅**面向未来长期可能演进方向与探索性架构提案**，请参阅 🚀 [future_roadmap/](../../future_roadmap/README.md)。

---

## 阶段演进路线总览

| 阶段 | 路线图文件 | 核心里程碑与主题 | 实施重点 | 当前状态 |
| :--- | :--- | :--- | :--- | :---: |
| **阶段二** | 🌐 **[stage2_antigravity_community_ready.md](./stage2_antigravity_community_ready.md)** | **Antigravity 社区通用开箱即用与开源准备** | 消除机器绝对路径绑定、跨平台一键安装脚本 `install.py`（含 Pre-flight 预检与回滚）、模板中立化、开源门面资产（MPL-2.0） | 📌 **待推进 (Next)** |
| **阶段三** | ⚡ **[stage3_cross_tool_cursor_adaptation.md](./stage3_cross_tool_cursor_adaptation.md)** | **以 Cursor 为切入点的跨开发工具适配** | **单核多适配器通用架构**（Detector/Adapter 生命周期解耦）、`.cursorrules` 自动导出、Git Pre-commit 物理兜底硬防线（零依赖+双拦截防范）、跨机器乐观锁指引、Quench CLI 工具 | 📋 **规划中 (Planned)** |

---

## 已归档阶段 (Completed & Archived)

| 阶段 | 归档文件 | 核心达成事项 | 归档时间 |
| :--- | :--- | :--- | :---: |
| **阶段一** | ✔️ **[stage1_personal_seamless_multiproject.md](./archive/stage1_personal_seamless_multiproject.md)** | **个人无缝跨项目治理与实战闭环**：<br>• 会话锁并发加固（UTC 统一/原子写入/输入净化/FileLock 并发保护）；<br>• 双轨边界判定引擎（多语言/工程目录智能免管）；<br>• Hook 决策可观测性（`SafeRotatingFileHandler` 1MB×3 轮转、结构化审计日志、消灭静默 pass）；<br>• 配置版本平滑迁移（`schema_version: "1.0"`、零注释破坏文本补丁写盘）；<br>• 脚手架轻量化与体检诊断（`init_project.py --check`、`quench-init.ps1`）。 | 2026-09-13 |

---

## 开发流程流转协议

1. **分步路线规划**：在 `docs/roadmap/stage<N>_*.md` 中拆解史诗级需求与技术方案；
2. **任务单生成与确认**：通过 `dev_tasks_propose` 将 Epic 实例化为 `docs/dev_tasks/<date>_<name>.md`；
3. **架构审查与交接**：高阶架构审查模型 (Reviewer) 审查并批准任务单；
4. **领单实施与验证**：执行模型领单，实现核心逻辑，通过对应 DoD 自动化断言；
5. **审计闭环与归档**：调用 `dev_tasks_complete` 物理审计代码与断言通过后，调用 `dev_tasks_archive` 归档任务单；
6. **阶段终结归档**：当阶段所有史诗级任务全部交付完成，将该阶段路线图移入 `docs/roadmap/archive/`。
