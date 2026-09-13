#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quench Cursor Rules Exporter.

从 rules/dev-tasks-discipline.md 动态提取精炼的核心纪律 Prompt，
并自动输出为兼容旧版 Cursor 的 .cursorrules 与兼容最新 Cursor MDC 规范的
.cursor/rules/quench-dev-tasks.mdc 规则文件。
"""
from __future__ import annotations

import argparse
import os
import sys

# Windows UTF-8 console defense
if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

DEFAULT_FALLBACK_RULES = """# Quench DevTasks Core Developer Discipline / 核心常驻开发纪律 (Cursor Agent Guidelines)

As an AI coding assistant operating within a Quench-governed project, you MUST strictly adhere to the following core disciplines:
（作为在接入 Quench 治理体系项目中工作的 AI 编程助手，你必须严格执行以下核心纪律约束：）

## 1. Task Status & Checkout Discipline / 任务状态与领单纪律
- **No Unmanaged Code Modification / 严禁擅自修改生产代码**：Do NOT modify any production source code before checking out a task (status MUST be `🔨 执行中`). （在未检出任务，状态未处于 `🔨 执行中` 前，严禁修改任何生产源代码。）
- **State Transition via MCP Tools / 通过 MCP 工具流转状态**：MUST transition task states through MCP tools (dev_tasks_status, dev_tasks_checkout, dev_tasks_complete, dev_tasks_archive). Direct manual text replacement of task status emojis is prohibited. （必须通过 MCP 工具流转状态，严禁直接文本替换修改任务状态 Emoji。）
- **Single Active Task Serial Execution / 单任务串行执行**：Only ONE task is permitted to be in `🔨 执行中` state globally at any given moment. （全局同一时刻仅允许一个任务处于 `🔨 执行中`。）

## 2. Implementation Scope & Affected Files Whitelist / 代码施工与涉及文件白名单
- **Strict Adherence to Whitelist / 严格遵循【涉及文件】白名单**：All code changes are strictly restricted to the files listed under 【涉及文件】/ [Affected Files]. If additional files need modification, halt and prompt the developer to update the task whitelist first. （修改代码时，严格受限于当前任务单中【涉及文件】清单。若发现需要修改范围外文件，必须先停止并向开发者提示扩充任务单白名单。）
- **Mandatory Test Assertions / 改动业务逻辑必加单测**：Modifications to core logic, algorithms, or API contracts MUST include unit test assertions in the test directory, validated via 【DoD 验证命令】/ [DoD Commands]. （凡是修改核心业务逻辑、算法或接口行为，必须在测试目录追加单测断言，并在【DoD 验证命令】中验证通过，杜绝隐蔽回归。）
- **Preserve Architecture & Comments / 保留架构设计与注释**：Preserve existing architecture comments and type annotations. （不得擅自删除既有代码架构注释与类型注解。）

## 3. Physical Pre-Commit Guard / Git Commit 物理硬防线配合
- Pre-commit guard is enabled. Git commits modifying files outside the active task scope or without an active task will be physically blocked. （本项目已启用 Git Pre-commit 守卫。若未检出任务或提交了任务单范围外的代码修改，git commit 将被物理拦截阻断。）
"""


class RulesExporter:
    """Extract Quench resident discipline and render as Cursor rules. / 提取 Quench 常驻纪律并渲染为 Cursor 规范配置。"""

    @staticmethod
    def resolve_discipline_path(discipline_path: str | None = None) -> str:
        """Resolve absolute discipline_path with fallback support. / 解析 discipline_path 绝对路径，支持缺省定位与相对路径移植。"""
        if discipline_path:
            norm = os.path.abspath(discipline_path)
            if os.path.isfile(norm):
                return norm
            # 尝试相对于 plugin_dir 解析
            script_dir = os.path.dirname(os.path.abspath(__file__))
            plugin_dir = os.path.dirname(script_dir)
            rel_in_plugin = os.path.normpath(os.path.join(plugin_dir, discipline_path))
            if os.path.isfile(rel_in_plugin):
                return rel_in_plugin
            # 若显式传入的路径在任何候选位置都找不到，返回空
            return ""

        # 基于本脚本位置相对定位: ../rules/dev-tasks-discipline.md
        script_dir = os.path.dirname(os.path.abspath(__file__))
        plugin_dir = os.path.dirname(script_dir)
        candidate = os.path.normpath(
            os.path.join(plugin_dir, "rules", "dev-tasks-discipline.md")
        )
        if os.path.isfile(candidate):
            return candidate

        return ""

    @classmethod
    def extract_condensed_rules(cls, discipline_path: str | None = None) -> str:
        """从 dev-tasks-discipline.md 中提炼精炼的自然语言约束 Prompt，失败时启用内置 Fallback。"""
        real_path = cls.resolve_discipline_path(discipline_path)
        if not real_path:
            return DEFAULT_FALLBACK_RULES.strip()

        try:
            with open(real_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            if not content.strip():
                return DEFAULT_FALLBACK_RULES.strip()

            header = (
                "# Quench DevTasks 核心常驻开发纪律 (Cursor Agent Guidelines)\n\n"
                "> 本文件由 Quench Rules Exporter 自动从 rules/dev-tasks-discipline.md 提取生成。\n\n"
            )
            rules_body = [
                header,
                "## 1. 任务领单与状态机推进\n",
                "- **未领单严禁动源码**：在开始修改任何生产代码前，必须确保当前工作区处于对应任务的 `🔨 执行中` 状态；\n",
                "- **调用 MCP 工具流转**：通过 `dev_tasks_status` 查看任务，通过 `dev_tasks_checkout` 领单，通过 `dev_tasks_complete` 报竣，严禁手动篡改 Markdown 图标；\n",
                "- **单核串行施工**：全局一次只能有一个任务处于 `🔨 执行中`。\n\n",
                "## 2. 涉及文件白名单与质量底线\n",
                "- **严格遵守【涉及文件】白名单**：代码修改范围必须完全落在当前任务单【涉及文件】清单内，严禁越界修改未纳管文件；\n",
                "- **改逻辑必加单测断言**：凡是修改核心业务逻辑、契约或算法，必须在测试目录追加单测，杜绝功能回归；\n",
                "- **保持架构注释完整**：严禁随意删除已有的架构说明、docstring 与类型标注。\n\n",
                "## 3. Git Commit 物理硬防线配合\n",
                "- 本项目已挂载 Git Pre-commit Guard，越界提交或未检出提交将被底层命令直接 `exit 1` 拦截；\n",
                "- 如需扩大修改范围，请先更新任务单【涉及文件】清单后再行施工提交。\n",
            ]
            return "".join(rules_body).strip()
        except Exception:
            return DEFAULT_FALLBACK_RULES.strip()

    @classmethod
    def export_cursorrules(
        cls, discipline_path: str | None, output_path: str, force: bool = False
    ) -> str:
        """输出兼容旧版 Cursor 的 .cursorrules 文件。"""
        out_abs = os.path.abspath(output_path)
        if os.path.isfile(out_abs) and not force:
            print(f"ℹ️ {out_abs} 已存在，跳过覆盖（使用 --force 可强制覆盖）。")
            return out_abs

        parent = os.path.dirname(out_abs)
        if parent:
            os.makedirs(parent, exist_ok=True)

        rules_text = cls.extract_condensed_rules(discipline_path)
        with open(out_abs, "w", encoding="utf-8", newline="\n") as f:
            f.write(rules_text + "\n")

        print(f"✅ 已生成 Cursor 规则文件: {out_abs}")
        return out_abs

    @classmethod
    def export_cursor_mdc(
        cls, discipline_path: str | None, output_path: str, force: bool = False
    ) -> str:
        """输出兼容最新版 Cursor MDC 规范的 .cursor/rules/*.mdc 文件。"""
        out_abs = os.path.abspath(output_path)
        if os.path.isfile(out_abs) and not force:
            print(f"ℹ️ {out_abs} 已存在，跳过覆盖（使用 --force 可强制覆盖）。")
            return out_abs

        parent = os.path.dirname(out_abs)
        if parent:
            os.makedirs(parent, exist_ok=True)

        rules_text = cls.extract_condensed_rules(discipline_path)

        mdc_content = (
            "---\n"
            "description: Quench 任务治理体系开发纪律与代码管控规范\n"
            'globs: "*"\n'
            "alwaysApply: true\n"
            "---\n\n"
            f"{rules_text}\n"
        )
        with open(out_abs, "w", encoding="utf-8", newline="\n") as f:
            f.write(mdc_content)

        print(f"✅ 已生成 Cursor MDC 规则文件: {out_abs}")
        return out_abs

    @classmethod
    def export_all(
        cls,
        project_root: str,
        discipline_path: str | None = None,
        force: bool = False,
    ) -> dict[str, str]:
        """为目标项目一键生成 .cursorrules 与 .cursor/rules/quench-dev-tasks.mdc。"""
        root = os.path.abspath(project_root)
        legacy_path = os.path.join(root, ".cursorrules")
        mdc_path = os.path.join(root, ".cursor", "rules", "quench-dev-tasks.mdc")

        out_legacy = cls.export_cursorrules(discipline_path, legacy_path, force=force)
        out_mdc = cls.export_cursor_mdc(discipline_path, mdc_path, force=force)

        return {
            "cursorrules": out_legacy,
            "cursor_mdc": out_mdc,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Quench Cursor Rules Exporter: 导出并生成 Cursor 原生规则与 MDC 规范文件。"
    )
    parser.add_argument(
        "--dest",
        dest="project_root",
        default=".",
        help="目标项目根目录路径（默认为当前目录）",
    )
    parser.add_argument(
        "--discipline-path",
        dest="discipline_path",
        default=None,
        help="指定 dev-tasks-discipline.md 源文件路径（可选）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="若已有规则文件存在，强制覆盖写入",
    )

    args = parser.parse_args()
    results = RulesExporter.export_all(
        project_root=args.project_root,
        discipline_path=args.discipline_path,
        force=args.force,
    )
    print("🎉 规则导出已顺利完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
