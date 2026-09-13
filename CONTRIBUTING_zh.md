# Quench Dev-Orchestrator (`quorch`) 贡献指南

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING_zh.md)

感谢您对 **Quench Dev-Orchestrator** 的关注与贡献！我们欢迎各类缺陷修复（Bug Fixes）、新功能特性（Features）、文档改进以及前沿架构建议。

---

## 🏗️ 本地开发环境配置

### 前置条件
- **Python**：版本 `>= 3.11`。
- **Git**：已安装并配置在系统 PATH 中。
- **FastMCP**：`>= 2.0`（通过 `install.py` 或 `requirements.txt` 自动安装）。

### 本地初始化步骤
1. Fork 并克隆代码仓库：
   ```bash
   git clone https://github.com/your-username/quorch.git
   cd quorch
   ```
2. 创建并激活虚拟环境：
   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate

   # macOS / Linux
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. 运行安装脚本自动渲染本地配置文件：
   ```bash
   python scripts/install.py
   ```
4. 执行全量测试套件验证环境可用性：
   ```bash
   # Windows (PowerShell)
   $env:PYTHONPATH="plugins/quench-dev-tasks/server"; python -m pytest plugins/quench-dev-tasks/server/tests -v

   # macOS / Linux (bash)
   PYTHONPATH="plugins/quench-dev-tasks/server" python -m pytest plugins/quench-dev-tasks/server/tests -v
   ```

---

## 📐 工程开发准则

### 1. 六大核心字段任务单标准
所有非细微的代码改动，均应按照 Quench 标准 DevTask 结构进行拆解与执行，包含六大核心字段：
- **涉及文件**（`【涉及文件】`）：明确的文件白名单，带 `[MODIFY]`、`[NEW]`、`[DELETE]`、`[RENAME]` 标识。
- **缺陷根因与修改目标**（`【缺陷根因与修改目标】`）：清晰说明为什么改、改完达到什么预期。
- **目标签名与类型契约**（`【目标签名与类型契约】`）：函数/类的方法签名与返回类型。
- **分步改造指引**（`【分步改造指引】`）：严格顺序的编号执行步骤。
- **防御与边缘校验**（`【防御与边缘校验】`）：并发控制、非法边界与容错兜底机制。
- **DoD 验证命令**（`【DoD 验证命令】`）：可直接执行且必须全部通过的自动化测试命令。

### 2. 测试驱动开发 (TDD)
- **零回归**：全量 105+ 项单元测试必须保持 100% 绿灯。
- **断言覆盖**：任何缺陷修复或新特性必须在 `plugins/quench-dev-tasks/server/tests/` 中配套新增测试用例与明确断言。
- **杜绝硬编码本地绝对路径**：严禁提交包含个人电脑绝对路径的代码（如 `C:\Users\...` 或 `D:\Work\...`），统一通过 `os.path.dirname(os.path.abspath(__file__))` 动态拼接。

### 3. 跨平台兼容性
- 保证所有脚本与终端命令均能在 Windows、macOS 和 Linux 上顺畅运行。
- 在标准输入/输出流中配置 UTF-8 编码（`sys.stdout.reconfigure(encoding="utf-8")`），防止 Windows CP936/GBK 编码解析冲突。
- 命令行中引用文件路径时应包裹双引号，支持包含空格的目录路径。

---

## 🚀 Pull Request 提交流程

1. 从 `master` 创建具有描述性的功能分支：
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. 按照工程规范编写代码并追加单元测试。
3. 运行 Pre-flight 预检与全量单测：
   ```bash
   python scripts/install.py --preflight
   $env:PYTHONPATH="plugins/quench-dev-tasks/server"; python -m pytest plugins/quench-dev-tasks/server/tests -v
   ```
4. 按照 Conventional Commits 规范提交代码（例如：`feat(engine): add ...`、`fix(guard): handle ...`、`docs: update ...`）。
5. 推送到您的 Fork 仓库，向主仓库的 `master` 分支发起 Pull Request。
