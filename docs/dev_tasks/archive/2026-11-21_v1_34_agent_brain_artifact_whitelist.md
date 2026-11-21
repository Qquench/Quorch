# 2026-11-21_v1_34_agent_brain_artifact_whitelist Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-21

---

## Task List & Status / 任务清单与状态

### 任务 34.1 ✔️ 已完成 — Agent Brain 运行期制品白名单、多段 ** Glob 路径段匹配加固与配置模板对齐

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] .agents/quench_stack.yaml
[MODIFY] plugins/quench-dev-tasks/templates/quench_stack.yaml
[MODIFY] plugins/quench-dev-tasks/server/tests/test_hooks.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_project_config.py
```

#### 【缺陷根因与修改目标】
```
缺陷根因：1) IDE 宿主在运行期向会话专属 brain/<conversation-id>/ 目录写入 Markdown 制品（walkthrough.md、implementation_plan.md 等）及 scratch/**、browser_sandbox/** 临时文件时，因该目录位于 workspace_root 之外（Windows 下常跨盘符），project_config.py::is_path_governed 在越界检查时短路返回 True（受管代码），且 file_scope_guard.py 缺乏针对 Agent 运行期 brain 制品的内置/默认快速通道白名单；2) matches_pattern 与 _match_glob 在处理 **/brain/**/*.md、**/brain/** 等多段 ** 递归 Glob 时，既未剥离 /** 分支的前导 **/，也未支持 ** 匹配 0 个或多个完整路径段，导致跨盘符外部路径与零中间层级路径匹配失灵。修改目标：内置 DEFAULT_AGENT_BRAIN_PATTERNS 与物理路径防逃逸校验 is_agent_brain_artifact，加固路径段感知的多段 ** Glob 匹配算法，并在 .agents/quench_stack.yaml 与 templates/quench_stack.yaml 的 allow_untracked_patterns 中预置 brain 制品白名单规则。
```

#### 【目标签名与类型契约】
```
DEFAULT_AGENT_BRAIN_PATTERNS: Tuple[str, ...] = (\n    "**/brain/**/*.md",\n    "**/brain/**/scratch/**",\n    "**/brain/**/browser_sandbox/**",\n)\n\ndef _match_segmented_glob(target_path: str, norm_pattern: str) -> bool:\n    ...\n\ndef resolve_physical_path(workspace_root: str, target: str) -> Optional[str]:\n    ...\n\ndef is_agent_brain_artifact(target_file: str, workspace_root: str) -> bool:\n    ...\n\ndef matches_pattern(target_file: str, pattern: str, workspace_root: str) -> bool:\n    ...\n\ndef is_whitelist_matched(config: Any, target_file: str, workspace_root: str) -> bool:\n    ...
```

#### 【分步改造指引】
在 plugins/quench-dev-tasks/server/project_config.py 中新增纯函数 _match_segmented_glob(target_path: str, norm_pattern: str) -> bool，将路径与模式按 '/' 切分为非空路径段（折叠连续的 '**' 段），支持 '**' 匹配 0 个或多个完整路径段、非 '**' 段通过 fnmatch.fnmatchcase 精确匹配单段；在 _match_glob 中修复 norm_pattern.endswith('/**') 时前导 '**/' 未剥离的问题并接入 _match_segmented_glob（注意：严禁在 project_config.py 的代码或注释中出现任何厂商 token 字面量以遵守 INV-5）。
在 plugins/quench-dev-tasks/server/hooks/file_scope_guard.py 中定义 DEFAULT_AGENT_BRAIN_PATTERNS: Tuple[str, ...] = ('**/brain/**/*.md', '**/brain/**/scratch/**', '**/brain/**/browser_sandbox/**')；抽取 resolve_physical_path(workspace_root: str, target: str) -> Optional[str] 消解软链接与未创建文件的祖先目录 realpath（供 resolve_realpath_under 与 main() 复用）。
在 file_scope_guard.py 中升级 matches_pattern：先对 target_file 进行 normpath 规整以消解 '..'，修复 endswith('/**') 前导 '**/' 截断问题，并接入路径段感知的 '**' 递归段匹配逻辑，使 '**/brain/**/*.md'、'**/brain/**'、'frontend/src/**/*.vue' 在工作区内相对路径、跨盘符外部绝对路径及 0 层或多层中间子目录下均精确匹配且严格按目录段边界隔离。
在 file_scope_guard.py 中新增 is_agent_brain_artifact(target_file: str, workspace_root: str) -> bool（基于 resolve_physical_path 规整后的物理路径校验是否命中 DEFAULT_AGENT_BRAIN_PATTERNS 且不含 '..' 逃逸），在 is_whitelist_matched 中合并 config.get_fast_track_patterns() 与 DEFAULT_AGENT_BRAIN_PATTERNS，并在 main() 的 0.1 阶段与情形 A/B 白名单检查中放行 Agent brain 制品写入。
更新 .agents/quench_stack.yaml 与 plugins/quench-dev-tasks/templates/quench_stack.yaml 中的 fast_track_rules.allow_untracked_patterns，预置 '**/brain/**/*.md'、'**/brain/**/scratch/**'、'**/brain/**/browser_sandbox/**'。
在 test_file_scope_guard.py、test_hooks.py 与 test_project_config.py 中补充完整单测：覆盖跨盘符/工作区外 brain/<conv-id>/*.md 与 scratch/** 在有活跃任务（情形 A）和无活跃任务（情形 B）下的免拦截放行、多段 ** Glob（0 层/多层中间目录、前导 **/）匹配、brain/../../evil.py 路径回溯与软链接逃逸拦截、以及非 brain 外部路径（如 ../outside_project/evil.py）继续拦截。

#### 【防御与边缘校验】
路径逃逸与软链接防御：通过 resolve_physical_path 先行消解软链接、junction 及 .. 相对路径回溯，确保形如 C:/Users/.../brain/conv-1/../../outside_repo/src/main.py 或指向工作区外其他目录的软链接在归一化后脱离 brain 目录段，绝不被误判为 brain 制品放行。
任务单目录逃逸硬拦截不变：保持 main() 中 has_task_dir_marker 与 is_governed_task_file 优先于 brain 制品与白名单判断执行，确保 docs/dev_tasks/../../outside.md 依然触发 decision='deny', reason='realpath_escape'。
工作区外普通路径受管防线不变：保持 project_config.py::is_path_governed 对 ../../etc/passwd、../outside_project/evil.py 等非白名单越界路径返回 True（受管拦截），且 _DEFAULT_FAST_TRACK_PATCH 保持 allow_untracked_patterns: [] 以兼容 v0->v1 配置迁移单测。
INV-5 厂商中立性红线与零状态 Emoji 铁律：project_config.py 等 server/*.py 顶层模块严禁出现任何 BANNED_VENDOR_TOKENS 子串（包括注释或路径示例中严禁出现点号加厂商名的目录字面量）；file_scope_guard.py 非文档字符串中严禁出现状态 Emoji 字面量，且顶层导入保持轻量隔离（不加载 fastmcp/manifest/filelock/yaml）。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py plugins/quench-dev-tasks/server/tests/test_hooks.py plugins/quench-dev-tasks/server/tests/test_project_config.py plugins/quench-dev-tasks/server/tests/test_file_scope_guard_hardening.py plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py plugins/quench-dev-tasks/server/tests/test_config_migration.py plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q
```

---

