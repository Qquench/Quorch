# 2026-11-26_v1_36_batch1_autopilot_and_gateway_contracts Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-26

---

## Task List & Status / 任务清单与状态

### 任务 36.1 ✔️ 已完成 — 修复 Autopilot CONFIRM 不可达、dev_reviewer_poll 非终态契约污染与归档/计数断路

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/autopilot_harness.py
[MODIFY] plugins/quench-dev-tasks/server/runtime_mode.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_tools.py
[NEW] plugins/quench-dev-tasks/server/tests/test_v1_36_batch1_gateway_contracts.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) autopilot_harness.py 中 D3 (if pending_tasks) 无条件拦截在 D4 (CONFIRM) 之前，导致 dev_reviewer_poll(COMPLETED) 或 dev_tasks_refine_spec 审查通过后永远返回 REVIEW 死循环，而 D4 仅在 pending_tasks 为空时可达并生成空 task_ids=()；同时 Step C 对任意非终态 dev_reviewer_poll 均误标 current_stage='after_review'；(2) server.py 中 dev_reviewer_poll 无条件对非 error 字典调用 _inject_harness_next_action，在存在 quench_stack.yaml 的真实工作区向非终态快照注入第 7 个键破坏 V2 6 字段与 <=1024B 契约，并对 FAILED/CANCELLED 误传 last_success=True；(3) dev_tasks_archive 归档后未清空 autopilot.task_file 遮蔽新批次，且 cumulative_runner_tasks 从未持久化透传导致 >=12 熔断器悬空。目标：恢复已敲定的 Autopilot 连续接力状态机、V2 非终态轮询契约与跨批次计数闭环。
```

#### 【目标签名与类型契约】
```
def _is_review_completed_and_passed(last_event: Optional[LastEventSnapshot]) -> bool
AutopilotRuntimeState(task_file: Optional[str] = None, stop_at: StopAtStage = 'none', consumed: bool = False, consumed_for: Optional[str] = None, set_at: Optional[str] = None, cumulative_runner_tasks: int = 0)
```

#### 【分步改造指引】
1. 在 autopilot_harness.py 中引入辅助判定 _is_review_completed_and_passed(last_event)：对 dev_reviewer_poll 仅当 result_data.get('state') == 'COMPLETED' 且内层 result 非 degraded/rework 时视为审查通过；对 dev_tasks_refine_spec 仅当 ok/status 正常且无 rework 阻断时视为通过；Step C 的 current_stage = 'after_review' 同样仅在审查终态完成时置位。
2. 在 autopilot_harness.py Step D 中，将审查刚通过且存在 pending_tasks 的 CONFIRM 分支置于 D3 (REVIEW) 之前，返回全部 pending_tasks 的 task_ids；当 pending_tasks 为空时不再进入 D4 生成空 task_ids=()。
3. 在 server.py 的 dev_reviewer_poll 中：仅当 res.get('state') in ('COMPLETED', 'FAILED', 'CANCELLED', 'ORPHANED')（即终态，绝对排除 QUEUED/RUNNING 非终态快照）时才按需计算或更新运行态；且若 state != 'COMPLETED' 或 (isinstance(res.get('result'), dict) and res['result'].get('status') == 'degraded')，不得误传推进成功通过信号，同时注意保持 POLL_TERMINAL_FIELDS 契约兼容（检查 test_reviewer_jobs.py 对终态字段白名单断言，若终态字段受白名单约束则不在终态快照字典上新增非法键，仅更新内部状态或不破坏终态契约）。
4. 在 runtime_mode.py 的 AutopilotRuntimeState 中新增可选整数字段 cumulative_runner_tasks: int = 0（读写向后兼容），在 server.py 的 dev_tasks_archive 成功后清空 autopilot.task_file=""，在 _inject_harness_next_action 中若 resolved_task_file 不存在于磁盘则回退扫描 dev_tasks_dir，并在 dev_tasks_complete / 跨批次切换时维护并透传 cumulative_runner_tasks 至 compute_next_action。
5. 在 test_autopilot_harness_baton.py、test_server_tools.py 与新建 test_v1_36_batch1_gateway_contracts.py 中补充真实带 quench_stack.yaml 工作区的非终态 dev_reviewer_poll 6 字段/1KB 断言、审查通过推进 CONFIRM 断言、归档后新批次发现断言及 >=12 任务熔断断言。

#### 【防御与边缘校验】
- 非终态 dev_reviewer_poll (QUEUED / RUNNING) 响应字典必须严格等于 POLL_NONTERMINAL_FIELDS 6 个键且字节数 <= 1024B，绝不注入第 7 个键 harness_next_action
- dev_reviewer_poll 处于 FAILED / CANCELLED / ORPHANED 或 result.status == 'degraded' 时，不得触发 CONFIRM，必须正确标记失败或维持阻塞/审查态
- dev_tasks_archive 成功后必须清理或失效旧 autopilot.task_file，且当持久化 autopilot.task_file 指向已不存在文件时自动回退扫描 dev_tasks_dir
- cumulative_runner_tasks 在跨批次切换 spawn_fresh 时重置、同 Runner 完成任务时递增，保持旧版 .quench_runtime_mode.json 向后兼容

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py plugins/quench-dev-tasks/server/tests/test_server_tools.py plugins/quench-dev-tasks/server/tests/test_v1_36_batch1_gateway_contracts.py -q --tb=short
```

---

### 任务 36.2 ✔️ 已完成 — 加固 runtime_mode 锁重入/非字典容错与 response_compactor 阶梯钳制精度

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/runtime_mode.py
[MODIFY] plugins/quench-dev-tasks/server/response_compactor.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_response_compactor.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_tool_response_slim.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch1_gateway_contracts.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) runtime_mode.py 中 update_runtime_mode 未捕获 FileLock Timeout，在持锁内的 CAS 不匹配分支调用 load_runtime_mode 导致同一锁文件自争用超时并产生虚假 lock_contended_read_only 告警，且对非 dict JSON（如 [] 或 autopilot: null）直接 .get() 抛 AttributeError，读取异常时还将 raw_data 置空覆写磁盘；(2) response_compactor.py 的 fit_to_budget Step 3 在缩减 harness_next_action 后未先重测字节数便无条件清空所有非 always_keep 键，且非 status 工具默认 always_keep 为空集导致业务主字段全灭。目标：消除 runtime_mode 自锁争用与类型/覆写隐患，修复 fit_to_budget 阶梯钳制精度。
```

#### 【目标签名与类型契约】
```
def _snapshot_from_raw_data(raw_data: Any, external_api_available: bool, runtime_mode_warning: Optional[str] = None) -> EffectiveModeSnapshot
TOOL_DEFAULT_ALWAYS_KEEP: Final[frozenset[str]]
```

#### 【分步改造指引】
1. 在 runtime_mode.py 中提取纯辅助函数 _snapshot_from_raw_data(raw_data, external_api_available, runtime_mode_warning=None)，统一校验 isinstance(raw_data, dict) 与 isinstance(autopilot_val, dict)；在 update_runtime_mode 锁内 CAS 不匹配时直接调用该纯函数构造快照，消除重入 load_runtime_mode 自超时。
2. 为 update_runtime_mode 外层包裹 FileLock Timeout 捕获（超时返回只读快照、applied=False 及 rejected_reason='lock_timeout'），并在既有文件存在但读取/JSON 解析失败时区分损坏恢复与瞬态锁/IO 错误，避免静默清空已有模式配置；寫入时增加 f.flush() + os.fsync(f.fileno())。
3. 在 response_compactor.py 中定义非 status 工具的轻量默认核心保留键集合（仅含小体积判别键如 'ok', 'status', 'error', 'created', 'updated', 'reason_code', 'task_id', 'job_id', 'state', 'action', 'harness_next_action'，绝不包含大文本键 'handoff_card', 'spec', 'files', 'tasks', 'warnings'），并在 Step 3 缩减 harness_next_action 为 {'action': ...} 后立即重测字节数，若已满足 budget 则直接返回，无需继续剥离其余业务字段。
4. 在 test_response_compactor.py、test_tool_response_slim.py 与 test_v1_36_batch1_gateway_contracts.py 中补充 CAS 不匹配零自超时告警、Timeout 优雅降级、非字典 JSON 容错及 fit_to_budget Step 3 保留核心鉴别键的单测断言。

#### 【防御与边缘校验】
- response_compactor.py 中严禁出现硬编码整数字面量 1024 / 2048 或字符串 'ASK_MODAL_BLOCKED'（遵守 test_response_compactor_e1_no_hardcoded_literals AST 门禁）
- 100% 保持 dev_tasks_export_handoff_card 超长 5000B 卡片钳制 <= 预算、dev_reviewer_poll terminal 阶段豁免及 dev_tasks_checkout 正常返回完整 spec 的既有行为不变
- update_runtime_mode 遭遇锁竞争 Timeout 时优雅返回当前只读快照与 rejected_reason='lock_timeout'，绝不抛未捕获异常崩溃；读取文件 I/O 异常时不得用空字典覆盖已有配置

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_response_compactor.py plugins/quench-dev-tasks/server/tests/test_tool_response_slim.py plugins/quench-dev-tasks/server/tests/test_v1_36_batch1_gateway_contracts.py -q --tb=short
```

---

### 任务 36.3 ✔️ 已完成 — 收紧 server.py 任务路径工作区禁锢、DoD AST 断言检测与 UTC 时间标准

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch1_gateway_contracts.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) server.py 中 _resolve_task_file_path 允许任意工作区外绝对路径与 '..' 相对穿越，导致 dev_tasks_archive (shutil.move)、dev_tasks_promote_draft 与 dev_tasks_escalate (context_files) 存在工作区逃逸风险；(2) _audit_test_changes 调用 git 时缺少 -c core.quotepath=false 与子目录相对路径对齐，且用纯字符串 'assert ' 匹配导致注释 '# assert True' 可绕过单测门禁；(3) server.py 多处使用无时区 datetime.now()，且解析无时区 bypass expires_at 时直接 .astimezone(timezone.utc) 被当作宿主机本地时区换算。目标：收紧网关路径边界、AST 断言核验与 UTC 时间标准。
```

#### 【目标签名与类型契约】
```
def _resolve_task_file_path(workspace_root: str, task_file: str, config: Optional[Any] = None) -> str
def _python_source_has_real_assertions(source_text: str) -> bool
```

#### 【分步改造指引】
1. 加固 server.py 的 _resolve_task_file_path：对传入绝对路径与拼接候选路径均通过 os.path.realpath + os.path.normcase + os.path.commonpath 严格断言落在 realpath(workspace_root) 之内（跨盘捕获 ValueError 并抛出路径越界异常），并在各调用点优雅转化为结构化错误字典返回；同步在 dev_tasks_escalate 读取 context_files 前调用 sanitize_workspace_path 校验边界。
2. 加固 server.py 的 _audit_test_changes：git 命令统一携带 -c core.quotepath=false 及 --relative（基于 workspace_root），对 Python 测试文件改用 ast.parse（语法错误回退词法过滤注释行）检查真实 ast.Assert 节点、pytest.raises / pytest.warns 调用或 self.assert* 方法调用，拦截仅含 '# assert ...' 注释的伪单测。
3. 将 server.py 中残余无时区 datetime.now()（如 _append_hook_log、dev_tasks_archive）统一改为 datetime.now(timezone.utc)，并在 dev_tasks_status 与 bypass 校验解析 expires_at 时先判断 if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)；将关键路径的静默 except Exception: pass 替换为 stderr/logger 诊断记录（严守 INV-4 零 stdout 写入）。
4. 在 test_v1_36_batch1_gateway_contracts.py 中新增工作区外路径拦截（archive / promote_draft / escalate）、注释伪断言拦截、Git 子目录测试审计与无时区 UTC 过期解析单测，并校验 export_ide_schemas.py --check 零漂移。

#### 【防御与边缘校验】
- _resolve_task_file_path 必须在保持合法相对名（如 'feat.md' 或 'docs/dev_tasks/feat.md'）及工作区内绝对路径 100% 兼容的前提下，对跨出 workspace_root（含软链接与 '..' 及跨盘路径）抛出 ValueError/UnsafePathError 阻断
- server.py 中所有 @mcp.tool() 的函数名、参数签名与 Docstring 保持零改动，确保 ide_tool_schemas.json 快照零漂移
- _audit_test_changes 的 AST 断言检查需兼容 unittest 风格 self.assert*、原生 assert 语句与 with pytest.raises / pytest.warns，同时精准拒绝纯注释 '# assert True' 或纯文档字符串绕过

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch1_gateway_contracts.py plugins/quench-dev-tasks/server/tests/test_server_tools.py -q --tb=short && .venv\Scripts\python.exe scripts/export_ide_schemas.py --check
```

---

