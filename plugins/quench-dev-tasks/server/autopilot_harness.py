"""Pure Autopilot Harness Decision Engine.

Provides deterministic compute_next_action for Quench DevTasks.
Strict Zero I/O, Zero Network, pure state transition logic.
Bound by Quench DevTasks lifecycle and INV-1..INV-9 invariants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

DEFAULT_MAX_REVIEW_ROUNDS = 2
DEFAULT_MAX_RUNNER_TASKS = 12
DEFAULT_BATCH_OVERLAP_THRESHOLD = 0.30

HarnessActionType = Literal[
    "PROPOSE",
    "REVIEW",
    "CONFIRM",
    "CHECKOUT",
    "DISPATCH_RUNNER",
    "SYNC_DOCS",
    "ARCHIVE",
    "NEXT_BATCH_PROPOSE",
    "PAUSE_FOR_ACCEPTANCE",
    "BLOCKED",
    "ROADMAP_DONE",
]

_STATUS_MAP: Mapping[str, str] = {
    "⬜ 待确认": "pending",
    "pending": "pending",
    "🔄 需返工": "rework",
    "rework": "rework",
    "✅ 已确认": "confirmed",
    "confirmed": "confirmed",
    "🔨 执行中": "in_progress",
    "in_progress": "in_progress",
    "✔️ 已完成": "completed",
    "completed": "completed",
    "⏭️ 跳过": "skipped",
    "skipped": "skipped",
}


def _norm_status(s: str) -> str:
    cleaned = s.strip()
    return _STATUS_MAP.get(cleaned, cleaned)


def _clean_path_for_overlap(p: str) -> str:
    s = str(p).strip()
    if not s or s.startswith("```"):
        return ""
    # strip leading bullet points, numbers, markdown symbols (avoid eating ./ paths)
    s = re.sub(r"^[\s\-\*\+\>\#]+\s*|^\d+\.\s+", "", s).strip()
    # strip operation markers
    s = re.sub(r"^\[\s*(?:MODIFY|NEW|DELETE|RENAME)\s*\]\s*", "", s, flags=re.IGNORECASE).strip()
    # strip quotes and backticks
    s = s.strip("`'\" ").strip()
    # strip markdown link [text](path)
    m_link = re.search(r"\[.*?\]\((.*?)\)", s)
    if m_link:
        s = m_link.group(1).strip()
    # strip comments / parentheses
    s = s.split("（")[0].split("(")[0].strip()
    s = s.strip("`'\" ").strip()
    if s.startswith("file:///"):
        s = s[8:].lstrip("/\\")
    posix_path = s.replace("\\", "/")
    while posix_path.startswith("./"):
        posix_path = posix_path[2:]
    posix_path = posix_path.lstrip("/")
    return posix_path.strip()


# Slice depth mapping for outer container directories (Zero I/O pure contract;
# register new monorepo/container prefixes here rather than probing filesystem):
#   _DEEP_SUBMODULE_CONTAINERS    -> dir_parts[:4] (distinguishes plugins/<pkg>/<mod> vs plugins/<pkg>/<mod>/<submod>)
#   _SHALLOW_SUBMODULE_CONTAINERS -> dir_parts[:2] (distinguishes src/<submod>, docs/<submod>, tests/<submod>)
_DEEP_SUBMODULE_CONTAINERS: frozenset[str] = frozenset({
    "plugins",
    "packages",
    "apps",
    "services",
    "crates",
    "libs",
    "modules",
})
_SHALLOW_SUBMODULE_CONTAINERS: frozenset[str] = frozenset({
    "src",
    "lib",
    "app",
    "pkg",
    "internal",
    "docs",
    "tests",
    "test",
})


def _extract_top_module_dir(p: str) -> str:
    cleaned = p.strip("/")
    if not cleaned:
        return ""
    if "/" not in cleaned:
        return f"__root__:{cleaned}"
    dir_parts = cleaned.split("/")[:-1]
    if dir_parts[0] in _DEEP_SUBMODULE_CONTAINERS:
        return "/".join(dir_parts[:4])
    if dir_parts[0] in _SHALLOW_SUBMODULE_CONTAINERS:
        return "/".join(dir_parts[:2])
    return dir_parts[0]


def compute_batch_overlap_ratio(
    prev_files: Sequence[str],
    curr_files: Sequence[str],
) -> float:
    """Compute structural and directory overlap ratio between two task batches.

    Returns float in range [0.0, 1.0] representing containment in curr_files.
    Zero I/O.
    """
    prev_set = {_clean_path_for_overlap(p) for p in prev_files}
    prev_set.discard("")
    curr_set = {_clean_path_for_overlap(p) for p in curr_files}
    curr_set.discard("")

    if not prev_set or not curr_set:
        return 0.0

    file_ratio = len(prev_set & curr_set) / len(curr_set)

    prev_dirs = {_extract_top_module_dir(p) for p in prev_set}
    curr_dirs = {_extract_top_module_dir(p) for p in curr_set}
    dir_ratio = len(prev_dirs & curr_dirs) / len(curr_dirs) if curr_dirs else 0.0

    return round(max(file_ratio, 0.5 * dir_ratio), 4)


def resolve_runner_dispatch_channel(
    completed_in_batch: int = 0,
    is_rework: bool = False,
    prev_batch_files: Sequence[str] = (),
    curr_batch_files: Sequence[str] = (),
    cumulative_runner_tasks: int = 0,
    max_runner_tasks: int = DEFAULT_MAX_RUNNER_TASKS,
    overlap_threshold: float = DEFAULT_BATCH_OVERLAP_THRESHOLD,
) -> str:
    """Resolve whether to reuse an active runner subagent or spawn a fresh one.

    Rule 1 (Intra-Batch or Rework -> Always Reuse):
        Never split a batch mid-stream or switch runners during rework.
    Rule 2 (Safety Fuse at Batch Boundary):
        If cumulative runner tasks reach max_runner_tasks, spawn fresh.
    Rule 3 (Cross-Batch File/Module Overlap):
        If overlap ratio >= threshold, reuse active runner to retain hot context;
        otherwise, spawn fresh runner to prevent cross-domain pollution.
    Zero I/O.
    """
    # Rule 1: Intra-Batch or Rework -> Always Reuse
    if is_rework or completed_in_batch > 0:
        return "reuse_active"

    # Rule 2: Safety Fuse at Batch Boundary
    if cumulative_runner_tasks >= max_runner_tasks:
        return "spawn_fresh"

    # Rule 3: Cross-Batch File/Module Overlap
    if not prev_batch_files or not curr_batch_files:
        return "spawn_fresh"

    overlap = compute_batch_overlap_ratio(prev_batch_files, curr_batch_files)
    if overlap >= overlap_threshold:
        return "reuse_active"

    return "spawn_fresh"


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "instruction": self.instruction,
            "task_file": self.task_file,
            "task_id": self.task_id,
            "task_ids": list(self.task_ids) if self.task_ids is not None else None,
            "channel": self.channel,
            "model_hint": self.model_hint,
            "stage": self.stage,
            "advisory": self.advisory,
            "candidates": list(self.candidates),
            "next_batch_tasks": list(self.next_batch_tasks),
            "roadmap_file": self.roadmap_file,
            "summary": self.summary,
            "expect_set_at": self.expect_set_at,
            "consume_for": self.consume_for,
        }


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
    runner_subagent_model_hint: Optional[str] = None,
    prev_batch_files: Sequence[str] = (),
    curr_batch_files: Sequence[str] = (),
    cumulative_runner_tasks: int = 0,
) -> Tuple[HarnessNextAction, bool]:
    """Pure decision function for autopilot baton progression.

    Step A (Candidates & Metadata first) -> Step B (Blocked on error)
    -> Step C (Stop-at breakpoint matching) -> Step D (State machine main line).
    Zero I/O.
    """
    # -------------------------------------------------------------------------
    # Step A: Compute metadata and candidates first (deterministic priority)
    # -------------------------------------------------------------------------
    pending_tasks = [t for t in task_states if _norm_status(t.status) == "pending"]
    rework_tasks = [t for t in task_states if _norm_status(t.status) == "rework"]
    confirmed_tasks = [t for t in task_states if _norm_status(t.status) == "confirmed"]
    in_progress_tasks = [t for t in task_states if _norm_status(t.status) == "in_progress"]
    completed_tasks = [t for t in task_states if _norm_status(t.status) in ("completed", "skipped")]

    # candidates: manifest order of all actionable tasks
    actionable_ids: List[str] = []
    for t in task_states:
        ns = _norm_status(t.status)
        if ns in ("pending", "rework", "confirmed", "in_progress"):
            actionable_ids.append(t.task_id)
    candidates: Sequence[str] = tuple(actionable_ids)
    next_batch_tasks: Sequence[str] = tuple(roadmap_pending_batches)

    # Resolve target current_task_id
    resolved_task_id: Optional[str] = None
    if current_task_id:
        resolved_task_id = current_task_id
    elif in_progress_tasks:
        resolved_task_id = in_progress_tasks[0].task_id
    elif confirmed_tasks:
        resolved_task_id = confirmed_tasks[0].task_id
    elif rework_tasks:
        resolved_task_id = rework_tasks[0].task_id
    elif pending_tasks:
        resolved_task_id = pending_tasks[0].task_id

    # -------------------------------------------------------------------------
    # Step B: Exception blocking check
    # -------------------------------------------------------------------------
    if last_event is not None and not last_event.success:
        err_msg = str(last_event.result_data.get("error") or last_event.result_data.get("message") or "Unknown tool error")
        return (
            HarnessNextAction(
                action="BLOCKED",
                reason=f"Tool '{last_event.tool_name}' failed execution: {err_msg}",
                instruction="Inspect tool failure output and resolve error before proceeding / 请检查工具执行失败原因并排除错误后再继续推进。",
                task_file=task_file,
                task_id=resolved_task_id,
                candidates=candidates,
                next_batch_tasks=next_batch_tasks,
                roadmap_file=roadmap_file,
            ),
            False,
        )

    # -------------------------------------------------------------------------
    # Step C: Breakpoint matching & evaluation
    # -------------------------------------------------------------------------
    # Determine the current stage
    current_stage: Optional[str] = None
    if last_event is not None and last_event.tool_name == "dev_tasks_archive":
        current_stage = "after_batch"
    elif last_event is not None and last_event.tool_name == "dev_tasks_complete" and len(completed_tasks) == len(task_states) > 0:
        current_stage = "before_archive"
    elif len(completed_tasks) == len(task_states) > 0 and len(task_states) > 0:
        current_stage = "before_archive"
    elif last_event is not None and last_event.tool_name == "dev_tasks_confirm":
        current_stage = "after_confirm"
    elif last_event is not None and last_event.tool_name in ("dev_reviewer_poll", "dev_tasks_refine_spec"):
        current_stage = "after_review"
    elif last_event is not None and last_event.tool_name == "dev_tasks_propose":
        current_stage = "after_propose"
    elif confirmed_tasks and not in_progress_tasks and not pending_tasks and not rework_tasks:
        current_stage = "after_confirm"
    elif pending_tasks and not rework_tasks and not confirmed_tasks and not in_progress_tasks:
        current_stage = "after_propose"

    # Evaluate stop_at against current_stage
    if stop_at != "none" and current_stage == stop_at:
        expected_scope: str
        if stop_at in ("after_batch", "before_archive"):
            expected_scope = f"__batch__:{task_file}" if task_file else "__batch__"
        else:
            expected_scope = resolved_task_id or (f"__batch__:{task_file}" if task_file else "__batch__")

        if not stop_at_consumed or consumed_for != expected_scope:
            return (
                HarnessNextAction(
                    action="PAUSE_FOR_ACCEPTANCE",
                    stage=stop_at,
                    reason=f"Autopilot breakpoint hit at stage '{stop_at}' for scope '{expected_scope}'",
                    instruction=f"Breakpoint '{stop_at}' reached. Verify state and resume when ready / 命中断点 '{stop_at}'，请确认当前状态后继续推进。",
                    task_file=task_file,
                    task_id=resolved_task_id,
                    candidates=candidates,
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                    expect_set_at=autopilot_set_at,
                    consume_for=expected_scope,
                ),
                True,
            )

    # -------------------------------------------------------------------------
    # Step D: State machine main line advancement
    # -------------------------------------------------------------------------
    # D1: All tasks completed / skipped or archive event
    if last_event is not None and last_event.tool_name == "dev_tasks_archive":
        if roadmap_pending_batches:
            if stop_at == "after_batch" and (not stop_at_consumed or consumed_for != (f"__batch__:{task_file}" if task_file else "__batch__")):
                expected_scope = f"__batch__:{task_file}" if task_file else "__batch__"
                return (
                    HarnessNextAction(
                        action="PAUSE_FOR_ACCEPTANCE",
                        stage="after_batch",
                        reason=f"Autopilot breakpoint hit at stage 'after_batch' for scope '{expected_scope}'",
                        instruction="Batch completed and archived. Review roadmap before starting next batch / 本批次已归档，请复核路线图后再推进下一批次。",
                        task_file=task_file,
                        candidates=(),
                        next_batch_tasks=next_batch_tasks,
                        roadmap_file=roadmap_file,
                        expect_set_at=autopilot_set_at,
                        consume_for=expected_scope,
                    ),
                    True,
                )
            return (
                HarnessNextAction(
                    action="NEXT_BATCH_PROPOSE",
                    reason="Previous batch archived; remaining roadmap batches found / 上一批次已归档，路线图仍有后续待办批次",
                    instruction="Propose next batch of tasks from roadmap / 根据路线图规划下一批次开发任务单。",
                    candidates=(),
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                ),
                False,
            )
        else:
            return (
                HarnessNextAction(
                    action="ROADMAP_DONE",
                    reason="All roadmap batches completed and archived / 路线图全部任务均已完工归档",
                    instruction="Roadmap implementation is complete. No further actions required / 路线图规划内容全量达成。",
                    candidates=(),
                    next_batch_tasks=(),
                    roadmap_file=roadmap_file,
                ),
                False,
            )

    if len(task_states) > 0 and len(completed_tasks) == len(task_states):
        # All tasks in the active file are completed or skipped
        if last_event is not None and last_event.tool_name == "dev_tasks_complete":
            return (
                HarnessNextAction(
                    action="SYNC_DOCS",
                    reason="All tasks in batch completed; documentation sync recommended before archive / 本批次任务已全量完工，建议归档前同步文档",
                    instruction="Review and sync architecture/specification docs before calling dev_tasks_archive / 归档前请同步更新架构与规范文档。",
                    task_file=task_file,
                    advisory=True,
                    candidates=(),
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                ),
                False,
            )
        else:
            return (
                HarnessNextAction(
                    action="ARCHIVE",
                    reason="All tasks completed; proceed to archive task file / 任务已全部完成，推进任务单归档",
                    instruction=f"Archive task file '{task_file}' using dev_tasks_archive / 调用 dev_tasks_archive 归档任务单。",
                    task_file=task_file,
                    candidates=(),
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                ),
                False,
            )

    if len(task_states) == 0:
        if roadmap_pending_batches:
            return (
                HarnessNextAction(
                    action="NEXT_BATCH_PROPOSE",
                    reason="No active tasks found; pending roadmap batches available / 当前无活跃任务单，路线图存在待规划批次",
                    instruction="Propose next development task batch via dev_tasks_propose / 调用 dev_tasks_propose 提出新批次开发任务。",
                    candidates=(),
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                ),
                False,
            )
        else:
            return (
                HarnessNextAction(
                    action="ROADMAP_DONE",
                    reason="No active tasks and no pending roadmap batches / 无活跃任务且路线图无待规划任务",
                    instruction="All work completed / 全部工作已完工。",
                    candidates=(),
                    next_batch_tasks=(),
                    roadmap_file=roadmap_file,
                ),
                False,
            )

    # D2: Handling rework tasks
    if rework_tasks:
        if review_round < max_review_rounds:
            return (
                HarnessNextAction(
                    action="PROPOSE",
                    reason=f"Tasks require rework ({len(rework_tasks)} items in rework queue; review round {review_round}/{max_review_rounds})",
                    instruction="Revise task specifications according to Reviewer critique and update task file / 根据审查意见修订任务单。",
                    task_file=task_file,
                    task_id=rework_tasks[0].task_id,
                    candidates=candidates,
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                ),
                False,
            )
        else:
            return (
                HarnessNextAction(
                    action="PAUSE_FOR_ACCEPTANCE",
                    stage="review_exhausted",
                    reason=f"Review round limit reached ({review_round}/{max_review_rounds}) with tasks needing rework",
                    instruction="Human operator intervention required to resolve rework impasse / 审查轮次已达上限，需人工介入裁决返工分歧。",
                    task_file=task_file,
                    task_id=rework_tasks[0].task_id,
                    candidates=candidates,
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                ),
                False,
            )

    # D3: Handling pending tasks (require review)
    if pending_tasks:
        if effective_mode == "inverted":
            channel = "inverted_main_reviewer"
            instruction = "Inverted mode: Main agent evaluates task specifications against invariants / inverted 模式：主模型基于架构不变量自审任务规约。"
        else:
            channel = reviewer_channel or "external_api"
            instruction = f"Submit tasks to Reviewer via {channel} / 通过 {channel} 提交 Reviewer 进行规约推演。"

        return (
            HarnessNextAction(
                action="REVIEW",
                channel=channel,
                task_file=task_file,
                task_id=pending_tasks[0].task_id,
                candidates=candidates,
                reason=f"Pending tasks require architecture review ({len(pending_tasks)} items pending)",
                instruction=instruction,
                next_batch_tasks=next_batch_tasks,
                roadmap_file=roadmap_file,
            ),
            False,
        )

    # D4: Handling tasks that just passed review and need confirm
    # (If last event was review and there are no pending or rework tasks, confirm them)
    if last_event is not None and last_event.tool_name in ("dev_reviewer_poll", "dev_tasks_refine_spec") and not confirmed_tasks:
        return (
            HarnessNextAction(
                action="CONFIRM",
                task_file=task_file,
                task_ids=tuple(t.task_id for t in task_states if _norm_status(t.status) == "pending"),
                candidates=candidates,
                reason="Review evaluation passed; proceed to confirm tasks / 审查推演通过，推进任务确认",
                instruction="Confirm approved tasks via dev_tasks_confirm / 调用 dev_tasks_confirm 确认通过审查的任务。",
                next_batch_tasks=next_batch_tasks,
                roadmap_file=roadmap_file,
            ),
            False,
        )

    # D5: Handling confirmed or in_progress tasks
    if in_progress_tasks:
        active = in_progress_tasks[0]
        if effective_mode == "inverted":
            dispatch_channel = resolve_runner_dispatch_channel(
                completed_in_batch=len(completed_tasks),
                is_rework=(len(rework_tasks) > 0),
                prev_batch_files=prev_batch_files,
                curr_batch_files=curr_batch_files,
                cumulative_runner_tasks=cumulative_runner_tasks,
            )
            strategy_guidance = (
                "reuse active runner subagent via send_message to retain hot context / 通过 send_message 复用当前 runner 子 Agent 以保全热文件上下文"
                if dispatch_channel == "reuse_active"
                else "spawn a fresh isolated runner subagent for this batch / 为本批次新建独立的 runner 子 Agent"
            )
            return (
                HarnessNextAction(
                    action="DISPATCH_RUNNER",
                    task_file=task_file,
                    task_id=active.task_id,
                    channel=dispatch_channel,
                    model_hint=runner_subagent_model_hint,
                    candidates=candidates,
                    reason=f"Task {active.task_id} is in progress under inverted mode",
                    instruction=f"Dispatch task {active.task_id} execution to runner subagent ({strategy_guidance}) / 派发任务 {active.task_id} 给 runner 子 Agent 施工（{strategy_guidance}）。",
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                ),
                False,
            )
        else:
            return (
                HarnessNextAction(
                    action="CHECKOUT",
                    task_file=task_file,
                    task_id=active.task_id,
                    candidates=candidates,
                    reason=f"Task {active.task_id} is currently in progress",
                    instruction=f"Continue implementing task {active.task_id} and execute DoD assertions / 继续执行任务 {active.task_id} 并运行 DoD 校验。",
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                ),
                False,
            )

    if confirmed_tasks:
        target = confirmed_tasks[0]
        if effective_mode == "inverted":
            dispatch_channel = resolve_runner_dispatch_channel(
                completed_in_batch=len(completed_tasks),
                is_rework=(len(rework_tasks) > 0),
                prev_batch_files=prev_batch_files,
                curr_batch_files=curr_batch_files,
                cumulative_runner_tasks=cumulative_runner_tasks,
            )
            strategy_guidance = (
                "reuse active runner subagent via send_message to retain hot context / 通过 send_message 复用当前 runner 子 Agent 以保全热文件上下文"
                if dispatch_channel == "reuse_active"
                else "spawn a fresh isolated runner subagent for this batch / 为本批次新建独立的 runner 子 Agent"
            )
            return (
                HarnessNextAction(
                    action="DISPATCH_RUNNER",
                    task_file=task_file,
                    task_id=target.task_id,
                    channel=dispatch_channel,
                    model_hint=runner_subagent_model_hint,
                    candidates=candidates,
                    reason=f"Task {target.task_id} confirmed; dispatch to runner subagent under inverted mode",
                    instruction=f"Dispatch task {target.task_id} execution to runner subagent ({strategy_guidance}) / 派发任务 {target.task_id} 给 runner 子 Agent 施工（{strategy_guidance}）。",
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                ),
                False,
            )
        else:
            return (
                HarnessNextAction(
                    action="CHECKOUT",
                    task_file=task_file,
                    task_id=target.task_id,
                    candidates=candidates,
                    reason=f"Task {target.task_id} confirmed and ready for checkout",
                    instruction=f"Check out task {target.task_id} via dev_tasks_checkout / 调用 dev_tasks_checkout 检出任务 {target.task_id}。",
                    next_batch_tasks=next_batch_tasks,
                    roadmap_file=roadmap_file,
                ),
                False,
            )

    # Fallback to confirm or propose
    return (
        HarnessNextAction(
            action="CONFIRM",
            task_file=task_file,
            task_ids=candidates,
            candidates=candidates,
            reason="Tasks ready for confirmation / 任务待确认",
            instruction="Confirm tasks via dev_tasks_confirm / 调用 dev_tasks_confirm 确认任务。",
            next_batch_tasks=next_batch_tasks,
            roadmap_file=roadmap_file,
        ),
        False,
    )
