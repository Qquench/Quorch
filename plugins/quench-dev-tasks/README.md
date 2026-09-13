# 🧊 quench-dev-tasks

> **Dual-Model Orchestration & Task Governance Plugin for Google Antigravity IDE**  
> 专为 Google Antigravity 设计的双模型协同与精细化任务治理插件（日常敏捷执行 + 自选高阶架构审查）。

---

## 🌟 核心特性 (Features)

1. **日常执行 (Runner) + 架构审查 (Reviewer) 双模型解耦协作**：
   - **日常执行器 (Runner)**：日常敏捷推进、领单执行与微小缺陷修复，节省高阶推理模型配额。
   - **架构审查器 (Reviewer)**：遇到重大分歧、深层架构重构或执行遇阻时，由用户自选的高阶推理模型（如 Claude 3.7 / Opus、GPT-4.5 / o3、Gemini Pro、DeepSeek R1 等）进行审查诊断并生成标准任务单。
2. **状态机强约束**：
   - 包含 `⬜ 待确认` ➔ `✅ 已确认` ➔ `🔨 执行中` ➔ `✔️ 已完成`（支持 `🔄 需返工` 与 `⏭️ 跳过`）的单向严密状态流转。
   - **单核执行原则**：全局限制同一时间仅允许一个任务处于 `🔨 执行中`。
   - **多进程文件锁保障**：防止并发或并行 Subagent 写入造成 Markdown 损坏。
3. **物理拦截层 (PreToolUse Hook Guard)**：
   - 每次模型修改代码前，物理核对修改文件是否属于当前任务的【涉及文件】白名单。
   - 超出范围时触发交互式弹窗，由模型提供修改理由并征得用户明确许可。
4. **六大字段标准化**：
   - 强制任务包含【涉及文件】、【缺陷根因与修改目标】、【目标签名与类型契约】、【分步改造指引】、【防御与边缘校验】、【DoD 验证命令】。
5. **三层灵活管控与快速旁路 (Fast-Track 3-Tier Architecture)**：
   - **Layer 1 静态白名单**：配置文件中 `allow_untracked_patterns`（宁少勿多，空单起步，按需沉淀）。
   - **Layer 2 会话级旁路**：`dev_tasks_set_bypass` 动态授权当前会话微调（样式/文档等），附带硬性失效时间（默认4小时），防止全局误触或静默失效；内置防 Agent 自主滥用拦截。
   - **Layer 3 交互决策弹窗**：未纳管改动触发 PreToolUse 钩子弹出【允许/拒绝】选择框，由用户掌控单次放行。
6. **项目通用解耦**：
   - 插件内核完全与特定业务代码解耦，仅依赖项目根目录 `.agents/quench_stack.yaml` 清单，适配任何编程语言与技术栈。

---

## 📁 目录结构 (Directory Structure)

```text
quench-dev-tasks/
├── plugin.json                 # Antigravity 插件清单
├── mcp_config.json             # MCP 服务配置
├── hooks.json                  # 生命周期拦截守卫配置
├── rules/                      # 常驻系统级规则注入
│   └── dev-tasks-discipline.md
├── skills/                     # 渐进式工作流手册
│   ├── dev-tasks-workflow/
│   └── dev-tasks-review/
├── agents/                     # 专业子代理
│   └── reviewer/
├── server/                     # FastMCP 服务端实现
│   ├── server.py               # 8 个核心治理工具
│   ├── state_machine.py        # 任务状态机引擎 + 文件锁
│   ├── schema_validator.py     # 六大字段规范校验器
│   ├── project_config.py       # 项目清单解析器
│   ├── changelog_writer.py     # CHANGELOG 归档日志同步
│   ├── hooks/                  # PreToolUse 守卫与上下文注入
│   └── tests/                  # 完整单元测试套件 (18/18 passed)
├── scripts/                    # 实用脚本
│   └── init_project.py         # 新项目一键接入脚本
└── templates/                  # 配置模板
    └── quench_stack.yaml
```

---

## 🚀 快速接入 (Quick Start)

### 1. 环境准备
```bash
cd server
python -m venv venv
# Windows:
.\venv\Scripts\pip install -r requirements.txt
# Linux/macOS:
source venv/bin/activate && pip install -r requirements.txt
```

### 2. 为你的项目接入 DevTasks
在任何需要引入任务治理的项目中运行初始化脚本：
```bash
python scripts/init_project.py /path/to/your/project --name "YourProject"
```
初始化脚本会自动完成：
- 在目标项目创建 `.agents/plugins.json`，注册插件路径。
- 生成项目专有的 `.agents/quench_stack.yaml` 配置文件。
- 创建标准任务目录 `docs/dev_tasks/`、归档目录 `archive/` 及使用说明。

---

## 🛠️ MCP 工具清单 (Tools Reference)

| 工具名称 | 描述 |
| :--- | :--- |
| `dev_tasks_status` | 查询任务状态概览、活跃会话旁路、当前执行任务与统计批次 |
| `dev_tasks_propose` | 提交新任务提案（状态为 `⬜ 待确认`），强制六大字段合规性校验 |
| `dev_tasks_confirm` | 确认任务单（支持 `confirm`, `rework`, `skip` 等多向流转） |
| `dev_tasks_checkout` | 领取任务进行开发（进入 `🔨 执行中`，单核互斥锁 + 批次完工感应） |
| `dev_tasks_complete` | 标记任务完成（进入 `✔️ 已完成`，强制要求 DoD 验证通过） |
| `dev_tasks_escalate` | 将陷入困境的任务升级委派给高阶架构模型深度审查 |
| `dev_tasks_archive` | 将已全量闭环的任务文件归档并自动同步至 CHANGELOG.md |
| `dev_tasks_set_bypass`| 用户授权的快速会话旁路工具（样式/文档等临时免检，防 Agent 私自滥用） |

---

## 📄 开源许可证 (License)

本项目采用 [MIT License](LICENSE) 开源。
