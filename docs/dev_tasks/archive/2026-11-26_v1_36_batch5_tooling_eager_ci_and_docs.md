# 2026-11-26_v1_36_batch5_tooling_eager_ci_and_docs Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-26

---

## Task List & Status / 任务清单与状态

### 任务 36.10 ✔️ 已完成 — 修复 config_sync 16 个 Eager 工具同步、init_project 只读诊断与 CLI/门禁脚本加固

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/scripts/config_sync.py
[MODIFY] plugins/quench-dev-tasks/scripts/init_project.py
[MODIFY] plugins/quench-dev-tasks/scripts/quench-init.ps1
[MODIFY] plugins/quench-dev-tasks/scripts/check_no_api_bypass.py
[MODIFY] plugins/quench-dev-tasks/scripts/probe_client_capabilities.py
[MODIFY] plugins/quench-dev-tasks/scripts/rules_exporter.py
[MODIFY] plugins/quench-dev-tasks/server/cli.py
[MODIFY] plugins/quench-dev-tasks/server/schema_validator.py
[MODIFY] plugins/quench-dev-tasks/server/ide_schema_export.py
[MODIFY] scripts/_introspect_schemas_child.py
[MODIFY] scripts/check_prompt_surface.py
[MODIFY] scripts/check_test_duration_baselines.py
[MODIFY] scripts/check_test_tiering_invariants.py
[MODIFY] scripts/install.py
[MODIFY] scripts/measure_tool_response_sizes.py
[MODIFY] scripts/tool_surface_snapshot.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_config_sync.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_init_project.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_no_api_bypass.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_schema_validator.py
[NEW] plugins/quench-dev-tasks/server/tests/test_v1_36_batch5_tooling_and_docs.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) mcp_config.json.template 服务键为 'core'（含 16 个 eager:true 工具），但 config_sync.render_agents_mcp_config 硬编码查找 'quench-dev-tasks' 落空退化，丢失全部 16 个 eager 工具声明，且 auto_heal_configs 单源去重未同步清理残余 'core' 键；(2) init_project.py 的 diagnose_environment (--check) 调 auto_heal_configs 误删工作区刚生成的配置，Windows 下默认 posix=True 的 shlex.split 吞掉反斜杠跳过可执行性校验，Python 版本门槛仍停留在 3.8，且多处直接裸 open('w') 非原子写；(3) cli.py 中 status/archive 默认用 compact 视图易被裁掉 files 且漏拦 STATUS_CONFIRMED，reviewer debug --execute 未发真实探测；(4) schema_validator.py 软链接根目录误拒 [NEW]、dry-run 仅按 basename 豁免且忽略代码围栏/连字符 ID；(5) check_no_api_bypass.py、check_prompt_surface.py、check_test_duration_baselines.py、check_test_tiering_invariants.py、_introspect_schemas_child.py、probe_client_capabilities.py、install.py、ide_schema_export.py、quench-init.ps1 存在 AST 盲区、路径/超时/退出码缺失。目标：确保 16 个正式工具在所有挂载形态下 100% Eager 启用，并全面加固 CLI、校验器与脚手架/门禁脚本。
```

#### 【目标签名与类型契约】
```
def render_agents_mcp_config(project_root: str, python_exe: str, existing_data: Optional[dict] = None, plugin_dir: Optional[str] = None) -> dict
def atomic_write_file(target_path: str, content: str) -> None
```

#### 【分步改造指引】
1. 修复 MCP Eager 工具同步与初始化自检 (config_sync.py, init_project.py, quench-init.ps1)：(a) config_sync.render_agents_mcp_config 从模板 mcpServers 中依次查找 'quench-dev-tasks' -> 'core' -> 唯一服务项，完整保留 16 个工具的 {'eager': true} 声明写入工作区 'quench-dev-tasks' 键；auto_heal_configs 在 is_mounted=True 时同时剥离工作区 mcpServers 中的 'quench-dev-tasks' 与 'core'；atomic_write_file 先 os.path.abspath(target_path) 再取 dirname 并去掉 mkstemp(text=True)；(b) init_project.diagnose_environment 仅自愈插件目录配置 (workspace_root=None) 保持对工作区配置的纯只读诊断，shlex.split 传入 posix=(sys.platform != 'win32')，Python 最低版本检查统一升至 (3, 12)，配置写入改走 atomic_write_file；(c) quench-init.ps1 缺失脚本时 exit 1 并透传 Python 子进程 $LASTEXITCODE。
2. 修复 CLI、Schema 校验器与 Schema 导出器 (cli.py, schema_validator.py, ide_schema_export.py)：(a) cli.py 中 cmd_status 与 cmd_archive 显式调用 dev_tasks_status(ws, verbosity='full')，cmd_archive 拦截包含 STATUS_CONFIRMED 在内的所有未结状态，cmd_reviewer_debug 在 dry_run=False 且引擎可用时执行有界 client.complete 连通性探测；(b) schema_validator.py 使用 realpath + normcase 校验 [NEW] 父目录，pytest dry-run 按规范化相对路径精确匹配缺失的 [NEW] 测试文件，_parse_task_markdown_sections 支持连字符 ID、忽略代码围栏并支持无序标题定位，validate_task_schema 拒绝全空白/纯标签项，lint_task_physical_feasibility 校验无前缀路径防穿越；(c) ide_schema_export.validate_schema_doc 传入 sort_keys=True，run_cli 在 resolve() 前检查路径各段 is_reparse_point_or_symlink。
3. 加固 AST 扫描与门禁脚本：(a) check_no_api_bypass.py 仅对相对于 workspace_root 的路径判断 'tests'，按规范化相对路径（而非 basename）匹配授权出口模块，在 visit_ImportFrom 检查 f'{node.module}.{alias.name}'（拦截 from google import genai），在 visit_Call 检查关键字参数（拦截 os.getenv(key=...)），并在 test_no_api_bypass.py 新增真仓 scan_workspace_for_bypass(WORKSPACE_ROOT) 断言；(b) check_prompt_surface.py 修正 docs/architecture 快照的 repo_root = snapshot.parents[2]，提取参数纳入 posonlyargs 与 kwonlyargs，rglob 跳过 .venv/venv/.git/node_modules，围栏跟踪支持精确反引号长度与 ~~~；(c) check_test_duration_baselines.py 修正 warn_line 比较与动态 panic 判定，save_tier2_baseline 使用 mkstemp + UTC ISO 时间；(d) check_test_tiering_invariants.py 补充 subprocess timeout、清洗 PYTHONPATH/PYTHONHOME/PYTHONUSERBASE 并完整对齐 conftest 的 13 个 Tier-1 模块；(e) _introspect_schemas_child.py 在 os._exit(1) 前 flush stderr 并对未知额外工具报错；probe_client_capabilities.py 流式有限读取 SSE data 行并排空 stdio stderr；install.py 为 rollback_configuration 增加 realpath 边界校验、校验依赖/子进程返回码并升级 run_smoke_test 验证核心模块导入；rules_exporter / measure_tool_response_sizes / tool_surface_snapshot 改用原子写。
4. 在 test_v1_36_batch5_tooling_and_docs.py 及关联测试中新增 16 个 Eager 工具完整保留断言、Windows shlex 反斜杠诊断断言、from google import genai 拦截断言与 CLI/校验器边界断言。

#### 【防御与边缘校验】
- 核心红线：100% 保留 plugins/quench-dev-tasks/mcp_config.json.template 的 'core' 服务键及全部 16 个 EXPECTED_TOOL_NAMES 的 {'eager': true} 声明，且 config_sync.render_agents_mcp_config 生成的独立工作区配置必须同样完整保留这 16 个 {'eager': true} 工具条目（同时保留工作区键名 'quench-dev-tasks' 兼容 init_project.py 与 test_init_project.py）！
- diagnose_environment (--check) 必须保持对工作区 .agents/ 配置文件的纯只读无破坏性，同时保持既有 test_init_project.py 与 test_config_sync.py 全部用例 100% 通过！
- check_test_tiering_invariants.py 的 TIER1_TARGET_MODULES 必须与 conftest.TIER1_TARGET_REL_FILES 完整对齐（13 个模块），并确保 check_test_tiering_invariants.py 实跑退出码为 0！

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch5_tooling_and_docs.py plugins/quench-dev-tasks/server/tests/test_config_sync.py plugins/quench-dev-tasks/server/tests/test_init_project.py plugins/quench-dev-tasks/server/tests/test_no_api_bypass.py plugins/quench-dev-tasks/server/tests/test_schema_validator.py plugins/quench-dev-tasks/server/tests/test_draft_lint.py plugins/quench-dev-tasks/server/tests/test_ide_schema_export.py plugins/quench-dev-tasks/server/tests/test_cli.py -q --tb=short && .venv\Scripts\python.exe plugins/quench-dev-tasks/scripts/check_no_api_bypass.py && .venv\Scripts\python.exe scripts/check_test_tiering_invariants.py
```

---

### 任务 36.11 ✔️ 已完成 — 对齐配置模板/三端 AGENTS.md/架构协议文档，补齐打包依赖、CI 静态门禁与资产快照

#### 【涉及文件】
```
[MODIFY] .github/workflows/ci.yml
[MODIFY] pyproject.toml
[MODIFY] plugins/quench-dev-tasks/plugin.json
[MODIFY] plugins/quench-dev-tasks/server/pyproject.toml
[MODIFY] plugins/quench-dev-tasks/server/requirements.txt
[MODIFY] plugins/quench-dev-tasks/templates/quench_stack.yaml
[MODIFY] .agents/quench_stack.sample.yaml
[MODIFY] AGENTS.md
[MODIFY] plugins/quench-dev-tasks/rules/AGENTS.md
[MODIFY] plugins/quench-dev-tasks/templates/AGENTS.md
[MODIFY] plugins/quench-dev-tasks/rules/dev-tasks-discipline.md
[MODIFY] docs/configuration.md
[MODIFY] docs/architecture/README.md
[MODIFY] docs/architecture/over_engineering_inventory.md
[MODIFY] dev_tasks_mcp_specification.md
[MODIFY] docs/guides/external-executor-onboarding.md
[MODIFY] README.md
[MODIFY] README_zh.md
[MODIFY] CONTRIBUTING.md
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/tests/conftest.py
[MODIFY] plugins/quench-dev-tasks/server/tests/fixtures/asset_inventory_default_golden.txt
[MODIFY] plugins/quench-dev-tasks/server/tests/test_agents_md_template.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_export_ide_schemas_cli.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_daemon_launch_canary.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch5_tooling_and_docs.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) docs/configuration.md 与 dev-tasks-discipline.md 中的 audit_gate 示例使用了非法 accepted_sources (['reviewer_poll', 'refine_spec']) 与未生效字段，复制即触发 ConfigError: safety_downgrade_denied；templates/quench_stack.yaml 含未接入运行的旧配置块注释误导；(2) dev-tasks-discipline.md 六大字段标题过时，三端 AGENTS.md 漏列 INV-10；docs/architecture/README.md、dev_tasks_mcp_specification.md、external-executor-onboarding.md、README/README_zh/CONTRIBUTING 存在脚本路径、枚举值 (switch_reviewer_channel / stop_at / 状态 Emoji)、日志命名、PROVIDER_PRESETS、Python 版本与工具数漂移；(3) server/pyproject.toml 与 requirements.txt 漏声明 pydantic / anyio 及 [build-system]，根 pyproject.toml 漏注册 concurrent_moat / heavy 标记且单测残留弃用 DeepSeekClient 告警；(4) ci.yml 缺少脚本语法与前置只读门禁，test_export_ide_schemas_cli.py 直接 --write 覆盖工作区快照，test_server_daemon_launch_canary.py 锁文件名写错为 manifest.lock，conftest.py 每测试建临时目录且未隔离本地 local.yaml。目标：一次性对齐配置模板、打包依赖、CI 门禁、测试夹具与全仓文档规约，刷新架构资产清单。
```

#### 【目标签名与类型契约】
```
QUORCH_DISABLE_LOCAL_OVERRIDE: env flag for deterministic repo-root tests
INV-10 synchronized across root/rules/template AGENTS.md (<= 120 lines)
```

#### 【分步改造指引】
1. 对齐配置模板、规则与三端 AGENTS.md：(a) 修正 docs/configuration.md 与 plugins/quench-dev-tasks/rules/dev-tasks-discipline.md 中的 audit_gate 字段（on_degraded、max_tail_bytes、max_age_minutes 及合法 accepted_sources: ['reviewer_client'] / ['reviewer_client', 'host_subagent']），清理或注释化 templates/quench_stack.yaml 与 .agents/quench_stack.sample.yaml 中未接入运行期的历史死配置块使渲染加载零告警；(b) 更新 dev-tasks-discipline.md 第 2 节六大字段标题对齐 schema_validator.py；(c) 在 AGENTS.md、plugins/quench-dev-tasks/rules/AGENTS.md、plugins/quench-dev-tasks/templates/AGENTS.md 哨兵块同步增补 INV-10（标题改为 10 Rules，严格控制在 <=120 行），并在 test_agents_md_template.py 中断言 INV-1..INV-10。
2. 对齐核心架构与协议规范文档：同步修正 docs/architecture/README.md（修正 plugins/quench-dev-tasks/scripts/* 路径、补入 code_explorer.py 模块行、移除不存在的 PostToolUse、对齐外部 API 通道名与 YYYYMMDD_NNN_<slug>.log 日志路径）、dev_tasks_mcp_specification.md（对齐 switch_reviewer_channel: 'external_api'|'host_subagent'、stop_at 6 枚举、标准状态 Emoji、日志路径与 PROVIDER_PRESETS 空表说明）、docs/guides/external-executor-onboarding.md（Python 3.12+ 与 16 个工具）、README.md / README_zh.md / CONTRIBUTING.md。
3. 加固打包元数据、Pytest 零告警与测试夹具隔离：(a) 在根 pyproject.toml 与 conftest.py 注册 concurrent_moat 与 heavy 标记，将 test_handoff_protocol.py 与 test_reviewer_observability.py 中的无意弃用导入改为 ReviewerClient 消除 DeprecationWarning；(b) 在 plugins/quench-dev-tasks/server/pyproject.toml 与 requirements.txt 显式补入 pydantic>=2.0 与 anyio>=4.0，补齐 [build-system] / py-modules 并将 server/pyproject.toml 与 plugin.json 版本同步为 '1.36.0'；(c) 在 conftest.py 将全局配置隔离哨兵改为 session 级路径复用，并在 project_config.py 支持 QUORCH_DISABLE_LOCAL_OVERRIDE=1 供 conftest 默认开启（测试显式测 local.yaml 时除外或仅在 workspace_root == 真仓根目录时隔离本地私有覆盖）。
4. 加固 CI 流水线与门禁测试：在 .github/workflows/ci.yml 补充 cache-dependency-path、扩展 compileall 覆盖 scripts 与 plugins/quench-dev-tasks/scripts，并在 pytest 前新增 export_ide_schemas.py --check、check_no_api_bypass.py、check_prompt_surface.py 步骤；将 test_export_ide_schemas_cli.py 中 test_cli_write_and_check_clean 的 --write 指向 docs/architecture/.test_write_clean_cache 临时目录（finally 清理）同时对真实快照执行只读 --check；将 test_server_daemon_launch_canary.py 锁路径修正为 manifest.json.lock。
5. 执行 .venv\Scripts\python.exe scripts/asset_inventory.py --write 更新 docs/architecture/over_engineering_inventory.md，并在 test_v1_36_batch5_tooling_and_docs.py 中断言 templates/quench_stack.yaml 与 docs/configuration.md 示例配置均可被 load_project_config 零错误零告警解析。

#### 【防御与边缘校验】
- 三端 AGENTS.md（根级、plugins/.../rules/AGENTS.md、plugins/.../templates/AGENTS.md）的哨兵块必须逐字一致、均 <= 120 行且 rules/AGENTS.md 无 YAML frontmatter，100% 通过 test_agents_md_sync.py 与 test_agents_md_template.py！
- 所有文档中的 MCP 工具调用示例必须遵守 P1~P5 Prompt-Surface 契约，100% 通过 scripts/check_prompt_surface.py！
- 完成代码变更后必须运行 scripts/asset_inventory.py --write 刷新 over_engineering_inventory.md 并通过 scripts/asset_inventory.py --check 与 test_asset_inventory.py！

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe scripts/asset_inventory.py --write && .venv\Scripts\python.exe scripts/asset_inventory.py --check && .venv\Scripts\python.exe scripts/check_prompt_surface.py && .venv\Scripts\python.exe scripts/export_ide_schemas.py --check && .venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch5_tooling_and_docs.py plugins/quench-dev-tasks/server/tests/test_agents_md_sync.py plugins/quench-dev-tasks/server/tests/test_agents_md_template.py plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py plugins/quench-dev-tasks/server/tests/test_onboarding_doc_contract.py plugins/quench-dev-tasks/server/tests/test_export_ide_schemas_cli.py plugins/quench-dev-tasks/server/tests/test_server_daemon_launch_canary.py plugins/quench-dev-tasks/server/tests/test_asset_inventory.py -q --tb=short
```

---

