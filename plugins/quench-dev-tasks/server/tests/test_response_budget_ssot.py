"""test_response_budget_ssot.py - Response Budget SSOT & Invariant Tests (Task 33.0).

Verifies:
- E1-A: AST de-duplication: no literal duplicates Final[int] constants; dev_reviewer_poll uses ast.Name.
- E1-B: Existence and exact values of HOOK_LOG_CODES, CHECKOUT_REASON_CODES, and overflow constants.
- E1-C: Immutable protection: RESPONSE_BUDGET_BYTES is MappingProxyType, assignment raises TypeError.
- E1-D: Strict key equality: set(RESPONSE_BUDGET_BYTES) == set(EXPECTED_TOOL_NAMES) and len == 16.
- E1-E: Measurement single point: measure_payload_bytes is sorted, canonical UTF-8 byte counter.
- E1-F: README INV-10 anchor check: asserts test_response_budget_ssot.py is registered in README §4.
- Cross-file anchor (D-10): MAX_NONTERMINAL_SNAPSHOT_BYTES == getattr(reviewer_jobs, ...).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

import reviewer_jobs
from tool_surface_constants import (
    CHECKOUT_REASON_CODES,
    EXPECTED_TOOL_NAMES,
    HOOK_LOG_CODES,
    HOOK_LOG_TAIL_BYTES,
    MAX_NONTERMINAL_SNAPSHOT_BYTES,
    RESPONSE_BUDGET_BYTES,
    STATUS_COMPACT_MAX_HOOK_ENTRIES,
    STATUS_COMPACT_MAX_TASKS,
    measure_payload_bytes,
    measure_tool_schema_bytes,
)

SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]


def test_response_budget_ssot_e1_a_dedup_ast() -> None:
    """E1-A 去重断言：

    1. RESPONSE_BUDGET_BYTES 字典内不存在与模块中任意 Final[int] 常量值相同的输入字面量 (literal ∩ constant_literals == ∅)；
    2. dev_reviewer_poll 的 value 节点为 ast.Name 且 id == 'MAX_NONTERMINAL_SNAPSHOT_BYTES'；
    3. 不因注释或 docstring 出现字面量而误红。
    """
    constants_file = SERVER_DIR / "tool_surface_constants.py"
    source = constants_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(constants_file))

    # 1. 采集模块中所有 Final[int] 常量的字面量数值
    constant_literals: set[int] = set()
    budget_dict_node: ast.Dict | None = None

    for stmt in tree.body:
        # 采集 Final[int] = <literal>
        if isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, int):
                # 确认其注解中包含 Final
                anno_str = ast.unparse(stmt.annotation)
                if "Final" in anno_str and "int" in anno_str:
                    constant_literals.add(stmt.value.value)

            # 寻找 RESPONSE_BUDGET_BYTES 定义
            if isinstance(stmt.target, ast.Name) and stmt.target.id == "RESPONSE_BUDGET_BYTES":
                if isinstance(stmt.value, ast.Call) and stmt.value.args and isinstance(stmt.value.args[0], ast.Dict):
                    budget_dict_node = stmt.value.args[0]

    assert budget_dict_node is not None, "Failed to locate RESPONSE_BUDGET_BYTES ast.Dict node"
    assert constant_literals, "Must have found Final[int] constant literals in tool_surface_constants.py"
    assert 1024 in constant_literals, "MAX_NONTERMINAL_SNAPSHOT_BYTES (1024) must be among Final[int] constants"

    # 2. 检查 RESPONSE_BUDGET_BYTES 字典内每一个 key-value 对
    budget_literals: set[int] = set()
    found_poll_name = False

    for k_node, v_node in zip(budget_dict_node.keys, budget_dict_node.values):
        assert isinstance(k_node, ast.Constant) and isinstance(k_node.value, str)
        key_str = k_node.value

        if key_str == "dev_reviewer_poll":
            assert isinstance(v_node, ast.Name), f"dev_reviewer_poll must be ast.Name, got {type(v_node).__name__}"
            assert v_node.id == "MAX_NONTERMINAL_SNAPSHOT_BYTES", (
                f"dev_reviewer_poll value id must be 'MAX_NONTERMINAL_SNAPSHOT_BYTES', got '{v_node.id}'"
            )
            found_poll_name = True
        elif isinstance(v_node, ast.Constant) and isinstance(v_node.value, int):
            budget_literals.add(v_node.value)
        else:
            pytest.fail(f"Unexpected value node for key '{key_str}': {ast.dump(v_node)}")

    assert found_poll_name, "dev_reviewer_poll entry not found in RESPONSE_BUDGET_BYTES"

    # 3. 去重交集断言：literal ∩ constant_literals == ∅
    collision = budget_literals & constant_literals
    assert not collision, (
        f"RESPONSE_BUDGET_BYTES contains duplicated literals that match module Final[int] constants: {collision}"
    )


def test_response_budget_ssot_e1_b_constants() -> None:
    """E1-B 常量存在性与封闭词表断言。"""
    assert HOOK_LOG_CODES == frozenset({
        "ASK_MODAL_BLOCKED",
        "SCOPE_VIOLATION",
        "BYPASS_ACTIVE",
        "TASK_STATUS_TAMPER",
        "PATH_OUT_OF_SCOPE",
        "OTHER",
    })
    assert CHECKOUT_REASON_CODES == frozenset({
        "REWORK_REQUIRED",
        "PENDING_REVIEW",
        "NO_CONFIRMED_TASKS",
    })
    assert isinstance(RESPONSE_BUDGET_BYTES, MappingProxyType)
    assert type(RESPONSE_BUDGET_BYTES) is MappingProxyType
    assert MAX_NONTERMINAL_SNAPSHOT_BYTES == 1024
    assert STATUS_COMPACT_MAX_TASKS == 5
    assert STATUS_COMPACT_MAX_HOOK_ENTRIES == 3
    assert HOOK_LOG_TAIL_BYTES == 65536


def test_response_budget_ssot_e1_c_immutability() -> None:
    """E1-C 冻结不可变保护：赋值必须抛出 TypeError。"""
    with pytest.raises(TypeError):
        RESPONSE_BUDGET_BYTES["dev_tasks_status"] = 1000  # type: ignore[index]

    with pytest.raises(TypeError):
        RESPONSE_BUDGET_BYTES["__unauthorized_key__"] = 1  # type: ignore[index]


def test_response_budget_ssot_e1_d_keys_and_length() -> None:
    """E1-D 键集严格等式：set(RESPONSE_BUDGET_BYTES) == set(EXPECTED_TOOL_NAMES) 且 len == 16。"""
    assert set(RESPONSE_BUDGET_BYTES) == set(EXPECTED_TOOL_NAMES)
    assert len(RESPONSE_BUDGET_BYTES) == 16
    assert len(EXPECTED_TOOL_NAMES) == 16


def test_response_budget_ssot_e1_e_measurement_canonical() -> None:
    """E1-E 计量口径单点化：

    - measure_payload_bytes 保证 sort_keys=True 下的规范序列化长度；
    - 键顺序颠倒不影响度量结果；
    - 幂等确定；
    - measure_tool_schema_bytes 与 measure_payload_bytes 口径完全一致。
    """
    dict1 = {"b": 1, "a": 2, "nested": {"y": [1, 2], "x": True}}
    dict2 = {"nested": {"x": True, "y": [1, 2]}, "a": 2, "b": 1}

    # 1. 键顺序独立性
    bytes1 = measure_payload_bytes(dict1)
    bytes2 = measure_payload_bytes(dict2)
    assert bytes1 == bytes2

    # 2. 与标准 json.dumps(sort_keys=True) 严格等价
    expected_bytes = len(
        json.dumps(dict1, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    assert bytes1 == expected_bytes

    # 3. 幂等性
    assert measure_payload_bytes(dict1) == measure_payload_bytes(dict1)

    # 4. 委托单点性
    assert measure_tool_schema_bytes(dict1) == measure_payload_bytes(dict1)


def test_response_budget_ssot_e1_f_readme_inv10_anchor() -> None:
    """E1-F 词表与 README 对账：

    解析 docs/architecture/README.md §4，断言 INV-10 的测试锚点列表中包含本测试文件。
    若解析失败 fail-closed 并携带可读诊断。
    """
    readme_path = REPO_ROOT / "docs" / "architecture" / "README.md"
    assert readme_path.is_file(), f"Architecture README not found at {readme_path}"

    readme_text = readme_path.read_text(encoding="utf-8")

    # 匹配 INV-10 行: | **INV-10** | <name> | <mechanism> | <test_file> |
    # 使用多行或逐行解析
    inv10_match = re.search(
        r"\|\s*\*\*INV-10\*\*\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|",
        readme_text,
    )
    assert inv10_match is not None, (
        "Failed to locate INV-10 row in docs/architecture/README.md §4 table. "
        "Expected format: | **INV-10** | ... | ... | ... |"
    )

    inv_name = inv10_match.group(1).strip()
    inv_mechanism = inv10_match.group(2).strip()
    inv_anchors = inv10_match.group(3).strip()

    assert "Response Budget SSOT" in inv_name, f"INV-10 name mismatch: '{inv_name}'"
    assert "test_response_budget_ssot.py" in inv_anchors, (
        f"'test_response_budget_ssot.py' must be in INV-10 anchors column, got: '{inv_anchors}'"
    )


def test_response_budget_ssot_cross_file_anchor() -> None:
    """交叉文件锚点（对齐 Reviewer D-10）：

    - assert MAX_NONTERMINAL_SNAPSHOT_BYTES == getattr(reviewer_jobs, 'MAX_NONTERMINAL_SNAPSHOT_BYTES', MAX_NONTERMINAL_SNAPSHOT_BYTES)
    - 使用 == 而非 is；
    - RESPONSE_BUDGET_BYTES['dev_reviewer_poll'] == MAX_NONTERMINAL_SNAPSHOT_BYTES == 1024。
    """
    assert MAX_NONTERMINAL_SNAPSHOT_BYTES == getattr(
        reviewer_jobs, "MAX_NONTERMINAL_SNAPSHOT_BYTES", MAX_NONTERMINAL_SNAPSHOT_BYTES
    )
    assert MAX_NONTERMINAL_SNAPSHOT_BYTES == 1024
    assert RESPONSE_BUDGET_BYTES["dev_reviewer_poll"] == MAX_NONTERMINAL_SNAPSHOT_BYTES

