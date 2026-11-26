#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import glob
import io
import json
import logging
import logging.handlers
import os
import re
import sys
from typing import Any, Optional, List, Tuple, Pattern, Final
from collections import Counter

# 保证能加载上级 server 模块
current_dir = os.path.dirname(os.path.abspath(__file__))
server_dir = os.path.dirname(current_dir)
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from task_status import (
    STATUS_PENDING,
    STATUS_REWORK,
    STATUS_UNKNOWN,
    TaskHeaderScan,
    extract_header_task_statuses,
)

if sys.version_info >= (3, 7):
    try:
        for _stream in (sys.stdin, sys.stdout, sys.stderr):
            if isinstance(_stream, io.TextIOWrapper):
                _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Windows 安全轮转：轮转失败时保持当前文件继续写入，不中断日志流。"""
    def doRollover(self):
        try:
            super().doRollover()
        except (PermissionError, OSError):
            # 轮转失败（Windows 多进程竞争），继续使用当前日志文件
            if self.stream is None:
                try:
                    self.stream = self._open()
                except Exception:
                    pass


_LOGGER_CACHE: dict[str, logging.Logger] = {}


def get_hook_logger(workspace_root: str) -> logging.Logger:
    """初始化并缓存基于 workspace_root/.agents/.quench_hook.log 的轮转日志记录器。
    使用 SafeRotatingFileHandler 保障 Windows 多进程安全。
    若 .agents 目录不可写，降级为 NullHandler（仅在初始化阶段）。
    """
    if not workspace_root:
        null_logger = logging.getLogger("quench.hook.null")
        if not null_logger.handlers:
            null_logger.addHandler(logging.NullHandler())
        return null_logger

    norm_root = os.path.normcase(os.path.normpath(workspace_root))
    if norm_root in _LOGGER_CACHE:
        return _LOGGER_CACHE[norm_root]

    logger_name = f"quench.hook.{abs(hash(norm_root))}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    agents_dir = os.path.join(workspace_root, ".agents")
    log_file = os.path.join(agents_dir, ".quench_hook.log")

    try:
        os.makedirs(agents_dir, exist_ok=True)
        handler = SafeRotatingFileHandler(
            log_file,
            maxBytes=1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    except (PermissionError, OSError, Exception):
        logger.addHandler(logging.NullHandler())

    _LOGGER_CACHE[norm_root] = logger
    return logger


def log_guard_event(
    logger: logging.Logger,
    event_type: str,  # "ALLOW", "DENIED", "ASK_MODAL", "BYPASS_CLEAN", "EXCEPTION"
    target_file: str,
    tool_name: str,
    decision: str,
    reason: str = "",
    session_id: Optional[str] = None,
) -> None:
    """记录结构化 Hook 治理决策事件。"""
    if not logger:
        return
    try:
        clean_reason = reason.replace("\r", " ").replace("\n", " ").strip() if reason else ""
        clean_target = target_file.replace("\r", " ").replace("\n", " ").strip() if target_file else ""
        sess = session_id.strip() if session_id else "none"
        msg = f"[{event_type}] decision={decision} tool={tool_name} target={clean_target} session={sess}"
        if clean_reason:
            msg += f" reason={clean_reason}"

        if event_type in ("EXCEPTION", "DENIED"):
            logger.warning(msg)
        else:
            logger.info(msg)
    except Exception:
        pass


def _match_segmented_glob(target_path: str, norm_pattern: str) -> bool:
    """路径段感知的递归 Glob 匹配纯函数：'**' 匹配 0 个或多个完整路径段，非 '**' 段通过 fnmatchcase 匹配单段。"""
    path_parts = [p for p in target_path.replace("\\", "/").lower().strip("/").split("/") if p]
    raw_pat_parts = [p for p in norm_pattern.replace("\\", "/").lower().strip("/").split("/") if p]
    if not raw_pat_parts:
        return not path_parts

    pat_parts: List[str] = []
    for part in raw_pat_parts:
        if part == "**" and pat_parts and pat_parts[-1] == "**":
            continue
        pat_parts.append(part)

    n_pat = len(pat_parts)
    n_path = len(path_parts)
    memo: dict[Tuple[int, int], bool] = {}

    def _dp(i: int, j: int) -> bool:
        state = (i, j)
        if state in memo:
            return memo[state]
        if i == n_pat:
            res = j == n_path
        elif pat_parts[i] == "**":
            res = _dp(i + 1, j) or (j < n_path and _dp(i, j + 1))
        else:
            res = (
                j < n_path
                and fnmatch.fnmatchcase(path_parts[j], pat_parts[i])
                and _dp(i + 1, j + 1)
            )
        memo[state] = res
        return res

    return _dp(0, 0)


def matches_pattern(target_file: str, pattern: str, workspace_root: str) -> bool:
    """检查文件是否符合 Glob 规则（支持文件名通配、路径前缀通配与多段 ** 路径段递归通配）。"""
    if not target_file or not pattern:
        return False
    pattern_str = pattern.strip()

    raw_target = target_file.replace("\\", "/")
    is_abs_target = (
        os.path.isabs(target_file)
        or raw_target.startswith("/")
        or bool(re.match(r"^[a-zA-Z]:/", raw_target))
    )
    if not is_abs_target and workspace_root:
        resolved_target = os.path.normpath(os.path.join(workspace_root, target_file))
    else:
        resolved_target = os.path.normpath(target_file)

    norm_target = resolved_target.replace("\\", "/").lower()
    norm_root = os.path.normpath(workspace_root).replace("\\", "/").lower() if workspace_root else ""
    norm_root_clean = norm_root.rstrip("/")

    if norm_root_clean and (norm_target == norm_root_clean or norm_target.startswith(norm_root_clean + "/")):
        is_inside_ws = True
        rel_path = norm_target[len(norm_root_clean):].lstrip("/")
    elif not workspace_root:
        is_inside_ws = True
        rel_path = norm_target
    else:
        is_inside_ws = False
        rel_path = norm_target

    norm_pattern = pattern_str.replace("\\", "/").lower()
    while norm_pattern.startswith("./"):
        norm_pattern = norm_pattern[2:]

    # 工作区外部路径仅允许 **/ 前缀递归模式（100% 保留 **/brain/** 跨盘匹配）
    if not is_inside_ws and workspace_root:
        if not norm_pattern.startswith("**/"):
            return False

    if norm_pattern == "*":
        return True

    basename = os.path.basename(norm_target)

    # 无斜杠文件名通配仅在含通配符 (* 或 ?) 时按 basename 匹配
    if "/" not in norm_pattern and ("*" in norm_pattern or "?" in norm_pattern):
        if fnmatch.fnmatchcase(basename, norm_pattern):
            return True

    # 目录递归通配前缀快速判定（如 docs/**，严格要求路径段边界，禁止子串回退）
    if norm_pattern.endswith("/**"):
        prefix = norm_pattern[:-3].strip("/")
        while prefix.startswith("**/"):
            prefix = prefix[3:].strip("/")
        rel_clean = rel_path.strip("/")
        if prefix and "**" not in prefix and not norm_pattern.startswith("**/"):
            if rel_clean == prefix or rel_clean.startswith(prefix + "/"):
                return True

    # 分段 Glob 匹配（精确处理 docs/* 单层、frontend/src/**/*.vue、**/brain/**/*.md 等）
    if _match_segmented_glob(rel_path, norm_pattern):
        return True

    return False


def extract_statuses(text: str) -> List[str]:
    """提取任务单标题行中出现的全部 Quench 标准任务状态（已对齐 SSOT 且具备围栏/引用块过滤）。"""
    if not text:
        return []
    scan = extract_header_task_statuses(text)
    return [status for _, status in scan.statuses_ordered if status != STATUS_UNKNOWN]


def _strip_long_path_prefix(path: str) -> str:
    """去除 Windows \\?\\ 长路径前缀，确保路径比较与 commonpath 兼容。"""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def resolve_physical_path(workspace_root: str, target: str) -> Optional[str]:
    """解析目标路径的真实物理路径（消解 symlink、junction、.. 相对路径别名及未创建文件的父级目录 realpath）。"""
    if not workspace_root or not target:
        return None

    try:
        real_root = _strip_long_path_prefix(os.path.realpath(workspace_root))

        if os.path.isabs(target):
            abs_target = os.path.abspath(target)
        else:
            abs_target = os.path.abspath(os.path.join(real_root, target))

        abs_target = _strip_long_path_prefix(abs_target)

        # 消解软链接、junction：直接调用 realpath 并对其父级目录递归 realpath 校验与规整
        real_target = _strip_long_path_prefix(os.path.realpath(abs_target))
        if not (os.path.exists(abs_target) or os.path.lexists(abs_target)):
            curr = abs_target
            unresolved = []
            while curr and not (os.path.exists(curr) or os.path.lexists(curr)):
                parent, tail = os.path.split(curr)
                if parent == curr:
                    break
                unresolved.append(tail)
                curr = parent
            if curr != abs_target:
                real_parent = _strip_long_path_prefix(os.path.realpath(curr))
                unresolved.reverse()
                real_target = os.path.join(real_parent, *unresolved) if unresolved else real_parent
                real_target = _strip_long_path_prefix(os.path.realpath(real_target))

        return real_target
    except Exception:
        return None


def resolve_realpath_under(workspace_root: str, target: str) -> Optional[str]:
    """返回 realpath 绝对路径；必须严格位于 workspace_root 之下，且消解所有 symlink 与相对路径别名。
    若目标文件尚未创建，对其父级目录执行 realpath 校验并规整。
    捕获 ValueError（Windows 跨驱动器）与跨挂载点逃逸，统一安全返回 None。
    """
    if not workspace_root or not target:
        return None

    try:
        real_root = _strip_long_path_prefix(os.path.realpath(workspace_root))
        real_target = resolve_physical_path(workspace_root, target)
        if not real_target:
            return None

        try:
            common = os.path.commonpath([real_root, real_target])
        except (ValueError, Exception):
            return None

        if os.path.normcase(common) != os.path.normcase(real_root):
            return None

        return real_target
    except Exception:
        return None


def is_governed_task_file(workspace_root: str, target: str, *, dev_tasks_dir: Optional[str] = None) -> bool:
    """判定目标路径物理上是否属于受管任务目录（支持自定义 dev_tasks_dir 配置）。"""
    if not workspace_root or not target:
        return False

    if not target.lower().endswith(".md"):
        return False
    if os.path.basename(target).lower() == "readme.md":
        return False

    resolved = resolve_realpath_under(workspace_root, target)
    if not resolved:
        return False

    if not resolved.lower().endswith(".md") or os.path.basename(resolved).lower() == "readme.md":
        return False

    if dev_tasks_dir:
        tasks_dir = os.path.abspath(os.path.join(workspace_root, dev_tasks_dir)) if not os.path.isabs(dev_tasks_dir) else os.path.abspath(dev_tasks_dir)
    else:
        tasks_dir = os.path.abspath(os.path.join(workspace_root, "docs", "dev_tasks"))

    real_tasks_dir = _strip_long_path_prefix(os.path.realpath(tasks_dir))

    try:
        common = os.path.commonpath([real_tasks_dir, resolved])
        return os.path.normcase(common) == os.path.normcase(real_tasks_dir)
    except (ValueError, Exception):
        return False


def is_task_file(target_file: str, workspace_root: str, config) -> bool:
    """判断是否为 dev_tasks 目录下的任务单文件（排除规范说明 README.md）。"""
    dev_tasks_dir = None
    if config:
        if hasattr(config, "resolve_path"):
            dev_tasks_dir = config.resolve_path("dev_tasks_dir")
        elif hasattr(config, "dev_tasks_dir"):
            dev_tasks_dir = config.dev_tasks_dir
    return is_governed_task_file(workspace_root, target_file, dev_tasks_dir=dev_tasks_dir)


DEFAULT_AGENT_BRAIN_PATTERNS: Tuple[str, ...] = (
    "**/brain/**/*.md",
    "**/brain/**/scratch/**",
    "**/brain/**/browser_sandbox/**",
)

SHELL_TOOL_NAMES: frozenset[str] = frozenset({
    "run_command",
    "execute_command",
    "bash",
    "shell",
    "terminal",
    "powershell",
    "cmd",
})

SHELL_WRITE_PATTERN: Pattern[str] = re.compile(
    r"""
    # 1. 重定向输出 (> 或 >>，含文件描述符 1> 2> &>)；排除 -> / => / >= / <=
    (?:(?<![-\w=])>{1,2}|[&12]>{1,2})(?!=)\s*["']?(?P<redir_target>[^\s|;&"'>]+)["']?
    |
    # 2. 管道传递至 tee
    \|\s*tee(?:\s+-[a-zA-Z]+)*\s+["']?(?P<tee_target>[^\s|;&"'>]+)["']?
    |
    # 3. PowerShell 文件写入、创建、删除、移动与重命名 Cmdlets
    (?:Out-File|Set-Content|Add-Content|New-Item|Remove-Item|Move-Item|Rename-Item)\s+(?:.*?-(?:FilePath|Path|LiteralPath|Destination)\s+)?["']?(?P<ps_target>[^\s|;&"'>]+)["']?
    |
    # 4. .NET 物理写文件调用
    \[(?:System\.)?IO\.File\]::(?:WriteAllText|WriteAllLines|AppendAllText|Create|Delete|Move)\s*\(\s*["'](?P<dotnet_target>[^"']+)["']
    |
    # 5. 复制、移动、删除与就地修改命令 (cp, mv, rm, del, erase, rmdir, touch, install, rsync, sed -i)
    \b(?:cp|copy|mv|move|install|rsync|touch|rm|del|erase|rmdir)\b.*?["']?(?P<cp_target>[^\s|;&"'>]+)["']?\s*(?:$|[|;&])
    |
    \bsed\b\s+-[a-zA-Z]*i[a-zA-Z]*\s+(?:-[eE]\s+)?(?:'[^']*'|"[^"]*"|\S+)\s+["']?(?P<sed_target>[^\s|;&"'>]+)["']?
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _is_task_dir_token(token: str, clean_dir: str) -> bool:
    """Check if a command token refers to the governed dev_tasks directory (path-boundary safe)."""
    if not token:
        return False
    norm_val = token.replace("\\", "/").strip("\"'").strip().lower()
    if not norm_val:
        return False
    base_dir = os.path.basename(clean_dir.rstrip("/"))
    for d in dict.fromkeys(d for d in (clean_dir, base_dir, "dev_tasks") if d):
        escaped_d = re.escape(d)
        if (
            norm_val == d
            or norm_val.startswith(d + "/")
            or f"/{d}/" in norm_val
            or norm_val.endswith("/" + d)
            or bool(re.search(rf"(?:^|/){escaped_d}(?:$|/)", norm_val))
        ):
            return True
    return False


def detect_shell_write_bypass(command: str, workspace_root: str, dev_tasks_dir: str = "docs/dev_tasks") -> Optional[str]:
    """保守检测 Shell 命令是否包含对受管任务目录的写入或删除/移动尝试（>、>>、tee、Out-File、rm、mv 等）。
    命中返回检测到的相对路径，未命中返回 None。
    """
    if not command or not isinstance(command, str):
        return None

    clean_dir = (dev_tasks_dir or "docs/dev_tasks").replace("\\", "/").strip("/").lower()
    base_dir = os.path.basename(clean_dir.rstrip("/"))
    dir_candidates = list(dict.fromkeys(d for d in (clean_dir, base_dir, "dev_tasks") if d))
    dir_alt = "|".join(re.escape(d) for d in dir_candidates)
    cmd_lower = command.replace("\\", "/").lower()

    # 快速短路：若命令中根本不包含受管任务目录路径，平滑放行
    if not any(d in cmd_lower for d in dir_candidates) and not re.search(
        rf"(?:^|[\s\"'/])(?:{dir_alt})(?:$|[\s\"'/])", cmd_lower
    ):
        return None

    # 1. 正则精确提取与判定
    for m in SHELL_WRITE_PATTERN.finditer(command):
        for val in m.groupdict().values():
            if not val:
                continue
            norm_val = val.replace("\\", "/").strip("\"'").strip()
            if _is_task_dir_token(norm_val, clean_dir):
                return norm_val

    # 2. Fail-Closed 兜底判定：包含任务目录关键字，且包含明显的写入/删除/移动原语
    has_write_indicator = bool(re.search(r"(?<![-\w=])>{1,2}(?!=)", cmd_lower)) or any(
        ind in cmd_lower for ind in (
            "tee", "out-file", "set-content", "add-content", "[io.file]::",
            "new-item", "remove-item", "move-item", "rename-item",
        )
    ) or bool(re.search(r"\b(?:rm|del|erase|rmdir|mv|move|cp|copy|touch|sed)\b", cmd_lower))
    if has_write_indicator:
        tokens = re.findall(
            rf"[\"']?([^\s|;&\"'>]*(?:{dir_alt})[^\s|;&\"']*)[\"']?",
            command.replace("\\", "/"),
            re.IGNORECASE,
        )
        for tok in tokens:
            if _is_task_dir_token(tok, clean_dir):
                return tok.strip("\"'")

    return None


MUTATING_TOOLS: Final[frozenset[str]] = frozenset({
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "insert_content",
    "delete_file",
    "write_file",
    "edit_file",
})

READ_ONLY_TOOLS: Final[frozenset[str]] = frozenset({
    "read_file",
    "view_file",
    "grep_search",
    "list_dir",
})


def build_post_image(tool_name: str, args: dict, old_content: str) -> Optional[str]:
    """Simulate post-image of file modifications faithfully.
    Returns Optional[str]: simulated content string, or None if post-image cannot be determined deterministically.
    """
    if tool_name == "write_to_file":
        return str(args.get("CodeContent", ""))

    if tool_name == "delete_file":
        return ""

    if tool_name == "write_file":
        content = args.get("Content")
        if content is None or not isinstance(content, str):
            return None
        if bool(args.get("Append", False)):
            return old_content + content
        return content

    if tool_name == "edit_file":
        tc = args.get("Target")
        rc = args.get("Replacement")
        if tc is None or rc is None or not isinstance(tc, str) or not isinstance(rc, str):
            return None
        if tc == "" or old_content.count(tc) == 0:
            return None
        return old_content.replace(tc, rc)

    if tool_name == "replace_file_content":
        tc = args.get("TargetContent")
        rc = args.get("ReplacementContent")
        if tc is None or rc is None or not isinstance(tc, str) or not isinstance(rc, str):
            return None
        if tc == "":
            return None

        allow_multiple = bool(args.get("AllowMultiple", False))
        start_line = args.get("StartLine")
        end_line = args.get("EndLine")

        if start_line is not None and end_line is not None:
            try:
                start_idx = int(start_line) - 1
                end_idx = int(end_line)
                lines = old_content.splitlines(keepends=True)
                if 0 <= start_idx <= end_idx <= len(lines):
                    range_text = "".join(lines[start_idx:end_idx])
                    count = range_text.count(tc)
                    if count == 1 or (count > 1 and allow_multiple):
                        new_range = range_text.replace(tc, rc, -1 if allow_multiple else 1)
                        return "".join(lines[:start_idx]) + new_range + "".join(lines[end_idx:])
            except Exception:
                pass

        count = old_content.count(tc)
        if count == 0:
            return None
        if count > 1 and not allow_multiple:
            return None
        return old_content.replace(tc, rc, -1 if allow_multiple else 1)

    if tool_name == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks", [])
        if not isinstance(chunks, list):
            return None
        if not chunks:
            return old_content
        curr = old_content
        for chunk in chunks:
            if not isinstance(chunk, dict):
                return None
            res = build_post_image("replace_file_content", chunk, curr)
            if res is None:
                return None
            curr = res
        return curr

    if tool_name == "insert_content":
        content_to_insert = args.get("Content") or args.get("Text")
        if content_to_insert is None:
            return None
        line_num = args.get("LineNumber") or args.get("Line")
        if line_num is not None:
            try:
                idx = int(line_num) - 1
                lines = old_content.splitlines(keepends=True)
                if idx < 0:
                    idx = 0
                elif idx > len(lines):
                    idx = len(lines)
                ins = str(content_to_insert)
                if not ins.endswith("\n") and (idx < len(lines) or old_content.endswith("\n")):
                    ins += "\n"
                lines.insert(idx, ins)
                return "".join(lines)
            except Exception:
                return None
        return None

    return None


def diff_task_statuses(old: TaskHeaderScan, new: TaskHeaderScan) -> List[dict]:
    """Compute directional multiset diff between old and new scan results.
    Returns list of violation dictionaries:
    [{"type": str, "task_id": str, "message": str}]
    """
    violations: List[dict] = []

    # 1. New duplicates detection (F1 multiset: counts increased)
    for tid, new_count in new.occurrence_counts.items():
        old_count = old.occurrence_counts.get(tid, 0)
        if new_count > old_count and new_count > 1:
            violations.append({
                "type": "duplicate_task_id",
                "task_id": tid,
                "message": (
                    f"Duplicate task ID {tid} (occurrences increased from {old_count} to {new_count}) / "
                    f"任务编号 {tid} 出现重复（出现次数由 {old_count} 次增至 {new_count} 次）"
                ),
            })

    # 2. Status smuggling and invalid transition via Counter
    old_counter = Counter(old.statuses_ordered)
    new_counter = Counter(new.statuses_ordered)

    for (tid, new_status), n_count in new_counter.items():
        o_count = old_counter.get((tid, new_status), 0)
        if n_count > o_count:
            # Check old status for this task_id
            old_status = old.statuses.get(tid)
            if old_status is None:
                # Newly added task
                if new_status != STATUS_PENDING:
                    violations.append({
                        "type": "status_smuggling",
                        "task_id": tid,
                        "message": (
                            f"New task {tid} has status [{new_status}]. Initial drafts must start at [{STATUS_PENDING}]. / "
                            f"新增任务 {tid} 状态为【{new_status}】。初稿一律必须从【{STATUS_PENDING}】开始。"
                        ),
                    })
            else:
                # Existing task: status changed
                if old_status != new_status:
                    violations.append({
                        "type": "invalid_transition",
                        "task_id": tid,
                        "message": (
                            f"Task {tid} status modified directly: [{old_status}] -> [{new_status}]. Use FastMCP tools (dev_tasks_checkout / dev_tasks_confirm) instead. / "
                            f"任务 {tid} 状态被直接修改：【{old_status}】➔【{new_status}】。请使用 FastMCP 工具（dev_tasks_checkout / dev_tasks_confirm）推进状态。"
                        ),
                    })

    # 3. Deletion of non-editable tasks
    for tid, old_count in old.occurrence_counts.items():
        new_count = new.occurrence_counts.get(tid, 0)
        if new_count == 0:
            old_status = old.statuses.get(tid, STATUS_PENDING)
            if old_status not in (STATUS_PENDING, STATUS_REWORK):
                violations.append({
                    "type": "delete_non_editable",
                    "task_id": tid,
                    "message": (
                        f"Non-editable task {tid} [{old_status}] was deleted or cleared; removing audit records is prohibited. / "
                        f"非可编辑任务 {tid}【{old_status}】被删除或清空，严禁删除已有审计台账。"
                    ),
                })

    # 4. Truncation / empty file
    if len(old.statuses_ordered) > 0 and len(new.statuses_ordered) == 0:
        violations.append({
            "type": "file_truncated",
            "task_id": "",
            "message": "Task file content was truncated/cleared and all tasks were lost. / 任务单内容被截断清空，所有任务均丢失。",
        })

    # 5. Newly introduced malformed headers (F2)
    new_malformed = new.malformed_ids - old.malformed_ids
    if new_malformed:
        violations.append({
            "type": "malformed_header",
            "task_id": ", ".join(sorted(new_malformed)),
            "message": f"Malformed task header(s) introduced: {', '.join(sorted(new_malformed))} / 新增畸形任务标题行: {', '.join(sorted(new_malformed))}",
        })

    return violations


def check_task_status_guard(target_file: str, tool_name: str, args: dict) -> Optional[dict]:
    """加固守卫：基于 header 精准提取 + 多维差分 + 入口穷举，防止任何未授权状态篡改。"""
    filename = os.path.basename(target_file)

    if tool_name in READ_ONLY_TOOLS:
        return None

    if tool_name not in MUTATING_TOOLS:
        return {
            "decision": "ask",
            "reason": (
                f"[Unknown Mutating Tool Blocked / 未知变更工具拦截]\n"
                f"Detected non-whitelisted mutating tool '{tool_name}' attempting to modify task file {filename}. / 检测到未在白名单中的变更工具 {tool_name} 试图操作任务单 {filename}。\n"
                f"Please confirm intent manually. / 为防范未定义修改行为，请人工确认操作意图。"
            ),
        }

    if tool_name == "delete_file":
        return {
            "decision": "ask",
            "reason": (
                f"[Task File Deletion Blocked / 任务单物理删除阻断]\n"
                f"Governed task file {filename} cannot be deleted via delete_file. Use dev_tasks_confirm(action='revoke') instead. / 受管任务单 {filename} 禁止通过 delete_file 删除。若需作废或撤销任务，请使用标准命令 dev_tasks_confirm(action='revoke')。"
            ),
        }

    # 读取旧文件内容（若不存在视为新建；读取异常 fail-open 并记日志）
    old_content = ""
    if os.path.isfile(target_file):
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                old_content = f.read()
        except (OSError, UnicodeDecodeError):
            # fail-open
            return None

    post_image = build_post_image(tool_name, args, old_content)
    if post_image is None:
        return {
            "decision": "ask",
            "reason": (
                f"[Undeterminable Post-Image / 无法确定后置快照]\n"
                f"Tool {tool_name} arguments on task file {filename} cannot be deterministically evaluated (undeterminable_post_image). / 工具 {tool_name} 对任务单 {filename} 的修改参数无法确定性演算 (undeterminable_post_image)。\n"
                f"Please review manually. / 请人工核查修改内容。"
            ),
        }

    old_scan = extract_header_task_statuses(old_content)
    new_scan = extract_header_task_statuses(post_image)

    if not old_content:
        # 新建文件检查
        for tid, st in new_scan.statuses_ordered:
            if st != STATUS_PENDING:
                return {
                    "decision": "ask",
                    "reason": (
                        f"[Initial Task Status Blocked / 任务单初始状态物理阻断]\n"
                        f"New task file {filename} contains non-[{STATUS_PENDING}] task: {tid} [{st}]. Initial drafts must start at [{STATUS_PENDING}]. / 新建任务单 {filename} 包含非【{STATUS_PENDING}】任务: {tid}【{st}】。按照 Quench 治理规范，初稿一律必须从【{STATUS_PENDING}】开始。"
                    ),
                }
        if new_scan.duplicates:
            return {
                "decision": "ask",
                "reason": f"[Duplicate Task ID Blocked / 重复任务编号拦截] New task file contains duplicate task IDs: {', '.join(sorted(new_scan.duplicates))} / 新建任务单包含重复任务编号: {', '.join(sorted(new_scan.duplicates))}",
            }
        if new_scan.malformed_ids:
            return {
                "decision": "ask",
                "reason": f"[Malformed Task Header Blocked / 畸形任务标题拦截] New task file contains unparsable task headers: {', '.join(sorted(new_scan.malformed_ids))} / 新建任务单包含无法解析的任务标题: {', '.join(sorted(new_scan.malformed_ids))}",
            }
        return None

    # 多维差分校验
    violations = diff_task_statuses(old_scan, new_scan)
    if violations:
        reasons_text = "\n".join(f"• {v['message']}" for v in violations)
        return {
            "decision": "ask",
            "reason": (
                f"[Task Status & Boundary Guard Interception / 任务状态与边界守卫拦截]\n"
                f"Detected specification violations modifying task file {filename}: / 检测到对任务单 {filename} 的修改违反规范：\n"
                f"{reasons_text}\n\n"
                f"Core Invariant: Task status must only advance via dev_tasks_checkout or dev_tasks_confirm, never direct edits. / ★ 核心防线：任务状态必须由 dev_tasks_checkout 或 dev_tasks_confirm 推进，严禁直接篡写。"
            ),
        }

    return None


def is_meta_file(target_file: str, workspace_root: str, config) -> bool:
    """识别 Quench 体系通用元数据文件（.agents、CHANGELOG、README），豁免拦截。"""
    resolved = resolve_realpath_under(workspace_root, target_file)
    if not resolved:
        return False

    norm_target = resolved.replace("\\", "/").lower()
    norm_root = _strip_long_path_prefix(os.path.realpath(workspace_root)).replace("\\", "/").lower().rstrip("/")

    if norm_target == norm_root or norm_target.startswith(norm_root + "/"):
        rel_path = norm_target[len(norm_root):].lstrip("/")
    else:
        return False

    # .agents 目录内的所有元文件
    if rel_path.startswith(".agents/") or rel_path == ".agents":
        return True

    # changelog 文件
    changelog_name = os.path.basename(config.changelog_path or "CHANGELOG.md").lower()
    if os.path.basename(norm_target) == changelog_name:
        return True

    # dev_tasks 目录内的规范说明文件（如 README.md）
    if os.path.basename(norm_target).lower() == "readme.md":
        dev_tasks_dir = _strip_long_path_prefix(os.path.realpath(config.resolve_path("dev_tasks_dir"))).replace("\\", "/").lower().rstrip("/")
        if norm_target.startswith(dev_tasks_dir + "/"):
            return True

    return False


def is_agent_brain_artifact(target_file: str, workspace_root: str) -> bool:
    """判定目标路径是否为 Agent 运行期 brain 会话制品（如 walkthrough.md、scratch/**、browser_sandbox/**）。
    先通过 resolve_physical_path 消解软链接、junction 及 .. 路径回溯，再按严格路径段匹配 DEFAULT_AGENT_BRAIN_PATTERNS。
    """
    if not target_file or not workspace_root:
        return False
    physical_target = resolve_physical_path(workspace_root, target_file)
    if not physical_target:
        return False
    for pat in DEFAULT_AGENT_BRAIN_PATTERNS:
        if matches_pattern(physical_target, pat, workspace_root):
            return True
    return False


def is_whitelist_matched(config: Any, target_file: str, workspace_root: str) -> bool:
    """第一层：静态配置白名单匹配（quench_stack.yaml fast_track_rules.allow_untracked_patterns + 内置 brain 制品白名单）。"""
    effective_file = resolve_physical_path(workspace_root, target_file) or target_file
    raw_patterns = list(config.get_fast_track_patterns()) if config and hasattr(config, "get_fast_track_patterns") else []
    patterns: List[str] = []
    for pat in [*raw_patterns, *DEFAULT_AGENT_BRAIN_PATTERNS]:
        if pat not in patterns:
            patterns.append(pat)
    for pat in patterns:
        if matches_pattern(effective_file, pat, workspace_root):
            return True
    return False


SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")


def verify_session_integrity(
    bypass_data: dict, incoming_conversation_id: Optional[str]
) -> Tuple[bool, str]:
    """
    校验会话旁路完整性与租约状态。
    统一使用 UTC aware datetime 进行时间比较。
    返回: (is_valid, reject_reason)
    """
    if not isinstance(bypass_data, dict):
        return False, "bypass 数据格式非字典"

    if not bypass_data.get("active", False):
        return False, "bypass 处于未激活状态"

    # 物理会话锁核验 (Session Lock Check)
    locked_session = bypass_data.get("session_id")
    if locked_session:
        if not incoming_conversation_id or not str(incoming_conversation_id).strip():
            return False, f"缺失当前会话 ID，无法校验会话锁 (锁定会话: {locked_session})"
        if str(locked_session).strip().lower() != str(incoming_conversation_id).strip().lower():
            return False, f"跨会话冲突: 锁定会话 {locked_session} != 当前会话 {incoming_conversation_id}"

    # 过期失效检查（统一 UTC 时间戳比对与 aware/naive 兼容）
    expires_at = bypass_data.get("expires_at")
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            exp_dt_utc = exp_dt.astimezone(timezone.utc)
            if datetime.now(timezone.utc) > exp_dt_utc:
                return False, f"会话租约已超时过期 ({expires_at})"
        except Exception as e:
            return False, f"过期时间格式异常: {e}"

    return True, ""


def safe_clean_corrupted_bypass(bypass_path: str, logger: Optional[logging.Logger] = None) -> None:
    """原子化清理或重命名已失效/损坏的会话旁路文件，带 FileLock 保护。"""
    from filelock import FileLock
    lock_file = bypass_path + ".lock"
    try:
        with FileLock(lock_file, timeout=5.0):
            if os.path.isfile(bypass_path):
                try:
                    os.remove(bypass_path)
                except Exception as e:
                    if logger:
                        logger.warning(f"删除旁路文件失败 {bypass_path}: {e}", exc_info=True)
    except Exception as e:
        if logger:
            logger.warning(f"获取旁路文件锁失败 {lock_file}: {e}", exc_info=True)


def is_session_bypass_matched(
    workspace_root: str,
    target_file: str,
    current_conversation_id: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """第二层：动态会话旁路匹配（.agents/.quench_bypass.json）。
    
    具备三重防线：
    1. 物理会话锁核验 (Session Lock)：比对 conversationId，跨会话立即失效并自愈清理；
    2. 有效时长倒计时 (Expiry Check)：超时自动失效并自愈清理；
    3. 并发安全锁 (FileLock)：保护 bypass 文件读取与自愈清理，防止瞬态穿透与数据竞争。
    """
    bypass_file = os.path.join(workspace_root, ".agents", ".quench_bypass.json")
    if not os.path.isfile(bypass_file):
        return False

    from filelock import FileLock, Timeout
    lock_file = bypass_file + ".lock"
    try:
        with FileLock(lock_file, timeout=5.0):
            if not os.path.isfile(bypass_file):
                return False

            try:
                with open(bypass_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                # 畸形 JSON 文件，自愈清理
                if logger:
                    logger.warning(f"读取旁路文件 JSON 异常，触发自愈清理 {bypass_file}: {e}", exc_info=True)
                    log_guard_event(
                        logger, "BYPASS_CLEAN", bypass_file, "", "clean", reason=f"畸形JSON: {e}", session_id=current_conversation_id
                    )
                try:
                    os.remove(bypass_file)
                except Exception as rem_err:
                    if logger:
                        logger.warning(f"自愈清理旁路文件失败: {rem_err}", exc_info=True)
                return False

            is_valid, reject_reason = verify_session_integrity(data, current_conversation_id)
            if not is_valid:
                # 校验未通过（跨会话或已过期或损坏），清理旁路文件
                if logger:
                    logger.warning(f"旁路文件校验未通过 ({reject_reason})，触发自愈清理 {bypass_file}")
                    log_guard_event(
                        logger, "BYPASS_CLEAN", bypass_file, "", "clean", reason=reject_reason, session_id=current_conversation_id
                    )
                try:
                    os.remove(bypass_file)
                except Exception as rem_err:
                    if logger:
                        logger.warning(f"清理失效旁路文件失败: {rem_err}", exc_info=True)
                return False

            patterns = data.get("patterns", [])
            for pat in patterns:
                if matches_pattern(target_file, pat, workspace_root):
                    return True
    except Timeout as e:
        # FileLock 超时，为安全防线起见不放行
        if logger:
            logger.warning(f"旁路文件锁超时: {e}", exc_info=True)
        return False
    except Exception as e:
        if logger:
            logger.warning(f"旁路匹配异常: {e}", exc_info=True)
        return False

    return False


def _extract_task_affected_files(content: str, task_id: str) -> List[str]:
    """Fence-aware extraction of affected file entries strictly within the target task section."""
    if not content or not task_id:
        return []

    header_re = re.compile(
        rf"^###\s+(?:任务|Task)\s+{re.escape(task_id)}(?:\s|$|:|—|-)",
        re.IGNORECASE,
    )
    in_fence_char: Optional[str] = None
    in_fence_len = 0
    in_target_task = False
    section_lines: List[str] = []

    for line in content.splitlines():
        stripped_left = line.lstrip(" ")
        indent = len(line) - len(stripped_left)

        if indent <= 3 and (stripped_left.startswith("```") or stripped_left.startswith("~~~")):
            fence_char = stripped_left[0]
            flen = len(stripped_left) - len(stripped_left.lstrip(fence_char))
            if in_fence_char is None:
                in_fence_char = fence_char
                in_fence_len = flen
            elif in_fence_char == fence_char and flen >= in_fence_len:
                in_fence_char = None
                in_fence_len = 0
            if in_target_task:
                section_lines.append(line)
            continue

        if in_fence_char is not None:
            if in_target_task:
                section_lines.append(line)
            continue

        if stripped_left.startswith(">"):
            if in_target_task:
                section_lines.append(line)
            continue

        if stripped_left.startswith("###") and not stripped_left.startswith("####"):
            if in_target_task:
                break
            if header_re.match(stripped_left):
                in_target_task = True
                continue

        if in_target_task:
            section_lines.append(line)

    if not section_lines:
        return []

    allowed_entries: List[str] = []
    in_fence_char = None
    in_fence_len = 0
    found_heading = False
    in_affected_fence = False

    for line in section_lines:
        stripped_left = line.lstrip(" ")
        indent = len(line) - len(stripped_left)

        if indent <= 3 and (stripped_left.startswith("```") or stripped_left.startswith("~~~")):
            fence_char = stripped_left[0]
            flen = len(stripped_left) - len(stripped_left.lstrip(fence_char))
            if in_fence_char is None:
                in_fence_char = fence_char
                in_fence_len = flen
                if found_heading:
                    in_affected_fence = True
                continue
            elif in_fence_char == fence_char and flen >= in_fence_len:
                in_fence_char = None
                in_fence_len = 0
                if in_affected_fence:
                    break
                continue

        if in_affected_fence:
            item = line.strip()
            if not item:
                continue
            item = re.sub(r"^(?:[-*+]\s+)+", "", item).strip()
            item = re.sub(r"^\[(?:MODIFY|NEW|DELETE|RENAME)\]\s*", "", item, flags=re.IGNORECASE).strip()
            item = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", item).strip()
            for part in re.split(r"\s*(?:->|➔)\s*", item):
                cleaned = part.strip().strip("`").strip().replace("\\", "/")
                while cleaned.startswith("./"):
                    cleaned = cleaned[2:]
                if cleaned:
                    allowed_entries.append(cleaned)
            continue

        if in_fence_char is not None:
            continue

        if re.match(r"^####\s+(?:【涉及文件】|\[Affected Files\]|【Affected Files】)\s*$", stripped_left, re.IGNORECASE):
            found_heading = True
        elif found_heading and stripped_left.startswith("####"):
            break

    return allowed_entries


def main():
    logger = None
    target_file = ""
    tool_name = ""
    conversation_id = None
    workspace_root = None

    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print(json.dumps({"decision": "allow"}))
            return

        payload = json.loads(raw_input)
    except Exception:
        print(json.dumps({"decision": "allow"}))
        return

    try:
        from adapters import EnvironmentDetector, get_adapter

        workspace_paths = payload.get("workspacePaths", [])
        workspace_root = workspace_paths[0] if workspace_paths and isinstance(workspace_paths, list) else None
        if workspace_root:
            logger = get_hook_logger(workspace_root)

        env_type = EnvironmentDetector.detect(payload, workspace_root=workspace_root)
        adapter = get_adapter(env_type, workspace_root=workspace_root)

        tool_call = payload.get("toolCall", {})
        args = tool_call.get("args", {})
        target_file = args.get("TargetFile") or args.get("Path") or ""
        tool_name = tool_call.get("name", "")
        conversation_id = adapter.extract_session_id(payload)

        def emit_decision(decision: str, reason: str = "", event_type: Optional[str] = None) -> None:
            if logger:
                if not event_type:
                    if decision == "allow":
                        ev = "ALLOW"
                    elif decision == "deny":
                        ev = "DENIED"
                    elif decision == "ask":
                        ev = "ASK_MODAL"
                    else:
                        ev = "ALLOW"
                else:
                    ev = event_type
                log_guard_event(
                    logger=logger,
                    event_type=ev,
                    target_file=target_file,
                    tool_name=tool_name,
                    decision=decision,
                    reason=reason,
                    session_id=conversation_id,
                )

            out = adapter.format_decision(decision, reason)
            if isinstance(out, dict):
                print(json.dumps(out))
            else:
                print(out)
                if decision in ("deny", "ask") and not adapter.supports_interactive_ask():
                    sys.exit(1)

        # 快速短路 1：只读工具无条件放行（保障 <50ms 预算，不加载 yaml/state_machine）
        if tool_name in READ_ONLY_TOOLS:
            emit_decision("allow", "Read-only tool fast-path allow / 只读工具快速放行")
            return

        # 专属分支：Shell 命令直接写入/重定向受管任务目录检测（废除“空 TargetFile 即盲目放行”漏洞）
        if tool_name in SHELL_TOOL_NAMES:
            command = args.get("CommandLine") or args.get("command") or args.get("cmd") or ""
            if not command or not workspace_root:
                emit_decision("allow", "Shell 命令为空或无工作区")
                return

            config_path = os.path.join(workspace_root, ".agents", "quench_stack.yaml")
            if not os.path.isfile(config_path):
                emit_decision("allow", "非Quench项目放行")
                return

            from project_config import load_project_config
            config = load_project_config(workspace_root)
            dev_tasks_dir = config.dev_tasks_dir or "docs/dev_tasks"

            detected_target = detect_shell_write_bypass(command, workspace_root, dev_tasks_dir=dev_tasks_dir)
            if detected_target:
                reason = (
                    f"【Shell 任务单篡写重定向拦截 / Shell Task Write Bypass Interception】\n"
                    f"Detected shell command attempting to write to governed task directory: {detected_target}\n"
                    f"检测到试图通过 Shell 写入/重定向受管任务目录：{detected_target}\n\n"
                    f"Command / 执行命令: {command[:200]}\n\n"
                    f"★ 核心防线：任务单必须通过 Quench MCP 工具受管流转，严禁通过 Shell 重定向或直接写文件进行旁路篡写！"
                )
                emit_decision("deny", reason, event_type="DENIED")
                return

            emit_decision("allow", "Shell 只读或非任务单操作放行")
            return

        if not workspace_paths or not target_file:
            emit_decision("allow", "无工作区或无目标文件")
            return

        workspace_root = workspace_paths[0]
        config_path = os.path.join(workspace_root, ".agents", "quench_stack.yaml")
        if not os.path.isfile(config_path):
            # 非 Quench 纳管项目，静默放行
            emit_decision("allow", "非Quench项目放行")
            return

        # 0. 物理路径归一原语解析（消解软链接、junction 与跨驱动器/相对路径逃逸）
        resolved_target = resolve_realpath_under(workspace_root, target_file)

        # 快速短路 2：工作区外部 Agent brain 会话制品白名单免加载 yaml 直接放行
        if resolved_target is None and is_agent_brain_artifact(target_file, workspace_root):
            emit_decision("allow", "Agent brain runtime artifact whitelist / Agent 运行期 brain 制品白名单豁免放行")
            return

        from project_config import load_project_config
        from state_machine import STATUS_IN_PROGRESS, parse_task_file

        config = load_project_config(workspace_root)
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")

        # 检查是否发生任务单物理逃逸攻击（以任务目录为跳板逃逸出受管任务单）
        rel_dev_tasks = (config.dev_tasks_dir or "docs/dev_tasks").replace("\\", "/").lower().strip("/")
        raw_norm = target_file.replace("\\", "/").lower()
        has_task_dir_marker = (
            raw_norm.startswith(rel_dev_tasks + "/")
            or f"/{rel_dev_tasks}/" in raw_norm
            or raw_norm.endswith("/" + rel_dev_tasks)
        )
        if (
            has_task_dir_marker
            and not is_governed_task_file(workspace_root, target_file, dev_tasks_dir=dev_tasks_dir)
            and os.path.basename(target_file).lower() != "readme.md"
        ):
            emit_decision("deny", "realpath_escape", event_type="DENIED")
            return

        # 0. 任务单文件状态强守卫（严防任何 Agent 擅自修改状态，或初稿私自越级设为已确认）
        if is_governed_task_file(workspace_root, target_file, dev_tasks_dir=dev_tasks_dir):
            guard_decision = check_task_status_guard(resolved_target or target_file, tool_name, args)
            if guard_decision:
                emit_decision(guard_decision.get("decision", "ask"), guard_decision.get("reason", ""))
                return
            # 任务单非状态内容编辑（如补充步骤细节、完善说明），直接放行
            emit_decision("allow", "任务单非状态编辑放行")
            return

        # 0.1 治理通用元数据文件豁免（.agents 配置文件、CHANGELOG、README）
        if is_meta_file(target_file, workspace_root, config):
            emit_decision("allow", "治理通用元数据文件豁免放行")
            return

        effective_target = resolved_target or resolve_physical_path(workspace_root, target_file) or target_file

        # 0.1b Agent 运行期 brain 会话制品白名单豁免（跨盘符/工作区外 brain/<conv-id>/*.md, scratch/**, browser_sandbox/**）
        if is_agent_brain_artifact(effective_target, workspace_root):
            emit_decision("allow", "Agent brain runtime artifact whitelist / Agent 运行期 brain 制品白名单豁免放行")
            return

        # 0.2 生产代码靶向识别（Dual-Track Boundary Engine）：非受管的纯文档/规划/素材天然豁免
        if hasattr(config, "is_path_governed") and not config.is_path_governed(effective_target):
            emit_decision("allow", "非受管路径（双轨边界）天然豁免放行")
            return

        # 寻找当前正在处于 🔨 执行中 的任务
        active_task = None
        active_file_path = None
        if os.path.isdir(dev_tasks_dir):
            for md_file in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
                if os.path.basename(md_file).lower() == "readme.md":
                    continue
                tasks = parse_task_file(md_file)
                for t in tasks:
                    if t.status == STATUS_IN_PROGRESS:
                        active_task = t
                        active_file_path = md_file
                        break
                if active_task:
                    break

        desc = (
            args.get("Description")
            or args.get("Instruction")
            or args.get("toolSummary")
            or "模型未在工具参数中填写修改理由"
        )

        # -------------------------------------------------------------
        # 情形 A：当前已有任务处于 🔨 执行中
        # -------------------------------------------------------------
        if active_task and active_file_path:
            with open(active_file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            allowed_entries = _extract_task_affected_files(content, str(active_task.id))
            is_in_allowed_scope = False

            for entry in allowed_entries:
                if "*" in entry or "?" in entry:
                    if matches_pattern(effective_target, entry, workspace_root):
                        is_in_allowed_scope = True
                        break
                else:
                    allowed_phys = resolve_realpath_under(workspace_root, entry)
                    if (
                        allowed_phys
                        and resolved_target
                        and os.path.normcase(allowed_phys) == os.path.normcase(resolved_target)
                    ):
                        is_in_allowed_scope = True
                        break

            if is_in_allowed_scope:
                emit_decision("allow", f"Matched active task scope / 命中执行中任务范围 (Task {active_task.id})")
                return

            # 任务外文件，先检查 Layer 1 静态白名单与 Layer 2 会话旁路（含会话锁核验）
            if is_whitelist_matched(config, effective_target, workspace_root):
                emit_decision("allow", "Matched static whitelist / 命中静态白名单配置放行")
                return

            if is_session_bypass_matched(workspace_root, effective_target, conversation_id, logger=logger):
                emit_decision("allow", "Matched session bypass / 命中动态会话旁路放行")
                return

            # 触发任务越界拦截提示
            reason = (
                f"[Out-of-Scope File Modification Warning / 范围外修改拦截]\n"
                f"Active task (Task {active_task.id}: {active_task.title}) does not include this file in its declared scope.\n"
                f"当前执行中的任务（Task {active_task.id}: {active_task.title}）规划的文件列表中未包含此文件。\n\n"
                f"📁 Target / 目标文件: {target_file}\n"
                f"💡 Agent Justification / 模型给出的修改理由: {desc}\n\n"
                f"Click [Allow] if this was a planning omission; click [Reject] if unexpected. / 若确属规划遗漏请点击【允许】，若属非预期变动请点击【拒绝】。"
            )
            emit_decision("ask", reason)
            return

        # -------------------------------------------------------------
        # 情形 B：当前无任务处于 🔨 执行中（空载改动）
        # -------------------------------------------------------------
        # 第一层：检查静态白名单（配置文件）
        if is_whitelist_matched(config, effective_target, workspace_root):
            emit_decision("allow", "Matched static whitelist / 命中静态白名单配置放行")
            return

        # 第二层：检查动态会话旁路（.agents/.quench_bypass.json，含会话锁核验）
        if is_session_bypass_matched(workspace_root, effective_target, conversation_id, logger=logger):
            emit_decision("allow", "Matched session bypass / 命中动态会话旁路放行")
            return

        # 第三层：交互式弹窗向用户确认（Ask Modal）
        reason = (
            f"【未纳管代码修改确认 / Unmanaged Code Modification Confirmation】\n"
            f"No Quench task is currently in '{STATUS_IN_PROGRESS}' state, and the target file did not match any fast-track whitelist or session bypass rule.\n"
            f"当前工作区未处于任何 Quench 任务的“{STATUS_IN_PROGRESS}”状态，且目标文件未命中快速通道白名单或会话旁路规则。\n\n"
            f"📁 Target / 目标文件: {target_file}\n"
            f"💡 Model Justification / 模型修改理由: {desc}\n\n"
            f"Decision Options / 请进行决策：\n"
            f"• Click [Allow] / 点击【允许】：Allow single edit for this tool call / 仅对本次修改单次放行；\n"
            f"• Click [Reject] / 点击【拒绝】：Block modification. To bypass temporarily, instruct Agent to enable fast-track bypass or checkout a task / 拦截本次修改。"
        )
        emit_decision("ask", reason)

    except Exception as e:
        if logger:
            logger.warning(f"Hook 运行期未捕获异常降级放行: {e}", exc_info=True)
            log_guard_event(
                logger=logger,
                event_type="EXCEPTION",
                target_file=target_file or "unknown",
                tool_name=tool_name,
                decision="allow",
                reason=f"Exception: {e}",
                session_id=conversation_id,
            )
        # 防御兜底：Hook 绝不能崩溃导致 IDE 流程死锁
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
