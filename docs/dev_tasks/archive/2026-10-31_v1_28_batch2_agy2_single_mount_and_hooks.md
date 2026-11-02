# 2026-10-31_v1_28_batch2_agy2_single_mount_and_hooks Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-31

---

## Task List & Status / 任务清单与状态

### 任务 28.3 ✔️ 已完成 — config_sync 单源插件去重、file_scope_guard 适配 edit_file/write_file 与单次熔断 Stop Hook

#### 【涉及文件】
```
[MODIFY] .gitignore
[MODIFY] plugins/quench-dev-tasks/scripts/config_sync.py
[MODIFY] plugins/quench-dev-tasks/hooks.json.template
[MODIFY] plugins/quench-dev-tasks/hooks.json
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/context_injector.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_config_sync.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_hooks.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) `config_sync.auto_heal_configs` 未检测 `<workspace_root>/.agents/plugins.json` 已挂载本地插件，仍在 `<workspace_root>/.agents/` 生成重复的 `mcp_config.json` 与 `hooks.json`，导致 MCP 工具翻倍注册与每次 Hook 双重执行；(2) `hooks.json.template` 的 `PreToolUse` `matcher` 与 `file_scope_guard.py` 仅适配旧版 `TargetFile` / `write_to_file` / `replace_file_content`，遗漏 `edit_file(Path, Target, Replacement)`、`write_file(Path, Content, Append, Overwrite)`、`delete_file` 与 `run_command`；(3) `context_injector.py` 尚未接入 `Stop` Hook 对 Autopilot 连续接力态的提前停机做单次熔断续跑。目标：实现 `plugins.json` 单源插件感知与冗余配置自愈剥离，补齐 `file_scope_guard.py` 对 `edit_file` / `write_file` / `run_command` 的完整拦截与 `build_post_image` 模拟，并在 `context_injector.py` 与 `hooks.json.template` 实现六重护栏单次熔断 `Stop` Hook。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/scripts/config_sync.py
def is_workspace_plugin_mounted(workspace_root: str, plugin_dir: Optional[str] = None) -> bool: ...

# plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
def build_post_image(tool_name: str, args: dict, old_content: str) -> Optional[str]: ...

# plugins/quench-dev-tasks/server/hooks/context_injector.py
def _handle_stop_event(payload: dict) -> dict: ...
```

#### 【分步改造指引】
1. 在 `.gitignore` 的 `# Quench Runtime & Session Locks` 段新增 `.agents/.quench_stop_guard.json` 与 `.agents/.quench_stop_guard.json.lock`。
2. 在 `plugins/quench-dev-tasks/scripts/config_sync.py` 新增 `is_workspace_plugin_mounted(workspace_root: str, plugin_dir: Optional[str] = None) -> bool`：读取 `<workspace_root>/.agents/plugins.json`，遍历 `entries`（跳过 `enabled is False` 的项），将 `entry["path"]` 分别相对 `workspace_root` 与 `<workspace_root>/.agents` 解析 `realpath`，若等于 `realpath(p_dir)` 或 `realpath(os.path.join(resolved_entry, os.path.basename(p_dir))) == realpath(p_dir)` 则返回 `True`。升级 `auto_heal_configs`：当 `workspace_root` 存在且 `is_workspace_plugin_mounted(workspace_root, p_dir)` 为 `True` 时，不再向 `<workspace_root>/.agents/` 生成 `hooks.json` 与 `mcp_config.json`，并检查若 `<workspace_root>/.agents/hooks.json` 含 `quench-file-guard`/`quench-context-injector` 或 `<workspace_root>/.agents/mcp_config.json` 的 `mcpServers` 含 `quench-dev-tasks`，安全剥离上述键（若剩余无其他条目则 `os.unlink` 删除文件，否则原子写回保留第三方配置，并将变动路径计入 `affected`）。
3. 更新 `plugins/quench-dev-tasks/hooks.json.template`：将 `quench-file-guard.PreToolUse[0].matcher` 扩展为 `"edit_file|write_file|replace_file_content|multi_replace_file_content|write_to_file|delete_file|run_command"`；在 `quench-context-injector` 下保留 `PreInvocation` 数组的同时，新增同构扁平 `Stop` 数组（`[{"type": "command", "command": "{{PYTHON_EXECUTABLE}} {{CONTEXT_INJECTOR_SCRIPT_PATH}}", "timeout": 5}]`）。
4. 升级 `plugins/quench-dev-tasks/server/hooks/file_scope_guard.py`：① `MUTATING_TOOLS` 新增 `"write_file"` 与 `"edit_file"`；② `build_post_image` 新增 `tool_name == "write_file"`（取 `args.get("Content")`，非 `str` 返回 `None`；若 `bool(args.get("Append", False))` 为真返回 `old_content + content`，否则返回 `content`）与 `tool_name == "edit_file"`（取 `tc = args.get("Target")`、`rc = args.get("Replacement")`，非 `str` 或 `tc == ""` 或 `old_content.count(tc) == 0` 返回 `None`，否则返回 `old_content.replace(tc, rc)`）；③ `main()` 中 `target_file = args.get("TargetFile") or args.get("Path") or ""`，`desc` 回退链补充 `or args.get("toolSummary")`。
5. 升级 `plugins/quench-dev-tasks/server/hooks/context_injector.py`：在 `main()` 中检测 `if "terminationReason" in payload:` 分流至 `_handle_stop_event(payload)`：先触发一次静默 `auto_heal_configs(workspace_root=workspace_root)`，随后严格校验防御检查中的六重护栏；满足续跑条件时在 `.agents/.quench_stop_guard.json`（用 `FileLock`）登记指纹并输出 `{"decision": "continue", "reason": ...}`，其余所有情况（含异常兜底）输出 `{"decision": "allow"}`。
6. 在 `test_config_sync.py`、`test_hooks.py`、`test_file_scope_guard_status.py`、`test_context_injector_autopilot_harness.py` 中补齐针对 `plugins.json` 单源去重（含空文件删除与第三方 MCP 保留）、`edit_file`/`write_file` 白名单拦截与任务单状态篡改拦截、`Stop` Hook 单次熔断续跑与子代理/`fullyIdle=False`/无活跃任务放行的完整单元测试。

#### 【防御与边缘校验】
- 独立工作区 100% 向后兼容：当 `<workspace_root>/.agents/plugins.json` 不存在或未启用挂载 `quench-dev-tasks` 时，`auto_heal_configs` 必须完全保持向 `.agents/{hooks.json, mcp_config.json}` 生成配置的既有行为，确保 `test_config_sync.py` 全部存量断言绿灯。
- 第三方配置零误伤清理：当 `is_workspace_plugin_mounted` 为 `True` 且 `<workspace_root>/.agents/mcp_config.json` 或 `hooks.json` 已存在时，仅剥离 `quench-dev-tasks`（MCP）及 `quench-file-guard` / `quench-context-injector`（Hooks）键；若仍含第三方条目则原子写回保留第三方配置，仅当剥离后为空时才 `unlink` 删除冗余文件。
- `Stop` Hook 防死循环与子代理零干扰六重护栏：(1) 仅当输入 JSON 含 `"terminationReason"` 键时进入 `Stop` 分支（否则走原 `PreInvocation` 分支）；(2) 必须满足 `terminationReason == "NO_TOOL_CALL"` 且 `fullyIdle is True`（有后台任务或子代理运行中时 `fullyIdle` 为 `False`，必须返回 `{"decision": "allow"}`）；(3) 若 `"[QUENCH-DISPATCH:" in str(payload.get("lastUserInput") or "")`（子代理会话）立即返回 `{"decision": "allow"}`；(4) 工作区必须存在活跃 `.agents/quench_stack.yaml` 且 `docs/dev_tasks/` 下至少存在 1 个任务单文件（普通问答回合永不拦截）；(5) `autopilot.stop_at == "none"` 且 `harness_state in {"REVIEW", "CONFIRM", "CHECKOUT", "DISPATCH_RUNNER", "ARCHIVE", "NEXT_BATCH_PROPOSE"}`；(6) 基于 `.agents/.quench_stop_guard.json`（`FileLock` 保护，最多保留 64 条最近键）记录指纹 `f"{conversation_id}::{target_file}::{harness_state}"`，同一指纹最多返回 1 次 `{"decision": "continue", "reason": ...}`，第二次必返回 `{"decision": "allow"}`。
- `test_templates.py` 兼容：更新 `hooks.json.template` 时保留顶层键 `"quench-file-guard"`、`"quench-context-injector"` 及既有占位符格式 `{{PYTHON_EXECUTABLE}} {{FILE_GUARD_SCRIPT_PATH}}` / `{{PYTHON_EXECUTABLE}} {{CONTEXT_INJECTOR_SCRIPT_PATH}}`。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_config_sync.py plugins/quench-dev-tasks/server/tests/test_templates.py plugins/quench-dev-tasks/server/tests/test_hooks.py plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py -q
```

---

### 任务 28.4 ✔️ 已完成 — 插件原生 rules/AGENTS.md 三端哨兵同步、当前工作区冗余配置自愈与架构文档收口

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/rules/AGENTS.md
[MODIFY] plugins/quench-dev-tasks/server/tests/test_agents_md_sync.py
[MODIFY] docs/architecture/README.md
[MODIFY] docs/future_roadmap_ideas.md
```

#### 【缺陷根因与修改目标】
```
根因：(1) 插件目录 `plugins/quench-dev-tasks/rules/` 尚无原生 `AGENTS.md` 纯 Markdown 规则入口，挂载插件时缺少三端同步的插件级路由卡；(2) 当前工作区磁盘仍留有旧版生成的 `.agents/hooks.json` 与 `.agents/mcp_config.json` 冗余副本，且 `plugins/quench-dev-tasks/hooks.json` 需通过新版 `config_sync.py` 重新渲染生效；(3) `docs/architecture/README.md` 与 `docs/future_roadmap_ideas.md` 尚未同步 `v1.28` 落地成果。目标：新建 `plugins/quench-dev-tasks/rules/AGENTS.md` 并纳入 `test_agents_md_sync.py` 三端门禁，执行 `config_sync.py --workspace-root .` 完成当前工作区单源挂载自愈去重，同步架构文档并将 `future_roadmap_ideas.md` §1.1 毕业归入 §2，全量 pytest 100% 绿灯。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/server/tests/test_agents_md_sync.py
PLUGIN_RULES_AGENTS_PATH = PLUGIN_DIR / "rules" / "AGENTS.md"
# Asserts byte-for-byte sentinel sync across ROOT_AGENTS_PATH, TEMPLATE_AGENTS_PATH, and PLUGIN_RULES_AGENTS_PATH, <= 120 lines, and no leading YAML frontmatter.
```

#### 【分步改造指引】
1. 新建 `plugins/quench-dev-tasks/rules/AGENTS.md`（纯 Markdown，无 YAML frontmatter，总行数 `<= 120` 行）：直接对齐根目录 `AGENTS.md` 的精简结构，确保两处 `<!-- QUENCH-CORE-INVARIANTS:BEGIN --> ... <!-- QUENCH-CORE-INVARIANTS:END -->` 哨兵块与根 `AGENTS.md`、`plugins/quench-dev-tasks/templates/AGENTS.md` 逐行逐字完全一致，并包含 Subagent 免调 `dev_tasks_status`、`[QUENCH-DISPATCH: RUNNER | REVIEWER | RESEARCH]` 与 C3 三终态规则。
2. 扩展 `plugins/quench-dev-tasks/server/tests/test_agents_md_sync.py`：引入 `PLUGIN_RULES_AGENTS_PATH = PLUGIN_DIR / "rules" / "AGENTS.md"`，在 `test_agents_md_core_block_byte_sync` 中同时断言 `rules/AGENTS.md` 与根 `AGENTS.md`、`templates/AGENTS.md` 的哨兵块逐行逐字等价，并在 `test_agents_md_line_budget_strict` 中断言 `rules/AGENTS.md` 行数 `<= 120` 且不以 `---`（YAML frontmatter）开头。
3. 更新 `docs/architecture/README.md`：① 在 §3.3 `Zero-Poll Long Polling (wait_max_s)` 条目补充 `POLL_WAIT_MAX_S_HARD_CEILING`（`25.0s`）与 `ReviewerJobSupervisor.gc_terminal_jobs()` 机会式终态回收说明（切勿在 `### 3.3.1` 与 `### 3.4` 之间插入新 `###` 标题）；② 在 §5 `Source Code Mapping` 表格更新 `hooks/file_scope_guard.py`、`hooks/context_injector.py` 职责描述，并新增 `scripts/config_sync.py` 行；③ 在 §6 增补 `plugins/quench-dev-tasks/rules/AGENTS.md` 引用。
4. 更新 `docs/future_roadmap_ideas.md`：将原 `### 1.1 [P0 — Next Up / v1.28 Candidate] Dual-Mode AuditGate Alignment, Single-Source Plugin Mounting & Hook Hardening` 从 `§1 Active Candidate Pool` 移至 `§2 Evaluated Ledger` 顶部，标记为 `### ✔️ 2026-10-31 — Dual-Mode AuditGate Alignment, Single-Source Plugin Mounting & Hook Hardening — Graduated (v1.28)`（原 `1.2`、`1.3`、`1.4` 顺次重排为 `1.1`、`1.2`、`1.3`）。
5. 运行 `python plugins/quench-dev-tasks/scripts/config_sync.py --workspace-root .` 验证当前仓库自动刷新 `plugins/quench-dev-tasks/{hooks.json, mcp_config.json}` 并清理冗余 `.agents/hooks.json` 与 `.agents/mcp_config.json`，随后执行全量测试套件验证 100% 通过。

#### 【防御与边缘校验】
- 纯 Markdown 规则格式：新建的 `plugins/quench-dev-tasks/rules/AGENTS.md` 严禁包含顶部 YAML frontmatter（不得以 `---` 开头），总行数必须严格 `<= 120` 行，字节数远低于 24,000 字节上限。
- 三端核心不变量逐字同步：`plugins/quench-dev-tasks/rules/AGENTS.md` 中的两段 `<!-- QUENCH-CORE-INVARIANTS:BEGIN --> ... <!-- QUENCH-CORE-INVARIANTS:END -->` 内容必须与根目录 `AGENTS.md` 及 `plugins/quench-dev-tasks/templates/AGENTS.md` 逐行逐字 100% 等价。
- 架构文档锚点门禁守恒：修改 `docs/architecture/README.md` 时，严禁在 `### 3.3.1 W10 Exclusion Domain (锁原语豁免域)` 与 `### 3.4` 之间插入任何 H3 标题（保护 `test_doc_invariants_case12.py`），且 §5 表格新增的任何模块路径必须在仓库磁盘真实存在（保护 `test_architecture_doc_anchor_integrity.py`）；所有文档代码块严禁出现已废弃参数或未知关键字（保护 `test_prompt_surface_contract.py`）。

#### 【DoD 验证命令】
```bash
python plugins/quench-dev-tasks/scripts/config_sync.py --workspace-root .
pytest plugins/quench-dev-tasks/server/tests/test_agents_md_sync.py plugins/quench-dev-tasks/server/tests/test_architecture_doc_anchor_integrity.py plugins/quench-dev-tasks/server/tests/test_doc_invariants_case12.py plugins/quench-dev-tasks/server/tests/test_doc_contract_hygiene.py plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py -q
pytest plugins/quench-dev-tasks/server/tests -q
```

---

