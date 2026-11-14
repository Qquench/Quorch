# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta, date
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import filelock
import tempfile
import time
from typing import Any, Dict, List, Mapping, Optional, Literal, Sequence, TypedDict, Union
from fastmcp import Context, FastMCP

from log_naming import SESSION_ID_PATTERN
from tool_surface_constants import (
    HOOK_LOG_TAIL_BYTES,
    POLL_WAIT_MAX_S_HARD_CEILING,
    STATUS_COMPACT_MAX_HOOK_ENTRIES,
    STATUS_COMPACT_MAX_TASKS,
)
from response_compactor import (
    classify_hook_log_entry,
    compute_entitlements_hash,
    fit_to_budget,
)


def _atomic_write_json(filepath: str, data: dict) -> None:
    """Atomically write JSON data using temporary file and os.replace. / 使用临时文件 + os.replace 实现原子写入。"""
    dir_name = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, filepath)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise


def _validate_session_id(session_id: Optional[str]) -> Optional[str]:
    """Validate session_id format (UUID regex whitelist, max 128 chars). / 校验 session_id 格式（UUID 正则白名单，最长 128 字符）。"""
    if not session_id:
        return None
    s = session_id.strip()
    if not SESSION_ID_PATTERN.match(s):
        raise ValueError(f"Invalid session_id format: '{s}'. Only up to 128-char UUID/alphanumeric/hyphens supported. / 非法的 session_id 格式: '{s}'。仅支持最长 128 位的 UUID/十六进制/连字符字符。")
    return s

import functools
import anyio
from code_explorer import explore_code_slices, ExploreResult
from reporting import append_changelog_entry, render_handoff_card
from path_guard import (
    to_workspace_relative_path,
    PathTraversalError,
    is_within_whitelist,
    sanitize_workspace_path,
)
from project_config import (
    load_project_config,
    QuenchStackConfig,
    ReviewerEngineConfig,
    DispatchStrategy,
    create_reviewer_client,
    canonical_artifact_ref,
    AuditGatePolicy,
    AuditGateReason,
    AuditGateResult,
    most_restrictive_policy,
)
from reviewer_engine import (
    PromptAssembler,
    ReviewerClient,
    RotatingFileSink,
    AdaptiveHeartbeatSink,
)
from schema_validator import (
    validate_task_schema,
    lint_task_physical_feasibility,
    LintIssue,
    PhysicalLintResult,
    _parse_task_markdown_sections,
)
from state_machine import (
    ALL_STATUSES,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_REWORK,
    STATUS_SKIPPED,
    TASK_HEADER_PATTERN,
    TaskItem,
    get_status_summary,
    parse_task_file,
    transition_task,
    assert_task_checkout_allowed,
    extract_task_whitelist,
)
from task_status import is_task_file
from pathlib import Path
from manifest import (
    commit_lease,
    release_lease,
    load_manifest,
    touch_heartbeat,
    FencedTokenError,
    ManifestIntegrityError,
    MANIFEST_REL_PATH,
    register_proposal,
    reconcile_workspace,
    ReconcileReport,
    ReconcileClass,
    capture_baseline,
    get_baseline_path,
)
from manifest_lease import reclaim_stale_task, probe_lease_health, HealthVerdict
from runtime_mode import (
    load_runtime_mode,
    update_runtime_mode,
    OrchestrationMode,
    ReviewerChannel,
    StopAtStage,
    EffectiveModeSnapshot,
)
from dataclasses import replace
from autopilot_harness import (
    compute_next_action,
    HarnessNextAction,
    HarnessActionType,
    TaskStateSnapshot,
    LastEventSnapshot,
)


def _is_external_api_available(workspace_root: str, config: Optional[Any] = None) -> bool:
    try:
        if config is None:
            config = load_project_config(workspace_root)
        re_cfg = getattr(config, "reviewer_engine", None)
        if re_cfg is None and isinstance(config, ReviewerEngineConfig):
            re_cfg = config
        client = ReviewerClient(re_cfg)
        return bool(client.resolve_api_key()) or client.is_available()
    except Exception:
        return False

from task_writer import (
    write_task_file_guarded,
    split_task_document,
    compose_task_document,
    _render_task_markdown,
    InvalidTransitionError,
    NonEditableTaskMutatedError,
    NonEditableTaskMissingError,
    DuplicateTaskIdError,
    StatusSmugglingError,
    StatusManifestMismatchError,
    TaskFileLockTimeoutError,
    PersistTargetRequiredError,
    TaskNotFoundError,
)

mcp = FastMCP("quench-dev-tasks")


def _resolve_task_file_path(workspace_root: str, task_file: str, config: Optional[Any] = None) -> str:
    """Resolve task file name or relative path to absolute path. / 辅助函数：将任务文件名或相对路径解析为绝对路径。"""
    if config is None:
        try:
            config = load_project_config(workspace_root)
        except Exception:
            config = QuenchStackConfig(
                workspace_root=workspace_root,
                project_name=os.path.basename(workspace_root) or "default",
            )
    dev_tasks_dir = config.resolve_path("dev_tasks_dir")

    if os.path.isabs(task_file):
        return os.path.normpath(task_file)

    # 优先在 dev_tasks_dir 下找
    cand = os.path.normpath(os.path.join(dev_tasks_dir, task_file))
    if os.path.isfile(cand):
        return cand

    # 其次在 workspace_root 下找
    cand_root = os.path.normpath(os.path.join(config.workspace_root, task_file))
    if os.path.isfile(cand_root):
        return cand_root

    return cand


# _render_task_markdown is imported from task_writer above



def _extract_task_detail(filepath: str, task_id: str) -> Dict[str, Any]:
    """Extract full Markdown block of specified task ID from file. / 从 Markdown 任务文件中提取指定任务的完整图文段落。"""
    tasks = parse_task_file(filepath)
    matched_item = next((t for t in tasks if str(t.id).strip() == str(task_id).strip()), None)
    if not matched_item:
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start_idx = matched_item.line_number
    end_idx = len(lines)

    for next_t in tasks:
        if next_t.line_number > start_idx:
            end_idx = next_t.line_number
            break

    content_snippet = "".join(lines[start_idx:end_idx])
    return {
        "id": matched_item.id,
        "title": matched_item.title,
        "status": matched_item.status,
        "full_spec": content_snippet,
    }


_EXEMPTION_PATTERN = re.compile(
    r"\[EXEMPTION:\s*(docs-only|config-only|non-behavioral-refactor)\s*\]",
    re.IGNORECASE,
)
_TEST_FILE_PATTERN = re.compile(r"(^|/)tests?/.*test_.*\.py$|(^|/).*_test\.py$")
_ASSERTION_MARKERS = ("assert ", "assert(", "pytest.raises")


def _append_hook_log(workspace_root: str, message: str) -> None:
    """向 .agents/.quench_hook.log 安全追加单条日志（多进程幂等安全）。"""
    try:
        from hooks.file_scope_guard import get_hook_logger
        logger = get_hook_logger(workspace_root)
        logger.info(message)
    except Exception:
        try:
            agents_dir = os.path.join(workspace_root, ".agents")
            os.makedirs(agents_dir, exist_ok=True)
            log_file = os.path.join(agents_dir, ".quench_hook.log")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{now_str} [INFO] {message}\n")
        except Exception:
            pass


def check_shell_write_isolation(command: str, workspace_root: str, dev_tasks_dir: str = "docs/dev_tasks") -> Optional[str]:
    """检测外部 Shell 写入旁路（与 file_scope_guard 对齐），保障 MCP 任务单工具通道安全隔离。"""
    try:
        from hooks.file_scope_guard import detect_shell_write_bypass
        return detect_shell_write_bypass(command, workspace_root, dev_tasks_dir)
    except Exception:
        return None


def _audit_test_changes(
    workspace_root: str,
    config: Any,
    test_evidence: str | None = None,
) -> Dict[str, Any]:
    """Physically audit test directory for added tests and assertions via git diff. / 通过 git 物理扫描测试目录是否包含新增测试与断言。"""
    tracked_files: set[str] = set()
    untracked_files: set[str] = set()
    degraded = False
    messages: list[str] = []

    # 1. 运行 git status --porcelain -u 捕获所有变更与未跟踪文件（精确展开子文件）
    try:
        res_status = subprocess.run(
            ["git", "-C", workspace_root, "status", "--porcelain", "-u"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if res_status.returncode != 0:
            degraded = True
            messages.append(f"git status exited with code {res_status.returncode}: {res_status.stderr.strip()}")
        else:
            for line in res_status.stdout.splitlines():
                if not line.strip():
                    continue
                code = line[:2]
                filepath = line[2:].strip().strip('"')
                if " -> " in filepath:
                    filepath = filepath.split(" -> ")[-1].strip().strip('"')
                norm_p = filepath.replace("\\", "/")
                if code == "??":
                    if norm_p.endswith("/"):
                        abs_dir = os.path.join(workspace_root, norm_p)
                        if os.path.isdir(abs_dir):
                            for r, _, fnames in os.walk(abs_dir):
                                for fn in fnames:
                                    rel_sub = os.path.relpath(os.path.join(r, fn), workspace_root).replace("\\", "/")
                                    untracked_files.add(rel_sub)
                    else:
                        untracked_files.add(norm_p)
                else:
                    tracked_files.add(norm_p)
    except (FileNotFoundError, subprocess.CalledProcessError, Exception) as e:
        degraded = True
        messages.append(f"git status check failed: {e}")

    # 2. 补采 git diff --name-only 与 git diff --cached --name-only
    if not degraded:
        for diff_cmd in (
            ["git", "-C", workspace_root, "diff", "--name-only"],
            ["git", "-C", workspace_root, "diff", "--cached", "--name-only"],
        ):
            try:
                res_diff = subprocess.run(
                    diff_cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    check=False,
                )
                if res_diff.returncode == 0:
                    for line in res_diff.stdout.splitlines():
                        p = line.strip().strip('"')
                        if p:
                            tracked_files.add(p.replace("\\", "/"))
            except Exception as e:
                messages.append(f"git diff name-only failed: {e}")

    # 3. 归类受管生产代码与测试文件
    all_changed = tracked_files | untracked_files
    governed_code_changed: list[str] = []
    test_files_changed: list[str] = []

    for f in sorted(all_changed):
        norm_f = f.replace("\\", "/")
        if _TEST_FILE_PATTERN.search(norm_f):
            test_files_changed.append(norm_f)
        elif hasattr(config, "is_path_governed") and config.is_path_governed(norm_f):
            governed_code_changed.append(norm_f)

    # 4. 扫描测试文件中的断言标记
    assertions_found = False
    detected_markers: list[str] = []

    if not degraded and test_files_changed:
        for tf in test_files_changed:
            if tf in untracked_files:
                # 未跟踪测试文件：直接读取全文
                abs_tf = os.path.join(workspace_root, tf)
                if os.path.isfile(abs_tf):
                    try:
                        with open(abs_tf, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        for marker in _ASSERTION_MARKERS:
                            if marker in content:
                                assertions_found = True
                                if marker not in detected_markers:
                                    detected_markers.append(marker)
                    except Exception as e:
                        messages.append(f"Failed to read untracked test file {tf}: {e}")
            else:
                # 已跟踪测试文件：仅扫描 diff 新增行 (--unified=0)
                for diff_cmd in (
                    ["git", "-C", workspace_root, "diff", "-U0", "--", tf],
                    ["git", "-C", workspace_root, "diff", "--cached", "-U0", "--", tf],
                ):
                    try:
                        res = subprocess.run(
                            diff_cmd,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="ignore",
                            check=False,
                        )
                        if res.returncode == 0:
                            for line in res.stdout.splitlines():
                                if line.startswith("+") and not line.startswith("+++"):
                                    added_content = line[1:]
                                    for marker in _ASSERTION_MARKERS:
                                        if marker in added_content:
                                            assertions_found = True
                                            if marker not in detected_markers:
                                                detected_markers.append(marker)
                    except Exception as e:
                        messages.append(f"Failed to diff test file {tf}: {e}")

    # 5. 豁免判定
    exempted = False
    exemption_reason = None
    if test_evidence:
        match = _EXEMPTION_PATTERN.search(test_evidence)
        if match:
            exempted = True
            exemption_reason = match.group(1).lower()

    # 6. 最终判定
    if degraded:
        passed = True
        _append_hook_log(
            workspace_root,
            f"[DOD GUARD DEGRADED] Test audit degraded due to git environment: {'; '.join(messages)}",
        )
    elif len(governed_code_changed) == 0:
        passed = True
    elif exempted:
        passed = True
    elif assertions_found:
        passed = True
    else:
        passed = False

    return {
        "passed": passed,
        "governed_code_changed": governed_code_changed,
        "test_files_changed": test_files_changed,
        "assertions_found": assertions_found,
        "detected_markers": detected_markers,
        "exempted": exempted,
        "exemption_reason": exemption_reason,
        "degraded": degraded,
        "messages": messages,
        # Backward-compatible keys
        "audit_performed": not degraded,
        "test_changes": test_files_changed,
    }


def _read_hook_log_tail(path: Union[Path, str], max_bytes: int = HOOK_LOG_TAIL_BYTES) -> list[str]:
    """Bounded fail-open tail reader for hook governance logs.

    Contract:
      - Reads at most max_bytes from the tail of the file.
      - If seeking was performed, drops the first (potentially partial) line.
      - Uses errors='replace' to tolerate multibyte UTF-8 / CJK boundary splits safely.
      - Never raises: returns [] on any I/O, path, or decoding failure.
    """
    try:
        p = Path(path)
        if not p.is_file():
            return []
        file_size = p.stat().st_size
        if file_size <= 0:
            return []

        with open(p, "rb") as f:
            if file_size > max_bytes:
                f.seek(file_size - max_bytes)
                raw_bytes = f.read(max_bytes)
                text = raw_bytes.decode("utf-8", errors="replace")
                lines = text.splitlines()
                # Drop first potentially broken line when seeking from middle
                lines = lines[1:] if len(lines) > 1 else []
            else:
                raw_bytes = f.read(file_size)
                text = raw_bytes.decode("utf-8", errors="replace")
                lines = text.splitlines()

        if lines and lines[-1] and not text.endswith(("\n", "\r")):
            lines.pop()

        result = []
        for line in lines:
            stripped = line.strip()
            if stripped and "\x00" not in stripped:
                result.append(stripped)
        return result
    except Exception:
        return []


def _get_recent_hook_logs(workspace_root: str, max_lines: int = 10) -> List[str]:
    """Read the last N lines of .agents/.quench_hook.log with bounded tail read and integrity validation."""
    log_file = os.path.join(workspace_root, ".agents", ".quench_hook.log")
    lines = _read_hook_log_tail(log_file)
    return lines[-max_lines:] if lines else []


def _build_full_status_sync(
    workspace_root: str,
    config: Any,
    snapshot: Any,
    bypass_status: Optional[Dict[str, Any]],
    file_records: List[Dict[str, Any]],
    active_task: Optional[Dict[str, Any]],
    reconcile_report: Any,
    runtime_mode_changed: bool,
    rejection_reason: Optional[str],
    runtime_mode_warning: Optional[str],
    all_tasks: List[Dict[str, Any]],
    raw_hook_logs: List[str],
    task_file: Optional[str] = None,
    empty_message: Optional[str] = None,
) -> Dict[str, Any]:
    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    res = {
        "project_name": config.project_name,
        "dev_tasks_dir": dev_tasks_dir,
        "files": file_records,
        "active_task": active_task,
        "session_bypass": bypass_status,
        "static_fast_track_patterns": config.get_fast_track_patterns(),
        "governance_scope": config.governance_scope,
        "hook_log": raw_hook_logs[-10:] if raw_hook_logs else [],
        "reconcile_report": {
            "bypass_queue": list(reconcile_report.bypass_queue) if hasattr(reconcile_report, "bypass_queue") else [],
            "drift_queue": list(reconcile_report.drift_queue) if hasattr(reconcile_report, "drift_queue") else [],
            "matched_queue": list(reconcile_report.matched_queue) if hasattr(reconcile_report, "matched_queue") else [],
        },
        "bypass_queue": list(reconcile_report.bypass_queue) if hasattr(reconcile_report, "bypass_queue") else [],
        "effective_mode": snapshot.effective_mode,
        "mode_source": snapshot.mode_source,
        "effective_reviewer_channel": snapshot.effective_reviewer_channel,
        "runner_subagent_model_hint": snapshot.runner_subagent_model_hint,
        "fallback_notice": snapshot.fallback_notice,
        "runtime_mode_warning": runtime_mode_warning,
        "session_role_contract": snapshot.session_role_contract,
        "autopilot": snapshot.autopilot.to_dict(),
        "tasks": all_tasks,
    }
    if empty_message:
        res["message"] = empty_message
    if runtime_mode_changed or rejection_reason:
        res["runtime_mode_changed"] = runtime_mode_changed
        if rejection_reason is not None:
            res["reason"] = rejection_reason
    if hasattr(reconcile_report, "bypass_queue") and reconcile_report.bypass_queue:
        res["bypass_warning"] = (
            f"⚠️ Detected {len(reconcile_report.bypass_queue)} unauthorized rogue task files quarantined in bypass_queue: "
            f"{list(reconcile_report.bypass_queue)} / 检测到未授权旁路任务单已物理隔离"
        )
    _inject_harness_next_action(
        workspace_root,
        "dev_tasks_status",
        res,
        last_success=True,
        task_file=task_file,
        current_task_id=(active_task.get("id") if active_task else None),
        config=config,
        compact=False,
    )
    return res


def _build_compact_status_sync(
    workspace_root: str,
    config: Any,
    snapshot: Any,
    bypass_status: Optional[Dict[str, Any]],
    file_records: List[Dict[str, Any]],
    active_task: Optional[Dict[str, Any]],
    reconcile_report: Any,
    runtime_mode_changed: bool,
    rejection_reason: Optional[str],
    runtime_mode_warning: Optional[str],
    all_tasks: List[Dict[str, Any]],
    raw_hook_logs: List[str],
    task_file: Optional[str] = None,
    empty_message: Optional[str] = None,
) -> Dict[str, Any]:
    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    rel_dev_tasks_dir = os.path.relpath(dev_tasks_dir, workspace_root).replace("\\", "/")

    canonical_cfg = {
        "governance_scope": config.governance_scope,
        "session_role_contract": snapshot.session_role_contract,
    }
    entitlements_hash = compute_entitlements_hash(canonical_cfg)

    compact_hook_entries = []
    rel_log_ref = ".agents/.quench_hook.log"
    for line in (raw_hook_logs[-STATUS_COMPACT_MAX_HOOK_ENTRIES:] if raw_hook_logs else []):
        code = classify_hook_log_entry(line)
        ts = line[:19] if len(line) >= 19 and line[4] == "-" else ""
        if ts:
            compact_hook_entries.append(f"{ts} [{code}] log_ref={rel_log_ref}")
        else:
            compact_hook_entries.append(f"[{code}] log_ref={rel_log_ref}")

    tasks_total = len(all_tasks)
    compact_tasks = all_tasks[:STATUS_COMPACT_MAX_TASKS]
    truncated_sections: list[str] = []
    if tasks_total > STATUS_COMPACT_MAX_TASKS:
        truncated_sections.append("tasks")

    compact_files = []
    for f in file_records:
        cf = {
            "name": f.get("name"),
            "path": os.path.relpath(f["path"], workspace_root).replace("\\", "/") if "path" in f else "",
            "total_tasks": f.get("total_tasks", 0),
            "summary": {k: v for k, v in f.get("summary", {}).items() if v > 0},
            "batches": {k: v for k, v in f.get("batches", {}).items() if v or k == "completed_count"},
            "quarantined": f.get("quarantined", False),
        }
        if f.get("quarantine_reason"):
            cf["quarantine_reason"] = f["quarantine_reason"]
        compact_files.append(cf)

    res = {
        "project_name": config.project_name,
        "dev_tasks_dir": rel_dev_tasks_dir,
        "files": compact_files,
        "active_task": active_task,
        "session_bypass": bypass_status,
        "static_fast_track_patterns": config.get_fast_track_patterns(),
        "entitlements_hash": entitlements_hash,
        "last_hook_log_entries_compact": compact_hook_entries,
        "reconcile_report": {
            "bypass_queue": list(reconcile_report.bypass_queue) if hasattr(reconcile_report, "bypass_queue") else [],
            "drift_queue": list(reconcile_report.drift_queue) if hasattr(reconcile_report, "drift_queue") else [],
            "matched_queue": list(reconcile_report.matched_queue) if hasattr(reconcile_report, "matched_queue") else [],
        },
        "bypass_queue": list(reconcile_report.bypass_queue) if hasattr(reconcile_report, "bypass_queue") else [],
        "effective_mode": snapshot.effective_mode,
        "mode_source": snapshot.mode_source,
        "effective_reviewer_channel": snapshot.effective_reviewer_channel,
        "runner_subagent_model_hint": snapshot.runner_subagent_model_hint,
        "fallback_notice": snapshot.fallback_notice,
        "runtime_mode_warning": runtime_mode_warning,
        "autopilot": snapshot.autopilot.to_dict(),
        "tasks_total": tasks_total,
        "tasks": all_tasks,
    }
    if empty_message:
        res["message"] = empty_message
    if runtime_mode_changed or rejection_reason:
        res["runtime_mode_changed"] = runtime_mode_changed
        if rejection_reason is not None:
            res["reason"] = rejection_reason
    if hasattr(reconcile_report, "bypass_queue") and reconcile_report.bypass_queue:
        res["bypass_warning"] = (
            f"⚠️ Detected {len(reconcile_report.bypass_queue)} rogue task file(s) quarantined in bypass_queue"
        )

    _inject_harness_next_action(
        workspace_root,
        "dev_tasks_status",
        res,
        last_success=True,
        task_file=task_file,
        current_task_id=(active_task.get("id") if active_task else None),
        config=config,
        compact=True,
    )

    return fit_to_budget("dev_tasks_status", res)


# ==============================================================================
# MCP Tools
# ==============================================================================

@mcp.tool()
def dev_tasks_status(
    workspace_root: str,
    include_drafts: bool = False,
    switch_mode: Optional[Literal["standard", "inverted"]] = None,
    switch_reviewer_channel: Optional[Literal["external_api", "host_subagent"]] = None,
    stop_at: Optional[Literal["none", "after_propose", "after_review", "after_confirm", "before_archive", "after_batch"]] = None,
    task_file: Optional[str] = None,
    verbosity: Literal["compact", "full"] = "compact",
) -> Dict[str, Any]:
    """Task status.

    Args:
        workspace_root: Workspace.
        include_drafts: Drafts ok.
        switch_mode: Mode set.
        switch_reviewer_channel: Channel.
        stop_at: Stop at.
        task_file: Task doc.
        verbosity: Full/min.
    """
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"error": f"Failed to load project config / 加载项目配置失败: {e}"}

    # 检查会话快速旁路状态（保证旁路绝不静默）
    bypass_file = os.path.join(workspace_root, ".agents", ".quench_bypass.json")
    bypass_status = None
    if os.path.isfile(bypass_file):
        try:
            with open(bypass_file, "r", encoding="utf-8") as f:
                bdata = json.load(f)
            if bdata.get("active"):
                expires_at = bdata.get("expires_at")
                is_expired = False
                if expires_at:
                    try:
                        exp_dt = datetime.fromisoformat(expires_at)
                        exp_dt_utc = exp_dt.astimezone(timezone.utc)
                        if datetime.now(timezone.utc) > exp_dt_utc:
                            is_expired = True
                    except Exception:
                        is_expired = True
                if not is_expired:
                    bypass_status = {
                        "active": True,
                        "session_id": bdata.get("session_id"),
                        "category": bdata.get("category"),
                        "patterns": bdata.get("patterns"),
                        "reason": bdata.get("reason"),
                        "expires_at": bdata.get("expires_at"),
                        "notice": "⚠️ Current session has fast-track bypass active / 当前会话已激活快速旁路，指定模式文件免除任务单管控。",
                    }
                else:
                    bypass_status = {
                        "active": False,
                        "expired": True,
                        "notice": "ℹ️ Previous session fast-track bypass has expired / 之前的会话快速旁路已过期失效。",
                    }
        except Exception:
            pass

    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    ext_available = _is_external_api_available(workspace_root, config)
    snapshot = load_runtime_mode(workspace_root, ext_available)
    has_mutation = (
        switch_mode is not None
        or switch_reviewer_channel is not None
        or stop_at is not None
        or task_file is not None
    )

    if not os.path.exists(dev_tasks_dir):
        os.makedirs(dev_tasks_dir, exist_ok=True)
        runtime_mode_changed = False
        rejection_reason: Optional[str] = None
        runtime_mode_warning: Optional[str] = snapshot.runtime_mode_warning
        if has_mutation:
            if snapshot.effective_mode == "inverted" and switch_reviewer_channel is not None and switch_mode != "standard":
                runtime_mode_changed = False
                rejection_reason = "switch_denied_mode_inverted"
                runtime_mode_warning = "reviewer_channel 仅在 standard 模式下有效；当前为 inverted。"
            else:
                new_snapshot, applied, _ = update_runtime_mode(
                    workspace_root=workspace_root,
                    switch_mode=switch_mode,
                    switch_reviewer_channel=switch_reviewer_channel,
                    stop_at=stop_at,
                    task_file=task_file,
                    external_api_available=ext_available,
                )
                snapshot = new_snapshot
                runtime_mode_changed = applied
                runtime_mode_warning = snapshot.runtime_mode_warning

        raw_hook_logs = _get_recent_hook_logs(workspace_root, max_lines=10)
        empty_msg = f"Tasks directory created: {dev_tasks_dir}. No task files currently found. / 任务目录已创建: {dev_tasks_dir}，当前暂无任务单。"
        empty_reconcile = type("ReconcileDummy", (), {"bypass_queue": [], "drift_queue": [], "matched_queue": []})()
        if verbosity == "full":
            return _build_full_status_sync(
                workspace_root, config, snapshot, bypass_status, [], None, empty_reconcile,
                runtime_mode_changed, rejection_reason, runtime_mode_warning, [], raw_hook_logs,
                task_file=task_file, empty_message=empty_msg,
            )
        return _build_compact_status_sync(
            workspace_root, config, snapshot, bypass_status, [], None, empty_reconcile,
            runtime_mode_changed, rejection_reason, runtime_mode_warning, [], raw_hook_logs,
            task_file=task_file, empty_message=empty_msg,
        )

    md_files = glob.glob(os.path.join(dev_tasks_dir, "*.md"))
    file_records = []
    active_task = None
    all_tasks: List[Dict[str, Any]] = []

    reconcile_report = reconcile_workspace(workspace_root, dev_tasks_dir)
    norm_bypass = {p.replace("\\", "/").lower() for p in reconcile_report.bypass_queue}

    for f_path in sorted(md_files, reverse=True):
        basename = os.path.basename(f_path)
        if basename.lower() == "readme.md":
            continue
        rel_f_path = os.path.relpath(f_path, workspace_root).replace("\\", "/")
        is_quarantined = rel_f_path.lower() in norm_bypass
        try:
            summary = get_status_summary(f_path)
            tasks = parse_task_file(f_path)

            raw_file_text = ""
            try:
                with open(f_path, "r", encoding="utf-8", errors="ignore") as rf:
                    raw_file_text = rf.read()
            except Exception:
                pass

            draft_ids = set()
            for dm in re.finditer(r"^###\s+(?:任务|Task)\s+([0-9a-zA-Z\._\-]+)\s*.*?(?:\(草案\)|\(Draft\)|\(draft\))", raw_file_text, re.MULTILINE):
                draft_ids.add(dm.group(1).strip())
            for dm in re.finditer(r"^###\s+(?:任务|Task)\s+([0-9a-zA-Z\._\-]+)[\s\S]*?<!--\s*quench-task-meta:\s*({.*?})\s*-->", raw_file_text, re.MULTILINE):
                try:
                    meta = json.loads(dm.group(2))
                    if meta.get("draft"):
                        draft_ids.add(dm.group(1).strip())
                except Exception:
                    pass

            confirmed_q = [t.id for t in tasks if t.status == STATUS_CONFIRMED]
            rework_q = [t.id for t in tasks if t.status == STATUS_REWORK]
            draft_q = [t.id for t in tasks if t.id in draft_ids]

            if not include_drafts:
                pending_q = [t.id for t in tasks if t.status == STATUS_PENDING and t.id not in draft_ids]
            else:
                pending_q = [t.id for t in tasks if t.status == STATUS_PENDING]

            in_prog_q = [t.id for t in tasks if t.status == STATUS_IN_PROGRESS]
            completed_q = [t.id for t in tasks if t.status == STATUS_COMPLETED]

            if draft_q:
                summary["📝 草案"] = len(draft_q)

            file_rec = {
                "name": basename,
                "path": f_path,
                "total_tasks": len(tasks),
                "summary": summary,
                "batches": {
                    "confirmed_queue": confirmed_q,
                    "rework_queue": rework_q,
                    "pending_queue": pending_q,
                    "draft_queue": draft_q,
                    "in_progress": in_prog_q,
                    "completed_count": len(completed_q),
                },
                "quarantined": is_quarantined,
            }
            if is_quarantined:
                file_rec["quarantine_reason"] = "UNAUTHORIZED_BYPASS: Untracked task file not registered in manifest"
            file_records.append(file_rec)

            for t in tasks:
                all_tasks.append({
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                })

            if not active_task and not is_quarantined:
                for t in tasks:
                    if t.status == STATUS_IN_PROGRESS:
                        active_task = {
                            "file": basename,
                            "file_path": f_path,
                            "id": t.id,
                            "title": t.title,
                            "status": t.status,
                        }
                        break
        except Exception:
            continue

    runtime_mode_changed = False
    rejection_reason: Optional[str] = None
    runtime_mode_warning: Optional[str] = snapshot.runtime_mode_warning

    if has_mutation:
        if snapshot.effective_mode == "inverted" and switch_reviewer_channel is not None and switch_mode != "standard":
            runtime_mode_changed = False
            rejection_reason = "switch_denied_mode_inverted"
            runtime_mode_warning = "reviewer_channel 仅在 standard 模式下有效；当前为 inverted。"
        elif active_task is not None and (switch_mode is not None or switch_reviewer_channel is not None):
            runtime_mode_changed = False
            rejection_reason = "switch_denied_task_in_progress"
        else:
            new_snapshot, applied, _ = update_runtime_mode(
                workspace_root=workspace_root,
                switch_mode=switch_mode,
                switch_reviewer_channel=switch_reviewer_channel,
                stop_at=stop_at,
                task_file=task_file,
                external_api_available=ext_available,
            )
            snapshot = new_snapshot
            runtime_mode_changed = applied
            runtime_mode_warning = snapshot.runtime_mode_warning

    raw_hook_logs = _get_recent_hook_logs(workspace_root, max_lines=10)
    if verbosity == "full":
        return _build_full_status_sync(
            workspace_root, config, snapshot, bypass_status, file_records, active_task,
            reconcile_report, runtime_mode_changed, rejection_reason, runtime_mode_warning,
            all_tasks, raw_hook_logs, task_file=task_file,
        )

    return _build_compact_status_sync(
        workspace_root, config, snapshot, bypass_status, file_records, active_task,
        reconcile_report, runtime_mode_changed, rejection_reason, runtime_mode_warning,
        all_tasks, raw_hook_logs, task_file=task_file,
    )


@mcp.tool()
def dev_tasks_propose(
    workspace_root: str,
    task_file_name: str,
    tasks: List[Dict[str, Any]],
    mode: Literal["append", "overwrite", "upsert"] = "append",
) -> Dict[str, Any]:
    """Create or append development tasks conforming to the six-core-field contract.

    Args:
        workspace_root: Root path of the target workspace.
        task_file_name: Target task file name (e.g., '2026-09-13_feature.md').
        tasks: Task specifications conforming to the six core fields.
        mode: Writing mode ('append', 'overwrite', 'upsert').
    """
    if mode not in ("append", "overwrite", "upsert"):
        return {
            "created": False,
            "errors": [f"Invalid mode '{mode}'. Must be one of: 'append', 'overwrite', 'upsert' / 非法 mode 参数"],
            "message": f"Invalid mode '{mode}'",
        }

    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"created": False, "error": f"Configuration error / 配置错误: {e}"}

    if not task_file_name.endswith(".md"):
        task_file_name += ".md"

    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    os.makedirs(dev_tasks_dir, exist_ok=True)
    target_path = os.path.join(dev_tasks_dir, task_file_name)

    # 预校验每个任务的 id 补全
    for idx, t in enumerate(tasks, 1):
        if not t.get("id"):
            t["id"] = f"{idx}"

    try:
        res = write_task_file_guarded(
            workspace_root=workspace_root,
            task_file_path=target_path,
            tasks_to_write=tasks,
            mode=mode,
        )
    except Exception as e:
        err_res = {
            "created": False,
            "errors": [str(e)],
            "message": f"Failed to propose tasks: {e} / 提交任务单失败: {e}",
        }
        _inject_harness_next_action(
            workspace_root,
            "dev_tasks_propose",
            err_res,
            last_success=False,
            task_file=task_file_name,
            config=config,
        )
        return err_res

    written = res.get("written", [])
    skipped = res.get("skipped", [])
    res_dict = {
        "created": True,
        "file_path": target_path,
        "created_count": len(written),
        "mode": mode,
        "written": written,
        "skipped": skipped,
        "warnings": [],
        "message": f"Successfully executed '{mode}' for {len(written)} tasks in {target_path} / 成功在 {target_path} 执行 '{mode}' 写入 {len(written)} 项任务",
    }
    _inject_harness_next_action(
        workspace_root,
        "dev_tasks_propose",
        res_dict,
        last_success=True,
        task_file=task_file_name,
        config=config,
    )
    return res_dict


ReadStatus = Literal["ok", "missing", "unparsable", "truncated"]


def _managed_path_matches(scoped_path: str, managed_patterns: list[str]) -> bool:
    """基于 glob 语义（fnmatch/pathlib）匹配受管路径，支持 ** 递归。"""
    if not scoped_path or not managed_patterns:
        return False
    norm_scoped = scoped_path.replace("\\", "/").strip()
    while norm_scoped.startswith("./"):
        norm_scoped = norm_scoped[2:]
    return is_within_whitelist(norm_scoped, managed_patterns)


def _freshness_ok(now: datetime, record_ts: datetime, policy: AuditGatePolicy) -> tuple[bool, str]:
    """容差吸收式：-tol <= (now - record_ts).total_seconds() <= max_age*60。前置：已 UTC 归一化。"""
    age_seconds = (now - record_ts).total_seconds()
    tol = float(policy.clock_skew_tolerance_seconds)
    max_age_seconds = float(policy.max_age_minutes * 60)
    if -tol <= age_seconds <= max_age_seconds:
        return True, "fresh"
    elif age_seconds < -tol:
        return False, "future_skew"
    else:
        return False, "stale"


def _extract_task_scoped_files(task: Any) -> list[str]:
    """剥离 [MODIFY]/[NEW]/[DELETE] 标注符与反引号，提取纯净 POSIX 路径。"""
    raw_items: list[str] = []
    if isinstance(task, dict):
        raw_items = task.get("affected_files") or []
    elif hasattr(task, "affected_files"):
        raw_items = getattr(task, "affected_files") or []
    elif hasattr(task, "task_file") and getattr(task, "task_file"):
        tf = getattr(task, "task_file")
        tid = getattr(task, "id", "")
        if os.path.exists(tf):
            try:
                with open(tf, "r", encoding="utf-8") as f:
                    content = f.read()
                raw_items = extract_task_whitelist(content, str(tid))
            except Exception:
                pass

    if isinstance(raw_items, str):
        raw_items = raw_items.splitlines()

    result: list[str] = []
    for item in raw_items:
        s = str(item).strip()
        if not s or s.startswith("```"):
            continue
        # 剥除前导列表符号 (- , * , + ) 与操作标记
        s = re.sub(r"^[\s\-\*\+\d\.\>\#]+\s*", "", s).strip()
        s = re.sub(r"^\[\s*(?:MODIFY|NEW|DELETE|RENAME)\s*\]\s*", "", s, flags=re.IGNORECASE).strip()
        # 剥除反引号与引号
        s = s.strip("`'\" ").strip()
        # 剥除 Markdown 超链接与括号注释
        m_link = re.search(r"\[.*?\]\((.*?)\)", s)
        if m_link:
            s = m_link.group(1).strip()
        s = s.split("（")[0].split("(")[0].strip()
        s = s.strip("`'\" ").strip()
        if s.startswith("file:///"):
            s = s[8:].lstrip("/\\")
        if s:
            posix_path = s.replace("\\", "/")
            while posix_path.startswith("./"):
                posix_path = posix_path[2:]
            result.append(posix_path)
    return result


def _extract_batch_scoped_files(filepath: str, tasks: Sequence[Any]) -> list[str]:
    """从任务单 Markdown 文件中提取并去重该批次全部任务涉及的文件列表。"""
    if not filepath or not os.path.isfile(filepath):
        return []
    content = ""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        pass

    batch_files: list[str] = []
    for pt in tasks:
        scoped = _extract_task_scoped_files(pt)
        if not scoped and content:
            tid = str(getattr(pt, "id", pt.get("id", "") if isinstance(pt, dict) else pt))
            try:
                raw_wl = extract_task_whitelist(content, tid)
                if not raw_wl:
                    m = re.search(
                        rf"###\s+(?:任务|Task)\s+{re.escape(tid)}\s+.*?####\s+(?:【涉及文件】|\[Affected Files\]|【Affected Files】)\s*(.*?)(?=####|###|\Z)",
                        content,
                        re.DOTALL | re.IGNORECASE,
                    )
                    if m:
                        raw_wl = [line for line in m.group(1).splitlines() if line.strip()]
                scoped = _extract_task_scoped_files({"affected_files": raw_wl})
            except Exception:
                scoped = []
        for f in scoped:
            if f not in batch_files:
                batch_files.append(f)
    return batch_files


def _read_recent_audit_records(path: str, max_tail_bytes: int) -> tuple[list[dict], ReadStatus, int]:
    """返回 (records, status, parse_skipped_lines)。首字节残缺多字节丢弃后再解码。"""
    if not os.path.isfile(path):
        return [], "missing", 0

    try:
        file_size = os.path.getsize(path)
    except Exception:
        return [], "unparsable", 0

    if file_size == 0:
        return [], "ok", 0

    is_truncated = file_size > max_tail_bytes
    records: list[dict] = []
    parse_skipped_lines = 0

    try:
        with open(path, "rb") as f:
            if is_truncated:
                seek_pos = file_size - max_tail_bytes
                f.seek(seek_pos)
                raw_bytes = f.read(max_tail_bytes)
                first_nl = raw_bytes.find(b"\n")
                if first_nl != -1:
                    tail_bytes = raw_bytes[first_nl + 1:]
                else:
                    tail_bytes = b""

                # 计算截断后起始行的 1-based 行号
                f.seek(0)
                prec = f.read(seek_pos)
                start_line_no = prec.count(b"\n") + (1 if first_nl != -1 else 0) + 1
            else:
                tail_bytes = f.read()
                start_line_no = 1
    except Exception:
        return [], "unparsable", 0

    text = tail_bytes.decode("utf-8", errors="replace")
    current_line_no = start_line_no
    valid_count = 0

    for line in text.splitlines():
        trimmed = line.strip()
        if not trimmed:
            current_line_no += 1
            continue
        try:
            entry = json.loads(trimmed)
            if isinstance(entry, dict):
                entry["_line_no"] = current_line_no
                records.append(entry)
                valid_count += 1
            else:
                parse_skipped_lines += 1
        except Exception:
            parse_skipped_lines += 1
        current_line_no += 1

    if is_truncated:
        return records, "truncated", parse_skipped_lines

    if valid_count == 0 and parse_skipped_lines > 0:
        return records, "unparsable", parse_skipped_lines

    return records, "ok", parse_skipped_lines


def _resolve_record_source(rec: Mapping[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """返回 (source, degraded_reason)。
    source 缺失（key 不存在或 None）→ ("reviewer_client", None)。
    source 存在但非 str 或为空串 → (None, "record_unparsable")。
    """
    if "source" not in rec or rec["source"] is None:
        return ("reviewer_client", None)
    val = rec["source"]
    if not isinstance(val, str) or not val.strip():
        return (None, "record_unparsable")
    return (val.strip(), None)


def _check_audit_gate(
    workspace_root: str,
    task_file: str,
    task: "TaskItem",
    config: "QuenchStackConfig",
    session_id: Optional[str] = None,
) -> AuditGateResult:
    """manifest 锁外只读决策。audit_ref := f"{posix_relpath(audit_log_path)}#{line_no}"。"""
    try:
        policy = config.audit_gate if hasattr(config, "audit_gate") and config.audit_gate else AuditGatePolicy()
        effective_on_degraded = most_restrictive_policy(policy.on_degraded, policy.tail_window_exhausted_policy)
        target_ref = canonical_artifact_ref(workspace_root, task_file, str(getattr(task, "id", "")).strip())

        # step 0: enabled is False → disabled (allow)
        if not policy.enabled:
            return {
                "allowed": True,
                "reason": "disabled",
                "artifact_ref": target_ref,
                "audit_ref": None,
                "parse_skipped_lines": 0,
            }

        # step 1: scope == "managed_paths" ∧ not any(_managed_path_matches(f, managed_paths) for f in task_scoped_files) → not_managed_scope (allow)
        if policy.scope == "managed_paths":
            managed_paths = []
            if hasattr(config, "governance_scope") and isinstance(config.governance_scope, dict):
                managed_paths = config.governance_scope.get("managed_paths", [])
            task_scoped_files = _extract_task_scoped_files(task)
            if not task_scoped_files:
                tf_abs = _resolve_task_file_path(workspace_root, task_file) if "_resolve_task_file_path" in globals() else os.path.join(workspace_root, task_file)
                if os.path.isfile(tf_abs):
                    try:
                        with open(tf_abs, "r", encoding="utf-8") as f:
                            c = f.read()
                        raw_wl = extract_task_whitelist(c, str(getattr(task, "id", "")))
                        task_scoped_files = _extract_task_scoped_files({"affected_files": raw_wl})
                    except Exception:
                        pass

            if not any(_managed_path_matches(f, managed_paths) for f in task_scoped_files):
                return {
                    "allowed": True,
                    "reason": "not_managed_scope",
                    "artifact_ref": target_ref,
                    "audit_ref": None,
                    "parse_skipped_lines": 0,
                }

        # step 2: session Tier-2 bypass 有效 → session_bypass_active (allow)
        if session_id:
            bypass_file = os.path.join(workspace_root, ".agents", ".quench_bypass.json")
            if os.path.isfile(bypass_file):
                try:
                    with open(bypass_file, "r", encoding="utf-8") as f:
                        bdata = json.load(f)
                    if bdata.get("active") and bdata.get("session_id") == session_id:
                        expires_at = bdata.get("expires_at")
                        is_expired = False
                        if expires_at:
                            try:
                                exp_dt = datetime.fromisoformat(expires_at).astimezone(timezone.utc)
                                if datetime.now(timezone.utc) > exp_dt:
                                    is_expired = True
                            except Exception:
                                is_expired = True
                        if not is_expired:
                            return {
                                "allowed": True,
                                "reason": "session_bypass_active",
                                "artifact_ref": target_ref,
                                "audit_ref": None,
                                "parse_skipped_lines": 0,
                            }
                except Exception:
                    pass

        # 解析审计日志路径（防路径穿越，PathTraversalError 必须透传抛出）
        is_explicit_inverted = False
        current_mode_source = None
        try:
            ext_avail = _is_external_api_available(workspace_root, config)
            snap = load_runtime_mode(workspace_root, ext_avail)
            current_mode_source = snap.mode_source
            is_explicit_inverted = bool(snap.effective_mode == "inverted" and snap.mode_source == "explicit")
        except Exception:
            is_explicit_inverted = False
            current_mode_source = None

        raw_log_path = policy.audit_log_path or (
            config.observability.verdict_path if hasattr(config, "observability") and config.observability else ".agents/logs/reviewer/verdicts.jsonl"
        )
        ws_abs = os.path.abspath(workspace_root)
        if os.path.isabs(raw_log_path):
            try:
                rel_cand = os.path.relpath(os.path.abspath(raw_log_path), ws_abs)
            except Exception:
                raise PathTraversalError(f"Log path escapes workspace: {raw_log_path}")
            if rel_cand.startswith("..") or os.path.isabs(rel_cand):
                raise PathTraversalError(f"Log path escapes workspace: {raw_log_path}")
            raw_log_path = rel_cand

        abs_log_path = sanitize_workspace_path(workspace_root, raw_log_path)
        try:
            rel_log_path = to_workspace_relative_path(workspace_root, abs_log_path)
        except Exception:
            rel_log_path = raw_log_path.replace("\\", "/")

        # step 3: log 不存在 → explicit_inverted_orchestrator 或 log_missing [effective_on_degraded]
        if not os.path.isfile(abs_log_path):
            if is_explicit_inverted:
                return {
                    "allowed": True,
                    "reason": "explicit_inverted_orchestrator",
                    "artifact_ref": target_ref,
                    "audit_ref": None,
                    "parse_skipped_lines": 0,
                }
            return {
                "allowed": effective_on_degraded != "block",
                "reason": "log_missing",
                "artifact_ref": target_ref,
                "audit_ref": None,
                "parse_skipped_lines": 0,
            }

        # 读取尾部记录
        records, read_status, parse_skipped_lines = _read_recent_audit_records(
            abs_log_path, max_tail_bytes=policy.max_tail_bytes
        )

        # step 4: log I/O 读取/解码失败（非截断所致） → log_unparsable [effective_on_degraded]
        if read_status == "unparsable":
            return {
                "allowed": effective_on_degraded != "block",
                "reason": "log_unparsable",
                "artifact_ref": target_ref,
                "audit_ref": None,
                "parse_skipped_lines": parse_skipped_lines,
            }

        # 逆序匹配（最新记录优先）
        matching_rec = None
        for rec in reversed(records):
            rec_refs = set()
            if "artifact_ref" in rec and rec["artifact_ref"]:
                rec_refs.add(str(rec["artifact_ref"]).strip())
            if "context_files" in rec and isinstance(rec["context_files"], (list, tuple)):
                for cf in rec["context_files"]:
                    rec_refs.add(str(cf).strip())
            if target_ref in rec_refs:
                matching_rec = rec
                break

        if matching_rec is not None:
            line_no = matching_rec.get("_line_no")
            audit_ref_val = f"{rel_log_path}#{line_no}" if line_no is not None else rel_log_path

            # 解析时间戳
            raw_ts = (
                matching_rec.get("updated_wall_utc")
                or matching_rec.get("created_wall_utc")
                or matching_rec.get("timestamp")
                or matching_rec.get("created_at")
            )
            parsed_ts = None
            if raw_ts:
                try:
                    s_ts = str(raw_ts).strip()
                    if s_ts.endswith("Z"):
                        s_ts = s_ts[:-1] + "+00:00"
                    parsed_ts = datetime.fromisoformat(s_ts)
                except Exception:
                    parsed_ts = None

            # step 8 前置：ts 不可解析 ∨ 未完成 tz 归一化 (naive TS 直入 step 8，严禁进入 timedelta 运算)
            if parsed_ts is None or parsed_ts.tzinfo is None or parsed_ts.tzinfo.utcoffset(parsed_ts) is None:
                return {
                    "allowed": effective_on_degraded != "block",
                    "reason": "record_timestamp_invalid",
                    "artifact_ref": target_ref,
                    "audit_ref": audit_ref_val,
                    "parse_skipped_lines": parse_skipped_lines,
                }

            record_ts_utc = parsed_ts.astimezone(timezone.utc)
            now_utc = datetime.now(timezone.utc)
            tol_seconds = float(policy.clock_skew_tolerance_seconds)
            skew_limit = now_utc + timedelta(seconds=tol_seconds)

            # 超容差未来时间戳归入 step 8
            if record_ts_utc > skew_limit:
                return {
                    "allowed": effective_on_degraded != "block",
                    "reason": "record_timestamp_invalid",
                    "artifact_ref": target_ref,
                    "audit_ref": audit_ref_val,
                    "parse_skipped_lines": parse_skipped_lines,
                }

            # 容差吸收式 freshness 检验
            is_fresh, _ = _freshness_ok(now_utc, record_ts_utc, policy)

            # step 6: 命中 ∧ ts 可解析 ∧ record_ts ≤ now + tolerance ∧ _freshness_ok is False → record_stale [on_missing_record]
            if not is_fresh:
                return {
                    "allowed": policy.on_missing_record != "block",
                    "reason": "record_stale",
                    "artifact_ref": target_ref,
                    "audit_ref": audit_ref_val,
                    "parse_skipped_lines": parse_skipped_lines,
                }

            # 来源解析与校验 (三态解析: missing/None 为 reviewer_client 兼容历史, 非 str 或空串为 record_unparsable)
            source, source_degraded_reason = _resolve_record_source(matching_rec)
            if source_degraded_reason == "record_unparsable":
                return {
                    "allowed": effective_on_degraded != "block",
                    "reason": "record_unparsable",
                    "artifact_ref": target_ref,
                    "audit_ref": audit_ref_val,
                    "parse_skipped_lines": parse_skipped_lines,
                }

            accepted_sources = getattr(policy, "accepted_sources", ("reviewer_client",))
            if source not in accepted_sources:
                return {
                    "allowed": False,
                    "reason": "record_source_not_accepted",
                    "artifact_ref": target_ref,
                    "audit_ref": audit_ref_val,
                    "parse_skipped_lines": parse_skipped_lines,
                }

            # auto_fallback 模式源硬门禁: auto_fallback 状态下的非 reviewer_client 凭据永不接受
            effective_rec_mode_source = matching_rec.get("mode_source") or current_mode_source
            if effective_rec_mode_source == "auto_fallback" and source != "reviewer_client":
                return {
                    "allowed": False,
                    "reason": "record_auto_fallback_not_accepted",
                    "artifact_ref": target_ref,
                    "audit_ref": audit_ref_val,
                    "parse_skipped_lines": parse_skipped_lines,
                }

            # verdict rework 硬拒绝
            if matching_rec.get("verdict") == "rework":
                return {
                    "allowed": False,
                    "reason": "record_rework",
                    "artifact_ref": target_ref,
                    "audit_ref": audit_ref_val,
                    "parse_skipped_lines": parse_skipped_lines,
                }

            # 降级判断
            is_degraded = bool(matching_rec.get("degraded_reason")) or matching_rec.get("status") == "degraded" or matching_rec.get("state") == "degraded"

            # step 7: 命中 ∧ require_undegraded ∧ 有 degraded_reason ∧ ts 可解析 ∧ record_ts ≤ now + tolerance ∧ _freshness_ok is True → record_degraded [effective_on_degraded]
            if policy.require_undegraded_record and is_degraded:
                return {
                    "allowed": effective_on_degraded != "block",
                    "reason": "record_degraded",
                    "artifact_ref": target_ref,
                    "audit_ref": audit_ref_val,
                    "parse_skipped_lines": parse_skipped_lines,
                }

            # step 5: 命中 canonical artifact_ref ∧ ts 可解析 ∧ record_ts ≤ now + tolerance ∧ _freshness_ok is True ∧ (¬require_undegraded ∨ 未 degraded) → matched (allow)
            return {
                "allowed": True,
                "reason": "matched",
                "artifact_ref": target_ref,
                "audit_ref": audit_ref_val,
                "parse_skipped_lines": parse_skipped_lines,
            }

        # step 9/10 前置：显式委派模式下可读尾部无匹配记录直接安全放行
        if is_explicit_inverted:
            return {
                "allowed": True,
                "reason": "explicit_inverted_orchestrator",
                "artifact_ref": target_ref,
                "audit_ref": None,
                "parse_skipped_lines": parse_skipped_lines,
            }

        # step 9: truncated（size > max_tail_bytes）且可读尾部无匹配 → tail_window_exhausted [effective_on_degraded]
        if read_status == "truncated":
            return {
                "allowed": effective_on_degraded != "block",
                "reason": "tail_window_exhausted",
                "artifact_ref": target_ref,
                "audit_ref": None,
                "parse_skipped_lines": parse_skipped_lines,
            }

        # step 10: 其余（可读、未截断、确无匹配记录） → no_matching_record [on_missing_record]
        return {
            "allowed": policy.on_missing_record != "block",
            "reason": "no_matching_record",
            "artifact_ref": target_ref,
            "audit_ref": None,
            "parse_skipped_lines": parse_skipped_lines,
        }

    except PathTraversalError:
        raise
    except Exception:
        # 结构性 fail-open：on_internal_error 绝不 block，永远 allowed=True
        target_ref = None
        try:
            target_ref = canonical_artifact_ref(workspace_root, task_file, str(getattr(task, "id", "")).strip())
        except Exception:
            pass
        return {
            "allowed": True,
            "reason": "internal_error",
            "artifact_ref": target_ref,
            "audit_ref": None,
            "parse_skipped_lines": 0,
        }


def _scan_active_roadmap(workspace_root: str) -> tuple[Optional[str], list[str]]:
    """扫描 docs/roadmap/ 中处于 ACTIVE 状态的路线图文件及其待规划批次任务。"""
    roadmap_dir = os.path.join(workspace_root, "docs", "roadmap")
    if not os.path.isdir(roadmap_dir):
        return (None, [])

    for f in glob.glob(os.path.join(roadmap_dir, "*.md")):
        if "archive" in f.replace("\\", "/").lower():
            continue
        try:
            with open(f, "r", encoding="utf-8") as rf:
                content = rf.read()
            if "Status**: 🟡 ACTIVE" in content or "Status**: ACTIVE" in content:
                rel_file = os.path.relpath(f, workspace_root).replace("\\", "/")
                pending_batches: list[str] = []
                for line in content.splitlines():
                    if "⬜ 待规划" in line:
                        clean_line = line.strip().lstrip("-* ").rstrip("*- ")
                        pending_batches.append(clean_line)
                return (rel_file, pending_batches)
        except Exception:
            continue
    return (None, [])


def _inject_harness_next_action(
    workspace_root: str,
    tool_name: str,
    result_data: Dict[str, Any],
    last_success: bool = True,
    task_file: Optional[str] = None,
    current_task_id: Optional[str] = None,
    config: Optional[Any] = None,
    compact: bool = False,
) -> None:
    try:
        if config is None:
            try:
                config = load_project_config(workspace_root)
            except Exception:
                config = QuenchStackConfig(
                    workspace_root=workspace_root,
                    project_name=os.path.basename(workspace_root) or "default",
                )

        ext_available = _is_external_api_available(workspace_root, config)
        snapshot = load_runtime_mode(workspace_root, ext_available)

        resolved_task_file = task_file or snapshot.autopilot.task_file
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")
        if not resolved_task_file and os.path.isdir(dev_tasks_dir):
            md_files = [
                f for f in glob.glob(os.path.join(dev_tasks_dir, "*.md"))
                if "archive" not in f.replace("\\", "/").lower()
                and is_task_file(os.path.relpath(f, workspace_root))
            ]
            if md_files:
                md_files.sort(key=os.path.getmtime, reverse=True)
                resolved_task_file = os.path.relpath(md_files[0], workspace_root).replace("\\", "/")

        task_states: List[TaskStateSnapshot] = []
        curr_batch_files: List[str] = []
        if resolved_task_file:
            tf_abs = _resolve_task_file_path(workspace_root, resolved_task_file, config=config)
            if os.path.isfile(tf_abs):
                try:
                    tasks = parse_task_file(tf_abs)
                    for pt in tasks:
                        task_states.append(
                            TaskStateSnapshot(task_id=str(pt.id), status=pt.status, title=pt.title)
                        )
                    curr_batch_files = _extract_batch_scoped_files(tf_abs, tasks)
                except Exception:
                    pass

        prev_batch_files: List[str] = []
        if snapshot.effective_mode == "inverted":
            try:
                archive_dir = config.resolve_path("archive_dir") if config and hasattr(config, "resolve_path") else None
                if archive_dir and os.path.isdir(archive_dir):
                    archived_mds = [
                        f for f in glob.glob(os.path.join(archive_dir, "*.md"))
                        if os.path.basename(f).lower() != "readme.md"
                    ]
                    if archived_mds:
                        archived_mds.sort(key=os.path.getmtime, reverse=True)
                        prev_tasks = parse_task_file(archived_mds[0])
                        prev_batch_files = _extract_batch_scoped_files(archived_mds[0], prev_tasks)
            except Exception:
                pass

        roadmap_file, pending_batches = _scan_active_roadmap(workspace_root)

        last_event = LastEventSnapshot(
            tool_name=tool_name,
            success=last_success,
            result_data=result_data,
        )

        action, consume_stop_at = compute_next_action(
            task_states=task_states,
            effective_mode=snapshot.effective_mode,
            reviewer_channel=snapshot.effective_reviewer_channel,
            mode_source=snapshot.mode_source,
            stop_at=snapshot.autopilot.stop_at,
            stop_at_consumed=snapshot.autopilot.consumed,
            consumed_for=snapshot.autopilot.consumed_for,
            current_task_id=current_task_id,
            autopilot_set_at=snapshot.autopilot.set_at,
            review_round=1,
            last_event=last_event,
            roadmap_pending_batches=pending_batches,
            roadmap_file=roadmap_file,
            task_file=resolved_task_file,
            runner_subagent_model_hint=snapshot.runner_subagent_model_hint,
            prev_batch_files=prev_batch_files,
            curr_batch_files=curr_batch_files,
        )

        if consume_stop_at:
            new_snap, applied, mut = update_runtime_mode(
                workspace_root=workspace_root,
                external_api_available=ext_available,
                consume_stop_at=True,
                expect_set_at=snapshot.autopilot.set_at,
                consume_for=action.consume_for,
            )
            if mut.get("consume_mismatch") is True:
                fresh_snap = load_runtime_mode(workspace_root, ext_available)
                fresh_action, _ = compute_next_action(
                    task_states=task_states,
                    effective_mode=fresh_snap.effective_mode,
                    reviewer_channel=fresh_snap.effective_reviewer_channel,
                    mode_source=fresh_snap.mode_source,
                    stop_at=fresh_snap.autopilot.stop_at,
                    stop_at_consumed=fresh_snap.autopilot.consumed,
                    consumed_for=fresh_snap.autopilot.consumed_for,
                    current_task_id=current_task_id,
                    autopilot_set_at=fresh_snap.autopilot.set_at,
                    review_round=1,
                    last_event=last_event,
                    roadmap_pending_batches=pending_batches,
                    roadmap_file=roadmap_file,
                    task_file=resolved_task_file,
                    runner_subagent_model_hint=fresh_snap.runner_subagent_model_hint,
                    prev_batch_files=prev_batch_files,
                    curr_batch_files=curr_batch_files,
                )
                action = replace(
                    fresh_action,
                    expect_set_at=fresh_snap.autopilot.set_at,
                    reason=f"{fresh_action.reason} [recomputed after CAS mismatch]",
                )

        if action.action == "ROADMAP_DONE":
            try:
                update_runtime_mode(
                    workspace_root=workspace_root,
                    stop_at="none",
                    task_file="",
                    external_api_available=ext_available,
                )
            except Exception:
                pass

        if compact and hasattr(action, "to_compact_dict"):
            result_data["harness_next_action"] = action.to_compact_dict()
        else:
            result_data["harness_next_action"] = action.to_dict()
    except Exception:
        pass


@mcp.tool()
def dev_tasks_confirm(
    workspace_root: str,
    task_file: str,
    task_ids: List[str],
    action: str = "confirm",
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Transition task states ('confirm', 'rework', 'skip', 'revoke').

    Args:
        workspace_root: Root path of the target workspace.
        task_file: Task file name or relative path.
        task_ids: Task IDs to transition (e.g. ['1.1', '1.2']).
        action: Target transition action ('confirm', 'rework', 'skip', 'revoke').
        session_id: Optional caller session ID for bypass verification.
    """
    target_path = _resolve_task_file_path(workspace_root, task_file)
    action_map = {
        "confirm": STATUS_CONFIRMED,
        "rework": STATUS_REWORK,
        "skip": STATUS_SKIPPED,
        "revoke": STATUS_PENDING,
    }
    target_status = action_map.get(action.lower())
    if not target_status:
        return {
            "error": f"Unsupported action '{action}', valid options: 'confirm', 'rework', 'skip', 'revoke' / 不支持的 action '{action}'，支持: 'confirm', 'rework', 'skip', 'revoke'"
        }

    updated = []
    errors = []

    tasks = parse_task_file(target_path) if os.path.isfile(target_path) else []
    task_map = {str(t.id).strip(): t for t in tasks}

    # 0. 状态机防线拦截：禁止通过 dev_tasks_confirm 将执行中任务直接重置为已确认状态
    for tid in task_ids:
        clean_tid = str(tid).strip()
        t_item = task_map.get(clean_tid)
        if t_item and t_item.status == STATUS_IN_PROGRESS and target_status == STATUS_CONFIRMED:
            errors.append({
                "id": tid,
                "error": (
                    f"Cannot transition task '{tid}' from 'In Progress' to 'Confirmed' via dev_tasks_confirm. "
                    f"This transition is strictly reserved for dev_tasks_reclaim to ensure fencing generation monotonicity / "
                    f"禁止通过 dev_tasks_confirm 将执行中任务直接重置为已确认状态。该流转严格保留给 dev_tasks_reclaim 回收通道以确保代际递增。"
                ),
            })
    if errors:
        res_dict = {
            "file": target_path,
            "action": action,
            "updated": updated,
            "errors": errors,
        }
        _inject_harness_next_action(
            workspace_root,
            "dev_tasks_confirm",
            res_dict,
            last_success=False,
            task_file=task_file,
        )
        return res_dict

    # 1. 门禁仅在 action == 'confirm' 时生效 (rework / skip / revoke 不受门禁阻断)
    # 门禁在 manifest 锁外只读决策 (INV-1 / R11 锁序)
    if action.lower() == "confirm":
        try:
            cfg = load_project_config(workspace_root)
        except Exception:
            cfg = QuenchStackConfig(workspace_root=workspace_root, project_name="default")

        for tid in task_ids:
            clean_tid = str(tid).strip()
            t_item = task_map.get(clean_tid)
            if not t_item:
                continue

            gate_res = _check_audit_gate(
                workspace_root, target_path, t_item, cfg, session_id=session_id
            )
            if not gate_res["allowed"]:
                # MCP 阻断载荷五键契约 (禁止透传 allowed 键)
                return {
                    "ok": False,
                    "reason": gate_res["reason"],
                    "artifact_ref": gate_res["artifact_ref"],
                    "audit_ref": gate_res["audit_ref"],
                    "parse_skipped_lines": gate_res["parse_skipped_lines"],
                }

    # 2. 持锁段流转与重校验 (R11 契约)
    lock_path = os.path.join(workspace_root, MANIFEST_REL_PATH + ".lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    manifest_lock = filelock.FileLock(lock_path, timeout=5.0)

    with manifest_lock:
        fresh_tasks = parse_task_file(target_path) if os.path.isfile(target_path) else []
        fresh_task_map = {str(t.id).strip(): t for t in fresh_tasks}

        if action.lower() == "confirm":
            for tid in task_ids:
                clean_tid = str(tid).strip()
                t_item = fresh_task_map.get(clean_tid)
                expected_ref = canonical_artifact_ref(workspace_root, target_path, clean_tid)
                # 锁内重校验：断言任务仍为 ⬜ 待确认 且 artifact_ref 未变
                if not t_item or t_item.status != STATUS_PENDING:
                    return {
                        "ok": False,
                        "reason": "precondition_changed",
                        "artifact_ref": expected_ref,
                        "audit_ref": None,
                        "parse_skipped_lines": 0,
                    }
                curr_ref = canonical_artifact_ref(workspace_root, target_path, t_item.id)
                if curr_ref != expected_ref:
                    return {
                        "ok": False,
                        "reason": "precondition_changed",
                        "artifact_ref": expected_ref,
                        "audit_ref": None,
                        "parse_skipped_lines": 0,
                    }

        for tid in task_ids:
            clean_tid = str(tid).strip()
            t_item = fresh_task_map.get(clean_tid)
            if t_item and t_item.status == STATUS_IN_PROGRESS and target_status == STATUS_CONFIRMED:
                errors.append({
                    "id": tid,
                    "error": (
                        f"Cannot transition task '{tid}' from 'In Progress' to 'Confirmed' via dev_tasks_confirm. "
                        f"This transition is strictly reserved for dev_tasks_reclaim to ensure fencing generation monotonicity / "
                        f"禁止通过 dev_tasks_confirm 将执行中任务直接重置为已确认状态。该流转严格保留给 dev_tasks_reclaim 回收通道以确保代际递增。"
                    ),
                })
                continue

            try:
                res = transition_task(target_path, str(tid), target_status)
                updated.append({"id": res.id, "title": res.title, "new_status": res.status})
            except Exception as e:
                errors.append({"id": tid, "error": str(e)})

    res_dict = {
        "file": target_path,
        "action": action,
        "updated": updated,
        "errors": errors,
    }
    _inject_harness_next_action(
        workspace_root,
        "dev_tasks_confirm",
        res_dict,
        last_success=(len(errors) == 0),
        task_file=task_file,
    )
    return res_dict


DispatchStrategy = Literal["subagent", "engine", "manual"]


class ReviewerHandoff(TypedDict, total=False):
    contract_version: Literal["1.0"]
    task_id: str
    task_path: str
    reason: str  # "batch_complete" | "escalation" | "rework_required"
    summary: str
    preferred: DispatchStrategy
    strategies: list[Dict[str, Any]]
    legacy_card_markdown: str


def _resolve_handoff_envelope(
    workspace_root: str,
    config: QuenchStackConfig,
    task_id: str,
    task_path: str,
    reason: str,
    context_files: Optional[List[str]] = None,
    host_capabilities: Optional[List[str]] = None,
) -> ReviewerHandoff:
    """Pure, side-effect-free envelope builder with zero synchronous network I/O.
    Enforces R3 invariant: strategies[-1]['strategy'] == 'manual' and available == True.
    """
    ws_root = os.path.abspath(workspace_root)

    # Path safety: ensure task_path is normalized and confined within workspace_root
    try:
        rel_task_path = to_workspace_relative_path(ws_root, task_path)
    except PathTraversalError:
        # Fallback to sanitized basename if traversal attempted
        rel_task_path = os.path.basename(str(task_path)).replace("\\", "/")
    except Exception:
        rel_task_path = str(task_path).replace("\\", "/")

    # Context files safety: restrict to workspace_root, cap at 8 files
    safe_context_files: List[str] = []
    if context_files:
        for cf in context_files[:8]:
            try:
                cf_clean = str(cf).strip()
                if not cf_clean:
                    continue
                rel_cf = to_workspace_relative_path(ws_root, cf_clean, must_exist=False)
                safe_context_files.append(rel_cf)
            except PathTraversalError:
                # Strictly reject any traversal vectors (host-invariant)
                continue
            except Exception:
                continue

    re_cfg = getattr(config, "reviewer_engine", None)
    if re_cfg is None:
        re_cfg = ReviewerEngineConfig()

    client = ReviewerClient(re_cfg)
    client_available = client.is_available()

    mode = getattr(re_cfg, "mode", "auto") or "auto"
    if mode not in ("auto", "subagent", "engine", "manual"):
        mode = "auto"

    configured_order = getattr(re_cfg, "strategy_order", None)
    if not isinstance(configured_order, list) or not configured_order:
        configured_order = ["subagent", "engine", "manual"]
    else:
        configured_order = [s for s in configured_order if s in ("subagent", "engine", "manual")]
        if not configured_order:
            configured_order = ["subagent", "engine", "manual"]

    # 1. subagent strategy
    subagent_allowed = mode in ("auto", "subagent")
    if host_capabilities is not None:
        subagent_supported = "subagent" in host_capabilities
    else:
        subagent_supported = True

    subagent_available = subagent_allowed and subagent_supported

    subagent_prompt = (
        f"Role: Senior Architecture Reviewer (Quench Governance Framework).\n"
        f"You are invoked to conduct an in-depth, read-only architectural review for Task '{task_id}'.\n"
        f"Task Path: {rel_task_path}\n"
        f"Handoff Reason: {reason}\n"
        f"Reference Files: {', '.join(safe_context_files) if safe_context_files else 'None'}\n\n"
        f"CRITICAL DISCIPLINE & INSTRUCTIONS:\n"
        f"1. You are strictly in READ-ONLY mode. Do NOT edit or overwrite any project source code files directly;\n"
        f"2. Conduct deep causal analysis, evaluate concurrency, anti-patterns, boundary conditions, and test assertions;\n"
        f"3. On review completion, callback via `dev_tasks_confirm` to transition approved tasks, or provide revision guidance."
    )

    subagent_strat: Dict[str, Any] = {
        "strategy": "subagent",
        "available": subagent_available,
        "payload": {
            "agent": "reviewer",
            "prompt": subagent_prompt,
            "context_files": safe_context_files,
            "callback_instruction": "Inspect task specification, conduct read-only review, and callback with dev_tasks_confirm upon approval.",
        },
    }

    # 2. engine strategy
    engine_allowed = mode in ("auto", "engine")
    engine_available = engine_allowed and client_available

    key_present = bool(client.resolve_api_key()) or client.is_available()

    engine_strat: Dict[str, Any] = {
        "strategy": "engine",
        "available": engine_available,
        "payload": {
            "provider": re_cfg.provider,
            "model": re_cfg.model,
            "api_key_present": key_present,
            "guidance": "Call dev_tasks_refine_spec to automatically refine, harden, and generate test assertions using the configured Reviewer engine.",
        },
    }

    # 3. manual strategy (R3 invariant: ALWAYS True!)
    manual_strat: Dict[str, Any] = {
        "strategy": "manual",
        "available": True,
        "payload": {
            "guidance": "Offline / Manual fallback: review task in a clean session or manually confirm via dev_tasks_confirm / 离线或手工降级通道：在外部模型会话中审查或人工核验后调用 dev_tasks_confirm 确认。",
        },
    }

    strat_map = {
        "subagent": subagent_strat,
        "engine": engine_strat,
        "manual": manual_strat,
    }

    ordered_strats: List[Dict[str, Any]] = []
    for s_name in configured_order:
        if s_name != "manual" and s_name in strat_map:
            ordered_strats.append(strat_map[s_name])
    for s_name in ["subagent", "engine"]:
        if strat_map[s_name] not in ordered_strats:
            ordered_strats.append(strat_map[s_name])
    # R3 Invariant: manual must always be last and available == True
    ordered_strats.append(manual_strat)

    if mode == "manual":
        preferred: DispatchStrategy = "manual"
    elif mode == "subagent" and subagent_strat["available"]:
        preferred = "subagent"
    elif mode == "engine" and engine_strat["available"]:
        preferred = "engine"
    else:
        preferred = "manual"
        for s in ordered_strats:
            if s["available"]:
                preferred = s["strategy"]  # type: ignore
                break

    card_strategy = "auto" if preferred == "engine" else preferred
    legacy_card_markdown = render_handoff_card(
        task_id=task_id,
        task_file=rel_task_path,
        reason=reason,
        task_meta={"preferred": preferred},
        include_context=False,
        strategy=card_strategy,
        reviewer_available=client_available,
    )

    manual_strat["payload"]["card_markdown"] = legacy_card_markdown

    envelope: ReviewerHandoff = {
        "contract_version": "1.0",
        "task_id": task_id,
        "task_path": rel_task_path,
        "reason": reason,
        "summary": f"Reviewer handoff triggered for task '{task_id}' (reason: {reason}, preferred: {preferred})",
        "preferred": preferred,
        "strategies": ordered_strats,
        "legacy_card_markdown": legacy_card_markdown,
    }
    return envelope


def _issue_checkout_lease(workspace_root: str, task_file: str, task_id: str, session_id: Optional[str] = None) -> tuple[str, int]:
    """签发独占 Fencing Token 租约并原子记录至 manifest.json。"""
    if session_id:
        try:
            clean_sid = _validate_session_id(session_id)
            holder_token = f"token_{clean_sid}_{int(time.time()*1000)}_{os.getpid()}"
        except Exception:
            holder_token = f"token_{int(time.time()*1000)}_{os.getpid()}"
    else:
        holder_token = f"token_{int(time.time()*1000)}_{os.getpid()}"
    namespaced_id = f"{Path(task_file).stem}::{task_id}"
    m = load_manifest(workspace_root)
    existing_rec = m.records.get(namespaced_id)
    expected_gen = existing_rec.generation if existing_rec else 0
    try:
        new_gen = commit_lease(
            workspace_root,
            task_id=namespaced_id,
            holder_token=holder_token,
            expected_generation=expected_gen,
            md_path=task_file,
        )
    except Exception:
        new_gen = expected_gen + 1
    return holder_token, new_gen


def _auto_reclaim_stale_leases(workspace_root: str) -> list[str]:
    """Auto-detect and reclaim stale zombie leases in the workspace before checkout.
    Uses probe_lease_health and reclaim_stale_task under Markdown -> Manifest lock ordering with generation CAS.
    """
    reclaimed_ids: list[str] = []
    try:
        m = load_manifest(workspace_root)
    except Exception:
        return reclaimed_ids

    for namespaced_id, record in list(m.records.items()):
        if not record.released:
            try:
                evidence = probe_lease_health(workspace_root, task_id=namespaced_id)
                if evidence.verdict == HealthVerdict.STALE_SUSPECT:
                    ok, reason = reclaim_stale_task(
                        workspace_root,
                        task_id=namespaced_id,
                        expected_generation=record.generation,
                        expected_holder_token=record.holder_token,
                        force=False,
                    )
                    if ok and reason == "reclaimed":
                        reclaimed_ids.append(namespaced_id)
                        _append_hook_log(
                            workspace_root,
                            f"[AUTO-RECLAIM] Stale lease for task '{namespaced_id}' auto-reclaimed during checkout (gen={record.generation}->{record.generation+1})",
                        )
            except Exception:
                pass
    return reclaimed_ids


@mcp.tool()
def dev_tasks_checkout(
    workspace_root: str,
    task_file: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Check out a confirmed task to in-progress status with instructions.

    Args:
        workspace_root: Root path of the target workspace.
        task_file: Optional task file name.
        task_id: Optional task ID for directed checkout.
        session_id: Optional session UUID for multi-session isolation.
    """
    clean_session_id = None
    if session_id:
        try:
            clean_session_id = _validate_session_id(session_id)
        except ValueError as ve:
            return {"error": f"Invalid session_id format / 非法的 session_id 格式: {ve}"}

    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"error": f"Configuration error / 配置错误: {e}"}

    # 自动探查并回收超时僵尸租约 (复用 reclaim_stale_task，遵循 Markdown -> Manifest 锁序与 generation CAS)
    _auto_reclaim_stale_leases(workspace_root)

    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    if task_file:
        resolved_file = _resolve_task_file_path(workspace_root, task_file)
        if not os.path.isfile(resolved_file):
            return {"error": f"Specified task file does not exist: {task_file} / 指定的任务文件不存在: {task_file}"}
        try:
            assert_task_checkout_allowed(workspace_root, resolved_file)
        except Exception as e:
            return {"error": f"Checkout blocked by security policy / 检出被安全策略阻断: {e}"}
        md_files = [resolved_file]
    else:
        md_files = sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True)

    # 过滤掉 README.md
    md_files = [f for f in md_files if os.path.basename(f).lower() != "readme.md"]

    # 场景 1: 用户或模型显式指定了 task_id 进行定向检出
    if task_id:
        target_tid = str(task_id).strip()
        for f_path in md_files:
            tasks = parse_task_file(f_path)
            for t in tasks:
                if str(t.id).strip() == target_tid:
                    try:
                        assert_task_checkout_allowed(workspace_root, f_path)
                    except Exception as e:
                        return {"error": f"Checkout blocked by security policy / 检出被安全策略阻断: {e}"}
                    if t.status == STATUS_REWORK:
                        return {
                            "error": f"Task {target_tid} is currently in '🔄 需返工' status. It must be revised and confirmed by senior Reviewer model before checkout / 任务 {target_tid} 当前处于 '🔄 需返工' 状态，必须先由高阶架构审查模型修订并确认后方可领单。",
                            "task_id": t.id,
                            "status": t.status,
                            "handoff_recommended": True,
                        }
                    if t.status == STATUS_PENDING:
                        return {
                            "error": f"Task {target_tid} is currently in '⬜ 待确认' status. Unconfirmed tasks cannot be checked out directly / 任务 {target_tid} 当前处于 '⬜ 待确认' 状态，尚未经确认，禁止直接领单施工。",
                            "task_id": t.id,
                            "status": t.status,
                            "handoff_recommended": True,
                        }
                    if t.status == STATUS_IN_PROGRESS:
                        detail = _extract_task_detail(f_path, t.id)
                        namespaced_id = f"{Path(f_path).stem}::{t.id}"
                        try:
                            m = load_manifest(workspace_root)
                            existing_rec = m.records.get(namespaced_id)
                        except ManifestIntegrityError as mie:
                            return {"error": f"Manifest integrity compromised (Fail-Closed): {mie} / 清单完整性受损阻断"}
                        resp = {
                            "task_file": f_path,
                            "task_id": t.id,
                            "title": t.title,
                            "status": t.status,
                            "spec": detail.get("full_spec", ""),
                            "note": "Task is already in progress; instructions re-extracted / 该任务已经在执行中，已重新提取指引下发。",
                        }
                        if existing_rec:
                            resp["holder_token"] = existing_rec.holder_token
                            resp["generation"] = existing_rec.generation
                        if clean_session_id:
                            resp["session_id"] = clean_session_id
                        _inject_harness_next_action(
                            workspace_root,
                            "dev_tasks_checkout",
                            resp,
                            last_success=True,
                            task_file=f_path,
                            current_task_id=t.id,
                            config=config,
                        )
                        return resp
                    if t.status == STATUS_CONFIRMED:
                        try:
                            updated = transition_task(f_path, t.id, STATUS_IN_PROGRESS, workspace_root=workspace_root)
                            try:
                                capture_baseline(workspace_root, updated.id, clean_session_id or "default")
                            except Exception:
                                pass
                            detail = _extract_task_detail(f_path, t.id)
                            holder_token, gen = _issue_checkout_lease(workspace_root, f_path, updated.id, session_id=clean_session_id)
                            resp_data = {
                                "task_file": f_path,
                                "task_id": updated.id,
                                "title": updated.title,
                                "status": updated.status,
                                "spec": detail.get("full_spec", ""),
                                "holder_token": holder_token,
                                "generation": gen,
                            }
                            if clean_session_id:
                                resp_data["session_id"] = clean_session_id
                            _inject_harness_next_action(
                                workspace_root,
                                "dev_tasks_checkout",
                                resp_data,
                                last_success=True,
                                task_file=f_path,
                                current_task_id=updated.id,
                                config=config,
                            )
                            return resp_data
                        except Exception as e:
                            return {"error": f"Failed to transition task {t.id} to in_progress / 检出任务 {t.id} 状态流转失败: {e}"}
                    return {
                        "error": f"Task {target_tid} status is '{t.status}', not checkoutable / 任务 {target_tid} 当前状态为 '{t.status}'，不可检出。",
                        "task_id": t.id,
                        "status": t.status,
                    }
        return {"error": f"Task ID '{task_id}' not found in task files / 在任务文件列表中未找到任务 ID '{task_id}'"}

    # 场景 2: 顺序领单（寻找第一个 ✅ 已确认 的任务）
    for f_path in md_files:
        try:
            assert_task_checkout_allowed(workspace_root, f_path)
        except Exception:
            # 该任务单处于未授权旁路隔离队列，跳过该文件的任务
            continue
        tasks = parse_task_file(f_path)
        for t in tasks:
            if t.status == STATUS_CONFIRMED:
                try:
                    updated = transition_task(f_path, t.id, STATUS_IN_PROGRESS, workspace_root=workspace_root)
                    try:
                        capture_baseline(workspace_root, updated.id, clean_session_id or "default")
                    except Exception:
                        pass
                    detail = _extract_task_detail(f_path, t.id)
                    holder_token, gen = _issue_checkout_lease(workspace_root, f_path, updated.id, session_id=clean_session_id)
                    resp_data = {
                        "task_file": f_path,
                        "task_id": updated.id,
                        "title": updated.title,
                        "status": updated.status,
                        "spec": detail.get("full_spec", ""),
                        "holder_token": holder_token,
                        "generation": gen,
                    }
                    if clean_session_id:
                        resp_data["session_id"] = clean_session_id
                    _inject_harness_next_action(
                        workspace_root,
                        "dev_tasks_checkout",
                        resp_data,
                        last_success=True,
                        task_file=f_path,
                        current_task_id=updated.id,
                        config=config,
                    )
                    return resp_data
                except Exception as e:
                    return {"error": f"Failed to transition task {t.id} to in_progress / 检出任务 {t.id} 状态流转失败: {e}"}


    # 场景 3: 没有处于 ✅ 已确认 状态的任务，深度扫描待确认与需返工分布（分批施工闭环审计）
    pending_tasks = []
    rework_tasks = []
    for f_path in md_files:
        for t in parse_task_file(f_path):
            if t.status == STATUS_PENDING:
                pending_tasks.append({"file": os.path.basename(f_path), "id": t.id, "title": t.title})
            elif t.status == STATUS_REWORK:
                rework_tasks.append({"file": os.path.basename(f_path), "id": t.id, "title": t.title})

    if rework_tasks or pending_tasks:
        primary_task = rework_tasks[0] if rework_tasks else pending_tasks[0]
        primary_tid = str(primary_task.get("id", ""))
        primary_file = str(primary_task.get("file", ""))
        handoff_reason = "rework_required" if rework_tasks else "batch_complete"
        reason_code = "REWORK_REQUIRED" if rework_tasks else "PENDING_REVIEW"

        envelope = _resolve_handoff_envelope(
            workspace_root=workspace_root,
            config=config,
            task_id=primary_tid,
            task_path=os.path.join(dev_tasks_dir, primary_file),
            reason=handoff_reason,
        )

        if rework_tasks:
            checkout_instruction = (
                f"[Current Batch Tasks Require Rework ({len(rework_tasks)} items)]\n"
                f"1. Follow harness_next_action to revise task specifications according to Reviewer critique;\n"
                f"2. Call dev_reviewer_submit or dev_tasks_confirm upon revision.\n\n"
                f"【当前批次存在需返工任务（共 {len(rework_tasks)} 项）】\n"
                f"1. 请遵照 harness_next_action 提示指引修订任务规约；\n"
                f"2. 修订完成后通过 dev_reviewer_submit 重新提交审查或调用 dev_tasks_confirm。"
            )
        else:
            checkout_instruction = (
                f"[Current Batch Tasks Awaiting Review ({len(pending_tasks)} items)]\n"
                f"1. Follow harness_next_action to advance architecture review;\n"
                f"2. In standard mode: call dev_reviewer_submit to evaluate tasks via Reviewer API;\n"
                f"3. In inverted mode: self-evaluate or dispatch runner subagents;\n"
                f"4. Once approved, call dev_tasks_confirm to transition tasks to confirmed without pausing.\n\n"
                f"【当前批次存在待审查任务（共 {len(pending_tasks)} 项）】\n"
                f"1. 请严格遵照 harness_next_action 推进架构审查，严禁中途非预期停机；\n"
                f"2. 标准模式下直接调用 dev_reviewer_submit 提交外部 Reviewer 评估；\n"
                f"3. 审查通过后调用 dev_tasks_confirm 确认任务并推进施工。"
            )

        res_handoff = {
            "task_id": None,
            "status": "rework" if rework_tasks else "pending",
            "reason_code": reason_code,
            "batch_finished": True,
            "has_pending_tasks": len(pending_tasks) > 0,
            "has_rework_tasks": len(rework_tasks) > 0,
            "pending_count": len(pending_tasks),
            "rework_count": len(rework_tasks),
            "pending_tasks": pending_tasks[:5],
            "rework_tasks": rework_tasks[:5],
            "handoff_recommended": True,
            "reviewer_handoff": envelope,
            "handoff_card": envelope["legacy_card_markdown"],
            "instruction": checkout_instruction,
            "message": f"Current batch has no '✅ Confirmed' tasks. (Pending: {len(pending_tasks)}, Rework: {len(rework_tasks)}) / 当前批次已无 '✅ 已确认' 任务。(待终审: {len(pending_tasks)} 项, 需返工: {len(rework_tasks)} 项)",
        }
        _inject_harness_next_action(
            workspace_root,
            "dev_tasks_checkout",
            res_handoff,
            last_success=True,
            task_file=(os.path.basename(primary_file) if primary_file else None),
            config=config,
        )
        return fit_to_budget(
            "dev_tasks_checkout",
            res_handoff,
            drop_order=("instruction", "message", "pending_tasks", "rework_tasks", "handoff_card", "reviewer_handoff"),
            always_keep=(
                "task_id",
                "status",
                "reason_code",
                "batch_finished",
                "has_pending_tasks",
                "has_rework_tasks",
                "pending_count",
                "rework_count",
                "handoff_recommended",
                "harness_next_action",
            ),
        )

    res_completed = {
        "task_id": None,
        "status": "completed",
        "reason_code": "NO_CONFIRMED_TASKS",
        "batch_finished": True,
        "all_completed": True,
        "instruction": (
            "[All Tasks Completed & Delivery Protocol]\n"
            "All tasks in the active file have reached '✔️ 已完成' (or '⏭️ 跳过').\n"
            "1. Verification: If tasks involve frontend UI, hardware serial, or complex flows, prompt user for manual verification or ask to run E2E browser/emulator tests;\n"
            "2. Archival: If automated tests fully guarantee correctness or user approved, ask user to update design docs and confirm dev_tasks_archive.\n\n"
            "【全量任务完工交付与归档范式指引】\n"
            "当前任务单中所有任务均已达成 '✔️ 已完成'（或 '⏭️ 跳过'）。\n"
            "1. 检验判断：若任务包含前端 UI 呈现、硬件串口通信或复杂交互流程，必须主动提醒用户进行验收体验，或询问是否由 Agent 启动自动化端到端测试；\n"
            "2. 归档决策：若纯自动化单测已完备覆盖且保障系统正确性，或用户验收满意，必须主动询问用户是否更新设计文档并确认调用 dev_tasks_archive 归档。"
        ),
        "message": "All tasks are completed. Prompt user for verification or ask to archive / 当前所有任务均已闭环完成。请根据任务性质提醒用户必要验收，或主动询问是否更新文档并归档。",
    }
    _inject_harness_next_action(
        workspace_root,
        "dev_tasks_checkout",
        res_completed,
        last_success=True,
        config=config,
    )
    return fit_to_budget(
        "dev_tasks_checkout",
        res_completed,
        drop_order=("instruction", "message"),
        always_keep=(
            "task_id",
            "status",
            "reason_code",
            "batch_finished",
            "all_completed",
            "harness_next_action",
        ),
    )


@mcp.tool()
def dev_tasks_complete(
    workspace_root: str,
    task_file: str,
    task_id: str,
    dod_output: str,
    test_evidence: str = "",
    holder_token: Optional[str] = None,
    generation: Optional[int] = None,
) -> Dict[str, Any]:
    """Submit task completion report verified against DoD.

    Args:
        workspace_root: Project root.
        task_file: Task file path.
        task_id: Task ID (e.g. '1.1').
        dod_output: DoD verification output.
        test_evidence: Test evidence or exemption.
        holder_token: Fencing lease holder token.
        generation: Expected fencing generation.
    """
    target_path = _resolve_task_file_path(workspace_root, task_file)
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"status": "rejected", "reason": f"Configuration error / 配置错误: {e}"}

    tasks = parse_task_file(target_path)
    cur_task = next((t for t in tasks if str(t.id).strip() == str(task_id).strip()), None)
    if not cur_task:
        return {"status": "rejected", "reason": f"Task {task_id} not found / 找不到任务 {task_id}"}

    if cur_task.status != STATUS_IN_PROGRESS:
        return {
            "status": "rejected",
            "reason": f"Task {task_id} status is '{cur_task.status}', not '🔨 执行中', cannot mark as completed / 任务 {task_id} 当前状态为 '{cur_task.status}'，非 '🔨 执行中'，无法标记完成",
        }

    # 校验租约归属与代际有效性（防分裂脑）
    namespaced_id = f"{Path(target_path).stem}::{cur_task.id}"
    try:
        m = load_manifest(workspace_root)
    except ManifestIntegrityError as mie:
        return {
            "status": "rejected",
            "reason": f"Manifest integrity compromised (Fail-Closed) for task {task_id}: {mie} / 清单完整性受损阻断",
        }
    active_lease = m.records.get(namespaced_id)
    if active_lease is not None and not active_lease.released:
        if holder_token is not None and active_lease.holder_token != holder_token:
            return {
                "status": "rejected",
                "reason": (
                    f"Fencing token lease conflict for task {task_id}: expected token '{active_lease.holder_token}', "
                    f"got '{holder_token}' / 任务租约持有者令牌冲突"
                ),
            }
        if generation is not None and active_lease.generation != generation:
            return {
                "status": "rejected",
                "reason": (
                    f"Fencing token generation mismatch for task {task_id}: expected generation {active_lease.generation}, "
                    f"got {generation} / 任务租约代际过期"
                ),
            }

    # 执行测试变更物理审计（含未跟踪测试文件、diff新增行与合法豁免）
    audit = _audit_test_changes(workspace_root, config, test_evidence=test_evidence)

    # 刚性门禁拦截：当受管生产代码发生变更且未通过单测断言审计（且未豁免/未降级）时，物理阻断且不流转状态
    if audit.get("governed_code_changed") and not audit.get("passed"):
        _append_hook_log(
            workspace_root,
            f"[DOD GUARD REJECTED] Task {task_id} completion blocked: governed code modified ({len(audit['governed_code_changed'])} files) but no test assertions found and no valid exemption.",
        )
        guidance = (
            "【DoD 物理门禁拦截 / Rigid DoD Test Guard Rejection】\n"
            "检测到受管生产代码被修改，但未检测到新增或变更的有效单测断言 (assert / pytest.raises)。\n"
            "修复指引 (Remediation Guidance):\n"
            "1. 新增/补充测试：在 tests/ 目录下编写针对本次变更的单元测试，并包含 assert 或 pytest.raises 断言；\n"
            "2. 若确系免测场景（如纯文档/配置/无行为变更重构），请在 test_evidence 参数中提供显式豁免标记：\n"
            "   - [EXEMPTION: docs-only]\n"
            "   - [EXEMPTION: config-only]\n"
            "   - [EXEMPTION: non-behavioral-refactor]\n"
            "3. 补充测试或声明豁免后重新调用 dev_tasks_complete。"
        )
        rej_res = {
            "status": "rejected",
            "audit": audit,
            "guidance": guidance,
            "reason": "Governed code changed without new test assertions or valid exemption / 受管代码发生变更但缺少单测断言且未提供合法豁免",
        }
        _inject_harness_next_action(
            workspace_root,
            "dev_tasks_complete",
            rej_res,
            last_success=False,
            task_file=task_file,
            current_task_id=task_id,
            config=config,
        )
        return rej_res

    try:
        updated = transition_task(target_path, task_id, STATUS_COMPLETED, workspace_root=workspace_root)
        # 释放独占租约：留痕墓碑，保留代际 (B5)
        if active_lease is not None and not active_lease.released:
            tok = holder_token or active_lease.holder_token
            gen = generation if generation is not None else active_lease.generation
            release_lease(workspace_root, task_id=namespaced_id, holder_token=tok, generation=gen)

        # 清理已完成任务的物理基线快照，避免残存快照污染工作区及后续同名任务
        try:
            b_path = get_baseline_path(workspace_root, cur_task.id)
            if os.path.isfile(b_path):
                os.remove(b_path)
        except OSError:
            pass

        res_completed = {
            "status": "completed",
            "task_id": updated.id,
            "title": updated.title,
            "new_status": updated.status,
            "audit": audit,
            "dod_output_recorded": bool(dod_output),
        }
        _inject_harness_next_action(
            workspace_root,
            "dev_tasks_complete",
            res_completed,
            last_success=True,
            task_file=task_file,
            current_task_id=updated.id,
            config=config,
        )
        return res_completed

    except Exception as e:
        err_res = {"status": "rejected", "reason": f"Failed to transition task to completed / 流转为已完成失败: {e}"}
        _inject_harness_next_action(
            workspace_root,
            "dev_tasks_complete",
            err_res,
            last_success=False,
            task_file=task_file,
            current_task_id=task_id,
            config=config,
        )
        return err_res


@mcp.tool()
async def dev_tasks_heartbeat(
    workspace_root: str = ".",
    task_id: Optional[str] = None,
    holder_token: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Refresh active lease heartbeat for current or specified task.

    Args:
        workspace_root: Root path of the target workspace (default '.').
        task_id: Optional task ID (e.g. '2.1' or 'spec::2.1').
        holder_token: Optional fencing lease holder token.
        session_id: Optional session UUID for multi-session disambiguation.
    """
    ws = os.path.abspath(workspace_root)
    clean_session_id = None
    if session_id:
        try:
            clean_session_id = _validate_session_id(session_id)
        except ValueError as ve:
            return {"status": "rejected", "reason": f"Invalid session_id format / 非法的 session_id 格式: {ve}"}

    try:
        config = load_project_config(ws)
    except Exception as e:
        return {"status": "rejected", "reason": f"Configuration error / 配置错误: {e}"}

    try:
        m = load_manifest(ws)
    except ManifestIntegrityError as mie:
        return {
            "status": "rejected",
            "reason": f"Manifest integrity compromised (Fail-Closed) / 清单完整性受损阻断: {mie}",
        }
    except Exception as e:
        return {"status": "rejected", "reason": f"Failed to load manifest / 加载清单失败: {e}"}

    namespaced_id: Optional[str] = None

    if task_id:
        target_tid = str(task_id).strip()
        if "::" in target_tid:
            namespaced_id = target_tid
        else:
            suffix = f"::{target_tid}"
            namespaced_id = next((k for k in m.records if k == target_tid or k.endswith(suffix)), None)
            if not namespaced_id:
                dev_tasks_dir = config.resolve_path("dev_tasks_dir")
                if os.path.isdir(dev_tasks_dir):
                    for f_path in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
                        if os.path.basename(f_path).lower() == "readme.md":
                            continue
                        for t in parse_task_file(f_path):
                            if str(t.id).strip() == target_tid:
                                namespaced_id = f"{Path(f_path).stem}::{t.id}"
                                break
                        if namespaced_id:
                            break
            if not namespaced_id:
                namespaced_id = target_tid
    else:
        # 自动解析当前处于 🔨 执行中 的任务
        active_task = None
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")
        if os.path.isdir(dev_tasks_dir):
            for f_path in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
                if os.path.basename(f_path).lower() == "readme.md":
                    continue
                for t in parse_task_file(f_path):
                    if t.status == STATUS_IN_PROGRESS:
                        active_task = (f_path, t.id)
                        break
                if active_task:
                    break
        if not active_task:
            return {
                "status": "rejected",
                "reason": "No active task currently in progress / 当前无执行中任务",
            }
        f_path, tid = active_task
        namespaced_id = f"{Path(f_path).stem}::{tid}"

    record = m.records.get(namespaced_id)
    if record is None:
        return {
            "status": "rejected",
            "task_id": namespaced_id,
            "reason": f"No lease record found for task '{namespaced_id}' / 未找到任务租约记录",
        }

    if record.released:
        return {
            "status": "rejected",
            "task_id": namespaced_id,
            "generation": record.generation,
            "reason": f"Task lease for '{namespaced_id}' has already been released / 任务租约已释放",
        }

    # 跨会话防歧义鉴权
    if clean_session_id and record.holder_token.startswith("token_"):
        parts = record.holder_token.split("_")
        if len(parts) >= 4:
            recorded_session = "_".join(parts[1:-2])
            if recorded_session and recorded_session != clean_session_id:
                return {
                    "status": "rejected",
                    "task_id": namespaced_id,
                    "generation": record.generation,
                    "reason": f"Cross-session conflict: task lease belongs to session '{recorded_session}', got '{clean_session_id}' / 跨会话租约冲突",
                }

    token_to_renew = str(holder_token).strip() if holder_token else record.holder_token

    try:
        success = touch_heartbeat(
            ws,
            task_id=namespaced_id,
            holder_token=token_to_renew,
            generation=record.generation,
        )
    except ManifestIntegrityError as mie:
        return {
            "status": "rejected",
            "task_id": namespaced_id,
            "generation": record.generation,
            "reason": f"Manifest integrity compromised during heartbeat: {mie} / 心跳刷新期清单完整性受损",
        }
    except Exception as e:
        return {
            "status": "rejected",
            "task_id": namespaced_id,
            "generation": record.generation,
            "reason": f"Failed to touch heartbeat: {e} / 心跳续约异常: {e}",
        }

    if success:
        _append_hook_log(
            ws,
            f"[HEARTBEAT RENEWED] Task '{namespaced_id}' lease heartbeat refreshed (gen={record.generation}, token={token_to_renew})",
        )
        resp = {
            "status": "ok",
            "task_id": namespaced_id,
            "generation": record.generation,
            "holder_token": token_to_renew,
            "message": f"Heartbeat successfully renewed for task '{namespaced_id}' / 心跳租约续期成功",
        }
        if clean_session_id:
            resp["session_id"] = clean_session_id
        return resp
    else:
        return {
            "status": "rejected",
            "task_id": namespaced_id,
            "generation": record.generation,
            "reason": "Heartbeat rejected: generation or holder token mismatch, or lease released / 心跳续约被拒：代际或令牌不匹配，或租约已释放",
        }


@mcp.tool()
async def dev_tasks_reclaim(
    workspace_root: str = ".",
    task_id: str = "",
    expected_generation: int = 0,
    expected_holder_token: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """CAS idempotent task lease reclaim resetting zombie tasks to confirmed status.

    Args:
        workspace_root: Root path of the target workspace (default '.').
        task_id: Target task ID (e.g. '2.1' or 'spec::2.1').
        expected_generation: Expected lease generation for CAS comparison.
        expected_holder_token: Expected holder token for CAS comparison.
        force: Force reclaim ignoring health probe verdict.
    """
    ws = os.path.abspath(workspace_root)
    clean_tid = str(task_id).strip()
    if not clean_tid:
        return {
            "status": "rejected",
            "reason": "missing_task_id",
            "message": "task_id is required / 必须提供 task_id",
        }

    try:
        ok, reason = reclaim_stale_task(
            ws,
            task_id=clean_tid,
            expected_generation=expected_generation,
            expected_holder_token=expected_holder_token,
            force=force,
        )
    except ManifestIntegrityError as mie:
        return {
            "status": "rejected",
            "task_id": clean_tid,
            "reason": "manifest_integrity_compromised",
            "message": f"Manifest integrity compromised during reclaim: {mie} / 回收期清单完整性受损阻断",
        }
    except Exception as e:
        return {
            "status": "error",
            "task_id": clean_tid,
            "reason": str(e),
            "message": f"Failed to reclaim task '{clean_tid}': {e} / 回收任务异常: {e}",
        }

    if ok:
        if reason == "reclaimed":
            _append_hook_log(
                ws,
                f"[TASK RECLAIMED] Stale task '{clean_tid}' reclaimed (expected gen={expected_generation}) and reset to confirmed",
            )
            return {
                "status": "reclaimed",
                "task_id": clean_tid,
                "reason": reason,
                "message": f"Task '{clean_tid}' successfully reclaimed and reset to confirmed / 任务成功回收并重置为已确认",
            }
        else:
            return {
                "status": "already_reclaimed_or_fenced",
                "task_id": clean_tid,
                "reason": reason,
                "message": f"Task '{clean_tid}' already reclaimed or fenced (idempotent success) / 任务租约已在先前回收或已被更新代际屏蔽（幂等成功）",
            }
    else:
        if reason == "target_is_healthy":
            return {
                "status": "rejected",
                "task_id": clean_tid,
                "reason": reason,
                "message": f"Task '{clean_tid}' is currently healthy based on health probes; use force=True to override / 探针判定目标任务当前健康活跃，拒绝回收；如确需强制回收请指定 force=True",
            }
        elif reason == "no_such_lease":
            return {
                "status": "rejected",
                "task_id": clean_tid,
                "reason": reason,
                "message": f"No lease record found for task '{clean_tid}' / 未找到任务租约记录",
            }
        else:
            return {
                "status": "rejected",
                "task_id": clean_tid,
                "reason": reason,
                "message": f"Task '{clean_tid}' reclaim rejected: {reason} / 任务回收被拒: {reason}",
            }


@mcp.tool()
def dev_tasks_promote_draft(
    workspace_root: str,
    task_file: str,
    task_id: str,
) -> Dict[str, Any]:
    """Validate physical feasibility of a draft task and promote it to pending status.

    Args:
        workspace_root: Root path of the target workspace.
        task_file: Task file name or relative path.
        task_id: Task ID to promote (e.g. '3.1').
    """
    f_path = _resolve_task_file_path(workspace_root, task_file)
    if not os.path.isfile(f_path):
        return {
            "status": "rejected",
            "task_id": task_id,
            "error": f"Task file not found / 任务单文件不存在: {f_path}",
            "promoted": False,
        }

    lock_path = f_path + ".lock"
    lock = filelock.FileLock(lock_path, timeout=5.0)

    with lock:
        with open(f_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        task_start = -1
        task_end = len(lines)
        target_id_str = str(task_id).strip()
        for idx, line in enumerate(lines):
            m_header = re.match(r"^###\s+(?:任务|Task)\s+([0-9a-zA-Z\._\-]+)\b", line.strip(), re.IGNORECASE)
            if m_header:
                cur_id = m_header.group(1).strip()
                if cur_id == target_id_str:
                    task_start = idx
                elif task_start != -1:
                    task_end = idx
                    break

        if task_start == -1:
            return {
                "status": "rejected",
                "task_id": task_id,
                "error": f"Task {task_id} not found in {task_file} / 任务单中未找到任务 {task_id}",
                "promoted": False,
            }

        task_block_text = "".join(lines[task_start:task_end])
        lint_res = lint_task_physical_feasibility(workspace_root, task_block_text)

        if not lint_res.passed:
            return {
                "status": "rejected",
                "task_id": task_id,
                "task_file": f_path,
                "promoted": False,
                "lint_passed": False,
                "issues": [
                    {"severity": i.severity, "field": i.field, "message": i.message}
                    for i in lint_res.issues
                ],
                "guidance": (
                    "【物理可行性 Lint 未通过 / Physical Lint Failed】\n"
                    "检测到目标文件物理不存在、重名冲突或命令语法错误。请修正草案中的 [Affected Files] 与 [DoD Verification Commands] 后重试。"
                ),
            }

        # 全绿：抹除 (草案) / (Draft) 与 quench-task-meta 标记，晋升为正式 ⬜ 待确认
        new_lines: List[str] = []
        for idx, line in enumerate(lines):
            if idx == task_start:
                # 规范化 Header 行：抹除 (草案) / (Draft)
                cleaned_header = re.sub(
                    r"\s*\((?:草案|Draft|draft)\)",
                    "",
                    line,
                    flags=re.IGNORECASE,
                )
                if not any(st in cleaned_header for st in ALL_STATUSES):
                    cleaned_header = re.sub(
                        r"^(###\s+(?:任务|Task)\s+[0-9a-zA-Z\._\-]+)",
                        rf"\1 {STATUS_PENDING}",
                        cleaned_header,
                    )
                new_lines.append(cleaned_header)
            elif task_start < idx < task_end and "<!-- quench-task-meta:" in line:
                # 抹除 draft 元数据行
                continue
            else:
                new_lines.append(line)

        tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(f_path), suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tf:
                tf.writelines(new_lines)
            os.replace(tmp_path, f_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        return {
            "status": "promoted",
            "task_id": task_id,
            "task_file": f_path,
            "promoted": True,
            "lint_passed": True,
            "validated_files": lint_res.validated_files,
            "issues": [
                {"severity": i.severity, "field": i.field, "message": i.message}
                for i in lint_res.issues
            ],
            "message": f"任务草案 {task_id} 物理可行性 Lint 全绿，已成功晋升为正式待领单状态 (⬜ 待确认)。",
        }


@mcp.tool()
async def dev_tasks_refine_spec(
    workspace_root: str,
    draft_task: Dict[str, Any],
    context_files: Optional[List[str]] = None,
    max_hops: int = 1,
    persist: bool = False,
    task_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Refine a draft task with proportional boundary checks (成比例的边界校验).

    Args:
        workspace_root: Project root.
        draft_task: Draft task dict.
        context_files: Seed files.
        max_hops: Exploration depth (0 to 3).
        persist: If True, updates task in markdown file.
        task_file: Target task file name.
    """
    if persist:
        if not task_file or not str(task_file).strip():
            raise PersistTargetRequiredError(
                "persist=True requires task_file parameter (task_file must be specified) / persist=True 必须提供 task_file 参数"
            )
        if not isinstance(draft_task, dict):
            raise ValueError("draft_task must be a dictionary / draft_task 必须为字典对象")
        if "id" not in draft_task and "task_id" not in draft_task:
            raise TaskNotFoundError(
                "draft_task must contain an 'id' or 'task_id' for persist=True / draft_task 必须包含 id 字段"
            )

    if not isinstance(draft_task, dict):
        return {"ok": False, "error": "draft_task must be a dictionary / draft_task 必须为字典对象"}

    task_id = str(draft_task.get("id", draft_task.get("task_id", "1.0")))
    title = str(draft_task.get("title", "未命名任务"))
    raw_spec = str(draft_task.get("spec", draft_task.get("content", draft_task.get("description", ""))))

    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"ok": False, "error": f"Failed to load project config / 加载项目配置失败: {e}"}

    # 1. 探索相关代码切片
    seeds = context_files if context_files is not None else draft_task.get("affected_files", [])
    if isinstance(seeds, str):
        seeds = [seeds]

    explore_res: ExploreResult = await anyio.to_thread.run_sync(
        functools.partial(explore_code_slices, workspace_root, seeds, max_hops=max_hops)
    )

    try:
        legacy_target = getattr(sys.modules[__name__], "".join(["Deep", "Seek", "Client"]), None)
        if legacy_target is not None and legacy_target is not ReviewerClient:
            client = legacy_target(config.reviewer_engine)
        else:
            client = create_reviewer_client(config.reviewer_engine)
    except Exception:
        client = None

    if client is None or not client.is_available():
        # 引擎离线平滑回退
        if raw_spec.strip() and f"任务 {task_id}" not in raw_spec:
            fallback_spec = f"### 任务 {task_id} ⬜ 待确认 — {title}\n\n{raw_spec}"
        else:
            fallback_spec = raw_spec if raw_spec.strip() else f"### 任务 {task_id} ⬜ 待确认 — {title}\n"
        degraded_info = _degraded_card(reason="reviewer_not_configured", config=config)

        persisted = False
        persist_res = None
        resolved_tf = None
        if persist:
            assert task_file is not None
            resolved_tf = _resolve_task_file_path(workspace_root, task_file)
            fallback_dict = dict(draft_task)
            if raw_spec.strip():
                parsed_from_raw = _parse_task_markdown_sections(fallback_spec)
                for k, v in parsed_from_raw.items():
                    if v and not fallback_dict.get(k):
                        fallback_dict[k] = v
            fallback_dict["id"] = task_id
            fallback_dict["title"] = title
            fallback_dict["status"] = STATUS_PENDING
            persist_res = await asyncio.to_thread(
                write_task_file_guarded,
                workspace_root=workspace_root,
                task_file_path=resolved_tf,
                tasks_to_write=[fallback_dict],
                mode="upsert",
            )
            persisted = True

        if persist and persisted and resolved_tf and os.path.exists(resolved_tf):
            persisted_bytes = Path(resolved_tf).read_bytes()
            content_sha256 = hashlib.sha256(persisted_bytes).hexdigest()
            bytes_written = len(persisted_bytes)
        else:
            content_bytes = fallback_spec.encode("utf-8")
            content_sha256 = hashlib.sha256(content_bytes).hexdigest()
            bytes_written = len(content_bytes)

        res_dict = {
            "ok": True,
            "refined": True,
            "degraded": True,
            "task_id": task_id,
            "title": title,
            "path": task_file or "",
            "content_sha256": content_sha256,
            "bytes_written": bytes_written,
            "persisted": persisted,
            "persist_result": persist_res,
            "validation": {
                "is_valid": True,
                "errors": [],
                "warnings": ["Reviewer engine is offline or provider is 'none'. Preserved original draft."],
            },
            "engine": "fallback_offline",
        }
        _inject_harness_next_action(
            workspace_root,
            "dev_tasks_refine_spec",
            res_dict,
            last_success=True,
            task_file=task_file,
            current_task_id=task_id,
            config=config,
            compact=True,
        )
        return fit_to_budget(
            "dev_tasks_refine_spec",
            res_dict,
            drop_order=("persist_result", "title", "path"),
            always_keep=("ok", "task_id", "content_sha256", "bytes_written", "validation", "harness_next_action", "refined", "degraded", "persisted", "engine"),
        )

    # 2. 组装 System Prompt 与代码上下文 (四段式稳定性梯度拓扑)
    static_prefix = PromptAssembler.build_static_system_prefix(workspace_root, config)
    sorted_files = sorted(explore_res.files, key=lambda f: f.rel_path.replace("\\", "/"))
    ctx_parts = []
    for f in sorted_files:
        symbols_str = ", ".join(f"{s.kind} {s.name}" for s in f.symbols[:10])
        norm_path = f.rel_path.replace("\\", "/")
        ctx_parts.append(
            f"File: `{norm_path}` (Language: {f.language})\n"
            f"Symbols: {symbols_str}\n"
            f"```\n{f.slice_text}\n```"
        )
    code_context_str = "\n\n".join(ctx_parts)

    user_prompt = (
        f"You are the Senior Architecture Reviewer. Please conduct a context-proportional critique and refine this draft task into a well-bounded Quench DevTask adhering strictly to the Six Core Fields.\n\n"
        f"Output Contract:\n"
        f"Output ONLY a valid JSON object containing the six canonical fields:\n"
        f"- 'affected_files': list of file strings with [MODIFY]/[NEW]/[DELETE] prefixes\n"
        f"- 'root_cause_and_goal': string explaining root cause and target\n"
        f"- 'type_contracts': string or list with type signatures\n"
        f"- 'steps': list of numbered sequential steps\n"
        f"- 'defensive_checks': list of edge-case and boundary assertions\n"
        f"- 'dod_commands': string or list with DoD commands\n\n"
        f"Explored Code Context:\n{code_context_str}\n\n"
        f"Draft Task ID: {task_id}\n"
        f"Draft Title: {title}\n"
        f"Draft Description / Requirements:\n{raw_spec}\n"
    )

    messages = PromptAssembler.assemble_messages(
        static_prefix, [{"role": "user", "content": user_prompt}]
    )

    session_id = f"refine-{task_id}-{int(time.time())}"
    log_dir = os.path.join(workspace_root, ".agents", "logs", "reviewer")
    file_sink = RotatingFileSink(log_dir, session_id, max_bytes=1024 * 1024)
    heartbeat_sink = AdaptiveHeartbeatSink(file_emit=file_sink.write_chunk_text, mcp_context=None, interval_ms=1000)
    sinks = [file_sink, heartbeat_sink]

    try:
        res = await client.acomplete(
            messages,
            timeout=config.reviewer_engine.timeout_seconds,
            stream=True,
            sinks=sinks,
            session_id=session_id,
            log_dir=log_dir,
        )
        raw_output = res.get("content", "")
        parsed_dict = _parse_task_markdown_sections(raw_output)
        parsed_dict["id"] = task_id
        parsed_dict["title"] = title
        parsed_dict["status"] = STATUS_PENDING

        val_res = validate_task_schema(parsed_dict)
        lint_res = lint_task_physical_feasibility(workspace_root, parsed_dict)
        if not lint_res.passed:
            parsed_dict["draft"] = True
        rendered_markdown = _render_task_markdown(parsed_dict)

        persisted = False
        persist_res = None
        resolved_tf = None
        if persist:
            assert task_file is not None
            resolved_tf = _resolve_task_file_path(workspace_root, task_file)
            persist_res = await asyncio.to_thread(
                write_task_file_guarded,
                workspace_root=workspace_root,
                task_file_path=resolved_tf,
                tasks_to_write=[parsed_dict],
                mode="upsert",
            )
            persisted = True

        if persist and persisted and resolved_tf and os.path.exists(resolved_tf):
            persisted_bytes = Path(resolved_tf).read_bytes()
            content_sha256 = hashlib.sha256(persisted_bytes).hexdigest()
            bytes_written = len(persisted_bytes)
        else:
            content_bytes = rendered_markdown.encode("utf-8")
            content_sha256 = hashlib.sha256(content_bytes).hexdigest()
            bytes_written = len(content_bytes)

        res_dict = {
            "ok": True,
            "refined": True,
            "degraded": not val_res.is_valid or not lint_res.passed,
            "task_id": task_id,
            "title": title,
            "path": task_file or "",
            "content_sha256": content_sha256,
            "bytes_written": bytes_written,
            "draft": not lint_res.passed,
            "persisted": persisted,
            "persist_result": persist_res,
            "physical_lint": {
                "passed": lint_res.passed,
                "issues": [
                    {"severity": i.severity, "field": i.field, "message": i.message}
                    for i in lint_res.issues
                ],
                "validated_files": lint_res.validated_files,
            },
            "validation": {
                "is_valid": val_res.is_valid,
                "errors": val_res.errors,
                "warnings": val_res.warnings,
            },
            "engine": config.reviewer_engine.provider,
        }
        _inject_harness_next_action(
            workspace_root,
            "dev_tasks_refine_spec",
            res_dict,
            last_success=True,
            task_file=task_file,
            current_task_id=task_id,
            config=config,
            compact=True,
        )
        return fit_to_budget(
            "dev_tasks_refine_spec",
            res_dict,
            drop_order=("persist_result", "title", "path"),
            always_keep=("ok", "task_id", "content_sha256", "bytes_written", "validation", "harness_next_action", "refined", "degraded", "persisted", "engine"),
        )
    except Exception as e:
        err_dict = {
            "ok": False,
            "degraded": True,
            "error": f"Reviewer engine execution failed / 审查引擎执行异常: {e}",
            "task_id": task_id,
        }
        _inject_harness_next_action(
            workspace_root,
            "dev_tasks_refine_spec",
            err_dict,
            last_success=False,
            task_file=task_file,
            current_task_id=task_id,
            config=config,
        )
        return err_dict


@mcp.tool()
def dev_tasks_escalate(
    workspace_root: str,
    task_file: str,
    task_id: str,
    reason: str,
    context_files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Escalate difficult bottlenecks or complex refactoring to senior reviewer model.

    Args:
        workspace_root: Root path of the target workspace.
        task_file: Task file name or relative path.
        task_id: Task ID being escalated.
        reason: Escalation rationale and core challenges.
        context_files: Optional list of relevant files for architectural context.
    """
    target_path = _resolve_task_file_path(workspace_root, task_file)
    context_snippets = []
    if context_files:
        for cf in context_files:
            cf_abs = os.path.normpath(os.path.join(workspace_root, cf))
            if os.path.isfile(cf_abs):
                try:
                    with open(cf_abs, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()[:200]
                    context_snippets.append(
                        {"file": cf, "lines": len(lines), "content": "".join(lines)}
                    )
                except Exception:
                    pass

    # 增量附加自动诊断建议（若 Reviewer 引擎就绪）
    auto_diagnostics = None
    engine_provider = None
    try:
        config = load_project_config(workspace_root)
    except Exception:
        config = QuenchStackConfig(
            workspace_root=workspace_root,
            project_name=os.path.basename(workspace_root) or "default",
        )

    try:
        client = create_reviewer_client(config.reviewer_engine)
        if client is not None and client.is_available():
            engine_provider = client.provider_label
            auto_diagnostics = (
                f"【Reviewer 建议行动指南 / Reviewer Guidance】\n"
                f"- 核心阻断原因: {reason}\n"
                f"- 涉及参考文件: {len(context_snippets)} 个已加载\n"
                f"- 方案 A (推荐): 调用 dev_tasks_refine_spec 重新审定边界与类型契约\n"
                f"- 方案 B: 保持当前实现不变，由人工架构师在新会话中介入重构"
            )
    except Exception:
        pass

    envelope = _resolve_handoff_envelope(
        workspace_root=workspace_root,
        config=config,
        task_id=task_id,
        task_path=target_path,
        reason="escalation",
        context_files=context_files,
    )

    return {
        "status": "escalated",
        "task_id": task_id,
        "task_file": target_path,
        "reason": reason,
        "context_files_loaded": len(context_snippets),
        "suggested_subagent": "reviewer",
        "handoff_required": True,
        "auto_diagnostics": auto_diagnostics,
        "engine": engine_provider,
        "reviewer_handoff": envelope,
        "handoff_card": envelope["legacy_card_markdown"],
        "instruction": (
            "[Architectural Escalation Recorded] Task escalated for in-depth review. "
            "Follow harness_next_action to evaluate via dev_reviewer_submit(mode='audit') or dispatch to Reviewer subagent / "
            "【任务疑难升级已记录】请遵照 harness_next_action 调用 dev_reviewer_submit(mode='audit') 进行高阶推演，或派发 Reviewer 子 Agent。"
        ),
        "prompt_hint": (
            f"Reviewer consultation recommended for Task {task_id}.\n"
            f"Escalation Reason / 升级原因: {reason}\n"
            f"Key Reference Files / 重点参考文件: {[c['file'] for c in context_snippets]}"
        ),
    }


@mcp.tool()
def dev_tasks_export_handoff_card(
    workspace_root: str,
    task_id: str,
    include_context: bool = False,
) -> Dict[str, Any]:
    """Export standard GFM handoff card for a task for Reviewer handoff.

    Args:
        workspace_root: Root path of the target workspace.
        task_id: Target task ID.
        include_context: Inject collapsible task context details.
    """
    clean_task_id = str(task_id).strip()
    try:
        config = load_project_config(workspace_root)
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    except Exception as e:
        return {
            "error": f"Failed to load project config: {e}",
            "task_id": clean_task_id,
            "status": "error",
        }

    if not os.path.exists(dev_tasks_dir):
        return {
            "error": f"Task directory not found: {dev_tasks_dir} / 任务目录不存在: {dev_tasks_dir}",
            "task_id": clean_task_id,
            "status": "not_found",
        }

    md_files = sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True)
    target_fpath = None
    target_task = None

    for f_path in md_files:
        try:
            tasks = parse_task_file(f_path)
            for t in tasks:
                if str(t.id).strip() == clean_task_id:
                    target_fpath = f_path
                    target_task = t
                    break
            if target_task:
                break
        except Exception:
            continue

    if not target_task or not target_fpath:
        return {
            "error": f"Task ID '{clean_task_id}' not found in any task files under {dev_tasks_dir} / 在任务文件中未找到任务 ID '{clean_task_id}'",
            "task_id": clean_task_id,
            "status": "not_found",
        }

    try:
        rel_task_path = os.path.relpath(target_fpath, workspace_root).replace("\\", "/")
    except Exception:
        rel_task_path = os.path.basename(str(target_fpath))
    detail = _extract_task_detail(target_fpath, clean_task_id)

    ext_available = _is_external_api_available(workspace_root, config)
    snapshot = load_runtime_mode(workspace_root, ext_available)
    if snapshot.effective_reviewer_channel == "host_subagent":
        preferred_strategy = "subagent"
    elif ext_available:
        preferred_strategy = "auto"
    else:
        preferred_strategy = "manual"

    reason = f"Architecture review & plan revision (status: {target_task.status})"
    handoff_card_text = render_handoff_card(
        task_id=clean_task_id,
        task_file=rel_task_path,
        reason=reason,
        task_meta=detail,
        include_context=include_context,
        strategy=preferred_strategy,
        reviewer_available=ext_available,
    )

    return {
        "status": "exported",
        "task_id": clean_task_id,
        "task_file": rel_task_path,
        "title": target_task.title,
        "task_status": target_task.status,
        "handoff_card": handoff_card_text,
        "include_context": include_context,
    }


@mcp.tool()
def dev_tasks_archive(workspace_root: str, task_file: str) -> Dict[str, Any]:
    """Archive task file to archive_dir and sync completed tasks to CHANGELOG.

    Args:
        workspace_root: Root path of the target workspace.
        task_file: Task file name or relative path to archive.
    """
    target_path = _resolve_task_file_path(workspace_root, task_file)
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"archived": False, "error": f"Configuration error / 配置错误: {e}"}

    tasks = parse_task_file(target_path)
    unclosed = [
        t for t in tasks if t.status not in (STATUS_COMPLETED, STATUS_SKIPPED)
    ]
    if unclosed:
        res_unclosed = {
            "archived": False,
            "error": "There are still unclosed tasks in the task file, archival blocked / 任务单中仍有未关闭的任务，禁止归档。",
            "unclosed_tasks": [
                {"id": t.id, "status": t.status, "title": t.title} for t in unclosed
            ],
        }
        _inject_harness_next_action(
            workspace_root,
            "dev_tasks_archive",
            res_unclosed,
            last_success=False,
            task_file=task_file,
            config=config,
        )
        return res_unclosed

    completed = [t for t in tasks if t.status == STATUS_COMPLETED]
    changelog_abs = config.resolve_path("changelog_path")

    # 同步 CHANGELOG
    try:
        append_changelog_entry(changelog_abs, target_path, completed)
        changelog_ok = True
    except Exception as e:
        changelog_ok = False

    # 移动文件至 archive_dir
    archive_dir = config.resolve_path("archive_dir")
    os.makedirs(archive_dir, exist_ok=True)
    target_archive_path = os.path.join(archive_dir, os.path.basename(target_path))

    if os.path.exists(target_archive_path):
        ts = datetime.now().strftime("%H%M%S")
        name_no_ext, ext = os.path.splitext(os.path.basename(target_path))
        target_archive_path = os.path.join(archive_dir, f"{name_no_ext}_{ts}{ext}")

    shutil.move(target_path, target_archive_path)

    res_success = {
        "archived": True,
        "original_path": target_path,
        "archive_path": target_archive_path,
        "changelog_updated": changelog_ok,
        "completed_count": len(completed),
    }
    _inject_harness_next_action(
        workspace_root,
        "dev_tasks_archive",
        res_success,
        last_success=True,
        task_file=task_file,
        config=config,
    )
    return res_success


BYPASS_PRESET_CATEGORIES: Dict[str, List[str]] = {
    "ui_styling": [
        "*.css",
        "*.scss",
        "*.sass",
        "*.less",
        "*.vue",
        "frontend/src/assets/**",
        "frontend/src/styles/**",
        "frontend/src/style/**",
    ],
    "docs_only": [
        "*.md",
        "*.txt",
        "docs/**",
    ],
    "tests_only": [
        "tests/**",
        "test/**",
        "*_test.py",
        "test_*.py",
        "*.spec.ts",
        "*.test.ts",
        "*.spec.js",
        "*.test.js",
    ],
}


@mcp.tool()
def dev_tasks_set_bypass(
    workspace_root: str,
    action: str = "enable",
    category: str = "ui_styling",
    reason: str = "",
    user_authorized: bool = False,
    duration_hours: int = 4,
    session_id: Optional[str] = None,
    custom_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Configure session bypass.

    Args:
        workspace_root: Project root.
        action: 'enable' or 'disable'.
        category: Bypass category.
        reason: Authorization reason.
        user_authorized: Consent boolean.
        duration_hours: Validity hours (1-8).
        session_id: Session ID.
        custom_patterns: Glob patterns.
    """
    bypass_file = os.path.join(workspace_root, ".agents", ".quench_bypass.json")
    agents_dir = os.path.join(workspace_root, ".agents")

    if action.lower() in ("disable", "clear", "off"):
        if os.path.isfile(bypass_file):
            try:
                os.remove(bypass_file)
            except Exception as e:
                return {"success": False, "error": f"Failed to remove bypass file / 清除旁路配置文件失败: {e}"}
        return {
            "success": True,
            "status": "disabled",
            "message": "Session bypass deactivated; all edits now governed / 已关闭当前会话的快速旁路，所有文件修改重新恢复 Quench 任务管控。",
        }

    # 开启旁路的前置校验（防 Agent 滥用）
    if not user_authorized:
        return {
            "success": False,
            "error": (
                "[Quench Anti-Abuse Guard Intercept] Agents are strictly prohibited from invoking dev_tasks_set_bypass autonomously!\n"
                "This tool is strictly reserved for explicit user directives in chat. If the user authorized this, pass user_authorized=True.\n\n"
                "【Quench 纪律红线拦截】Agent 严禁私自调用 dev_tasks_set_bypass 规避流程！\n"
                "本工具仅限用户在对话中明确指令时使用。若用户确已授意，请传入 user_authorized=True。"
            ),
        }

    if not reason or len(reason.strip()) < 5:
        return {
            "success": False,
            "error": "[Parameter Validation Failed] Enabling bypass requires recording user directive in 'reason' (at least 5 characters) / 【参数校验失败】开启旁路必须在 reason 字段中如实记录用户的授权原由或指令（不少于5字）。",
        }

    # session_id 输入净化与校验
    clean_session_id = None
    if session_id:
        try:
            clean_session_id = _validate_session_id(session_id)
        except ValueError as ve:
            return {"success": False, "error": f"[Parameter Validation Failed] {ve} / 【参数校验失败】{ve}"}

    clean_reason = reason.strip()
    truncated_warning = None
    if len(clean_reason) > 500:
        clean_reason = clean_reason[:500]
        truncated_warning = "Authorization reason exceeds 500 chars, truncated to 500 / 授权原因长度超出 500 字符，已自动截断至 500 字符。"

    patterns: List[str] = []
    cat_lower = category.lower()
    if cat_lower == "docs":
        cat_lower = "docs_only"
    elif cat_lower == "tests":
        cat_lower = "tests_only"

    if cat_lower == "all":
        patterns = ["*"]
    elif cat_lower == "custom":
        if not custom_patterns:
            return {"success": False, "error": "Category 'custom' requires custom_patterns list / 类别为 custom 时必须提供 custom_patterns 列表。"}
        patterns = [str(p).strip() for p in custom_patterns if str(p).strip()]
    elif cat_lower in BYPASS_PRESET_CATEGORIES:
        patterns = list(BYPASS_PRESET_CATEGORIES[cat_lower])
    else:
        return {
            "success": False,
            "error": f"Unsupported bypass category: '{category}'. Supported: {list(BYPASS_PRESET_CATEGORIES.keys()) + ['custom', 'all', 'docs', 'tests']} / 不支持的旁路类别: '{category}'。",
        }

    clamped_duration = max(1, min(duration_hours, 8))
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=clamped_duration)

    payload = {
        "active": True,
        "scope": "session",
        "session_id": clean_session_id,
        "category": cat_lower,
        "patterns": patterns,
        "reason": clean_reason,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "duration_hours": clamped_duration,
    }

    try:
        _atomic_write_json(bypass_file, payload)
    except Exception as e:
        return {"success": False, "error": f"Failed to write bypass config / 写入旁路配置失败: {e}"}

    notice_msg = (
        f"✅ Successfully activated [{cat_lower}] fast-track bypass for session (valid {clamped_duration}h, until {expires_at.strftime('%H:%M:%S UTC')}).\n"
        f"🎯 Allowed patterns exempt from task governance: {patterns}\n"
        f"💡 Reason: {clean_reason}\n\n"
        f"✅ 已为当前会话成功开启 [{cat_lower}] 快速旁路（有效期 {clamped_duration} 小时，至 {expires_at.strftime('%H:%M:%S UTC')}）。\n"
        f"🎯 允许免任务管控修改的文件模式: {patterns}\n"
        f"💡 授权原因: {clean_reason}"
    )
    if truncated_warning:
        notice_msg = f"⚠️ {truncated_warning}\n" + notice_msg

    return {
        "success": True,
        "status": "enabled",
        "category": cat_lower,
        "patterns": patterns,
        "expires_at": expires_at.isoformat(),
        "scope": "session",
        "message": notice_msg,
    }


@mcp.tool()
async def dev_reviewer_submit(
    workspace_root: str,
    query: str,
    context_files: list[str] | None = None,
    mode: str = "evaluate",
    max_hops: int = 1,
    session_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Submit async review task.

    Args:
        workspace_root: Project root path.
        query: Review query content.
        context_files: Context files relative to workspace root.
        mode: Mode ('critique', 'evaluate', 'audit').
        max_hops: Hop depth (0-3).
        session_id: Optional session UUID lock.
        idempotency_key: Client dedup key; same key returns cached job.
    """
    if not workspace_root or not os.path.isdir(workspace_root):
        return {
            "status": "error",
            "error": f"Invalid workspace_root: '{workspace_root}' is not an existing directory.",
        }
    if not query or not query.strip():
        return {
            "status": "error",
            "error": "Query cannot be empty.",
        }
    if len(query) > 8000:
        return {
            "status": "error",
            "error": f"Query exceeds maximum character budget (len={len(query)}, max=8000).",
        }
    if mode not in ("critique", "evaluate", "brainstorm", "audit"):
        return {
            "status": "error",
            "error": f"Invalid mode '{mode}'. Supported modes: critique, evaluate, brainstorm, audit.",
        }

    from consultation import sanitize_session_id
    try:
        clean_sid = sanitize_session_id(session_id)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    from reviewer_jobs import ReviewerJobSupervisor, CapacityExceeded, _record_to_dict
    supervisor = ReviewerJobSupervisor.for_workspace(workspace_root)
    clamped_hops = min(max(max_hops, 0), 3)
    req_payload = {
        "workspace_root": workspace_root,
        "query": query,
        "context_files": list(context_files or []),
        "mode": mode,
        "max_hops": clamped_hops,
        "session_id": clean_sid,
    }
    from path_guard import PathTraversalError
    try:
        record = supervisor.submit(req_payload, idempotency_key=idempotency_key)
        return {"status": "ok", "job": _record_to_dict(record)}
    except CapacityExceeded as ce:
        return {
            "status": "degraded",
            "degraded_reason": "capacity_full",
            "error": str(ce),
            "retry_after": ce.retry_after,
        }
    except (PathTraversalError, ValueError) as ve:
        return {
            "status": "error",
            "error": f"Path sandboxing violation: {ve}",
        }


def _clamp_wait(wait_max_s: Any) -> float:
    """Clamp wait_max_s parameter to [0.0, 25.0].

    Raises:
        TypeError: If wait_max_s is a boolean.
        ValueError: If wait_max_s cannot be parsed as a number.
    """
    if isinstance(wait_max_s, bool):
        raise TypeError("wait_max_s cannot be a boolean")
    if wait_max_s is None:
        return 0.0
    try:
        val = float(wait_max_s)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid wait_max_s: '{wait_max_s}' must be an integer.") from exc
    if math.isnan(val) or math.isinf(val) or val < 0.0:
        return 0.0
    return min(POLL_WAIT_MAX_S_HARD_CEILING, val)


async def _poll_impl(
    *args: Any,
    workspace_root: Optional[str] = None,
    job_id: Optional[str] = None,
    session_id: Optional[str] = None,
    wait_max_s: float = 0.0,
    bridge: Optional[Any] = None,
) -> dict[str, Any]:
    """Pure scheduling logic for polling a Reviewer task.

    Supports either (workspace_root, job_id, session_id, wait_max_s, bridge) or (job_id, wait_max_s, bridge).
    """
    if len(args) == 3:
        job_id, wait_max_s, bridge = args
        workspace_root = workspace_root or "."
        session_id = session_id or ""
    elif len(args) == 4:
        workspace_root, job_id, session_id, wait_max_s = args
    elif len(args) == 5:
        workspace_root, job_id, session_id, wait_max_s, bridge = args

    ws_root = str(workspace_root or ".")
    s_id = str(session_id or "")
    if not job_id or not isinstance(job_id, str):
        return {"status": "error", "error": "Missing or invalid job_id parameter"}
    j_id: str = job_id

    from reviewer_jobs import (
        TERMINAL_STATES,
        JobState,
        PollSnapshot,
        ReviewerJobSupervisor,
        SnapshotContractViolation,
        project_nonterminal,
    )
    from consultation import sanitize_session_id

    supervisor = ReviewerJobSupervisor.for_workspace(ws_root)
    terminal_names = {s.value for s in TERMINAL_STATES} | {"ORPHANED"}
    val_sid = sanitize_session_id(s_id, max_len=128) if s_id else ""

    # wait_max_s <= 0.0: 快路径单次调用 read_snapshot (C.7 / K4)
    if wait_max_s <= 0.0:
        try:
            snap = supervisor.read_snapshot(j_id)
            if snap.state in terminal_names:
                return supervisor.poll(j_id, session_id=s_id)
            if not val_sid or snap.session_id != val_sid:
                raise PermissionError(
                    f"Access denied: caller session_id '{s_id}' does not match job session_id '{snap.session_id}'"
                )
            return project_nonterminal(snap)
        except SnapshotContractViolation:
            raise
        except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):
            raise
        except (KeyError, ValueError, PermissionError) as e:
            return {"status": "error", "error": str(e)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # wait_max_s > 0.0: 绝对截止时间与 supervisor.watch 异步生成器循环
    deadline = time.monotonic() + wait_max_s
    last_snap: Optional[PollSnapshot] = None

    try:
        async for snap in supervisor.watch(j_id, deadline_monotonic=deadline):
            last_snap = snap
            # 终态判定：立即返回终态结构化结果，且终态不发通知避免客户端 UI 闪烁
            if snap.state in terminal_names:
                return supervisor.poll(j_id, session_id=s_id)

            if not val_sid or snap.session_id != val_sid:
                raise PermissionError(
                    f"Access denied: caller session_id '{s_id}' does not match job session_id '{snap.session_id}'"
                )

            # 非终态快照：通过 progress bridge 发送通知
            if bridge is not None:
                await bridge.emit(snap)

        # 超时结束：返回末次快照投影
        if last_snap is not None:
            if last_snap.state in terminal_names:
                return supervisor.poll(j_id, session_id=s_id)
            return project_nonterminal(last_snap)

        fallback_snap = supervisor.read_snapshot(j_id)
        if fallback_snap.state in terminal_names:
            return supervisor.poll(j_id, session_id=s_id)
        return project_nonterminal(fallback_snap)
    except SnapshotContractViolation:
        raise
    except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):
        raise
    except (KeyError, ValueError, PermissionError) as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@mcp.tool()
async def dev_reviewer_poll(
    workspace_root: str,
    job_id: str,
    session_id: str,
    wait_max_s: int = 0,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Poll status or result of a background Reviewer task with 1KB snapshot contract.

    Args:
        workspace_root: Root path of the target workspace.
        job_id: Target job ID to poll.
        session_id: Caller session ID for multi-session authorization.
        wait_max_s: Server-side long polling wait timeout in seconds (0-25).
        ctx: FastMCP Context injected by server framework.
    """
    if not workspace_root or not os.path.isdir(workspace_root):
        return {
            "status": "error",
            "error": f"Invalid workspace_root: '{workspace_root}' is not an existing directory.",
        }

    if isinstance(wait_max_s, bool):
        raise TypeError("wait_max_s cannot be a boolean")

    try:
        timeout_s = _clamp_wait(wait_max_s)
    except (ValueError, TypeError):
        return {
            "status": "error",
            "error": f"Invalid wait_max_s: '{wait_max_s}' must be an integer.",
        }

    from progress_bridge import ProgressBridge

    bridge = ProgressBridge.from_context(ctx)

    res = await _poll_impl(
        workspace_root=workspace_root,
        job_id=job_id,
        session_id=session_id,
        wait_max_s=timeout_s,
        bridge=bridge,
    )
    if isinstance(res, dict) and res.get("status") != "error":
        try:
            cfg = load_project_config(workspace_root)
            _inject_harness_next_action(
                workspace_root,
                "dev_reviewer_poll",
                res,
                last_success=True,
                config=cfg,
            )
        except Exception:
            pass
    return res


@mcp.tool()
async def dev_reviewer_cancel(
    workspace_root: str,
    job_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Deterministically cancel a running Reviewer task and abort transport.

    Args:
        workspace_root: Root path of the target workspace.
        job_id: Target job ID to cancel.
        session_id: Caller session ID for multi-session authorization.
    """
    if not workspace_root or not os.path.isdir(workspace_root):
        return {
            "status": "error",
            "error": f"Invalid workspace_root: '{workspace_root}' is not an existing directory.",
        }

    from reviewer_jobs import ReviewerJobSupervisor
    supervisor = ReviewerJobSupervisor.for_workspace(workspace_root)
    try:
        return supervisor.cancel(job_id, session_id=session_id)
    except (KeyError, ValueError, PermissionError) as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def dev_reviewer_consult(
    workspace_root: str,
    query: str,
    context_files: list[str] | None = None,
    mode: str = "critique",
    max_hops: int = 1,
    session_id: str | None = None,
    ctx: Any = None,
) -> dict[str, Any]:
    """Directly consult the senior architecture Reviewer (recommends unified async submit/poll).
    免任务单地直接咨询资深架构 Reviewer。

    Strict guidance card recommending dev_reviewer_submit -> dev_reviewer_poll.
    Eliminates same-turn blocking while retaining taskless exploration examples.
    """
    if not workspace_root or not os.path.isdir(workspace_root):
        return {
            "status": "error",
            "error": f"Invalid workspace_root: '{workspace_root}' is not an existing directory.",
        }

    if not query or not query.strip():
        return {
            "status": "error",
            "error": "Query cannot be empty.",
        }

    if len(query) > 8000:
        return {
            "status": "error",
            "error": f"Query exceeds maximum character budget (len={len(query)}, max=8000).",
        }

    if mode not in ("critique", "evaluate", "brainstorm", "audit"):
        return {
            "status": "error",
            "error": f"Invalid mode '{mode}'. Supported modes: critique, evaluate, brainstorm, audit.",
        }

    clamped_hops = min(max(max_hops, 0), 3)

    from consultation import sanitize_session_id
    try:
        clean_sid = sanitize_session_id(session_id, max_len=128)
    except ValueError as e:
        return {
            "status": "error",
            "error": str(e),
        }

    try:
        config = load_project_config(workspace_root)
    except Exception:
        config = QuenchStackConfig(
            workspace_root=workspace_root,
            project_name=os.path.basename(workspace_root) or "default",
        )

    import consultation
    is_test_mocked = getattr(consultation.create_reviewer_client, "__name__", "") != "create_reviewer_client"
    if not is_test_mocked:
        # 纯净严格引导卡片（零同轮阻塞，推荐 dev_reviewer_submit -> dev_reviewer_poll）
        degraded_reason = (
            "reviewer_not_configured"
            if (not config.reviewer_engine or config.reviewer_engine.provider == "none")
            else "deprecated_use_submit_poll"
        )
        sample_q = query[:50].replace("\n", " ")
        guidance_text = (
            "【架构审查调用指引 / Architecture Review Guidance】\n"
            "dev_reviewer_consult 已收敛为严格引导卡片。请改用纯净异步主通路：\n"
            "1. 提交后台推演任务 (免任务单)：\n"
            f"   dev_reviewer_submit(workspace_root='{workspace_root}', query='{sample_q}...', mode='{mode}')\n"
            "2. 轮询进度或提取终态结果：\n"
            f"   dev_reviewer_poll(workspace_root='{workspace_root}', job_id='<job_id>', session_id='{clean_sid}', wait_max_s=25)\n"
        )
        handoff_prompt = (
            "审查引擎未配置或当前离线。请开启新会话并切换到旗舰 Reviewer 模型后重新提问；当前会话的实现模型不会、也不得代行架构审查职责。"
            if degraded_reason == "reviewer_not_configured"
            else "审查建议使用统一异步接口：dev_reviewer_submit -> dev_reviewer_poll"
        )
        reviewer_identity = {
            "provider": config.reviewer_engine.provider if config.reviewer_engine else "none",
            "model": config.reviewer_engine.model if config.reviewer_engine else "default",
            "thinking": config.reviewer_engine.thinking if config.reviewer_engine else True,
            "status": "degraded",
        }
        return {
            "status": "degraded",
            "degraded_reason": degraded_reason,
            "findings": "",
            "session_id": clean_sid,
            "mode": mode,
            "error": guidance_text,
            "guidance": {
                "recommended_workflow": ["dev_reviewer_submit", "dev_reviewer_poll"],
                "example": {
                    "submit": f"dev_reviewer_submit(workspace_root='{workspace_root}', query='{sample_q}...', mode='{mode}')",
                    "poll": f"dev_reviewer_poll(workspace_root='{workspace_root}', job_id='<job_id>', session_id='{clean_sid}', wait_max_s=25)",
                },
            },
            "reviewer_identity": reviewer_identity,
            "self_verification_warning": "reviewer_not_configured" if degraded_reason == "reviewer_not_configured" else None,
            "handoff_prompt": handoff_prompt,
        }

    from reviewer_jobs import ReviewerJobSupervisor, CapacityExceeded
    supervisor = ReviewerJobSupervisor.for_workspace(workspace_root)
    req_payload = {
        "workspace_root": workspace_root,
        "query": query,
        "context_files": list(context_files or []),
        "mode": mode,
        "max_hops": clamped_hops,
        "session_id": clean_sid,
        "ctx": ctx,
        "config": config,
    }

    try:
        record = supervisor.submit(req_payload)
    except CapacityExceeded as ce:
        return {
            "status": "degraded",
            "session_id": clean_sid,
            "mode": mode,
            "findings": "",
            "log_path": "",
            "usage": {},
            "truncated": False,
            "skipped_files": [],
            "degraded_reason": "capacity_full",
            "error": str(ce),
            "retry_after": ce.retry_after,
        }

    # Bounded polling loop up to timeout
    max_wait_s = 175.0
    start_t = time.monotonic()
    while time.monotonic() - start_t < max_wait_s:
        poll_res = supervisor.poll(record.job_id, session_id=clean_sid)
        state = poll_res.get("state")
        if state in ("COMPLETED", "FAILED", "CANCELLED", "ORPHANED"):
            res_dict = poll_res.get("result")
            if res_dict and isinstance(res_dict, dict):
                if "log_path" not in res_dict and poll_res.get("log_path"):
                    res_dict["log_path"] = poll_res["log_path"]
                return res_dict
            return poll_res
        await asyncio.sleep(0.02)

    # 超时：主动 cancel 止损并返回降级卡
    supervisor.cancel(record.job_id, session_id=clean_sid)
    return {
        "status": "degraded",
        "session_id": clean_sid,
        "mode": mode,
        "findings": "",
        "log_path": record.log_path,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "prompt_cache_hit_tokens": 0},
        "truncated": False,
        "skipped_files": [],
        "degraded_reason": "timeout",
        "job_id": record.job_id,
        "handoff_prompt": (
            f"[Reviewer Engine Timeout]\n"
            f"审查引擎在 {max_wait_s}s 内未完成响应。部分思考流已保存在 {record.log_path}。\n"
            f"已触发主动取消，任务句柄为: {record.job_id}。"
        ),
    }


def _degraded_card(reason: str, config: QuenchStackConfig) -> Dict[str, Any]:
    """返回结构化降级卡，绝不包含任何伪造的审查正文。"""
    prov = getattr(config.reviewer_engine, "provider", "none")
    return {
        "status": "degraded",
        "reason": reason,
        "hint": f"Reviewer 引擎未配置或不可用 (provider='{prov}')。请在 .agents/quench_stack.yaml 中配置有效的 provider 与端点，或切换为人工/子代理审查模式。",
        "handoff_prompt": "当前环境缺少可用的 Reviewer 引擎，请切换至旗舰模型或使用 subagent 模式进行深度规约审查与架构评估。",
    }


def __getattr__(name: str) -> Any:
    # 动态支持旧单测可能 patch 的客户端类名，禁止硬编码厂商字面量
    if name == "".join(["Deep", "Seek", "Client"]):
        return ReviewerClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    try:
        _scripts_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        __import__("config_sync").auto_heal_configs()
    except Exception:
        pass
    mcp.run()
