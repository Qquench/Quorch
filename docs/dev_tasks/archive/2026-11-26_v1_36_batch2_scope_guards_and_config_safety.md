# 2026-11-26_v1_36_batch2_scope_guards_and_config_safety Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-26

---

## Task List & Status / 任务清单与状态

### 任务 36.4 ✔️ 已完成 — 封堵物理范围守卫（PreToolUse / PathGuard / Pre-Commit）逃逸并加固 Stop Hook 熔断精度

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/context_injector.py
[MODIFY] plugins/quench-dev-tasks/server/path_guard.py
[MODIFY] plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_hooks.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_path_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_pre_commit_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py
[NEW] plugins/quench-dev-tasks/server/tests/test_v1_36_batch2_scope_and_config.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) git_pre_commit_guard.py 的 find_active_task 仅匹配纯数字 (\d+)，导致 1.1/36.1 等点分任务号下提交守卫完全静默失效，且 check_violations 允许同名 basename 与双向 endswith 绕过；(2) file_scope_guard.py 与 path_guard.py 允许字面量文件名按 basename 或无锚点 endswith 全仓匹配，matches_pattern 的 /** 子串回退与 /* 前缀快捷分支越过目录与工作区边界，活跃任务正则 re.DOTALL 可跨任务头吞入后续白名单，verify_session_integrity 在缺失 conversationId 时跳过会话锁且无时区时间按本地时区换算；(3) context_injector.py 的 Stop Hook 指纹缺少 task_id 导致同文件后续任务被永久熔断，未覆盖 snake_case last_user_input/子代理标识，且 mkstemp(text=True) 在 Windows 产生双回车。目标：全面封堵范围守卫逃逸漏洞并修复 Stop Hook 熔断精度。
```

#### 【目标签名与类型契约】
```
def is_within_whitelist(canonical_rel_path: str, whitelist: Sequence[str | os.PathLike[str]], *, case_sensitive: bool = True) -> bool
def verify_session_integrity(bypass_data: dict, incoming_conversation_id: Optional[str]) -> Tuple[bool, str]
```

#### 【分步改造指引】
1. 修复 git_pre_commit_guard.py：将 find_active_task 任务号正则升级为 ([0-9a-zA-Z\._\-]+) 并过滤 Markdown 代码围栏，仅剥离行尾括号注释 \s*[（(][^）)]*[）)]\s*$ 与 -> 重命名路径；在 check_violations 中移除 allowed_basenames 与双向 endswith，改为规范化工作区相对路径精确匹配（通配符走锚定 glob）；get_staged_files 增加 -c core.quotePath=false；install_hook 兼容 Git Worktree（.git 为文件时解析 git rev-parse --git-dir）。
2. 修复 path_guard.py：在 is_within_whitelist 中将 basename 匹配严格限定于含通配符 ('*' in pat_str or '?' in pat_str) 的无斜杠模式；在 canonicalize_path 中补齐 Windows 驱动器相对路径 (C:foo)、冒号/NTFS ADS (:)、段尾点/空格与 Win32 保留设备名拦截。
3. 修复 hooks/file_scope_guard.py：(a) 活跃任务【涉及文件】提取严格截断至下一个 ^###\s+ 标题行，兼容大小写标记、列表前缀 (-/*)、反引号与 -> 重命名，移除 basename 与无锚点 endswith 放行，统一归一化为工作区内物理路径精确比对（含通配符时走 matches_pattern）；(b) 在 matches_pattern 中移除 '/**' 的 f'/{prefix}/' in f'/{rel_clean}/' 子串回退与 '/*' 的 startswith 快捷分支（交由分段匹配器精确处理），并对非 '**/' 开头模式拒绝匹配 workspace_root 外部路径（100% 保留 '**/brain/**' 跨盘匹配）；(c) verify_session_integrity 在 locked_session 非空且 not incoming_conversation_id 时返回 False，无时区 expires_at 先 .replace(tzinfo=timezone.utc)（同步更新 test_file_scope_guard.py:41 使用 datetime.now(timezone.utc)），移除 safe_clean_corrupted_bypass 锁超时分支中的无锁删除；(d) detect_shell_write_bypass 用 re.escape(clean_dir) 替代硬编码 dev_tasks 并覆盖删除/移动命令，check_task_status_guard 捕获 (OSError, UnicodeDecodeError)，is_meta_file 使用 realpath + '/' 边界，并在 main() 前置 READ_ONLY_TOOLS 与 is_agent_brain_artifact 快速短路以保障 <50ms 预算。
4. 修复 hooks/context_injector.py：_handle_stop_event 同时检查 lastUserInput / last_user_input 含 '[QUENCH-DISPATCH:' 以及 parentConversationId / parent_conversation_id / isSubagent 标识；选择活跃任务单时优先定位含 🔨 执行中任务的文件；将当前活跃/待办 task_id 与状态摘要纳入 .quench_stop_guard.json 指纹使同批次后续任务正常续跑；移除 _atomic_write_json 中 mkstemp 的 text=True。
5. 在 test_v1_36_batch2_scope_and_config.py 及对应测试文件中补充点分任务 ID 提交拦截、同名 basename 拒绝、docs/** 与 docs/* 边界隔离、缺失 conversationId 旁路拒绝及多任务 Stop Hook 续跑单测。

#### 【防御与边缘校验】
- 100% 保持 v1.34 DEFAULT_AGENT_BRAIN_PATTERNS (**/brain/**/*.md, **/brain/**/scratch/**, **/brain/**/browser_sandbox/**) 对工作区外跨盘路径的自动放行能力不退化
- file_scope_guard.py 中严禁硬编码状态 Emoji 字面量（遵守零状态 Emoji 门禁，统一从 task_status 导入常量），并维持 <50ms 子进程轻量导入纪律
- test_hooks.py、test_file_scope_guard.py、test_file_scope_guard_status.py、test_snapshot_drift_gate_contract.py、test_pre_commit_guard.py 既有断言必须 100% 全绿

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch2_scope_and_config.py plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py plugins/quench-dev-tasks/server/tests/test_hooks.py plugins/quench-dev-tasks/server/tests/test_path_guard.py plugins/quench-dev-tasks/server/tests/test_pre_commit_guard.py plugins/quench-dev-tasks/server/tests/test_snapshot_drift_gate_contract.py plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py -q --tb=short
```

---

### 任务 36.5 ✔️ 已完成 — 加固 project_config 本地覆盖单调防线/迁移锁与 code_explorer 软链接沙箱

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/code_explorer.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_project_config.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_code_explorer.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch2_scope_and_config.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) project_config.py 的 _merge_local_override 用 `is False` 判定 audit_gate.enabled（可被 0 或 'false' 绕过），且当基线未显式声明 accepted_sources / managed_paths / unmanaged_paths 时跳过单调检查（允许 local.yaml 注入 unmanaged_paths: ['**'] 关闭全仓治理）；此外 migrate_config_if_needed 缺少 FileLock/fsync/BOM 保留且正则误匹配缩进子键，非字典 local.yaml 被静默忽略，大写安全级别如 'BLOCK' 触发 Pydantic 失败，is_protected_config_path 在 POSIX 漏判反斜杠，canonical_artifact_ref 缺少 realpath 与跨盘 ValueError 处理；(2) code_explorer.grep 未校验遍历到的软链接目标路径归属与敏感性，可越界读取外部文件或 .env，且全树 os.walk 未做懒加载提前终止。目标：闭环本地覆盖单调防线、配置迁移并发安全与代码检索沙箱。
```

#### 【目标签名与类型契约】
```
def _coerce_strict_bool(val: Any, default: bool = True) -> bool
def canonical_artifact_ref(workspace_root: str, task_file: str, task_id: str) -> str
```

#### 【分步改造指引】
1. 加固 project_config._merge_local_override：引入规范化布尔解析辅助函数（识别 False/0/'0'/'false'/'no'/'off'），基线有效 enabled 默认按 AuditGatePolicy 默认值对比；对 accepted_sources 在基线缺省时按当前模式默认允许源对比；对 unmanaged_paths 在基线缺省视同空集 set()（禁止 local.yaml 新增未声明的免管路径），对 managed_paths 在基线未设置显式子集时禁止 local.yaml 擅自注入窄化列表覆盖全局启发式受管范围。
2. 加固 project_config.py 其余边界：为 migrate_config_if_needed 增加 FileLock(f'{yaml_path}.lock', timeout=5.0)、UTF-8 BOM 保全、行首零缩进正则锚定 (^schema_version\s*: 与 ^fast_track_rules\s*:)、mkstemp + flush + fsync + finally 清理；对非 dict 的 quench_stack.local.yaml 抛出 ConfigError；在构造 AuditGatePolicy 前将小写归一化后的安全策略值写回 ag_dict；is_protected_config_path 先将 '\\' 替换为 '/' 再取 basename；canonical_artifact_ref 使用 os.path.realpath 并捕获跨盘 ValueError；将 'reviewer_jobs' 纳入 KNOWN_TOP_LEVEL_KEYS。
3. 加固 code_explorer.py：在 resolve_within_roots 中拦截非允许根的 Windows 驱动器相对路径 (如 'C:foo.py')；在 grep() 中按需流式迭代 os.walk（达 max_files 或 deadline 提前退出），对每个候选文件通过 os.path.realpath 校验严格落在 realpath(matched_root) 内（捕获跨盘 ValueError），并对链接名与真实目标相对路径双向执行 is_sensitive_file 过滤；将 explore_code_slices 中的静默 except Exception: pass 改为 logger.warning(..., exc_info=True)。
4. 在 test_v1_36_batch2_scope_and_config.py、test_project_config.py 与 test_code_explorer.py 中新增 enabled:0/'false' 拦截、缺省基线注入 unmanaged_paths:['**'] 拦截、POSIX 反斜杠受保护配置识别、跨盘 canonical_artifact_ref 及 grep 外部/敏感软链接拦截单测。

#### 【防御与边缘校验】
- _merge_local_override 必须继续允许合法收紧操作（如 warn -> block、缩小 accepted_sources）与非安全字段（如 reviewer_engine 模型配置）的正常本地覆盖，不破坏现有用户的 quench_stack.local.yaml 用法
- KNOWN_TOP_LEVEL_KEYS 兼容历史/模板遗留键 'reviewer_jobs' 以消除新仓无端告警，但对真正未知的拼写错误键依然产生 ConfigFault.UNKNOWN_KEY 保持既有容错测试通过
- code_explorer.grep 修复软链接逃逸后仍须保持既有分页 cursor、文件大小上限与匹配行号格式 100% 兼容

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch2_scope_and_config.py plugins/quench-dev-tasks/server/tests/test_project_config.py plugins/quench-dev-tasks/server/tests/test_global_config_layer.py plugins/quench-dev-tasks/server/tests/test_code_explorer.py -q --tb=short
```

---

