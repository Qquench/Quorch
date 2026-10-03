# -*- coding: utf-8 -*-
"""Unit tests for §1.4.1 Prompt Layout Criterion and Mode Anchor Token Budget.

Verifies:
1. §1.4.1 Criterion Flip Point: Mode anchor (<=200 tokens / <=1200 bytes) is strictly tail-anchored (after code slices, before query).
2. Cross-mode prefix byte identity: evaluate / critique / brainstorm / audit share 100% identical prefix_hash for identical code slices.
3. Deterministic token budget proxy (mode_anchor_token_budget_proxy): <=200 whitespace tokens and <=1200 UTF-8 bytes across all modes.
4. Mode instruction line count <= 5 lines per mode.
5. Deterministic delimiter separation (\n\n) without erratic whitespace.
6. POSIX normalization for code slices and paths.
7. Python >= 3.10 slots guard and immutable frozen slots structure on AssembledPrompt.
"""
from __future__ import annotations

import dataclasses
import hashlib
import sys
from typing import Sequence

import pytest

from reviewer_engine import (
    AssembledPrompt,
    CodeSlice,
    CONSULT_MODE_INSTRUCTIONS,
    OUTPUT_PROTOCOLS,
    PromptAssembler,
    mode_anchor_token_budget_proxy,
)
from consultation import render_mode_prompt


def test_python_version_and_dataclass_slots_guard():
    """断言 Quench 运行环境满足 Python >= 3.10，且 AssembledPrompt 严格启用 frozen=True 与 slots=True。"""
    assert sys.version_info >= (3, 10), "Quench requires Python 3.10+ for dataclass slots support"
    assert hasattr(AssembledPrompt, "__slots__")

    prompt = AssembledPrompt(
        static_system_prefix="sys",
        code_context_block="code",
        mode_anchor="mode",
        dynamic_query="query",
        prefix_hash="0123456789abcdef",
    )
    # 实例无 __dict__
    assert not hasattr(prompt, "__dict__")

    with pytest.raises(dataclasses.FrozenInstanceError):
        prompt.prefix_hash = "mutated"  # type: ignore


def test_mode_anchor_token_budget_and_line_count_limits():
    """断言所有审查模式协议严格遵守奥卡姆剃刀原则：行数 <= 5，whitespace <= 200，UTF-8 bytes <= 1200。"""
    required_modes = ("evaluate", "critique", "brainstorm", "audit")
    assert set(CONSULT_MODE_INSTRUCTIONS.keys()) == set(required_modes)

    for mode_name, instruction in CONSULT_MODE_INSTRUCTIONS.items():
        lines = instruction.strip().splitlines()
        # 1. 严格 <= 5 行
        assert len(lines) <= 5, f"Mode '{mode_name}' exceeds 5-line limit (has {len(lines)} lines)"

        # 2. 纯函数预算代理验证：whitespace <= 200, bytes <= 1200
        tokens, bytes_len = mode_anchor_token_budget_proxy(instruction)
        assert tokens <= 200, f"Mode '{mode_name}' tokens={tokens} exceeds 200 token budget"
        assert bytes_len <= 1200, f"Mode '{mode_name}' bytes={bytes_len} exceeds 1200 byte limit"

        # 3. 统一为纯英文规范，无 CJK 字符
        assert not any(ord(c) > 127 for c in instruction), f"Mode '{mode_name}' contains non-ASCII characters"


def test_cross_mode_prefix_bytes_and_hash_absolute_identity():
    """断言在代码切片相同时，不同模式（evaluate/critique/brainstorm/audit）生成的 ①+② 前缀字节与 prefix_hash 绝对恒等。"""
    slices = [
        CodeSlice("src/kernel/engine.py", 1, 50, "# file: src/kernel/engine.py:1-50\nclass Engine: pass"),
        CodeSlice("src/adapter/client.py", 10, 30, "# file: src/adapter/client.py:10-30\ndef connect(): pass"),
    ]
    query = "Evaluate state machine convergence"

    assembled_prompts = {
        mode: PromptAssembler.assemble_consultation_prompt(mode=mode, slices=slices, query=query)
        for mode in ("evaluate", "critique", "brainstorm", "audit")
    }

    # 1. 所有模式的 static_system_prefix 与 code_context_block 必须逐字节绝对相等
    base_eval = assembled_prompts["evaluate"]
    for mode, prompt in assembled_prompts.items():
        assert prompt.static_system_prefix == base_eval.static_system_prefix
        assert prompt.code_context_block == base_eval.code_context_block
        assert prompt.prefix_hash == base_eval.prefix_hash

    # 2. 跨模式 prefix_hash 集合必须唯有一项
    distinct_hashes = {p.prefix_hash for p in assembled_prompts.values()}
    assert len(distinct_hashes) == 1

    # 3. 模式锚点 mode_anchor 必须在不同模式间呈现专有特征（尾置差异化）
    assert assembled_prompts["evaluate"].mode_anchor != assembled_prompts["critique"].mode_anchor


def test_criterion_flip_point_tail_positioning():
    """断言段序判定律翻转点：因为锚点 <= 200tok，故模式锚点必须尾置于代码切片之后、Query 之前。"""
    slice_a = CodeSlice("src/a.py", 1, 10, "class A: pass")
    query_str = "MY_SPECIAL_CRITERION_QUERY"
    rendered = render_mode_prompt("evaluate", query_str, [slice_a])

    pos_protocols = rendered.find("### Protocols for Reviewer Output")
    pos_slices = rendered.find("### Injected Code Context Slices")
    pos_mode = rendered.find("### Mode: Technical Trade-off Evaluation")
    pos_query = rendered.find("### Consultation Query")

    # 拓扑断言：① 系统输出协议 -> ② 代码切片 -> ③ 模式锚点(尾置) -> ④ 动态提问
    assert pos_protocols != -1 and pos_slices != -1 and pos_mode != -1 and pos_query != -1
    assert pos_protocols < pos_slices < pos_mode < pos_query
    assert rendered.endswith(query_str)


def test_prefix_hash_drift_detection_when_slices_or_prefix_change():
    """断言前缀哈希敏感度：当系统前缀或代码切片发生任何一字节漂移时，prefix_hash 必须敏锐变化。"""
    s1 = CodeSlice("src/a.py", 1, 10, "class A: pass")
    s2 = CodeSlice("src/a.py", 1, 10, "class A: pass # modified")

    p1 = PromptAssembler.assemble_consultation_prompt(mode="evaluate", slices=[s1], query="q")
    p2 = PromptAssembler.assemble_consultation_prompt(mode="evaluate", slices=[s2], query="q")
    assert p1.prefix_hash != p2.prefix_hash

    p3 = PromptAssembler.assemble_consultation_prompt(
        mode="evaluate",
        slices=[s1],
        query="q",
        static_system_prefix="CUSTOM_SYSTEM_BASELINE_V2",
    )
    assert p1.prefix_hash != p3.prefix_hash


def test_deterministic_posix_normalization_and_sorting():
    """断言切片路径在组装时被规范化为 POSIX 斜杠，且不同传入顺序产生绝对相同的 context_block。"""
    s_win1 = CodeSlice("src\\sub\\mod_b.py", 1, 10, "# file: src\\sub\\mod_b.py:1-10\ndef b(): pass")
    s_win2 = CodeSlice("src\\sub\\mod_a.py", 1, 10, "# file: src\\sub\\mod_a.py:1-10\ndef a(): pass")

    p1 = PromptAssembler.assemble_consultation_prompt(mode="evaluate", slices=[s_win1, s_win2], query="q")
    p2 = PromptAssembler.assemble_consultation_prompt(mode="evaluate", slices=[s_win2, s_win1], query="q")

    # 1. 消除 Windows 反斜杠
    assert "src/sub/mod_a.py" in p1.code_context_block
    assert "src/sub/mod_b.py" in p1.code_context_block
    assert "\\" not in p1.code_context_block

    # 2. 乱序传入产出完全相同的 context_block 与 prefix_hash
    assert p1.code_context_block == p2.code_context_block
    assert p1.prefix_hash == p2.prefix_hash
