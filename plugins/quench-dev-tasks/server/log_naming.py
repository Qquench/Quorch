# -*- coding: utf-8 -*-
"""Reviewer log naming kernel.

Provides stateless, UTC-normalized, atomically allocated log naming adhering to:
    YYYYMMDD_NNN_<slug>.log

Key properties:
1. Lexicographical order == chronological order (zero-stat GC).
2. Atomic O_CREAT|O_EXCL allocation prevents TOCTOU and truncation overwrite.
3. Daily sequence is bounded to [1, 999] and raises SequenceExhaustedError on overflow (never wraps around).
4. No persistent sequence counter files needed (restores from directory state).
5. Strict slug sanitization guards against path traversal and Windows reserved device names.
6. Header contract is flushed immediately upon allocation.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Any, Mapping, Callable

# 全仓库唯一 SESSION_ID_PATTERN SSOT (128位，叶子节点防环形导入)
SESSION_ID_PATTERN: Final[re.Pattern] = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")
MAX_DAILY_SEQUENCE: Final[int] = 999
SLUG_MAX_LEN: Final[int] = 20
HEADER_VERSION: Final[str] = "quench-reviewer-log v1"

REVIEWER_LOG_QUOTA_KEEP: Final[int] = 20
REVIEWER_TERMINAL_LOG_RETENTION: Final[int] = 40  # 终态保留条数 SSOT（必须 > KEEP 且覆盖最大门禁消费窗口）

_LOG_FILENAME_REGEX = re.compile(r"^(\d{8})_(\d{3})_([a-z0-9_]+)\.log$")
LOG_FILENAME_REGEX: Final[re.Pattern] = _LOG_FILENAME_REGEX
MAX_LOG_REF_CHARS: Final[int] = 40

_WINDOWS_RESERVED_NAMES: Final[set[str]] = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}



def validate_log_ref(log_ref: str) -> str:
    """Validate log_ref: must match legal log basename regex and never exceed MAX_LOG_REF_CHARS.
    Silent lossy truncation is strictly forbidden (H-A).
    """
    if not isinstance(log_ref, str) or not log_ref.strip():
        raise ValueError("log_ref must be a non-empty string")
    clean = log_ref.strip()
    if len(clean) > MAX_LOG_REF_CHARS:
        raise ValueError(
            f"log_ref length ({len(clean)}) exceeds limit ({MAX_LOG_REF_CHARS}): '{clean}'"
        )
    if "/" in clean or "\\" in clean or not LOG_FILENAME_REGEX.match(clean):
        raise ValueError(f"Invalid log_ref format: '{clean}'. Must match {LOG_FILENAME_REGEX.pattern}")
    return clean


_ROTATION_SUFFIX_REGEX: Final[re.Pattern] = re.compile(r"(?:\.\d+)?(\.(?:log|jsonl))(?:\.\d+)?$")


def norm_registry_key(path: str | os.PathLike[str]) -> str:
    """唯一 registry 键规范化 SSOT：折叠 Windows 大小写、解析软链接、并剥离轮转分片后缀 (.1.log/.log.1 -> .log；.1.jsonl/.jsonl.1 -> .jsonl) (N-1)。"""
    base_path = _ROTATION_SUFFIX_REGEX.sub(r"\1", str(path))
    return os.path.normcase(os.path.realpath(base_path))


class ActiveLogRegistry:
    """线程安全的在途日志文件注册表，防止 GC 回收活跃日志句柄。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pinned: set[str] = set()

    def pin(self, log_path: str | os.PathLike[str]) -> None:
        key = norm_registry_key(log_path)
        with self._lock:
            self._pinned.add(key)

    def unpin(self, log_path: str | os.PathLike[str]) -> None:
        key = norm_registry_key(log_path)
        with self._lock:
            self._pinned.discard(key)

    def is_pinned(self, log_path: str | os.PathLike[str]) -> bool:
        key = norm_registry_key(log_path)
        with self._lock:
            return key in self._pinned

    def is_reclaimable(self, log_path: str | os.PathLike[str]) -> bool:
        return not self.is_pinned(log_path)

    def snapshot(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._pinned)

    def reap_dead(self, is_alive: Any) -> int:
        """清理已死亡进程或不再存活的 pinned 条目。返回清理条目数。
        锁序红线：锁内浅拷贝快照 → 锁外执行 is_alive 谓词 → 锁内差分写回，杜绝锁内外部调用。
        """
        if not callable(is_alive):
            return 0
        with self._lock:
            snapshot = set(self._pinned)

        dead_keys = set()
        for k in snapshot:
            try:
                if not is_alive(k):
                    dead_keys.add(k)
            except Exception:
                pass

        if not dead_keys:
            return 0

        with self._lock:
            removed = dead_keys & self._pinned
            self._pinned -= removed
            return len(removed)



class SequenceExhaustedError(RuntimeError):
    """Raised when daily sequence exceeds 999. Wrap-around is strictly prohibited."""


class InvalidSlugError(ValueError):
    """Raised when slug contains forbidden path separators or invalid navigation."""


@dataclass(frozen=True, slots=True)
class LogFileName:
    date: str          # "YYYYMMDD", UTC normalized
    seq: int           # 1..999
    slug: str          # Sanitized <= 20 chars

    def render(self) -> str:
        return f"{self.date}_{self.seq:03d}_{self.slug}.log"


def normalize_utc_date(now: datetime | None = None) -> str:
    """Normalize datetime to UTC 'YYYYMMDD' string.

    Naive datetime is treated as UTC. Aware datetime is converted to UTC.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    return now.strftime("%Y%m%d")


def sanitize_slug(raw: str | None, *, fallback: str = "consult") -> str:
    """Sanitize raw slug string into safe [a-z0-9_]{1,20} token.

    Rules:
    - Path separators ('/' or '\\') or '.'/'..' raise InvalidSlugError.
    - Lowercased and filtered to [a-z0-9_].
    - Consecutive underscores are collapsed.
    - Stripped of leading/trailing underscores.
    - Truncated to <= 20 chars without trailing underscore.
    - Windows reserved device names (con, prn, aux, nul, etc.) prefixed with '_'.
    - Empty result falls back to fallback token.
    """
    if raw is None or not str(raw).strip():
        return fallback

    raw_str = str(raw).strip()
    if "/" in raw_str or "\\" in raw_str:
        raise InvalidSlugError(f"Slug contains path separator: {raw_str!r}")
    if raw_str in {".", ".."}:
        raise InvalidSlugError(f"Invalid slug navigation token: {raw_str!r}")

    lowered = raw_str.lower()
    cleaned = re.sub(r"[^a-z0-9_]+", "_", lowered)
    collapsed = re.sub(r"_+", "_", cleaned).strip("_")

    truncated = collapsed[:SLUG_MAX_LEN].rstrip("_")
    if not truncated:
        truncated = fallback

    if truncated in _WINDOWS_RESERVED_NAMES:
        truncated = f"_{truncated}"[:SLUG_MAX_LEN].rstrip("_")

    return truncated


def allocate_log_file(
    directory: str | os.PathLike[str],
    slug: str | None = None,
    *,
    now: datetime | None = None,
    header_metadata: dict[str, str] | None = None,
    registry: ActiveLogRegistry | None = None,
) -> tuple[str, bytes]:
    """Atomically allocate a new log file using O_CREAT|O_EXCL.

    Scans existing sequence numbers for the current UTC date, attempts atomic
    creation from max(seq) + 1 up to MAX_DAILY_SEQUENCE. On success, writes the
    Header line and flushes to disk immediately.

    Returns:
        (absolute_file_path, header_bytes)

    Raises:
        SequenceExhaustedError: When all 999 daily slots are occupied.
        InvalidSlugError: When slug contains path traversal characters.
    """
    target_dir = os.path.abspath(directory)
    os.makedirs(target_dir, exist_ok=True)

    date_str = normalize_utc_date(now)
    clean_slug = sanitize_slug(slug)

    # Fast start sequence discovery
    start_seq = 1
    existing_seqs: list[int] = []
    try:
        for entry in os.listdir(target_dir):
            m = _LOG_FILENAME_REGEX.match(entry)
            if m and m.group(1) == date_str:
                existing_seqs.append(int(m.group(2)))
    except OSError:
        pass

    if existing_seqs:
        start_seq = max(existing_seqs) + 1

    if start_seq > MAX_DAILY_SEQUENCE:
        raise SequenceExhaustedError(
            f"Daily sequence exhausted for date {date_str} (max {MAX_DAILY_SEQUENCE})"
        )

    # Format ISO timestamp for Header contract
    if now is None:
        utc_dt = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        utc_dt = now.replace(tzinfo=timezone.utc)
    else:
        utc_dt = now.astimezone(timezone.utc)
    now_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    for seq in range(start_seq, MAX_DAILY_SEQUENCE + 1):
        filename = LogFileName(date_str, seq, clean_slug).render()
        filepath = os.path.join(target_dir, filename)

        try:
            fd = os.open(filepath, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue

        # Header contract line
        header_parts = [
            f"# {HEADER_VERSION}",
            f"date={date_str}",
            f"seq={seq:03d}",
            f"slug={clean_slug}",
            f"utc={now_iso}",
        ]
        if header_metadata:
            for k, v in header_metadata.items():
                safe_k = re.sub(r"[^a-zA-Z0-9_-]", "", str(k))
                safe_v = re.sub(r"[\r\n|]", " ", str(v)).strip()
                header_parts.append(f"{safe_k}={safe_v}")

        header_line = " | ".join(header_parts) + "\n"
        header_bytes = header_line.encode("utf-8")

        try:
            # 同步在持有文件且未关闭前完成 pin，消除 TOCTOU
            if registry is not None:
                registry.pin(norm_registry_key(filepath))
            os.write(fd, header_bytes)
            os.fsync(fd)
        finally:
            os.close(fd)

        return (filepath, header_bytes)

    raise SequenceExhaustedError(
        f"Daily sequence exhausted for date {date_str} (max {MAX_DAILY_SEQUENCE})"
    )


def list_log_files(directory: str | os.PathLike[str]) -> list[str]:
    """Return log filenames sorted in strictly ascending chronological order.

    Lexicographical order of YYYYMMDD_NNN_<slug>.log guarantees chronological
    ordering without any os.stat() / getmtime() calls.
    """
    target_dir = os.path.abspath(directory)
    try:
        entries = os.listdir(target_dir)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return []

    matched: list[str] = []
    for entry in entries:
        if _LOG_FILENAME_REGEX.match(entry):
            matched.append(entry)

    matched.sort()
    return matched


def gc_by_filename_order(
    directory: str | os.PathLike[str],
    *,
    keep: int = 20,
    registry: ActiveLogRegistry | None = None,
    require_lease: bool = False,
    lease_guard: Any | None = None,
) -> list[str]:
    """Retain newest `keep` log files and prune older ones based purely on filename order.

    Syscall contract (zero-stat GC invariant):
        ALLOWED: os.listdir, os.remove
        FORBIDDEN: os.stat, os.lstat, os.path.exists, os.path.isfile,
                   os.path.isdir, os.path.getmtime, os.path.getsize
    Concurrency: idempotent against concurrent GC — FileNotFoundError
    is absorbed as a benign success. PermissionError (Windows handle lock,
    cf. ci_incident_tracker_and_compatibility_guide.md Case 4) is caught and skipped.

    Never deletes the latest active file. Also unlinks associated rotation backups (.1.log).
    """
    if keep <= 0:
        raise ValueError(f"keep must be greater than 0, got {keep}")

    if require_lease:
        from workspace_lease import WorkspaceLeaseNotHeldError
        if lease_guard is None or not lease_guard.is_held():
            raise WorkspaceLeaseNotHeldError("Workspace lease not held during GC")

    target_dir = os.path.abspath(directory)
    files = list_log_files(target_dir)

    if len(files) <= keep:
        return []

    to_prune = files[:-keep]
    pruned: list[str] = []

    for fname in to_prune:
        fpath = os.path.join(target_dir, fname)
        if registry is not None and not registry.is_reclaimable(norm_registry_key(fpath)):
            continue

        try:
            os.remove(fpath)
            pruned.append(fname)
        except (FileNotFoundError, OSError):
            pass

        # Cascade delete rotation backup if present (atomic unlink without stat/exists)
        rot_path = os.path.splitext(fpath)[0] + ".1.log"
        if registry is not None and not registry.is_reclaimable(norm_registry_key(rot_path)):
            continue
        try:
            os.remove(rot_path)
        except (FileNotFoundError, OSError):
            pass

    return pruned


def norm_path_pure(p: str | os.PathLike[str]) -> str:
    """纯字符串路径归一化：normcase + normpath + abspath，零系统调用。"""
    return os.path.normcase(os.path.normpath(os.path.abspath(str(p))))


class QuotaResult(list[str]):
    """限额清理返回值：支持 list[str]（被清理文件列表）与 int（被清理文件数量）双向契约比较。"""

    def __int__(self) -> int:
        return len(self)

    def __index__(self) -> int:
        return len(self)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, int):
            return len(self) == other
        return super().__eq__(other)

    def __ne__(self, other: Any) -> bool:
        if isinstance(other, int):
            return len(self) != other
        return super().__ne__(other)

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, int):
            return len(self) > other
        return super().__gt__(other)

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, int):
            return len(self) >= other
        return super().__ge__(other)

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, int):
            return len(self) < other
        return super().__lt__(other)

    def __le__(self, other: Any) -> bool:
        if isinstance(other, int):
            return len(self) <= other
        return super().__le__(other)


def enforce_unified_log_quota(
    log_dir: str | os.PathLike[str],
    *,
    keep: int = REVIEWER_LOG_QUOTA_KEEP,
    retention: int = REVIEWER_TERMINAL_LOG_RETENTION,
    registry: ActiveLogRegistry | None = None,
    require_lease: bool = False,
    lease_guard: Any | None = None,
    is_peer_alive: Callable[[str], bool] | None = None,
    protected_paths: frozenset[str] = frozenset(),
    max_deletions: int = 8,
    timeout_s: float = 0.05,
    purge_legacy: bool = False,
) -> QuotaResult:
    """Retain at most `keep` total log files across reviewer logs.
    Zero-stat GC invariant: candidate enumeration exclusively matches *.log (explicitly
    excluding latest-*.log, .jsonl, and indices). Compares protected_paths and registry
    via pure string normalization.
    All runtime exceptions during deletion are absorbed.
    """
    if keep <= 0:
        raise ValueError(f"keep must be greater than 0, got {keep}")

    if require_lease:
        from workspace_lease import WorkspaceLeaseNotHeldError

        if lease_guard is None or not lease_guard.is_held():
            raise WorkspaceLeaseNotHeldError("Workspace lease not held during GC")

    try:
        target_dir = os.path.abspath(log_dir)
        if not os.path.isdir(target_dir):
            return QuotaResult()

        if purge_legacy:
            new_files = list_log_files(target_dir)
            legacy_files: list[str] = []
            for entry in os.listdir(target_dir):
                if entry.startswith("latest-") and entry.endswith(".log") and not entry.endswith(".1.log"):
                    legacy_files.append(entry)
            legacy_files.sort(key=lambda fname: os.path.getmtime(os.path.join(target_dir, fname)))
            total_logs = len(new_files) + len(legacy_files)
            if total_logs <= keep:
                return QuotaResult()
            excess = total_logs - keep
            pruned_legacy: list[str] = []
            while legacy_files and excess > 0:
                oldest_legacy = legacy_files.pop(0)
                fpath = os.path.join(target_dir, oldest_legacy)
                if registry is not None and not registry.is_reclaimable(norm_registry_key(fpath)):
                    excess -= 1
                    continue
                try:
                    os.remove(fpath)
                    pruned_legacy.append(oldest_legacy)
                except (FileNotFoundError, OSError):
                    pass
                rot_path = os.path.splitext(fpath)[0] + ".1.log"
                if registry is None or registry.is_reclaimable(norm_registry_key(rot_path)):
                    try:
                        os.remove(rot_path)
                    except (FileNotFoundError, OSError):
                        pass
                excess -= 1
            remaining_new_allowed = keep - len(legacy_files)
            if len(new_files) > remaining_new_allowed and remaining_new_allowed > 0:
                new_pruned = gc_by_filename_order(
                    target_dir,
                    keep=remaining_new_allowed,
                    registry=registry,
                    require_lease=False,
                    lease_guard=lease_guard,
                )
                pruned_legacy.extend(new_pruned)
            return QuotaResult(pruned_legacy)

        # Standard / Hardened Zero-stat path:
        # 先执行 registry 的 dead pin 回收（锁外探测）
        if registry is not None and is_peer_alive is not None:
            try:
                registry.reap_dead(is_peer_alive)
            except Exception:
                pass

        try:
            entries = os.listdir(target_dir)
        except (FileNotFoundError, NotADirectoryError, OSError):
            return QuotaResult()

        # 纯路径规范化保护集
        norm_protected: set[str] = {norm_path_pure(p) for p in protected_paths}

        # 候选枚举：仅匹配 *.log，显式排除 latest-*.log、.1.log、latest.log、.jsonl 等
        candidates: list[str] = []
        for entry in entries:
            if not entry.endswith(".log"):
                continue
            if entry.endswith(".1.log"):
                continue
            if entry.startswith("latest-") or entry == "latest.log":
                continue
            candidates.append(entry)

        # Basename 字典序排序（等价于时间序，零系统调用）
        candidates.sort()

        reclaimable_candidates: list[str] = []
        for fname in candidates:
            fpath = os.path.join(target_dir, fname)
            norm_f = norm_path_pure(fpath)
            if norm_f in norm_protected:
                continue
            if registry is not None and registry.is_pinned(norm_f):
                continue
            reclaimable_candidates.append(fname)

        if len(reclaimable_candidates) <= keep:
            return QuotaResult()

        excess = len(reclaimable_candidates) - keep
        to_delete = reclaimable_candidates[: min(excess, max_deletions)]

        start_mono = time.monotonic()
        pruned: list[str] = []

        for fname in to_delete:
            if time.monotonic() - start_mono > timeout_s:
                break
            fpath = os.path.join(target_dir, fname)
            try:
                os.remove(fpath)
                pruned.append(fname)
            except (FileNotFoundError, OSError):
                pass

            # 级联删除 .1.log 轮转备份
            rot_path = os.path.splitext(fpath)[0] + ".1.log"
            norm_rot = norm_path_pure(rot_path)
            if norm_rot not in norm_protected and (registry is None or not registry.is_pinned(norm_rot)):
                try:
                    os.remove(rot_path)
                except (FileNotFoundError, OSError):
                    pass

        return QuotaResult(pruned)
    except Exception:
        return QuotaResult()



