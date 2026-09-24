# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import glob
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

import filelock

try:
    from .manifest import (
        load_manifest,
        ManifestIntegrityError,
        MANIFEST_REL_PATH,
        TaskRecord,
        atomic_replace_manifest,
        _get_git_metadata,
    )
    from .project_config import load_project_config
    from .state_machine import parse_task_file, transition_task, STATUS_CONFIRMED
    from .manifest_lease import is_workspace_actively_modifying
except (ImportError, ValueError):
    from manifest import (
        load_manifest,
        ManifestIntegrityError,
        MANIFEST_REL_PATH,
        TaskRecord,
        atomic_replace_manifest,
        _get_git_metadata,
    )
    from project_config import load_project_config
    from state_machine import parse_task_file, transition_task, STATUS_CONFIRMED
    from manifest_lease import is_workspace_actively_modifying


class HealthVerdict(str, Enum):
    HEALTHY = "HEALTHY"
    STALE_SUSPECT = "STALE_SUSPECT"
    RELEASED = "RELEASED"
    NO_LEASE = "NO_LEASE"


@dataclass(frozen=True)
class ProbeEvidence:
    task_id: str
    verdict: HealthVerdict
    heartbeat_silence_seconds: float                         # 缺失或负值强制夹为 0.0
    affected_files_max_mtime_age_seconds: Optional[float]    # None = 无文件范围，mtime 维度缺席
    holder_token: Optional[str]                              # NO_LEASE 时为 None
    generation: int                                          # NO_LEASE 时为 -1
    reasons: Tuple[str, ...]                                 # 结构化判定理由，便于 CLI 渲染


def _extract_affected_files_from_task(
    dev_tasks_dir: str,
    md_stem: Optional[str],
    task_id: str,
) -> Optional[List[str]]:
    """从任务单 Markdown 中提取当前任务声明的 [Affected Files] 相对路径列表。"""
    md_candidates = []
    if md_stem:
        candidate = os.path.join(dev_tasks_dir, f"{md_stem}.md")
        if os.path.isfile(candidate):
            md_candidates.append(candidate)

    if not md_candidates and os.path.isdir(dev_tasks_dir):
        for f in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
            if os.path.basename(f).lower() != "readme.md":
                md_candidates.append(f)

    clean_tid = str(task_id).strip()
    for md_path in md_candidates:
        tasks = parse_task_file(md_path)
        matched = next((t for t in tasks if str(t.id).strip() == clean_tid), None)
        if not matched:
            continue

        try:
            with open(md_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue

        tid_pattern = re.escape(clean_tid)
        pattern = re.compile(
            rf"###\s+(?:任务|Task)\s+{tid_pattern}\s+.*?####\s+(?:【涉及文件】|\[Affected Files\]|【Affected Files】)\s*```(.*?)```",
            re.DOTALL | re.IGNORECASE,
        )
        m = pattern.search(content)
        if not m:
            return None

        raw_block = m.group(1).strip()
        files = []
        for line in raw_block.splitlines():
            line = line.strip()
            if not line:
                continue
            for prefix in ("[MODIFY]", "[NEW]", "[DELETE]", "[RENAME]"):
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
                    break
            if line:
                files.append(line)
        return files
    return None


def _evaluate_affected_files_mtime(
    workspace_root: str,
    affected_files: Optional[List[str]],
    now_ts: float,
) -> Tuple[Optional[float], Optional[str]]:
    """计算受管文件的最大 mtime 距当前时长（即最年轻修改与 now_ts 的时间差）。
    返回: (max_mtime_age_seconds, reason_or_degraded_note)
    """
    if affected_files is None:
        return None, "任务单未声明涉及文件段落"
    if not affected_files:
        return None, "涉及文件列表为空"

    valid_mtimes = []
    for rel_path in affected_files:
        abs_p = rel_path if os.path.isabs(rel_path) else os.path.join(workspace_root, rel_path)
        if os.path.isfile(abs_p):
            try:
                valid_mtimes.append(os.path.getmtime(abs_p))
            except Exception:
                pass

    if not valid_mtimes:
        return None, "声明的涉及文件在工作区中均不存在"

    # 最大 mtime = 最近一次文件修改时间戳
    most_recent_mtime = max(valid_mtimes)
    age = max(0.0, now_ts - most_recent_mtime)
    return age, None


def probe_lease_health(
    workspace_root: str,
    *,
    task_id: str,
    heartbeat_silence_threshold_seconds: Optional[float] = None,
    affected_files_mtime_threshold_seconds: Optional[float] = None,
    now_wall_utc: Optional[str] = None,
) -> ProbeEvidence:
    """对指定任务的活跃租约进行多维只读健康度探测。
    优先级：传入参数 > 项目配置 (reaper_policy) > 系统默认值 (900s / 600s)。
    """
    ws = os.path.abspath(workspace_root)

    # 1. 确定阈值与当前统一时间戳
    try:
        config = load_project_config(ws)
        cfg_hb = config.reaper_policy.heartbeat_silence_threshold_seconds
        cfg_mtime = config.reaper_policy.affected_files_mtime_threshold_seconds
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    except Exception:
        cfg_hb = 900.0
        cfg_mtime = 600.0
        dev_tasks_dir = os.path.join(ws, "docs", "dev_tasks")

    hb_thresh = float(heartbeat_silence_threshold_seconds) if heartbeat_silence_threshold_seconds is not None else float(cfg_hb)
    mtime_thresh = float(affected_files_mtime_threshold_seconds) if affected_files_mtime_threshold_seconds is not None else float(cfg_mtime)

    if now_wall_utc:
        try:
            now_dt = datetime.fromisoformat(now_wall_utc.replace("Z", "+00:00"))
        except Exception:
            now_dt = datetime.now(timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
    else:
        now_dt = datetime.now(timezone.utc)
    now_ts = now_dt.timestamp()

    # 2. 只读加载清单
    m = load_manifest(ws)

    # 解析 namespaced_id
    md_stem: Optional[str] = None
    clean_tid = str(task_id).strip()
    if "::" in clean_tid:
        namespaced_id = clean_tid
        md_stem = clean_tid.split("::", 1)[0]
        actual_tid = clean_tid.split("::", 1)[1]
    else:
        suffix = f"::{clean_tid}"
        namespaced_id = next((k for k in m.records if k == clean_tid or k.endswith(suffix)), None)
        if namespaced_id:
            md_stem = namespaced_id.split("::", 1)[0]
            actual_tid = clean_tid
        else:
            actual_tid = clean_tid
            if os.path.isdir(dev_tasks_dir):
                for f_path in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
                    if os.path.basename(f_path).lower() == "readme.md":
                        continue
                    for t in parse_task_file(f_path):
                        if str(t.id).strip() == clean_tid:
                            md_stem = Path(f_path).stem
                            namespaced_id = f"{md_stem}::{t.id}"
                            break
                    if namespaced_id:
                        break
            if not namespaced_id:
                namespaced_id = clean_tid

    record = m.records.get(namespaced_id)
    if record is None:
        return ProbeEvidence(
            task_id=namespaced_id,
            verdict=HealthVerdict.NO_LEASE,
            heartbeat_silence_seconds=0.0,
            affected_files_max_mtime_age_seconds=None,
            holder_token=None,
            generation=-1,
            reasons=(f"Task '{namespaced_id}' has no lease record in manifest / 清单中无租约记录",),
        )

    if record.released:
        return ProbeEvidence(
            task_id=namespaced_id,
            verdict=HealthVerdict.RELEASED,
            heartbeat_silence_seconds=0.0,
            affected_files_max_mtime_age_seconds=None,
            holder_token=record.holder_token,
            generation=record.generation,
            reasons=(f"Task '{namespaced_id}' lease was already released (tombstone) / 租约已被释放 (留痕墓碑)",),
        )

    # 3. 计算心跳静默时间差 (带 max(0.0, ...) 负时长防卫)
    try:
        hb_dt = datetime.fromisoformat(record.last_heartbeat_wall_utc.replace("Z", "+00:00"))
        if hb_dt.tzinfo is None:
            hb_dt = hb_dt.replace(tzinfo=timezone.utc)
        hb_silence = max(0.0, (now_dt - hb_dt).total_seconds())
    except Exception:
        hb_silence = 0.0

    hb_stale = (hb_silence > hb_thresh)

    # 4. 计算涉及文件最近一次修改距当前时长
    affected_files = _extract_affected_files_from_task(dev_tasks_dir, md_stem, actual_tid)
    mtime_age, mtime_note = _evaluate_affected_files_mtime(ws, affected_files, now_ts)

    mtime_absent = (mtime_age is None)
    mtime_stale = False
    if not mtime_absent:
        mtime_stale = (mtime_age > mtime_thresh)

    reasons: List[str] = []

    # 5. 判定矩阵严格遵循：STALE_SUSPECT ⟺ hb_stale ∧ (mtime_stale ∨ mtime_absent)
    # 【沉浸防杀前置条件】只要心跳或文件任意一维呈现新鲜活跃状态，即判定为 HEALTHY。
    # 特别地，即便心跳静默超时 (hb_stale)，若工作区受管文件处于活跃修改状态（沉浸防杀探针命中），
    # 则不触发 STALE_SUSPECT，降级判定为 HEALTHY。
    # 【已知局限声明】
    # 长时间纯计算/网络等待（>window_seconds）且不留白名单文件 mtime 时，hb_stale ∧ mtime_stale
    # 两套机制同时失效，仍会触发 STALE_SUSPECT。此为设计已知局限。
    if hb_stale and (mtime_stale or mtime_absent):
        actively_modifying = False
        if affected_files:
            actively_modifying = is_workspace_actively_modifying(
                ws, affected_files, window_seconds=int(mtime_thresh), now_ts=now_ts
            )

        if actively_modifying:
            verdict = HealthVerdict.HEALTHY
            reasons.append(
                f"虽然心跳静默 ({hb_silence:.1f}s > 阈值 {hb_thresh:.1f}s)，但工作区受管文件处于活跃修改状态（沉浸防杀探针命中），降级判定为 HEALTHY"
            )
        else:
            verdict = HealthVerdict.STALE_SUSPECT
            reasons.append(f"心跳静默超时 ({hb_silence:.1f}s > 阈值 {hb_thresh:.1f}s)")
            if mtime_absent:
                reasons.append(f"文件活跃度维度缺席降级 ({mtime_note})")
            else:
                reasons.append(f"受管文件修改超时 ({mtime_age:.1f}s > 阈值 {mtime_thresh:.1f}s)")
    else:
        verdict = HealthVerdict.HEALTHY
        if not hb_stale:
            reasons.append(f"心跳新鲜活跃 (静默 {hb_silence:.1f}s <= 阈值 {hb_thresh:.1f}s)")
        if not mtime_absent and not mtime_stale:
            reasons.append(f"受管文件近期有编辑活跃 (最新修改距今 {mtime_age:.1f}s <= 阈值 {mtime_thresh:.1f}s)")
        if hb_stale and not mtime_absent and not mtime_stale:
            reasons.append(f"虽然心跳静默 ({hb_silence:.1f}s > 阈值 {hb_thresh:.1f}s)，但受管文件处于新鲜活跃状态")
        elif not hb_stale and mtime_absent:
            reasons.append(f"受管文件维度缺席 ({mtime_note})，心跳活跃单独判定健康")

    return ProbeEvidence(
        task_id=namespaced_id,
        verdict=verdict,
        heartbeat_silence_seconds=hb_silence,
        affected_files_max_mtime_age_seconds=mtime_age,
        holder_token=record.holder_token,
        generation=record.generation,
        reasons=tuple(reasons),
    )


def reclaim_stale_task(
    workspace_root: str,
    *,
    task_id: str,
    expected_generation: int,
    expected_holder_token: str,
    force: bool = False,
) -> tuple[bool, str]:
    """执行 CAS 幂等任务回收。
    严格锁序：先持 Markdown 锁，再持 Manifest 锁，根除 AB-BA 死锁风险。
    若无记录返回 (False, "no_such_lease")；
    若 generation != expected 或 token != expected 或 released is True，返回 (True, "already_reclaimed_or_fenced")（幂等成功）；
    若锁内复核探针判定任务依然 HEALTHY 且未开启 force，返回 (False, "target_is_healthy")；
    回收成功将释放租约、递增 generation 并将任务单状态重置为 Confirmed。
    """
    ws = os.path.abspath(workspace_root)
    try:
        config = load_project_config(ws)
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    except Exception:
        dev_tasks_dir = os.path.join(ws, "docs", "dev_tasks")

    clean_tid = str(task_id).strip()
    md_stem: Optional[str] = None
    actual_tid: str = clean_tid
    namespaced_id: Optional[str] = None

    if "::" in clean_tid:
        namespaced_id = clean_tid
        md_stem, actual_tid = clean_tid.split("::", 1)
    else:
        # 1. 尝试从清单中反查命名空间
        try:
            m = load_manifest(ws)
            suffix = f"::{clean_tid}"
            namespaced_id = next((k for k in m.records if k == clean_tid or k.endswith(suffix)), None)
            if namespaced_id and "::" in namespaced_id:
                md_stem, actual_tid = namespaced_id.split("::", 1)
        except Exception:
            pass

        # 2. 若清单中未查到，从 dev_tasks_dir 扫描
        if not md_stem and os.path.isdir(dev_tasks_dir):
            for f_path in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
                if os.path.basename(f_path).lower() == "readme.md":
                    continue
                for t in parse_task_file(f_path):
                    if str(t.id).strip() == clean_tid:
                        md_stem = Path(f_path).stem
                        namespaced_id = f"{md_stem}::{t.id}"
                        actual_tid = str(t.id).strip()
                        break
                if md_stem:
                    break

    if not namespaced_id:
        namespaced_id = clean_tid

    md_path: Optional[str] = None
    if md_stem:
        cand = os.path.join(dev_tasks_dir, f"{md_stem}.md")
        if os.path.isfile(cand):
            md_path = cand
        elif os.path.isfile(os.path.join(ws, f"{md_stem}.md")):
            md_path = os.path.join(ws, f"{md_stem}.md")

    if not md_path:
        return (False, "no_such_lease")

    # 严格锁序：先持 Markdown 锁，再持 Manifest 锁，杜绝 AB-BA 死锁
    md_lock_path = md_path + ".lock"
    manifest_lock_path = os.path.join(ws, MANIFEST_REL_PATH + ".lock")
    os.makedirs(os.path.dirname(manifest_lock_path), exist_ok=True)

    md_lock = filelock.FileLock(md_lock_path, timeout=5.0, is_singleton=True)
    manifest_lock = filelock.FileLock(manifest_lock_path, timeout=5.0, is_singleton=True)

    with md_lock:
        with manifest_lock:
            manifest = load_manifest(ws)
            record = manifest.records.get(namespaced_id)
            if record is None and clean_tid != namespaced_id:
                record = manifest.records.get(clean_tid)
                if record is not None:
                    namespaced_id = clean_tid

            if record is None:
                return (False, "no_such_lease")

            # 双属性 CAS 校验：generation, holder_token, released
            if (
                record.generation != expected_generation
                or record.holder_token != expected_holder_token
                or record.released
            ):
                return (True, "already_reclaimed_or_fenced")

            # 锁内复核探针判定（防 TOCTOU）
            if not force:
                evidence = probe_lease_health(ws, task_id=namespaced_id)
                if evidence.verdict == HealthVerdict.HEALTHY:
                    return (False, "target_is_healthy")

            # 执行回收：递增 generation，设置 released=True 墓碑
            new_generation = record.generation + 1
            git_head_sha, git_index_mtime = _get_git_metadata(ws)
            if not git_head_sha:
                git_head_sha = record.git_head_sha
            if git_index_mtime == 0.0:
                git_index_mtime = record.git_index_mtime

            manifest.records[namespaced_id] = TaskRecord(
                task_id=record.task_id,
                md_sha256=record.md_sha256,
                generation=new_generation,
                holder_token=record.holder_token,
                last_heartbeat_monotonic_ns=time.monotonic_ns(),
                last_heartbeat_wall_utc=datetime.now(timezone.utc).isoformat(),
                git_head_sha=git_head_sha,
                git_index_mtime=git_index_mtime,
                released=True,
            )
            atomic_replace_manifest(ws, manifest)

            # 原子更新任务单状态为 ✅ 已确认 (STATUS_CONFIRMED)
            transition_task(md_path, actual_tid, STATUS_CONFIRMED)

            return (True, "reclaimed")

