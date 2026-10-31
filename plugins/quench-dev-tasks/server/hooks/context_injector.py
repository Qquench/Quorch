#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import glob
import json
import os
import sys
from typing import Any, Dict, Final, List, Optional, Tuple

current_dir = os.path.dirname(os.path.abspath(__file__))
server_dir = os.path.dirname(current_dir)
if os.path.normpath(os.path.join(server_dir, "..", "scripts")) not in sys.path:
    sys.path.insert(0, os.path.normpath(os.path.join(server_dir, "..", "scripts")))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_RELAY_STATES: Final[frozenset[str]] = frozenset({
    "PROPOSE",
    "REVIEW",
    "CONFIRM",
    "CHECKOUT",
    "DISPATCH_RUNNER",
    "SYNC_DOCS",
    "ARCHIVE",
    "NEXT_BATCH_PROPOSE",
})

_HALT_STATES: Final[frozenset[str]] = frozenset({
    "PAUSE_FOR_ACCEPTANCE",
    "BLOCKED",
    "ROADMAP_DONE",
})

_STOP_HOOK_RELAY_STATES: Final[frozenset[str]] = frozenset({
    "REVIEW",
    "CONFIRM",
    "CHECKOUT",
    "DISPATCH_RUNNER",
    "ARCHIVE",
    "NEXT_BATCH_PROPOSE",
})


def _is_external_api_available(workspace_root: str) -> bool:
    try:
        from project_config import load_project_config
        from reviewer_client import ReviewerClient
        config = load_project_config(workspace_root)
        re_cfg = getattr(config, "reviewer_engine", config)
        client = ReviewerClient(re_cfg)
        return bool(client.resolve_api_key()) or client.is_available()
    except Exception:
        return False


def _resolve_harness_baton(
    workspace_root: str,
    dev_tasks_dir: str,
    active_task_file: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """从 Autopilot Harness 决策 SSOT 探查当前接力动作与指引。
    Fail-Safe: 任何异常或不可用时返回 (None, None)。
    """
    try:
        from runtime_mode import load_runtime_mode
        from autopilot_harness import (
            compute_next_action,
            TaskStateSnapshot,
        )
        from state_machine import parse_task_file

        snapshot = load_runtime_mode(
            workspace_root,
            external_api_available=_is_external_api_available(workspace_root),
        )
        task_states: List[TaskStateSnapshot] = []
        target_file = None

        if active_task_file:
            tf_path = os.path.join(dev_tasks_dir, active_task_file)
            if os.path.isfile(tf_path):
                tasks = parse_task_file(tf_path)
                for t in tasks:
                    task_states.append(
                        TaskStateSnapshot(task_id=str(t.id), status=t.status, title=t.title)
                    )
                target_file = active_task_file
        else:
            md_files = [
                f for f in glob.glob(os.path.join(dev_tasks_dir, "*.md"))
                if os.path.basename(f).lower() != "readme.md"
            ]
            if md_files:
                md_files.sort(key=os.path.getmtime, reverse=True)
                latest_f = md_files[0]
                tasks = parse_task_file(latest_f)
                for t in tasks:
                    task_states.append(
                        TaskStateSnapshot(task_id=str(t.id), status=t.status, title=t.title)
                    )
                target_file = os.path.basename(latest_f)

        if not task_states:
            return None, None

        action, _ = compute_next_action(
            task_states=task_states,
            effective_mode=snapshot.effective_mode,
            reviewer_channel=snapshot.effective_reviewer_channel,
            mode_source=snapshot.mode_source,
            stop_at=snapshot.autopilot.stop_at,
            stop_at_consumed=snapshot.autopilot.consumed,
            consumed_for=snapshot.autopilot.consumed_for,
            current_task_id=None,
            task_file=target_file,
        )
        return action.action, action.instruction
    except Exception as exc:
        if os.environ.get("QUENCH_HOOK_DEBUG"):
            sys.stderr.write(f"[context_injector] _resolve_harness_baton failed: {exc}\n")
        return None, None


def _build_reminder(
    harness_state: Optional[str],
    harness_instruction: Optional[str],
    active_task: Optional[Any],
    active_file_name: Optional[str],
    pending_count: int,
    latest_pending_file: Optional[str],
) -> Optional[str]:
    """构建注入提醒文案（纯函数逻辑）：
    - 存在 active_task: 下发执行纪律提醒；
    - harness_state in _RELAY_STATES: 下发正向接力指引（抑制过时 C3/交接卡提醒）；
    - harness_state in _HALT_STATES: 下发停靠/交付提醒（规范格式 > [!IMPORTANT]）；
    - harness_state is None 且 pending_count > 0: 回退到待确认提醒；
    - 其他: 返回 None。
    """
    if active_task:
        return (
            f"【Quench DevTasks 上下文守卫】当前处于执行中的任务：\n"
            f"• 任务单: {active_file_name}\n"
            f"• 当前任务: Task {active_task.id} — {active_task.title}\n"
            f"• 执行纪律提醒: 仅修改【涉及文件】清单内的文件；保留现有注释与 docstring；改动核心逻辑必加单测断言。"
        )

    if harness_state in _RELAY_STATES:
        inst = harness_instruction or "请直接遵照流水线接力指示继续推进。"
        return (
            f"【Quench Autopilot 接力守卫】当前处于 Autopilot 全自动流转状态（动作: {harness_state}）：\n"
            f"• 接力指引: {inst}\n"
            f"• 执行纪律: 当前处于连续接力流转状态，严禁中途非预期停机抛出交接卡（AGENTS.md §6 与纪律 §8）。"
        )

    if harness_state in _HALT_STATES:
        inst = harness_instruction or "当前已到达 Autopilot 停靠断点/终态。"
        return (
            f"【Quench Autopilot 停靠提醒】当前已到达停靠断点/终态（动作: {harness_state}）：\n"
            f"• 状态指引: {inst}\n"
            f"• 交付契约: 请按 §4 Handoff Card / §8 C3 Delivery Card 格式（必须使用 > [!IMPORTANT] 引用块）结束本轮并输出交付卡。"
        )

    if pending_count > 0:
        return (
            f"【Quench DevTasks 待确认任务提醒】检测到任务单 {latest_pending_file} 存在 {pending_count} 项【⬜ 待确认】任务。\n"
            f"• 提示: 任务需要确认后方可施工。请调用 dev_tasks_status 检查状态或调用 dev_tasks_confirm 进行确认。"
        )

    return None


def _handle_stop_event(payload: dict) -> dict:
    """处理 Stop Hook 事件：六重护栏校验下的单次熔断续跑决策。
    Fail-Safe: 任何异常或校验未通过时恒定输出 {"decision": "allow"}。
    """
    try:
        # Guardrail 1: 必须含 terminationReason
        if "terminationReason" not in payload:
            return {"decision": "allow"}

        # Guardrail 2: 必须满足 terminationReason == "NO_TOOL_CALL" 且 fullyIdle is True
        term_reason = payload.get("terminationReason")
        fully_idle = payload.get("fullyIdle")
        if term_reason != "NO_TOOL_CALL" or fully_idle is not True:
            return {"decision": "allow"}

        # Guardrail 3: 子代理会话零干扰（lastUserInput 含 [QUENCH-DISPATCH:）
        last_user_input = str(payload.get("lastUserInput") or "")
        if "[QUENCH-DISPATCH:" in last_user_input:
            return {"decision": "allow"}

        # 解析 workspace_root
        workspace_paths = payload.get("workspacePaths", [])
        if not workspace_paths or not isinstance(workspace_paths, list):
            return {"decision": "allow"}
        workspace_root = workspace_paths[0]
        if not workspace_root or not os.path.isdir(workspace_root):
            return {"decision": "allow"}

        # 触发一次静默配置自愈
        try:
            from config_sync import auto_heal_configs
            auto_heal_configs(workspace_root=workspace_root, quiet=True)
        except Exception:
            pass

        # Guardrail 4: 工作区必须存在活跃 .agents/quench_stack.yaml 且 docs/dev_tasks/ 下至少存在 1 个任务单文件
        config_path = os.path.join(workspace_root, ".agents", "quench_stack.yaml")
        if not os.path.isfile(config_path):
            return {"decision": "allow"}

        from project_config import load_project_config
        config = load_project_config(workspace_root)
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")
        if not os.path.isdir(dev_tasks_dir):
            return {"decision": "allow"}

        md_files = [
            f for f in glob.glob(os.path.join(dev_tasks_dir, "*.md"))
            if os.path.basename(f).lower() != "readme.md"
        ]
        if not md_files:
            return {"decision": "allow"}

        # 寻找最新任务单
        md_files.sort(key=os.path.getmtime, reverse=True)
        target_file = os.path.basename(md_files[0])

        # Guardrail 5: autopilot.stop_at == "none" 且 harness_state in _STOP_HOOK_RELAY_STATES
        from runtime_mode import load_runtime_mode
        snapshot = load_runtime_mode(
            workspace_root,
            external_api_available=_is_external_api_available(workspace_root),
        )
        if snapshot.autopilot.stop_at != "none":
            return {"decision": "allow"}

        harness_state, harness_instruction = _resolve_harness_baton(
            workspace_root, dev_tasks_dir, target_file
        )
        if not harness_state or harness_state not in _STOP_HOOK_RELAY_STATES:
            return {"decision": "allow"}

        # Guardrail 6: 基于 .agents/.quench_stop_guard.json（FileLock 保护，最多保留 64 条最近键）记录指纹
        conversation_id = payload.get("conversationId") or payload.get("conversation_id") or "default_session"
        fingerprint = f"{conversation_id}::{target_file}::{harness_state}"

        agents_dir = os.path.join(workspace_root, ".agents")
        os.makedirs(agents_dir, exist_ok=True)
        guard_file = os.path.join(agents_dir, ".quench_stop_guard.json")
        lock_file = os.path.join(agents_dir, ".quench_stop_guard.json.lock")

        from filelock import FileLock, Timeout
        try:
            with FileLock(lock_file, timeout=5.0):
                records: dict = {}
                if os.path.isfile(guard_file):
                    try:
                        with open(guard_file, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                        if isinstance(raw, dict) and isinstance(raw.get("history"), dict):
                            records = raw["history"]
                        elif isinstance(raw, dict):
                            records = raw
                    except Exception:
                        records = {}

                # 检查指纹：若已存在则熔断放行（最多只续跑 1 次）
                if fingerprint in records:
                    return {"decision": "allow"}

                # 首次触发：记录指纹并保留最多 64 条
                records[fingerprint] = 1
                while len(records) > 64:
                    oldest = next(iter(records))
                    del records[oldest]

                from config_sync import atomic_write_file
                atomic_write_file(
                    guard_file,
                    json.dumps({"history": records}, indent=2, ensure_ascii=False) + "\n"
                )

                reason_msg = f"Autopilot relay '{harness_state}' active: {harness_instruction or 'Please continue next relay step in-band without stopping.'}"
                return {
                    "decision": "continue",
                    "reason": reason_msg,
                }
        except (Timeout, Exception) as lock_exc:
            if os.environ.get("QUENCH_HOOK_DEBUG"):
                sys.stderr.write(f"[context_injector] stop guard lock error: {lock_exc}\n")
            return {"decision": "allow"}

    except Exception as exc:
        if os.environ.get("QUENCH_HOOK_DEBUG"):
            sys.stderr.write(f"[context_injector] _handle_stop_event error: {exc}\n")
        return {"decision": "allow"}


def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print(json.dumps({}))
            return

        payload = json.loads(raw_input)
    except Exception:
        print(json.dumps({}))
        return

    if isinstance(payload, dict) and "terminationReason" in payload:
        res = _handle_stop_event(payload)
        print(json.dumps(res))
        return

    try:
        workspace_paths = payload.get("workspacePaths", [])
        if not workspace_paths:
            print(json.dumps({}))
            return

        workspace_root = workspace_paths[0]

        # 跨仓库静默自愈：若上游模板有更新，立即重新渲染 mcp_config.json 与 hooks.json
        try:
            __import__("config_sync").auto_heal_configs(workspace_root=workspace_root)
        except Exception:
            pass

        config_path = os.path.join(workspace_root, ".agents", "quench_stack.yaml")
        if not os.path.isfile(config_path):
            print(json.dumps({}))
            return

        from project_config import load_project_config
        from state_machine import STATUS_IN_PROGRESS, STATUS_PENDING, parse_task_file

        config = load_project_config(workspace_root)
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")

        if not os.path.isdir(dev_tasks_dir):
            print(json.dumps({}))
            return

        active_task = None
        active_file_name = None
        pending_count = 0
        latest_pending_file = None

        for md_file in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
            if os.path.basename(md_file).lower() == "readme.md":
                continue
            try:
                tasks = parse_task_file(md_file)
            except Exception:
                continue

            for t in tasks:
                if t.status == STATUS_IN_PROGRESS and not active_task:
                    active_task = t
                    active_file_name = os.path.basename(md_file)
                elif t.status == STATUS_PENDING:
                    pending_count += 1
                    if not latest_pending_file:
                        latest_pending_file = os.path.basename(md_file)

        # 探查 Autopilot 接力状态
        harness_state, harness_instruction = _resolve_harness_baton(
            workspace_root, dev_tasks_dir, active_file_name or latest_pending_file
        )

        reminder_msg = _build_reminder(
            harness_state=harness_state,
            harness_instruction=harness_instruction,
            active_task=active_task,
            active_file_name=active_file_name,
            pending_count=pending_count,
            latest_pending_file=latest_pending_file,
        )

        if reminder_msg:
            print(
                json.dumps(
                    {
                        "injectSteps": [
                            {
                                "ephemeralMessage": reminder_msg
                            }
                        ]
                    }
                )
            )
            return

        print(json.dumps({}))

    except Exception as exc:
        if os.environ.get("QUENCH_HOOK_DEBUG"):
            sys.stderr.write(f"[context_injector] main uncaught error: {exc}\n")
        print(json.dumps({}))


if __name__ == "__main__":
    main()
