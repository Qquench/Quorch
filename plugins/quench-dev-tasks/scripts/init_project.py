#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# Ensure UTF-8 output on Windows
if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def diagnose_environment(project_root: str) -> dict:
    """全面诊断目标项目的治理环境就绪状态。
    返回结构: {
        "is_git_repo": bool,
        "has_quench_stack": bool,
        "has_plugins_json": bool,
        "python_valid": bool,
        "dependencies_ready": bool,
        "issues": list[str],
        "suggestions": list[str]
    }
    """
    root = os.path.abspath(project_root)
    issues: list[str] = []
    suggestions: list[str] = []

    # 1. 检查目标目录是否存在
    if not os.path.isdir(root):
        issues.append(f"目标项目根目录不存在: {root}")
        suggestions.append("请提供已存在的项目目录路径")
        return {
            "is_git_repo": False,
            "has_quench_stack": False,
            "has_plugins_json": False,
            "python_valid": sys.version_info >= (3, 8),
            "dependencies_ready": False,
            "issues": issues,
            "suggestions": suggestions,
        }

    # 2. 检查 Git 仓库有效性
    is_git_repo = False
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and "true" in (res.stdout or "").strip().lower():
            is_git_repo = True
        else:
            issues.append("目标目录不是 Git 仓库（缺少 .git 目录）")
            suggestions.append("在项目根目录执行 'git init' 初始化版本控制")
    except FileNotFoundError:
        issues.append("git 命令未找到，请安装 Git 或将其添加到系统 PATH")
        suggestions.append("安装 Git 并配置系统环境变量 PATH: https://git-scm.com/")
    except Exception as e:
        issues.append(f"Git 检测失败: {e}")
        suggestions.append("请确保 Git 已安装并在项目目录中可用")

    # 3. 检查 .agents/quench_stack.yaml
    quench_stack_path = os.path.join(root, ".agents", "quench_stack.yaml")
    has_quench_stack = os.path.isfile(quench_stack_path)
    if not has_quench_stack:
        issues.append("缺少 Quench 核心配置文件: .agents/quench_stack.yaml")
        suggestions.append(f"运行 'python {os.path.abspath(__file__)} {project_root}' 初始化配置文件")

    # 4. 检查 .agents/plugins.json
    plugins_json_path = os.path.join(root, ".agents", "plugins.json")
    has_plugins_json = os.path.isfile(plugins_json_path)
    if not has_plugins_json:
        issues.append("缺少插件注册文件: .agents/plugins.json")
        suggestions.append(f"运行 'python {os.path.abspath(__file__)} {project_root}' 注册插件")

    # 5. 检查 Python 版本
    python_valid = sys.version_info >= (3, 8)
    if not python_valid:
        py_ver_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        issues.append(f"当前 Python 版本 ({py_ver_str}) 过低，推荐 Python >= 3.8")
        suggestions.append("请升级 Python 运行环境至 3.8 或更高版本")

    # 6. 检查关键依赖库
    missing_deps = []
    for dep in ["fastmcp", "yaml", "filelock"]:
        try:
            __import__(dep)
        except ImportError:
            missing_deps.append(dep)

    dependencies_ready = (len(missing_deps) == 0)
    if not dependencies_ready:
        issues.append(f"缺少关键 Python 依赖库: {', '.join(missing_deps)}")
        suggestions.append(f"在当前运行环境中执行: pip install {' '.join(missing_deps)}")

    return {
        "is_git_repo": is_git_repo,
        "has_quench_stack": has_quench_stack,
        "has_plugins_json": has_plugins_json,
        "python_valid": python_valid,
        "dependencies_ready": dependencies_ready,
        "issues": issues,
        "suggestions": suggestions,
    }


def print_diagnostic_report(diag: dict, project_root: str) -> None:
    root = os.path.abspath(project_root)
    print("=" * 60)
    print(f"🏥 Quench DevTasks 治理环境体检报告: {root}")
    print("=" * 60)
    print(f"• Git 仓库有效性:   {'✅ 是' if diag['is_git_repo'] else '❌ 否'}")
    print(f"• 核心配置文件:     {'✅ 已存在 (.agents/quench_stack.yaml)' if diag['has_quench_stack'] else '❌ 缺失'}")
    print(f"• 插件注册清单:     {'✅ 已就绪 (.agents/plugins.json)' if diag['has_plugins_json'] else '❌ 缺失'}")
    print(f"• Python 运行环境:  {'✅ 合格 (>= 3.8)' if diag['python_valid'] else '❌ 版本过低'}")
    print(f"• 关键依赖库就绪:   {'✅ 全部就绪 (fastmcp, yaml, filelock)' if diag['dependencies_ready'] else '❌ 缺失部分依赖'}")
    print("-" * 60)
    if not diag["issues"]:
        print("🎉 恭喜！当前项目治理环境完全就绪，可无缝使用 Quench DevTasks。")
    else:
        print("⚠️ 诊断发现以下潜在问题与建议:")
        for idx, issue in enumerate(diag["issues"], 1):
            sugg = diag["suggestions"][idx - 1] if idx - 1 < len(diag["suggestions"]) else ""
            print(f"  {idx}. [问题] {issue}")
            if sugg:
                print(f"     [建议] {sugg}")
    print("=" * 60)


def init_project(project_root: str, project_name: str | None = None, force: bool = False) -> None:
    """在 project_root 创建 .agents/plugins.json 和 .agents/quench_stack.yaml 模板。

    Args:
        project_root: 目标项目根目录路径。
        project_name: 项目名称，若未提供则默认使用 project_root 的文件夹名称。
        force: 是否强制覆盖已有 quench_stack.yaml 配置文件。
    """
    root = os.path.abspath(project_root)
    if not os.path.isdir(root):
        print(f"❌ 错误: 目标项目根目录不存在: {root}", file=sys.stderr)
        sys.exit(1)

    effective_name = project_name or os.path.basename(root)

    # 0. 检查 Git 仓库（友好提示但不强阻断）
    is_git = False
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and "true" in (res.stdout or "").strip().lower():
            is_git = True
    except Exception:
        pass

    if not is_git:
        print("⚠️ 提示: 目标目录暂未初始化为 Git 仓库。建议初始化完成后运行 'git init' 以获得完整的规范守卫能力。")

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
    if os.path.isfile(stack_yaml_path) and not force:
        print("ℹ️ .agents/quench_stack.yaml 已存在，跳过覆盖。如需更新请使用版本迁移检查或配合 --force 覆盖。")
    else:
        if os.path.isfile(stack_yaml_path) and force:
            print("⚠️ 检测到 --force 参数，正在覆盖已有 .agents/quench_stack.yaml...")
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
        description="Quench DevTasks 项目接入初始化脚本：为目标项目生成 .agents 插件注册与配置清单，或诊断环境就绪状态。"
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="目标项目根目录路径（默认当前目录）",
    )
    parser.add_argument(
        "--name",
        dest="project_name",
        default=None,
        help="项目名称（可选，默认使用目标目录文件夹名）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="健康体检模式：全面诊断目标项目的治理环境就绪状态",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制覆盖已有的 quench_stack.yaml（默认不覆盖）",
    )

    args = parser.parse_args()

    if args.check:
        diag = diagnose_environment(args.project_root)
        print_diagnostic_report(diag, args.project_root)
        return

    init_project(args.project_root, args.project_name, force=args.force)


if __name__ == "__main__":
    main()
