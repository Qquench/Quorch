# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, ClassVar, Final, Literal, Mapping, Optional, Sequence, Union
from uuid import uuid4

import anyio
from filelock import FileLock

from log_naming import (
    MAX_LOG_REF_CHARS,
    REVIEWER_LOG_QUOTA_KEEP,
    REVIEWER_TERMINAL_LOG_RETENTION,
    SESSION_ID_PATTERN,
    SLUG_MAX_LEN,
    ActiveLogRegistry,
    allocate_log_file,
    enforce_unified_log_quota,
    norm_registry_key,
    validate_log_ref,
)
from project_config import resolve_reviewer_log_dir
from workspace_lease import WorkspaceLeaseGuard, WorkspaceLeaseNotHeldError
from reviewer_engine import format_heartbeat_line


JOB_ID_PATTERN: Final[re.Pattern] = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")
if MAX_LOG_REF_CHARS < 13 + SLUG_MAX_LEN + 4:
    raise ValueError(f"MAX_LOG_REF_CHARS ({MAX_LOG_REF_CHARS}) must be >= 13 + SLUG_MAX_LEN + 4")

DegradedReason = Literal[
    "reviewer_not_configured",
    "timeout",
    "auth",
    "network",
    "reasoning_budget_exceeded",
    "cancelled",
    "orphaned",
]

# 严格收窄后的非终态白名单（6字段，无死字段，无绝对路径）
POLL_NONTERMINAL_FIELDS: Final[frozenset[str]] = frozenset(
    {"job_id", "session_id", "state", "retry_after_seconds", "log_ref", "progress"}
)

# 终态对称白名单
POLL_TERMINAL_FIELDS: Final[frozenset[str]] = frozenset(
    {"job_id", "session_id", "state", "log_path", "usage", "result", "degraded_reason"}
)

# 终态结果允许字段白名单（反思维链与未纳管键泄露）
TERMINAL_RESULT_ALLOWED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "status",
        "findings",
        "mode",
        "session_id",
        "usage",
        "truncated",
        "skipped_files",
        "degraded_reason",
        "handoff_prompt",
        "verdict",
        "reviewer_identity",
        "self_verification_warning",
        "log_path",
        "suggested_task_draft",
    }
)

MAX_NONTERMINAL_SNAPSHOT_BYTES: Final[int] = 1024
AUDIT_LINE_MAX_BYTES: Final[int] = 16384
if MAX_NONTERMINAL_SNAPSHOT_BYTES != 1024:
    raise ValueError("MAX_NONTERMINAL_SNAPSHOT_BYTES must be 1024")
if AUDIT_LINE_MAX_BYTES < 4096:
    raise ValueError("AUDIT_LINE_MAX_BYTES must be >= 4096")
if MAX_NONTERMINAL_SNAPSHOT_BYTES == AUDIT_LINE_MAX_BYTES:
    raise ValueError("MAX_NONTERMINAL_SNAPSHOT_BYTES must not equal AUDIT_LINE_MAX_BYTES")

_WINDOWS_RESERVED_NAMES: Final[set[str]] = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    CANCELLED_PENDING_REAP = "CANCELLED_PENDING_REAP"
    ORPHANED = "ORPHANED"


POLL_TERMINAL_STATES: Final[frozenset[JobState]] = frozenset(
    {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.ORPHANED}
)
PIN_RELEASABLE_STATES: Final[frozenset[JobState]] = frozenset(
    {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.ORPHANED}
)
TERMINAL_STATES: Final[frozenset[JobState]] = PIN_RELEASABLE_STATES  # 消除双重终态分裂
if not (POLL_TERMINAL_STATES == PIN_RELEASABLE_STATES == TERMINAL_STATES):
    raise AssertionError("Inconsistent terminal states invariants")



class ReviewerPhase(str, Enum):
    ASSEMBLING = "assembling"
    STREAMING = "streaming"
    FINALIZING = "finalizing"


@dataclass(frozen=True)
class JobProgress:
    elapsed_s: float  # time.monotonic() 差值生成
    approx_reasoning_tokens: int
    phase: ReviewerPhase
    idle_s: float  # time.monotonic() 相对静默秒数，消除 NTP 时钟偏斜


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    session_id: str
    workspace_root: str
    mode: str
    owner_pid: int
    owner_boot_nonce: str
    generation: int
    state: JobState
    created_monotonic: float
    updated_monotonic: float
    created_wall_utc: str
    updated_wall_utc: str
    log_path: str  # 盘上绝对权威路径
    progress: JobProgress
    result_ref: Optional[str]
    tokens_billed_after_cancel: Optional[int] = None
    degraded_reason: Optional[DegradedReason] = None
    context_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class PollSnapshot:
    job_id: str
    session_id: str
    state: JobState
    retry_after_seconds: int  # 钳制于 [2, 30] (I6)
    log_ref: str  # 非终态仅暴露 basename (<= 40字符)
    progress: Optional[JobProgress]
    result: Optional[dict] = None
    degraded_reason: Optional[DegradedReason] = None


class SnapshotContractViolation(RuntimeError, AssertionError):
    """Raised when snapshot contract or invariant is violated.
    Inherits from RuntimeError and AssertionError for complete python -O resilience and test compatibility.
    """
    pass


class CapacityExceeded(RuntimeError):
    def __init__(self, retry_after: int = 5):
        super().__init__(f"Reviewer capacity full, retry after {retry_after}s")
        self.retry_after = retry_after


def validate_job_id(raw: str | None) -> str:
    """严格校验 job_id，防止路径穿越及 Windows 保留设备名注入。"""
    if raw is None or not str(raw).strip():
        raise ValueError("job_id cannot be empty")
    val = str(raw).strip()
    if not JOB_ID_PATTERN.match(val):
        raise ValueError(
            f"Invalid job_id: '{raw}'. Must match '^[0-9a-zA-Z_-]{{1,64}}$' and cannot contain '/', '\\', or '..'."
        )
    lower_val = val.lower()
    base_name = lower_val.split(".")[0]
    if base_name in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"job_id contains Windows reserved device name: '{raw}'")
    return val


def canonical_snapshot_bytes(payload: Mapping[str, Any]) -> int:
    """唯一序列化度量 SSOT：json.dumps(..., separators=(',', ':'), ensure_ascii=False, sort_keys=True).encode('utf-8')"""
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return len(raw)


def compute_elapsed_s(record: JobRecord) -> float:
    """Compute elapsed seconds from UTC wall clock timestamp for cross-process/reboot resilience (H-2)."""
    try:
        created_dt = datetime.fromisoformat(record.created_wall_utc)
        now_dt = datetime.now(timezone.utc)
        return max(0.0, (now_dt - created_dt).total_seconds())
    except Exception:
        return max(0.0, time.monotonic() - record.created_monotonic)


def project_nonterminal(snapshot: PollSnapshot) -> dict[str, Any]:
    """强投影函数：键集合恒等于 POLL_NONTERMINAL_FIELDS"""
    prog = None
    if snapshot.progress is not None:
        prog = {
            "elapsed_s": round(float(snapshot.progress.elapsed_s), 2),
            "approx_reasoning_tokens": int(snapshot.progress.approx_reasoning_tokens),
            "phase": (
                snapshot.progress.phase.value
                if isinstance(snapshot.progress.phase, ReviewerPhase)
                else str(snapshot.progress.phase)
            ),
            "idle_s": round(float(snapshot.progress.idle_s), 2),
        }

    try:
        validated_log_ref = validate_log_ref(str(snapshot.log_ref))
    except ValueError as e:
        raise SnapshotContractViolation(f"Invalid log_ref: {e}") from e

    res = {
        "job_id": snapshot.job_id,
        "session_id": snapshot.session_id,
        "state": (
            snapshot.state.value if isinstance(snapshot.state, JobState) else str(snapshot.state)
        ),
        "retry_after_seconds": int(snapshot.retry_after_seconds),
        "log_ref": validated_log_ref,
        "progress": prog,
    }

    if set(res.keys()) != POLL_NONTERMINAL_FIELDS:
        raise SnapshotContractViolation(
            f"Projected keys {set(res.keys())} do not match {POLL_NONTERMINAL_FIELDS}"
        )

    # 1KB 约束检查，超限抛 SnapshotContractViolation，严禁截断
    size_bytes = canonical_snapshot_bytes(res)
    if size_bytes > MAX_NONTERMINAL_SNAPSHOT_BYTES:
        raise SnapshotContractViolation(
            f"Nonterminal snapshot size ({size_bytes} bytes) exceeds {MAX_NONTERMINAL_SNAPSHOT_BYTES} bytes limit"
        )
    return res


def project_terminal(record: JobRecord, result: Optional[dict]) -> dict[str, Any]:
    """终态双源对称投影函数 (N-3, C-5, 权威三态判别联合)：
    - 判别字段 state 恒为终态之一 (COMPLETED, FAILED, CANCELLED, ORPHANED)；
    - 输出键集合恒等于 POLL_TERMINAL_FIELDS；
    - 从 JobRecord 提取 log_path；从 result 提取 usage；
    - 严格校验禁止 raw reasoning 键，并使用固定白名单 TERMINAL_RESULT_ALLOWED_FIELDS 过滤，杜绝思维链泄露；
    - Form A (state == "COMPLETED"):
        result 包含 ok 审查正文，degraded_reason 恒为 None；
    - Form B (state in {"FAILED", "CANCELLED", "ORPHANED"}):
        degraded_reason 为非空降级枚举值，
        result 严格为降级形态 {"status": "degraded", "findings": "", "degraded_reason": ...} (INV-3)；
    - 所有断言抛出 SnapshotContractViolation，确保 python -O 下校验不脱保。
    """
    clean_result = None
    usage: dict[str, int] = {}

    if result is not None:
        forbidden = {"reasoning", "raw_reasoning", "chain_of_thought"}
        intersect = set(result.keys()) & forbidden
        if intersect:
            raise SnapshotContractViolation(
                f"Terminal result contains forbidden raw reasoning keys: {intersect}"
            )

        clean_result = {k: v for k, v in result.items() if k in TERMINAL_RESULT_ALLOWED_FIELDS}
        # findings 严格受 MAX_TOTAL_INJECTION_CHARS (40000 字符) 预算保护
        if "findings" in clean_result and isinstance(clean_result["findings"], str):
            if len(clean_result["findings"]) > 40000:
                clean_result["findings"] = clean_result["findings"][:40000]

        usage = dict(clean_result.get("usage", {}))

    degraded_reason = record.degraded_reason
    if record.state in (JobState.FAILED, JobState.CANCELLED, JobState.ORPHANED):
        if degraded_reason is None:
            if record.state == JobState.CANCELLED:
                degraded_reason = "cancelled"
            elif record.state == JobState.ORPHANED:
                degraded_reason = "orphaned"
            else:
                degraded_reason = "network"

        if clean_result is None:
            clean_result = {
                "status": "degraded",
                "findings": "",
                "degraded_reason": degraded_reason,
                "session_id": record.session_id,
                "mode": record.mode,
            }
        else:
            clean_result["status"] = "degraded"
            clean_result["findings"] = ""
            clean_result["degraded_reason"] = degraded_reason
    elif record.state == JobState.COMPLETED:
        degraded_reason = None

    res = {
        "job_id": record.job_id,
        "session_id": record.session_id,
        "state": (
            record.state.value if isinstance(record.state, JobState) else str(record.state)
        ),
        "log_path": record.log_path,
        "usage": usage,
        "result": clean_result,
        "degraded_reason": degraded_reason,
    }
    if set(res.keys()) != POLL_TERMINAL_FIELDS:
        raise SnapshotContractViolation(
            f"Projected keys {set(res.keys())} do not match {POLL_TERMINAL_FIELDS}"
        )
    return res


def project_poll_result(
    snapshot: PollSnapshot,
    *,
    raw_text: bool = False,
) -> Union[str, dict[str, Any]]:
    """If raw_text is True and state is non-terminal, returns single-line canonical str.
    Otherwise returns compact non-terminal dict or full terminal projection dict.
    """
    if raw_text:
        tokens = snapshot.progress.approx_reasoning_tokens if snapshot.progress else 0
        elapsed = snapshot.progress.elapsed_s if snapshot.progress else 0.0
        return format_heartbeat_line(tokens, elapsed)
    return project_nonterminal(snapshot)


def format_progress(
    progress: JobProgress,
    locale: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """本地化转译纯函数：
    - locale 顺序：入参 locale > env['LC_ALL'] > env['LC_MESSAGES'] > env['LANG'] > 默认 'en'
    - ReviewerPhase 映射：
        en: assembling -> 'assembling', streaming -> 'streaming', finalizing -> 'finalizing'
        zh: assembling -> '组装中', streaming -> '思考中', finalizing -> '总结中'
    - 输出模版：
        en: f"Thinking ({phase_en}) · {m}m {s}s · idle {int(progress.idle_s)}s"
        zh: f"正在思考 ({phase_zh}) · {m}min {s}s · 静默 {int(progress.idle_s)}s"
    """
    if env is None:
        env = os.environ

    candidates = [locale, env.get("LC_ALL"), env.get("LC_MESSAGES"), env.get("LANG")]
    resolved_lang = "en"
    for cand in candidates:
        if cand and str(cand).strip():
            c_lower = str(cand).strip().lower()
            if "zh" in c_lower:
                resolved_lang = "zh"
                break
            elif "en" in c_lower:
                resolved_lang = "en"
                break

    total_s = max(0, int(progress.elapsed_s))
    m = total_s // 60
    s = total_s % 60
    idle_s = max(0, int(progress.idle_s))

    phase_raw = (
        progress.phase.value
        if isinstance(progress.phase, ReviewerPhase)
        else str(progress.phase).lower()
    )

    if resolved_lang == "zh":
        mapping = {"assembling": "组装中", "streaming": "思考中", "finalizing": "总结中"}
        phase_zh = mapping.get(phase_raw, phase_raw)
        return f"正在思考 ({phase_zh}) · {m}min {s}s · 静默 {idle_s}s"
    else:
        mapping = {"assembling": "assembling", "streaming": "streaming", "finalizing": "finalizing"}
        phase_en = mapping.get(phase_raw, phase_raw)
        return f"Thinking ({phase_en}) · {m}m {s}s · idle {idle_s}s"


def assert_poll_authorized(job: JobRecord, caller_session_id: str) -> None:
    """会话授权校验：防止跨会话 IDOR 越权查看或操作任务"""
    if not caller_session_id or job.session_id != caller_session_id:
        raise PermissionError(
            f"Access denied: caller session_id '{caller_session_id}' does not match job session_id '{job.session_id}'"
        )


def _durable_write_json(filepath: Path, data: dict) -> None:
    """Durable write for JobRecord and results:
    temp -> flush -> fsync(file) -> os.replace -> fsync(dir).
    Guarantees zero-length files are never created upon power loss or crash (C-3, H-C).
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    temp_file = filepath.with_suffix(f".tmp.{os.getpid()}.{time.time_ns()}")
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        try:
            os.fsync(f.fileno())
        except (OSError, AttributeError):
            pass

    max_retries = 5
    for attempt in range(max_retries):
        try:
            os.replace(temp_file, filepath)
            break
        except (PermissionError, OSError):
            if attempt == max_retries - 1:
                try:
                    if temp_file.exists():
                        temp_file.unlink()
                except Exception:
                    pass
                raise
            time.sleep(0.02 * (2 ** attempt))

    if hasattr(os, "O_DIRECTORY") and sys.platform != "win32":
        try:
            dir_fd = os.open(str(filepath.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, AttributeError):
            pass


_atomic_replace_json = _durable_write_json


def _record_to_dict(record: JobRecord) -> dict[str, Any]:
    d = asdict(record)
    d["state"] = record.state.value
    d["progress"]["phase"] = (
        record.progress.phase.value
        if isinstance(record.progress.phase, ReviewerPhase)
        else str(record.progress.phase)
    )
    return d


def _record_from_dict(d: dict[str, Any]) -> JobRecord:
    prog_d = d["progress"]
    prog = JobProgress(
        elapsed_s=float(prog_d["elapsed_s"]),
        approx_reasoning_tokens=int(prog_d["approx_reasoning_tokens"]),
        phase=ReviewerPhase(prog_d["phase"]),
        idle_s=float(prog_d["idle_s"]),
    )
    return JobRecord(
        job_id=d["job_id"],
        session_id=d["session_id"],
        workspace_root=d["workspace_root"],
        mode=d["mode"],
        owner_pid=int(d["owner_pid"]),
        owner_boot_nonce=d["owner_boot_nonce"],
        generation=int(d["generation"]),
        state=JobState(d["state"]),
        created_monotonic=float(d["created_monotonic"]),
        updated_monotonic=float(d["updated_monotonic"]),
        created_wall_utc=d["created_wall_utc"],
        updated_wall_utc=d["updated_wall_utc"],
        log_path=d["log_path"],
        progress=prog,
        result_ref=d.get("result_ref"),
        tokens_billed_after_cancel=d.get("tokens_billed_after_cancel"),
        degraded_reason=d.get("degraded_reason"),
        context_files=tuple(d.get("context_files", ())),
    )


def compute_protected_logs(
    jobs_dir: str | os.PathLike[str],
    *,
    retention: int = REVIEWER_TERMINAL_LOG_RETENTION,
) -> frozenset[str]:
    """保护集 = 最近 retention 条终态(basename字典序) ∪ 非终态在途 ∪ 排除 latest-*。
    零系统调用 (zero-stat) 扫描 durable JobRecord，仅依据 basename 字典序排序。
    """
    j_dir = os.path.abspath(jobs_dir)
    if not os.path.isdir(j_dir):
        return frozenset()

    inflight_logs: set[str] = set()
    terminal_entries: list[tuple[str, str]] = []  # (basename, log_path)

    try:
        for root, _, files in os.walk(j_dir):
            for file in files:
                if not file.endswith(".record.json"):
                    continue
                record_path = os.path.join(root, file)
                try:
                    with open(record_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                log_path = data.get("log_path")
                if not log_path or not isinstance(log_path, str):
                    continue

                basename = os.path.basename(log_path)
                # 显式排除 latest-* 命名空间
                if basename.startswith("latest-") or basename == "latest.log":
                    continue

                state_str = data.get("state")
                # 在途状态保护：QUEUED, RUNNING, CANCELLED_PENDING_REAP
                if state_str in ("QUEUED", "RUNNING", "CANCELLED_PENDING_REAP"):
                    inflight_logs.add(log_path)
                elif state_str in (
                    JobState.COMPLETED.value,
                    JobState.FAILED.value,
                    JobState.CANCELLED.value,
                    JobState.ORPHANED.value,
                ):
                    terminal_entries.append((basename, log_path))
    except Exception:
        pass

    # Basename 字典序排序（等价于时间序，零系统调用）
    terminal_entries.sort(key=lambda item: item[0])
    recent_terminal = (
        terminal_entries[-retention:]
        if len(terminal_entries) > retention
        else terminal_entries
    )

    protected: set[str] = {item[1] for item in recent_terminal} | inflight_logs
    return frozenset(protected)


def build_peer_liveness_probe(
    jobs_dir: str | os.PathLike[str],
    workspace_root: str,
) -> Callable[[str], bool]:
    """构建跨进程存活探测器。
    严格遵守 Zero-stat：仅遍历 durable JobRecord，绝不 stat 候选日志文件；
    无匹配 record 时默认极性 fail-safe 返回 True (alive)。
    """
    j_dir = os.path.abspath(jobs_dir)

    def _is_alive_probe(log_path: str) -> bool:
        if not os.path.isdir(j_dir):
            return True

        norm_target_key = norm_registry_key(log_path)
        matching_record: dict[str, Any] | None = None

        try:
            for root, _, files in os.walk(j_dir):
                for file in files:
                    if not file.endswith(".record.json"):
                        continue
                    r_path = os.path.join(root, file)
                    try:
                        with open(r_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        continue

                    r_log = data.get("log_path")
                    if r_log and norm_registry_key(r_log) == norm_target_key:
                        matching_record = data
                        break
                if matching_record is not None:
                    break
        except Exception:
            return True

        if matching_record is None:
            # 零 record 对应项：fail-safe 默认存活
            return True

        state_str = matching_record.get("state")
        if state_str in (
            JobState.COMPLETED.value,
            JobState.FAILED.value,
            JobState.CANCELLED.value,
            JobState.ORPHANED.value,
        ):
            return False

        owner_pid = matching_record.get("owner_pid")
        owner_boot_nonce = matching_record.get("owner_boot_nonce")

        if not isinstance(owner_pid, int) or owner_pid <= 0:
            return True

        try:
            peer = WorkspaceLeaseGuard.probe_peer(
                owner_pid, owner_boot_nonce or "", workspace_root
            )
            return peer.is_alive
        except Exception:
            try:
                os.kill(owner_pid, 0)
                return True
            except OSError as err:
                import errno

                return err.errno == errno.EPERM

    return _is_alive_probe


class ReviewerJobSupervisor:
    """MCP 服务进程内的单例 Job 调度主管与状态机。"""

    _instances: ClassVar[dict[str, "ReviewerJobSupervisor"]] = {}
    _global_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, workspace_root: Union[Path, str]) -> None:
        self.workspace_root = str(os.path.realpath(workspace_root))
        self._boot_nonce = f"boot_{os.getpid()}_{time.time_ns()}_{uuid4().hex[:8]}"
        self._ws_hash = hashlib.sha256(self.workspace_root.encode("utf-8")).hexdigest()[:16]
        self._jobs_base = (
            Path(resolve_reviewer_log_dir(self.workspace_root)) / "jobs" / self._ws_hash
        )
        self._jobs_base.mkdir(parents=True, exist_ok=True)
        self._lease_guard = WorkspaceLeaseGuard(self.workspace_root)
        self._registry = ActiveLogRegistry()
        self._limiter = anyio.CapacityLimiter(4)
        self._tasks: dict[str, asyncio.Task] = {}
        self._worker_threads: dict[str, threading.Thread] = {}
        self._abort_handles: dict[str, Any] = {}
        self._running_jobs_lock = threading.Lock()

    def _pin_log(self, log_path: str) -> str:
        key = norm_registry_key(log_path)
        self._registry.pin(key)
        return key

    def _release_log_pin(self, record: Union[JobRecord, str, None]) -> None:
        try:
            if record is None:
                return
            if isinstance(record, str):
                self._registry.unpin(record)
            elif hasattr(record, "log_path") and record.log_path:
                self._registry.unpin(record.log_path)
        except Exception:
            pass

    def _get_verdicts_path(self) -> Path:
        return Path(resolve_reviewer_log_dir(self.workspace_root)) / "verdicts.jsonl"


    def _read_existing_verdict_job_ids(self) -> set[str]:
        v_path = self._get_verdicts_path()
        if not v_path.is_file():
            return set()
        seen: set[str] = set()
        try:
            with open(v_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if "job_id" in entry:
                            seen.add(entry["job_id"])
                    except Exception:
                        pass
        except Exception:
            pass
        return seen

    def _append_verdict_audit(self, record: JobRecord, result_dict: Optional[dict] = None) -> None:
        """Append-only audit projection to verdicts.jsonl with fsync.
        Failure logs warning only and never blocks or fails terminal state (C-3).
        """
        try:
            v_path = self._get_verdicts_path()
            v_path.parent.mkdir(parents=True, exist_ok=True)
            v_lock_path = v_path.with_suffix(".jsonl.lock")
            c_files = list(record.context_files) if hasattr(record, "context_files") and record.context_files else []
            payload: dict[str, Any] = {
                "job_id": record.job_id,
                "session_id": record.session_id,
                "state": record.state.value if isinstance(record.state, JobState) else str(record.state),
                "mode": record.mode,
                "generation": record.generation,
                "created_wall_utc": record.created_wall_utc,
                "updated_wall_utc": record.updated_wall_utc,
                "log_path": record.log_path,
                "degraded_reason": record.degraded_reason,
                "context_files": c_files,
            }
            if result_dict:
                payload["usage"] = result_dict.get("usage", {})
                if "status" in result_dict:
                    payload["status"] = result_dict["status"]
                if "context_files" in result_dict and result_dict["context_files"]:
                    payload["context_files"] = list(result_dict["context_files"])

            line = json.dumps(payload, ensure_ascii=False)
            with FileLock(str(v_lock_path), timeout=5.0):
                with open(v_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except (OSError, AttributeError):
                        pass
        except Exception as e:
            sys.stderr.write(f"[ReviewerJobSupervisor] Warning: failed to append to verdicts.jsonl for {record.job_id}: {e}\n")

    @classmethod
    def for_workspace(cls, root: Union[Path, str]) -> "ReviewerJobSupervisor":
        norm_root = str(os.path.realpath(root))
        with cls._global_lock:
            if norm_root not in cls._instances:
                cls._instances[norm_root] = cls(norm_root)
            return cls._instances[norm_root]

    @property
    def registry(self) -> ActiveLogRegistry:
        return self._registry

    @property
    def lease_guard(self) -> WorkspaceLeaseGuard:
        return self._lease_guard

    @property
    def boot_nonce(self) -> str:
        return self._boot_nonce

    def _get_session_dir(self, session_id: str) -> Path:
        s_dir = self._jobs_base / session_id
        s_dir.mkdir(parents=True, exist_ok=True)
        return s_dir

    def _get_record_path(self, session_id: str, job_id: str) -> Path:
        return self._get_session_dir(session_id) / f"{job_id}.record.json"

    def _get_lock_path(self, session_id: str, job_id: str) -> Path:
        return self._get_session_dir(session_id) / f"{job_id}.record.lock"

    def _get_result_path(self, session_id: str, job_id: str) -> Path:
        res_dir = self._get_session_dir(session_id) / "results"
        res_dir.mkdir(parents=True, exist_ok=True)
        return res_dir / f"{job_id}.result.json"

    def _find_job_session(self, job_id: str) -> Optional[str]:
        if not self._jobs_base.is_dir():
            return None
        for s_entry in self._jobs_base.iterdir():
            if s_entry.is_dir():
                cand = s_entry / f"{job_id}.record.json"
                if cand.is_file():
                    return s_entry.name
        return None

    def _compute_retry_after(self, elapsed_s: float) -> int:
        """退避钳制防风暴：服务端 retry_after_seconds 严格钳制在 [2, 30] 闭区间 (I6)。"""
        val = int(2 + elapsed_s * 0.2)
        return min(30, max(2, val))

    def _load_job_record(self, session_id: str, job_id: str) -> Optional[JobRecord]:
        rec_path = self._get_record_path(session_id, job_id)
        if not rec_path.is_file():
            return None
        try:
            with open(rec_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _record_from_dict(data)
        except Exception:
            return None

    def _save_job_record(self, record: JobRecord) -> None:
        rec_path = self._get_record_path(record.session_id, record.job_id)
        _atomic_replace_json(rec_path, _record_to_dict(record))

    def _cas_transition(
        self,
        session_id: str,
        job_id: str,
        expected_state: Union[JobState, tuple[JobState, ...]],
        new_state: JobState,
        *,
        updates: Optional[dict[str, Any]] = None,
    ) -> bool:
        """单写者终态 CAS：终态经 filelock 原子 CAS 迁移，JobRecord 强制 temp+os.replace 原子替换 (I1)。"""
        lock_path = self._get_lock_path(session_id, job_id)
        with FileLock(str(lock_path), timeout=5.0):
            current = self._load_job_record(session_id, job_id)
            if current is None:
                return False

            expected = (expected_state,) if isinstance(expected_state, JobState) else expected_state
            if current.state not in expected:
                return False

            if current.state in TERMINAL_STATES and new_state != current.state:
                return False

            now_mono = time.monotonic()
            now_wall = datetime.now(timezone.utc).isoformat()
            up_dict = updates or {}

            new_record = dataclasses.replace(
                current,
                state=new_state,
                generation=current.generation + 1,
                updated_monotonic=now_mono,
                updated_wall_utc=now_wall,
                **up_dict,
            )
            self._save_job_record(new_record)
            return True

    def submit(self, req: dict, *, idempotency_key: Optional[str] = None) -> JobRecord:
        """提交异步长推演任务，遵循准入控制与常驻所有权模型。
        权威步骤序：
        准入判定 (CapacityLimiter) → 幂等键查重 (命中直接返回既有 record，不二次组装上下文也不二次 pin)
        → allocate_log_file() → _pin_log() → 落盘 JobRecord → 机会式清理 (传入 compute_protected_logs)
        """
        # I8: 并发准入控制（CapacityLimiter 纯读快速失败判据）
        if self._limiter.borrowed_tokens >= self._limiter.total_tokens:
            raise CapacityExceeded(retry_after=5)

        raw_session_id = req.get("session_id")
        from consultation import sanitize_session_id

        session_id = sanitize_session_id(raw_session_id, max_len=128)
        mode = req.get("mode", "critique")

        if idempotency_key:
            job_id = validate_job_id(idempotency_key)
            existing = self._load_job_record(session_id, job_id)
            if existing is not None:
                return existing
        else:
            job_id = f"job_{int(time.time())}_{uuid4().hex[:8]}"

        # 前置 fail-closed 沙箱检查与上下文组装截断 (INV-6 / INV-8)
        # 必须在 allocate_log_file() 之前执行，失败直接阻断，零残留日志与 pin
        from consultation import assert_read_only_sandbox, assemble_reviewer_context
        context_files = req.get("context_files") or []
        assert_read_only_sandbox(self.workspace_root, context_files)

        cfg = req.get("config")
        slices, skipped_files, truncated = assemble_reviewer_context(
            self.workspace_root,
            context_files,
            config=cfg,
        )
        req["_assembled_slices"] = slices
        req["_skipped_files"] = skipped_files
        req["_context_truncated"] = truncated

        log_dir = resolve_reviewer_log_dir(self.workspace_root)
        os.makedirs(log_dir, exist_ok=True)

        allocated_log_path = None
        try:
            allocated_log_path, _ = allocate_log_file(
                log_dir,
                slug=session_id,
                header_metadata={"mode": mode, "session_id": session_id, "job_id": job_id},
                registry=self._registry,
            )
            self._pin_log(allocated_log_path)

            now_mono = time.monotonic()
            now_wall = datetime.now(timezone.utc).isoformat()
            initial_progress = JobProgress(
                elapsed_s=0.0,
                approx_reasoning_tokens=0,
                phase=ReviewerPhase.ASSEMBLING,
                idle_s=0.0,
            )

            record = JobRecord(
                job_id=job_id,
                session_id=session_id,
                workspace_root=self.workspace_root,
                mode=mode,
                owner_pid=os.getpid(),
                owner_boot_nonce=self._boot_nonce,
                generation=1,
                state=JobState.QUEUED,
                created_monotonic=now_mono,
                updated_monotonic=now_mono,
                created_wall_utc=now_wall,
                updated_wall_utc=now_wall,
                log_path=allocated_log_path,
                progress=initial_progress,
                result_ref=None,
                context_files=tuple(context_files),
            )

            # 原子落盘并启动后台 worker
            self._save_job_record(record)
            self._launch_worker(record, req)
        except Exception:
            if allocated_log_path:
                self._release_log_pin(allocated_log_path)
            raise

        # 机会式清理（传入 compute_protected_logs 与 build_peer_liveness_probe）
        try:
            protected = compute_protected_logs(
                str(self._jobs_base), retention=REVIEWER_TERMINAL_LOG_RETENTION
            )
            is_peer_alive = build_peer_liveness_probe(
                str(self._jobs_base), self.workspace_root
            )
            enforce_unified_log_quota(
                log_dir,
                keep=REVIEWER_LOG_QUOTA_KEEP,
                retention=REVIEWER_TERMINAL_LOG_RETENTION,
                registry=self._registry,
                require_lease=False,
                is_peer_alive=is_peer_alive,
                protected_paths=protected,
            )
        except Exception:
            pass

        return record


    def _launch_worker(self, record: JobRecord, req: dict) -> None:
        """启动后台 Worker 协程，强引用常驻持有 Task (I2)。"""
        from consultation import AbortHandle, ConsultRequest, _execute_consultation
        from project_config import load_project_config

        cancel_event = asyncio.Event()
        abort_handle = AbortHandle()

        with self._running_jobs_lock:
            self._abort_handles[record.job_id] = (cancel_event, abort_handle)

        async def _worker():
            tokens_accum = {"tokens": 0}
            try:
                async with self._limiter:
                    # QUEUED -> RUNNING CAS 迁移
                    if not self._cas_transition(
                        record.session_id,
                        record.job_id,
                        JobState.QUEUED,
                        JobState.RUNNING,
                    ):
                        return

                    def on_prog(tokens: int, elapsed: float, phase_str: str, idle: float):
                        tokens_accum["tokens"] = tokens
                        p_phase = (
                            ReviewerPhase(phase_str)
                            if phase_str in ("assembling", "streaming", "finalizing")
                            else ReviewerPhase.STREAMING
                        )
                        prog = JobProgress(
                            elapsed_s=elapsed,
                            approx_reasoning_tokens=tokens,
                            phase=p_phase,
                            idle_s=idle,
                        )
                        # 更新盘上进度
                        curr = self._load_job_record(record.session_id, record.job_id)
                        if curr and curr.state == JobState.RUNNING:
                            new_curr = dataclasses.replace(
                                curr,
                                progress=prog,
                                updated_monotonic=time.monotonic(),
                            )
                            self._save_job_record(new_curr)

                    consult_req = ConsultRequest(
                        workspace_root=self.workspace_root,
                        query=req.get("query", ""),
                        context_files=tuple(req.get("context_files", ())),
                        mode=record.mode,
                        max_hops=req.get("max_hops", 1),
                        session_id=record.session_id,
                    )

                    cfg = req.get("config")
                    if cfg is None:
                        try:
                            cfg = load_project_config(self.workspace_root)
                        except Exception:
                            from project_config import QuenchStackConfig

                            cfg = QuenchStackConfig(
                                workspace_root=self.workspace_root,
                                project_name="default",
                            )

                    res = await _execute_consultation(
                        consult_req,
                        record.log_path,
                        cancel_event=cancel_event,
                        abort_handle=abort_handle,
                        config=cfg,
                        ctx=req.get("ctx"),
                        on_progress=on_prog,
                    )

                    # I7: 隔离目录与结果优先落盘 (C-3, H-C: durable write)
                    res_path = self._get_result_path(record.session_id, record.job_id)
                    from dataclasses import asdict

                    _durable_write_json(res_path, asdict(res))

                    if res.status == "degraded":
                        self._cas_transition(
                            record.session_id,
                            record.job_id,
                            JobState.RUNNING,
                            JobState.FAILED,
                            updates={
                                "result_ref": str(res_path),
                                "degraded_reason": res.degraded_reason or "network",
                            },
                        )
                    else:
                        self._cas_transition(
                            record.session_id,
                            record.job_id,
                            JobState.RUNNING,
                            JobState.COMPLETED,
                            updates={"result_ref": str(res_path)},
                        )

                    # 固化写入序：payload -> JobRecord(durable) -> jsonl(append+fsync)
                    final_rec = self._load_job_record(record.session_id, record.job_id)
                    if final_rec:
                        self._append_verdict_audit(final_rec, asdict(res))

            except asyncio.CancelledError:
                # 确定性取消：Worker 负责在 CAS 临界区记录 tokens_billed_after_cancel (I4)
                actual_tokens = tokens_accum.get("tokens", 0)
                self._cas_transition(
                    record.session_id,
                    record.job_id,
                    (JobState.QUEUED, JobState.RUNNING),
                    JobState.CANCELLED,
                    updates={
                        "degraded_reason": "cancelled",
                        "tokens_billed_after_cancel": actual_tokens,
                    },
                )
                final_rec = self._load_job_record(record.session_id, record.job_id)
                if final_rec:
                    self._append_verdict_audit(final_rec)
            except Exception:
                self._cas_transition(
                    record.session_id,
                    record.job_id,
                    (JobState.QUEUED, JobState.RUNNING),
                    JobState.FAILED,
                    updates={"degraded_reason": "network"},
                )
                final_rec = self._load_job_record(record.session_id, record.job_id)
                if final_rec:
                    self._append_verdict_audit(final_rec)
            finally:
                with self._running_jobs_lock:
                    self._abort_handles.pop(record.job_id, None)
                    self._tasks.pop(record.job_id, None)
                    self._worker_threads.pop(record.job_id, None)

                # 终态安全 unpin：仅当已处于 PIN_RELEASABLE_STATES 时释放 pin
                final_rec = self._load_job_record(record.session_id, record.job_id)
                if final_rec and final_rec.state in PIN_RELEASABLE_STATES:
                    self._release_log_pin(final_rec)
                    # 随后调用 compute_protected_logs 传入配额清理
                    try:
                        log_dir = resolve_reviewer_log_dir(self.workspace_root)
                        protected = compute_protected_logs(
                            str(self._jobs_base), retention=REVIEWER_TERMINAL_LOG_RETENTION
                        )
                        is_peer_alive = build_peer_liveness_probe(
                            str(self._jobs_base), self.workspace_root
                        )
                        enforce_unified_log_quota(
                            log_dir,
                            keep=REVIEWER_LOG_QUOTA_KEEP,
                            retention=REVIEWER_TERMINAL_LOG_RETENTION,
                            registry=self._registry,
                            require_lease=False,
                            is_peer_alive=is_peer_alive,
                            protected_paths=protected,
                        )
                    except Exception:
                        pass


        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_worker())
            with self._running_jobs_lock:
                self._tasks[record.job_id] = task
        except RuntimeError:
            pass

    def project_poll_result(
        self,
        snapshot: PollSnapshot,
        *,
        raw_text: bool = False,
    ) -> Union[str, dict[str, Any]]:
        """If raw_text is True and state is non-terminal, returns single-line canonical str.
        Otherwise returns compact non-terminal dict or full terminal projection dict.
        """
        return project_poll_result(snapshot, raw_text=raw_text)

    def poll(
        self,
        job_id: str,
        *,
        session_id: str,
        raw_text: bool = False,
    ) -> Union[str, dict[str, Any]]:
        """Poll 只读零锁与极简白名单契约 (I5, I5-B, I5-C, AUTH)。"""
        val_id = validate_job_id(job_id)
        from consultation import sanitize_session_id

        val_sid = sanitize_session_id(session_id, max_len=128)

        target_sid = self._find_job_session(val_id) or val_sid
        record = self._load_job_record(target_sid, val_id)
        if record is None:
            raise KeyError(f"Job not found: '{val_id}'")

        # 会话鉴权
        assert_poll_authorized(record, val_sid)

        # 终态判定
        if record.state in TERMINAL_STATES:
            res_dict = None
            if record.result_ref and Path(record.result_ref).is_file():
                try:
                    with open(record.result_ref, "r", encoding="utf-8") as f:
                        res_dict = json.load(f)
                except Exception:
                    pass
            return project_terminal(record, res_dict)

        # 非终态白名单投影
        elapsed = compute_elapsed_s(record)
        retry_after = self._compute_retry_after(elapsed)
        log_basename = os.path.basename(record.log_path)
        try:
            log_ref = validate_log_ref(log_basename)
        except ValueError as e:
            raise SnapshotContractViolation(f"Invalid log_ref: {e}") from e

        snapshot = PollSnapshot(
            job_id=record.job_id,
            session_id=record.session_id,
            state=record.state,
            retry_after_seconds=retry_after,
            log_ref=log_ref,
            progress=record.progress,
        )
        return self.project_poll_result(snapshot, raw_text=raw_text)

    def cancel(self, job_id: str, *, session_id: str) -> dict[str, Any]:
        """确定性真实取消 (I4, H-7, AUTH)。
        取消必须在 worker 结束（或 join）成功后再 unpin；超时进入 CANCELLED_PENDING_REAP 保留 pin。
        """
        val_id = validate_job_id(job_id)
        from consultation import sanitize_session_id

        val_sid = sanitize_session_id(session_id, max_len=128)

        target_sid = self._find_job_session(val_id) or val_sid
        record = self._load_job_record(target_sid, val_id)
        if record is None:
            raise KeyError(f"Job not found: '{val_id}'")

        assert_poll_authorized(record, val_sid)

        if record.state in TERMINAL_STATES:
            # 终态幂等
            return self.poll(job_id, session_id=session_id)

        with self._running_jobs_lock:
            handles = self._abort_handles.get(val_id)
            task = self._tasks.get(val_id)
            thread = self._worker_threads.get(val_id)

        if handles is not None:
            c_event, a_handle = handles
            c_event.set()
            a_handle.abort()

        worker_joined = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
            if thread.is_alive():
                worker_joined = False

        if task is not None and not task.done():
            task.cancel()

        target_state = JobState.CANCELLED if worker_joined else JobState.CANCELLED_PENDING_REAP

        # CAS 推进 CANCELLED 或 CANCELLED_PENDING_REAP
        self._cas_transition(
            record.session_id,
            record.job_id,
            (JobState.QUEUED, JobState.RUNNING),
            target_state,
            updates={
                "degraded_reason": "cancelled",
                "tokens_billed_after_cancel": record.tokens_billed_after_cancel or 0,
            },
        )

        final_rec = self._load_job_record(record.session_id, record.job_id)
        if final_rec:
            self._append_verdict_audit(final_rec)

        if final_rec and final_rec.state in PIN_RELEASABLE_STATES:
            self._release_log_pin(final_rec)
            try:
                log_dir = resolve_reviewer_log_dir(self.workspace_root)
                protected = compute_protected_logs(
                    str(self._jobs_base), retention=REVIEWER_TERMINAL_LOG_RETENTION
                )
                is_peer_alive = build_peer_liveness_probe(
                    str(self._jobs_base), self.workspace_root
                )
                enforce_unified_log_quota(
                    log_dir,
                    keep=REVIEWER_LOG_QUOTA_KEEP,
                    retention=REVIEWER_TERMINAL_LOG_RETENTION,
                    registry=self._registry,
                    require_lease=False,
                    is_peer_alive=is_peer_alive,
                    protected_paths=protected,
                )
            except Exception:
                pass

        return self.poll(job_id, session_id=session_id)

    def reconcile_on_load(self) -> list[str]:
        """启动载入对账：
        1. 幂等自愈：对账盘上已落盘的终态 JobRecord，若 verdicts.jsonl 缺失对应记录则执行自动补写 (C-3)；
        2. 异代接管：通过 Task 4.0 probe_peer 验证异代进程真实存活；仅当异代且确认 PID 死亡才迁 ORPHANED 并 unpin (I3)；
        3. 单一 SSOT：verdicts.jsonl 缺行绝不构成孤儿判据。
        """
        orphaned: list[str] = []
        if not self._jobs_base.is_dir():
            return orphaned

        existing_verdict_ids = self._read_existing_verdict_job_ids()

        for s_dir in self._jobs_base.iterdir():
            if not s_dir.is_dir():
                continue
            for r_file in s_dir.glob("*.record.json"):
                try:
                    with open(r_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    rec = _record_from_dict(data)
                except Exception:
                    continue

                # 1. 终态自愈补写 (C-3 幂等补写)
                if rec.state in TERMINAL_STATES:
                    if rec.job_id not in existing_verdict_ids:
                        res_dict = None
                        if rec.result_ref and Path(rec.result_ref).is_file():
                            try:
                                with open(rec.result_ref, "r", encoding="utf-8") as rf:
                                    res_dict = json.load(rf)
                            except Exception:
                                pass
                        self._append_verdict_audit(rec, res_dict)
                        existing_verdict_ids.add(rec.job_id)
                    continue

                # 2. 非终态在途任务：缺行绝不判定孤儿；严格基于进程探针
                if rec.state in (JobState.QUEUED, JobState.RUNNING):
                    # 同进程自身启动时不抢自己
                    if rec.owner_pid == os.getpid() and rec.owner_boot_nonce == self._boot_nonce:
                        continue

                    peer = WorkspaceLeaseGuard.probe_peer(
                        rec.owner_pid, rec.owner_boot_nonce, self.workspace_root
                    )
                    if not peer.is_alive and peer.takeover_allowed:
                        # 异代且已死亡，安全标记 ORPHANED 并释放 unpin
                        if self._cas_transition(
                            rec.session_id,
                            rec.job_id,
                            (JobState.QUEUED, JobState.RUNNING),
                            JobState.ORPHANED,
                            updates={"degraded_reason": "orphaned"},
                        ):
                            self._release_log_pin(rec)
                            orphaned.append(rec.job_id)
                            updated_rec = self._load_job_record(rec.session_id, rec.job_id)
                            if updated_rec:
                                self._append_verdict_audit(updated_rec)
                                existing_verdict_ids.add(rec.job_id)
        return orphaned


    def gc_terminal_jobs(self, *, max_records: int = 100, max_age_s: float = 1800.0) -> int:
        """终态 GC 与容错：仅回收超 TTL 终态任务，GC 期间对已解引用文件优雅容忍 ENOENT (I10)。"""
        reaped = 0
        if not self._jobs_base.is_dir():
            return 0

        now = time.time()
        for s_dir in self._jobs_base.iterdir():
            if not s_dir.is_dir():
                continue
            record_files = list(s_dir.glob("*.record.json"))
            for r_file in record_files:
                try:
                    with open(r_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    rec = _record_from_dict(data)
                except Exception:
                    continue

                if rec.state in TERMINAL_STATES:
                    try:
                        mtime = r_file.stat().st_mtime
                        age = now - mtime
                    except FileNotFoundError:
                        continue

                    if age >= max_age_s or len(record_files) > max_records:
                        job_id = rec.job_id
                        lock_file = self._get_lock_path(rec.session_id, job_id)
                        res_file = self._get_result_path(rec.session_id, job_id)

                        for target_f in [r_file, lock_file, res_file]:
                            try:
                                target_f.unlink(missing_ok=True)
                            except (FileNotFoundError, OSError):
                                pass
                        reaped += 1
        return reaped

    def shutdown(self) -> None:
        """优雅清理常驻 supervisor。"""
        with self._running_jobs_lock:
            for c_event, a_handle in self._abort_handles.values():
                try:
                    c_event.set()
                    a_handle.abort()
                except Exception:
                    pass
            for task in self._tasks.values():
                try:
                    task.cancel()
                except Exception:
                    pass
            self._abort_handles.clear()
            self._tasks.clear()
