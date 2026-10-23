"""Runtime mode persistence, effective mode resolution, and autopilot state management.

Bound by Quench DevTasks lifecycle.
Zero I/O in pure paths, non-blocking reads on hot paths.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple, TypedDict

from filelock import FileLock, Timeout

OrchestrationMode = Literal["standard", "inverted"]
ReviewerChannel = Literal["external_api", "host_subagent"]
StopAtStage = Literal["none", "after_propose", "after_review", "after_confirm", "before_archive", "after_batch"]
ModeSource = Literal["explicit", "auto_fallback", "default"]

VALID_ORCHESTRATION_MODES: frozenset[str] = frozenset({"standard", "inverted"})
VALID_REVIEWER_CHANNELS: frozenset[str] = frozenset({"external_api", "host_subagent"})
VALID_STOP_AT_STAGES: frozenset[str] = frozenset({
    "none", "after_propose", "after_review", "after_confirm", "before_archive", "after_batch"
})


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_file": self.task_file,
            "stop_at": self.stop_at,
            "consumed": self.consumed,
            "consumed_for": self.consumed_for,
            "set_at": self.set_at,
        }


@dataclass
class RuntimeModeState:
    orchestration_mode: Optional[OrchestrationMode] = None  # None indicates not explicitly set
    reviewer_channel: ReviewerChannel = "external_api"
    runner_subagent_model_hint: Optional[str] = None
    autopilot: AutopilotRuntimeState = field(default_factory=AutopilotRuntimeState)
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "reviewer_channel": self.reviewer_channel,
            "runner_subagent_model_hint": self.runner_subagent_model_hint,
            "autopilot": self.autopilot.to_dict(),
            "updated_at": self.updated_at,
        }
        if self.orchestration_mode is not None:
            res["orchestration_mode"] = self.orchestration_mode
        return res


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "effective_mode": self.effective_mode,
            "mode_source": self.mode_source,
            "effective_reviewer_channel": self.effective_reviewer_channel,
            "runner_subagent_model_hint": self.runner_subagent_model_hint,
            "fallback_notice": self.fallback_notice,
            "runtime_mode_warning": self.runtime_mode_warning,
            "session_role_contract": self.session_role_contract,
            "autopilot": self.autopilot.to_dict(),
        }


def get_runtime_mode_path(workspace_root: str) -> str:
    return os.path.join(workspace_root, ".agents", ".quench_runtime_mode.json")


def get_runtime_mode_lock_path(workspace_root: str) -> str:
    return os.path.join(workspace_root, ".agents", ".quench_runtime_mode.json.lock")


def generate_session_role_contract(
    effective_mode: OrchestrationMode,
    runner_subagent_model_hint: Optional[str] = None,
) -> SessionRoleContract:
    if effective_mode == "inverted":
        return {
            "role": "reviewer_orchestrator",
            "primary_guidelines": [
                "主模型作为审查编排者（Reviewer Orchestrator），负责架构规划、规约强化与任务分派。",
                "执行施工委托给 Runner 子 Agent，通过标准信封派发并附带上下文。",
                "主模型仅在规约/文档层操作，严禁直接篡改生产受管源码（INV-6）。",
            ],
            "dispatch_envelope": "[QUENCH-DISPATCH: RUNNER]",
            "review_dispatch_envelope": "[QUENCH-DISPATCH: REVIEWER]",
            "research_dispatch_envelope": "[QUENCH-DISPATCH: RESEARCH]",
            "handshake_rule": "status_called_by_main_only",
            "runner_subagent_model_hint": runner_subagent_model_hint,
        }
    else:
        return {
            "role": "runner",
            "primary_guidelines": [
                "主模型作为执行者（Runner），负责代码修改、单测编写与执行交付。",
                "遇到重大架构分歧或审查需求时，调用 dev_reviewer_submit 提交外部 Reviewer 评估。",
                "严禁自我扮演 Reviewer，严格遵守 INV-3 反自我伪装红线。",
            ],
            "dispatch_envelope": "[QUENCH-DISPATCH: RUNNER]",
            "review_dispatch_envelope": "[QUENCH-DISPATCH: REVIEWER]",
            "research_dispatch_envelope": "[QUENCH-DISPATCH: RESEARCH]",
            "handshake_rule": "status_called_by_main_only",
            "runner_subagent_model_hint": runner_subagent_model_hint,
        }


def load_runtime_mode(workspace_root: str, external_api_available: bool) -> EffectiveModeSnapshot:
    mode_path = get_runtime_mode_path(workspace_root)
    lock_path = get_runtime_mode_lock_path(workspace_root)
    runtime_mode_warning: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None

    if os.path.isfile(mode_path):
        lock = FileLock(lock_path, timeout=0)
        try:
            with lock:
                with open(mode_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
        except (Timeout, OSError):
            runtime_mode_warning = "lock_contended_read_only"
            try:
                with open(mode_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
            except Exception as e:
                runtime_mode_warning = f"runtime_mode_corrupt_read_fallback: {e}"
                raw_data = None
        except json.JSONDecodeError as e:
            runtime_mode_warning = f"runtime_mode_corrupt_json: {e}"
            raw_data = None
        except Exception as e:
            runtime_mode_warning = f"runtime_mode_read_error: {e}"
            raw_data = None

    if raw_data is None:
        raw_data = {}

    explicit_mode = raw_data.get("orchestration_mode")
    reviewer_channel = raw_data.get("reviewer_channel", "external_api")
    runner_subagent_model_hint = raw_data.get("runner_subagent_model_hint")
    autopilot_dict = raw_data.get("autopilot", {})

    if explicit_mode in VALID_ORCHESTRATION_MODES:
        effective_mode: OrchestrationMode = explicit_mode
        mode_source: ModeSource = "explicit"
        fallback_notice = None
    else:
        if not external_api_available:
            effective_mode = "inverted"
            mode_source = "auto_fallback"
            fallback_notice = "外部 Reviewer API 未配置或不可用，运行时自动回退为 inverted 模式。主模型执行自审，严守 INV-3/INV-6/INV-9 规范。"
        else:
            effective_mode = "standard"
            mode_source = "default"
            fallback_notice = None

    effective_reviewer_channel: Optional[ReviewerChannel] = (
        reviewer_channel if effective_mode == "standard" else None
    )

    raw_stop_at = autopilot_dict.get("stop_at", "none")
    autopilot = AutopilotRuntimeState(
        task_file=autopilot_dict.get("task_file"),
        stop_at=raw_stop_at if raw_stop_at in VALID_STOP_AT_STAGES else "none",
        consumed=bool(autopilot_dict.get("consumed", False)),
        consumed_for=autopilot_dict.get("consumed_for"),
        set_at=autopilot_dict.get("set_at"),
    )

    role_contract = generate_session_role_contract(effective_mode, runner_subagent_model_hint)

    return EffectiveModeSnapshot(
        effective_mode=effective_mode,
        mode_source=mode_source,
        effective_reviewer_channel=effective_reviewer_channel,
        runner_subagent_model_hint=runner_subagent_model_hint,
        fallback_notice=fallback_notice,
        runtime_mode_warning=runtime_mode_warning,
        session_role_contract=role_contract,
        autopilot=autopilot,
    )


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
    external_api_available: bool = True,
) -> Tuple[EffectiveModeSnapshot, bool, MutationResultDict]:
    mode_path = get_runtime_mode_path(workspace_root)
    lock_path = get_runtime_mode_lock_path(workspace_root)
    os.makedirs(os.path.dirname(mode_path), exist_ok=True)
    lock = FileLock(lock_path, timeout=lock_timeout_s)

    with lock:
        raw_data: Dict[str, Any] = {}
        if os.path.isfile(mode_path):
            try:
                with open(mode_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
            except Exception:
                raw_data = {}

        autopilot_dict = raw_data.get("autopilot", {})
        disk_set_at = autopilot_dict.get("set_at")

        # Step 3: CAS check for consume_stop_at
        if consume_stop_at:
            if expect_set_at != disk_set_at:
                # CAS mismatch! Fail-closed, do not mutate disk!
                current_snapshot = load_runtime_mode(workspace_root, external_api_available)
                return (
                    current_snapshot,
                    False,
                    {
                        "applied": False,
                        "consume_mismatch": True,
                        "disk_set_at": disk_set_at,
                        "expected_set_at": expect_set_at,
                    },
                )
            # CAS passed: bind consumed_for and refresh set_at
            target_consumed_for = consume_for or current_task_id
            new_set_at = datetime.now(timezone.utc).isoformat()
            autopilot_dict["consumed"] = True
            autopilot_dict["consumed_for"] = target_consumed_for
            autopilot_dict["set_at"] = new_set_at

        # Step 4: explicit new stop_at passed (including stop_at="none")
        if stop_at is not None:
            new_set_at = datetime.now(timezone.utc).isoformat()
            autopilot_dict["stop_at"] = stop_at
            autopilot_dict["set_at"] = new_set_at
            autopilot_dict["consumed"] = False
            autopilot_dict["consumed_for"] = None

        if task_file is not None:
            autopilot_dict["task_file"] = task_file

        raw_data["autopilot"] = autopilot_dict

        if switch_mode is not None:
            raw_data["orchestration_mode"] = switch_mode
        if switch_reviewer_channel is not None:
            raw_data["reviewer_channel"] = switch_reviewer_channel
        if runner_subagent_model_hint is not None:
            raw_data["runner_subagent_model_hint"] = runner_subagent_model_hint

        raw_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Atomic write: write to temp file in .agents, then os.replace
        dir_name = os.path.dirname(mode_path)
        fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=".quench_mode_tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, mode_path)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise

    fresh_snapshot = load_runtime_mode(workspace_root, external_api_available)
    final_disk_set_at = fresh_snapshot.autopilot.set_at
    return (
        fresh_snapshot,
        True,
        {
            "applied": True,
            "consume_mismatch": False,
            "disk_set_at": final_disk_set_at,
            "expected_set_at": expect_set_at,
        },
    )
