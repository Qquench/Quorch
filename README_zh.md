# Quench Dev-Orchestrator (`quorch`)

[English](README.md) | [简体中文](README_zh.md)

> 💡 **文档语言政策**：本项目技术规范、配置手册与变更日志以英文为唯一权威版本 (English as SSOT)。中文 Issue 与 PR 讨论完全欢迎；如需中文查阅，可使用 LLM 辅助按需翻译。

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python: >=3.12](https://img.shields.io/badge/python-3.12+-brightgreen.svg)](https://www.python.org/)
[![FastMCP: >=2.0](https://img.shields.io/badge/FastMCP-2.0+-orange.svg)](https://github.com/jlowin/fastmcp)
[![CI](https://github.com/Qquench/Quorch/actions/workflows/ci.yml/badge.svg)](https://github.com/Qquench/Quorch/actions/workflows/ci.yml)

> **面向 AI 编程智能体的确定性物理护栏与双模治理引擎**  
> *把“防越界”和“防假完成”落到物理钩子与测试对账上，而不是靠口头叮嘱模型自觉。*

---

## 🎯 为什么需要 Quorch？

绝大多数 AI 编程助手只靠提示词纪律（例如*“请只改 `auth.py` 并跑通测试”*）。在真实复杂工程中，模型依然经常“顺手”改动无关文件、破坏旧契约，或者没写有效断言就口头宣布“已完成”。

**Quorch 通过 IDE PreToolUse 钩子与跨进程 MCP 状态机，提供三道确定性物理防线：**

1. **PreToolUse 文件作用域守卫**：将写入权限物理锁死在当前任务的【涉及文件】白名单内。越界编辑、无活跃任务下的未纳管修改、直接篡写任务单状态以及 Shell 重定向旁路，都会在落盘前被直接拦截。
2. **确定性 DoD 测试断言审计**：任务收口前，Quorch 会通过 `git diff` 物理扫描测试目录中是否真实存在新增测试断言，并校验可执行的 DoD 验证输出——没跑测试或未补断言的“假完工”会被直接拒收。
3. **双模角色解耦（`inverted` 委派模式 & `standard` 标准模式）**：
   - **`inverted`（委派模式 — 高阶主控 + 轻量子代理施工）**：在 IDE 主窗口常驻高阶推理模型把控架构与验收，将受白名单约束的编码步骤派发给同环境的轻量宿主子代理（`Runner`）执行，无需外部 API Key。
   - **`standard`（标准模式 — 敏捷主控 + 按需调高阶审查）**：在主窗口用轻量敏捷模型进行日常开发，遇到规划或复杂问题时按需调起更高阶的审查者——支持同环境的高阶 IDE 子代理、手动切模型，或选配外部旗舰 API（如 OpenAI、DeepSeek）。

---

## 🧭 什么时候该用 Quorch？

| 开发场景 | 推荐方案 | 原因 |
| :--- | :--- | :--- |
| 快速 UI 原型、一次性脚本、探索性实验 | IDE 原生对话 | 零治理开销，跑得最快 |
| 模块边界清晰、可并行拆分的独立任务（且不心疼配额） | 官方并行多代理（如原生 `swarm`） | 文件冲突少时吞吐量最高 |
| **强耦合后端、状态机、老代码重构或共享契约核心模块** | **Quorch** | **物理锁死改动范围、单任务排他防并发冲突、强制跑通真实测试断言** |

---

## ⚡ 30 秒快速上手

### 1. 安装套件

```bash
git clone https://github.com/Qquench/Quorch.git
cd quorch
python scripts/install.py
```

安装脚本会自动探测/配置 Python 虚拟环境、校验依赖（`fastmcp`、`filelock`、`pyyaml`、`pytest`），从模板渲染生成本地 `mcp_config.json` 与 `hooks.json`，并执行 Pre-flight 路径安全预检。

### 2. 为目标项目接入治理

```bash
python <quorch路径>/plugins/quench-dev-tasks/scripts/init_project.py <目标项目根路径>
```

执行后会在目标项目中生成 `.agents/plugins.json`、`.agents/quench_stack.yaml` 与 `docs/dev_tasks/`。

### 3. 一句话日常启动（无需写长提示词）

插件自带的 `AGENTS.md` 规则与 `harness_next_action` 会自动接管状态流转。日常使用时只需在对话框点一句目标模式 + 需求即可：

- **委派模式（`inverted`，零外部 Key — 首推）**：
  > *“用委派模式，帮我修复 `src/auth.py` 的登录超时问题。”*
- **标准模式（`standard` — 敏捷主控 + 按需调高阶审查，可用高阶子代理或外部 API）**：
  > *“用标准模式，重构配置加载模块。”*
- **轻量旁路（`bypass`，改文档或拼写等免任务单微调）**：
  > *“开一下 bypass，修一下 `src/cli.py` 里的拼写错误。”*

---

## 🛡️ 真实拦截记录展示

以下样本均脱敏自本仓库 [.agents/.quench_hook.log](.agents/.quench_hook.log) 中由 `file_scope_guard.py` 与 DoD 审计门禁产生的真实日志：

```text
# 1. 拦截执行中任务的范围外新增文件
2026-10-20 02:01:53 [INFO] [ASK_MODAL] decision=ask tool=write_to_file target=<repo>/plugins/quench-dev-tasks/server/path_safety_core.py
reason=[Out-of-Scope File Modification Warning / 范围外修改拦截] Active task (Task 1.1) does not include this file in its declared scope.
Agent Justification: Create path_safety_core.py for zero-dependency path safety checks
Click [Allow] if this was a planning omission; click [Reject] if unexpected.

# 2. 拦截未补测试断言的提前完工申报（DoD 审计阻断）
2026-11-11 11:27:33 [INFO] [DOD GUARD REJECTED] Task 31.1 completion blocked: governed code modified (1 files) but no test assertions found and no valid exemption.

# 3. 拦截无活跃任务时的未纳管代码修改
2026-11-11 11:09:10 [INFO] [ASK_MODAL] decision=ask tool=edit_file target=<repo>/plugins/quench-dev-tasks/server/server.py
reason=【未纳管代码修改确认 / Unmanaged Code Modification Confirmation】 No Quench task is currently in '🔨 执行中' state, and the target file did not match any fast-track whitelist or session bypass rule.
```

> 此外，任何试图通过 Shell 重定向（如 `echo ... > docs/dev_tasks/task.md`、`tee`、`Out-File`）绕过 MCP 工具篡改任务单的命令，都会被钩子直接拒绝（`[DENIED]`）。

---

## 🔍 进阶细节与架构展开（按需查阅）

<details>
<summary>🛠️ 16 个 MCP 工具完整字典（由插件规则自动引导调用）</summary>

| 分类 | 工具名称 | 核心作用 | 典型使用时机 |
| :--- | :--- | :--- | :--- |
| **任务流转与执行** | `dev_tasks_status` | 查询任务总览、批次排队（支持 `include_drafts`）、运行模式热切换与 Hook 审计日志 | 会话启动自检、完成里程碑后 |
| | `dev_tasks_propose` | 提交符合六大字段契约的标准开发任务提案 (`⬜ 待确认` 或 `📝 草案`) | 架构设计或需求梳理时 |
| | `dev_tasks_confirm` | 调整任务状态 (`confirm`, `rework`, `skip`, `revoke`) | 审查通过、准许开工前 |
| | `dev_tasks_checkout` | 领单检出已确认任务，置为 `🔨 执行中` 并下发指引 | 执行模型按序或定向领取任务 |
| | `dev_tasks_complete` | 提交任务完成报告并审计单测断言与工作区范围对账 (`✔️ 已完成`) | 物理执行全部 DoD 命令通过后 |
| | `dev_tasks_escalate` | 升级遇到冲突的任务并生成多层能力审查交接卡 | 遇到方案冲突、死锁或回归缺陷时 |
| | `dev_tasks_export_handoff_card` | 纯导出标准 Reviewer 交接卡片，不触发任何状态突变 | 需跨会话或离线人工交接审查时 |
| **租约与并发治理** | `dev_tasks_heartbeat` | 刷新当前执行中任务的活跃租约心跳，防止被回收 | 长期沉浸编码或大批量单测执行时 |
| | `dev_tasks_reclaim` | 基于 CAS 原子夺权回收异常僵死或超时失联的任务 | 多进程下抢占恢复无主任务 |
| **草案与规约强化** | `dev_tasks_refine_spec` | 基于 AST 代码探查与高阶推理强化任务规约 | 将粗粒度草案升级为可执行契约 |
| | `dev_tasks_promote_draft` | 实施物理可行性 Lint 门禁（防路径穿越、语法 dry-run）并晋升为待执行 | 将推演完毕的草案纳入待领队列 |
| **架构审查与咨询** | `dev_reviewer_submit` | 提交异步 Reviewer 推演任务，常驻后台 Worker 独立运行 | 发起耗时较长或即席的深度架构审查 |
| | `dev_reviewer_poll` | 轮询异步任务进度或结果，强约束 1KB 极简快照与结构化裁定 | 定期探查推演进展、拉取最终审查裁定 |
| | `dev_reviewer_cancel` | 确定性主动取消执行中的异步推演任务，中止模型网络传输 | 发现方案不符或需紧急刹车止损时 |
| **治理维护与旁路** | `dev_tasks_set_bypass` | 开启附带物理会话锁与过期倒计时的快速通道旁路 | 进行极轻量修补（如单点样式、错别字） |
| | `dev_tasks_archive` | 归档已闭环的任务单并自动追加记录至 `CHANGELOG.md` | 当前任务单全量完成闭环后 |

</details>

<details>
<summary>🧱 系统架构与核心能力清单</summary>

```text
用户需求 ──▶ 规约提案（六大核心字段）──▶ ✅ 已确认
                                            │
    PreToolUse 物理守卫 ◀── 🔨 执行中 ◀─────┘
             │
             ▼
    DoD 单测与 Diff 审计 ──▶ ✔️ 已完成 ──▶ CHANGELOG.md
```

- **厂商中立审查引擎 (`ReviewerClient`)**：支持同一 IDE 环境内的高阶子代理与人工切模协作，也支持通过声明式 `PROVIDER_PRESETS` 注册表按需接入 OpenAI、DeepSeek（含 Prompt Cache 感知）、通用代理及企业内网自建满血模型集群（如 `vLLM` / `Ollama` OpenAI 兼容网关），并通过 `scripts/check_no_api_bypass.py` 静态 AST 门禁确保单一出口与零厂商硬编码。
- **严格防角色扮演与结构化契约**：异步轮询非终态恒定返回 <= 1KB 的极简快照，终态裁定上限 40,000 字符；外部引擎不可用时统一输出 `findings == ""` 的显式降级卡片。
- **实时思考流落盘与 Stdio 纯净度**：思维链实时写入 `.agents/logs/reviewer/`（1024KB 硬封顶安全轮转 + 跨块流式脱敏），100% 保障 MCP `stdout` JSON-RPC 通道纯净。
- **跨进程排他锁与六字段契约**：由 `filelock`、心跳租约与工作区基线 Git diff 对账守护，每项任务均显式约束【涉及文件】、【缺陷根因与修改目标】、【目标签名与类型契约】、【分步改造指引】、【防御与边缘校验】和【DoD 验证命令】。
- **业务领域零侵入**：通过项目根目录的 `.agents/quench_stack.yaml` 声明边界与测试命令，语言与框架完全无关。

</details>

---

## 💡 项目起源与作者手记 (Author's Note)

> **作者说明与诚挚提示**  
> 本项目源于我个人在 **Windows 环境下使用 Google Antigravity IDE** 进行日常开发时的实际工程痛点与治理需求。其底层核心状态机、治理引擎与 Antigravity 拦截链路已在本地经过充分实战跑通与验证。
>
> 然而，针对其他开发工具（如 **Cursor**、Windsurf 等）以及跨操作系统的适配层代码，由于我个人缺乏相关的实操与开发经验，相关模块完全是由 AI Agent 基于既有架构抽象推演并生成的。虽然仓库内已配备完整自动化测试套件（`pytest` 共计 **1,318 项收集用例**），但在真实多元的生产场景下可能仍会遇到边缘缺陷或兼容性瑕疵。
>
> 诚挚欢迎广大社区开发者提出 Issue、反馈实际使用体验或提交 PR，共同完善和加固各客户端适配层！

---

## 📖 相关文档

- ⚙️ [docs/configuration.md](docs/configuration.md)：`quench_stack.yaml` 完整配置说明与字段手册 (English as SSOT)。
- 🏛️ [docs/architecture/](docs/architecture/README.md)：高层系统架构说明书（四层拓扑、核心不变量、模块映射表）。
- 📐 [dev_tasks_mcp_specification.md](dev_tasks_mcp_specification.md)：FastMCP 工具与协议规格说明书（工具参数、字段 Schema、返回值类型）。
- 🌐 [CHANGELOG.md](CHANGELOG.md)：版本更新日志与历史架构演进记录。
- 🤝 [CONTRIBUTING.md](CONTRIBUTING.md)：开源贡献指南与本地测试规范。
- ❓ [docs/FAQ.md](docs/FAQ.md)：常见环境问题、编码乱码、企业代理与 Hook 排查手册。
- 📜 [LICENSE](LICENSE)：Apache License 2.0 (Apache-2.0)。

---

## 📄 开源许可证

本项目采用 [Apache License 2.0 (Apache-2.0)](LICENSE) 开源许可协议。提供宽松的商用、修改与分发授权以及明确的专利授权保护，对下游专有业务代码不施加传染性限制。
