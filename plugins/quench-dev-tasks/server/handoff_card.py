# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def _extract_spec_section(spec_text: str, header_keyword: str) -> Optional[str]:
    """从任务单规范文本中安全提取指定章节内容（去除标题行本身）。"""
    if not spec_text:
        return None
    # 匹配形如 #### 【涉及文件】 或 #### 【.*header_keyword.*】
    pattern = re.compile(
        rf"(?:^|\n)####\s*【[^】]*{re.escape(header_keyword)}[^】]*】[^\n]*\n([\s\S]*?)(?=(?:\n####\s*【|\n---|(?:\n##\s+)|\Z))",
        re.MULTILINE,
    )
    match = pattern.search(spec_text)
    if match:
        content = match.group(1).strip()
        return content if content else None
    return None


def render_handoff_card(
    task_id: str,
    task_file: str,
    reason: str,
    task_meta: Optional[Dict[str, Any]] = None,
    include_context: bool = False,
) -> str:
    """单一生成源纯函数：生成符合 GitHub Flavored Markdown 规范的交接卡片文本。

    当 include_context=True 时，仅将规范字段（缺陷根因、涉及文件、类型契约、DoD命令）
    以 <details> 折叠块安全注入，杜绝环境变量与未过滤配置泄漏。
    """
    clean_task_id = str(task_id).strip()
    clean_task_file = str(task_file).strip()
    clean_reason = str(reason).strip()

    title_suffix = ""
    preferred_mode = ""
    if task_meta and isinstance(task_meta, dict):
        if task_meta.get("title"):
            title_suffix = f" — {task_meta['title']}"
        if task_meta.get("preferred"):
            preferred_mode = f"\n> - **Preferred Mode / 推荐模式**: `{task_meta['preferred']}`"

    card_lines = [
        "> [!IMPORTANT]",
        f"> ### ⏸️ Quench 任务交接卡 / Quench Task Handoff Card{title_suffix}",
        f"> - **Task ID / 任务编号**: `{clean_task_id}`",
        f"> - **Task File / 任务文件**: `{clean_task_file}`",
        f"> - **Handoff Reason / 交接原因**: {clean_reason}{preferred_mode}",
        "> ",
        "> **👉 Low-Token Handoff Steps / 极简低消耗交接指引:**",
        "> 1. 点击 `+` 开启**新的纯净会话**（零历史 Token 冗余，避免注意力稀释与就地混淆）；",
        "> 2. 切换至预先分配的**高阶架构审查模型 (Reviewer)**；",
        f"> 3. 发送提示词：`请审查并精化任务单 {clean_task_file} (Task {clean_task_id})`；",
        "> 4. 架构审查模型完成审查/返工确认后，通过工具或标记任务单为 `[Confirmed] / ✅ 已确认`；",
        "> 5. **切回当前开发会话**，输入 `继续` 或 `Ready to proceed` 恢复开发。",
    ]

    base_card = "\n".join(card_lines)

    if not include_context:
        return base_card

    # 提取四大约束规范字段（根因、文件、契约、DoD），严禁泄漏外部系统信息
    spec_text = ""
    if task_meta and isinstance(task_meta, dict):
        spec_text = str(task_meta.get("full_spec") or task_meta.get("spec") or "")

    # 1. 涉及文件
    files_val = None
    if spec_text:
        files_val = _extract_spec_section(spec_text, "涉及文件")
    if not files_val and task_meta and isinstance(task_meta, dict):
        raw_files = task_meta.get("affected_files") or task_meta.get("files")
        if isinstance(raw_files, list):
            files_val = "```\n" + "\n".join(str(f) for f in raw_files) + "\n```"
        elif isinstance(raw_files, str) and raw_files.strip():
            files_val = raw_files.strip()

    # 2. 缺陷根因与修改目标
    root_cause_val = None
    if spec_text:
        root_cause_val = _extract_spec_section(spec_text, "缺陷根因") or _extract_spec_section(spec_text, "根因")
    if not root_cause_val and task_meta and isinstance(task_meta, dict):
        rc = task_meta.get("root_cause_and_goal") or task_meta.get("root_cause")
        if rc:
            root_cause_val = str(rc).strip()

    # 3. 目标签名与类型契约
    contract_val = None
    if spec_text:
        contract_val = _extract_spec_section(spec_text, "类型契约") or _extract_spec_section(spec_text, "契约")
    if not contract_val and task_meta and isinstance(task_meta, dict):
        tc = task_meta.get("type_contracts") or task_meta.get("type_contract") or task_meta.get("contract")
        if tc:
            contract_val = str(tc).strip()

    # 4. DoD 验证命令
    dod_val = None
    if spec_text:
        dod_val = _extract_spec_section(spec_text, "DoD")
    if not dod_val and task_meta and isinstance(task_meta, dict):
        dc = task_meta.get("dod_commands") or task_meta.get("dod")
        if isinstance(dc, list):
            dod_val = "```bash\n" + "\n".join(str(c) for c in dc) + "\n```"
        elif isinstance(dc, str) and dc.strip():
            dod_val = dc.strip()

    details_sections = []
    if files_val:
        details_sections.append(f"#### 【涉及文件】\n{files_val}")
    if root_cause_val:
        details_sections.append(f"#### 【缺陷根因与修改目标】\n{root_cause_val}")
    if contract_val:
        details_sections.append(f"#### 【目标签名与类型契约】\n{contract_val}")
    if dod_val:
        details_sections.append(f"#### 【DoD 验证命令】\n{dod_val}")

    if not details_sections:
        details_content = "*（未提供详细规范字段）*"
    else:
        details_content = "\n\n".join(details_sections)

    context_details = (
        "\n\n<details>\n"
        "<summary><b>🔍 任务单上下文详情 / Task Context Details</b></summary>\n\n"
        f"{details_content}\n\n"
        "</details>"
    )

    return base_card + context_details
