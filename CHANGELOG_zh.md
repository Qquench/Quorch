# 更新日志 (Changelog)

[English](CHANGELOG.md) | [简体中文](CHANGELOG_zh.md)

本文档用于归档开发过程中已完成的重大架构演进、旧方案替换历史以及版本更新说明。
与设计说明书（只反映当前生效的设计）不同，更新日志主要用于追溯“为什么改”、“以前是怎么样的”等历史问题。

---

## [2026-09-13] 2026-09-13_stage3_cross_tool_cursor_adaptation.md

- **Task 1**: Cursor MCP 一键配置接入与 Git Pre-commit Guard 自动化安装集成
- **Task 2**: Cursor Rules 规则转换器与 MDC 规范文件自动生成
- **Task 3**: 统一轻量 Quench CLI 命令行工具与跨工具流转集成
- **feat(stage3)**: 完成以 Cursor 为切入点的跨开发工具适配体系与统一轻量 Quench CLI
  - **Cursor MCP 一键接入与已有工具合并保护**：在 `init_project.py` 与 `install.py` 中增加 `--ide {antigravity,cursor,all}` 支持，自动生成/安全合并 `.cursor/mcp.json`，确保用户既有其他 MCP 服务不被覆盖；
  - **Git Pre-commit Guard 自动化链式挂载**：支持 `--install-git-hook` 自动将物理硬拦截脚本挂载至 `.git/hooks/pre-commit`，若已有自定义 Hook 自动采用链式追加注入，零依赖物理防御越界提交；
  - **Rules 导出器与 MDC 规范生成**：实现 `rules_exporter.py`，提炼纪律手册为高密度指令，自动输出 `.cursorrules` 与符合最新 Cursor MDC 规范的 `.cursor/rules/quench-dev-tasks.mdc`；
  - **统一轻量终端 CLI (Quench CLI)**：实现 `plugins/quench-dev-tasks/server/cli.py`，支持 `status` 看板、`check` 体检、`init` 初始化与 `archive` 一键归档，自适应 ANSI 彩色降级，并在 `pyproject.toml` 中注册 `quench` 控制台入口；
  - **全量测试套件 105/105 绿灯**：新增 22 个专项测试用例，全套测试 100% 通过无回归。

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
- **fix(adapter)**: AntigravityAdapter 升级 ask 为 force_ask，击穿 IDE 权限缓存确保第三层物理弹窗必现
  - **决策契约升级**：Antigravity IDE 的 `"ask"` 会尊重“始终允许 / Always Allow”权限缓存，导致未纳管修改可能被静默放行；升级为 `"force_ask"` 契约后，无条件强制唤起交互确认弹窗，实现真正的第三层底线物理拦截；
  - **跨宿主隔离保全**：该转换内敛封装于 `AntigravityAdapter.format_decision`，通用 CLI 与 Cursor 适配器保持各自终端拦截行为，状态机与日志事件继续维持架构纯洁性；
  - **单测全量同步**：更新 `test_adapters.py` 与 `test_hooks.py` 中 10 余处断言，83/83 项单测 100% 通过。

## [2026-09-13] 2026-09-13_fix_external_hooks_and_diagnostics.md

- **Task 1.1**: 脚手架 hooks.json 自动生成、体检健康审计增强与 Windows 引号剥离修复
- **Task 1.2**: 补齐脚手架与体检单元测试及同步文档变更
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
- **移除误导性提示词**：全库彻底扫描并清理所有 `@opus_reviewer` 标签；
- **审查角色纯粹化解耦**：将所有规范、规则、技能、提示卡与 MCP 工具中的审查角色统一抽象为“架构审查模型 (Reviewer)”；
- **子代理与测试对齐**：将 `agents/opus_reviewer` 重构迁移为 `agents/reviewer`，同步更新 `dev_tasks_escalate` 建议角色与全量自动化测试。

---

## [0.1.4] - 2026-09-11

### 🧠 默认双模型交接固化与审查模型角色抽象解耦 (Default Handoff & Role Decoupling)
- **架构角色解耦（去除模型版本硬编码，确立 Reviewer 抽象角色代号）**；
- **默认双模型交接行为固化 (`context_injector.py` & `SKILL.md`)**。

---

## [0.1.3] - 2026-09-11

### 🛡️ MCP 虚拟环境解析加固与任务单状态流转物理守卫 (Venv Path Fix & Task Status Guard)
- **MCP Server 虚拟环境解释器路径修复 (`mcp_config.json`)**；
- **任务单状态机物理防线与人工审批弹窗 (`file_scope_guard.py`)**。

---

## [0.1.2] - 2026-09-11

### 🔄 敏捷多批次施工与已确认任务 Opus 返工挂起机制 (Flexible Batch Pipeline & Rework Degradation)
- **已确认任务的返工挂起 (`action="rework"`)**；
- **多任务分批施工流水线 (`dev_tasks_checkout` 定向与批次感知)**。

---

## [0.1.1] - 2026-09-11

### 🤝 低 Token 审查交接协议与多会话复工闭环 (Reviewer Handoff Protocol)
- **多会话解耦防 Token 污染规范**；
- **MCP 核心工具增强**；
- **未来演进路线归档**。

---

## [0.1.0] - 2026-09-11

### 🧊 Quench DevTasks 插件全量基础建设与双模型治理架构 (Plugin Core, FastMCP Tools, Hooks & Subagent)
- **Phase 1: 基础骨架与核心引擎 (Foundation Modules & State Machine Engine)**；
- **Phase 2: 7 大 FastMCP 治理工具链 (FastMCP Server & Governance Toolchain)**；
- **Phase 3: 执行纪律守卫、工作流技能与子代理 (Discipline Hooks, Skills & Subagent)**；
- **全量测试套件 100% 通过**。
