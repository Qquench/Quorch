# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Task status SSOT and header scanning module.
Lightweight module with ZERO heavy dependencies (no filelock, manifest, fastmcp, yaml).

Note on STATUS_REVOKED:
Per Quench architecture, `dev_tasks_confirm(action="revoke")` reverts tasks back to `STATUS_PENDING`.
There is no dedicated `STATUS_REVOKED` constant on disk in state_machine.py.
Any unrecognized or legacy revoked emoji is classified as STATUS_UNKNOWN.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Final, Mapping, Pattern, Optional

# --- Canonical Status Constants (Disk truth aligned with state_machine.py) ---
STATUS_PENDING: Final[str] = "⬜ 待确认"
STATUS_CONFIRMED: Final[str] = "✅ 已确认"
STATUS_IN_PROGRESS: Final[str] = "🔨 执行中"
STATUS_COMPLETED: Final[str] = "✔️ 已完成"
STATUS_SKIPPED: Final[str] = "⏭️ 跳过"
STATUS_REWORK: Final[str] = "🔄 需返工"

ALL_STATUSES: Final[tuple[str, ...]] = (
    STATUS_PENDING,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_SKIPPED,
    STATUS_REWORK,
)

# Pure ASCII sentinel for drift / unknown status. Never use emojis to avoid masking diffs.
STATUS_UNKNOWN: Final[str] = "?? UNKNOWN"

TASK_FILE_RELATIVE_DIR: Final[str] = "docs/dev_tasks"

# Emoji status options sorted by length descending for regex safety
EMOJI_STATUS_OPTIONS: Final[tuple[str, ...]] = (
    r"⬜\s*(?:待确认|Pending)",
    r"✅\s*(?:已确认|Confirmed)",
    r"🔨\s*(?:执行中|In[-_ ]?Progress)",
    r"✔️\s*(?:已完成|Completed)",
    r"✔\s*(?:已完成|Completed)",
    r"⏭️\s*(?:跳过|Skipped)",
    r"⏭\s*(?:跳过|Skipped)",
    r"🔄\s*(?:需返工|Rework)",
    r"In[-_ ]?Progress",
    r"待确认",
    r"已确认",
    r"执行中",
    r"已完成",
    r"跳过",
    r"需返工",
    r"Pending",
    r"Confirmed",
    r"Completed",
    r"Skipped",
    r"Rework",
)

STATUS_REGEX_PART: Final[str] = "|".join(EMOJI_STATUS_OPTIONS)

TASK_HEADER_PATTERN: Final[Pattern[str]] = re.compile(
    rf"^###\s+(?:任务|Task)\s+([0-9a-zA-Z\._\-]+)\s*[:—\-]?\s*({STATUS_REGEX_PART})\s*[:—\-]?\s*(.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TaskHeaderScan:
    """Immutable scan result of task headers across a task document."""
    statuses_ordered: tuple[tuple[str, str], ...]   # Preserves order: ((task_id, normalized_status), ...)
    occurrence_counts: Mapping[str, int]            # task_id -> occurrence count
    malformed_ids: frozenset[str]                   # Task IDs or headers that failed total-order parsing

    @property
    def statuses(self) -> Mapping[str, str]:
        """Last-wins dictionary view for backwards compatibility."""
        return dict(self.statuses_ordered)

    @property
    def duplicates(self) -> frozenset[str]:
        """Set of task_ids appearing strictly more than once."""
        return frozenset(t for t, c in self.occurrence_counts.items() if c > 1)


def normalize_status(raw: str) -> str:
    """Normalize raw status string to canonical status or STATUS_UNKNOWN.
    Handles Unicode Variation Selector-16 (\\ufe0f), full/half-width spaces, and English aliases.
    """
    if not raw or not raw.strip():
        return STATUS_UNKNOWN

    s = raw.strip().replace("\ufe0f", "")
    s_clean = re.sub(r"\s+", " ", s)
    s_compact = s_clean.replace(" ", "")

    for standard in ALL_STATUSES:
        std_clean = standard.replace("\ufe0f", "")
        std_compact = std_clean.replace(" ", "")
        if std_compact in s_compact:
            return standard
        # Key suffix check (e.g. "待确认", "已完成")
        key = standard.split(" ")[-1]
        if key in s_clean:
            return standard

    # English aliases check
    s_lower = s_clean.lower()
    if "pending" in s_lower:
        return STATUS_PENDING
    if "confirmed" in s_lower:
        return STATUS_CONFIRMED
    if "progress" in s_lower:
        return STATUS_IN_PROGRESS
    if "completed" in s_lower or "done" in s_lower:
        return STATUS_COMPLETED
    if "skipped" in s_lower or "skip" in s_lower:
        return STATUS_SKIPPED
    if "rework" in s_lower:
        return STATUS_REWORK

    return STATUS_UNKNOWN


def extract_header_task_statuses(content: str) -> TaskHeaderScan:
    """Fence-aware and blockquote-aware extractor for task headers in Markdown content.
    
    Total order classification rules for lines:
    1. Line not starting with '^###' -> Ignore
    2. '^###' but does not start with prefix '### 任务' / '### Task' -> Ignore
    3. Prefix matches but task ID is missing/blank -> add to malformed_ids
    4. Task ID exists but status field missing -> add to malformed_ids
    5. Task ID & status field exist, status not in ALL_STATUSES -> status is STATUS_UNKNOWN
    6. Repeated task IDs: all recorded in statuses_ordered, counted in occurrence_counts, last-wins in .statuses
    """
    if not content:
        return TaskHeaderScan(statuses_ordered=(), occurrence_counts={}, malformed_ids=frozenset())

    statuses_ordered: list[tuple[str, str]] = []
    counts: Counter[str] = Counter()
    malformed: set[str] = set()

    in_fence_char: Optional[str] = None
    in_fence_len: int = 0

    lines = content.splitlines()
    for line in lines:
        stripped_left = line.lstrip(" ")
        indent = len(line) - len(stripped_left)

        # Code block fence state machine
        if indent <= 3 and (stripped_left.startswith("```") or stripped_left.startswith("~~~")):
            fence_char = stripped_left[0]
            # Count consecutive fence characters
            flen = len(stripped_left) - len(stripped_left.lstrip(fence_char))
            if in_fence_char is None:
                in_fence_char = fence_char
                in_fence_len = flen
                continue
            elif in_fence_char == fence_char and flen >= in_fence_len:
                in_fence_char = None
                in_fence_len = 0
                continue

        if in_fence_char is not None:
            # Inside code fence: skip completely
            continue

        # Skip blockquotes
        if stripped_left.startswith(">"):
            continue

        # Rule 1 & 2: Header classification
        if not stripped_left.startswith("###"):
            continue

        m_prefix = re.match(r"^###\s+(?:任务|Task)\b", stripped_left, re.IGNORECASE)
        if not m_prefix:
            continue

        # Extract everything after "### 任务" / "### Task"
        remainder = stripped_left[m_prefix.end():].strip()
        if not remainder:
            malformed.add("missing_id")
            continue

        # Check if remainder immediately starts with a status token (i.e. task ID omitted)
        # e.g., "### 任务 ⬜ 待确认 — T"
        first_token = remainder.split()[0]
        first_norm = normalize_status(first_token)
        if first_norm != STATUS_UNKNOWN or any(first_token.startswith(s.split()[0]) for s in ALL_STATUSES):
            malformed.add("missing_id")
            continue

        # Standard pattern matching: id, status, rest
        m_full = TASK_HEADER_PATTERN.match(stripped_left)
        if m_full:
            task_id = m_full.group(1).strip()
            raw_status = m_full.group(2).strip()
            norm = normalize_status(raw_status)
            statuses_ordered.append((task_id, norm))
            counts[task_id] += 1
            continue

        # Fallback parse to classify malformed vs unknown status
        # Example 1: "1.3 — 缺失状态" -> task_id="1.3", title="缺失状态", status is missing -> malformed.add("1.3")
        # Example 2: "1.3" -> task_id="1.3", status is missing -> malformed.add("1.3")
        # Example 3: "1.3 ❓未知 — 标题" -> task_id="1.3", status="❓未知" -> status is STATUS_UNKNOWN
        # Example 4: "1.3 ❓未知" -> task_id="1.3", status="❓未知" -> status is STATUS_UNKNOWN
        m_fallback = re.match(
            r"^([0-9a-zA-Z\._\-]+)(?:\s*[:—\-]\s*(.*)|\s+([^:—\-\s]+)(?:\s*[:—\-]?\s*(.*))?)?$",
            remainder,
        )
        if not m_fallback:
            malformed.add("missing_id")
            continue

        task_id = m_fallback.group(1).strip()
        status_candidate = m_fallback.group(3)
        if not status_candidate or not status_candidate.strip():
            # ID exists but status field missing
            malformed.add(task_id)
            continue

        norm = normalize_status(status_candidate.strip())
        statuses_ordered.append((task_id, norm))
        counts[task_id] += 1

    return TaskHeaderScan(
        statuses_ordered=tuple(statuses_ordered),
        occurrence_counts=dict(counts),
        malformed_ids=frozenset(malformed),
    )


def is_task_file(rel_path: str) -> bool:
    """Normalize and verify if relative path belongs to governed task directory (docs/dev_tasks).
    - Normalizes separators (os.sep and slash)
    - Rejects path traversal ('..')
    - Rejects root directory itself ('docs/dev_tasks')
    - Requires .md extension (case-insensitive)
    - Excludes 'readme.md'
    """
    if not rel_path or not isinstance(rel_path, str):
        return False

    norm = rel_path.replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]

    parts = [p for p in norm.split("/") if p]
    if ".." in parts:
        return False

    norm_lower = norm.lower()
    if not norm_lower.endswith(".md"):
        return False

    if os.path.basename(norm_lower) == "readme.md":
        return False

    # Must be under docs/dev_tasks/ with at least one file segment
    if len(parts) >= 3 and parts[0].lower() == "docs" and parts[1].lower() == "dev_tasks":
        return True

    return False
