# 2026-11-26_v1_36_batch3_state_machine_and_leases Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-26

---

## Task List & Status / 任务清单与状态

### 任务 36.6 ✔️ 已完成 — 统一 Markdown->Manifest 锁序，修复 reclaim 半提交、租约伪造与裸 ID 墓碑遮蔽

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/manifest.py
[MODIFY] plugins/quench-dev-tasks/server/manifest_lease.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py
[NEW] plugins/quench-dev-tasks/server/tests/test_v1_36_batch3_state_and_leases.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) server.py 的 dev_tasks_confirm 先持 manifest_lock 再调 transition_task 申请 md_lock，与 reclaim_stale_task 的 Markdown -> Manifest 严格锁序反转存在 AB-BA 死锁风险；且多处混用 FileLock is_singleton=True/False；(2) reclaim_stale_task 先落盘 manifest(released=True) 再执行 transition_task，若后者失败则任务永久卡死在 🔨 执行中而重试误报 already_reclaimed_or_fenced；(3) server.py 的 _issue_checkout_lease 静默吞掉 commit_lease 异常并伪造 expected_gen + 1，且重入检出未校验跨会话归属；(4) manifest._resolve_namespaced_id / probe_lease_health / reclaim_stale_task / dev_tasks_heartbeat 裸 task_id 查找被旧任务单留存的 released=True 墓碑遮蔽，touch_lease_heartbeat 在多记录下提前 break；(5) probe_lease_health 对不存在的 [NEW] 父目录调保守探针反向误判为 HEALTHY，且将空/损坏心跳时间夹为 0.0 (新鲜)。目标：统一全局锁序、保障租约 CAS 原子性与活跃记录优先解析。
```

#### 【目标签名与类型契约】
```
def is_workspace_actively_modifying(workspace_root: str, affected_files: Sequence[str], window_seconds: float = 600.0, now_ts: Optional[float] = None, *, conservative_on_unreadable: bool = True) -> bool
def _resolve_namespaced_id(manifest: Manifest, task_id: str, md_path: Optional[str] = None) -> str
```

#### 【分步改造指引】
1. 统一锁序与 FileLock 参数：在 server.py 的 dev_tasks_confirm 中，按 target_path + '.lock' -> manifest.json.lock (Markdown -> Manifest) 顺序加锁（或在释放 manifest_lock 前已完成前置条件核验、统一遵循先持 md_lock 再持 manifest_lock），并统一协调 is_singleton 使用避免同线程自争用或 timeout 不一致抛 ValueError。
2. 修复 reclaim_stale_task (manifest_lease.py)：在 md_lock -> manifest_lock 临界区内先完成 transition_task(md_path, actual_tid, STATUS_CONFIRMED)（若已为 CONFIRMED 则幂等放行），成功后再调用 atomic_replace_manifest 提交 released=True 与 new_generation，杜绝半提交卡死；同时将 _extract_affected_files_from_task 截断至当前任务段落并支持大小写标记、括号注释剥离与 -> 重命名拆分，_evaluate_affected_files_mtime 增加工作区内 realpath 边界校验。
3. 修复 server.py 检出租约安全：在 _issue_checkout_lease 中禁止静默吞掉 FencedTokenError / ManifestIntegrityError / Timeout 伪造令牌（若检出后签发租约失败则回滚 Markdown 状态至 STATUS_CONFIRMED 并返回结构化错误）；在 dev_tasks_checkout 重入检出 STATUS_IN_PROGRESS 任务时，提取 existing_rec.holder_token 中的绑定 session_id，若存在绑定 session_id 且调用方传入不同或缺失的 clean_session_id 则拒绝回传 holder_token（无绑定会话的默认单会话检出保持 100% 原行为兼容）。
4. 修复裸 task_id 墓碑遮蔽与心跳多记录匹配：在 manifest._resolve_namespaced_id、manifest_lease.probe_lease_health、manifest_lease.reclaim_stale_task 与 server.dev_tasks_heartbeat 中，当未传 md_path 解析裸 task_id 时优先匹配 released=False 的活跃记录（若无活跃记录再回退最新记录）；在 touch_lease_heartbeat 循环内结合 holder_token / generation 过滤候选而非遇到首条即 break；支持 compare_and_swap / release_lease / touch_heartbeat 可选接收 md_path。
5. 修复 probe_lease_health 与 manifest 边界：为 is_workspace_actively_modifying 增加关键字参数 conservative_on_unreadable: bool = True（保持直接调用默认行为不变），在 probe_lease_health 中传入 conservative_on_unreadable=False 与浮点 window_seconds=float(mtime_thresh)，并对缺失/损坏的 last_heartbeat_wall_utc 视为已超时而非 0.0（仅对合法时间解析出的负时钟偏移夹为 0.0），在 line 138 同样对微小负时钟偏移做 max(0.0, age) 对齐；在 manifest.py 中补齐软链接/跨盘 relpath ValueError 防护、去除前导 './' 及在超阈值时记录 manifest 体积告警日志。

#### 【防御与边缘校验】
- 100% 保持 ★并发不变量硬门禁★ pytest -q -k 'state_machine or reclaim_cas or workspace_lease' 及 test_lease_heartbeat_external.py 全绿（保留 is_workspace_actively_modifying 默认 conservative_on_unreadable=True 向后兼容直接调用方）
- server.py 中所有 @mcp.tool() 的函数名、参数签名与 Docstring 零修改，确保 ide_tool_schemas.json 快照零漂移，且严守 INV-4 零 stdout 输出
- 当 dev_tasks_checkout 重入检出已处于 🔨 执行中的任务时：若调用方未传 session_id 且原 holder_token 不绑定特定会话（或传了匹配的 session_id）允许正常返回凭据，仅在原 holder_token 绑定了会话 ID 且调用方缺失或不匹配时拒绝跨会话泄露 holder_token，保持单会话无 session_id 检出流程 100% 兼容！

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch3_state_and_leases.py plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py -q --tb=short && .venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests -q -k "state_machine or reclaim_cas or workspace_lease" --tb=short
```

---

### 任务 36.7 ✔️ 已完成 — 加固 state_machine 围栏/BOM 保全、normalize_status 词边界、task_writer 保态与原子写

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/state_machine.py
[MODIFY] plugins/quench-dev-tasks/server/task_status.py
[MODIFY] plugins/quench-dev-tasks/server/task_writer.py
[MODIFY] plugins/quench-dev-tasks/server/workspace_lease.py
[MODIFY] plugins/quench-dev-tasks/server/reporting.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_state_machine.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_task_file_write_guarded.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_workspace_lease.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reporting_render_golden.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch3_state_and_leases.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) state_machine.py 中 parse_task_file 与 transition_task 未跳过 Markdown 代码围栏与引用块，extract_task_whitelist 的 re.DOTALL 可跨任务头串味且保留前导 './'，transition_task 未保留原始 LF/CRLF 与 UTF-8 BOM 且缺 fsync / WinError 32 重试，_verify_scope_reconciliation 静默吞掉配置异常；(2) task_status.normalize_status 使用无锚点子串匹配，将 'unconfirmed'/'undone'/'skip_check' 误判为有效状态；(3) task_writer.py 在 overwrite 模式省略 status 时把 STATUS_REWORK 重置为 STATUS_PENDING，重复 ID 后者覆盖前者掩盖不可编辑块，无尾换行文件追加粘连，且静默吞掉 register_proposal 异常；(4) workspace_lease.py 的 destructive_context 跳过 renew_or_die，touch() 另建非单例锁，损坏 JSON 非数字字段永久锁死 acquire_or_probe，_atomic_write_json 在 try 外写文件易漏删临时文件；(5) reporting.append_changelog_entry 直接裸 open('w') 无锁无原子替换。目标：全面收敛状态机、任务写入器、工作区租约与变更日志的原子性与解析精度。
```

#### 【目标签名与类型契约】
```
def normalize_status(raw: str) -> str
def append_changelog_entry(changelog_path: str, task_file: str, completed_tasks: List[TaskItem]) -> None
```

#### 【分步改造指引】
1. 加固 state_machine.py：(a) parse_task_file 与 transition_task 增加与 task_status.py 一致的 Markdown 代码围栏 (```/~~~) 与引用块 (>) 跳过逻辑，兼容首行 UTF-8 BOM；(b) transition_task 使用 newline='' 读取并保留原文件换行风格与 BOM，采用 tempfile.mkstemp + flush + os.fsync + 带 WinError 32 短暂重试的 os.replace 及异常清理；(c) extract_task_whitelist 先按顶层任务头切片至当前任务块再提取代码块，支持大小写操作前缀并剥离前导 './'；(d) 将 _verify_scope_reconciliation 中静默吞掉配置加载的 except Exception: pass 改为日志记录。
2. 加固 task_status.normalize_status：将英文别名匹配 ('pending', 'confirmed', 'in progress'/'in_progress', 'completed'/'done', 'skipped'/'skip', 'rework') 改为精确词边界正则（如 \bconfirmed\b），拒绝 'unconfirmed'、'undone'、'skip_check' 等否定或复合词误匹配，同时保持合法中英文状态与 Emoji 变体 100% 兼容。
3. 加固 task_writer.py：(a) 在 mode='overwrite' 中（可编辑与不可编辑任务比对前）使用浅拷贝默认回填 old_st（保护 STATUS_REWORK 不退化为 STATUS_PENDING，且省略 status 的未改动已完成任务不误判报错）；(b) 检测磁盘既有重复 task_id 块并阻断防覆盖不可编辑块；(c) compose_task_document 仅在 appended 非空且前序非空文本不以 '\n' 结尾时插入换行分隔符；(d) 将 register_proposal 处的静默 except Exception: pass 改为 logger.warning(..., exc_info=True)。
4. 加固 workspace_lease.py 与 reporting.py：(a) workspace_lease._atomic_write_json 改用 tempfile.mkstemp(dir=file_path.parent) 并将序列化/写入/flush/fsync 全程置于 try/except 临时文件清理块内；acquire_or_probe 校验 isinstance(data, dict) 并将 float/int 转换异常纳入损坏租约恢复接管；touch() 复用 self._lock 且显式判断 self._generation is not None；destructive_context() 入口在 self.is_held() 之后调用 self.renew_or_die()；release() 对锁/IO 异常打 warning 日志；(b) reporting.append_changelog_entry 外层加 FileLock(f'{os.path.abspath(changelog_path)}.lock', timeout=5.0)，确保父目录存在，使用 mkstemp + open(..., encoding='utf-8')（保持与原 open('w', encoding='utf-8') 完全一致的平台换行行为以通过 golden hash 测试！）+ flush + fsync + os.replace + 异常清理。
5. 在 test_v1_36_batch3_state_and_leases.py 及关联单测中补充围栏内伪任务头忽略、unconfirmed/undone 拒绝、overwrite 保持 STATUS_REWORK、destructive_context 过期拦截与并发原子写 CHANGELOG 单测。

#### 【防御与边缘校验】
- reporting.append_changelog_entry 改造为 FileLock + mkstemp + fsync + os.replace 原子写时，生成的文本字节与换行符必须与既有实现逐字节等价，确保 test_reporting_render_golden.py 的 SHA-256 金标准哈希断言 100% 通过！
- task_writer.compose_task_document 仅在 appended 非空且前序文本不以换行符结尾时补齐分隔换行，确保无追加时 compose_task_document(doc, {}, ()) == doc_text 无损往返断言 100% 通过！
- workspace_lease.is_held() 的纯本地布尔返回语义保持不变（遵守 test_workspace_lease.py:122-137 契约），仅在 destructive_context() 入口执行 renew_or_die() 续租校验！

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch3_state_and_leases.py plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py plugins/quench-dev-tasks/server/tests/test_task_file_write_guarded.py plugins/quench-dev-tasks/server/tests/test_reporting_render_golden.py -q --tb=short && .venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests -q -k "state_machine or reclaim_cas or workspace_lease" --tb=short
```

---

