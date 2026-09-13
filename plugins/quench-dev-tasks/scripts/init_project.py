#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Ensure UTF-8 output on Windows
if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def init_project(project_root: str, project_name: str | None = None) -> None:
    """在 project_root 创建 .agents/plugins.json 和 .agents/quench_stack.yaml 模板。

    Args:
        project_root: 目标项目根目录路径。
        project_name: 项目名称，若未提供则默认使用 project_root 的文件夹名称。
    """
    root = os.path.abspath(project_root)
    if not os.path.isdir(root):
        print(f"❌ 错误: 目标项目根目录不存在: {root}", file=sys.stderr)
        sys.exit(1)

    effective_name = project_name or os.path.basename(root)

    # 1. 查找模板文件路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    plugin_dir = os.path.dirname(script_dir)
    plugins_parent_dir = os.path.dirname(plugin_dir)
    template_path = os.path.join(plugin_dir, "templates", "quench_stack.yaml")

    if not os.path.isfile(template_path):
        print(
            f"❌ 错误: Plugin 模板文件缺失: {template_path}\n"
            f"请检查 quench-dev-tasks Plugin 安装完整性。",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"🚀 开始在项目 [{effective_name}] ({root}) 初始化 Quench DevTasks 配置...")

    # 2. 创建 .agents 目录
    agents_dir = os.path.join(root, ".agents")
    os.makedirs(agents_dir, exist_ok=True)

    # 3. 配置 plugins.json
    plugins_json_path = os.path.join(agents_dir, "plugins.json")
    norm_plugins_parent = os.path.normpath(plugins_parent_dir)

    if os.path.isfile(plugins_json_path):
        try:
            with open(plugins_json_path, "r", encoding="utf-8") as f:
                plugins_data = json.load(f)
        except Exception:
            plugins_data = {}

        entries = plugins_data.setdefault("entries", [])
        already_configured = False
        for entry in entries:
            entry_path = entry.get("path", "")
            if os.path.normpath(entry_path).lower() == norm_plugins_parent.lower() or "quench-dev-tasks" in entry_path.lower():
                already_configured = True
                break

        if already_configured:
            print("ℹ️ .agents/plugins.json 已配置 quench-dev-tasks 插件路径，跳过添加。")
        else:
            entries.append({"path": norm_plugins_parent})
            with open(plugins_json_path, "w", encoding="utf-8") as f:
                json.dump(plugins_data, f, indent=2, ensure_ascii=False)
            print(f"✅ 已在 .agents/plugins.json 中添加插件路径: {norm_plugins_parent}")
    else:
        plugins_data = {
            "entries": [
                {"path": norm_plugins_parent}
            ]
        }
        with open(plugins_json_path, "w", encoding="utf-8") as f:
            json.dump(plugins_data, f, indent=2, ensure_ascii=False)
        print(f"✅ 已创建 .agents/plugins.json (注册插件路径: {norm_plugins_parent})")

    # 4. 创建 .agents/quench_stack.yaml
    stack_yaml_path = os.path.join(agents_dir, "quench_stack.yaml")
    if os.path.isfile(stack_yaml_path):
        print("ℹ️ .agents/quench_stack.yaml 已存在，跳过覆盖。")
    else:
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        # 替换项目名称占位符
        customized_content = re.sub(
            r'project_name:\s*"[^"]*"',
            f'project_name: "{effective_name}"',
            template_content,
            count=1,
        )

        with open(stack_yaml_path, "w", encoding="utf-8") as f:
            f.write(customized_content)
        print(f"✅ 已创建 .agents/quench_stack.yaml (项目名称: {effective_name})")

    # 5. 创建任务目录结构
    dev_tasks_dir = os.path.join(root, "docs", "dev_tasks")
    archive_dir = os.path.join(dev_tasks_dir, "archive")
    os.makedirs(dev_tasks_dir, exist_ok=True)
    os.makedirs(archive_dir, exist_ok=True)
    print(f"✅ 已确认任务目录结构: {dev_tasks_dir} 及 {archive_dir}")

    # 6. 初始化默认 README.md (如果不存在)
    readme_path = os.path.join(dev_tasks_dir, "README.md")
    if not os.path.isfile(readme_path):
        readme_content = f"""# {effective_name} 开发任务管理

本项目接入 Quench 开发任务治理体系（quench-dev-tasks）。

## 任务状态图例
- `⬜ 待确认`：新提出的需求或架构整改方案，待人工审核。
- `✅ 已确认`：已通过审查或用户确认，待进入开发流程。
- `🔨 执行中`：正在由模型领单执行中（单核执行，同一时间只允许一个任务处于此状态）。
- `✔️ 已完成`：通过完整分步改造及 DoD 自动化命令验证。
- `⏭️ 跳过`：由于环境变动或需求废弃暂缓执行。
- `🔄 需返工`：在测试或审查中发现缺陷，需要退回重新整改。

## 常用交互
- 查阅进度：AI 调用 `dev_tasks_status`
- 领取任务：AI 调用 `dev_tasks_checkout`
- 标记完成：AI 调用 `dev_tasks_complete`
- 归档历史：AI 调用 `dev_tasks_archive`
"""
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(readme_content)
        print("✅ 已生成 docs/dev_tasks/README.md 说明文档。")

    print(f"\n🎉 项目 [{effective_name}] 初始化完成！随时可在 Antigravity IDE 中开始开发。")


def main():
    parser = argparse.ArgumentParser(
        description="Quench DevTasks 项目接入初始化脚本：为目标项目生成 .agents 插件注册与配置清单。"
    )
    parser.add_argument(
        "project_root",
        help="目标项目根目录路径（必须是已存在的目录）",
    )
    parser.add_argument(
        "--name",
        dest="project_name",
        default=None,
        help="项目名称（可选，默认使用目标目录文件夹名）",
    )

    args = parser.parse_args()
    init_project(args.project_root, args.project_name)


if __name__ == "__main__":
    main()
