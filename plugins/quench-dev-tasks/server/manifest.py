# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

from enum import Enum
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Tuple, TypeVar
import filelock

T = TypeVar("T")  # TypeVar 兼容 Python < 3.12，非 PEP 695 [T]

try:
    from .observability_policy import MAX_RECORD_BYTES
except (ImportError, ValueError):
    from observability_policy import MAX_RECORD_BYTES

try:
    from .path_guard import is_within_whitelist
except (ImportError, ValueError):
    from path_guard import is_within_whitelist

MANIFEST_REL_PATH = ".agents/.quorch/manifest.json"


class FencedTokenError(Exception):
    """当租约持有令牌冲突或代际过期时抛出 (B3)。"""
    pass


class ManifestIntegrityError(Exception):
    """清单物理文件损坏或校验不一致时抛出的 Fail-Closed 阻断异常。"""
    pass


class RetryableManifestError(Exception):
    """可重试错误基类，与 ManifestIntegrityError（Fatal）严格隔离。"""
    pass


class ManifestConflictError(RetryableManifestError):
    """CAS generation 不一致时抛出，调用方可捕获后有界重试。
    ⚠️ 不继承 ManifestIntegrityError，防止 fatal 处理器误捕获。"""
    pass


class ManifestRecordOverflowError(ManifestIntegrityError):
    """单条记录 UTF-8 字节长度超过 MAX_RECORD_BYTES 时 Fail-Closed。"""
    pass


@dataclass(frozen=True)
class ManifestMetrics:
    record_count: int
    total_bytes: int
    max_record_bytes: int


def compute_manifest_metrics(manifest: Manifest) -> ManifestMetrics:
    """纯函数，无副作用；用于 telemetry 与触发决策。"""
    records_dict = {tid: asdict(rec) for tid, rec in manifest.records.items()}
    payload = {"schema_version": manifest.schema_version, "records": records_dict}
    content_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return ManifestMetrics(
        record_count=len(manifest.records),
        total_bytes=len(content_bytes),
        max_record_bytes=MAX_RECORD_BYTES,
    )


@dataclass(frozen=True)
class TaskRecord:
    task_id: str                      # 命名空间格式: <md_stem>::<task_id> (B5)
    md_sha256: str                    # 规范化正文哈希 (B1)
    generation: int                   # 单调递增代际，fencing 核心
    holder_token: str                 # 派发时的独占租约标识
    last_heartbeat_monotonic_ns: int  # 进程内单调时钟（判时长）
    last_heartbeat_wall_utc: str      # 跨进程时间戳（判归属）
    git_head_sha: str                 # Git 分支切换容错标识
    git_index_mtime: float
    released: bool = False            # 墓碑留痕标识，代际永不回退 (B5)


@dataclass
class Manifest:
    schema_version: str = "1.0"
    records: Dict[str, TaskRecord] = field(default_factory=dict)


def compute_normalized_md_hash(md_content: str) -> str:
    """剔除状态图标 (⬜/✅/🔨/✔️/🔄/⏭️) 与元注释后计算规范化 SHA-256 (B1)。"""
    text = md_content.replace("\r\n", "\n").replace("\r", "\n")
    # 剔除 HTML 注释 (元注释)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # 剔除所有状态 Emoji 变体
    text = re.sub(r"[⬜✅🔨✔️✔🔄⏭️⏭]", "", text)
    # 规范化任务标题行（消除待确认/执行中/已完成等状态词对正文哈希的扰动）
    status_keywords = (
        r"(?:待确认|已确认|执行中|已完成|跳过|需返工|"
        r"Pending|Confirmed|In[-_ ]?Progress|Completed|Done|Skipped|Rework)"
    )
    header_regex = re.compile(
        rf"^(###\s+(?:任务|Task)\s+[0-9a-zA-Z\._\-]+)\s*[:—\-]*(?:\s*{status_keywords}\s*[:—\-]*)?\s*(.*)$",
        re.IGNORECASE | re.MULTILINE,
    )

    def _normalize_header(m: re.Match) -> str:
        prefix = m.group(1).strip()
        title = m.group(2).strip()
        if title:
            return f"{prefix} — {title}"
        return prefix

    text = header_regex.sub(_normalize_header, text)
    # 剔除行尾空格并规整空行
    lines = [line.rstrip() for line in text.splitlines()]
    normalized_text = "\n".join(lines).strip() + "\n"
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def _get_git_metadata(workspace_root: str) -> Tuple[str, float]:
    """提取 Git HEAD SHA 与 .git/index 修改时间（用于分支切换容错）。"""
    head_sha = ""
    index_mtime = 0.0
    try:
        git_dir = os.path.join(workspace_root, ".git")
        if os.path.isdir(git_dir):
            index_path = os.path.join(git_dir, "index")
            if os.path.isfile(index_path):
                index_mtime = os.path.getmtime(index_path)
            head_path = os.path.join(git_dir, "HEAD")
            if os.path.isfile(head_path):
                with open(head_path, "r", encoding="utf-8", errors="replace") as f:
                    head_content = f.read().strip()
                if head_content.startswith("ref:"):
                    ref_part = head_content[4:].strip()
                    ref_path = os.path.join(git_dir, ref_part.replace("/", os.sep))
                    if os.path.isfile(ref_path):
                        with open(ref_path, "r", encoding="utf-8", errors="replace") as rf:
                            head_sha = rf.read().strip()
                else:
                    head_sha = head_content
        if not head_sha:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                head_sha = res.stdout.strip()
    except Exception:
        pass

    if index_mtime == 0.0:
        index_mtime = time.time()
    return head_sha, index_mtime


def load_manifest(workspace_root: str) -> Manifest:
    """加载权威清单；首次运行自动初始化 generation=0 容器，若损坏则 Fail-Closed 阻断抛出 ManifestIntegrityError。"""
    manifest_path = os.path.join(workspace_root, MANIFEST_REL_PATH)
    if not os.path.isfile(manifest_path):
        return Manifest(schema_version="1.0", records={})

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise ManifestIntegrityError(f"Failed to read or parse manifest '{manifest_path}': {e}") from e

    if not isinstance(data, dict):
        raise ManifestIntegrityError(f"Corrupted manifest format in '{manifest_path}': root must be a JSON object")

    schema_version = str(data.get("schema_version", "1.0"))
    raw_records = data.get("records")
    if raw_records is None:
        raw_records = {}
    elif not isinstance(raw_records, dict):
        raise ManifestIntegrityError(f"Corrupted manifest records in '{manifest_path}': 'records' must be a JSON object")

    records: Dict[str, TaskRecord] = {}
    for tid, rdata in raw_records.items():
        if not isinstance(rdata, dict):
            raise ManifestIntegrityError(f"Invalid record data for '{tid}' in '{manifest_path}': record must be a dict")
        try:
            record = TaskRecord(
                task_id=str(rdata.get("task_id", tid)),
                md_sha256=str(rdata.get("md_sha256", "")),
                generation=int(rdata.get("generation", 0)),
                holder_token=str(rdata.get("holder_token", "")),
                last_heartbeat_monotonic_ns=int(rdata.get("last_heartbeat_monotonic_ns", 0)),
                last_heartbeat_wall_utc=str(rdata.get("last_heartbeat_wall_utc", "")),
                git_head_sha=str(rdata.get("git_head_sha", "")),
                git_index_mtime=float(rdata.get("git_index_mtime", 0.0)),
                released=bool(rdata.get("released", False)),
            )
            records[tid] = record
        except (ValueError, TypeError) as e:
            raise ManifestIntegrityError(f"Corrupted record fields for '{tid}' in '{manifest_path}': {e}") from e
    return Manifest(schema_version=schema_version, records=records)


def atomic_replace_manifest(workspace_root: str, manifest: Manifest) -> None:
    """通过同目录临时文件与 os.replace 保证 manifest.json 原子安全持久化（带 16KB 物理上限防护）。"""
    manifest_path = os.path.join(workspace_root, MANIFEST_REL_PATH)
    dir_name = os.path.dirname(manifest_path)
    os.makedirs(dir_name, exist_ok=True)

    records_dict: Dict[str, Any] = {}
    for tid, rec in manifest.records.items():
        rec_data = asdict(rec)
        rec_str = json.dumps(rec_data, ensure_ascii=False)
        rec_bytes = rec_str.encode("utf-8")
        # 边界防护：单条记录不超过 MAX_RECORD_BYTES，违者 Fail-Closed 熔断阻断
        if len(rec_bytes) > MAX_RECORD_BYTES:
            raise ManifestRecordOverflowError(
                f"Task record '{tid}' byte size ({len(rec_bytes)} bytes) exceeds MAX_RECORD_BYTES ({MAX_RECORD_BYTES} bytes). "
                f"Fail-Closed protection triggered / 任务单记录字节大小超过物理上限，触发安全熔断阻断"
            )
        records_dict[tid] = rec_data

    payload = {
        "schema_version": manifest.schema_version,
        "records": records_dict,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)

    prefix = f".tmp_manifest_{os.getpid()}_"
    temp_fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, manifest_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


def _resolve_namespaced_id(manifest: Manifest, task_id: str, md_path: Optional[str] = None) -> str:
    """解析权威命名空间格式: <md_stem>::<task_id> (B5)。"""
    if "::" in task_id:
        return task_id
    if md_path:
        stem = Path(md_path).stem
        return f"{stem}::{task_id}"
    # 若未传 md_path，尝试在 manifest 现有记录中匹配
    suffix = f"::{task_id}"
    for k in manifest.records:
        if k == task_id or k.endswith(suffix):
            return k
    return task_id


_lock_local = threading.local()


def mutate_manifest_under_lock(
    workspace_root: str,
    mutator: Callable[[Manifest], Tuple[Manifest, T]],
    *,
    lock_timeout: float = 5.0,  # 取锁超时（非整体操作超时，仅控制获取物理锁等待上限；mutator 必须为轻量纯内存计算）
) -> T:
    """持锁 → 锁内 fresh-fd 重读 → mutator → 兜底 CAS → 原子覆写。
    - mutator 必须为纯函数，禁止调用任何 manifest 取锁 API（违反 → RuntimeError，非死锁）；
    - mutator 抛异常时：跳过 atomic_replace + 释放锁(finally) + 关闭 fd(finally)，原样重抛；
    - helper 内部 fresh-fd 读时记录 generation，replace 前再断言未变（兜底 CAS）；
    - 临时文件置于清单同目录（跨平台 os.replace 原子性）。
    """
    if getattr(_lock_local, "in_critical_section", False):
        raise RuntimeError(
            "Re-entrant manifest lock acquisition detected in mutator / mutator 中禁止调用取锁 API（重入死锁守护触发）"
        )

    lock_path = os.path.join(workspace_root, MANIFEST_REL_PATH + ".lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock = filelock.FileLock(lock_path, timeout=lock_timeout)

    _lock_local.in_critical_section = True
    try:
        with lock:
            initial_manifest = load_manifest(workspace_root)
            initial_generations = {
                tid: rec.generation for tid, rec in initial_manifest.records.items()
            }

            new_manifest, result = mutator(initial_manifest)

            # 兜底 CAS 校验：在原子替换前重新检验磁盘代际是否被并发修改
            manifest_path = os.path.join(workspace_root, MANIFEST_REL_PATH)
            if os.path.exists(manifest_path):
                current_disk = load_manifest(workspace_root)
                current_generations = {
                    tid: rec.generation for tid, rec in current_disk.records.items()
                }
                if current_generations != initial_generations:
                    raise ManifestConflictError(
                        f"Manifest generation on disk conflicted during mutation: "
                        f"expected {initial_generations}, got {current_generations} / 清单代际在事务内发生冲突"
                    )

            if new_manifest is not initial_manifest or result is not False:
                atomic_replace_manifest(workspace_root, new_manifest)

            return result
    finally:
        _lock_local.in_critical_section = False


def commit_lease(
    workspace_root: str,
    *,
    task_id: str,
    holder_token: str,
    expected_generation: int,
    md_path: str,
) -> int:
    """提交/续签独占租约。成功自增返回新 generation，代际/哈希冲突抛出 FencedTokenError (B3)。"""
    resolved_md_path = md_path if os.path.isabs(md_path) else os.path.join(workspace_root, md_path)
    if not os.path.isfile(resolved_md_path):
        raise FileNotFoundError(f"Task file not found / 任务文件不存在: {md_path}")

    with open(resolved_md_path, "r", encoding="utf-8") as f:
        md_content = f.read()
    current_hash = compute_normalized_md_hash(md_content)

    def _mutator(manifest: Manifest) -> Tuple[Manifest, int]:
        namespaced_id = _resolve_namespaced_id(manifest, task_id, resolved_md_path)
        existing = manifest.records.get(namespaced_id)

        if existing is not None:
            if existing.generation != expected_generation:
                raise FencedTokenError(
                    f"Generation mismatch for '{namespaced_id}': expected {expected_generation}, got {existing.generation} / "
                    f"代际不匹配：预期 {expected_generation}，实际当前为 {existing.generation}"
                )
            if not existing.released and existing.holder_token and existing.holder_token != holder_token:
                raise FencedTokenError(
                    f"Task '{namespaced_id}' lease is currently held by active token '{existing.holder_token}' / "
                    f"任务 '{namespaced_id}' 租约已被活跃持有者 '{existing.holder_token}' 占用"
                )
            if existing.md_sha256 and expected_generation > 0 and existing.md_sha256 != current_hash:
                raise FencedTokenError(
                    f"Task '{namespaced_id}' content hash mismatch (expected {existing.md_sha256}, got {current_hash}). Document was altered / "
                    f"任务 '{namespaced_id}' 正文哈希对账不一致，任务内容已被外部未核准修改"
                )
            new_generation = expected_generation + 1
        else:
            if expected_generation != 0:
                raise FencedTokenError(
                    f"Task '{namespaced_id}' has no prior lease record, expected_generation must be 0, got {expected_generation} / "
                    f"任务 '{namespaced_id}' 无历史记录，初始 expected_generation 必须为 0"
                )
            new_generation = 1

        git_head_sha, git_index_mtime = _get_git_metadata(workspace_root)
        new_manifest = Manifest(schema_version=manifest.schema_version, records=dict(manifest.records))
        new_manifest.records[namespaced_id] = TaskRecord(
            task_id=namespaced_id,
            md_sha256=current_hash,
            generation=new_generation,
            holder_token=holder_token,
            last_heartbeat_monotonic_ns=time.monotonic_ns(),
            last_heartbeat_wall_utc=datetime.now(timezone.utc).isoformat(),
            git_head_sha=git_head_sha,
            git_index_mtime=git_index_mtime,
            released=False,
        )
        return new_manifest, new_generation

    return mutate_manifest_under_lock(workspace_root, _mutator)


def compare_and_swap(
    workspace_root: str,
    *,
    task_id: str,
    expected_generation: int,
    new_generation: int,
    holder_token: str,
) -> bool:
    """原子 CAS 状态变更：仅在当前 generation == expected_generation 且单调递增时生效。"""
    if new_generation <= expected_generation:
        return False

    def _mutator(manifest: Manifest) -> Tuple[Manifest, bool]:
        namespaced_id = _resolve_namespaced_id(manifest, task_id)
        record = manifest.records.get(namespaced_id)
        if record is None:
            return manifest, False
        if record.generation != expected_generation:
            return manifest, False

        git_head_sha, git_index_mtime = _get_git_metadata(workspace_root)
        new_manifest = Manifest(schema_version=manifest.schema_version, records=dict(manifest.records))
        new_manifest.records[namespaced_id] = TaskRecord(
            task_id=record.task_id,
            md_sha256=record.md_sha256,
            generation=new_generation,
            holder_token=holder_token,
            last_heartbeat_monotonic_ns=time.monotonic_ns(),
            last_heartbeat_wall_utc=datetime.now(timezone.utc).isoformat(),
            git_head_sha=git_head_sha,
            git_index_mtime=git_index_mtime,
            released=False,
        )
        return new_manifest, True

    return mutate_manifest_under_lock(workspace_root, _mutator)


def release_lease(
    workspace_root: str,
    *,
    task_id: str,
    holder_token: str,
    generation: int,
) -> bool:
    """释放租约：采用留痕墓碑（released=True），保留 generation，代际永不回退 (B5)。"""
    def _mutator(manifest: Manifest) -> Tuple[Manifest, bool]:
        namespaced_id = _resolve_namespaced_id(manifest, task_id)
        record = manifest.records.get(namespaced_id)
        if record is None:
            return manifest, False
        if record.generation != generation:
            return manifest, False
        if record.holder_token != holder_token:
            return manifest, False
        if record.released:
            return manifest, True

        git_head_sha, git_index_mtime = _get_git_metadata(workspace_root)
        new_manifest = Manifest(schema_version=manifest.schema_version, records=dict(manifest.records))
        new_manifest.records[namespaced_id] = TaskRecord(
            task_id=record.task_id,
            md_sha256=record.md_sha256,
            generation=record.generation,
            holder_token=record.holder_token,
            last_heartbeat_monotonic_ns=time.monotonic_ns(),
            last_heartbeat_wall_utc=datetime.now(timezone.utc).isoformat(),
            git_head_sha=git_head_sha,
            git_index_mtime=git_index_mtime,
            released=True,
        )
        return new_manifest, True

    return mutate_manifest_under_lock(workspace_root, _mutator)


def touch_heartbeat(
    workspace_root: str,
    *,
    task_id: str,
    holder_token: str,
    generation: int,
    now_monotonic_ns: Optional[int] = None,
    now_wall_utc: Optional[str] = None,
) -> bool:
    """原子刷新任务心跳时间戳。
    仅当 generation 与 holder_token 严格匹配活跃租约时刷新并返回 True；
    若代际失效或租约已释放，返回 False（fail-closed），防已回收的旧持有者误续命。
    """
    def _mutator(manifest: Manifest) -> Tuple[Manifest, bool]:
        namespaced_id = _resolve_namespaced_id(manifest, task_id)
        record = manifest.records.get(namespaced_id)
        if record is None:
            return manifest, False
        if record.released:
            return manifest, False
        if record.generation != generation:
            return manifest, False
        if record.holder_token != holder_token:
            return manifest, False

        m_ns = now_monotonic_ns if now_monotonic_ns is not None else time.monotonic_ns()
        w_utc = now_wall_utc if now_wall_utc is not None else datetime.now(timezone.utc).isoformat()

        new_manifest = Manifest(schema_version=manifest.schema_version, records=dict(manifest.records))
        new_manifest.records[namespaced_id] = TaskRecord(
            task_id=record.task_id,
            md_sha256=record.md_sha256,
            generation=record.generation,
            holder_token=record.holder_token,
            last_heartbeat_monotonic_ns=m_ns,
            last_heartbeat_wall_utc=w_utc,
            git_head_sha=record.git_head_sha,
            git_index_mtime=record.git_index_mtime,
            released=False,
        )
        return new_manifest, True

    return mutate_manifest_under_lock(workspace_root, _mutator)


class ReconcileClass(str, Enum):
    REGISTERED_MATCH      = "REGISTERED_MATCH"       # 已登记且哈希一致
    REGISTERED_DRIFT      = "REGISTERED_DRIFT"       # 已登记但正文哈希不符（人工编辑 / 篡改）
    BRANCH_CHANGED        = "BRANCH_CHANGED"         # git_head_sha 变更引发的正常分支切换漂移
    UNAUTHORIZED_BYPASS   = "UNAUTHORIZED_BYPASS"    # 完全未在清单登记的非法旁路文件


@dataclass(frozen=True)
class ReconcileEntry:
    rel_path: str
    namespaced_id: Optional[str]
    classification: ReconcileClass
    md_sha256: str
    drift_reason: str = ""


@dataclass(frozen=True)
class ReconcileReport:
    entries: Tuple[ReconcileEntry, ...]
    bypass_queue: Tuple[str, ...]     # 未经授权的隔离文件（仅在内存/报表呈现，不写回 Markdown）
    drift_queue: Tuple[str, ...]      # 发生哈希漂移的文件
    matched_queue: Tuple[str, ...]    # 正常通过核验的文件


def register_proposal(workspace_root: str, *, task_id: str, md_path: str) -> str:
    """在权威清单中登记新任务单的 SHA-256 哈希基线。"""
    resolved_md_path = md_path if os.path.isabs(md_path) else os.path.join(workspace_root, md_path)
    if not os.path.isfile(resolved_md_path):
        raise FileNotFoundError(f"Task file not found / 任务文件不存在: {md_path}")

    with open(resolved_md_path, "r", encoding="utf-8") as f:
        content = f.read()
    current_hash = compute_normalized_md_hash(content)

    def _mutator(manifest: Manifest) -> Tuple[Manifest, str]:
        namespaced_id = _resolve_namespaced_id(manifest, task_id, resolved_md_path)
        git_head_sha, git_index_mtime = _get_git_metadata(workspace_root)

        existing = manifest.records.get(namespaced_id)
        gen = existing.generation if existing else 0
        holder = existing.holder_token if existing else ""
        released = existing.released if existing else False

        new_manifest = Manifest(schema_version=manifest.schema_version, records=dict(manifest.records))
        new_manifest.records[namespaced_id] = TaskRecord(
            task_id=namespaced_id,
            md_sha256=current_hash,
            generation=gen,
            holder_token=holder,
            last_heartbeat_monotonic_ns=time.monotonic_ns(),
            last_heartbeat_wall_utc=datetime.now(timezone.utc).isoformat(),
            git_head_sha=git_head_sha,
            git_index_mtime=git_index_mtime,
            released=released,
        )
        return new_manifest, current_hash

    return mutate_manifest_under_lock(workspace_root, _mutator)


def _get_git_tracked_files(workspace_root: str, target_dir: str) -> set[str]:
    """获取 target_dir 下被 Git 明确跟踪的文件集合（相对 workspace_root）。"""
    try:
        rel_target_dir = os.path.relpath(target_dir, workspace_root).replace("\\", "/")
        res = subprocess.run(
            ["git", "-C", workspace_root, "ls-files", rel_target_dir],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
            timeout=5.0,
        )
        if res.returncode == 0:
            return {line.strip().replace("\\", "/") for line in res.stdout.splitlines() if line.strip()}
        return set()
    except Exception:
        return set()


def reconcile_workspace(workspace_root: str, dev_tasks_dir: str) -> ReconcileReport:
    """全盘扫描任务单目录并与清单执行后置对账。"""
    resolved_dir = dev_tasks_dir if os.path.isabs(dev_tasks_dir) else os.path.join(workspace_root, dev_tasks_dir)
    if not os.path.isdir(resolved_dir):
        return ReconcileReport(entries=(), bypass_queue=(), drift_queue=(), matched_queue=())

    manifest = load_manifest(workspace_root)
    git_head_sha, _ = _get_git_metadata(workspace_root)
    tracked_files = _get_git_tracked_files(workspace_root, resolved_dir)

    entries: list[ReconcileEntry] = []
    bypass_list: list[str] = []
    drift_list: list[str] = []
    matched_list: list[str] = []

    md_files = sorted(glob.glob(os.path.join(resolved_dir, "*.md")))
    for md_path in md_files:
        basename = os.path.basename(md_path)
        if basename.lower() == "readme.md":
            continue

        rel_path = os.path.relpath(md_path, workspace_root).replace("\\", "/")
        stem = Path(md_path).stem

        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            current_hash = compute_normalized_md_hash(content)
        except Exception:
            current_hash = ""

        matching_records = [
            rec for k, rec in manifest.records.items()
            if k == stem or k.startswith(f"{stem}::")
        ]

        if matching_records:
            primary_record = matching_records[0]
            if any(rec.md_sha256 == current_hash for rec in matching_records):
                entry = ReconcileEntry(
                    rel_path=rel_path,
                    namespaced_id=primary_record.task_id,
                    classification=ReconcileClass.REGISTERED_MATCH,
                    md_sha256=current_hash,
                    drift_reason="",
                )
                entries.append(entry)
                matched_list.append(rel_path)
            else:
                if primary_record.git_head_sha and git_head_sha and primary_record.git_head_sha != git_head_sha:
                    entry = ReconcileEntry(
                        rel_path=rel_path,
                        namespaced_id=primary_record.task_id,
                        classification=ReconcileClass.BRANCH_CHANGED,
                        md_sha256=current_hash,
                        drift_reason=f"Git HEAD changed ({primary_record.git_head_sha[:8]} -> {git_head_sha[:8]})",
                    )
                    entries.append(entry)
                    matched_list.append(rel_path)
                else:
                    entry = ReconcileEntry(
                        rel_path=rel_path,
                        namespaced_id=primary_record.task_id,
                        classification=ReconcileClass.REGISTERED_DRIFT,
                        md_sha256=current_hash,
                        drift_reason=f"Hash mismatch: expected {primary_record.md_sha256[:8]}..., got {current_hash[:8]}...",
                    )
                    entries.append(entry)
                    drift_list.append(rel_path)
        else:
            # 未在清单中找到记录
            if rel_path in tracked_files:
                # Git 历史跟踪文件自动平滑录入
                try:
                    register_proposal(workspace_root, task_id=stem, md_path=md_path)
                except Exception:
                    pass
                entry = ReconcileEntry(
                    rel_path=rel_path,
                    namespaced_id=f"{stem}::{stem}",
                    classification=ReconcileClass.REGISTERED_MATCH,
                    md_sha256=current_hash,
                    drift_reason="Git-tracked historical file smoothly onboarded",
                )
                entries.append(entry)
                matched_list.append(rel_path)
            else:
                # 未跟踪也未登记：非法旁路任务单，隔离入 bypass_queue
                entry = ReconcileEntry(
                    rel_path=rel_path,
                    namespaced_id=None,
                    classification=ReconcileClass.UNAUTHORIZED_BYPASS,
                    md_sha256=current_hash,
                    drift_reason="Untracked task file not registered in manifest",
                )
                entries.append(entry)
                bypass_list.append(rel_path)

    return ReconcileReport(
        entries=tuple(entries),
        bypass_queue=tuple(bypass_list),
        drift_queue=tuple(drift_list),
        matched_queue=tuple(matched_list),
    )


# ---------------------------------------------------------------------------
# Task 1.2: Baseline Snapshot & Physical Scope Reconciliation Gate
# ---------------------------------------------------------------------------

EXCLUDED_WORKSPACE_DIRS: Final[frozenset[str]] = frozenset({
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
})


@dataclass(frozen=True)
class FileFingerprint:
    rel_path: str
    size: int
    mtime_ns: int
    digest: str  # sha256:<hex>
    inode: int = 0


@dataclass(frozen=True)
class BaselineSnapshot:
    schema_version: int
    task_id: str
    session_id: str
    head_commit: str
    fingerprints: Mapping[str, FileFingerprint]
    created_at_utc: str
    snapshot_digest: str


@dataclass(frozen=True)
class ReconciliationReport:
    verdict: Literal["allow", "deny", "degraded"]
    violating_files: tuple[str, ...]
    checked_count: int
    fast_path_hits: int
    elapsed_ms: float
    degraded_reason: str | None


def _get_git_head_commit(workspace_root: str) -> str:
    """Safely obtain Git HEAD commit or fallback to 'no-git'."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "no-git"


def _safe_baseline_filename(task_id: str) -> str:
    cleaned = re.sub(r"[^\w\.-]", "_", str(task_id).strip())
    return f"{cleaned}.json"


def get_baseline_path(workspace_root: str, task_id: str) -> str:
    """Return canonical path to baseline snapshot JSON file."""
    return os.path.join(
        workspace_root, ".agents", ".quorch", "baselines", _safe_baseline_filename(task_id)
    )


def save_baseline_snapshot(workspace_root: str, snapshot: BaselineSnapshot) -> str:
    """Atomically save baseline snapshot to disk using tempfile + os.replace."""
    target_path = get_baseline_path(workspace_root, snapshot.task_id)
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir, exist_ok=True)

    data = {
        "schema_version": snapshot.schema_version,
        "task_id": snapshot.task_id,
        "session_id": snapshot.session_id,
        "head_commit": snapshot.head_commit,
        "created_at_utc": snapshot.created_at_utc,
        "snapshot_digest": snapshot.snapshot_digest,
        "fingerprints": {
            k: {
                "rel_path": v.rel_path,
                "size": v.size,
                "mtime_ns": v.mtime_ns,
                "digest": v.digest,
                "inode": v.inode,
            }
            for k, v in snapshot.fingerprints.items()
        },
    }

    temp_fd, temp_path = tempfile.mkstemp(
        dir=target_dir, prefix=".tmp_baseline_", suffix=".json"
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise
    return target_path


def load_baseline_snapshot(path: str) -> BaselineSnapshot:
    """Load baseline snapshot from file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    fps = {
        k: FileFingerprint(
            rel_path=v["rel_path"],
            size=v["size"],
            mtime_ns=v["mtime_ns"],
            digest=v["digest"],
            inode=v.get("inode", 0),
        )
        for k, v in data.get("fingerprints", {}).items()
    }
    return BaselineSnapshot(
        schema_version=data.get("schema_version", 1),
        task_id=data["task_id"],
        session_id=data.get("session_id", "default"),
        head_commit=data.get("head_commit", "no-git"),
        fingerprints=fps,
        created_at_utc=data.get("created_at_utc", ""),
        snapshot_digest=data.get("snapshot_digest", ""),
    )


def capture_baseline(
    workspace_root: str, task_id: str, session_id: str
) -> BaselineSnapshot:
    """Capture physical workspace baseline snapshot at checkout."""
    real_ws = os.path.realpath(os.path.abspath(workspace_root))
    fingerprints: dict[str, FileFingerprint] = {}

    for root, dirs, files in os.walk(real_ws):
        dirs[:] = [
            d for d in dirs if d not in EXCLUDED_WORKSPACE_DIRS and not d.startswith(".tmp_")
        ]
        rel_root = os.path.relpath(root, real_ws).replace("\\", "/")
        if rel_root.startswith(".agents/.quorch/baselines"):
            continue

        for fname in files:
            if fname.endswith(".lock") or fname.endswith(".tmp") or fname.startswith(".tmp_"):
                continue
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, real_ws).replace("\\", "/")
            try:
                st = os.stat(abs_path)
                mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
                size = st.st_size
                inode = getattr(st, "st_ino", 0)

                h = hashlib.sha256()
                with open(abs_path, "rb") as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
                digest = f"sha256:{h.hexdigest()}"

                fingerprints[rel_path] = FileFingerprint(
                    rel_path=rel_path,
                    size=size,
                    mtime_ns=mtime_ns,
                    digest=digest,
                    inode=inode,
                )
            except (OSError, PermissionError):
                continue

    head_commit = _get_git_head_commit(real_ws)
    now_utc = datetime.now(timezone.utc).isoformat()

    items = [
        {
            "rel_path": fp.rel_path,
            "size": fp.size,
            "mtime_ns": fp.mtime_ns,
            "digest": fp.digest,
        }
        for fp in sorted(fingerprints.values(), key=lambda x: x.rel_path)
    ]
    raw_digest_content = json.dumps(items, sort_keys=True).encode("utf-8")
    snapshot_digest = f"sha256:{hashlib.sha256(raw_digest_content).hexdigest()}"

    snapshot = BaselineSnapshot(
        schema_version=1,
        task_id=str(task_id).strip(),
        session_id=str(session_id).strip() if session_id else "default",
        head_commit=head_commit,
        fingerprints=fingerprints,
        created_at_utc=now_utc,
        snapshot_digest=snapshot_digest,
    )

    save_baseline_snapshot(real_ws, snapshot)
    return snapshot


def reconcile_workspace_against_whitelist(
    workspace_root: str,
    snapshot: BaselineSnapshot,
    whitelist_paths: Sequence[str],
    unmanaged_patterns: Sequence[str],
    budget_ms: float = 50.0,
) -> ReconciliationReport:
    """Pure-function workspace reconciliation against baseline and whitelist. Zero write syscalls."""
    start_time = time.perf_counter()
    budget_sec = budget_ms / 1000.0
    real_ws = os.path.realpath(os.path.abspath(workspace_root))

    fast_path_hits = 0
    checked_count = 0
    modified_files: set[str] = set()

    # Fast check: if budget is 0 or negative, degrade immediately
    if budget_ms <= 0:
        return ReconciliationReport(
            verdict="degraded",
            violating_files=(),
            checked_count=0,
            fast_path_hits=0,
            elapsed_ms=0.0,
            degraded_reason="Zero or negative reconciliation budget",
        )

    # 1. Quick + Slow path comparison against baseline fingerprints
    for rel_path, fp in snapshot.fingerprints.items():
        if (time.perf_counter() - start_time) > budget_sec:
            elapsed = (time.perf_counter() - start_time) * 1000
            return ReconciliationReport(
                verdict="degraded",
                violating_files=(),
                checked_count=checked_count,
                fast_path_hits=fast_path_hits,
                elapsed_ms=elapsed,
                degraded_reason="Reconciliation timeout budget exceeded during baseline comparison",
            )

        checked_count += 1
        abs_path = os.path.join(real_ws, rel_path)
        if not os.path.exists(abs_path):
            # File was removed
            modified_files.add(rel_path)
            continue

        try:
            st = os.stat(abs_path)
            st_mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
            st_size = st.st_size
            st_ino = getattr(st, "st_ino", 0)

            # Fast path hit: size, mtime_ns, and inode match exactly
            if (
                st_size == fp.size
                and st_mtime_ns == fp.mtime_ns
                and (fp.inode == 0 or st_ino == fp.inode)
            ):
                fast_path_hits += 1
            else:
                # Slow path: re-hash
                h = hashlib.sha256()
                with open(abs_path, "rb") as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
                cur_digest = f"sha256:{h.hexdigest()}"
                if cur_digest != fp.digest:
                    modified_files.add(rel_path)
        except (OSError, PermissionError):
            modified_files.add(rel_path)

    # 2. Check for newly introduced files in workspace
    for root, dirs, files in os.walk(real_ws):
        if (time.perf_counter() - start_time) > budget_sec:
            elapsed = (time.perf_counter() - start_time) * 1000
            return ReconciliationReport(
                verdict="degraded",
                violating_files=(),
                checked_count=checked_count,
                fast_path_hits=fast_path_hits,
                elapsed_ms=elapsed,
                degraded_reason="Reconciliation timeout budget exceeded during workspace scan",
            )

        dirs[:] = [
            d for d in dirs if d not in EXCLUDED_WORKSPACE_DIRS and not d.startswith(".tmp_")
        ]
        rel_root = os.path.relpath(root, real_ws).replace("\\", "/")
        if rel_root.startswith(".agents/.quorch/baselines"):
            continue

        for fname in files:
            if fname.endswith(".lock") or fname.endswith(".tmp") or fname.startswith(".tmp_"):
                continue
            abs_p = os.path.join(root, fname)
            rel_p = os.path.relpath(abs_p, real_ws).replace("\\", "/")
            if rel_p not in snapshot.fingerprints:
                modified_files.add(rel_p)

    # 3. Filter modified files against unmanaged patterns and whitelist
    cs = (sys.platform != "win32")
    violating: list[str] = []

    effective_unmanaged = list(unmanaged_patterns) + [
        ".agents/.quorch/**",
        ".agents/.quorch/baselines/**",
    ]

    for f_rel in modified_files:
        if is_within_whitelist(f_rel, effective_unmanaged, case_sensitive=cs):
            # Unmanaged path (e.g. docs, markdown, baselines), allowed to change freely
            continue

        if not is_within_whitelist(f_rel, whitelist_paths, case_sensitive=cs):
            violating.append(f_rel)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    if violating:
        return ReconciliationReport(
            verdict="deny",
            violating_files=tuple(sorted(violating)),
            checked_count=checked_count,
            fast_path_hits=fast_path_hits,
            elapsed_ms=elapsed_ms,
            degraded_reason=None,
        )

    return ReconciliationReport(
        verdict="allow",
        violating_files=(),
        checked_count=checked_count,
        fast_path_hits=fast_path_hits,
        elapsed_ms=elapsed_ms,
        degraded_reason=None,
    )


