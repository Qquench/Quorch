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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

MAX_DAILY_SEQUENCE: Final[int] = 999
SLUG_MAX_LEN: Final[int] = 20
HEADER_VERSION: Final[str] = "quench-reviewer-log v1"

_LOG_FILENAME_REGEX = re.compile(r"^(\d{8})_(\d{3})_([a-z0-9_]+)\.log$")

_WINDOWS_RESERVED_NAMES: Final[set[str]] = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


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
    if not os.path.isdir(target_dir):
        return []

    matched: list[str] = []
    for entry in os.listdir(target_dir):
        if _LOG_FILENAME_REGEX.match(entry):
            matched.append(entry)

    matched.sort()
    return matched


def gc_by_filename_order(
    directory: str | os.PathLike[str],
    *,
    keep: int = 20,
) -> list[str]:
    """Retain newest `keep` log files and prune older ones based purely on filename order.

    ZERO stat calls are made. Never deletes the latest active file.
    Also unlinks associated rotation backups (.1.log).
    """
    if keep <= 0:
        raise ValueError(f"keep must be greater than 0, got {keep}")

    target_dir = os.path.abspath(directory)
    files = list_log_files(target_dir)

    if len(files) <= keep:
        return []

    to_prune = files[:-keep]
    pruned: list[str] = []

    for fname in to_prune:
        fpath = os.path.join(target_dir, fname)
        try:
            if os.path.exists(fpath):
                os.remove(fpath)
                pruned.append(fname)
            # Cascade delete rotation backup if present
            rot_path = os.path.splitext(fpath)[0] + ".1.log"
            if os.path.exists(rot_path):
                os.remove(rot_path)
        except OSError:
            pass

    return pruned
