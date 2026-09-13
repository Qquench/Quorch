#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import glob
import json
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
server_dir = os.path.dirname(current_dir)
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


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

    try:
        workspace_paths = payload.get("workspacePaths", [])
        if not workspace_paths:
            print(json.dumps({}))
            return

        workspace_root = workspace_paths[0]
        config_path = os.path.join(workspace_root, ".agents", "quench_stack.yaml")
        if not os.path.isfile(config_path):
            print(json.dumps({}))
            return

        from project_config import load_project_config
        from state_machine import STATUS_IN_PROGRESS, parse_task_file

        config = load_project_config(workspace_root)
        dev_tasks_dir = config.resolve_path("dev_tasks_dir")

        if not os.path.isdir(dev_tasks_dir):
            print(json.dumps({}))
            return

        active_task = None
        active_file_name = None
        for md_file in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
            if os.path.basename(md_file).lower() == "readme.md":
                continue
            tasks = parse_task_file(md_file)
            for t in tasks:
                if t.status == STATUS_IN_PROGRESS:
                    active_task = t
                    active_file_name = os.path.basename(md_file)
                    break
            if active_task:
                break

        if active_task:
            reminder_msg = (
                f"【Quench DevTasks 上下文守卫】当前处于执行中的任务：\n"
                f"• 任务单: {active_file_name}\n"
                f"• 当前任务: Task {active_task.id} — {active_task.title}\n"
                f"• 执行纪律提醒: 仅修改【涉及文件】清单内的文件；保留现有注释与 docstring；改动核心逻辑必加单测断言。"
            )
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

        # 无执行中任务时，检查是否有处于 ⬜ 待确认 的任务
        from state_machine import STATUS_PENDING
        pending_count = 0
        latest_pending_file = None
        for md_file in sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True):
            if os.path.basename(md_file).lower() == "readme.md":
                continue
            tasks = parse_task_file(md_file)
            for t in tasks:
                if t.status == STATUS_PENDING:
                    pending_count += 1
                    if not latest_pending_file:
                        latest_pending_file = os.path.basename(md_file)

        if pending_count > 0:
            reminder_msg = (
                f"【Quench DevTasks 默认交接守卫】检测到任务单 {latest_pending_file} 存在 {pending_count} 项【⬜ 待确认】任务。\n"
                f"★ 核心纪律：双模型交接是默认流程（Default Golden Standard）！\n"
                f"1. 默认动作：起草完成或面对未审任务时，必须主动向用户输出规范的【Quench 任务交接卡】（⚠️ 排版硬性要求：必须直接使用 GitHub 原生引用块 `> [!NOTE]` 渲染，绝对严禁使用 ASCII 边框画图 `┌──┐`，绝对严禁套在 ```markdown 代码块中做成黑板报/展示板）；\n"
                f"2. 严禁自作主张询问用户是否由自己直接开工；\n"
                f"3. 唯一例外：仅当用户在提示词中显式明确要求“本单无需 Opus / 跳过 Opus / 直接执行”时，方可豁免交接。"
            )
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

    except Exception:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
