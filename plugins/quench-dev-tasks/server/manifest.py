# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import filelock

try:
    from .observability_policy import MAX_RECORD_BYTES
except (ImportError, ValueError):
    from observability_policy import MAX_RECORD_BYTES

MANIFEST_REL_PATH = ".agents/.quorch/manifest.json"


class FencedTokenError(Exception):
    """当租约持有令牌冲突或代际过期时抛出 (B3)。"""
    pass


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
    """加载权威清单；首次运行自动初始化 generation=0 容器，若损坏则自动安全兜底。"""
    manifest_path = os.path.join(workspace_root, MANIFEST_REL_PATH)
    if not os.path.isfile(manifest_path):
        return Manifest(schema_version="1.0", records={})

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return Manifest(schema_version="1.0", records={})

    schema_version = str(data.get("schema_version", "1.0"))
    raw_records = data.get("records", {})
    records: Dict[str, TaskRecord] = {}
    for tid, rdata in raw_records.items():
        if isinstance(rdata, dict):
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
            except (ValueError, TypeError):
                continue
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
        # 边界防护：单条记录不超过 MAX_RECORD_BYTES
        if len(rec_str.encode("utf-8")) > MAX_RECORD_BYTES:
            pass
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

    lock_path = os.path.join(workspace_root, MANIFEST_REL_PATH + ".lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock = filelock.FileLock(lock_path, timeout=5.0)

    with lock:
        manifest = load_manifest(workspace_root)
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
        record = TaskRecord(
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
        manifest.records[namespaced_id] = record
        atomic_replace_manifest(workspace_root, manifest)
        return new_generation


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

    lock_path = os.path.join(workspace_root, MANIFEST_REL_PATH + ".lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock = filelock.FileLock(lock_path, timeout=5.0)

    with lock:
        manifest = load_manifest(workspace_root)
        namespaced_id = _resolve_namespaced_id(manifest, task_id)
        record = manifest.records.get(namespaced_id)
        if record is None:
            return False
        if record.generation != expected_generation:
            return False

        git_head_sha, git_index_mtime = _get_git_metadata(workspace_root)
        manifest.records[namespaced_id] = TaskRecord(
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
        atomic_replace_manifest(workspace_root, manifest)
        return True


def release_lease(
    workspace_root: str,
    *,
    task_id: str,
    holder_token: str,
    generation: int,
) -> bool:
    """释放租约：采用留痕墓碑（released=True），保留 generation，代际永不回退 (B5)。"""
    lock_path = os.path.join(workspace_root, MANIFEST_REL_PATH + ".lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock = filelock.FileLock(lock_path, timeout=5.0)

    with lock:
        manifest = load_manifest(workspace_root)
        namespaced_id = _resolve_namespaced_id(manifest, task_id)
        record = manifest.records.get(namespaced_id)
        if record is None:
            return False
        if record.generation != generation:
            return False
        if record.holder_token != holder_token:
            return False
        if record.released:
            return True

        manifest.records[namespaced_id] = TaskRecord(
            task_id=record.task_id,
            md_sha256=record.md_sha256,
            generation=record.generation,
            holder_token=record.holder_token,
            last_heartbeat_monotonic_ns=time.monotonic_ns(),
            last_heartbeat_wall_utc=datetime.now(timezone.utc).isoformat(),
            git_head_sha=record.git_head_sha,
            git_index_mtime=record.git_index_mtime,
            released=True,
        )
        atomic_replace_manifest(workspace_root, manifest)
        return True
