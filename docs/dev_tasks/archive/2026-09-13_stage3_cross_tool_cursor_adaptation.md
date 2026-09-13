# 2026-09-13_stage3_cross_tool_cursor_adaptation 开发任务单

> **执行模型须知**
> - 严格按照每条任务的【分步改造指引】顺序执行
> - 不得修改任务未涉及的文件
> - 保留所有现有注释和文档字符串（除非明确要求修改）
> - **改逻辑必加单测断言**：在测试目录追加断言，杜绝回归
> - 每完成一条任务，更新其状态为 `🔨 执行中`，完成后更新为 `✔️ 已完成`

- **创建日期**：2026-09-13

---

## 任务清单与状态

### 任务 1 ✔️ 已完成 — Cursor MCP 一键配置接入与 Git Pre-commit Guard 自动化安装集成

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/scripts/init_project.py
[MODIFY] scripts/install.py
[NEW] plugins/quench-dev-tasks/server/tests/test_cursor_init.py
```

#### 【缺陷根因与修改目标】
```
根因：当前 init_project.py 仅生成 Antigravity 所需的 .agents/hooks.json 与 plugins.json，Cursor 用户无法一键开箱即用；且已实现的 git_pre_commit_guard.py 守卫脚本尚未接入脚手架安装流程，缺乏自动挂载能力。
目标：在 init_project.py 和 install.py 中新增 --ide {antigravity,cursor,all}（兼容 --cursor 别名）及 --install-git-hook 选项，自动生成规范的 .cursor/mcp.json 并将 Git Pre-commit Guard 注入目标项目的 .git/hooks/pre-commit。
```

#### 【目标签名与类型契约】
```
1. generate_cursor_mcp_config(project_root: str, python_exe: str, force: bool = False) -> str: 生成或安全合并 .cursor/mcp.json，返回写入路径。
2. install_git_pre_commit_hook(project_root: str, force: bool = False) -> bool: 将 git_pre_commit_guard.py 部署至 .git/hooks/pre-commit 并赋予可执行权限。
```

#### 【分步改造指引】
1. 在 init_project.py 中实现 generate_cursor_mcp_config，支持注册 quench-dev-tasks FastMCP 服务，采用 JSON 合并策略保留用户现有其他 MCP 工具。
2. 在 init_project.py 中实现 install_git_pre_commit_hook，调用 git_pre_commit_guard.py 的安装逻辑挂载到 .git/hooks/pre-commit。
3. 在 init_project.py 与 install.py 的 argparse 中扩展 --ide (antigravity/cursor/all) 与 --install-git-hook 参数。
4. 编写 test_cursor_init.py 验证 Cursor MCP 配置渲染格式、Windows 路径转义正确性、已有 MCP 配置合并机制与 Git Hook 挂载流程。

#### 【防御与边缘校验】
- Windows 路径安全转义：生成 .cursor/mcp.json 时使用 json 安全转义，防止 Windows 反斜杠破坏 JSON 结构。
- 已有 MCP 配置保护：目标已有 .cursor/mcp.json 时，解析后仅更新或追加 mcpServers['quench-dev-tasks']，严禁直接抹除其他工具配置。
- 非 Git 仓库容错：若未初始化 .git 目录，友好提示警告并跳过 Hook 安装，严禁进程崩溃。
- 已有 Hook 链式追加：若目标 .git/hooks/pre-commit 已存在用户自定义脚本（如 lint-staged、husky 等），采用链式追加策略（在现有脚本尾部注入对 guard 的调用）而非直接替换，保护用户既有 Hook 工作流。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_cursor_init.py -v
```

---

### 任务 2 ✔️ 已完成 — Cursor Rules 规则转换器与 MDC 规范文件自动生成

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/scripts/rules_exporter.py
[MODIFY] plugins/quench-dev-tasks/scripts/init_project.py
[NEW] plugins/quench-dev-tasks/server/tests/test_rules_exporter.py
```

#### 【缺陷根因与修改目标】
```
根因：Cursor 无法直接识别 Antigravity 的 rules/*.md 规则，缺乏对 Agent 的常驻系统 Prompt 纪律约束（未检出严禁写代码、严格遵守涉及文件白名单等），开发者手动维护易造成规则同步滞后与遗漏。
目标：编写 rules_exporter.py 规则提取转换器，从 rules/dev-tasks-discipline.md 动态提取核心纪律并输出为兼容旧版 Cursor 的 .cursorrules 与兼容最新 Cursor MDC 规范的 .cursor/rules/quench-dev-tasks.mdc。
```

#### 【目标签名与类型契约】
```
1. class RulesExporter:
    @staticmethod
    def export_cursorrules(discipline_path: str, output_path: str) -> str
    @staticmethod
    def export_cursor_mdc(discipline_path: str, output_path: str) -> str
2. rules_exporter.py CLI: python rules_exporter.py --dest <project_root>
```

#### 【分步改造指引】
1. 新建 plugins/quench-dev-tasks/scripts/rules_exporter.py，编写规则提取与 MDC Frontmatter 构造逻辑。
2. 实现精炼 Prompt 提取器，将 17KB 的详细纪律提炼为高密度的 Cursor Agent 强约束指令（领单前严禁改代码、改动必附单测等）。
3. 在 init_project.py 初始化 Cursor 模式时，自动调用 rules_exporter 输出 .cursorrules 与 .cursor/rules/quench-dev-tasks.mdc。
4. 编写 test_rules_exporter.py，验证 MDC Frontmatter 格式（description、globs、alwaysApply: true）及提取内容的完整性。

#### 【防御与边缘校验】
- 源文件缺失回退：若 dev-tasks-discipline.md 文件路径不可达，启用内置的预设规范模板作为兜底保障。
- 目录不存在防御：生成 .cursor/rules/*.mdc 时递归创建父级目录。
- 覆盖保护：默认检测存在则跳过，支持 --force 覆盖，并在规则文件中标注自动生成水印与 Quench 版本号。
- 路径可移植性：discipline_path 输入支持相对路径解析（相对于 plugin 安装位置），确保不同用户机器上 quorch 安装路径差异不影响正确定位源规则文件。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_rules_exporter.py -v
```

---

### 任务 3 ✔️ 已完成 — 统一轻量 Quench CLI 命令行工具与跨工具流转集成

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/server/cli.py
[MODIFY] plugins/quench-dev-tasks/server/pyproject.toml
[NEW] plugins/quench-dev-tasks/server/tests/test_cli.py
```

#### 【缺陷根因与修改目标】
```
根因：在 Cursor、Windsurf 或纯终端工作流下，开发者缺少便捷的非 AI 交互入口，无法一键巡检当前任务状态或进行手动自检与归档。
目标：提供轻量零外部依赖的统一 CLI 模块 plugins/quench-dev-tasks/server/cli.py，支持 status、check、init、archive 等核心子命令，并在 pyproject.toml 中注册控制台入口。
```

#### 【目标签名与类型契约】
```
1. def main(argv: Optional[List[str]] = None) -> int: CLI 统一主入口，返回退出码。
2. def cmd_status(workspace_root: str, plain: bool = False) -> int: 终端渲染任务看板。
3. def cmd_check(workspace_root: str) -> int: 运行环境与治理状态体检。
4. def cmd_init(project_root: str, ide: str = "antigravity", install_hook: bool = False) -> int: 薄封装 init_project.py，支持 --ide 与 --install-git-hook 透传。
5. def cmd_archive(workspace_root: str, yes: bool = False) -> int: 执行已完成任务归档。
```

#### 【分步改造指引】
1. 编写 plugins/quench-dev-tasks/server/cli.py，设计直观的命令行参数解析器与格式化输出模块。
2. 对接 state_machine.py 与 project_config.py，实现 status 任务看板与 check 健康体检命令。
3. 实现 init 子命令，作为 init_project.py 的薄 CLI 封装，透传 --ide 与 --install-git-hook 参数（复用已有逻辑，不重复实现）。
4. 对接 server.py 中的 dev_tasks_archive 逻辑，实现终端一键归档并输出变更日志提示。
5. 在 server/pyproject.toml 中添加 project.scripts 控制台入口点 'quench = quench_dev_tasks_server.cli:main'。
6. 编写 test_cli.py 验证 status/check/init/archive 各子命令解析、ANSI 降级、异常捕获与退出码。

#### 【防御与边缘校验】
- 终端颜色自适应：检测终端是否支持 ANSI Color (如 NO_COLOR 环境变量或非 TTY 管道)，不支持时自动降级为纯文本输出。
- 异常防护：所有子命令内部包裹安全异常捕获，打印友好报错信息并退出码设为 1，严禁向终端暴露原始 Traceback。
- 参数校验：对未知子命令或错误参数提供标准帮助说明与示例。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_cli.py -v
```

---

## 附录 A：架构审查知情风险备忘

> **审查日期**：2026-09-13 | **审查者**：Quench Reviewer

1. **governance_scope 未覆盖 scripts/ 目录**：当前 `.agents/quench_stack.yaml` 的 `managed_paths` 未包含 `plugins/quench-dev-tasks/scripts/**` 和 `scripts/**`，导致任务 1、2 的核心涉及文件落在 unmanaged 区域（PreToolUse Hook 天然豁免放行）。执行器在 Antigravity IDE 环境下修改这些文件不会触发白名单拦截——这在当前阶段可接受（scripts 属于基础设施脚本而非核心业务逻辑），但建议在后续迭代中评估是否需要扩展 governance_scope。

2. **Cursor 环境变量稳定性**：`base_adapter.py` 使用 `CURSOR_PROJECT_DIR` / `CURSOR_VERSION` 环境变量探测 Cursor 环境，需关注 Cursor 版本迭代是否会变更这些变量名。建议在适配器测试中 mock 这些环境变量，确保检测逻辑的可验证性。

3. **CLI init 子命令为薄封装**：任务 3 新增的 `cmd_init` 应严格复用 `init_project.py` 的既有逻辑（通过函数调用或 subprocess），不得在 CLI 中重复实现初始化流程，以维护 Single Source of Truth。
