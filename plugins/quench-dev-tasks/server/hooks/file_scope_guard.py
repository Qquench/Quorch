#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import glob
import json
import logging
import logging.handlers
import os
import re
import sys
from typing import Optional, List, Tuple, Pattern
from filelock import FileLock, Timeout

# 保证能加载上级 server 模块
current_dir = os.path.dirname(os.path.abspath(__file__))
server_dir = os.path.dirname(current_dir)
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
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


def matches_pattern(target_file: str, pattern: str, workspace_root: str) -> bool:
    """检查文件是否符合 Glob 规则（支持文件名通配与路径前缀通配）。"""
    if not target_file or not pattern:
        return False
    pattern_str = pattern.strip()
    if pattern_str == "*":
        return True

    norm_target = os.path.normpath(target_file).replace("\\", "/").lower()
    norm_root = os.path.normpath(workspace_root).replace("\\", "/").lower()

    if norm_target.startswith(norm_root):
        rel_path = norm_target[len(norm_root):].lstrip("/")
    else:
        rel_path = norm_target

    basename = os.path.basename(norm_target)
    norm_pattern = pattern_str.replace("\\", "/").lower()

    # 文件名通配（如 *.vue, *.css, test_*.py）
    if "/" not in norm_pattern:
        if fnmatch.fnmatch(basename, norm_pattern):
            return True
        if fnmatch.fnmatch(rel_path, norm_pattern):
            return True

    # 路径匹配（如 docs/*, frontend/src/**/*.vue）
    if fnmatch.fnmatch(rel_path, norm_pattern):
        return True

    # 目录递归通配（如 docs/**, frontend/src/assets/**）
    if norm_pattern.endswith("/**"):
        prefix = norm_pattern[:-3].strip("/")
        if rel_path.startswith(prefix + "/") or rel_path == prefix:
            return True
        if f"/{prefix}/" in f"/{rel_path}/":
            return True

    # 目录单层通配（如 docs/*）
    if norm_pattern.endswith("/*"):
        prefix = norm_pattern[:-2].strip("/")
        if rel_path.startswith(prefix + "/"):
            return True

    return False


STATUS_PATTERN = re.compile(r"(?:[⬜✅🔨🔄]|✔️|⏭️)\s*(?:待确认|已确认|执行中|已完成|跳过|需返工)")


def extract_statuses(text: str) -> List[str]:
    """提取文本中出现的全部 Quench 标准任务状态。"""
    if not text:
        return []
    raw_matches = STATUS_PATTERN.findall(text)
    cleaned = []
    for m in raw_matches:
        c = re.sub(r"\s+", " ", m.strip())
        cleaned.append(c)
    return cleaned


def _strip_long_path_prefix(path: str) -> str:
    """去除 Windows \\?\\ 长路径前缀，确保路径比较与 commonpath 兼容。"""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def resolve_realpath_under(workspace_root: str, target: str) -> Optional[str]:
    """返回 realpath 绝对路径；必须严格位于 workspace_root 之下，且消解所有 symlink 与相对路径别名。
    若目标文件尚未创建，对其父级目录执行 realpath 校验并规整。
    捕获 ValueError（Windows 跨驱动器）与跨挂载点逃逸，统一安全返回 None。
    """
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
    # 1. 重定向输出 (> 或 >>，含文件描述符 1> 2> &>)
    (?:>{1,2}|[&12]>{1,2})\s*["']?(?P<redir_target>[^\s|;&"'>]+)["']?
    |
    # 2. 管道传递至 tee
    \|\s*tee(?:\s+-[a-zA-Z]+)*\s+["']?(?P<tee_target>[^\s|;&"'>]+)["']?
    |
    # 3. PowerShell 文件写入与创建 Cmdlets
    (?:Out-File|Set-Content|Add-Content|New-Item)\s+(?:.*?-(?:FilePath|Path)\s+)?["']?(?P<ps_target>[^\s|;&"'>]+)["']?
    |
    # 4. .NET 物理写文件调用
    \[(?:System\.)?IO\.File\]::(?:WriteAllText|WriteAllLines|AppendAllText|Create)\s*\(\s*["'](?P<dotnet_target>[^"']+)["']
    |
    # 5. Linux / Unix 复制、移动与修改命令 (cp, mv, touch, install, rsync, sed -i)
    \b(?:cp|copy|mv|move|install|rsync|touch)\b.*?["']?(?P<cp_target>[^\s|;&"'>]+)["']?\s*(?:$|[|;&])
    |
    \bsed\b\s+-[a-zA-Z]*i[a-zA-Z]*\s+(?:-[eE]\s+)?(?:'[^']*'|"[^"]*"|\S+)\s+["']?(?P<sed_target>[^\s|;&"'>]+)["']?
    """,
    re.VERBOSE | re.IGNORECASE,
)


def detect_shell_write_bypass(command: str, workspace_root: str, dev_tasks_dir: str = "docs/dev_tasks") -> Optional[str]:
    """保守检测 Shell 命令是否包含对受管任务目录的写入尝试（>、>>、tee、Out-File、Set-Content 等）。
    命中返回检测到的相对路径，未命中返回 None。
    """
    if not command or not isinstance(command, str):
        return None

    clean_dir = (dev_tasks_dir or "docs/dev_tasks").replace("\\", "/").strip("/").lower()
    cmd_lower = command.replace("\\", "/").lower()

    # 快速短路：若命令中根本不包含任务目录关键字，平滑放行
    if clean_dir not in cmd_lower and "dev_tasks" not in cmd_lower:
        return None

    # 1. 正则精确提取与判定
    for m in SHELL_WRITE_PATTERN.finditer(command):
        for val in m.groupdict().values():
            if not val:
                continue
            norm_val = val.replace("\\", "/").strip("\"'").strip()
            norm_val_lower = norm_val.lower()
            if (
                norm_val_lower.startswith(clean_dir + "/")
                or norm_val_lower == clean_dir
                or f"/{clean_dir}/" in norm_val_lower
                or norm_val_lower.endswith("/" + clean_dir)
                or "dev_tasks" in norm_val_lower
            ):
                return norm_val

    # 2. Fail-Closed 兜底判定：包含任务目录关键字，且包含明显的写入重定向/覆盖原语
    write_indicators = (">", "tee", "out-file", "set-content", "add-content", "[io.file]::", "new-item")
    has_write_indicator = any(ind in cmd_lower for ind in write_indicators)
    if has_write_indicator:
        tokens = re.findall(r"[\"']?([^\s|;&\"'>]*dev_tasks[^\s|;&\"']*)[\"']?", command, re.IGNORECASE)
        if tokens:
            return tokens[0].strip("\"'")
        return dev_tasks_dir

    return None


def check_task_status_guard(target_file: str, tool_name: str, args: dict) -> Optional[dict]:
    """加固守卫：不论哪一个 Agent 变更状态均必须经过用户明确确认；
    首次生成任务单时除非用户明确指示直接标记为已确认，一律从待确认开始。
    """
    filename = os.path.basename(target_file)

    # 1. 首次创建或整文件写入 (write_to_file)
    if tool_name == "write_to_file":
        code_content = args.get("CodeContent", "")
        statuses = extract_statuses(code_content)
        if statuses:
            non_pending = [s for s in statuses if "待确认" not in s]
            if non_pending:
                unique_non_pending = list(dict.fromkeys(non_pending))
                reason = (
                    f"【任务单初始状态物理阻断】\n"
                    f"检测到 Agent 正在创建或写入任务单：{filename}\n"
                    f"内容中包含非【待确认】状态标记: {', '.join(unique_non_pending)}\n\n"
                    f"★ 核心防线：按照 Quench 治理规范，任务初稿一律必须从【⬜ 待确认】开始，"
                    f"严禁任何 Agent 擅自越级设为已确认！\n\n"
                    f"决策指引：\n"
                    f"• 若您此前已明确指示 Agent 直接标记为已确认：请点击【允许】单次放行；\n"
                    f"• 若属于 Agent 自作主张越级跳过：请点击【拒绝】，强制要求 Agent 改为【⬜ 待确认】并走规范审查流程。"
                )
                return {"decision": "ask", "reason": reason}
        return None

    # 2. 单块文本替换 (replace_file_content)
    if tool_name == "replace_file_content":
        target_content = args.get("TargetContent", "")
        replacement_content = args.get("ReplacementContent", "")
        old_statuses = extract_statuses(target_content)
        new_statuses = extract_statuses(replacement_content)

        if (old_statuses or new_statuses) and old_statuses != new_statuses:
            old_desc = ", ".join(old_statuses) if old_statuses else "(无状态)"
            new_desc = ", ".join(new_statuses) if new_statuses else "(无状态)"
            reason = (
                f"【任务状态流转人工审批确认】\n"
                f"检测到 Agent 正在尝试修改任务单状态：{filename}\n"
                f"目标变更轨迹: 【{old_desc}】 ➔ 【{new_desc}】\n\n"
                f"★ 核心防线：不论哪一个 Agent 变更任务状态，都必须经过用户的明确确认，"
                f"防止 Agent 私自推进或跳过状态机生命周期。\n\n"
                f"决策指引：\n"
                f"• 点击【允许】：明确授权并批准本次状态流转；\n"
                f"• 点击【拒绝】：拦截本次篡改，保持原状态。"
            )
            return {"decision": "ask", "reason": reason}
        return None

    # 3. 多块文本替换 (multi_replace_file_content)
    if tool_name == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks", [])
        for chunk in chunks:
            tc = chunk.get("TargetContent", "")
            rc = chunk.get("ReplacementContent", "")
            old_s = extract_statuses(tc)
            new_s = extract_statuses(rc)
            if (old_s or new_s) and old_s != new_s:
                old_desc = ", ".join(old_s) if old_s else "(无状态)"
                new_desc = ", ".join(new_s) if new_s else "(无状态)"
                reason = (
                    f"【任务状态流转人工审批确认】\n"
                    f"检测到 Agent 正在尝试批量修改任务单状态：{filename}\n"
                    f"检测到变更轨迹: 【{old_desc}】 ➔ 【{new_desc}】\n\n"
                    f"★ 核心防线：不论哪一个 Agent 变更任务状态，都必须经过用户的明确确认。\n\n"
                    f"决策指引：\n"
                    f"• 点击【允许】：明确授权本次状态流转；\n"
                    f"• 点击【拒绝】：拦截本次篡改，保持原状态。"
                )
                return {"decision": "ask", "reason": reason}
        return None

    return None


def is_meta_file(target_file: str, workspace_root: str, config) -> bool:
    """识别 Quench 体系通用元数据文件（.agents、CHANGELOG、README），豁免拦截。"""
    resolved = resolve_realpath_under(workspace_root, target_file)
    if not resolved:
        return False

    norm_target = resolved.replace("\\", "/").lower()
    norm_root = _strip_long_path_prefix(os.path.realpath(workspace_root)).replace("\\", "/").lower()

    if norm_target.startswith(norm_root):
        rel_path = norm_target[len(norm_root):].lstrip("/")
    else:
        rel_path = norm_target

    # .agents 目录内的所有元文件
    if rel_path.startswith(".agents/") or rel_path == ".agents":
        return True

    # changelog 文件
    changelog_name = os.path.basename(config.changelog_path or "CHANGELOG.md").lower()
    if os.path.basename(norm_target) == changelog_name:
        return True

    # dev_tasks 目录内的规范说明文件（如 README.md）
    if os.path.basename(norm_target).lower() == "readme.md":
        dev_tasks_dir = config.resolve_path("dev_tasks_dir").replace("\\", "/").lower()
        if norm_target.startswith(dev_tasks_dir):
            return True

    return False


def is_whitelist_matched(config, target_file: str, workspace_root: str) -> bool:
    """第一层：静态配置白名单匹配（quench_stack.yaml fast_track_rules.allow_untracked_patterns）。"""
    patterns = config.get_fast_track_patterns()
    for pat in patterns:
        if matches_pattern(target_file, pat, workspace_root):
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
    if locked_session and incoming_conversation_id:
        if locked_session.strip().lower() != incoming_conversation_id.strip().lower():
            return False, f"跨会话冲突: 锁定会话 {locked_session} != 当前会话 {incoming_conversation_id}"

    # 过期失效检查（统一 UTC 时间戳比对与 aware/naive 兼容）
    expires_at = bypass_data.get("expires_at")
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            exp_dt_utc = exp_dt.astimezone(timezone.utc)
            if datetime.now(timezone.utc) > exp_dt_utc:
                return False, f"会话租约已超时过期 ({expires_at})"
        except Exception as e:
            return False, f"过期时间格式异常: {e}"

    return True, ""


def safe_clean_corrupted_bypass(bypass_path: str, logger: Optional[logging.Logger] = None) -> None:
    """原子化清理或重命名已失效/损坏的会话旁路文件，带 FileLock 保护。"""
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
        if os.path.isfile(bypass_path):
            try:
                os.remove(bypass_path)
            except Exception as e2:
                if logger:
                    logger.warning(f"降级删除旁路文件失败 {bypass_path}: {e2}", exc_info=True)


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
        target_file = args.get("TargetFile") or ""
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

        from project_config import load_project_config
        from state_machine import STATUS_IN_PROGRESS, parse_task_file

        config = load_project_config(workspace_root)
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")

        # 0. 物理路径归一原语解析（消解软链接、junction 与跨驱动器/相对路径逃逸）
        resolved_target = resolve_realpath_under(workspace_root, target_file)

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

        effective_target = resolved_target or target_file

        # 0.1 生产代码靶向识别（Dual-Track Boundary Engine）：非受管的纯文档/规划/素材天然豁免
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
            or "模型未在工具参数中填写修改理由"
        )

        # -------------------------------------------------------------
        # 情形 A：当前已有任务处于 🔨 执行中
        # -------------------------------------------------------------
        if active_task and active_file_path:
            with open(active_file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            task_id_pattern = re.escape(active_task.id)
            pattern = re.compile(
                rf"###\s+(?:任务|Task)\s+{task_id_pattern}\s+.*?####\s+(?:【涉及文件】|\[Affected Files\]|【Affected Files】)\s*```(.*?)```",
                re.DOTALL | re.IGNORECASE,
            )
            m = pattern.search(content)

            allowed_files = set()
            if m:
                raw_files_block = m.group(1).strip()
                for line in raw_files_block.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    cleaned = re.sub(r"^\[(MODIFY|NEW|DELETE|RENAME)\]\s*", "", line).strip()
                    cleaned = cleaned.split("（")[0].split("(")[0].strip()
                    if cleaned:
                        norm_path = os.path.normpath(os.path.join(workspace_root, cleaned)).lower()
                        allowed_files.add(norm_path)
                        allowed_files.add(os.path.normpath(cleaned).lower())

            target_norm = os.path.normpath(effective_target).lower()
            target_basename = os.path.basename(target_norm)

            is_in_allowed_scope = False
            if target_norm in allowed_files:
                is_in_allowed_scope = True
            else:
                for af in allowed_files:
                    if target_norm.endswith(af) or af.endswith(target_norm) or os.path.basename(af) == target_basename:
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
            f"No Quench task is currently in '🔨 In Progress' state, and the target file did not match any fast-track whitelist or session bypass rule.\n"
            f"当前工作区未处于任何 Quench 任务的“🔨 执行中”状态，且目标文件未命中快速通道白名单或会话旁路规则。\n\n"
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
