# Quench Dev-Orchestrator (`quorch`)

[English](README.md) | [简体中文](README_zh.md)

[![License: MPL-2.0](https://img.shields.io/badge/License-MPL_2.0-blue.svg)](https://opensource.org/licenses/MPL-2.0)
[![Python: >=3.11](https://img.shields.io/badge/python-3.11+-brightgreen.svg)](https://www.python.org/)
[![FastMCP: >=2.0](https://img.shields.io/badge/FastMCP-2.0+-orange.svg)](https://github.com/jlowin/fastmcp)
[![CI](https://github.com/Qquench/Quorch/actions/workflows/ci.yml/badge.svg)](https://github.com/Qquench/Quorch/actions/workflows/ci.yml)

> **面向 AI IDE（Antigravity, Cursor, Windsurf, Claude Code）的双模型编排调度与开发任务治理套件**  
> *高阶推理架构审查模型 (Reviewer) 负责全局架构设计与复杂冲突仲裁 • 敏捷执行模型 (Runner) 负责轻量实施与 DoD 自动化单测断言闭环。*

---

## 🎯 痛点背景

AI 编程助手显著提升了编码效率，但在复杂的真实工程实践中，开发者普遍面临四大核心瓶颈：

1. **旗舰推理模型的高昂成本与敏捷模型的失控返工**：全流程使用旗舰推理模型会迅速消耗配额与预算；全流程使用轻量敏捷模型则容易在复杂架构重构与边界推演时产生幻觉与返工。
2. **AI 越界修改（Scope Creep）与无意识破坏**：模型经常“顺手”修改需求范围外的无关文件，破坏已有接口契约并引入难以排查的隐蔽回归。
3. **任务生命周期缺乏可审计性**：开发往往在聊天窗口中随性进行，没有不可变状态追踪、结构化交接记录与清晰的回滚路径。
4. **口头宣称“已完成”而缺乏真实可执行的物理测试**：模型常常口头回复“已完成”，但缺乏真实的物理断言命令与自动化校验闭环。

---

## 💡 解决方案

**Quench Dev-Orchestrator (`quorch`)** 提供了开箱即用的双模型治理框架，兼具敏捷执行与严格的架构审查：

```
                  ┌─────────────────────────────────────────┐
                  │          用户需求输入 / 功能规范文档       │
                  └────────────────────┬────────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │   战略架构审查者 (Reviewer)         │
                     │  • 深度架构分析与系统性诊断          │
                     │  • 缺陷根因排查与类型契约设计        │
                     │  • 编写标准六大字段开发任务单        │
                     └─────────────────┬─────────────────┘
                                       │ 任务交接与确认 (✅ 已确认)
                                       ▼
                     ┌───────────────────────────────────┐
                     │       日常敏捷执行者 (Runner)       │
                     │  • 严格按分步改造指引顺序施工        │
                     │  • PreToolUse 物理守卫强制白名单     │
                     │  • 执行自动化 DoD 单测断言命令       │
                     └─────────────────┬─────────────────┘
                                       │
                 ┌─────────────────────┴─────────────────────┐
                 ▼                                           ▼
      [DoD 自动化测试全部通过]                      [遇到重大设计分歧 / 冲突]
                 │                                           │
                 ▼                                           ▼
         dev_tasks_complete                          dev_tasks_escalate
       (版本日志记录与阶段归档)                      (生成交接卡回传审查者)
```

### 核心特性

- **双模型逻辑角色解耦**：90% 的日常编码由轻量高敏捷模型（`Runner`）执行；高阶推理模型（`Reviewer`）仅在任务规划、架构复核与遇到重大冲突时委派介入，大幅节省旗舰算力配额。
- **PreToolUse 物理拦截层**：真正基于 Hook 拦截当前任务【涉及文件】白名单之外的修改行为，在未授权修改前弹出交互确认框，把终审权交还给开发者。
- **跨进程排他锁状态机**：基于 `filelock` 实现单核互斥状态机，严格保障同一时刻仅单任务执行，彻底杜绝多 Subagent 协作冲突与竞态。
- **六大核心字段契约**：每项任务必须明确【涉及文件】、【缺陷根因与修改目标】、【目标签名与类型契约】、【分步改造指引】、【防御与边缘校验】和【DoD 验证命令】。
- **业务领域零侵入**：纯通用治理引擎，通过每个项目根目录下的 `.agents/quench_stack.yaml` 声明自身边界与约束，适用于任何编程语言与技术栈。

---

## ⚡ 30 秒快速上手

### 1. 安装套件

克隆本仓库并运行跨平台安装引导脚本：

```bash
git clone https://github.com/your-org/quorch.git
cd quorch
python scripts/install.py
```

安装脚本将自动：
- 探测或创建 Python 虚拟环境（`.venv` 或 `venv`）；
- 校验必要运行依赖（`fastmcp`, `filelock`, `pyyaml`, `pytest`）；
- 读取 `.template` 模板文件，自动渲染生成本地生效的 `mcp_config.json` 与 `hooks.json`；
- 执行 Pre-flight 目录占用检查与路径安全审计。

### 2. 为目标项目接入 Quench 治理

在需要启用任务治理的任何项目根目录执行：

```bash
python <quorch路径>/plugins/quench-dev-tasks/scripts/init_project.py <目标项目根路径>
```

脚本将自动在目标项目中生成：
- `.agents/plugins.json`：注册 `quench-dev-tasks` 插件；
- `.agents/quench_stack.yaml`：定制项目规范约束、测试命令与边界；
- `docs/dev_tasks/`：任务生命周期流转管理工作区。

---

## 🛠️ MCP 工具字典与功能速查

`quench-dev-tasks` MCP Server 提供以下专用工具：

| 工具名称 | 核心作用 | 典型使用时机 |
| :--- | :--- | :--- |
| `dev_tasks_status` | 查询任务总览、批次排队与 Hook 审计日志 | 会话启动自检、完成里程碑后 |
| `dev_tasks_propose` | 提交符合六大字段契约的标准开发任务提案 (`⬜ 待确认`) | 架构设计或需求梳理时 |
| `dev_tasks_confirm` | 调整任务状态 (`confirm`, `rework`, `skip`, `revoke`) | 架构审查完成、准许开工前 |
| `dev_tasks_checkout` | 领单检出已确认任务，置为 `🔨 执行中` 并下发指引 | 执行模型按序或定向领取任务 |
| `dev_tasks_complete` | 提交任务完成报告并审计单测断言 (`✔️ 已完成`) | 物理执行全部 DoD 命令通过后 |
| `dev_tasks_escalate` | 升级遇到冲突的任务并生成架构审查交接卡 | 遇到方案冲突、死锁或回归缺陷时 |
| `dev_tasks_set_bypass`| 开启附带物理会话锁与过期倒计时的快速通道旁路 | 进行极轻量修补（如单点样式、错别字） |
| `dev_tasks_archive` | 归档已闭环的任务单并自动追加记录至 `CHANGELOG.md` | 当前任务单全量完成闭环后 |

## 💡 项目起源与作者手记 (Author's Note)

> **作者说明与诚挚提示**  
> 本项目源于我个人在 **Windows 环境下使用 Google Antigravity IDE** 进行日常开发时的实际工程痛点与治理需求。其底层核心状态机、治理引擎与 Antigravity 拦截链路已在本地经过充分实战跑通与验证。
> 
> 然而，针对其他开发工具（如 **Cursor**、Windsurf 等）以及跨操作系统的适配层代码，由于我个人缺乏相关的实操与开发经验，相关模块完全是由 AI Agent 基于既有架构抽象推演并生成的。虽然已编写了全量自动化单元测试（105+ 项单测覆盖），但在真实多元的生产场景下可能仍会遇到边缘缺陷或兼容性瑕疵。
> 
> 诚挚欢迎广大社区开发者提出 Issue、反馈实际使用体验或提交 PR，共同完善和加固各客户端适配层！

---

## 📖 相关文档

- 🌐 [CHANGELOG.md](CHANGELOG.md)：版本更新日志与历史架构演进记录。
- 🤝 [CONTRIBUTING.md](CONTRIBUTING.md)：开源贡献指南与本地测试规范。
- ❓ [docs/FAQ.md](docs/FAQ.md)：常见环境问题、编码乱码与 Hook 排查手册。
- 📐 [dev_tasks_mcp_specification.md](dev_tasks_mcp_specification.md)：技术架构与规范设计说明书。
- 📜 [LICENSE](LICENSE)：Mozilla Public License 2.0 (MPL-2.0)。

---

## 📄 开源许可证

本项目采用 [Mozilla Public License 2.0 (MPL-2.0)](LICENSE) 许可协议。  
对核心文件进行的修改必须保持开源回馈社区；同时允许免责、安全地进行商业集成与调用，绝不传染使用者的专有业务代码。
