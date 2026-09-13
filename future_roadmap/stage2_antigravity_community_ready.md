# 阶段二演进路线图：Antigravity 社区通用开箱即用与开源准备
(Stage 2 Roadmap: Antigravity Community Out-of-the-Box & Open Source Release)

> **目标定位**：将当前仓库改造为对**任何外部 Antigravity IDE 用户**均可即开即用的开源插件。彻底消除本地特定硬编码路径，支持跨平台（Windows / macOS / Linux）一键自动化配置安装，剥离特定工业私有业务约束，具备高质量社区门面与规范文档。

---

## 一、 当前基线与差距分析

- **当前现状**：
  - 拥有完善的插件清单 `plugin.json`、`mcp_config.json`、`hooks.json`、常驻规则 `rules/`、工作流指南 `skills/` 与子代理 `agents/`；
  - 编写了初始的 [OPEN_SOURCE_RELEASE_GUIDE.md](file:///d:/Work/Quench/MCP/OPEN_SOURCE_RELEASE_GUIDE.md) 作为设计备忘录；
- **核心痛点与差距**：
  1. **致命的机器绝对路径强绑定**：
     - `mcp_config.json` 硬编码了 `D:\\Work\\Quench\\MCP\\venv\\Scripts\\python.exe` 与固定插件源码路径；
     - `hooks.json` 同样硬编码了上述本机绝对路径；
     - 任何其他开发者 Clone 仓库后必因找不到路径直接崩溃；
  2. **缺少跨平台一键安装脚手架**：未提供自动探测操作系统、创建虚拟环境、安装依赖、渲染配置文件的引导脚本；
  3. **项目配置模板含私有工控业务约束**：`templates/quench_stack.yaml` 默认规则夹带 SQLite WAL、机床双寄存器、离线局域网等私有属性；
  4. **开源门面与双语/中文文档缺位**：根目录 README 需要重写，缺少架构示意动图、核心价值与常见 FAQ。

---

## 二、 史诗级任务拆解 (Epics & Tasks)

### Epic 2.1: 消除本地绝对路径与配置模板化
- **背景**：使配置文件成为动态生成的产物，源码库仅保留纯净模板。
- **任务项**：
  - [ ] 创建 `mcp_config.json.template`：
    ```json
    {
      "mcpServers": {
        "quench-dev-tasks": {
          "command": "{{PYTHON_EXECUTABLE}}",
          "args": ["{{SERVER_SCRIPT_PATH}}"]
        }
      }
    }
    ```
  - [ ] 创建 `hooks.json.template`：使用 `{{PYTHON_EXECUTABLE}}` 和 `{{HOOKS_DIR}}` 占位符；
  - [ ] 在 `.gitignore` 中追加 `plugins/quench-dev-tasks/mcp_config.json` 与 `plugins/quench-dev-tasks/hooks.json`，防止本地生成路径被误提交；
  - [ ] 改造代码中所有 `sys.path` 与相对路径计算，全面使用相对于当前脚本的动态 `os.path.dirname` 解析。

### Epic 2.2: 编写跨平台自适应安装引导脚本 (`scripts/install.py`)
- **背景**：外部用户 Clone 仓库后，通过一行命令自动完成环境搭建与配置生效。
- **任务项**：
  - [ ] 编写 `scripts/install.py`，支持跨平台（Windows / Linux / macOS）：
    - 自动识别当前执行的 Python 解释器或在当前目录自动创建 `.venv`；
    - 自动判断可执行文件路径：Windows 为 `Scripts/python.exe`，Unix 为 `bin/python`；
    - 自动安装必要运行时依赖（`fastmcp>=2.0`, `filelock>=3.0`, `pyyaml>=6.0`, `pytest`）；
    - 读取 `.template` 模板文件，替换变量并输出生效的 `mcp_config.json` 与 `hooks.json`；
    - 运行内置冒烟测试（执行 1 次状态查询和环境自检），输出安装成功卡片；
  - [ ] 支持可选参数 `--global`：将插件注册引导注入用户全局配置 `~/.gemini/config/`，或 `--project <path>` 注入特定项目。

> [!IMPORTANT]
> ### ⚠️ 关键实战联动备忘：完成路径自适应后的文件夹更名与 JJW_MES 恢复指引
> 在本阶段（Epic 2.1 与 Epic 2.2）实现 `install.py` 动态渲染与路径自适应之后，必须立即执行以下三步闭环联动：
> 1. **执行文件夹重命名**：将当前根目录 `D:\Work\Quench\MCP` 重命名为已正式选定的工程名：`D:\Work\Quench\quench-dev-orchestrator`；
> 2. **新目录下执行自愈安装**：在 `quench-dev-orchestrator` 目录下直接执行 `python scripts/install.py`，瞬间完成动态配置渲染与自检；
> 3. **★ 同步更新老项目 JJW_MES（防止插件失联）**：
>    在终端中前往 `D:\Work\JJW_MES` 根目录，执行：
>    ```powershell
>    python D:\Work\Quench\quench-dev-orchestrator\plugins\quench-dev-tasks\scripts\init_project.py "D:\Work\JJW_MES"
>    ```
>    重新刷新 `JJW_MES\.agents\plugins.json` 中的插件路径，确保现有业务项目平滑过度、完全无缝！

### Epic 2.3: 项目配置模板去特定化与模型解耦
- **背景**：消除私有工业特异性，让通用软件工程师能够直观理解。
- **任务项**：
  - [ ] 重构 `templates/quench_stack.yaml`：
    - 默认约束提炼为普适性工程原则（代码注释保护、改逻辑必加单测断言、接口向后兼容、凭据与敏感数据不硬编码）；
    - 提供不同技术栈场景的注释范例（Python Web / 前端 Vue&React / Go&Rust 微服务）；
  - [ ] 完善模型解耦：明确在文档中声明 `Opus` 与 `Flash` 为逻辑角色代号（架构师与执行器），支持用户在配置文件中映射为其环境所使用的实际模型。

### Epic 2.4: 社区门面资产与开源发布走查
- **背景**：打造专业、清晰、吸引社区贡献者的高品质开源仓库。
- **任务项**：
  - [ ] 重写根目录 [README.md](file:///d:/Work/Quench/MCP/README.md)：
    - 增加痛点陈述（AI 越界失控、Token 消耗过大、口头 DoD 缺测试）；
    - 增加核心架构 ASCII 动图/流程图；
    - 增加“30 秒快速上手”引导；
  - [ ] 完善标准开源社区资产：
    - 确认 `LICENSE`（MIT 协议完整性）；
    - 编写 `CONTRIBUTING.md`（开发与测试指引）；
    - 编写 `docs/FAQ.md`（常见报错排查：如 FastMCP 解释器找不到、GBK 编码问题）；
  - [ ] 在一台无任何旧依赖的纯净机器（或全新虚拟环境）上执行预发布走查（Pre-flight Run），确保零门槛跑通。

---

## 三、 DoD 验收标准 (Definition of Done)

1. **环境纯净度**：仓库中所有提交的跟踪文件**零包含任何本地驱动器盘符（如 `D:\` 或 `C:\`）**；
2. **跨平台一键安装**：在全新目录下运行 `git clone <repo> && python scripts/install.py`，无报错自动完成依赖安装与配置文件渲染；
3. **自动化测试**：新环境下一键运行 `pytest`，全部测试通过率 100%。
