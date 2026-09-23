# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, NamedTuple, Optional, Union

from path_guard import sanitize_workspace_path, PathTraversalError

REQUIRED_FIELDS = [
    "affected_files",
    "root_cause_and_goal",
    "type_contracts",
    "steps",
    "defensive_checks",
    "dod_commands",
]

VALID_AFFECTED_PREFIXES = ("[MODIFY]", "[NEW]", "[DELETE]", "[RENAME]")


FIELD_ALIASES: Dict[str, str] = {
    "【涉及文件】": "affected_files",
    "涉及文件": "affected_files",
    "affected_files": "affected_files",
    "【缺陷根因与修改目标】": "root_cause_and_goal",
    "缺陷根因与修改目标": "root_cause_and_goal",
    "root_cause_and_goal": "root_cause_and_goal",
    "【目标签名与类型契约】": "type_contracts",
    "目标签名与类型契约": "type_contracts",
    "type_contracts": "type_contracts",
    "【分步改造指引】": "steps",
    "分步改造指引": "steps",
    "steps": "steps",
    "【防御与边缘校验】": "defensive_checks",
    "防御与边缘校验": "defensive_checks",
    "defensive_checks": "defensive_checks",
    "【DoD 验证命令】": "dod_commands",
    "DoD 验证命令": "dod_commands",
    "dod_commands": "dod_commands",
}


@dataclass
class ValidationResult:
    """Schema validation outcome container. / 任务契约校验结果容器。"""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class LintIssue(NamedTuple):
    severity: Literal["error", "warning"]
    field: str
    message: str


class PhysicalLintResult(NamedTuple):
    passed: bool
    issues: List[LintIssue]
    validated_files: List[str]


def _parse_task_markdown_sections(text: str) -> Dict[str, Any]:
    """从 Markdown 文本或 JSON 格式中提取六大核心字段字典。"""
    clean_text = text.strip()
    if clean_text.startswith("```json") and clean_text.endswith("```"):
        clean_text = clean_text[7:-3].strip()
    elif clean_text.startswith("```") and clean_text.endswith("```"):
        first_nl = clean_text.find("\n")
        if first_nl != -1:
            clean_text = clean_text[first_nl + 1:-3].strip()

    try:
        data = json.loads(clean_text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    result: Dict[str, Any] = {}
    header_m = re.search(r"^###\s+(?:任务|Task)\s+([^\s—\-]+)\s*.*?[—\-]\s*(.*)$", text, re.MULTILINE)
    if header_m:
        result["id"] = header_m.group(1).strip()
        result["title"] = header_m.group(2).strip()

    # 提取 draft 元数据标识
    meta_m = re.search(r"<!--\s*quench-task-meta:\s*({.*?})\s*-->", text)
    if meta_m:
        try:
            meta_obj = json.loads(meta_m.group(1))
            if isinstance(meta_obj, dict) and meta_obj.get("draft") is not None:
                result["draft"] = bool(meta_obj["draft"])
        except Exception:
            pass
    if "draft" not in result:
        header_sample = text[:300]
        if "(草案)" in header_sample or "(Draft)" in header_sample or "(draft)" in header_sample or "draft: true" in header_sample.lower():
            result["draft"] = True

    sections = [
        ("affected_files", r"####\s+【?(?:涉及文件|Affected Files)】?"),
        ("root_cause_and_goal", r"####\s+【?(?:缺陷根因与修改目标|Root Cause & Goal|Root Cause and Goal)】?"),
        ("type_contracts", r"####\s+【?(?:目标签名与类型契约|Type Contracts)】?"),
        ("steps", r"####\s+【?(?:分步改造指引|Step-by-Step Instructions|Steps)】?"),
        ("defensive_checks", r"####\s+【?(?:防御与边缘校验|Defensive Checks|Defensive and Edge Checks)】?"),
        ("dod_commands", r"####\s+【?(?:DoD 验证命令|DoD Verification Commands|dod_commands)】?"),
    ]

    for idx, (field_name, pattern) in enumerate(sections):
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        start_pos = m.end()
        next_pos = len(text)
        for _, next_pat in sections[idx + 1:]:
            next_m = re.search(next_pat, text[start_pos:], re.IGNORECASE)
            if next_m:
                next_pos = start_pos + next_m.start()
                break

        sec_content = text[start_pos:next_pos].strip()
        if sec_content.startswith("```") and sec_content.endswith("```"):
            inner = sec_content.splitlines()
            if len(inner) >= 2:
                sec_content = "\n".join(inner[1:-1]).strip()

        if field_name == "affected_files":
            files = [l.strip() for l in sec_content.splitlines() if l.strip() and not l.strip().startswith("```")]
            result["affected_files"] = files
        elif field_name == "steps":
            result["steps"] = [l.strip() for l in sec_content.splitlines() if l.strip()]
        elif field_name == "defensive_checks":
            result["defensive_checks"] = [l.strip() for l in sec_content.splitlines() if l.strip()]
        else:
            result[field_name] = sec_content

    return result


def validate_task_schema(task: Dict[str, Any]) -> ValidationResult:
    """Validate completeness and quality of the six core fields for a single task. / 校验单条任务数据的六大字段完整性与内容质量。"""
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(task, dict):
        return ValidationResult(is_valid=False, errors=["Task object must be a JSON dictionary/object / 任务对象必须为 JSON 字典/对象"])

    # 规范化别名字段（支持直接传入中文键名）
    for alias_k, canonical_k in FIELD_ALIASES.items():
        if alias_k in task and canonical_k not in task:
            task[canonical_k] = task[alias_k]

    # 1. 检查六大必填字段是否存在
    for req in REQUIRED_FIELDS:
        if req not in task:
            errors.append(f"Missing required field: '{req}' / 缺失必填字段: '{req}'")

    # 2. 详细校验各字段内容
    # affected_files
    affected = task.get("affected_files")
    if affected is not None:
        if not isinstance(affected, list) or len(affected) == 0:
            errors.append("Field 'affected_files' must be a non-empty file list / 字段 'affected_files' 必须是非空文件列表")
        else:
            modify_count = 0
            for item in affected:
                if not isinstance(item, str):
                    errors.append(f"Field 'affected_files' contains non-string element: {item} / affected_files 包含非字符串元素: {item}")
                    continue
                s_item = re.sub(r"^[\s\-\*\+\d\.\>\#]+\s*", "", item).strip().strip("`'\" ")
                if not any(s_item.startswith(prefix) for prefix in VALID_AFFECTED_PREFIXES):
                    warnings.append(
                        f"File item '{s_item}' does not use recommended prefixes [MODIFY]/[NEW]/[DELETE]/[RENAME] / 文件项 '{s_item}' 未使用推荐的操作标记 [MODIFY]/[NEW]/[DELETE]/[RENAME]"
                    )
                if s_item.startswith("[MODIFY]"):
                    modify_count += 1

            if modify_count > 3:
                warnings.append(
                    f"Task touches {modify_count} modified files (more than 3), granularity is coarse / 任务涉及修改 {modify_count} 个文件（超过 3 个），任务粒度偏粗，建议评估是否拆分为子任务。"
                )

    # root_cause_and_goal
    rc_goal = task.get("root_cause_and_goal")
    if rc_goal is not None:
        if not isinstance(rc_goal, str) or not rc_goal.strip():
            errors.append("Field 'root_cause_and_goal' must be a non-empty string / 字段 'root_cause_and_goal' 必须是非空字符串")

    # type_contracts
    contracts = task.get("type_contracts")
    if contracts is not None:
        if not isinstance(contracts, (str, list)):
            errors.append("Field 'type_contracts' must be string or list / 字段 'type_contracts' 必须是字符串或列表")
        elif isinstance(contracts, str) and not contracts.strip():
            errors.append("Field 'type_contracts' cannot be empty / 字段 'type_contracts' 不能为空（若无变更请填写'无'）")

    # steps
    steps = task.get("steps")
    if steps is not None:
        if isinstance(steps, str):
            warnings.append("Field 'steps' recommends numbered step list, currently plain string / 字段 'steps' 建议为编号步骤数组，当前为纯字符串")
            step_lines = [s.strip() for s in steps.splitlines() if s.strip()]
        elif isinstance(steps, list):
            step_lines = steps
        else:
            errors.append("Field 'steps' must be a list of steps or multi-line text / 字段 'steps' 必须是步骤数组或换行文本")
            step_lines = []

        if len(step_lines) == 0:
            errors.append("Field 'steps' step list cannot be empty / 字段 'steps' 步骤列表不能为空")
        elif len(step_lines) < 2:
            warnings.append("Too few steps (fewer than 2), please clarify sequential steps / 步骤过少（少于 2 步），建议进一步明确分步改造路径")
        elif len(step_lines) > 7:
            warnings.append(f"Too many steps ({len(step_lines)} steps), check if task granularity is coarse / 步骤数量（{len(step_lines)} 步）较多，建议检查任务是否粒度过粗")

        # 检查步骤中的连续代码行数是否越界
        for s_idx, step_str in enumerate(step_lines, 1):
            if isinstance(step_str, str):
                code_lines = step_str.count("\n") + 1
                if code_lines > 15:
                    warnings.append(
                        f"Step {s_idx} contains {code_lines} lines of code, recommend condensing to skeleton/pseudocode / 步骤 {s_idx} 包含 {code_lines} 行连续代码，建议浓缩为关键骨架或伪代码，避免直接给出全量实现。"
                    )

    # defensive_checks
    checks = task.get("defensive_checks")
    if checks is not None:
        if not isinstance(checks, (list, str)):
            errors.append("Field 'defensive_checks' must be list or string / 字段 'defensive_checks' 必须是列表或字符串")
        elif isinstance(checks, list) and len(checks) == 0:
            warnings.append("Field 'defensive_checks' is empty list, defensive validation recommended / 字段 'defensive_checks' 为空列表，建议尽可能补充边界与防御性校验")

    # dod_commands
    dod = task.get("dod_commands")
    if dod is not None:
        if isinstance(dod, str):
            if not dod.strip():
                errors.append("Field 'dod_commands' cannot be empty / 字段 'dod_commands' 不能为空")
        elif isinstance(dod, list):
            if len(dod) == 0:
                errors.append("Field 'dod_commands' verification command list cannot be empty / 字段 'dod_commands' 验证命令列表不能为空")
        else:
            errors.append("Field 'dod_commands' must be command string or list / 字段 'dod_commands' 必须是字符串命令或命令列表")

    is_valid = len(errors) == 0
    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)


def lint_task_physical_feasibility(
    workspace_root: str,
    task_content: Union[str, Dict[str, Any]],
) -> PhysicalLintResult:
    """Validate physical sanity:
    1. [MODIFY]/[DELETE] files must physically exist on disk (Path.exists() == True).
    2. [NEW] target file must NOT already exist, but parent directory must exist or be within workspace.
    3. DoD pytest commands must pass `pytest --collect-only -q` dry-run (exit code in {0, 5}).
    """
    ws_root = os.path.abspath(workspace_root)
    if isinstance(task_content, str):
        task_dict = _parse_task_markdown_sections(task_content)
    elif isinstance(task_content, dict):
        task_dict = task_content
    else:
        return PhysicalLintResult(
            passed=False,
            issues=[LintIssue("error", "task_content", "Invalid task content format / 无效的任务内容格式")],
            validated_files=[],
        )

    issues: List[LintIssue] = []
    validated_files: List[str] = []

    # 1. 扫描受影响文件
    affected = task_dict.get("affected_files") or []
    if isinstance(affected, str):
        affected = [l.strip() for l in affected.splitlines() if l.strip()]

    new_declared_files: List[str] = []

    for raw_item in affected:
        item = str(raw_item).strip()
        if not item or item.startswith("```"):
            continue

        # 剥除前导列表符号 (- , * , + ) 与反引号
        clean_item = re.sub(r"^[\s\-\*\+\d\.\>\#]+\s*", "", item).strip()
        clean_item = clean_item.strip("`'\" ")

        # 匹配操作标记与文件路径
        m = re.match(r"^\[(MODIFY|NEW|DELETE|RENAME)\]\s*(.*)$", clean_item, re.IGNORECASE)
        if not m:
            continue

        action = m.group(1).upper()
        target_str = m.group(2).strip()

        # 剥除 Markdown 超链接与反引号
        m_link = re.search(r"\[.*?\]\((.*?)\)", target_str)
        if m_link:
            target_path = m_link.group(1).strip()
        else:
            target_path = target_str

        target_path = target_path.strip("`'\" ")
        if target_path.startswith("file:///"):
            target_path = target_path[8:].lstrip("/\\")

        if action == "RENAME":
            parts = [p.strip("`'\" ") for p in target_path.split("->")]
            if len(parts) != 2:
                issues.append(
                    LintIssue("error", "affected_files", f"[RENAME] 格式无效，必须为 'old -> new': {item}")
                )
                continue
            old_rel, new_rel = parts
            check_items = [("DELETE", old_rel), ("NEW", new_rel)]
        else:
            check_items = [(action, target_path)]

        for act, rel in check_items:
            # 路径穿越防线（单一事实源 path_guard，消除跨平台分隔符歧义）
            try:
                target_abs = sanitize_workspace_path(ws_root, rel)
            except PathTraversalError as pte:
                issues.append(
                    LintIssue(
                        "error",
                        "affected_files",
                        f"路径穿越安全违规: '{rel}' 超出工作区根目录 ({pte})",
                    )
                )
                continue
            except Exception:
                issues.append(
                    LintIssue("error", "affected_files", f"非法文件路径: '{rel}'")
                )
                continue

            if act in ("MODIFY", "DELETE"):
                if not os.path.exists(target_abs):
                    issues.append(
                        LintIssue(
                            "error",
                            "affected_files",
                            f"[{act}] 目标文件在磁盘上物理不存在: '{rel}'",
                        )
                    )
                else:
                    validated_files.append(rel)

            elif act == "NEW":
                if os.path.exists(target_abs):
                    issues.append(
                        LintIssue(
                            "error",
                            "affected_files",
                            f"[NEW] 目标文件已存在于磁盘，存在覆盖冲突风险: '{rel}'",
                        )
                    )
                else:
                    parent_dir = os.path.dirname(target_abs)
                    try:
                        common_parent = os.path.commonpath([ws_root, os.path.abspath(parent_dir)])
                        if common_parent != ws_root:
                            issues.append(
                                LintIssue(
                                    "error",
                                    "affected_files",
                                    f"[NEW] 父目录超出工作区根目录: '{rel}'",
                                )
                            )
                        else:
                            validated_files.append(rel)
                            new_declared_files.append(rel)
                    except Exception:
                        issues.append(
                            LintIssue(
                                "error",
                                "affected_files",
                                f"[NEW] 目标父路径无效: '{rel}'",
                            )
                        )

    # 2. 校验 DoD 验证命令 (单测 dry-run 与命令注入防线)
    dod = task_dict.get("dod_commands") or []
    if isinstance(dod, str):
        dod_lines = [l.strip() for l in dod.splitlines() if l.strip()]
    elif isinstance(dod, list):
        dod_lines = [str(l).strip() for l in dod if str(l).strip()]
    else:
        dod_lines = []

    for cmd_line in dod_lines:
        if cmd_line.startswith("```") or not cmd_line or cmd_line.startswith("#"):
            continue
        # 命令注入防线：拦截危险 Shell 字符
        if any(c in cmd_line for c in (";", "&", "|", "$", "`", ">", "<")):
            issues.append(
                LintIssue(
                    "error",
                    "dod_commands",
                    f"DoD 命令包含危险 shell 元字符，已拦截: '{cmd_line}'",
                )
            )
            continue

        # 匹配 pytest 命令执行静态 Dry-run
        m_pytest = re.search(
            r"(?:python(?:\.exe)?\s+(?:-m\s+)?pytest|pytest(?:\.exe)?)\s*(.*)",
            cmd_line,
            re.IGNORECASE,
        )
        if m_pytest:
            args_str = m_pytest.group(1).strip()
            try:
                raw_args = shlex.split(args_str, posix=(sys.platform != "win32"))
            except Exception as e:
                issues.append(
                    LintIssue("error", "dod_commands", f"pytest 参数解析失败: {e}")
                )
                continue

            # 过滤掉交互式或破坏性参数
            safe_args = [a for a in raw_args if a not in ("-s", "--capture=no", "--pdb")]
            dry_cmd = [
                sys.executable,
                "-m",
                "pytest",
                *safe_args,
                "--collect-only",
                "-q",
                "-o",
                "pythonpath=.",
            ]

            try:
                proc = subprocess.run(
                    dry_cmd,
                    cwd=ws_root,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                comb_out = (proc.stdout + "\n" + proc.stderr).strip()

                if proc.returncode in (0, 5):
                    # 0: collected ok; 5: no tests collected (normal for new files)
                    pass
                else:
                    # 检查是否为 [NEW] 声明的新建测试文件不存在导致的单测收集未就绪
                    missing_expected_new = False
                    if "file or directory not found" in comb_out.lower():
                        for nf in new_declared_files:
                            if os.path.basename(nf) in comb_out:
                                missing_expected_new = True
                                break

                    if missing_expected_new or "no tests collected" in comb_out.lower():
                        pass
                    elif "error: unrecognized arguments" in comb_out.lower():
                        issues.append(
                            LintIssue(
                                "error",
                                "dod_commands",
                                f"pytest 命令包含未知参数: {comb_out[:180]}",
                            )
                        )
                    elif "syntaxerror" in comb_out.lower() or "indentationerror" in comb_out.lower():
                        issues.append(
                            LintIssue(
                                "error",
                                "dod_commands",
                                f"pytest 收集命中语法错误: {comb_out[:180]}",
                            )
                        )
                    elif proc.returncode == 4:
                        issues.append(
                            LintIssue(
                                "error",
                                "dod_commands",
                                f"pytest 用法错误 (exit code 4): {comb_out[:180]}",
                            )
                        )
                    else:
                        issues.append(
                            LintIssue(
                                "error",
                                "dod_commands",
                                f"pytest dry-run 收集失败 (code {proc.returncode}): {comb_out[:180]}",
                            )
                        )
            except subprocess.TimeoutExpired:
                issues.append(
                    LintIssue("warning", "dod_commands", "pytest dry-run 收集超时 (8s)")
                )
            except Exception as e:
                issues.append(
                    LintIssue("warning", "dod_commands", f"pytest dry-run 执行异常: {e}")
                )

    passed = not any(i.severity == "error" for i in issues)
    return PhysicalLintResult(passed=passed, issues=issues, validated_files=validated_files)
