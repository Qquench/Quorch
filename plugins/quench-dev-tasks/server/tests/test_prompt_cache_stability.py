# -*- coding: utf-8 -*-
"""Unit tests for Prompt Cache Stability Gradient and PromptAssembler.

Validates the four-stage prompt caching topology:
1. Static System Baseline (System cache)
2. Mode Guidance & Output Protocols (Session prefix)
3. Deterministic POSIX Code Slices (Context block)
4. Dynamic Query & Task ID (Strict tail position)

Asserts:
- Exact prefix_hash invariance under query variations
- CodeSlice backward compatibility (frozen dataclass, positional args, no slots)
- Clean relative POSIX paths without mtimes or absolute paths
- Quench stack architecture_doc resolution to docs/architecture/README.md
"""
import dataclasses
import os
import re
from pathlib import Path

import pytest

import consultation
from consultation import render_mode_prompt
import reviewer_engine
from reviewer_engine import (
    AssembledPrompt,
    CodeSlice,
    PromptAssembler,
)
from project_config import load_project_config


def test_code_slice_backward_compatibility():
    """断言 CodeSlice 契约零回归：跨模块同一性、位置参数构造、.text 访问与 dataclasses.asdict。"""
    # 1. 跨模块导入同一性
    assert consultation.CodeSlice is reviewer_engine.CodeSlice

    # 2. 位置参数构造 (rel_path, start_line, end_line, text)
    cs = CodeSlice("src/core/engine.py", 10, 50, "# file: src/core/engine.py:10-50\ndef run(): pass")
    assert cs.rel_path == "src/core/engine.py"
    assert cs.start_line == 10
    assert cs.end_line == 50
    assert cs.text == "# file: src/core/engine.py:10-50\ndef run(): pass"

    # 3. 不可变性 (frozen)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cs.text = "modified"  # type: ignore

    # 4. 保留 __dict__ (显式未加 slots，以保护既有生态反射/weakref)
    assert hasattr(cs, "__dict__")

    # 5. dataclasses.asdict 键序与值完全兼容
    d = dataclasses.asdict(cs)
    assert list(d.keys()) == ["rel_path", "start_line", "end_line", "text"]
    assert d["rel_path"] == "src/core/engine.py"
    assert d["start_line"] == 10
    assert d["end_line"] == 50
    assert d["text"] == "# file: src/core/engine.py:10-50\ndef run(): pass"


def test_assembled_prompt_slots_structure():
    """断言 AssembledPrompt 结构满足 frozen=True 且 slots=True。"""
    ap = AssembledPrompt(
        stable_prefix="prefix",
        context_block="context",
        dynamic_tail="tail",
        prefix_hash="1234567890abcdef",
    )
    assert ap.stable_prefix == "prefix"
    assert ap.context_block == "context"
    assert ap.dynamic_tail == "tail"
    assert ap.prefix_hash == "1234567890abcdef"

    # AssembledPrompt 启用了 slots=True，因此默认无 __dict__
    assert not hasattr(ap, "__dict__")

    with pytest.raises(dataclasses.FrozenInstanceError):
        ap.prefix_hash = "other"  # type: ignore


def test_prompt_assembler_prefix_hash_invariance_under_query_variation():
    """断言在模式与代码切片相同时，多次组装产出的 prefix_hash 绝对一致，且 query 变化不影响 prefix_hash。"""
    slices = [
        CodeSlice("src/b.py", 1, 20, "# file: src/b.py:1-20\nclass B: pass"),
        CodeSlice("src/a.py", 5, 15, "# file: src/a.py:5-15\ndef a(): pass"),
    ]

    p1 = PromptAssembler.assemble_consultation_prompt(
        mode="critique",
        slices=slices,
        query="First query: How does B interact with a?",
    )
    p2 = PromptAssembler.assemble_consultation_prompt(
        mode="critique",
        slices=slices,
        query="Second query: Is there any deadlock in B?",
    )

    # 1. 前缀哈希长度为 16 位十六进制
    assert len(p1.prefix_hash) == 16
    assert re.match(r"^[0-9a-f]{16}$", p1.prefix_hash)

    # 2. query 无论如何变化，前缀哈希 100% 保持完全不变
    assert p1.prefix_hash == p2.prefix_hash
    assert p1.stable_prefix == p2.stable_prefix
    assert p1.context_block == p2.context_block

    # 3. 动态 tail 严格隔离并反映对应 query
    assert "First query" in p1.dynamic_tail
    assert "First query" not in p2.dynamic_tail
    assert "Second query" in p2.dynamic_tail


def test_prompt_assembler_slices_deterministic_alphabetical_sorting():
    """断言无论传入切片的初始顺序如何，组装后的 context_block 均按相对路径字典序稳定排序。"""
    s_z = CodeSlice("src/z.py", 1, 10, "# file: src/z.py:1-10\nZ = 1")
    s_a = CodeSlice("src/a.py", 1, 10, "# file: src/a.py:1-10\nA = 1")
    s_m = CodeSlice("src/m.py", 1, 10, "# file: src/m.py:1-10\nM = 1")

    # 乱序传入
    p_order1 = PromptAssembler.assemble_consultation_prompt(
        mode="critique",
        slices=[s_z, s_a, s_m],
        query="test query",
    )
    p_order2 = PromptAssembler.assemble_consultation_prompt(
        mode="critique",
        slices=[s_a, s_m, s_z],
        query="test query",
    )

    # 两次不同顺序的输入产出的 context_block 与 prefix_hash 必须逐字节绝对一致
    assert p_order1.context_block == p_order2.context_block
    assert p_order1.prefix_hash == p_order2.prefix_hash

    # 切片在 context_block 中按 a -> m -> z 顺序呈现
    pos_a = p_order1.context_block.find("src/a.py")
    pos_m = p_order1.context_block.find("src/m.py")
    pos_z = p_order1.context_block.find("src/z.py")
    assert pos_a != -1 and pos_m != -1 and pos_z != -1
    assert pos_a < pos_m < pos_z


def test_prompt_assembler_pure_relative_paths_and_no_timestamps():
    """断言前三段稳定前缀绝无绝对路径、Windows 反斜杠或动态时间戳。"""
    # 模拟包含 Windows 反斜杠的切片路径
    s = CodeSlice("src\\utils\\helper.py", 1, 10, "# file: src\\utils\\helper.py:1-10\ndef h(): pass")
    prompt = PromptAssembler.assemble_consultation_prompt(
        mode="critique",
        slices=[s],
        query="my question",
    )

    # 1. 验证 context_block 中的路径已规范化为 POSIX 斜杠
    assert "src/utils/helper.py" in prompt.context_block
    assert "\\" not in prompt.context_block

    # 2. 检查 stable_prefix 与 context_block 中绝不包含常见的系统盘符或绝对路径模式
    for block in (prompt.stable_prefix, prompt.context_block):
        assert "C:" not in block
        assert "D:" not in block
        assert "/Users/" not in block
        assert "/home/" not in block
        # 绝无 ISO-8601 或时间戳字面量
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", block)


def test_render_mode_prompt_places_query_strictly_at_tail():
    """断言 consultation.render_mode_prompt 组装结果中，Query 处于最尾部，前缀为协议与切片。"""
    s = CodeSlice("src/service.py", 1, 20, "# file: src/service.py:1-20\nclass Service: pass")
    query_text = "ULTRA_UNIQUE_DYNAMIC_QUERY_TOKEN_98765"
    rendered = render_mode_prompt("critique", query_text, [s])

    # 1. 必须包含各段内容
    assert "### Mode: Architectural Critique" in rendered
    assert "### Protocols for Reviewer Output" in rendered
    assert "### Injected Code Context Slices" in rendered
    assert query_text in rendered

    # 2. Query 必须在切片和协议之后
    pos_protocols = rendered.find("### Protocols for Reviewer Output")
    pos_slices = rendered.find("### Injected Code Context Slices")
    pos_query = rendered.find("### Consultation Query")

    assert pos_protocols < pos_slices < pos_query
    # Query 块处于最末尾
    assert rendered.endswith(query_text)


def test_quench_stack_architecture_doc_path_and_resolution():
    """断言 quench_stack.yaml 中 architecture_doc 指向真实存在的 docs/architecture/README.md。"""
    ws_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    config = load_project_config(ws_root)

    # 1. 配置路径必须是 docs/architecture/README.md
    assert config.architecture_doc == "docs/architecture/README.md"

    # 2. 工作区中对应文件客观存在
    arch_file = os.path.join(ws_root, config.architecture_doc)
    assert os.path.isfile(arch_file), f"Architecture file not found: {arch_file}"

    # 3. 验证 build_static_system_prefix 成功挂载该架构设计文档
    prefix = PromptAssembler.build_static_system_prefix(ws_root, config)
    assert "Quench Dev-Orchestrator — System Architecture" in prefix
    assert "docs/architecture/README.md" in prefix
