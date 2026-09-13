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


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate_task_schema(task: Dict[str, Any]) -> ValidationResult:
    """校验单条任务数据的六大字段完整性与内容质量。"""
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(task, dict):
        return ValidationResult(is_valid=False, errors=["任务对象必须为 JSON 字典/对象"])

    # 1. 检查六大必填字段是否存在
    for req in REQUIRED_FIELDS:
        if req not in task:
            errors.append(f"缺失必填字段: '{req}'")

    # 2. 详细校验各字段内容
    # affected_files
    affected = task.get("affected_files")
    if affected is not None:
        if not isinstance(affected, list) or len(affected) == 0:
            errors.append("字段 'affected_files' 必须是非空文件列表")
        else:
            modify_count = 0
            for item in affected:
                if not isinstance(item, str):
                    errors.append(f"affected_files 包含非字符串元素: {item}")
                    continue
                s_item = item.strip()
                if not any(s_item.startswith(prefix) for prefix in VALID_AFFECTED_PREFIXES):
                    warnings.append(
                        f"文件项 '{s_item}' 未使用推荐的操作标记 [MODIFY]/[NEW]/[DELETE]/[RENAME]"
                    )
                if s_item.startswith("[MODIFY]"):
                    modify_count += 1

            if modify_count > 3:
                warnings.append(
                    f"任务涉及修改 {modify_count} 个文件（超过 3 个），任务粒度偏粗，建议评估是否拆分为子任务。"
                )

    # root_cause_and_goal
    rc_goal = task.get("root_cause_and_goal")
    if rc_goal is not None:
        if not isinstance(rc_goal, str) or not rc_goal.strip():
            errors.append("字段 'root_cause_and_goal' 必须是非空字符串")

    # type_contracts
    contracts = task.get("type_contracts")
    if contracts is not None:
        if not isinstance(contracts, (str, list)):
            errors.append("字段 'type_contracts' 必须是字符串或列表")
        elif isinstance(contracts, str) and not contracts.strip():
            errors.append("字段 'type_contracts' 不能为空（若无变更请填写'无'）")

    # steps
    steps = task.get("steps")
    if steps is not None:
        if isinstance(steps, str):
            warnings.append("字段 'steps' 建议为编号步骤数组，当前为纯字符串")
            step_lines = [s.strip() for s in steps.splitlines() if s.strip()]
        elif isinstance(steps, list):
            step_lines = steps
        else:
            errors.append("字段 'steps' 必须是步骤数组或换行文本")
            step_lines = []

        if len(step_lines) == 0:
            errors.append("字段 'steps' 步骤列表不能为空")
        elif len(step_lines) < 2:
            warnings.append("步骤过少（少于 2 步），建议进一步明确分步改造路径")
        elif len(step_lines) > 7:
            warnings.append(f"步骤数量（{len(step_lines)} 步）较多，建议检查任务是否粒度过粗")

        # 检查步骤中的连续代码行数是否越界
        for s_idx, step_str in enumerate(step_lines, 1):
            if isinstance(step_str, str):
                code_lines = step_str.count("\n") + 1
                if code_lines > 15:
                    warnings.append(
                        f"步骤 {s_idx} 包含 {code_lines} 行连续代码，建议浓缩为关键骨架或伪代码，避免直接给出全量实现。"
                    )

    # defensive_checks
    checks = task.get("defensive_checks")
    if checks is not None:
        if not isinstance(checks, (list, str)):
            errors.append("字段 'defensive_checks' 必须是列表或字符串")
        elif isinstance(checks, list) and len(checks) == 0:
            warnings.append("字段 'defensive_checks' 为空列表，建议尽可能补充边界与防御性校验")

    # dod_commands
    dod = task.get("dod_commands")
    if dod is not None:
        if isinstance(dod, str):
            if not dod.strip():
                errors.append("字段 'dod_commands' 不能为空")
        elif isinstance(dod, list):
            if len(dod) == 0:
                errors.append("字段 'dod_commands' 验证命令列表不能为空")
        else:
            errors.append("字段 'dod_commands' 必须是字符串命令或命令列表")

    is_valid = len(errors) == 0
    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)
