# 2026-10-24_v1_25_batch2_dual_mode_and_autopilot_harness Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-24

---

## Task List & Status / 任务清单与状态

### 任务 25.2 ✔️ 已完成 — 持久化双模运行时状态（.quench_runtime_mode.json）、可见自动回退与 dev_tasks_status 热切换及角色契约下发

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/server/runtime_mode.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] docs/architecture/ide_tool_schemas.json
[MODIFY] .gitignore
[NEW] plugins/quench-dev-tasks/server/tests/test_dual_mode_runtime_switch.py
```

#### 【缺陷根因与修改目标】
```
当前系统缺少跨会话持久化的双模编排状态管理，无法在 standard（主会话敏捷执行 + 外部 API 审查）与 inverted（主会话 Reviewer + 委派 Runner 执行）之间热切换，且未配置外部 API 时无可见回退提示；同时现有断点消费机制缺少 CAS 校验与任务级作用域隔离，容易引发断点覆盖死锁或跨任务静默失效。目标是：(1) 创建独立模块 runtime_mode.py，实现 .agents/.quench_runtime_mode.json 的加锁原子读写、损坏容错与优先级解析（显式值 > 内置默认；auto_fallback 读取时计算不落盘并附带 fallback_notice 与 runtime_mode_warning）；(2) load_runtime_mode 采用非阻塞快速只读路径（timeout=0，竞争时安全降级无锁读取并置 warning），杜绝 0.5s 阻塞热路径；(3) AutopilotRuntimeState 引入 consumed_for 作用域与 update_runtime_mode 的 CAS expect_set_at 校验（mismatch 时 fail-closed），并在 consume 成功时刷新 set_at 杜绝二次消费，彻底解决 R1/R2/Blocker A/B；(4) 在 server.py 中扩充 dev_tasks_status 支持 switch_mode / switch_reviewer_channel / stop_at / task_file 参数，在 inverted 模式下传入 reviewer channel 时返回具名拒绝码 switch_denied_mode_inverted，在途 🔨 执行中时拒绝模式切换 switch_denied_task_in_progress，在途重置 stop_at（含 stop_at='none'）允许清空 consumed 并重置断点；(5) 保持 status 响应完全向后兼容，下发包含单一前缀信封常量的 SessionRoleContract；(6) 同步工具快照并将运行时文件忽略。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/server/runtime_mode.py
from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any, TypedDict

OrchestrationMode = Literal["standard", "inverted"]
ReviewerChannel = Literal["external_api", "host_subagent"]
StopAtStage = Literal["none", "after_propose", "after_review", "after_confirm", "before_archive", "after_batch"]
ModeSource = Literal["explicit", "auto_fallback", "default"]

class SessionRoleContract(TypedDict):
    role: Literal["runner", "reviewer_orchestrator"]
    primary_guidelines: list[str]
    dispatch_envelope: str  # "[QUENCH-DISPATCH: RUNNER]"
    review_dispatch_envelope: str  # "[QUENCH-DISPATCH: REVIEWER]"
    research_dispatch_envelope: str  # "[QUENCH-DISPATCH: RESEARCH]"
    handshake_rule: str
    runner_subagent_model_hint: Optional[str]

class MutationResultDict(TypedDict, total=False):
    applied: bool
    rejected_reason: Optional[str]
    consume_mismatch: bool
    disk_set_at: Optional[str]
    expected_set_at: Optional[str]

@dataclass
class AutopilotRuntimeState:
    task_file: Optional[str] = None
    stop_at: StopAtStage = "none"
    consumed: bool = False
    consumed_for: Optional[str] = None  # 当前消费所绑定的 task_id（严格任务ID命名空间，batch阶段为 "__batch__:<task_file>"）
    set_at: Optional[str] = None  # ISO-8601 UTC

@dataclass
class RuntimeModeState:
    orchestration_mode: OrchestrationMode = "standard"
    reviewer_channel: ReviewerChannel = "external_api"
    runner_subagent_model_hint: Optional[str] = None
    autopilot: AutopilotRuntimeState = AutopilotRuntimeState()
    updated_at: Optional[str] = None

@dataclass
class EffectiveModeSnapshot:
    effective_mode: OrchestrationMode
    mode_source: ModeSource
    effective_reviewer_channel: Optional[ReviewerChannel]
    runner_subagent_model_hint: Optional[str]
    fallback_notice: Optional[str]
    runtime_mode_warning: Optional[str]
    session_role_contract: SessionRoleContract
    autopilot: AutopilotRuntimeState

def load_runtime_mode(workspace_root: str, external_api_available: bool) -> EffectiveModeSnapshot: ...
def update_runtime_mode(
    workspace_root: str,
    switch_mode: Optional[OrchestrationMode] = None,
    switch_reviewer_channel: Optional[ReviewerChannel] = None,
    stop_at: Optional[StopAtStage] = None,
    consume_stop_at: bool = False,
    expect_set_at: Optional[str] = None,
    consume_for: Optional[str] = None,
    current_task_id: Optional[str] = None,
    runner_subagent_model_hint: Optional[str] = None,
    task_file: Optional[str] = None,
    lock_timeout_s: float = 0.5,
) -> tuple[EffectiveModeSnapshot, bool, MutationResultDict]: ...
```

#### 【分步改造指引】
1. 在 .gitignore 中追加 .agents/.quench_runtime_mode.json 与 .agents/.quench_runtime_mode.json.lock。
2. 新建 plugins/quench-dev-tasks/server/runtime_mode.py，实现 RuntimeModeState、EffectiveModeSnapshot、SessionRoleContract、MutationResultDict。load_runtime_mode 实施读写分离快路径：尝试非阻塞 FileLock(timeout=0)，若超时则免锁尽力读取 JSON 文件并返回 runtime_mode_warning="lock_contended_read_only"，绝不阻塞 PreToolUse 热路径；解析损坏时降级为内置默认并在快照中置 runtime_mode_warning。优先级严格满足：显式值 > 默认值（standard + external_api）；仅当无显式值且外部 API 不可用时，读取时计算 effective_mode="inverted", mode_source="auto_fallback"，附带 fallback_notice，不写磁盘。
3. 实现带 CAS 的 update_runtime_mode：返回 tuple[EffectiveModeSnapshot, bool, MutationResultDict]；当 consume_stop_at=True 时，必须比对 expect_set_at == disk_set_at，若不匹配返回 (snapshot, False, {"applied": False, "consume_mismatch": True, "disk_set_at": ..., "expected_set_at": ...}) 且不落盘（fail-closed）；匹配通过时原子写入 {consumed: True, consumed_for: consume_for or current_task_id, set_at: datetime.now(timezone.utc).isoformat()}（consume 成功时必须同时刷新 set_at 生成新一轮时间戳，杜绝并发二次消费）。consumed_for 严格限定以 task_id 为唯一命名空间，严禁以 task_file 路径作为 fallback。当显式传入新 stop_at 时（包含 stop_at="none"，其作为断点重置路径而非模式切换，在在途状态下同样允许重置），自动生成新 set_at 并重置 consumed=False, consumed_for=None；传入 task_file 时同步绑定至 autopilot.task_file。
4. 实现 generate_session_role_contract(snapshot)，生成结构化 SessionRoleContract（含 role: "runner" 或 "reviewer_orchestrator"、primary_guidelines、dispatch_envelope: "[QUENCH-DISPATCH: RUNNER]"、review_dispatch_envelope: "[QUENCH-DISPATCH: REVIEWER]"、research_dispatch_envelope: "[QUENCH-DISPATCH: RESEARCH]"、handshake_rule: "status_called_by_main_only"，及 runner_subagent_model_hint）。
5. 改造 plugins/quench-dev-tasks/server/server.py 的 dev_tasks_status：新增可选参数 switch_mode: Optional[Literal["standard", "inverted"]] = None、switch_reviewer_channel: Optional[Literal["external_api", "host_subagent"]] = None、stop_at: Optional[Literal["none", "after_propose", "after_review", "after_confirm", "before_archive", "after_batch"]] = None、task_file: Optional[str] = None；若存在 🔨 执行中 任务且仅传入 stop_at（含 stop_at="none"），明确将其作为断点重置路径予以允许，重置断点并清空 consumed 标记（保留 task_file）；若当前已为 inverted 模式且传入 switch_reviewer_channel，拒绝并返回 runtime_mode_changed=False, reason="switch_denied_mode_inverted", runtime_mode_warning="reviewer_channel 仅在 standard 模式下有效；当前为 inverted。"；若存在 🔨 执行中 任务且传入了 switch_mode / switch_reviewer_channel，拒绝切换并返回 reason="switch_denied_task_in_progress"；无上述参数时保持 100% 幂等只读；返回报文在完全保留既有字段前提下追加注入 effective_mode、mode_source、fallback_notice、runtime_mode_warning、session_role_contract、autopilot。
6. 运行 python scripts/export_ide_schemas.py --write 生成更新后的工具快照 docs/architecture/ide_tool_schemas.json，并通过 --check 严格验证。
7. 新建 plugins/quench-dev-tasks/server/tests/test_dual_mode_runtime_switch.py，编写单测覆盖：(1) test_status_read_hotpath_does_not_block_on_lock（非阻塞读快路径）；(2) test_concurrent_double_consume_rejected（CAS 刷新 set_at 杜绝二次消费）；(3) test_consumed_for_never_uses_task_file_key（双任务文件命名空间行为测试）；(4) test_status_response_backward_compat（旧键全集合冻结断言）；(5) test_stop_at_none_clears_consumed_even_when_foreign_task；(6) switch_denied_mode_inverted 与 switch_denied_task_in_progress 拒绝分支；(7) auto_fallback 动态计算不落盘；(8) .gitignore 生效物理验证。

#### 【防御与边缘校验】
CAS lost-update 防护：consume_stop_at=True 必须携带 expect_set_at 比对，成功时刷新 set_at，不匹配 fail-closed 不落盘
读写分离与时延红线：load_runtime_mode 采用非阻塞 timeout=0 快读路径，争用时无锁安全降级并标记 warning，确保 <50ms 预算；仅 update_runtime_mode 允许在 0.5s 内加锁写
跨任务消费隔离：consumed_for 严格以 task_id 为唯一命名空间，严禁 fallback 为 task_file，杜绝跨任务静默失效或死锁
inverted 专属拒绝分支：inverted 模式下修改 reviewer channel 坚决拦截，返回明确具名 reason switch_denied_mode_inverted
dev_tasks_status 响应字典保持完全向后兼容，通过全量旧键集合冻结断言硬性加固
工具签名变更必须同步更新快照，通过 scripts/export_ide_schemas.py --check 门禁

#### 【DoD 验证命令】
```bash
& .\venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_dual_mode_runtime_switch.py plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py -q
& .\venv\Scripts\python.exe scripts/export_ide_schemas.py --check
git check-ignore -v .agents/.quench_runtime_mode.json .agents/.quench_runtime_mode.json.lock
```

---

### 任务 25.3 ✔️ 已完成 — Autopilot compute_next_action 纯函数引擎与状态转移表测试

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/server/autopilot_harness.py
[NEW] plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py
```

#### 【缺陷根因与修改目标】
```
当前工作流在各 MCP 工具执行完毕后仅返回静态结果，缺少面向状态机的接力指引，导致自动化闭环在每一步停机等待人工指令；且此前断点与候选列表计算顺序未确定，可能导致用户在停靠时无法查看候选任务清单。目标是实现独立纯函数引擎 autopilot_harness.py，提供 compute_next_action 纯函数与完整 HarnessNextAction 契约，基于任务快照、有效编排模式、Autopilot 运行时状态与最新事件，确立“先候选后断点”确定性顺序，推导出下一步精准动作（含跨批次连续接力 NEXT_BATCH_PROPOSE 与 ROADMAP_DONE 收官），支持动态注入 max_review_rounds，严格执行 task_id 单一命名空间（以及 batch 阶段明确的 __batch__:<file>）的 consumed_for 作用域校验，并在消费后重新呈现新鲜的 set_at，覆盖全场景状态转移表测试。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/server/autopilot_harness.py
from dataclasses import dataclass
from typing import Literal, Optional, Sequence, Mapping, Any

DEFAULT_MAX_REVIEW_ROUNDS = 2

HarnessActionType = Literal[
    "PROPOSE", "REVIEW", "CONFIRM", "CHECKOUT", "DISPATCH_RUNNER",
    "SYNC_DOCS", "ARCHIVE", "NEXT_BATCH_PROPOSE", "PAUSE_FOR_ACCEPTANCE",
    "BLOCKED", "ROADMAP_DONE"
]

@dataclass(frozen=True)
class TaskStateSnapshot:
    task_id: str
    status: str  # pending, rework, confirmed, in_progress, completed, skipped
    title: str = ""

@dataclass(frozen=True)
class LastEventSnapshot:
    tool_name: str
    success: bool
    result_data: Mapping[str, Any]

@dataclass(frozen=True)
class HarnessNextAction:
    action: HarnessActionType
    reason: str
    instruction: str
    task_file: Optional[str] = None
    task_id: Optional[str] = None
    task_ids: Optional[Sequence[str]] = None
    channel: Optional[str] = None
    model_hint: Optional[str] = None
    stage: Optional[str] = None
    advisory: bool = False
    candidates: Sequence[str] = ()  # 待确认/待领取的任务ID候选列表（按清单正序排列）
    next_batch_tasks: Sequence[str] = ()  # 路线图中扫描出的后续待规划任务或批次标题列表
    roadmap_file: Optional[str] = None
    summary: Optional[str] = None
    expect_set_at: Optional[str] = None  # 命中断点时透传，用于后续 CAS 原子写入
    consume_for: Optional[str] = None    # 命中断点时透传，绑定当前消费任务ID或batch键

def compute_next_action(
    task_states: Sequence[TaskStateSnapshot],
    effective_mode: str,  # "standard" | "inverted"
    reviewer_channel: Optional[str],  # "external_api" | "host_subagent"
    mode_source: str,  # "explicit" | "auto_fallback" | "default"
    stop_at: str,  # "none" | "after_propose" | "after_review" | "after_confirm" | "before_archive" | "after_batch"
    stop_at_consumed: bool,
    consumed_for: Optional[str] = None,
    current_task_id: Optional[str] = None,
    autopilot_set_at: Optional[str] = None,
    review_round: int = 1,
    max_review_rounds: int = DEFAULT_MAX_REVIEW_ROUNDS,
    last_event: Optional[LastEventSnapshot] = None,
    roadmap_pending_batches: Sequence[str] = (),
    roadmap_file: Optional[str] = None,
    task_file: Optional[str] = None,
) -> tuple[HarnessNextAction, bool]: ...
```

#### 【分步改造指引】
1. 创建 plugins/quench-dev-tasks/server/autopilot_harness.py，定义数据模型与纯函数 compute_next_action。实现零 I/O、零网络、零外部依赖设计。确定 roadmap_pending_batches 与 roadmap_file 均由服务端显式预先解析后注入，引擎内部严禁触发文件 I/O。
2. 实现严格确定性的计算与判定流程：Step A（先计算元数据与候选）：无条件计算 candidates（当前所有待确认或已确认待执行的任务 ID，按清单正序）与 next_batch_tasks（路线图待规划批次）；解析当前目标 current_task_id（执行中任务ID > 首个已确认任务ID > 首个pending任务ID；若为 after_batch 阶段则当前范围键规范为 f"__batch__:{task_file}"）；Step B（异常阻断检查）：若 last_event 存在且 success is False，立即返回 BLOCKED(reason=..., instruction=..., candidates=candidates, next_batch_tasks=next_batch_tasks)，consume_stop_at=False；Step C（断点匹配评估）：若命中当前阶段的 stop_at（如 after_propose、after_review 等），且该断点未被当前任务/批次消费（not stop_at_consumed or consumed_for != expected_scope_key），返回 PAUSE_FOR_ACCEPTANCE(stage=stop_at, candidates=candidates, next_batch_tasks=next_batch_tasks, expect_set_at=autopilot_set_at, consume_for=expected_scope_key)，并返回 consume_stop_at=True；Step D（状态机主线推进）：若未命中停靠或当前任务已消费停靠：无任务/仅草案 -> PROPOSE；存在 pending 任务 -> REVIEW（根据 channel 选择 external_api、host_subagent 或 inverted_self）；存在 rework 任务：若 review_round < max_review_rounds，返回 PROPOSE（修订）；若 review_round >= max_review_rounds，返回 PAUSE_FOR_ACCEPTANCE(stage="review_exhausted", candidates=candidates)，consume_stop_at=False；任务已全部通过审查待确认 -> CONFIRM，附带 task_ids 与 candidates；存在已确认待执行任务 -> standard 模式下返回 CHECKOUT，inverted 模式下返回 DISPATCH_RUNNER（附带 task_id、task_file、model_hint）；本批次任务已全部完成/跳过 -> 先返回 SYNC_DOCS(advisory=True)，随后接力 ARCHIVE；归档完成事件后检查 roadmap_pending_batches：若仍有待办批次且 stop_at != "after_batch"，返回 NEXT_BATCH_PROPOSE（附带 next_batch_tasks）；若 stop_at == "after_batch" 且未 consumed，返回 PAUSE_FOR_ACCEPTANCE(stage="after_batch")；若路线图已无待办任务，返回 ROADMAP_DONE。
3. 新建 plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py，单测涵盖：test_pause_carries_candidates_and_next_batch_tasks、test_priority_candidates_before_stop_at、test_consumed_for_never_uses_task_file_key、test_consumed_for_scoped_per_task、test_pause_after_consume_reemits_fresh_expect_set_at、test_max_review_rounds_boundary_exhaustion、test_state_matrix_standard_and_inverted、test_compute_next_action_zero_io_pure。

#### 【防御与边缘校验】
无候选即停靠禁止：PAUSE_FOR_ACCEPTANCE 必须携带已计算的 candidates 与 next_batch_tasks，使用户在停靠时能完整感知队列
纯函数零 I/O：autopilot_harness.py 内部严禁任何磁盘或环境读写，所有状态由参数显式注入
单命名空间校验：consumed_for 严格比对 task_id（batch 阶段比对 __batch__:<file>），绝不回退至普通 task_file 混淆命名空间
确定性优先级：Step A 候选优先 -> Step B 异常阻断 -> Step C 断点停靠 -> Step D 状态流转

#### 【DoD 验证命令】
```bash
& .\venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py -q
```

---

### 任务 25.4 ✔️ 已完成 — 接力棒工具接入、audit_gate.accepted_sources 来源策略与 CAS 失配重封包

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] docs/architecture/ide_tool_schemas.json
[MODIFY] plugins/quench-dev-tasks/server/tests/test_audit_gate.py
[NEW] plugins/quench-dev-tasks/server/tests/test_review_attestation_channel.py
```

#### 【缺陷根因与修改目标】
```
现有 _check_audit_gate 仅识别外部 API 写入的审计记录，导致 host_subagent 与 inverted 自审模式下 confirm 无法通过门禁（报 log_missing 或 no_matching_record）；且当前缺乏凭据来源策略防范 auto_fallback 下自签凭据风险；同时存量审计记录若缺失 source 字段需要在读取端安全向后兼容；此外既有 8 个核心 MCP 工具返回报文缺少 Autopilot 接力棒与 CAS 断点状态写回。目标是：(1) 移除 refine_spec 的自报凭据通道（坚守 INV-3 防角色扮演硬红线，refine_spec 恢复为纯规约强化工具，不开放外部自报 review_* 凭据入参）；(2) 在 AuditGatePolicy 中新增 accepted_sources 字段，在 load_project_config 中将其与 effective_mode 物理耦合，越界配置触发 ConfigError(SAFETY_DOWNGRADE_DENIED)；(3) 改造 _check_audit_gate 使用 _resolve_record_source 进行三态解析（缺失/None 视为 reviewer_client 兼容历史，非 str 或空串返回 record_unparsable，杜绝 falsy 复活），硬拒绝 auto_fallback 自签凭据；(4) 在 8 个工具中接入 harness_next_action，并在 update_runtime_mode 返回 consume_mismatch 时重算并追加 advisory 标记重封包；(5) 在 dev_tasks_archive 中扫描活跃路线图驱动跨批次自动推进。
```

#### 【目标签名与类型契约】
```python
# plugins/quench-dev-tasks/server/project_config.py
_MODE_ACCEPTED_SOURCES: Final[Mapping[str, frozenset[str]]] = MappingProxyType({
    "standard": frozenset({"reviewer_client"}),
    "inverted": frozenset({"reviewer_client", "host_subagent"}),
    "auto_fallback": frozenset({"reviewer_client"}),
})

def _validate_accepted_sources(accepted: Sequence[str], effective_mode: str) -> None:
    """fail-closed：越界 accepted_sources 触发 ConfigError(SAFETY_DOWNGRADE_DENIED)。"""

class AuditGatePolicy(BaseModel):
    enabled: bool = False
    scope: Literal["managed_paths", "all"] = "managed_paths"
    on_missing_record: AuditAction = "block"
    on_degraded: AuditAction = "warn"
    on_internal_error: AuditAction = "allow"
    max_tail_bytes: int = 16384
    record_ttl_seconds: int = 86400
    audit_log_path: Optional[str] = None
    accepted_sources: tuple[str, ...] = ("reviewer_client",)

AuditGateReason = Literal[
    "disabled", "not_managed_scope", "session_bypass_active", "matched",
    "no_matching_record", "record_stale", "record_timestamp_invalid", "record_degraded",
    "tail_window_exhausted", "log_missing", "log_unparsable", "record_unparsable",
    "precondition_changed", "internal_error",
    "record_source_not_accepted", "record_auto_fallback_not_accepted", "record_rework",
]

# plugins/quench-dev-tasks/server/server.py
def _resolve_record_source(rec: Mapping[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """返回 (source, degraded_reason)。source 缺失（key 不存在或 None）→ ("reviewer_client", None)。
    source 存在但非 str 或为空串 → (None, "record_unparsable")。"""
```

#### 【分步改造指引】
1. project_config.py：在 AuditGatePolicy 定义 accepted_sources: tuple[str, ...] = ("reviewer_client",)；在 load_project_config 审计策略加载路径插入 _validate_accepted_sources。当 declared orchestration_mode 为 standard 且 accepted 集合含 host_subagent 时，raise ConfigError(f"{ConfigFault.SAFETY_DOWNGRADE_DENIED}: accepted_sources not permitted in standard mode")；auto_fallback 同理强制 accepted_sources == {"reviewer_client"}。在 AuditGateReason Literal 中加入 "record_unparsable"。
2. 坚守 INV-3 防角色扮演硬红线：不向 dev_tasks_refine_spec 引入 review_source / review_verdict / review_findings_digest 参数，refine_spec 维持纯规约强化设计，避免调用方自报凭据形成提权后门。
3. server.py _check_audit_gate：matching_rec 检出后调用 _resolve_record_source(matching_rec)。若返回 (None, "record_unparsable") → reason="record_unparsable" 并将 "record_unparsable" 纳入 degraded_family 经由 effective_on_degraded 策略路由判定（根据 policy.on_degraded 决定 allow / warn / block）。若 source not in accepted_sources → record_source_not_accepted。若 mode_source == "auto_fallback" and source != "reviewer_client" → record_auto_fallback_not_accepted。若 verdict == "rework" → record_rework。
4. server.py 8 工具 harness CAS 回写：在 dev_tasks_status、dev_tasks_propose、dev_tasks_refine_spec、dev_reviewer_poll、dev_tasks_confirm、dev_tasks_checkout、dev_tasks_complete、dev_tasks_archive 共 8 个工具中接入 harness_next_action = compute_next_action(...)。当 consume_stop_at 为 True 时调用 update_runtime_mode；若返回 mutation.get("consume_mismatch") == True 时，重新 load_runtime_mode 拿最新 snapshot，用其 autopilot.set_at 覆盖 harness_next_action.expect_set_at，并在 reason 后缀追加 " [recomputed after CAS mismatch]"，禁止静默吞掉 mismatch。
5. 在 dev_tasks_archive 成功归档后，扫描 docs/roadmap/ 中处于 ACTIVE 状态的路线图文件：若仍含 ⬜ 待规划 任务且未设断点，下发 NEXT_BATCH_PROPOSE（附带 next_batch_tasks）；若全部完成则下发 ROADMAP_DONE 并清理运行时 autopilot 段。
6. 快照一致性：运行 python scripts/export_ide_schemas.py --check 确保 MCP 工具快照完全同步。
7. 在 test_audit_gate.py 中扩充门禁来源策略测试；新建 plugins/quench-dev-tasks/server/tests/test_review_attestation_channel.py，必须包含以下具名测试断言：test_refine_spec_rejects_self_reported_review_source、test_accepted_sources_standard_mode_forbids_host_subagent、test_accepted_sources_auto_fallback_locked_to_reviewer_client、test_empty_string_source_is_not_resurrected_as_legacy、test_null_source_is_legacy_compat、test_missing_source_key_is_legacy_compat、test_non_str_source_yields_record_unparsable、test_record_unparsable_routes_through_effective_on_degraded、test_harness_cas_mismatch_recomputes_and_reenvelopes。

#### 【防御与边缘校验】
自签凭据攻击面收敛：不向 refine_spec 开设外部自报参数，从物理签名层杜绝伪造凭据
accepted_sources 与 effective_mode 物理耦合，越界配置在 load_project_config 阶段 raise ConfigError(SAFETY_DOWNGRADE_DENIED)
_resolve_record_source 三态解析（missing / None / 空串 / 非 str）闭合 falsy 复活漏洞；缺失 source 键与 None 值明确分派为 legacy 兼容，空串或非 str 一律 record_unparsable
harness CAS mismatch 必须重算 + 追加 advisory 标记，客户端可感知状态漂移；不允许静默丢帧
运行 python scripts/export_ide_schemas.py --check 确保 MCP 工具快照完全同步

#### 【DoD 验证命令】
```bash
& .\venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_audit_gate.py plugins/quench-dev-tasks/server/tests/test_review_attestation_channel.py plugins/quench-dev-tasks/server/tests/test_dual_mode_runtime_switch.py -q
& .\venv\Scripts\python.exe scripts/export_ide_schemas.py --check
& .\venv\Scripts\python.exe scripts/check_prompt_surface.py
```

---

