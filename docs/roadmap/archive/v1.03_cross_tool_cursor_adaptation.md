# 阶段三演进路线图：以 Cursor 为切入点的跨开发工具适配
(Stage 3 Roadmap: Cross-Tool Adaptation with Cursor as Anchor)

> **目标定位**：突破对 Google Antigravity 原生 IDE 插件机制的单一依赖。以 **Cursor** 为首要切入点（并兼顾 Windsurf、Claude Code、Git CLI），构建跨工具适配抽象层，使没有 PreToolUse 钩子能力的现代 AI 编辑器用户，也能全面享受任务状态机、双模型分工与白名单物理拦截带来的工程治理红利。
> 
> **已归档状态 (Completed & Archived)**：本阶段（Stage 3）规划的全部史诗任务（Epic 3.1 ~ 3.5）已于 2026-09-13 全部交付，并通过全量 105 项自动化断言测试验证（涵盖 Cursor MCP 渲染与保护、Git Pre-commit Guard 物理链式挂载、高密度 Rules/MDC 导出器及统一 Quench CLI），正式移入归档区。后续长期演进提案请查阅 [future_roadmap/](../../../future_roadmap/README.md)。

---

## 一、 核心痛点与技术破局方案

### 1.1 客户端机制差异分析

| 治理能力维度 | Antigravity IDE | Cursor / Windsurf / Claude Code | 破局方案 |
| :--- | :---: | :---: | :--- |
| **MCP 工具协议支持** | ✔️ 原生支持 | ✔️ 原生支持 (Cursor Settings / MCP) | **直接复用 FastMCP Server**，8 个 `dev_tasks_*` 工具原生可用 |
| **写文件前拦截 (PreToolUse)** | ✔️ 原生支持 (Hooks) | ❌ 不支持写入时外部打断 | **平移拦截点**：前置靠 Cursor Rules 约束，后置靠 **Git Pre-commit Hook 物理硬拦截** |
| **人机交互决策弹窗** | ✔️ 原生 Ask Modal | ❌ 无弹窗 API | **标准终端交互**：CLI 退出码 (Exit Code 0/1) 与红字警示指引 |
| **常驻系统提示词注入** | ✔️ rules/*.md | ✔️ `.cursorrules` / `.cursor/rules/*.mdc` | **自动转换导出**：将纪律手册转换为 Cursor 原生 Rules |

### 1.2 全生态通用架构：单核多适配器模式 (Core-Adapter Architecture)

为避免因适配不同 IDE 而维护多个分叉版本，系统采用 **“单通用内核 + 差异化适配器外壳”** 架构：

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      【15% 差异接入层】不同 IDE 专属适配器                          │
│                                                                                 │
│   Antigravity            Cursor                 Windsurf          Claude Code   │
│   - plugins.json         - .cursor/mcp.json     - windsurf/mcp    - settings    │
│   - hooks.json (拦截)    - .cursorrules (规则)  - .windsurfrules  - CLAUDE.md   │
│   - 交互 Ask 弹窗        - Git Pre-commit 兜底  - CLI 退出码       - 终端交互   │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │ 标准 JSON-RPC / MCP 协议调用
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      【85% 通用内核】同一套 Python 代码 (Zero-Dep)                │
│                                                                                 │
│   1. FastMCP 服务端 (server.py: 8 个原子工具完全通用，输入输出全为标准 JSON)       │
│   2. 物理状态机引擎 (state_machine.py: Markdown 解析、合法性流转、FileLock 排他锁) │
│   3. 六大字段强校验 (schema_validator.py: 契约审计、防伪代码越界)                │
│   4. 双轨管控边界引擎 (project_config.py: 识别生产代码 vs 免管文档)              │
│   5. 增量 CHANGELOG 写入器 (changelog_writer.py)                                │
│   6. Git 物理审计 (基于项目自身的 git status / git diff 审计单测变更)           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### 架构核心决断：
1. **坚决不搞分支分叉 (Zero-Fork Principle)**：
   核心状态机与 MCP 服务端 100% 共享，拒绝为不同 IDE 维护不同代码分支。
2. **通过安装脚手架实现多外壳渲染**：
   通过 `init_project.py --ide cursor|antigravity|all`，一行命令为项目生成对应 IDE 的配置与规则文件。
3. **团队异构协同红利 (Team Heterogeneity)**：
   架构师使用 Antigravity 进行任务拆解与 Opus 深度审查；前端开发使用 Cursor 领单施工与高速补全。两者操作同一份 Git 仓库中的 `docs/dev_tasks/`，共享同一份状态机与任务生命周期，实现跨工具无缝协作。
4. **生命周期分离原则 (Lifecycle Separation)**（架构审查新增）：
   "环境检测"（`EnvironmentDetector`，一次性，Server 启动时执行并缓存结果）与"决策格式化"（`EnvironmentAdapter`，高频，每次 Hook 拦截时调用）必须分离为独立组件，避免每次拦截都重新做环境探测。
5. **跨机器协同的乐观锁补充防线**（架构审查新增）：
   当前 `FileLock` 为本地 OS 级文件锁，对单机多进程有效但对跨网络 Git worktree 无效。文档中必须明确声明此适用边界；对于多机协同场景，建议引入 Git 层面的乐观锁机制（在任务文件中嵌入 `last_modified_hash`，transition 前校验文件 SHA 是否一致）。

### 1.3 Cursor 治理“三板斧”与物理兜底防线

针对 Cursor 缺少写文件实时拦截能力的现实，采用分层防线实现等价闭环：

```
                     ┌──────────────────────────────────────────────┐
                     │              Cursor IDE 客户端               │
                     └──────┬────────────────────────────────┬──────┘
                            │                                │ 
       1. 软性行为规范       │                                │ 2. 标准 MCP 协议调用
      (.cursor/rules/*.mdc) │                                │
                            ▼                                ▼
      ┌───────────────────────────────┐    ┌───────────────────────────────────┐
      │     Cursor Rules 纪律注入     │    │       Quench MCP Server 工具链     │
      │ - 领单前严禁触碰业务代码      │    │ - dev_tasks_status / checkout     │
      │ - 严格按【涉及文件】白名单修改│    │ - dev_tasks_complete / archive    │
      │ - 改动业务逻辑必加单测断言    │    └─────────────────┬─────────────────┘
      └───────────────────────────────┘                      │
                                                             │ 3. 记录任务状态与涉及文件
                                                             ▼
                            ┌──────────────────────────────────────────────────┐
                            │       物理防线：Git Pre-commit Hook 守护脚本      │
                            │ (在 git commit 时校验修改文件是否超出任务单范围)  │
                            └──────────────────────────────────────────────────┘
```

---

## 二、 史诗级任务拆解 (Epics & Tasks)

### Epic 3.1: 抽象适配器架构层 (对应当前活跃任务 3)
- **背景**：使治理引擎不再直接写死 Antigravity 报文格式，支持灵活扩展不同客户端。
- **任务项**：
  - [x] 在 `plugins/quench-dev-tasks/server/` 下新建 `adapters/` 目录与 `__init__.py` 包标识文件；
  - [x] 编写 `adapters/base_adapter.py`，定义分离的双层抽象（架构审查改进）：
    - `EnvironmentDetector`（静态类）：`detect(context) -> EnvironmentType`，一次性检测并缓存结果；
    - `EnvironmentAdapter`（抽象基类）：`extract_session_id`、`format_decision`、`supports_interactive_ask`；
  - [x] 实现 `adapters/antigravity_adapter.py`：继承并封装现有的 JSON Payload 与 Ask Modal 输出；
  - [x] 实现 `adapters/cursor_adapter.py`：针对 Cursor `.cursor/mcp.json` 配置格式与终端文本输出；
  - [x] 实现 `adapters/generic_cli_adapter.py`（架构审查改进，从原 `cursor_claude_adapter.py` 拆分）：适用于 Claude Code、Windsurf、裸 Git CLI 等通用终端场景，支持标准退出码。

### Epic 3.2: Cursor 一键配置与 MCP 接入支持
- **背景**：降低 Cursor 用户的配置门槛。
- **任务项**：
  - [x] 在 `scripts/init_project.py` 中新增 `--cursor` 选项；
  - [x] 自动在目标项目根目录下生成或更新 Cursor MCP 配置文件：
    - `.cursor/mcp.json`（自动注册 `quench-dev-tasks` 命令）；
  - [x] 验证 Cursor 内置 Agent 对 `dev_tasks_status`、`dev_tasks_checkout` 等工具的调用与参数回传稳定性。

### Epic 3.3: 自动生成 `.cursorrules` 与 MDC 规范文件
- **背景**：将常驻纪律手册注入 Cursor 的系统 Prompt 中。
- **任务项**：
  - [x] 编写规则转换器：将 `rules/dev-tasks-discipline.md` 提取并精简为适合 Cursor 上下文的 Prompt；
  - [x] 在项目初始化时自动输出：
    - `.cursorrules`（兼容旧版 Cursor）；
    - `.cursor/rules/quench-dev-tasks.mdc`（兼容最新版 Cursor MDC 规范，设置 `alwaysApply: true`）；
  - [x] 明确指引 Cursor Agent：未检出任务前严禁写生产代码，涉及文件超出时主动提醒开发者。

### Epic 3.4: 物理硬防线——Git Pre-commit Hook 守护脚本
- **背景**：在无 PreToolUse 的环境下，将物理拦截防线平移至代码提交点。
- **任务项**：
  - [x] 编写轻量独立守卫脚本 `scripts/git_pre_commit_guard.py`（**零依赖约束**（架构审查新增）：仅使用 Python 标准库，严禁导入 FastMCP、filelock 或任何第三方库，确保在任意 Python 3.7+ 环境下无需安装即可运行）；
  - [x] 支持通过 `python git_pre_commit_guard.py --install [project_path]` 一键安装至目标项目的 `.git/hooks/pre-commit`；
  - [x] 核心拦截逻辑：
    1. 通过 `git rev-parse --show-toplevel` 定位工作区根目录；
    2. 直接解析 `docs/dev_tasks/*.md` 文件查找 `🔨 执行中` 的任务单（不依赖 MCP Server）；
    3. 执行 `git diff --cached --name-only` 获取本次待提交文件；
    4. 校验是否有超出任务单【涉及文件】白名单的代码文件（自动排除文档/素材类文件）；
    5. 若存在越界改动或处于未检出状态，直接 `exit 1` 阻断提交，并打印红字告警与整改指引；
    6. 校验若修改了核心逻辑，是否配套提交了测试目录变更；
  - [x] **双拦截避免逻辑**（架构审查新增）：检测 `.agents/plugins.json` 是否存在且包含 `quench-dev-tasks` 插件注册（表明 Antigravity IDE 已接管拦截），若是则降级为 warning-only 模式（打印但不 `exit 1`），将拦截权交给更早生效的 PreToolUse Hook；
  - [x] 编写 `test_pre_commit_guard.py` 验证 Pre-commit 拦截、豁免与双拦截降级逻辑。

### Epic 3.5: 开发者友好 CLI 命令行工具 (Quench CLI)
- **背景**：让不打开 AI 窗口的人类开发者也能在终端中方便地巡检与流转任务。
- **任务项**：
  - [x] 提供统一 CLI 入口（例如 `python -m quench` 或控制台脚本 `quench`）：
    - `quench status`：终端富文本展示当前任务分布与活跃队列；
    - `quench init <path> [--cursor]`：快速初始化项目；
    - `quench check`：手动运行边界与白名单自检；
    - `quench archive`：手动触发归档流程。


---

## 三、 DoD 验收标准 (Definition of Done)

1. **Cursor 实战体验**：在 Cursor 中打开接入项目，配置 MCP 后，Cursor Composer/Agent 能自主调取 `dev_tasks_*` 工具按部就班领单；
2. **Git Hook 物理防线**：在 Cursor 中故意修改非任务涉及的源码并执行 `git commit`，被 Git Pre-commit Hook 100% 成功拦截并打印友好的纠偏指引；
3. **适配器测试覆盖**：`test_adapters.py` 覆盖 Antigravity、Cursor 及 Generic CLI 三种模式的模拟行为，全部通过；
4. **双拦截避免**（架构审查新增）：在 Antigravity IDE 环境下安装 Git Pre-commit Guard，验证 Guard 自动降级为 warning-only 模式而非 `exit 1` 硬阻断；
5. **跨机器协同文档**（架构审查新增）：在适配器文档或 README 中明确声明 FileLock 的适用边界为"单机多进程"，并提供乐观锁备选方案指引。
