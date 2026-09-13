from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

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
                s_item = item.strip()
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
