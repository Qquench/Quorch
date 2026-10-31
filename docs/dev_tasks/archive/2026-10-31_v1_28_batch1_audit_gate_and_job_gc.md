# 2026-10-31_v1_28_batch1_audit_gate_and_job_gc Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-31

---

## Task List & Status / 任务清单与状态

### 任务 28.1 ✔️ 已完成 — 显式委派模式（Explicit inverted）AuditGate 免外部凭据闭环与防回退绕过加固

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/rules/dev-tasks-discipline.md
[MODIFY] plugins/quench-dev-tasks/server/tests/test_audit_gate.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_review_attestation_channel.py
```

#### 【缺陷根因与修改目标】
```
根因：当工作区通过 switch_mode='inverted' 显式切换为委派编排模式（effective_mode == 'inverted' 且 mode_source == 'explicit'）时，主会话本身即为用户指定的 reviewer_orchestrator（effective_reviewer_channel = None），无需也不应调用外部 Reviewer HTTP API；但 server.py 的 _check_audit_gate 仍无条件要求 verdicts.jsonl 中存在外部审查记录，在 log_missing 或无匹配记录时触发阻断。目标：在 AuditGateReason 新增 'explicit_inverted_orchestrator'，使 _check_audit_gate 仅在显式委派模式且无外部匹配记录（log_missing / tail_window_exhausted / no_matching_record）时安全放行，同时保留已有匹配异常记录拦截及 auto_fallback 硬门禁。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/server/project_config.py
AuditGateReason = Literal[
    "disabled",
    "not_managed_scope",
    "session_bypass_active",
    "explicit_inverted_orchestrator",
    "matched",
    "record_stale",
    "record_degraded",
    "record_timestamp_invalid",
    "record_unparsable",
    "record_source_not_accepted",
    "record_auto_fallback_not_accepted",
    "record_rework",
    "tail_window_exhausted",
    "no_matching_record",
    "log_missing",
    "log_unparsable",
    "internal_error",
    "precondition_changed",
]
```

#### 【分步改造指引】
1. 在 `plugins/quench-dev-tasks/server/project_config.py` 的 `AuditGateReason` Literal 联合类型（约 L662-668）中新增字面量 `"explicit_inverted_orchestrator"`（使总枚举数由 17 增至 18）。
2. 在 `plugins/quench-dev-tasks/server/server.py` 的 `_check_audit_gate` 中新增辅助布尔判定 `_is_explicit_inverted`（通过 `ext_avail = _is_external_api_available(workspace_root, config)` 与 `snap = load_runtime_mode(workspace_root, ext_avail)` 计算 `snap.effective_mode == "inverted" and snap.mode_source == "explicit"`，异常时回退 `False`），并复用该 `snap.mode_source` 消除 L1248-1254 的重复读取：当处于 `log_missing`（step 3，文件不存在）或 `matching_rec is None`（step 9/10，可读尾部无匹配记录）且 `_is_explicit_inverted` 为 `True` 时，返回 `{"allowed": True, "reason": "explicit_inverted_orchestrator", "artifact_ref": target_ref, "audit_ref": None, "parse_skipped_lines": parse_skipped_lines}`（step 3 处 `parse_skipped_lines` 为 `0`）。注意：`log_unparsable` 与 `matching_rec is not None` 的所有分支（含 `record_rework`、`record_stale`、`record_unparsable`、`record_auto_fallback_not_accepted`）保持原判据不变。
3. 在 `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md` 的 `## 7. Pre-Confirm 审计策略门禁纪律`（§7.③ 确定性守卫序阶梯）中补充说明 `explicit_inverted_orchestrator`：当工作区处于显式委派编排模式（`effective_mode == "inverted"` 且 `mode_source == "explicit"`，旗舰主会话直接担任 `reviewer_orchestrator`）且无匹配外部审查记录时放行；`auto_fallback` 模式绝不适用该放行。
4. 更新 `plugins/quench-dev-tasks/server/tests/test_audit_gate.py`（将 `test_ladder_predicate_exclusivity_matrix` 的 `AuditGateReason` 枚举数断言更新为 `18` 并覆盖 `explicit_inverted_orchestrator` 分支）与 `plugins/quench-dev-tasks/server/tests/test_review_attestation_channel.py`（新增集成单测验证：① 显式 `switch_mode="inverted"` 下无 `verdicts.jsonl` 或无匹配记录时 `dev_tasks_confirm` 以 `explicit_inverted_orchestrator` 放行；② `auto_fallback` 委派模式下无记录仍被 `no_matching_record` 阻断；③ 显式 `inverted` 模式下若账本已存在匹配 `verdict="rework"` 记录仍被 `record_rework` 阻断）。

#### 【防御与边缘校验】
- 严防降级绕过：`mode_source == 'auto_fallback'`（例如未配置外部 API 时的自动降级委派）绝不触发 `explicit_inverted_orchestrator` 放行，仍严格走 `log_missing` / `no_matching_record` / `record_auto_fallback_not_accepted` 原有拦截分支。
- 严防坏记录被掩盖：当审计日志可读且存在匹配 `target_ref` 的记录（`matching_rec is not None`）时，绝不提前短路放行，确保 `record_rework`、`record_unparsable`、`record_stale`、`record_source_not_accepted`、`record_degraded` 等既有守卫阶梯 100% 保持原语义；`log_unparsable` 亦保持原语义不掩盖损坏日志。
- 纪律文档合规：更新 `dev-tasks-discipline.md` §7 时保留全部既有章节标题基线，且严禁出现 `test_anti_roleplay_discipline_contract.py` 禁止的角色扮演表述。
- 核心模块中性铁律（INV-5）：`project_config.py` 与 `server.py` 代码及注释中严禁出现任何模型厂商或特定模型名称字面量。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_audit_gate.py plugins/quench-dev-tasks/server/tests/test_review_attestation_channel.py plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q
```

---

### 任务 28.2 ✔️ 已完成 — 固化 POLL_WAIT_MAX_S_HARD_CEILING 常量 SSOT 与 ReviewerJobSupervisor 终态作业机会式 GC

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tool_surface_constants.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/reviewer_jobs.py
[MODIFY] dev_tasks_mcp_specification.md
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_longpoll_v124.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py
```

#### 【缺陷根因与修改目标】
```
根因：(1) `server.py` 的 `_clamp_wait` 仍使用内联魔法数字 `25.0`，未抽取至 `tool_surface_constants.py` SSOT；(2) `ReviewerJobSupervisor.gc_terminal_jobs()` 未在 `submit()`、`cancel()`、`reconcile_on_load()` 中机会式调用，且原实现按单会话目录静态长度判定 `len(record_files) > max_records`、未清理已清空的会话子目录，导致长期使用后 `jobs/` 终态产物堆积并间接撑大 `compute_protected_logs` 保护集。目标：固化 `POLL_WAIT_MAX_S_HARD_CEILING = 25.0` 常量 SSOT，改进 `gc_terminal_jobs` 全局终态排序裁剪与空目录回收，并在 `submit`（位于 `compute_protected_logs` 之前）、`cancel`、`reconcile_on_load` 中机会式触发。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/server/tool_surface_constants.py
POLL_WAIT_MAX_S_HARD_CEILING: Final[float] = 25.0

# plugins/quench-dev-tasks/server/reviewer_jobs.py
def gc_terminal_jobs(self, *, max_records: int = 100, max_age_s: float = 1800.0) -> int: ...
```

#### 【分步改造指引】
1. 在 `plugins/quench-dev-tasks/server/tool_surface_constants.py` 中新增导出常量 `POLL_WAIT_MAX_S_HARD_CEILING: Final[float] = 25.0`，并在 `__all__` 中导出；在 `plugins/quench-dev-tasks/server/server.py` 顶部导入该常量，将 `_clamp_wait` 中的硬编码 `25.0` 替换为 `POLL_WAIT_MAX_S_HARD_CEILING`。
2. 在 `dev_tasks_mcp_specification.md` 描述 `dev_reviewer_poll` 的 `wait_max_s` 参数上限处，补充注明其服务端硬上限由 `tool_surface_constants.POLL_WAIT_MAX_S_HARD_CEILING`（`25.0` 秒）统一约束。
3. 在 `plugins/quench-dev-tasks/server/reviewer_jobs.py` 中优化 `gc_terminal_jobs(self, *, max_records: int = 100, max_age_s: float = 1800.0) -> int`：跨 `self._jobs_base` 下所有会话目录收集 `rec.state in TERMINAL_STATES` 的 `(mtime, r_file, rec)` 列表并按 `mtime` 降序排列（最新在前），仅对 `now - mtime >= max_age_s` 或全局终态排名索引 `idx >= max_records` 的终态记录删除 `r_file`、`lock_file`、`res_file`（若该会话 `results/` 子目录为空也尝试 `rmdir()`，若会话目录 `s_dir` 已无任何 `.record.json` 且为空目录则尝试 `rmdir()`，所有 `OSError` 静默忽略）。
4. 在 `ReviewerJobSupervisor` 的三处生命周期入口接入机会式 `try: self.gc_terminal_jobs() except Exception: pass`：① `submit()` 尾部机会式清理块的首行（必须在 `compute_protected_logs(...)` 调用之前执行，使超期终态作业不再占用日志保护名额）；② `cancel()` 完成终态迁移后返回前；③ `reconcile_on_load()` 扫描结束返回 `orphaned` 前。
5. 在 `test_reviewer_poll_longpoll_v124.py` 增加对 `POLL_WAIT_MAX_S_HARD_CEILING == 25.0` 及 `_clamp_wait` 绑定关系的断言；在 `test_reviewer_jobs_log_quota.py` 增加单测验证：① 超 `max_age_s` 的历史终态作业在下次 `submit()` 时被自动机会式 GC 且空会话目录被清理，同时不再阻塞超额 `.log` 文件裁剪；② 未超 `max_age_s` 的近期终态作业在 `max_records` 以内保留完好，跨会话超出 `max_records` 时仅保留最新 `max_records` 条终态记录且活跃非终态作业绝不被误删。

#### 【防御与边缘校验】
- 日志配额契约不变量：严禁修改 `log_naming.py` 中 `REVIEWER_TERMINAL_LOG_RETENTION = 40` 与 `REVIEWER_LOG_QUOTA_KEEP = 20` 的数值关系，确保 `test_reviewer_log_retention_semantics.py` 100% 绿灯。
- `reviewer_jobs.py` 静态隔离守卫：`test_reviewer_jobs.py::test_no_ctx_leak_into_reviewer_jobs` 静态扫描源码禁止出现子串 `ctx:`、`ctx.`、`ctx =`，编写代码与注释时严禁引入上述字符序列，且严禁出现模型厂商字面量（INV-5）。
- 并发与活跃作业保护：`gc_terminal_jobs` 仅回收 `rec.state in TERMINAL_STATES` 的作业；清理空会话子目录时须确认目录内无任何 `.record.json` 或剩余文件，并对 `OSError` / `FileNotFoundError` 幂等静默容错，绝不阻塞主流程。
- 工具表面契约守恒：`tool_surface_constants.py` 新增常量后不改变 `EXPECTED_TOOL_NAMES` 与 `TOOL_COUNT`（保持 16），确保 `test_tool_surface_contract.py` 与 `test_missing_sentinel_singleton.py` 通过。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_poll_longpoll_v124.py plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_log_quota.py plugins/quench-dev-tasks/server/tests/test_reviewer_log_retention_semantics.py plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py plugins/quench-dev-tasks/server/tests/test_tool_surface_contract.py -q
```

---

