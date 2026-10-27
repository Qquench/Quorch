# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Unit tests for Task 26.2: Static system prefix 64-byte block alignment padding and prompt stability."""

import dataclasses
import pytest

from reviewer_engine import (
    STATIC_PREFIX_BLOCK_BYTES,
    align_static_prefix_to_block,
    AssembledPrompt,
    CodeSlice,
    PromptAssembler,
)


def test_fill_is_pure_function():
    """同一入参调用两次，输出字节恒等；纯函数无状态、无副作用。"""
    prefix = "Sample static prefix for audit"
    res1 = align_static_prefix_to_block(prefix, block_bytes=64)
    res2 = align_static_prefix_to_block(prefix, block_bytes=64)
    assert res1 == res2
    assert len(res1) % 64 == 0
    assert res1.startswith(prefix)


def test_fill_empty_prefix_returns_empty():
    """空前缀返回空串，严禁注入 64 字节幽灵填充。"""
    assert align_static_prefix_to_block("") == ""
    assert align_static_prefix_to_block("", block_bytes=64) == ""


def test_fill_already_aligned_is_identity():
    """长度已为 block_bytes 整数倍的前缀恒等返回原串（幂等）。"""
    aligned_64 = "x" * 64
    assert align_static_prefix_to_block(aligned_64, block_bytes=64) == aligned_64

    aligned_128 = "y" * 128
    assert align_static_prefix_to_block(aligned_128, block_bytes=64) == aligned_128


def test_fill_uses_lf_only():
    """填充严格仅追加 LF (\\n)，严禁出现 \\r、空格或 \\r\\n；支持多字节/中文字符近似。"""
    prefix = "Prefix with some text"
    res = align_static_prefix_to_block(prefix, block_bytes=64)
    assert "\r" not in res
    padding = res[len(prefix):]
    assert set(padding) == {"\n"}
    assert len(res) % 64 == 0

    # 中文前缀测试
    chinese_prefix = "项目法定工程约束与审查纪律规范"
    res_cn = align_static_prefix_to_block(chinese_prefix, block_bytes=64)
    assert "\r" not in res_cn
    padding_cn = res_cn[len(chinese_prefix):]
    assert set(padding_cn) == {"\n"}
    assert len(res_cn) % 64 == 0


def test_fill_does_not_touch_slices():
    """调用 assemble_consultation_prompt 后，context_block 与 dynamic_tail 严格段落隔离，不被填充影响。"""
    slices = [
        CodeSlice("src/calc.py", 1, 10, "def add(a, b):\n    return a + b"),
        CodeSlice("src/util.py", 20, 30, "def helper():\n    pass"),
    ]
    query = "Check arithmetic invariants"
    raw_prefix = "Custom Static System Prefix (Unpadded)"

    p_assembled = PromptAssembler.assemble_consultation_prompt(
        mode="audit",
        slices=slices,
        query=query,
        static_system_prefix=raw_prefix,
    )

    # 验证段②切片与段④query逐字未受前缀填充影响
    assert "def add(a, b):" in p_assembled.context_block
    assert "def helper():" in p_assembled.context_block
    assert p_assembled.dynamic_tail == f"{p_assembled.mode_anchor}\n\n{p_assembled.dynamic_query}"
    assert "Check arithmetic invariants" in p_assembled.dynamic_query


def test_slots_and_frozen_preserved():
    """断言 AssembledPrompt 仍满足 frozen=True, slots=True，且产出的 stable_prefix 达到 64 对齐。"""
    slices = [CodeSlice("pkg/mod.py", 1, 5, "x = 1")]
    p = PromptAssembler.assemble_consultation_prompt(
        mode="evaluate",
        slices=slices,
        query="Evaluate mod",
        static_system_prefix="Short Prefix",
    )

    # slots=True 无 __dict__
    assert not hasattr(p, "__dict__")

    # frozen=True 属性只读
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.static_system_prefix = "mutated"  # type: ignore

    # assemble 产出的 stable_prefix 长度已达到 64 字节对齐
    assert len(p.stable_prefix) % 64 == 0
    assert p.stable_prefix == p.static_system_prefix


def test_prefix_hash_invariance_under_fill():
    """断言填充绝不进入 prefix_hash 计算，两次不同 query 下 hash 严格恒等。"""
    slices = [CodeSlice("core.py", 1, 15, "class Core:\n    pass")]
    raw_prefix = "Fixed Static Prefix 123"

    p1 = PromptAssembler.assemble_consultation_prompt(
        mode="critique",
        slices=slices,
        query="Query 1",
        static_system_prefix=raw_prefix,
    )
    p2 = PromptAssembler.assemble_consultation_prompt(
        mode="critique",
        slices=slices,
        query="Query 2 (completely different content)",
        static_system_prefix=raw_prefix,
    )

    assert p1.prefix_hash == p2.prefix_hash
    assert p1.stable_prefix == p2.stable_prefix
    assert p1.context_block == p2.context_block


def test_existing_assembled_prompt_constructor_unchanged():
    """防回归测试：直接构造 AssembledPrompt(static_system_prefix='raw', ...) 保持 raw 语义不变。"""
    raw_input = "raw unpadded prefix"
    ap = AssembledPrompt(
        static_system_prefix=raw_input,
        code_context_block="ctx",
        mode_anchor="mode",
        dynamic_query="q",
        prefix_hash="0123456789abcdef",
    )
    assert ap.static_system_prefix == raw_input
    assert ap.stable_prefix == raw_input


def test_invalid_block_bytes_raises():
    """block_bytes <= 0 必须抛出 ValueError。"""
    with pytest.raises(ValueError, match="block_bytes must be positive"):
        align_static_prefix_to_block("test", block_bytes=0)

    with pytest.raises(ValueError, match="block_bytes must be positive"):
        align_static_prefix_to_block("test", block_bytes=-1)
