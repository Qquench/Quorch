# 2026-10-31_v1_28_batch3_harness_overlap_drilldown Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-31

---

## Task List & Status / 任务清单与状态

### 任务 28.5 ✔️ 已完成 — 升级 autopilot_harness._extract_top_module_dir 支持外层容器目录子模块下钻与根文件桶隔离

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/autopilot_harness.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py
```

#### 【缺陷根因与修改目标】
```
根因：autopilot_harness._extract_top_module_dir 当前仅对 tests/test 做单层截取，其余路径一律返回 parts[0]，且将所有无斜杠根目录文件统一映射至同一 "__root__" 桶。在采用 plugins/<pkg>/...、packages/<pkg>/...、src/<submod>/... 等外层容器目录的仓库中，完全异构的子模块（如 plugins/quench-dev-tasks/server/*.py 与 plugins/quench-dev-tasks/scripts/*.py、plugins/quench-dev-tasks/server/hooks/*.py）以及无关根文件（如 dev_tasks_mcp_specification.md 与 .gitignore）被折叠进同一粗粒度桶，虚增 dir_ratio 跨过 0.30 阈值并误导 resolve_runner_dispatch_channel 返回 reuse_active。目标：在纯函数零 I/O 约束下升级 _extract_top_module_dir，引入显式深度映射的 _DEEP_SUBMODULE_CONTAINERS（保留至多 4 层目录段以区分 plugins/<pkg>/server 与 plugins/<pkg>/server/hooks）及 _SHALLOW_SUBMODULE_CONTAINERS（保留至多 2 层目录段以区分 src/<submod>），并将根文件映射为 "__root__:<filename>"，确保同域子模块维持 reuse_active、异构子域准确路由至 spawn_fresh。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/server/autopilot_harness.py
# Slice depth mapping:
#   _DEEP_SUBMODULE_CONTAINERS    -> dir_parts[:4] (distinguishes plugins/<pkg>/<mod> vs plugins/<pkg>/<mod>/<submod>)
#   _SHALLOW_SUBMODULE_CONTAINERS -> dir_parts[:2] (distinguishes src/<submod>, docs/<submod>, tests/<submod>)
_DEEP_SUBMODULE_CONTAINERS: frozenset[str] = frozenset({
    "plugins", "packages", "apps", "services", "crates", "libs", "modules",
})
_SHALLOW_SUBMODULE_CONTAINERS: frozenset[str] = frozenset({
    "src", "lib", "app", "pkg", "internal", "docs", "tests", "test",
})
def _extract_top_module_dir(p: str) -> str: ...
```

#### 【分步改造指引】
在 plugins/quench-dev-tasks/server/autopilot_harness.py 中声明模块级常量与深度映射注释：_DEEP_SUBMODULE_CONTAINERS: frozenset[str] = frozenset({"plugins", "packages", "apps", "services", "crates", "libs", "modules"})（保留至多 4 层 dir_parts，用以区分 plugins/<pkg>/<module> 与 plugins/<pkg>/<module>/<submod>，如 server/*.py vs server/hooks/*.py）与 _SHALLOW_SUBMODULE_CONTAINERS: frozenset[str] = frozenset({"src", "lib", "app", "pkg", "internal", "docs", "tests", "test"})（保留至多 2 层 dir_parts，用以区分 src/<submod>、docs/<submod>、tests/<submod>）。
重构 _extract_top_module_dir(p: str) -> str：先执行 cleaned = p.strip("/")，若 not cleaned 则返回 ""；若 "/" not in cleaned，返回 f"__root__:{cleaned}"；否则设 dir_parts = cleaned.split("/")[:-1]：(a) 若 dir_parts[0] in _DEEP_SUBMODULE_CONTAINERS，返回 "/".join(dir_parts[:4])；(b) 若 dir_parts[0] in _SHALLOW_SUBMODULE_CONTAINERS，返回 "/".join(dir_parts[:2])；(c) 其余常规顶层模块目录返回 dir_parts[0]。
在 plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py 中导入 _extract_top_module_dir 并新增 @pytest.mark.tier1_fast 单元测试：(1) 精确断言空串、同名/异名根文件（CHANGELOG.md vs .gitignore）、深层容器 1~4+ 层目录深度（plugins/README.md -> "plugins"、plugins/pkg/hooks.json -> "plugins/pkg"、plugins/pkg/server/a.py -> "plugins/pkg/server"、plugins/pkg/server/hooks/b.py -> "plugins/pkg/server/hooks"、plugins/pkg/server/hooks/sub/c.py -> "plugins/pkg/server/hooks"）与浅层容器 1~2+ 层深度（src/main.py -> "src"、src/auth/login.py -> "src/auth"、tests/unit/test_x.py -> "tests/unit"）；(2) 使用确定性回测数据集 BATCH_1_FILES = ["plugins/quench-dev-tasks/server/project_config.py", "plugins/quench-dev-tasks/server/server.py", "plugins/quench-dev-tasks/rules/dev-tasks-discipline.md", "plugins/quench-dev-tasks/server/tests/test_audit_gate.py", "dev_tasks_mcp_specification.md"] 与 BATCH_2_FILES = [".gitignore", "plugins/quench-dev-tasks/scripts/config_sync.py", "plugins/quench-dev-tasks/hooks.json.template", "plugins/quench-dev-tasks/server/hooks/file_scope_guard.py", "plugins/quench-dev-tasks/server/tests/test_hooks.py", "plugins/quench-dev-tasks/rules/AGENTS.md", "docs/architecture/README.md", "docs/future_roadmap_ideas.md"]，断言 compute_batch_overlap_ratio(BATCH_1_FILES, BATCH_2_FILES) == 0.125 (< 0.30) 且 resolve_runner_dispatch_channel(prev_batch_files=BATCH_1_FILES, curr_batch_files=BATCH_2_FILES) == "spawn_fresh"；同时断言 BATCH_SERVER_FOLLOWUP = ["plugins/quench-dev-tasks/server/autopilot_harness.py", "plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py"] 与 BATCH_1_FILES 的 compute_batch_overlap_ratio == 0.5 (>= 0.30) 且路由至 "reuse_active"，而与 BATCH_2_FILES 的 compute_batch_overlap_ratio == 0.25 (< 0.30) 且路由至 "spawn_fresh"。

#### 【防御与边缘校验】
严守 autopilot_harness.py 纯函数零 I/O、零网络边界（test_compute_next_action_zero_io_pure 拦截 builtins.open 必须持续通过），严禁引入 os.path.exists 或任何文件系统调用。
严守厂商中立红线（INV-5）与协议通道纯净度（INV-4）：严禁在模块中出现任何模型厂商字面量或 print()，并通过 test_architecture_hygiene.py 与 test_vendor_neutrality.py 物理扫描门禁。
既有测试全量核查：test_autopilot_harness_baton.py 现有 11 个测试均使用 backend/*、frontend/* 与 docs/README.md（无 __root__ 硬编码断言），对非容器顶层目录（backend/...、frontend/...）维持返回 dir_parts[0]，确保既有断言零回归。
根文件同名命中与异名隔离语义：_extract_top_module_dir("CHANGELOG.md") == "__root__:CHANGELOG.md" 且 != _extract_top_module_dir(".gitignore")，确保跨批次修改同一根文件命中同桶（overlap=1.0），而修改不同根文件互不碰撞（overlap=0.0）。
防御空串与浅层容器边界：若 p.strip("/") 为空串则返回 ""；当文件直接位于容器根下（如 plugins/README.md 或 src/main.py，len(dir_parts) == 1）时切片 dir_parts[:4] / dir_parts[:2] 安全返回单个元素 "plugins" / "src"，绝不产生越界异常。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py plugins/quench-dev-tasks/server/tests/test_vendor_neutrality.py -q
pytest plugins/quench-dev-tasks/server/tests -q
```

---

