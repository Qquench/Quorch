# -*- coding: utf-8 -*-
"""Controlled Atomic Task Document Writer and Splitter Primitive for Quench DevTasks.

Provides bounded, fault-tolerant Markdown task file manipulation enforcing:
- Lossless roundtrip identity partition (preamble + blocks + epilogue)
- Status smuggling defense (new tasks must be in EDITABLE_STATES)
- Invariant transition defense (existing tasks cannot change status via writer)
- Non-editable task mutation and deletion defense
- Single Markdown filelock with non-blocking manifest verification
- Atomic tempfile + fsync + os.replace on disk
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import (
    Any,
    Dict,
    Final,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

import filelock

from task_status import (
    STATUS_PENDING,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_SKIPPED,
    STATUS_REWORK,
    STATUS_UNKNOWN,
    TASK_HEADER_PATTERN,
    ALL_STATUSES,
    normalize_status,
    is_task_file,
)
from path_guard import (
    assert_dir_contained,
    canonicalize_path,
    PathTraversalError,
)
from schema_validator import validate_task_schema
from manifest import load_manifest, register_proposal

logger = logging.getLogger(__name__)

EDITABLE_STATES: Final[frozenset[str]] = frozenset({STATUS_PENDING, STATUS_REWORK})


class InvalidTransitionError(RuntimeError):
    """Raised when an existing task status is modified via writer."""
    pass


class NonEditableTaskMutatedError(RuntimeError):
    """Raised when a non-editable task content is mutated during overwrite."""
    pass


class NonEditableTaskMissingError(RuntimeError):
    """Raised when an existing non-editable task is missing from overwrite payload."""
    pass


class DuplicateTaskIdError(ValueError):
    """Raised when a duplicate task ID is encountered in payload or append mode."""
    pass


class StatusSmugglingError(RuntimeError):
    """Raised when a new task is introduced with a non-editable status."""
    pass


class StatusManifestMismatchError(RuntimeError):
    """Raised when task status in markdown contradicts manifest record."""
    pass


class TaskFileLockTimeoutError(TimeoutError):
    """Raised when acquiring the task markdown filelock times out."""
    pass


class PersistTargetRequiredError(ValueError):
    """Raised when persist=True is specified without target task_file."""
    pass


class TaskNotFoundError(LookupError):
    """Raised when a targeted task ID does not exist."""
    pass


@dataclass(frozen=True)
class RawTaskBlock:
    task_id: str
    status: str
    start_offset: int
    end_offset: int
    raw_text: str


@dataclass(frozen=True)
class TaskDocument:
    preamble: str
    blocks: tuple[RawTaskBlock, ...]
    epilogue: str


def _render_task_markdown(task: Dict[str, Any]) -> str:
    """Render a single structured task dictionary into compliant Markdown snippet."""
    task_id = str(task.get("id") or task.get("task_id") or "1.0").strip()
    title = str(task.get("title") or "未命名任务").strip()
    raw_status = task.get("status") or STATUS_PENDING
    status = normalize_status(raw_status)
    if status == STATUS_UNKNOWN:
        status = raw_status
    is_draft = bool(task.get("draft"))

    if is_draft:
        lines = [
            f"### 任务 {task_id} {status} (草案) — {title}\n",
            "<!-- quench-task-meta: {\"draft\": true} -->\n\n",
            "#### 【涉及文件】\n",
            "```\n",
        ]
    else:
        lines = [
            f"### 任务 {task_id} {status} — {title}\n",
            "\n",
            "#### 【涉及文件】\n",
            "```\n",
        ]
    affected = task.get("affected_files", [])
    if isinstance(affected, list):
        for af in affected:
            lines.append(f"{af}\n")
    else:
        lines.append(f"{affected}\n")
    lines.append("```\n\n")

    lines.append("#### 【缺陷根因与修改目标】\n")
    lines.append("```\n")
    lines.append(f"{task.get('root_cause_and_goal', '无')}\n")
    lines.append("```\n\n")

    lines.append("#### 【目标签名与类型契约】\n")
    contracts = task.get("type_contracts", "无")
    if isinstance(contracts, list):
        contracts_str = "\n".join(contracts)
    else:
        contracts_str = str(contracts)
    lines.append("```\n")
    lines.append(f"{contracts_str}\n")
    lines.append("```\n\n")

    lines.append("#### 【分步改造指引】\n")
    steps = task.get("steps", [])
    if isinstance(steps, list):
        for s in steps:
            lines.append(f"{s}\n")
    else:
        lines.append(f"{steps}\n")
    lines.append("\n")

    lines.append("#### 【防御与边缘校验】\n")
    checks = task.get("defensive_checks", [])
    if isinstance(checks, list):
        for c in checks:
            lines.append(f"{c}\n")
    else:
        lines.append(f"{checks}\n")
    lines.append("\n")

    lines.append("#### 【DoD 验证命令】\n")
    lines.append("```bash\n")
    dod = task.get("dod_commands", "")
    if isinstance(dod, list):
        for d in dod:
            lines.append(f"{d}\n")
    else:
        lines.append(f"{dod}\n")
    lines.append("```\n\n---\n\n")

    return "".join(lines)


def split_task_document(text: str) -> TaskDocument:
    """Split markdown task text into preamble, tuple of RawTaskBlock, and epilogue.

    Guarantees partition invariant:
    preamble + "".join(b.raw_text for b in blocks) + epilogue == text
    """
    if not text:
        return TaskDocument(preamble="", blocks=(), epilogue="")

    in_fence_char: Optional[str] = None
    in_fence_len: int = 0

    header_indices: list[tuple[int, str, str]] = []

    offset = 0
    lines = text.splitlines(keepends=True)
    for line in lines:
        stripped_left = line.lstrip(" ")
        indent = len(line) - len(stripped_left)

        # Code block fence state machine
        if indent <= 3 and (stripped_left.startswith("```") or stripped_left.startswith("~~~")):
            fence_char = stripped_left[0]
            flen = len(stripped_left) - len(stripped_left.lstrip(fence_char))
            if in_fence_char is None:
                in_fence_char = fence_char
                in_fence_len = flen
                offset += len(line)
                continue
            elif in_fence_char == fence_char and flen >= in_fence_len:
                in_fence_char = None
                in_fence_len = 0
                offset += len(line)
                continue

        if in_fence_char is not None:
            offset += len(line)
            continue

        # Skip blockquotes
        if stripped_left.startswith(">"):
            offset += len(line)
            continue

        if stripped_left.startswith("###"):
            m_full = TASK_HEADER_PATTERN.match(stripped_left.rstrip("\r\n"))
            if m_full:
                t_id = m_full.group(1).strip()
                t_status = normalize_status(m_full.group(2).strip())
                header_indices.append((offset, t_id, t_status))
            else:
                m_prefix = re.match(r"^###\s+(?:任务|Task)\b", stripped_left, re.IGNORECASE)
                if m_prefix:
                    rem = stripped_left[m_prefix.end():].strip()
                    m_fallback = re.match(
                        r"^([0-9a-zA-Z\._\-]+)(?:\s*[:—\-]\s*(.*)|\s+([^:—\-\s]+)(?:\s*[:—\-]?\s*(.*))?)?$",
                        rem,
                    )
                    if m_fallback:
                        t_id = m_fallback.group(1).strip()
                        cand = m_fallback.group(3)
                        st = normalize_status(cand.strip()) if cand else STATUS_UNKNOWN
                        header_indices.append((offset, t_id, st))

        offset += len(line)

    if not header_indices:
        return TaskDocument(preamble=text, blocks=(), epilogue="")

    preamble = text[:header_indices[0][0]]
    blocks: list[RawTaskBlock] = []

    for idx, (start, tid, st) in enumerate(header_indices):
        if idx + 1 < len(header_indices):
            next_start = header_indices[idx + 1][0]
            raw = text[start:next_start]
            blocks.append(RawTaskBlock(
                task_id=tid,
                status=st,
                start_offset=start,
                end_offset=next_start,
                raw_text=raw,
            ))
        else:
            last_raw = text[start:]
            blocks.append(RawTaskBlock(
                task_id=tid,
                status=st,
                start_offset=start,
                end_offset=len(text),
                raw_text=last_raw,
            ))

    return TaskDocument(
        preamble=preamble,
        blocks=tuple(blocks),
        epilogue="",
    )


def compose_task_document(
    doc: TaskDocument,
    replaced: Mapping[str, str],
    appended: Sequence[str],
) -> str:
    """Compose TaskDocument into full text by replacing and appending blocks."""
    parts: list[str] = [doc.preamble]
    for b in doc.blocks:
        if b.task_id in replaced:
            parts.append(replaced[b.task_id])
        else:
            parts.append(b.raw_text)
    for app in appended:
        parts.append(app)
    parts.append(doc.epilogue)
    return "".join(parts)


def write_task_file_guarded(
    workspace_root: str,
    task_file_path: str,
    tasks_to_write: list[dict],
    mode: Literal["append", "overwrite", "upsert"] = "append",
    *,
    lock_timeout_s: float = 5.0,
    manifest_snapshot: Optional[Mapping[str, str]] = None,
) -> dict:
    """Controlled atomic task file writer with boundary defenses and state invariant guards.

    Args:
        workspace_root: Absolute root path of the managed workspace.
        task_file_path: Relative or absolute path to the .md task file.
        tasks_to_write: List of task dictionaries conforming to the six-core-field contract.
        mode: Writing mode ('append', 'overwrite', 'upsert').
        lock_timeout_s: Timeout in seconds for markdown filelock acquisition.
        manifest_snapshot: Optional pre-loaded manifest mapping task_id -> status.

    Returns:
        Structured contract dict: {"ok": bool, "mode": str, "task_file": str, "written": list, "skipped": list, "reason": Optional[str]}
    """
    if mode not in ("append", "overwrite", "upsert"):
        raise ValueError(f"Invalid mode '{mode}'. Must be one of: 'append', 'overwrite', 'upsert'")

    if not task_file_path or not str(task_file_path).strip():
        raise ValueError("task_file_path cannot be empty")

    # 1. 强制 docs/dev_tasks 目录受管约束与 .md 后缀核验
    dev_tasks_dir = os.path.join(workspace_root, "docs", "dev_tasks")
    assert_dir_contained(workspace_root, dev_tasks_dir)

    raw_norm = str(task_file_path).replace("\\", "/").strip()
    if not raw_norm.lower().endswith(".md"):
        raise ValueError(f"Task file must have .md extension: '{task_file_path}'")

    if os.path.isabs(task_file_path):
        abs_path = os.path.normpath(task_file_path)
    else:
        if "/" in raw_norm:
            abs_path = os.path.normpath(os.path.join(workspace_root, raw_norm))
        else:
            abs_path = os.path.normpath(os.path.join(dev_tasks_dir, raw_norm))

    can_rel = canonicalize_path(abs_path, base_dir=workspace_root)
    if not is_task_file(can_rel):
        raise PathTraversalError(f"Task file must reside within docs/dev_tasks: '{task_file_path}'")

    # 2. 读取 manifest 快照（必须在 Markdown 文件锁之前读取，锁内仅做比较杜绝反向锁死）
    if manifest_snapshot is None:
        try:
            m = load_manifest(workspace_root)
            file_stem = Path(abs_path).stem
            manifest_snapshot_map: dict[str, str] = {}
            for nid, rec in m.records.items():
                if nid.startswith(f"{file_stem}::"):
                    tid = nid.split("::", 1)[1]
                    if hasattr(rec, "status"):
                        manifest_snapshot_map[tid] = getattr(rec, "status")
            if manifest_snapshot_map:
                manifest_snapshot = manifest_snapshot_map
        except Exception as e:
            logger.warning(f"Manifest snapshot temporarily unavailable before lock: {e}")
            manifest_snapshot = None

    # 3. 校验写入有效负载内的重复 ID
    seen_ids = set()
    for t in tasks_to_write:
        tid = str(t.get("id") or "").strip()
        if not tid:
            raise ValueError("Every task in tasks_to_write must have a non-empty 'id'")
        if tid in seen_ids:
            raise DuplicateTaskIdError(f"Duplicate task ID '{tid}' in tasks_to_write payload")
        seen_ids.add(tid)

    # 4. 获取 Markdown 任务文件独占锁
    lock_path = abs_path + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock = filelock.FileLock(lock_path, timeout=lock_timeout_s)

    try:
        with lock:
            file_exists = os.path.isfile(abs_path)
            if not file_exists:
                # 文件不存在：初始化新任务单
                for t in tasks_to_write:
                    tid = str(t.get("id")).strip()
                    st = normalize_status(t.get("status") or STATUS_PENDING)
                    if st not in EDITABLE_STATES:
                        raise StatusSmugglingError(
                            f"New task '{tid}' has non-editable status '{st}'. "
                            f"Newly proposed tasks must start in EDITABLE_STATES ({sorted(EDITABLE_STATES)})."
                        )
                    val_res = validate_task_schema(t)
                    if not val_res.is_valid:
                        raise ValueError(f"Task '{tid}' schema validation failed: {val_res.errors}")

                header = [
                    f"# {Path(abs_path).stem} Development Tasks / 开发任务单\n\n",
                    "> **Execution Guidelines for AI Models / 执行模型须知**\n",
                    "> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order\n",
                    "> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件\n",
                    "> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串\n",
                    "> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions\n",
                    "> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`\n\n",
                    f"- **Created Date / 创建日期**：{date.today().isoformat()}\n\n",
                    "---\n\n",
                    "## Task List & Status / 任务清单与状态\n\n",
                ]
                rendered_blocks = "".join(_render_task_markdown(t) for t in tasks_to_write)
                full_content = "".join(header) + rendered_blocks

                dir_name = os.path.dirname(abs_path)
                fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_task_", suffix=".md")
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(full_content.encode("utf-8"))
                        f.flush()
                        os.fsync(f.fileno())

                    for attempt in range(3):
                        try:
                            os.replace(tmp_path, abs_path)
                            break
                        except OSError:
                            if attempt == 2:
                                raise
                            time.sleep(0.05)
                finally:
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass

                try:
                    for t in tasks_to_write:
                        register_proposal(workspace_root, task_id=str(t["id"]).strip(), md_path=abs_path)
                except Exception:
                    pass

                return {
                    "ok": True,
                    "mode": mode,
                    "task_file": abs_path,
                    "written": [str(t["id"]).strip() for t in tasks_to_write],
                    "skipped": [],
                    "reason": None,
                }

            # 文件已存在：读取原文、探测 BOM 与行结束符
            with open(abs_path, "rb") as f:
                raw_bytes = f.read()

            has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
            clean_bytes = raw_bytes[3:] if has_bom else raw_bytes
            orig_text = clean_bytes.decode("utf-8")
            newline = "\r\n" if "\r\n" in orig_text else "\n"

            doc = split_task_document(orig_text)
            existing_blocks = {b.task_id: b for b in doc.blocks}
            existing_statuses = {b.task_id: b.status for b in doc.blocks}

            # 5. Manifest 一致性核验（仅校验本次涉及任务 ID）
            if manifest_snapshot is not None:
                for t in tasks_to_write:
                    tid = str(t.get("id")).strip()
                    if tid in manifest_snapshot and tid in existing_statuses:
                        m_st = normalize_status(manifest_snapshot[tid])
                        d_st = normalize_status(existing_statuses[tid])
                        if m_st != d_st:
                            raise StatusManifestMismatchError(
                                f"Manifest status mismatch for task '{tid}': manifest status '{manifest_snapshot[tid]}' does not match "
                                f"document status '{existing_statuses[tid]}'."
                            )

            written: list[str] = []
            skipped: list[dict] = []
            replaced: dict[str, str] = {}
            appended: list[str] = []

            if mode == "append":
                for t in tasks_to_write:
                    tid = str(t.get("id")).strip()
                    if tid in existing_blocks:
                        raise DuplicateTaskIdError(
                            f"Task ID '{tid}' already exists in '{abs_path}'. "
                            f"Use mode='upsert' to modify existing tasks."
                        )
                    st = normalize_status(t.get("status") or STATUS_PENDING)
                    if st not in EDITABLE_STATES:
                        raise StatusSmugglingError(
                            f"Newly added task '{tid}' has non-editable status '{st}'. "
                            f"New tasks must start in EDITABLE_STATES ({sorted(EDITABLE_STATES)})."
                        )
                    val_res = validate_task_schema(t)
                    if not val_res.is_valid:
                        raise ValueError(f"Task '{tid}' schema validation failed: {val_res.errors}")

                    appended.append(_render_task_markdown(t))
                    written.append(tid)

            elif mode == "upsert":
                for t in tasks_to_write:
                    tid = str(t.get("id")).strip()
                    if tid in existing_blocks:
                        old_st = existing_statuses[tid]
                        if old_st in EDITABLE_STATES:
                            if "status" in t:
                                new_st = normalize_status(t["status"])
                                if new_st != old_st:
                                    raise InvalidTransitionError(
                                        f"Invalid status modification: cannot change status of task '{tid}' from '{old_st}' to '{new_st}' "
                                        f"via write_task_file_guarded. Use state machine tools instead."
                                    )
                            else:
                                t["status"] = old_st
                            val_res = validate_task_schema(t)
                            if not val_res.is_valid:
                                raise ValueError(f"Task '{tid}' schema validation failed: {val_res.errors}")

                            replaced[tid] = _render_task_markdown(t)
                            written.append(tid)
                        else:
                            # 命中非可编辑块则进 skipped(reason="non_editable") 且不抛错
                            skipped.append({
                                "id": tid,
                                "task_id": tid,
                                "status": old_st,
                                "reason": "non_editable",
                            })
                    else:
                        st = normalize_status(t.get("status") or STATUS_PENDING)
                        if st not in EDITABLE_STATES:
                            raise StatusSmugglingError(
                                f"Newly added task '{tid}' has non-editable status '{st}'. "
                                f"New tasks must start in EDITABLE_STATES ({sorted(EDITABLE_STATES)})."
                            )
                        val_res = validate_task_schema(t)
                        if not val_res.is_valid:
                            raise ValueError(f"Task '{tid}' schema validation failed: {val_res.errors}")

                        appended.append(_render_task_markdown(t))
                        written.append(tid)

            elif mode == "overwrite":
                payload_map = {str(t.get("id")).strip(): t for t in tasks_to_write}

                # a. 全量核验已有非可编辑任务必须在 payload 中完整存在
                for tid, old_st in existing_statuses.items():
                    if old_st not in EDITABLE_STATES:
                        if tid not in payload_map:
                            raise NonEditableTaskMissingError(
                                f"Existing non-editable task '{tid}' ({old_st}) is missing from overwrite payload."
                            )
                        target_dict = payload_map[tid]
                        if "status" in target_dict:
                            new_st = normalize_status(target_dict["status"])
                            if new_st != old_st:
                                raise InvalidTransitionError(
                                    f"Invalid status modification: cannot change status of non-editable task '{tid}' from '{old_st}' to '{new_st}'."
                                )
                        # 检查非可编辑块内容未篡改（归一化换行符以兼容跨平台差异）
                        rendered = _render_task_markdown(target_dict)
                        rendered_norm = rendered.strip().replace("\r\n", "\n")
                        old_raw_norm = existing_blocks[tid].raw_text.strip().replace("\r\n", "\n")
                        if rendered_norm != old_raw_norm:
                            raise NonEditableTaskMutatedError(
                                f"Cannot mutate content of non-editable task '{tid}' ({old_st})."
                            )

                # b. 检查新任务状态
                for tid, t in payload_map.items():
                    if tid not in existing_blocks:
                        st = normalize_status(t.get("status") or STATUS_PENDING)
                        if st not in EDITABLE_STATES:
                            raise StatusSmugglingError(
                                f"New task '{tid}' has non-editable status '{st}'. Must be in EDITABLE_STATES."
                            )
                    else:
                        old_st = existing_statuses[tid]
                        if "status" in t:
                            new_st = normalize_status(t["status"])
                            if new_st != old_st:
                                raise InvalidTransitionError(
                                    f"Invalid status modification: cannot change status of task '{tid}' from '{old_st}' to '{new_st}'."
                                )

                # c. 组装替换块与新增块
                for b in doc.blocks:
                    if b.task_id in payload_map:
                        t = payload_map[b.task_id]
                        if b.status in EDITABLE_STATES:
                            val_res = validate_task_schema(t)
                            if not val_res.is_valid:
                                raise ValueError(f"Task '{b.task_id}' schema validation failed: {val_res.errors}")
                            replaced[b.task_id] = _render_task_markdown(t)
                        else:
                            # 非可编辑块：原始切片逐字复用
                            replaced[b.task_id] = b.raw_text
                        written.append(b.task_id)
                    else:
                        # 移除已有可编辑任务
                        replaced[b.task_id] = ""

                for tid, t in payload_map.items():
                    if tid not in existing_blocks:
                        val_res = validate_task_schema(t)
                        if not val_res.is_valid:
                            raise ValueError(f"Task '{tid}' schema validation failed: {val_res.errors}")
                        appended.append(_render_task_markdown(t))
                        written.append(tid)

            # 6. 合成最终文档
            new_text = compose_task_document(doc, replaced=replaced, appended=appended)

            # 7. 原子落盘：tempfile + fsync + os.replace（保持原 newline 与 BOM）
            dir_name = os.path.dirname(abs_path)
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_task_", suffix=".md")
            try:
                with os.fdopen(fd, "wb") as f:
                    if newline == "\r\n":
                        formatted_text = new_text.replace("\r\n", "\n").replace("\n", "\r\n")
                    else:
                        formatted_text = new_text.replace("\r\n", "\n")

                    encoded_bytes = formatted_text.encode("utf-8")
                    if has_bom:
                        encoded_bytes = b"\xef\xbb\xbf" + encoded_bytes
                    f.write(encoded_bytes)
                    f.flush()
                    os.fsync(f.fileno())

                for attempt in range(3):
                    try:
                        os.replace(tmp_path, abs_path)
                        break
                    except OSError:
                        if attempt == 2:
                            raise
                        time.sleep(0.05)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

            try:
                for tid in written:
                    if tid not in existing_blocks:
                        register_proposal(workspace_root, task_id=tid, md_path=abs_path)
            except Exception:
                pass

            return {
                "ok": True,
                "mode": mode,
                "task_file": abs_path,
                "written": written,
                "skipped": skipped,
                "reason": None,
            }

    except filelock.Timeout:
        raise TaskFileLockTimeoutError(
            f"Timed out acquiring task file lock '{lock_path}' after {lock_timeout_s}s (timed out)"
        )
