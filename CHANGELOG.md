# 更新日志 (Changelog)

本文档用于归档开发过程中已完成的重大架构演进、旧方案替换历史以及版本更新说明。
与设计说明书（只反映当前生效的设计）不同，更新日志主要用于追溯“为什么改”、“以前是怎么样的”等历史问题。

---

## [2026-09-13] 2026-09-13_fix_windows_hook_quote_wrapping.md

- **Task 1.1**: 移除 hooks.json 渲染中的多余双引号包裹并验证 Node.js 兼容性

## [2026-09-13] 2026-09-13_fix_windows_hook_quote_wrapping.md

- **Task 1.1**: 移除 hooks.json 渲染中的多余双引号包裹并验证 Node.js 兼容性
- **fix(hooks)**: 移除 hooks.json 渲染多余双引号，彻底修复 Node.js child_process.exec 语法错误崩溃
  - **双重包裹根因消除**：Antigravity IDE 基于 Node.js，执行 Hook 时底层自动使用 `cmd.exe /d /s /c "<command>"` 进行包裹。原在 Windows 平台追加的双重外层双引号 (`""...""`) 导致 cmd.exe 产生三层引号嵌套，首部被解析为空命令 `""` 并报错闪退（`文件、目录名或卷标语法不正确。`），触发 IDE Fail-Open 静默放行；
  - **跨平台命令格式归一**：彻底移除 `install.py` 与 `init_project.py` 中的 `_wrap_cmds` 逻辑，统一使用跨平台合法的 `"python" "script"` 格式；
  - **Node.js 端到端验证**：使用 Node.js 原生进程调用 `file_scope_guard.py` 测试，确认执行零报错，`force_ask` 拦截报文稳定输出。

## [2026-09-13] 2026-09-13_stage2_antigravity_community_ready.md

- **Task 1**: 消除本地绝对路径与配置模板化 (Epic 2.1)
- **Task 2**: 跨平台自适应安装引导脚本与 Pre-flight 安全预检 (Epic 2.2)
- **Task 3**: 项目配置模板去特定化与逻辑角色模型解耦 (Epic 2.3)
- **Task 4**: 社区门面资产、双语文档与发布走查 (Epic 2.4)

## [2026-09-13] 2026-09-13_upgrade_adapter_to_force_ask.md

- **Task 1.1**: 升级 AntigravityAdapter 决策契约为 force_ask 并同步单测

## [2026-09-13] 2026-09-13_upgrade_adapter_to_force_ask.md

- **Task 1.1**: 升级 AntigravityAdapter 决策契约为 force_ask 并同步单测
- **fix(adapter)**: AntigravityAdapter 升级 ask 为 force_ask，击穿 IDE 权限缓存确保第三层物理弹窗必现
  - **决策契约升级**：Antigravity IDE 的 `"ask"` 会尊重“始终允许 / Always Allow”权限缓存，导致未纳管修改可能被静默放行；升级为 `"force_ask"` 契约后，无条件强制唤起交互确认弹窗，实现真正的第三层底线物理拦截；
  - **跨宿主隔离保全**：该转换内敛封装于 `AntigravityAdapter.format_decision`，通用 CLI 与 Cursor 适配器保持各自终端拦截行为，状态机与日志事件继续维持架构纯洁性；
  - **单测全量同步**：更新 `test_adapters.py` 与 `test_hooks.py` 中 10 余处断言，83/83 项单测 100% 通过。

## [2026-09-13] 2026-09-13_fix_external_hooks_and_diagnostics.md

- **Task 1.1**: 脚手架 hooks.json 自动生成、体检健康审计增强与 Windows 引号剥离修复
- **Task 1.2**: 补齐脚手架与体检单元测试及同步文档变更

## [2026-09-13] 2026-09-13_fix_external_hooks_and_diagnostics.md

- **fix(scaffolding)**: 修复外部项目 hooks.json 缺失导致 FileGuard 失效、体检假阳性与 Windows cmd.exe /c 引号剥离导致 Hook 闪退
  - **外部项目 Hook 闭环生成**：在 `init_project.py` 中增加 `_render_hooks_json()`，为所有接入的外部业务项目在本地 `.agents/hooks.json` 生成独立的生命周期 Hook 物理文件，支持 `--force` 幂等自愈覆盖；
  - **健康体检升级 (diagnose_environment)**：增加 `has_hooks_json` 与 `hooks_json_valid` 诊断维度，全面覆盖文件缺失、JSON损坏、解释器或脚本路径不可达分支，杜绝体检假阳性；
  - **Windows cmd.exe /c 引号剥离保护**：针对 Windows 下 `cmd /c` 剥离首尾引号导致命令解析崩溃的系统性缺陷，在 `hooks.json.template` 及渲染器中对 Windows 平台命令自动包裹双引号保护 (`""{{PYTHON}}" "{{SCRIPT}}""`)；
  - **全量测试与安装器适配**：在 `scripts/install.py --project` 一键接入流程中联动注入 `--force`，并在 `test_init_project.py` 中新增 5 个专项测试用例。

## [2026-09-13] 2026-09-13_stage1_scaffolding_observability_and_migration.md

- **Task 1**: Hook 决策日志与可观测性基线 (Epic 1.5)
- **Task 2**: 配置文件版本管理、平滑升级迁移与模板项目中立化 (Epic 1.6)
- **Task 3**: 全局脚手架轻量化与环境自检优化 (Epic 1.3)

## [2026-09-13] 2026-09-11_governance_engine_and_cross_tool_adaptation.md

- **Task 1**: 三层快速旁路与物理会话锁安全审查与防御加固
- **Task 2**: 双轨管控边界判定引擎与多语言仓库启发式算法调优
- **Task 3**: 跨开发工具环境适配器抽象层设计
- **Task 4**: Git Pre-commit Guard 物理硬防线独立脚本

## [0.1.5] - 2026-09-13

### 🧹 全面移除无效 `@opus_reviewer` 提示词与 Reviewer 角色纯粹化解耦
- **移除误导性提示词**：全库彻底扫描并清理所有 `@opus_reviewer` 标签（Antigravity 平台中该类 @ 标签无模型切换实效，模型切换需用户在界面手动选定，消除误导与执行偏差）；
- **审查角色纯粹化解耦**：将所有规范、规则、技能、提示卡与 MCP 工具中的审查角色统一抽象为“架构审查模型 (Reviewer)”，审查模型完全由用户根据自身预算与环境自主选定，绝不枚举或强绑定任何具体模型版本；
- **子代理与测试对齐**：将 `agents/opus_reviewer` 重构迁移为 `agents/reviewer`，同步更新 `dev_tasks_escalate` 建议角色与 20 项全量自动化测试。

---

## [0.1.4] - 2026-09-11

### 🧠 默认双模型交接固化与审查模型角色抽象解耦 (Default Handoff & Role Decoupling)
- **架构角色解耦（去除模型版本硬编码，确立 Reviewer 抽象角色代号）**：
  - 架构本质纠偏：Reviewer 在 Quench 治理体系中并非指代某一个死板的历史版本，而是指代**“用户当前所选用于架构审查与深度推理的高阶旗舰模型”**；
  - 动态演进解耦：随着平台服务调整，模型系列名、厂家与版本号均可能发生演进。交互提示与任务交接卡中**一律呈现为“高阶架构审查模型 (Reviewer)”**，彻底消除硬编码带来的认知偏差与过期失效。
- **默认双模型交接行为固化 (`context_injector.py` & `SKILL.md`)**：
  - 核心基准纠偏：明确确立“双模型交接是默认标准流程，单模型执行仅限显式豁免”；
  - 底座守卫注入：在 `PreInvocation` 钩子中增加对未审任务（`⬜ 待确认`）的实时感知，在日常执行模型生成任务后自动注入规则，强制其默认主动呈递【Quench 任务交接卡】，彻底杜绝自作主张越俎代庖。

---

## [0.1.3] - 2026-09-11

### 🛡️ MCP 虚拟环境解析加固与任务单状态流转物理守卫 (Venv Path Fix & Task Status Guard)
- **MCP Server 虚拟环境解释器路径修复 (`mcp_config.json`)**：
  - 根因定位：此前 `mcp_config.json` 将启动命令写为系统默认 `python`，在全局 Python 未安装 `fastmcp` 依赖的环境下，Antigravity Language Server 启动 MCP 子进程静默崩溃，导致 7 大 MCP 治理工具完全失联；
  - 修复方案：将命令明确指向安装有 `fastmcp` 依赖的虚拟环境 Python 绝对路径（`D:\Work\Quench\MCP\venv\Scripts\python.exe`）；
  - 引入与部署排查沉淀：明确规范在任何下游项目引入 `quench-dev-tasks` 插件时，必须执行环境自检确保 `fastmcp` 解释器可用，彻底排除启动失联问题。
- **任务单状态机物理防线与人工审批弹窗 (`file_scope_guard.py`)**：
  - 根因定位：此前 `file_scope_guard.py` 对 `dev_tasks_dir` 目录所有 `.md` 文件完全豁免拦截，导致模型能够直接用文本替换工具将 `⬜ 待确认` 偷换为 `✅ 已确认`，绕过了双会话交接协议与人工确认；
  - 核心防线一（初始生成强制待确认）：首次生成/全量写入新任务单时，除非用户明确指示直接标记为已确认，一律强制从【⬜ 待确认】开始；检测到非待确认状态立即触发 `decision: "ask"` 物理弹窗核验；
  - 核心防线二（状态变更强授权）：不论哪一个 Agent（Flash 还是 Opus）尝试修改任务单状态（单块或多块替换），只要发生状态标记流转，立即触发 `decision: "ask"` 物理阻断，必须经由用户亲手点击【允许】方可生效。

---

## [0.1.2] - 2026-09-11

### 🔄 敏捷多批次施工与已确认任务 Opus 返工挂起机制 (Flexible Batch Pipeline & Rework Degradation)
- **已确认任务的返工挂起 (`action="rework"`)**：
  - 放宽状态机流转约束：允许 `STATUS_CONFIRMED` ➔ `STATUS_REWORK`（解决任务前期虽已确认但实际需要 Opus 深度把关返工的痛点）；
  - 在 `dev_tasks_confirm` 中正式增加 `action="rework"` 选项；
  - 任务一旦标记为 `🔄 需返工`，状态机物理阻断领单施工，强制触发 Opus 审查交接卡。
- **多任务分批施工流水线 (`dev_tasks_checkout` 定向与批次感知)**：
  - `dev_tasks_checkout` 扩展支持 `task_file` 与 `task_id` 定向领单；
  - 增加批次完工保护（Batch Finished Guard）：当当前批次已确认任务完工时，扫描剩余待确认与需返工任务，安全停机向用户汇报，严禁越权施工下一批次；
  - `dev_tasks_status` 增强输出 `confirmed_queue`、`rework_queue`、`pending_queue` 等多队列批次分布卡。
- **测试覆盖**：
  - 在 `tests/test_server_tools.py` 补充 `test_batch_and_rework_workflow` 单元测试，全套 13 项用例全部通过。

---

## [0.1.1] - 2026-09-11

### 🤝 Opus 低 Token 审查交接协议与多会话复工闭环 (Opus Handoff Protocol)
- **多会话解耦防 Token 污染规范**：
  - 在 `dev-tasks-discipline.md` 新增《Opus 审查交接与多会话复工纪律》；
  - 明确规定当任务单包含 `⬜ 待确认` 任务需要高级架构审查与指南修订时、或遇到升级时，Flash 必须**主动停下工作并展示交接卡**，严禁擅自修改业务代码；
  - 指导用户使用低成本全新会话（单次仅 ~2k Token）由 Opus 完成开发指南终审修订；
  - 建立复工确认机制：用户切回原会话输入确认后，Flash 必须重新读取任务文件并验证六大字段后方可领单。
- **MCP 核心工具增强**：
  - 增强 `dev_tasks_checkout`：当没有 `✅ 已确认` 任务但存在 `⬜ 待确认` 任务时，主动返回交接建议与操作指南；
  - 增强 `dev_tasks_escalate`：附加 `handoff_required: True` 与显式停机引导指令。
- **未来演进路线归档**：
  - 建立 `future_roadmap/` 目录并归档《基于独立 API 的全自动 Subagent 委派与代码库动态探查架构规划》。

---

## [0.1.0] - 2026-09-11

### 🧊 Quench DevTasks 插件全量基础建设与双模型治理架构 (Plugin Core, FastMCP Tools, Hooks & Subagent)

- **Phase 1: 基础骨架与核心引擎 (Foundation Modules & State Machine Engine)**：
  - **Antigravity 插件目录骨架构建 (Task 1.1)**：
    - 依据 Antigravity Plugin 规范建立完整模块树（`server/`、`hooks/`、`rules/`、`skills/`、`agents/`、`scripts/`、`templates/`）；
    - 建立 `plugin.json`、`mcp_config.json`，并配置 `pyproject.toml` 和 `requirements.txt`（声明 `fastmcp>=2.0`、`pyyaml>=6.0`、`filelock>=3.0`）。
  - **项目配置解耦加载器与模板 (Task 1.2)**：
    - 在 `server/project_config.py` 实现 `load_project_config(workspace_root)`，从各项目根目录 `.agents/quench_stack.yaml` 读取技术栈、测试器与目录映射；
    - 在 `templates/quench_stack.yaml` 建立项目专有清单模板，实现 MCP 核心治理能力与具体项目业务逻辑的完全解耦。
  - **任务状态机引擎与多进程文件排他锁 (Task 1.3)**：
    - 在 `server/state_machine.py` 建立任务状态机核心引擎，实现 `⬜ 待确认` ➔ `✅ 已确认` ➔ `🔨 执行中` ➔ `✔️ 已完成`（支持 `🔄 需返工` 与 `⏭️ 跳过`）的严格合法流转验证；
    - 引入 `filelock.FileLock` 实现跨进程排他锁，彻底杜绝多 Subagent 或并发修改导致 Markdown 语法损坏；
    - 解决 Windows 控制台与包含不可见变体选择符（VS-16 `\ufe0f`）的 Emoji 状态（`✔️`、`⏭️`）正则匹配截断问题。
  - **任务六大字段规范 Schema 校验器 (Task 1.4)**：
    - 在 `server/schema_validator.py` 建立 `validate_task_schema()` 严格校验器；
    - 强制任务包含【涉及文件】、【缺陷根因与修改目标】、【目标签名与类型契约】、【分步改造指引】、【防御与边缘校验】、【DoD 验证命令】六大规范段落；
    - 增加代码块约束与单任务粒度预警（涉及文件 > 5 时提示拆分）。

- **Phase 2: 7 大 FastMCP 治理工具链 (FastMCP Server & Governance Toolchain)**：
  - **状态查询与提案工具 (Task 2.1)**：
    - 实现 `dev_tasks_status`：自动化扫描并统计工作区内未关闭与已完成任务，输出结构化健康度与活跃任务卡片；
    - 实现 `dev_tasks_propose`：接收任务提案，自动执行六大字段合规性校验，并原子追加或创建任务单（状态为 `⬜ 待确认`）。
  - **任务确认与领单检出工具 (Task 2.2)**：
    - 实现 `dev_tasks_confirm`：支持用户将指定任务推进为 `✅ 已确认`、`⏭️ 跳过` 或撤回为 `⬜ 待确认`；
    - 实现 `dev_tasks_checkout`：自动定位排序最靠前的 `✅ 已确认` 任务，将其原子流转为 `🔨 执行中` 并提取分步改造指引下发；严格执行单核互斥控制，已有活跃任务时阻断重复领单。
  - **任务完成与单测审计工具 (Task 2.3)**：
    - 实现 `dev_tasks_complete`：标记任务为 `✔️ 已完成`，强制要求执行模型附带 DoD 终端输出与改动说明；
    - 引入物理单测审计，若任务涉及核心逻辑修改则校验对应测试目录是否有断言增加。
  - **任务升级、归档与增量 CHANGELOG 写入 (Task 2.4)**：
    - 实现 `dev_tasks_escalate`：当模型执行受阻时主动唤醒 `opus_reviewer` 外置大脑，自动收集相关文件关键代码片段作为精准上下文；
    - 实现 `dev_tasks_archive`：当任务单全量闭环后，自动将 Markdown 文件移入 `archive/` 目录收纳；
    - 在 `server/changelog_writer.py` 实现 `append_changelog_entry`，提取完成任务的根因与目标，自动格式化并增量写入根目录 `CHANGELOG.md`。

- **Phase 3: 执行纪律守卫、工作流技能与子代理 (Discipline Hooks, Skills & Subagent)**：
  - **Hooks 物理拦截守卫与上下文注入 (Task 3.1)**：
    - 在 `hooks.json` 注册 `PreToolUse` 与 `PreInvocation` 钩子；
    - 实现 `server/hooks/file_scope_guard.py`：当模型试图修改非任务【涉及文件】白名单时物理拦截，并提取工具调用参数中的理由弹出交互确认框，实现人机协同纠偏；
    - 实现 `server/hooks/context_injector.py`：在新调用开始时自动向模型注入当前正在执行的任务 ID 与标题提醒；
    - 针对 Windows 默认控制台 GBK 编码全面注入 `sys.stdin/stdout/stderr.reconfigure(encoding="utf-8")`，杜绝 Unicode 截断与崩溃。
  - **常驻纪律 Rules 与按需技能手册 Skills (Task 3.2)**：
    - 编写 `rules/dev-tasks-discipline.md`：常驻注入模型上下文，规范审查阶段绝不碰源码、执行阶段不越界、改动必加单测；
    - 编写 `skills/dev-tasks-workflow/SKILL.md`：提供完整的会话启动协议、六大字段范例与 MCP 工具速查；
    - 编写 `skills/dev-tasks-review/SKILL.md`：明确三级质量弹性分级（防御严格、实现极简、类型宽松）与方案权衡规范。
  - **Opus 审查 Subagent 与一键初始化脚本 (Task 3.3)**：
    - 编写 `agents/opus_reviewer/agent.md`：定义外置大脑高级架构师角色，仅产出任务单、绝不碰源码；
    - 编写 `scripts/init_project.py`：支持 `python init_project.py <path> [--name <name>]`，一键为任意新项目生成 `.agents/plugins.json`、`.agents/quench_stack.yaml` 及 `docs/dev_tasks/` 目录；
    - 验证初始化幂等性，已成功为外部业务项目完成注册接入验证。

- **测试与验证保障 (Verification & DoD)**：
  - 建立 `server/tests/` 完整测试矩阵，共 12 项端到端单元测试：
    - `test_state_machine.py` (3 passed)
    - `test_schema_validator.py` (3 passed)
    - `test_server_tools.py` (1 passed)
    - `test_hooks.py` (3 passed)
    - `test_init_project.py` (2 passed)
  - 全量回归测试 100% 通过（12 passed in 3.37s）。
