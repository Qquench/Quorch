#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import glob
import json
import os
import re
import sys
from typing import Optional, List, Tuple
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


def is_task_file(target_file: str, workspace_root: str, config) -> bool:
    """判断是否为 dev_tasks 目录下的任务单文件（排除规范说明 README.md）。"""
    if not target_file or not target_file.lower().endswith(".md"):
        return False
    if os.path.basename(target_file).lower() == "readme.md":
        return False

    norm_target = os.path.normpath(target_file).replace("\\", "/").lower()
    norm_root = os.path.normpath(workspace_root).replace("\\", "/").lower()

    dev_tasks_dir = config.resolve_path("dev_tasks_dir").replace("\\", "/").lower()
    if norm_target.startswith(dev_tasks_dir):
        return True

    rel_dev_tasks = (config.dev_tasks_dir or "docs/dev_tasks").replace("\\", "/").lower().strip("/")
    if norm_target.startswith(norm_root):
        rel_path = norm_target[len(norm_root):].lstrip("/")
    else:
        rel_path = norm_target

    if rel_path.startswith(rel_dev_tasks + "/") or rel_path == rel_dev_tasks:
        return True

    return False


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
    norm_target = os.path.normpath(target_file).replace("\\", "/").lower()
    norm_root = os.path.normpath(workspace_root).replace("\\", "/").lower()

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


def safe_clean_corrupted_bypass(bypass_path: str) -> None:
    """原子化清理或重命名已失效/损坏的会话旁路文件，带 FileLock 保护。"""
    lock_file = bypass_path + ".lock"
    try:
        with FileLock(lock_file, timeout=5.0):
            if os.path.isfile(bypass_path):
                try:
                    os.remove(bypass_path)
                except Exception:
                    pass
    except Exception:
        if os.path.isfile(bypass_path):
            try:
                os.remove(bypass_path)
            except Exception:
                pass


def is_session_bypass_matched(
    workspace_root: str, target_file: str, current_conversation_id: Optional[str] = None
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
            except Exception:
                # 畸形 JSON 文件，自愈清理
                try:
                    os.remove(bypass_file)
                except Exception:
                    pass
                return False

            is_valid, reject_reason = verify_session_integrity(data, current_conversation_id)
            if not is_valid:
                # 校验未通过（跨会话或已过期或损坏），清理旁路文件
                try:
                    os.remove(bypass_file)
                except Exception:
                    pass
                return False

            patterns = data.get("patterns", [])
            for pat in patterns:
                if matches_pattern(target_file, pat, workspace_root):
                    return True
    except Timeout:
        # FileLock 超时，为安全防线起见不放行
        return False
    except Exception:
        return False

    return False


def main():
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

        env_type = EnvironmentDetector.detect(payload, workspace_root=workspace_root)
        adapter = get_adapter(env_type, workspace_root=workspace_root)

        def emit_decision(decision: str, reason: str = "") -> None:
            out = adapter.format_decision(decision, reason)
            if isinstance(out, dict):
                print(json.dumps(out))
            else:
                print(out)
                if decision in ("deny", "ask") and not adapter.supports_interactive_ask():
                    sys.exit(1)

        tool_call = payload.get("toolCall", {})
        args = tool_call.get("args", {})
        target_file = args.get("TargetFile")
        conversation_id = adapter.extract_session_id(payload)

        if not workspace_paths or not target_file:
            emit_decision("allow")
            return

        workspace_root = workspace_paths[0]
        config_path = os.path.join(workspace_root, ".agents", "quench_stack.yaml")
        if not os.path.isfile(config_path):
            # 非 Quench 纳管项目，静默放行
            emit_decision("allow")
            return

        from project_config import load_project_config
        from state_machine import STATUS_IN_PROGRESS, parse_task_file

        config = load_project_config(workspace_root)
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")

        tool_name = tool_call.get("name", "")

        # 0. 任务单文件状态强守卫（严防任何 Agent 擅自修改状态，或初稿私自越级设为已确认）
        if is_task_file(target_file, workspace_root, config):
            guard_decision = check_task_status_guard(target_file, tool_name, args)
            if guard_decision:
                emit_decision(guard_decision.get("decision", "ask"), guard_decision.get("reason", ""))
                return
            # 任务单非状态内容编辑（如补充步骤细节、完善说明），直接放行
            emit_decision("allow")
            return

        # 0.1 治理通用元数据文件豁免（.agents 配置文件、CHANGELOG、README）
        if is_meta_file(target_file, workspace_root, config):
            emit_decision("allow")
            return

        # 0.1 生产代码靶向识别（Dual-Track Boundary Engine）：非受管的纯文档/规划/素材天然豁免
        if hasattr(config, "is_path_governed") and not config.is_path_governed(target_file):
            emit_decision("allow")
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
                rf"###\s+(?:任务|Task)\s+{task_id_pattern}\s+.*?####\s+【涉及文件】\s*```(.*?)```",
                re.DOTALL,
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

            target_norm = os.path.normpath(target_file).lower()
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
                emit_decision("allow")
                return

            # 任务外文件，先检查 Layer 1 静态白名单与 Layer 2 会话旁路（含会话锁核验）
            if is_whitelist_matched(config, target_file, workspace_root):
                emit_decision("allow")
                return

            if is_session_bypass_matched(workspace_root, target_file, conversation_id):
                emit_decision("allow")
                return

            # 触发任务越界拦截提示
            reason = (
                f"【范围外修改拦截】当前执行中的任务（Task {active_task.id}: {active_task.title}）"
                f"规划的文件列表中未包含此文件。\n\n"
                f"📁 目标文件: {target_file}\n"
                f"💡 模型给出的修改理由: {desc}\n\n"
                f"若确属规划遗漏请点击【允许】，若属非预期变动请点击【拒绝】。"
            )
            emit_decision("ask", reason)
            return

        # -------------------------------------------------------------
        # 情形 B：当前无任务处于 🔨 执行中（空载改动）
        # -------------------------------------------------------------
        # 第一层：检查静态白名单（配置文件）
        if is_whitelist_matched(config, target_file, workspace_root):
            emit_decision("allow")
            return

        # 第二层：检查动态会话旁路（.agents/.quench_bypass.json，含会话锁核验）
        if is_session_bypass_matched(workspace_root, target_file, conversation_id):
            emit_decision("allow")
            return

        # 第三层：交互式弹窗向用户确认（Ask Modal）
        reason = (
            f"【未纳管代码修改确认】\n"
            f"当前工作区未处于任何 Quench 任务的“🔨 执行中”状态，且目标文件未命中快速通道白名单或会话旁路规则。\n\n"
            f"📁 目标文件: {target_file}\n"
            f"💡 模型修改理由: {desc}\n\n"
            f"请进行决策：\n"
            f"• 点击【允许】：仅对本次修改单次放行（临时微调）；\n"
            f"• 点击【拒绝】：拦截本次修改。如需批量微调，可对 Agent 发送“开启样式快速通道”或领单正式任务。"
        )
        emit_decision("ask", reason)

    except Exception:
        # 防御兜底：Hook 绝不能崩溃导致 IDE 流程死锁
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
