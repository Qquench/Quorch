# -*- coding: utf-8 -*-
"""Unit tests for AST slice canonical ordering, LF normalization and multi-round context cache reuse.

Addresses Task 26.3:
1. explore_code_slices deterministic topological ordering across seed_files permutations.
2. SlicedFile.slice_text pure LF invariant.
3. resolve_context_files canonical (rel_path, start_line, end_line) ordering and pure LF.
4. PromptAssembler.sort_slices pure function & no in-place mutation.
5. PromptAssembler.format_slice_block SSOT formatting.
6. PromptAssembler.compute_slices_fingerprint permutation invariance.
7. PromptAssembler.get_or_render_code_context_block cache reuse across multi-round turns.
8. Multi-threaded concurrency safety for slice caching.
"""
from __future__ import annotations

import concurrent.futures
import os
from pathlib import Path
from typing import List

import pytest

from code_explorer import explore_code_slices
from consultation import resolve_context_files
from reviewer_engine import CodeSlice, PromptAssembler


def test_code_explorer_seed_order_determinism(tmp_path: Path):
    """断言 explore_code_slices 对不同顺序输入的 seed_files 返回完全相同顺序的 files 列表。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "z_module.py").write_text("def z_func(): pass\n", encoding="utf-8")
    (ws / "a_module.py").write_text("def a_func(): pass\n", encoding="utf-8")
    (ws / "m_module.py").write_text("def m_func(): pass\n", encoding="utf-8")

    res1 = explore_code_slices(str(ws), ["z_module.py", "a_module.py", "m_module.py"], max_hops=1)
    res2 = explore_code_slices(str(ws), ["a_module.py", "m_module.py", "z_module.py"], max_hops=1)
    res3 = explore_code_slices(str(ws), ["m_module.py", "z_module.py", "a_module.py"], max_hops=1)

    paths1 = [f.rel_path for f in res1.files]
    paths2 = [f.rel_path for f in res2.files]
    paths3 = [f.rel_path for f in res3.files]

    assert paths1 == ["a_module.py", "m_module.py", "z_module.py"]
    assert paths1 == paths2 == paths3


def test_code_explorer_slice_text_lf_only(tmp_path: Path):
    """断言即便源文件包含 CRLF 换行符，explore_code_slices 返回的 slice_text 仍保证为纯 LF。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    crlf_content = "def test_crlf():\r\n    x = 1\r\n    return x\r\n"
    (ws / "crlf_mod.py").write_bytes(crlf_content.encode("utf-8"))

    res = explore_code_slices(str(ws), ["crlf_mod.py"], max_hops=0)
    assert len(res.files) == 1
    assert "\r\n" not in res.files[0].slice_text
    assert "\n" in res.files[0].slice_text


def test_resolve_context_files_canonical_ordering_and_lf(tmp_path: Path):
    """断言 resolve_context_files 返回的 slices 按 (rel_path, start, end) 字典序排列且强制 LF。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "beta.py").write_bytes(b"line1\r\nline2\r\nline3\r\n")
    (ws / "alpha.py").write_bytes(b"foo1\r\nfoo2\r\nfoo3\r\n")

    # 乱序传入
    slices, skipped, truncated = resolve_context_files(
        str(ws),
        ["beta.py", "alpha.py"],
    )

    assert len(slices) == 2
    assert slices[0].rel_path == "alpha.py"
    assert slices[1].rel_path == "beta.py"

    for s in slices:
        assert "\r\n" not in s.text


def test_prompt_assembler_sort_slices_pure_function():
    """断言 sort_slices 纯函数性：绝不原地修改入参列表。"""
    s1 = CodeSlice(rel_path="z.py", start_line=1, end_line=10, text="z")
    s2 = CodeSlice(rel_path="a.py", start_line=5, end_line=15, text="a2")
    s3 = CodeSlice(rel_path="a.py", start_line=1, end_line=4, text="a1")

    orig_list = [s1, s2, s3]
    orig_copy = list(orig_list)

    sorted_res = PromptAssembler.sort_slices(orig_list)

    # 原列表顺序必须未变
    assert orig_list == orig_copy
    # 返回的新列表按 (rel_path, start_line, end_line) 正确升序
    assert sorted_res == [s3, s2, s1]


def test_prompt_assembler_format_slice_block_ssot():
    """断言 format_slice_block 统一格式化为 markdown code block 且换行符为 LF。"""
    s = CodeSlice(rel_path="src\\mod.py", start_line=1, end_line=2, text="def foo():\r\n    pass\r\n")
    formatted = PromptAssembler.format_slice_block(s)

    assert formatted.startswith("```\n")
    assert formatted.endswith("\n```")
    assert "\r\n" not in formatted
    assert "def foo():\n    pass" in formatted


def test_prompt_assembler_slices_fingerprint_invariance():
    """断言 compute_slices_fingerprint 在切片列表顺序颠倒时产出完全相同的指纹。"""
    s1 = CodeSlice(rel_path="b.py", start_line=1, end_line=10, text="content_b")
    s2 = CodeSlice(rel_path="a.py", start_line=1, end_line=20, text="content_a")

    fp1 = PromptAssembler.compute_slices_fingerprint([s1, s2])
    fp2 = PromptAssembler.compute_slices_fingerprint([s2, s1])

    assert len(fp1) == 16
    assert fp1 == fp2


def test_prompt_assembler_code_context_block_caching():
    """断言 get_or_render_code_context_block 在多轮调用中复用相同缓存对象。"""
    s1 = CodeSlice(rel_path="mod1.py", start_line=1, end_line=5, text="code1")
    s2 = CodeSlice(rel_path="mod2.py", start_line=1, end_line=5, text="code2")

    rendered1 = PromptAssembler.get_or_render_code_context_block([s1, s2])
    rendered2 = PromptAssembler.get_or_render_code_context_block([s2, s1])

    # 跨乱序返回完全相同的字符串
    assert rendered1 == rendered2
    # 空切片返回空字符串
    assert PromptAssembler.get_or_render_code_context_block([]) == ""


def test_prompt_assembler_multi_round_prefix_hash_invariance():
    """断言在多轮咨询中，Query 变更但代码切片不变时，AssembledPrompt 的 prefix_hash 保持 100% 恒定。"""
    slices = [
        CodeSlice(rel_path="core.py", start_line=1, end_line=10, text="def run(): pass\n"),
        CodeSlice(rel_path="util.py", start_line=1, end_line=5, text="def helper(): pass\n"),
    ]

    # 第 1 轮咨询
    p1 = PromptAssembler.assemble_consultation_prompt(
        mode="critique",
        slices=slices,
        query="第一轮提问：请审查整体并发安全性。",
    )

    # 第 2 轮咨询（乱序切片传入，Query 改变）
    p2 = PromptAssembler.assemble_consultation_prompt(
        mode="critique",
        slices=[slices[1], slices[0]],
        query="第二轮追问：helper 函数在死锁状态下的行为？",
    )

    assert p1.prefix_hash == p2.prefix_hash
    assert p1.code_context_block == p2.code_context_block
    assert p1.static_system_prefix == p2.static_system_prefix
    # 动态 Query 各自独立尾置
    assert p1.dynamic_query != p2.dynamic_query


def test_concurrent_slice_caching_thread_safety():
    """断言高并发多线程下切片缓存的线程安全性与数据完整性。"""
    def worker(idx: int) -> str:
        s = CodeSlice(rel_path=f"mod_{idx % 5}.py", start_line=1, end_line=10, text=f"code_{idx % 5}")
        return PromptAssembler.get_or_render_code_context_block([s])

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(50)]
        results = [f.result() for f in futures]

    assert len(results) == 50
    # mod_0 的所有结果必须完全一致
    mod0_res = [r for idx, r in enumerate(results) if idx % 5 == 0]
    assert all(r == mod0_res[0] for r in mod0_res)
