# 2026-11-26_v1_36_batch4_reviewer_jobs_and_engine Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-26

---

## Task List & Status / 任务清单与状态

### 任务 36.8 ✔️ 已完成 — 修复 reviewer_jobs 孤儿态回弹 RUNNING、on_prog 无锁漏刷墙钟与取消/恢复缺陷

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/reviewer_jobs.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_watch.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_longpoll_v124.py
[NEW] plugins/quench-dev-tasks/server/tests/test_v1_36_batch4_reviewer_and_engine.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) reviewer_jobs.py 中 supervisor.poll() 对磁盘仍为 RUNNING 的超时孤儿任务走非终态分支并在 2s 节流窗内跳过探针，将 watch() 已识别的 ORPHANED 重新翻回 RUNNING 造成死循环轮询；(2) _launch_worker 的 on_prog() 未加作业 FileLock 进行无锁读改写（可覆盖并发终态），且只更新 updated_monotonic 从不更新 updated_wall_utc，导致运行超过 lease_ttl_s (300s) 的健康任务被误判 ORPHANED；(3) cancel() 丢失运行期累积的 tokens_accum，watch() 漏透传 liveness_probe_interval_s，reconcile_on_load() 漏恢复崩溃残留的 CANCELLED_PENDING_REAP 任务；(4) Windows 下 _ExemptInodeTracker 与 _snapshot_business_state_scandir 在 (st_dev, st_ino)==(0,0) 时发生键碰撞且未强制 _maxsize。目标：在 100% 遵守 W10 零写契约的前提下闭环异步审查监督器生命周期。
```

#### 【目标签名与类型契约】
```
def poll(self, job_id: str, *, session_id: str) -> dict[str, Any]
def reconcile_on_load(self) -> list[str]
```

#### 【分步改造指引】
1. 修复 supervisor.poll() 孤儿终态投影（严守 W10 零写）：在 supervisor.poll() 非终态分支调用 read_snapshot（或无节流复核 is_record_orphaned / probe_lease_health），当 snapshot.state == 'ORPHANED' 或 not snapshot.is_healthy 时，在内存中通过 dataclasses.replace(record, state=JobState.ORPHANED, degraded_reason=record.degraded_reason or 'orphaned') 调用 project_terminal(..., None) 直接返回终态 ORPHANED 投影，不触发磁盘写入。
2. 修复 on_prog() 锁保护与心跳墙钟刷新：在 on_prog() 中维护内存实时计数 self._live_tokens[record.job_id] = tokens，并获取 FileLock(self._get_lock_path(record.session_id, record.job_id), timeout=5.0) 后重读 curr；仅当 curr.state == JobState.RUNNING 时同时更新 progress、updated_monotonic=time.monotonic() 与 updated_wall_utc=datetime.now(timezone.utc).isoformat()，杜绝无锁覆盖终态与 >300s 假孤儿。
3. 修复 cancel() token 计量、watch() 参数透传与崩溃恢复：(a) cancel() 读取 max(record.tokens_billed_after_cancel or 0, self._live_tokens.get(val_id, 0), record.progress.approx_reasoning_tokens if record.progress else 0) 写入 tokens_billed_after_cancel，并在存在未结束后台任务/线程时协调安全的日志 unpin 时机（保持既有同步 cancel 单测断言兼容）；(b) 在 watch() 的两处 _read_snapshot_sync 调用中透传 liveness_probe_interval_s=liveness_probe_interval_s；(c) 在 is_record_orphaned() 与 reconcile_on_load() 中纳入 JobState.CANCELLED_PENDING_REAP 的超时恢复与日志 unpin。
4. 修复 Windows (0, 0) 追踪键碰撞：在 _ExemptInodeTracker.register/is_exempt 与 _snapshot_business_state_scandir 中，当 _inode_key == (0, 0) 时以规范化绝对路径字符串作为区分键（严禁在 _snapshot_business_state_scandir 内调用 os.stat/Path.stat），并在 register() 中强制实施 self._maxsize 上限。
5. 在 test_v1_36_batch4_reviewer_and_engine.py 及关联测试中新增超时孤儿经 dev_reviewer_poll 返回终态 ORPHANED、>300s 活跃任务刷墙钟不误判孤儿、watch 自定义探针间隔、CANCELLED_PENDING_REAP 重启恢复及 Windows (0,0) 多文件隔离单测。

#### 【防御与边缘校验】
- 严守 W10 轮询零磁盘写入契约：supervisor.poll() 与 watch() 期间绝对禁止向磁盘写入或修改 *.record.json / verdicts.jsonl / 日志文件；探测到 ORPHANED 时必须在内存中构造终态投影返回！
- 严守 test_architecture_hygiene.py:426-454 AST 门禁：_snapshot_business_state_scandir 内部严禁调用 os.stat 或 Path.stat（仅允许使用 scandir DirEntry.stat 并对 (0, 0) 回退路径键）！
- 保持 POLL_NONTERMINAL_FIELDS (6 字段 <=1024B)、POLL_TERMINAL_FIELDS 与 PIN_RELEASABLE_STATES 既有单测契约 100% 兼容！

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch4_reviewer_and_engine.py plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_watch.py plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py plugins/quench-dev-tasks/server/tests/test_reviewer_poll_longpoll_v124.py plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q --tb=short
```

---

### 任务 36.9 ✔️ 已完成 — 打通流式引擎异常继承/断流、RotatingFileSink 线程锁与零 stat 日志/审计闭环

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/reviewer_engine.py
[MODIFY] plugins/quench-dev-tasks/server/consultation.py
[MODIFY] plugins/quench-dev-tasks/server/log_naming.py
[MODIFY] plugins/quench-dev-tasks/server/observability_policy.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_log_naming.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_observability_policy.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_v1_36_batch4_reviewer_and_engine.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) reviewer_engine.py 中 ReviewerAuthError / ReviewerTimeoutError / ReviewerNotConfiguredError 继承自 ReviewerError 而非 ReviewerEngineError，导致 stream_chat() 抛出的真实异常穿透 consultation._execute_consultation() 漏写降级结果与审计；且 AbortHandle.set_target 从未绑定底层 HTTP 响应，_stream_worker 无超时 chunk_queue.put 在消费者早退时死锁，_iter_sse_payloads 将 IncompleteRead 吞为正常 EOF；(2) RotatingFileSink 缺少线程锁，architecture_doc 缺少路径禁锢，complete(stream=True) 缺体积/截止时间上限，AdaptiveHeartbeatSink 在工作线程泄漏未 await 协程；(3) log_naming.py 在启用 ActiveLogRegistry 时逐文件调 realpath 违背零 stat 契约，主日志锁定时误删 .1.log；(4) observability_policy.py 中 _structured_truncate 混合载荷整包丢失，emit_verdict 的 makedirs 在 try 外，且记录结构与 server._check_audit_gate 存在字段代差。目标：打通流式引擎异常/断流闭环、线程安全与零 stat 日志/审计健壮性。
```

#### 【目标签名与类型契约】
```
class RotatingFileSink: ... # internal threading.RLock
def _structured_truncate(self, record: dict[str, Any], orig_bytes: int) -> str
```

#### 【分步改造指引】
1. 修复异常捕获、AbortHandle 接线与流式队列死锁 (reviewer_engine.py, consultation.py)：(a) 让 ReviewerAuthError / ReviewerTimeoutError / ReviewerNotConfiguredError 同时兼容或由 consultation._execute_consultation() 显式分类捕获全部 ReviewerError 子类（映射 auth_401 / timeout / reviewer_not_configured / connect_error / network，确保 findings=='' 并完整写入审计与遥测）；(b) 在 stream_chat() / complete() 支持可选 abort_handle 参数并在打开 HTTP 响应后调用 abort_handle.set_target(resp)，从 consultation._execute_consultation 透传 abort_handle；(c) _stream_worker 改用带 timeout=0.2 与 stop_event 轮询的入队辅助函数，消费者 finally 排空队列，捕获 HTTPException/Exception 入队错误标记，并在 _iter_sse_payloads 中将 IncompleteRead/HTTPException 向上抛出而非当作正常 EOF。
2. 加固 RotatingFileSink、路径沙箱与流式预算 (reviewer_engine.py, consultation.py)：(a) 为 RotatingFileSink 增加 threading.RLock 保护 write_chunk_text / flush / close / on_heartbeat / _rotate_if_needed；(b) 在 PromptAssembler.build_static_system_prefix 与 consultation.build_static_prefix 中使用 path_guard.sanitize_workspace_path 约束 config.architecture_doc；(c) 在 complete(stream=True) 中强制检查 MAX_RESPONSE_BYTES 与 deadline，重试退避 sleep 钳制不超过 max(0.0, deadline - time.monotonic())；(d) AdaptiveHeartbeatSink.on_heartbeat 在无事件循环捕获 RuntimeError 时调用 res.close() 消除未 await 协程告警。
3. 修复 log_naming.py 零 stat 注册表匹配与轮转备份保护：在 ActiveLogRegistry 中同步维护基于 norm_path_pure 的纯词法归一化键索引（pin/unpin 时写入规范化键，GC 扫描时优先用预先对齐过目录前缀的纯词法键判定 is_pinned/is_reclaimable，彻底消除逐文件 realpath/lstat 调用）；仅在主 .log 成功删除或本不存在时才连带删除 .1.log（PermissionError 时保留 .1.log）；修复 purge_legacy 对 protected_paths、max_deletions、timeout_s 的遵守且跳过时不递减 excess。
4. 修复 observability_policy.py 与 server._check_audit_gate 互操作：(a) emit_verdict 将 os.makedirs 移入 try/except 并在 flush 后调用 os.fsync；(b) _structured_truncate 在字符串二分压缩后若仍超限，继续压缩非字符串容器字段并对顶层超长字段做兜底截断保证严格 <= max_record_bytes；(c) _get_consultation_telemetry_sink 对路径先 normpath/abspath 归一化再走底层 lru_cache（透传暴露 .cache_info 与 .cache_clear 方法）；(d) 在 server._check_audit_gate 中兼容读取顶层 ts 时间戳及嵌套 payload 中的审查字段，使 FileVerdictAuditSink 记录可被正常识别。
5. 在 test_v1_36_batch4_reviewer_and_engine.py 及关联测试中新增 ReviewerAuthError/TimeoutError/IncompleteRead 降级闭环、AbortHandle 物理关闭响应流、RotatingFileSink 多线程并发写与轮转、带 ActiveLogRegistry 的零 stat GC 断言及混合大载荷截断单测。

#### 【防御与边缘校验】
- 严守 INV-3 (降级响应 findings 必须严格等于 '')、INV-4 (零 stdout 输出)、INV-5 (核心模块零新增厂商硬编码) 与 INV-9 (唯一出口 ReviewerClient)！
- 严守 log_naming.py 零 stat 契约：test_log_naming.py 的 AST 与运行期零 stat 门禁必须 100% 通过，且 test_reviewer_log_retention_semantics.py 的 protected_paths 保全契约不可退化！
- 保持 FileVerdictAuditSink 记录的 ts 与 payload 字段兼容 test_observability_policy.py，保持 _get_consultation_telemetry_sink 的 .cache_info() 与 .cache_clear() 接口兼容 test_consultation_telemetry.py！

#### 【DoD 验证命令】
```bash
.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_v1_36_batch4_reviewer_and_engine.py plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py plugins/quench-dev-tasks/server/tests/test_log_naming.py plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py plugins/quench-dev-tasks/server/tests/test_observability_policy.py plugins/quench-dev-tasks/server/tests/test_consultation_telemetry.py plugins/quench-dev-tasks/server/tests/test_audit_gate.py plugins/quench-dev-tasks/server/scripts/../tests/test_no_api_bypass.py -q --tb=short && .venv\Scripts\python.exe plugins/quench-dev-tasks/scripts/check_no_api_bypass.py
```

---

