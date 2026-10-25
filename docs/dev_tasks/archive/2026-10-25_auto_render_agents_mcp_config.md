# 2026-10-25_auto_render_agents_mcp_config Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-25

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 抽取 .agents/mcp_config.json 渲染与安全合并唯一真相源，并在 init_project 中接入与收敛 server 任务扫描

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/scripts/config_sync.py
[MODIFY] plugins/quench-dev-tasks/scripts/init_project.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_init_project.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) server.py 在解析 dev_tasks_dir 活跃任务文件时使用裸 glob 未经过 task_status.is_task_file 谓词过滤，导致 README.md 中的任务模板示例被误识别为待办任务；(2) 目标项目接入时 init_project.py 遗漏 .agents/mcp_config.json 生成，且若在 init_project 与 config_sync 各自维护一套合并逻辑将造成双真相源漂移。
目标：(1) 在 config_sync.py 抽取 render_agents_mcp_config 纯函数与 generate_agents_mcp_config 作为唯一真相源；(2) init_project.py 复用该 SSOT，在 ide in ('antigravity', 'all') 时自动生成与安全合并；(3) server.py 采用 is_task_file 过滤 dev_tasks_dir 下的任务单文件，排除 readme.md；(4) 补齐单测。
```

#### 【目标签名与类型契约】
```
1. config_sync.py: def render_agents_mcp_config(project_root: str, python_exe: str, existing_data: Optional[dict] = None) -> dict
2. config_sync.py: def generate_agents_mcp_config(project_root: str, python_exe: str, force: bool = False) -> str
3. server.py: _inject_harness_next_action 的 md_files 列表过滤排除 readme.md (对齐 is_task_file 谓词)
```

#### 【分步改造指引】
1. 在 config_sync.py 实现 render_agents_mcp_config(project_root, python_exe, existing_data=None) -> dict 纯函数与 generate_agents_mcp_config(project_root, python_exe, force=False) -> str。已有 JSON 损坏时自动生成 .bak 备份。
2. 在 init_project.py 引入并调用 config_sync.generate_agents_mcp_config，并在主流程 ide in ('antigravity', 'all') 处执行。
3. 修改 server.py: 在 _inject_harness_next_action 中将 dev_tasks_dir 文件列表通过 is_task_file(os.path.relpath(f, workspace_root)) 或 basename != 'readme.md' 进行严格过滤。
4. 在 test_autopilot_harness_baton.py 增加 test_inject_harness_next_action_ignores_readme_md 回归用例。
5. 在 test_init_project.py 增加全新生成、保留第三方 server 合并及幂等性单测。
6. 运行 DoD 命令验证通过。

#### 【防御与边缘校验】
- 纯函数与原子写入：合并逻辑保持无副作用纯函数化，落盘使用 atomic_write_file 杜绝半成品损坏
- 损坏回退与备份：解析已有 JSON 失败时自动备份为 .agents/mcp_config.json.bak 后重置重建
- 安全合并与幂等性：保留第三方 mcpServers 配置；quench-dev-tasks 内容一致且非 force 时跳过写入
- 任务文件谓词复用：server.py 复用 task_status.is_task_file 消除裸字符串正则重复 (INV-5 / §5 SSOT)

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_init_project.py plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py -k "mcp_config or ignores_readme or is_task_file" -v
```

---

### 任务 1.2 ✔️ 已完成 — 在 config_sync 中实现工作区 mcp_config 自愈，在 install.py 中固化本地配置与快照回滚，并补齐 diagnose 断言

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/scripts/config_sync.py
[MODIFY] plugins/quench-dev-tasks/scripts/init_project.py
[MODIFY] scripts/install.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_config_sync.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_install.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) config_sync.py 中 auto_heal_configs 仅探查自愈 workspace 的 hooks.json，遗漏了 workspace 的 .agents/mcp_config.json；(2) install.py 安装引导仅产出插件目录配置，未在 quorch 自身 .agents/ 目录下固化生效配置，且 preflight 快照与 rollback 回滚未覆盖 .agents/mcp_config.json；(3) diagnose_environment 体检报告检查的是插件级配置，导致目标项目缺少 .agents/mcp_config.json 时体检假阳性。
目标：(1) config_sync.auto_heal_configs 增加 workspace_root/.agents/mcp_config.json 探查与基于 render_agents_mcp_config 的安全合并自愈；(2) install.py 自动渲染 quorch/.agents/mcp_config.json 并纳入 preflight 快照与 rollback 恢复；(3) init_project.py diagnose_environment 增加对目标项目 .agents/mcp_config.json 的物理检查；(4) 补齐全量单测。
```

#### 【目标签名与类型契约】
```
1. config_sync.py: auto_heal_configs(plugin_dir, workspace_root, python_exe, quiet) 支持 ws_mcp_target
2. install.py: render_configs(plugin_dir, python_exe) 产出并同步 repo_root/.agents/mcp_config.json
3. init_project.py: diagnose_environment(project_root) 包含 has_agents_mcp_config 与 agents_mcp_config_valid 字段
```

#### 【分步改造指引】
1. 在 config_sync.auto_heal_configs 中添加 ws_mcp_target 探查逻辑，检测到缺失或滞后时调用 render_agents_mcp_config 纯函数合并并 atomic_write_file。
2. 在 scripts/install.py 的 render_configs 中检测 repo_root/.agents 目录，若存在则同步生成 repo_root/.agents/mcp_config.json；在 run_preflight 与 rollback_configuration 中纳入该文件。
3. 在 init_project.py 的 diagnose_environment 中新增 has_agents_mcp_config 与 agents_mcp_config_valid 校验，并在 print_diagnostic_report 中输出。
4. 在 test_config_sync.py 增加 test_auto_heal_workspace_mcp_config 用例。
5. 在 test_install.py 增加仓库级 mcp_config.json 生成与 rollback 恢复断言用例。
6. 运行 DoD 命令验证通过。

#### 【防御与边缘校验】
- 毫秒级性能保障：auto_heal_configs 仅执行最多 4 次 stat 探查，无网络无重型依赖
- 快照覆盖完整性：preflight 快照支持文件内容记录，并在 rollback 中准确恢复或清理未初始化的 mcp_config
- 诊断健壮性：diagnose_environment 仅做静态存在性与 JSON 合法性校验，不执行外部脚本

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_config_sync.py plugins/quench-dev-tasks/server/tests/test_install.py -v
```

---

