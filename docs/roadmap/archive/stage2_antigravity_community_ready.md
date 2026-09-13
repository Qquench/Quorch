# 阶段二演进路线图：Antigravity 社区通用开箱即用与开源准备
(Stage 2 Roadmap: Antigravity Community Out-of-the-Box & Open Source Release)

> **目标定位**：将当前仓库改造为对**任何外部 Antigravity IDE 用户**均可即开即用的开源插件。彻底消除本地特定硬编码路径，支持跨平台（Windows / macOS / Linux）一键自动化配置安装，剥离特定工业私有业务约束，具备高质量社区门面与规范文档。
> 
> **已归档状态 (Completed & Archived)**：本阶段（Stage 2）规划的全部史诗任务（Epic 2.1 ~ 2.4）已于 2026-09-13 全部开发交付完成，并通过全量 83 项自动化断言测试验证，正式移入归档区。后续任务请查阅 [阶段三路线图](./stage3_cross_tool_cursor_adaptation.md)。

---

## 一、 当前基线与差距分析

- **当前现状**：
  - 拥有完善的插件清单 `plugin.json`、`mcp_config.json`、`hooks.json`、常驻规则 `rules/`、工作流指南 `skills/` 与子代理 `agents/`；
  - 编写了初始的 `OPEN_SOURCE_RELEASE_GUIDE.md` 作为设计备忘录；
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
  - [x] 创建 `mcp_config.json.template`：
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
  - [x] 创建 `hooks.json.template`：使用 `{{PYTHON_EXECUTABLE}}`、`{{FILE_GUARD_SCRIPT_PATH}}`、`{{CONTEXT_INJECTOR_SCRIPT_PATH}}` 占位符（每个 Hook 入口由 install.py 动态计算完整路径，扩展性优于单一 `{{HOOKS_DIR}}`）；
  - [x] 在 `.gitignore` 中追加 `plugins/quench-dev-tasks/mcp_config.json` 与 `plugins/quench-dev-tasks/hooks.json`，防止本地生成路径被误提交；
  - [x] 改造代码中所有 `sys.path` 与相对路径计算，全面使用相对于当前脚本的动态 `os.path.dirname` 解析；
  - [x] **修复 `project_config.py` 错误消息硬编码路径**（架构审查新增）：`load_project_config` 的 `FileNotFoundError` 消息中硬编码了 `D:\\Work\\Quench\\MCP\\plugins\\...` 绝对路径，必须改为基于 `os.path.dirname(os.path.abspath(__file__))` 的动态拼接。

### Epic 2.2: 编写跨平台自适应安装引导脚本 (`scripts/install.py`)
- **背景**：外部用户 Clone 仓库后，通过一行命令自动完成环境搭建与配置生效。
- **任务项**：
  - [x] 编写 `scripts/install.py`，支持跨平台（Windows / Linux / macOS）：
    - 自动识别当前执行的 Python 解释器或在当前目录自动创建 `.venv`；
    - 自动判断可执行文件路径：Windows 为 `Scripts/python.exe`，Unix 为 `bin/python`；
    - 自动安装必要运行时依赖（`fastmcp>=2.0`, `filelock>=3.0`, `pyyaml>=6.0`, `pytest`）；
    - 读取 `.template` 模板文件，替换变量并输出生效的 `mcp_config.json` 与 `hooks.json`；
    - 运行内置冒烟测试（执行 1 次状态查询和环境自检），输出安装成功卡片；
  - [x] **Pre-flight 预检与回滚机制**（架构审查新增）：
    - 在安装或目录重命名前执行目录占用检测（检查是否有进程锁定当前目录或关键文件）；
    - 自动备份旧路径映射快照至 `.agents/.quench_path_backup.json`，提供 `--rollback` 参数一键恢复；
    - 在 Windows 上检查安装路径总长度是否接近 260 字符 MAX_PATH 限制，若超过 200 字符输出黄色警告；
  - [x] **配置文件版本迁移**（架构审查新增）：安装时自动检测现有 `quench_stack.yaml` 的 `schema_version`，若缺失或版本低于最新，自动补全新字段并更新版本号；
  - [x] 支持可选参数 `--global`：将插件注册引导注入用户全局配置 `~/.gemini/config/`，或 `--project <path>` 注入特定项目。

> [!IMPORTANT]
> ### ⚠️ 关键实战联动备忘：完成路径自适应后的文件夹更名与下游项目更新指引
> 在本阶段（Epic 2.1 与 Epic 2.2）实现 `install.py` 动态渲染与路径自适应之后，必须立即执行以下闭环联动：
> 0. **⚠️ Pre-flight 预检**（架构审查新增）：执行 `python scripts/install.py --preflight` 确认无进程占用目录、路径长度安全、旧配置已备份；
> 1. **执行文件夹重命名**：将旧根目录重命名为简短规范仓库名：`quorch`（即 **Qu**ench Dev **Orch**estrator 缩写，项目内部全称保持 `quench-dev-orchestrator`）；
> 2. **新目录下执行自愈安装**：在 `quorch` 目录下直接执行 `python scripts/install.py`，瞬间完成动态配置渲染与自检；
> 3. **★ 同步更新下游既有项目（防止插件失联）**：
>    在终端中前往目标项目根目录，执行：
>    ```powershell
>    python <path_to_quorch>\plugins\quench-dev-tasks\scripts\init_project.py "<path_to_project>"
>    ```
>    重新刷新目标项目 `.agents/plugins.json` 与 `.agents/hooks.json` 中的插件路径，确保现有业务项目平滑过渡、完全无缝！

### Epic 2.3: 项目配置模板去特定化与模型解耦
- **背景**：消除私有工业特异性，让通用软件工程师能够直观理解。
- **任务项**：
  - [x] 重构 `templates/quench_stack.yaml`：
    - 默认约束提炼为普适性工程原则（代码注释保护、改逻辑必加单测断言、接口向后兼容、凭据与敏感数据不硬编码）；
    - 提供不同技术栈场景的注释范例（Python Web / 前端 Vue&React / Go&Rust 微服务）；
  - [x] 完善模型解耦：明确在文档中声明 `Reviewer` 与 `Runner` 为逻辑角色代号（架构师与执行器），支持用户在配置文件中映射为其环境所使用的实际模型。

### Epic 2.4: 社区门面资产与开源发布走查
- **背景**：打造专业、清晰、吸引社区贡献者的高品质开源仓库。
- **任务项**：
  - [x] 重写根目录 [README.md](../../../README.md)：
    - 增加痛点陈述（AI 越界失控、Token 消耗过大、口头 DoD 缺测试）；
    - 增加核心架构 ASCII 动图/流程图；
    - 增加“30 秒快速上手”引导；
  - [x] 完善标准开源社区资产：
    - 确认 `LICENSE`（MPL-2.0 协议完整性）；
    - 编写 `CONTRIBUTING.md`（开发与测试指引）；
    - 编写 `docs/FAQ.md`（常见报错排查：如 FastMCP 解释器找不到、GBK 编码问题）；
  - [x] 在一台无任何旧依赖的纯净机器（或全新虚拟环境）上执行预发布走查（Pre-flight Run），确保零门槛跑通。

---

## 三、 DoD 验收标准 (Definition of Done)

1. **环境纯净度**：仓库中所有提交的跟踪文件（含代码中的错误消息字符串）**零包含任何本地驱动器盘符（如 `D:\` 或 `C:\`）**；
2. **跨平台一键安装**：在全新目录下运行 `git clone <repo> && python scripts/install.py`，无报错自动完成依赖安装与配置文件渲染；
3. **自动化测试**：新环境下一键运行 `pytest`，全部测试通过率 100%；
4. **配置版本兼容**（架构审查新增）：旧版 `quench_stack.yaml` 在安装时自动升级至最新 `schema_version`，无数据丢失；
5. **路径安全**（架构审查新增）：Pre-flight 检查通过后方可执行目录重命名操作，失败时可通过 `--rollback` 一键恢复。
