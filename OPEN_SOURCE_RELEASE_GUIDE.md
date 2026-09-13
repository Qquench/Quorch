# 🌐 Quench DevTasks 开源发布备忘录与微调指南 (Open-Source Release Guide)

> **⚠️ 状态提示**：
> 本文档为**预备备忘录（Draft / Pending Verification）**。
> 当前阶段**暂不执行发布**，待在当前业务项目（`JJW_MES`）中全流程实战跑通一到两次完整的开发与归档生命周期，积累真实使用体验与边缘 case 之后，再参照本文档进行轻量微调并推送到 GitHub。

---

## 目录
1. [开源价值主张与社区定位](#1-开源价值主张与社区定位)
2. [发布前需微调的关键清单 (Tuning Checklist)](#2-发布前需微调的关键清单-tuning-checklist)
   - [2.1 消除本地绝对路径（模板化与自适应安装）](#21-消除本地绝对路径模板化与自适应安装)
   - [2.2 跨平台（Windows / Linux / macOS）路径与环境适配](#22-跨平台windows--linux--macos路径与环境适配)
   - [2.3 项目模板去特定化（通用场景示例）](#23-项目模板去特定化通用场景示例)
   - [2.4 仓库形态与命名建议](#24-仓库形态与命名建议)
   - [2.5 GitHub 社区门面资产准备](#25-github-社区门面资产准备)
3. [自动化安装脚本设计草案 (`install.py`)](#3-自动化安装脚本设计草案-installpy)
4. [发布前纯净环境走查流程 (Pre-Flight Checklist)](#4-发布前纯净环境走查流程-pre-flight-checklist)
5. [开源许可证选型与法务合规备忘 (License Strategy: MPL-2.0)](#5-开源许可证选型与法务合规备忘-license-strategy-mpl-20)
6. [国际化与语言策略备忘 (Language & Internationalization Strategy)](#6-国际化与语言策略备忘-language--internationalization-strategy)

---

## 1. 开源价值主张与社区定位

Google Antigravity IDE 拥有极强的 Agent 编程能力，但社区开发者在实际工程实践中普遍面临四大痛点：
1. **高阶推理模型成本过高，敏捷模型容易失控**：如果全流程用高阶模型，Token 配额消耗极大；全流程用轻量模型，在复杂架构规划和重构时容易产生返工。
2. **AI 越界修改（Scope Creep）与幻觉改动**：模型经常“热心”地顺手修改了未包含在需求中的其他文件，导致难以排查的回归缺陷。
3. **缺乏严格的任务生命周期管理**：很多开发在聊天窗口中随性进行，没有可审计的任务状态流转，容易漏项、并发冲突或难以回滚。
4. **交付物缺乏可验证性 (DoD)**：模型常常口头回复“已完成”，但缺乏真实的物理测试命令与断言审计。

### 本插件的核心竞争力
- **敏捷执行 (Runner) + 架构审查 (Reviewer) 双模型解耦互补**：大幅降低高阶模型用量（90% 日常开发由轻量模型完成，仅在复杂冲突或关键架构节点一键 `dev_tasks_escalate` 升级委派给用户自选的高阶架构审查模型）。
- **PreToolUse 物理拦截层**：真正基于 Hooks 拦截范围外修改，且**弹出带模型自述理由的人机协同确认框**。
- **单核互斥状态机 + 跨进程文件锁**：确保任务单项推进，多 Subagent 协作安全。
- **六大字段标准化规范**：缺陷根因、类型契约、分步改造、防御边界与 DoD 自动化命令强校验。
- **业务领域零侵入**：纯通用引擎，通过每个项目自身的 `.agents/quench_stack.yaml` 配置清单实现多语言、多框架通用。

---

## 2. 发布前需微调的关键清单 (Tuning Checklist)

在准备将代码上传至 GitHub 之前，需要针对以下 5 个方面进行微调：

### 2.1 消除本地绝对路径（模板化与自适应安装）
* **现状分析**：
  当前为了本机即开即用，以下两个文件写死了 Windows 本地绝对路径：
  - `plugins/quench-dev-tasks/mcp_config.json`：写有 `D:\\Work\\Quench\\MCP\\venv\\Scripts\\python.exe` 和 `D:\\Work\\Quench\\MCP\\plugins\\quench-dev-tasks\\server\\server.py`。
  - `plugins/quench-dev-tasks/hooks.json`：写有上述 Python 解释器与 Hook 脚本的绝对路径。
* **微调动作**：
  1. 将它们作为模板保留：
     - 新建 `mcp_config.json.template`
     - 新建 `hooks.json.template`
  2. 模板中使用占位符，例如：`"command": "{{PYTHON_PATH}}"`，`"args": ["{{SERVER_PATH}}"]`。
  3. 提供一个极简的安装脚本 `scripts/install.py`（见第 3 节），在用户克隆后自动检测环境并生成真实的 `mcp_config.json` 和 `hooks.json`。
  4. 将生成的 `mcp_config.json` 和 `hooks.json` 加入 `.gitignore`，防止开发者无意提交本地路径。

### 2.2 跨平台（Windows / Linux / macOS）路径与环境适配
* **现状分析**：
  - Windows 环境下虚拟环境目录为 `venv\Scripts\python.exe`；
  - macOS / Linux 环境下为 `venv/bin/python`；
  - Windows 下 Antigravity Hooks 采用 `cmd /c` 执行，Unix 下采用 `sh -c` 执行。
* **微调动作**：
  1. `install.py` 安装脚本中利用 `sys.platform` 和 `sys.executable` 自动判断平台并提取正确的 Python 可执行文件路径。
  2. 检查所有路径拼接：插件内部 Python 代码已全面使用 `os.path.join`、`os.path.normpath` 和 `resolve_path()`，保持继续使用规范路径即可。
  3. **Unicode 编码**：目前已在所有 Hook 脚本及工具中显式注入了 `sys.stdin/stdout/stderr.reconfigure(encoding="utf-8")`，跨平台无乱码风险。

### 2.3 项目模板去特定化（通用场景示例）
* **现状分析**：
  当前 `templates/quench_stack.yaml` 中的 `constraints`（项目专有约束）包含了当前车间离线局域网工控系统的特有规则（如 SQLite WAL 模式、机床寄存器握手、FastAPI 静态托管等）。
* **微调动作**：
  1. 将 `templates/quench_stack.yaml` 默认预置的约束调整为通用的软件工程最佳实践：
     ```yaml
     constraints:
       - "核心逻辑修改必须配套编写单元测试，严禁直接跳过 DoD 自动化断言"
       - "修改代码时必须保留现有的架构设计注释与 docstring，严禁随意删除上下文"
       - "对外公开 API 或函数签名变更必须保持向后兼容，若有破坏性变更须提前声明"
       - "敏感凭据与环境配置严禁硬编码在代码中，必须通过环境变量或配置清单注入"
     ```
  2. 在注释中增加不同领域的示例段落供开发者参考：
     - **Web 全栈开发**（FastAPI / Spring Boot + React / Vue）
     - **CLI 命令行工具与系统运维**（Click / Cobra / Shell）
     - **云原生微服务**（gRPC / Docker / K8s）
     - **嵌入式与工控物联网**（C/C++ / Modbus / PLC）

### 2.4 仓库形态与命名建议
* **推荐发布形态**：
  以独立仓库发布插件本身，仓库根目录即对应当前的 `plugins/quench-dev-tasks/`。
* **推荐仓库名称**：
  - `quench-dev-orchestrator`（正式确定：兼顾双模型调度、任务治理与工程质感，精准表达编排调度中枢定位）
* **简介（One-liner Description）**：
  > "Dual-model orchestration & task governance engine for AI IDEs (Antigravity, Cursor, Windsurf) — Agile runner for execution, Frontier reasoning model for strategic architecture."

### 2.5 GitHub 社区门面资产准备
在开放在 GitHub 之前，补齐以下社区标准件：
- [x] **`README.md`**：已创建在插件根目录下，包含中英文功能特性、工作流架构图、MCP 工具字典、快速上手步骤。后续可补充一段 30 秒的终端/IDE 交互 GIF 或录屏。
- [x] **`LICENSE`**：已预设宽松的 MIT License。
- [x] **`.gitignore`**：已配置，过滤缓存、虚拟环境与锁文件。
- [ ] **GitHub Actions CI (`.github/workflows/ci.yml`)**：
  配置在 Ubuntu 与 Windows 双平台上，每次提交或 PR 自动运行 12 项 pytest 测试，展示 Green CI 徽章。
- [ ] **Issue & PR 模板 (`.github/ISSUE_TEMPLATE/`)**：
  配置 Bug Report 与 Feature Request 模板。

---

## 3. 自动化安装脚本设计草案 (`install.py`)

为了让从 GitHub 克隆插件的用户能在 5 秒内完成本地配置，可在插件根目录下提供如下 `install.py`：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
quench-dev-tasks 跨平台一键安装配置脚本
自动根据当前运行 Python 环境与目录位置，渲染生成 mcp_config.json 与 hooks.json
"""
import json
import os
import sys

def main():
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable

    print(f"🔧 正在配置 quench-dev-tasks 插件...")
    print(f"📁 插件路径: {plugin_dir}")
    print(f"🐍 Python 环境: {python_exe}")

    # 1. 渲染 mcp_config.json
    server_script = os.path.join(plugin_dir, "server", "server.py")
    mcp_config = {
        "mcpServers": {
            "quench-dev-tasks": {
                "command": python_exe,
                "args": [server_script]
            }
        }
    }
    mcp_config_path = os.path.join(plugin_dir, "mcp_config.json")
    with open(mcp_config_path, "w", encoding="utf-8") as f:
        json.dump(mcp_config, f, indent=2, ensure_ascii=False)
    print(f"✅ 已生成: {mcp_config_path}")

    # 2. 渲染 hooks.json
    guard_script = os.path.join(plugin_dir, "server", "hooks", "file_scope_guard.py")
    injector_script = os.path.join(plugin_dir, "server", "hooks", "context_injector.py")
    
    # 格式化命令（处理路径中的空格）
    guard_cmd = f'"{python_exe}" "{guard_script}"'
    injector_cmd = f'"{python_exe}" "{injector_script}"'

    hooks_config = {
        "quench-file-guard": {
            "PreToolUse": [
                {
                    "matcher": "replace_file_content|multi_replace_file_content|write_to_file",
                    "hooks": [
                        {
                            "type": "command",
                            "command": guard_cmd,
                            "timeout": 5
                        }
                    ]
                }
            ]
        },
        "quench-context-injector": {
            "PreInvocation": [
                {
                    "type": "command",
                    "command": injector_cmd,
                    "timeout": 5
                }
            ]
        }
    }
    hooks_config_path = os.path.join(plugin_dir, "hooks.json")
    with open(hooks_config_path, "w", encoding="utf-8") as f:
        json.dump(hooks_config, f, indent=2, ensure_ascii=False)
    print(f"✅ 已生成: {hooks_config_path}")

    print("\n🎉 插件配置成功！在你的任何项目中运行以下命令即可接入：")
    print(f'python "{os.path.join(plugin_dir, "scripts", "init_project.py")}" <你的项目根路径>')

if __name__ == "__main__":
    main()
```

---

## 4. 发布前纯净环境走查流程 (Pre-Flight Checklist)

在正式将 GitHub 仓库状态设为 **Public** 前，建议按以下标准流程执行一次“全新机器走查验证”：

1. **全新目录克隆测试**：
   - 在一个临时的空目录（或另一台电脑/虚拟机中）运行 `git clone <repo_url>`。
2. **依赖安装测试**：
   - 创建全新干净的 Python 虚拟环境：`python -m venv .venv`。
   - 安装依赖：`pip install -r server/requirements.txt`。
   - 运行自动化测试：`pytest server/tests/ -v`，确保 12 项测试 100% 通过。
3. **初始化接入测试**：
   - 运行 `python install.py`。
   - 新建一个测试项目目录：`python scripts/init_project.py /tmp/demo_app --name "DemoApp"`。
   - 检查 `DemoApp` 中生成的 `.agents/plugins.json`、`.agents/quench_stack.yaml` 及 `docs/dev_tasks/README.md` 是否完整正确。
4. **Antigravity IDE 端到端演练**：
   - 打开 Antigravity IDE，进入 `DemoApp` 工作区。
   - 确认在 IDE 中能看到插件注册的 Tools（`dev_tasks_status` 等）与 Skills（`dev-tasks-workflow` 等）。
   - 让 Flash 模型尝试触发一次 `dev_tasks_propose` 和 `dev_tasks_checkout`。
   - 尝试让模型修改非任务范围内的文件，确认**范围外拦截弹窗与原因解释正常弹出**。
   - 走查完毕后，正式公开仓库并在社区/Twitter/Reddit 等渠道进行分享。

---

## 5. 开源许可证选型与法务合规备忘 (License Strategy: MPL-2.0)

本项目选定 **MPL-2.0 (Mozilla Public License 2.0)** 作为开源许可协议：

1. **核心诉求定位**：
   - 保证自身完全法务免责（AS-IS 条款），不惹任何连带法律纠纷；
   - 欢迎开发者个人免费使用与正规商业落地；
   - 坚决杜绝“拿走源码做了微调却转为闭源独占、且不回馈社区”的寄生行为；
   - 绝不传染使用者的下游业务代码与专有 Prompt。
2. **为何弃用 MIT / AGPL 选用 MPL-2.0**：
   - **MIT / Apache 2.0**：传播阻力为 0，但防不住直接把状态机与 Hook 改名打包成闭源付费插件转卖；
   - **AGPL-3.0**：“网络调用即传染”触发大厂与中大型企业法务审计红线，阻碍开发者日常引用；
   - **MPL-2.0**：**文件级弱传染（File-level Copyleft）**。谁修改核心文件谁必须开源回馈；而外部 import、通过 MCP 协议（Stdio/SSE）调用、或作为子进程运行，绝对不传染下游业务代码，兼具专利反击与严密免责条款。

---

## 6. 国际化与语言策略备忘 (Language & Internationalization Strategy)

在面向国际开源生态发布时，本套件应遵循 **“English-First 门面 + 运行时防乱码 + 渐进式双语”** 的分层策略，切忌一刀切全盘重写：

### 6.1 门面层（GitHub 首页）：English-First
* **定位**：海外开发者（占全球技术生态与社交媒体流量核心）若打开纯中文 README，极易在一秒内关闭离开。
* **落地规范**：
  - 根目录 `README.md` 设为纯英文，顶部提供清晰的语言切换导航：`[English] | [简体中文](README_zh.md)`；
  - 保留 `README_zh.md` 完整中文文档，兼顾中文开发者阅读；
  - `CONTRIBUTING.md`、Issue 模版、PR 模版采用标准英文。

### 6.2 运行时与控制台交互（Runtime Output）：纯英文优先
* **定位**：跨平台终端乱码免疫与统一体验。
* **落地规范**：
  - `git_pre_commit_guard.py`（Git 拦截警告）、`init_project.py` 等 CLI 工具的控制台打印统一采用标准英文；
  - 彻底杜绝 Windows CMD（默认 CP936/GBK 编码）下的汉字乱码问题；
  - Hook 返回的 `reason` 字段模版支持英文优先或中英双语紧凑格式。

### 6.3 Agent 技能与规则层（Prompt & Skills）：英文技术优势
* **定位**：大模型内在机制与 Token 经济学。
* **落地规范**：
  - 现代主流大模型（Claude 3.7 / Sonnet、GPT-4o、Gemini 2.0、DeepSeek R1）在英文 System Prompt 下的指令遵循度（Instruction Following）普遍高于中文；
  - **Token 压缩比优势**：英文分词天然更紧凑，静态规则使用英文编写相比中文能**节省约 20% ~ 30% 上下文 Token 开销**；
  - 在正式开源前，提供英文版的 `skills/dev-tasks-workflow` 与 `dev-tasks-review`。

### 6.4 业务任务单与历史记录（Workspace Tasks）：自由母语
* **定位**：开发认知效率高于微小差价。
* **落地规范**：
  - 历史归档任务单（`docs/dev_tasks/archive/`）属于真实研发工单记录，保留中文原生记录，无需刻意翻译；
  - 状态机内核天然支持双语标签别名（`completed` / `✔️ 已完成`，`in_progress` / `🔨 执行中`）；
  - 开源发布时仅需在任务单模版目录提供 `template_en.md` 与 `template_zh.md`。
