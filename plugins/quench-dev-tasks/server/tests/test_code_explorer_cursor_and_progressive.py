# -*- coding: utf-8 -*-
"""Tests for cursor pagination, progressive code exploration, and multi-root sandbox.

Validates acceptance assertions A-1 through A-12 and defensive invariants D-1 through D-12.
"""
from __future__ import annotations

import os
import re
import sys
import pytest
from pathlib import Path

from code_explorer import (
    CodeExplorerError,
    DirListing,
    GrepResult,
    LineWindow,
    SlicedFile,
    UnsafePathError,
    build_line_window,
    build_safe_slice,
    explore_code_slices,
    grep,
    is_path_safe,
    list_dir,
    read_file_slice,
    resolve_within_roots,
    RING1_MAX_BYTES,
    RING1_MAX_LINES,
    MAX_FILE_BYTES,
    MAX_GREP_HITS,
    MAX_GREP_HITS_PER_FILE,
    MAX_GREP_PATTERN_CHARS,
    MAX_LIST_ENTRIES,
    MAX_SLICE_LINES,
)


def test_a1_read_authority_and_cursor():
    """A-1 续读权威性：250 行文件 page(0).next_offset==100，page(100).next_offset==200，page(200).next_offset is None。"""
    # 构造恰好 250 行（无末尾换行）
    source_text = "\n".join(f"line_{i}" for i in range(250))

    # Page 1: 0..99
    p0 = build_line_window(source_text, offset=0, limit=100)
    assert p0.start_line == 1
    assert p0.end_line == 100
    assert p0.total_lines == 250
    assert p0.next_offset == 100
    assert p0.byte_capped is False

    # Page 2: 100..199
    p1 = build_line_window(source_text, offset=p0.next_offset, limit=100)
    assert p1.start_line == 101
    assert p1.end_line == 200
    assert p1.total_lines == 250
    assert p1.next_offset == 200
    assert p1.byte_capped is False

    # Page 3: 200..249
    p2 = build_line_window(source_text, offset=p1.next_offset, limit=100)
    assert p2.start_line == 201
    assert p2.end_line == 250
    assert p2.total_lines == 250
    assert p2.next_offset is None
    assert p2.byte_capped is False


def test_a2_concatenation_equivalence_property():
    """A-2 拼接等价性：连续分页 "\n".join(p.text for p in pages) == source_text（含结尾换行与不含结尾换行两例）。"""
    # Case 1: 不含末尾换行 (250 行)
    text1 = "\n".join(f"content_{i}" for i in range(250))
    pages1: list[LineWindow] = []
    curr_offset: int | None = 0
    while curr_offset is not None:
        win = build_line_window(text1, offset=curr_offset, limit=100)
        pages1.append(win)
        curr_offset = win.next_offset

    assert len(pages1) == 3
    assert "\n".join(p.text for p in pages1) == text1
    for i in range(1, len(pages1)):
        assert pages1[i].start_line == pages1[i - 1].end_line + 1
    assert pages1[0].start_line == 1
    assert pages1[-1].end_line == 250

    # Case 2: 含末尾换行 (251 行，末行空字符串)
    text2 = "\n".join(f"content_{i}" for i in range(250)) + "\n"
    pages2: list[LineWindow] = []
    curr_offset = 0
    while curr_offset is not None:
        win = build_line_window(text2, offset=curr_offset, limit=100)
        pages2.append(win)
        curr_offset = win.next_offset

    assert len(pages2) == 3
    assert "\n".join(p.text for p in pages2) == text2
    for i in range(1, len(pages2)):
        assert pages2[i].start_line == pages2[i - 1].end_line + 1
    assert pages2[0].start_line == 1
    assert pages2[-1].end_line == 251


def test_a3_line_atomicity_and_byte_budget():
    """A-3 行原子性：外环(64KB)下 100KB 单行 -> 整行返回、len(text)==行长、byte_capped is True、next_offset==offset+1、无字符丢失。"""
    big_line = "A" * (100 * 1024)
    src = f"{big_line}\nsecond_line"

    p0 = build_line_window(src, offset=0, limit=100, max_bytes=RING1_MAX_BYTES)
    assert p0.text == big_line
    assert len(p0.text) == 100 * 1024
    assert p0.byte_capped is True
    assert p0.next_offset == 1
    assert p0.start_line == 1
    assert p0.end_line == 1

    p1 = build_line_window(src, offset=p0.next_offset, limit=100, max_bytes=RING1_MAX_BYTES)
    assert p1.text == "second_line"
    assert p1.byte_capped is False
    assert p1.next_offset is None
    assert p1.start_line == 2
    assert p1.end_line == 2

    # 往返重组无缝
    assert "\n".join([p0.text, p1.text]) == src


def test_a4_out_of_bounds_and_empty_file():
    """A-4 越界与空文件：offset>=total_lines -> text==""且 next_offset is None 不抛异常；source_text=="" -> total_lines==0。"""
    # 空文件契约
    empty_win = build_line_window("")
    assert empty_win.text == ""
    assert empty_win.total_lines == 0
    assert empty_win.start_line == 1
    assert empty_win.end_line == 0
    assert empty_win.next_offset is None
    assert empty_win.byte_capped is False

    # 越界契约
    src = "line0\nline1"
    oob_win = build_line_window(src, offset=10**6)
    assert oob_win.text == ""
    assert oob_win.total_lines == 2
    assert oob_win.start_line == 3
    assert oob_win.end_line == 2
    assert oob_win.next_offset is None
    assert oob_win.byte_capped is False


def test_a5_first_line_never_rejected_even_extreme_budget():
    """A-5 首行永不拒：offset=0 首行超 max_bytes 仍返回整行，max_bytes=1 时亦不得死循环，且 A-2 拼接仍精确成立。"""
    line0 = "X" * 200_000
    src = f"{line0}\nline1\nline2"

    pages: list[LineWindow] = []
    curr_offset: int | None = 0
    while curr_offset is not None:
        p = build_line_window(src, offset=curr_offset, limit=10, max_bytes=1)
        pages.append(p)
        curr_offset = p.next_offset

    assert len(pages) == 3
    assert pages[0].text == line0
    assert pages[0].byte_capped is True
    assert pages[0].next_offset == 1

    assert pages[1].text == "line1"
    assert pages[1].byte_capped is True
    assert pages[1].next_offset == 2

    assert pages[2].text == "line2"
    assert pages[2].byte_capped is False
    assert pages[2].next_offset is None

    assert "\n".join(p.text for p in pages) == src


def test_a6_root_rejection_family(tmp_path: Path):
    """A-6 根拒绝族："", "\x00", "/", "C:/", "C:", "\\\\?\\C:\\", "\\\\server\\share" -> resolve_within_roots 返回 None。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    ws_str = str(ws)

    bad_targets = ["", "\x00", "/", "C:/", "C:", "\\\\?\\C:\\", "\\\\server\\share", "CON", "PRN", "NUL"]
    for bt in bad_targets:
        assert resolve_within_roots(ws_str, bt) is None, f"Expected None for {bt!r}"

    # allowed_roots 中若传入 C:/ 或 / 恒被拒绝
    assert resolve_within_roots(ws_str, "C:/Windows", allowed_roots=["C:/"]) is None
    assert resolve_within_roots(ws_str, "D:/data", allowed_roots=None) is None

    # 合法兄弟目录多根支持
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sib_file = sibling / "lib.py"
    sib_file.write_text("print('hello')", encoding="utf-8")

    # 未指定 allowed_roots 时拒绝
    assert resolve_within_roots(ws_str, str(sib_file), allowed_roots=None) is None
    # 指定 allowed_roots 时放行
    matched = resolve_within_roots(ws_str, str(sib_file), allowed_roots=[str(sibling)])
    assert matched is not None
    root_real, target_real = matched
    assert os.path.normcase(root_real) == os.path.normcase(os.path.realpath(str(sibling)))


def test_a7_symlink_escape_defense(tmp_path: Path):
    """A-7 符号链接防御：root 内 symlink 指向外部 -> None。"""
    ws = tmp_path / "ws"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("classified", encoding="utf-8")

    symlink_path = ws / "sym_link"
    try:
        os.symlink(str(outside), str(symlink_path), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink not permitted in this environment")

    escaped_target = str(symlink_path / "secret.txt")
    assert resolve_within_roots(str(ws), escaped_target) is None
    assert is_path_safe(str(ws), escaped_target) is False


def test_a8_windows_normcase(tmp_path: Path):
    """A-8 (Windows) normcase 双端归一：大小写差异路径命中 root（POSIX 上用例 skip）。"""
    if sys.platform != "win32":
        pytest.skip("Windows-specific normcase test")

    ws = tmp_path / "Workspace"
    ws.mkdir()
    f = ws / "Target.py"
    f.write_text("x = 1\n", encoding="utf-8")

    # 大小写不一致传入
    lower_target = os.path.join(str(ws).lower(), "target.py")
    res = resolve_within_roots(str(ws), lower_target)
    assert res is not None
    assert is_path_safe(str(ws), lower_target) is True


def test_a9_external_budget_and_hint(tmp_path: Path):
    """A-9 外环预算：origin=="external" -> limit<=40、max_bytes<=64KB；单行过冲场景 page 字节<=512KB 硬顶。"""
    ws = tmp_path / "ws"
    ext_dir = tmp_path / "ext"
    ws.mkdir()
    ext_dir.mkdir()

    # 100 行外部文件
    ext_file = ext_dir / "external_data.py"
    lines = [f"var_{i} = {i}" for i in range(100)]
    ext_file.write_text("\n".join(lines), encoding="utf-8")

    # limit=1000 请求，强制钳制为 40 行
    sliced = read_file_slice(str(ws), str(ext_file), offset=0, limit=1000, allowed_roots=[str(ext_dir)])
    assert sliced.origin == "external"
    assert len(sliced.slice_text.split("\n")) <= 40
    assert sliced.next_offset == 40
    assert "[EXTERNAL]" in sliced.hint
    assert sliced.hint not in sliced.slice_text
    assert len(sliced.slice_text.encode("utf-8")) <= RING1_MAX_BYTES


def test_a10_grep_contract(tmp_path: Path):
    """A-10 正则卫生：len(pattern)>1024 被拒；非法正则抛 CodeExplorerError；单行仅扫描前 4096 字符；每文件<=20 行，全局<=200。"""
    ws = tmp_path / "ws"
    ws.mkdir()

    # 非法正则
    with pytest.raises(CodeExplorerError):
        grep(str(ws), "[unclosed-bracket")

    # 长度超过 MAX_GREP_PATTERN_CHARS (1024)
    with pytest.raises(CodeExplorerError):
        grep(str(ws), "a" * (MAX_GREP_PATTERN_CHARS + 1))

    # 空模式
    with pytest.raises(CodeExplorerError):
        grep(str(ws), "")

    # 构造单个文件 25 处命中
    f1 = ws / "many_hits.py"
    f1.write_text("\n".join(f"target_marker_{i}" for i in range(25)), encoding="utf-8")

    res = grep(str(ws), r"target_marker_\d+")
    assert len(res.histogram) == 1
    assert res.histogram[0].count == 25  # 真实命中数不受 per-file 行上限影响
    assert len(res.matches) == 20       # 每文件 matches 最多 20 条 (MAX_GREP_HITS_PER_FILE)

    # 构造超长行：匹配在 4096 之后应漏检，在 4096 之前命中
    f2 = ws / "long_line.py"
    long_line_hit = "FIND_ME_" + ("y" * 5000)
    long_line_miss = ("z" * 4100) + "FIND_ME_LATE"
    f2.write_text(f"{long_line_hit}\n{long_line_miss}\n", encoding="utf-8")

    res_long = grep(str(ws), "FIND_ME_")
    matched_texts = [m.text for m in res_long.matches if m.rel_path == "long_line.py"]
    assert len(matched_texts) == 1
    assert matched_texts[0] == long_line_hit  # 原始整行保留返回

    # 排序与耗时检查
    assert res.elapsed_ms >= 0


def test_a11_deadline_immediate_cutoff(tmp_path: Path):
    """A-11 超时熔断：deadline<=0 -> 立即熔断返回，elapsed_ms>=0，不抛异常；truncated 不变量断言。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "file.py").write_text("alpha\nbeta\n", encoding="utf-8")

    res = grep(str(ws), "alpha", deadline=0.0)
    assert res.truncated is True
    assert res.files_scanned == 0
    assert res.elapsed_ms >= 0

    # truncated 不变量：truncated == (next_offset is not None)
    s_full = read_file_slice(str(ws), "file.py", offset=0, limit=100)
    assert s_full.truncated is False
    assert s_full.next_offset is None

    s_part = read_file_slice(str(ws), "file.py", offset=0, limit=1)
    assert s_part.truncated is True
    assert s_part.next_offset == 1


def test_a12_encoding_binary_and_list_dir(tmp_path: Path):
    """A-12 编码/二进制与确定性：非 UTF-8 errors='replace'；NUL 二进制跳过；list_dir 单层字典序与 omitted。"""
    ws = tmp_path / "ws"
    ws.mkdir()

    # 二进制文件
    (ws / "bin.dat").write_bytes(b"\x00\x01\x02\x03\x04")
    # 正常文本
    (ws / "text.txt").write_bytes("hello world\n".encode("utf-8"))

    res = grep(str(ws), "hello")
    rel_paths = [h.rel_path for h in res.histogram]
    assert "text.txt" in rel_paths
    assert "bin.dat" not in rel_paths

    # list_dir 测试
    sub_dir = ws / "sub_dir"
    sub_dir.mkdir()
    for i in range(10):
        (ws / f"f_{i:02d}.py").write_text(f"# {i}", encoding="utf-8")

    listing = list_dir(str(ws), max_entries=5)
    assert listing.origin == "workspace"
    assert listing.total_entries == 13  # bin.dat, text.txt, sub_dir, 10 * f_*.py
    assert len(listing.entries) == 5
    assert listing.omitted == 8
    # 目录优先
    assert listing.entries[0].kind == "dir"
    assert listing.entries[0].name == "sub_dir"

    # 非目录调用 list_dir 抛 CodeExplorerError
    with pytest.raises(CodeExplorerError):
        list_dir(str(ws), "text.txt")

    # 向后兼容性断言：allowed_roots=None 时与 is_path_safe 一致
    assert is_path_safe(str(ws), "text.txt") is True
    assert is_path_safe(str(ws), "../outside") is False
    assert (resolve_within_roots(str(ws), "text.txt") is not None) == is_path_safe(str(ws), "text.txt")


def test_a13_constants_evolution_and_long_regex(tmp_path: Path):
    """A-13 常量演进与长正则支持：MAX_GREP_HITS_PER_FILE=20, MAX_GREP_PATTERN_CHARS=1024。"""
    assert MAX_GREP_HITS_PER_FILE == 20
    assert MAX_GREP_PATTERN_CHARS == 1024

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "sample.py").write_text("class TestServiceStateEngine:\n    pass\n", encoding="utf-8")

    # 超过旧上限 200 字符但 <= 1024 字符的合法联合长正则
    long_pattern = "class Test" + "(?:Service|Client|Engine|State)*" * 20
    assert 200 < len(long_pattern) <= 1024

    res = grep(str(ws), long_pattern)
    assert len(res.matches) == 1
    assert res.matches[0].rel_path == "sample.py"
    assert "class TestServiceStateEngine" in res.matches[0].text

    # 超过 1024 字符触发 CodeExplorerError
    too_long_pattern = "a" * (MAX_GREP_PATTERN_CHARS + 1)
    with pytest.raises(CodeExplorerError):
        grep(str(ws), too_long_pattern)


def test_a14_list_dir_cursor_pagination_and_equivalence(tmp_path: Path):
    """A-14 list_dir 游标分页遍历与全集等价性。"""
    ws = tmp_path / "ws_pagination"
    ws.mkdir()

    # 创建 5 个子目录与 20 个文件
    for d in range(5):
        (ws / f"dir_{d:02d}").mkdir()
    for f in range(20):
        (ws / f"file_{f:02d}.txt").write_text(f"content {f}", encoding="utf-8")

    # 1. 一次性获取全量
    full_listing = list_dir(str(ws), max_entries=100)
    assert full_listing.total_entries == 25
    assert len(full_listing.entries) == 25
    assert full_listing.omitted == 0
    assert full_listing.offset == 0
    assert full_listing.next_offset is None

    # 2. 分页遍历（每页 7 条）
    paged_entries = []
    current_offset: int | None = 0
    page_count = 0

    while current_offset is not None:
        page = list_dir(str(ws), max_entries=7, offset=current_offset)
        page_count += 1
        assert page.offset == current_offset
        paged_entries.extend(page.entries)
        if current_offset + len(page.entries) < page.total_entries:
            assert page.next_offset == current_offset + len(page.entries)
        else:
            assert page.next_offset is None
        current_offset = page.next_offset

    # 3. 验证分页累积全集与一次性全集完全等价
    assert page_count == 4  # 7 + 7 + 7 + 4 = 25
    assert len(paged_entries) == len(full_listing.entries)
    assert [e.name for e in paged_entries] == [e.name for e in full_listing.entries]
    assert [e.kind for e in paged_entries] == [e.kind for e in full_listing.entries]

    # 4. 边界防御断言
    # offset < 0 自动钳位至 0
    clamped_page = list_dir(str(ws), max_entries=5, offset=-10)
    assert clamped_page.offset == 0
    assert len(clamped_page.entries) == 5

    # offset >= total_entries 返回空 entries 且 next_offset 为 None
    overflow_page = list_dir(str(ws), max_entries=5, offset=30)
    assert overflow_page.offset == 30
    assert len(overflow_page.entries) == 0
    assert overflow_page.next_offset is None
    assert overflow_page.omitted == 25


def test_a15_grep_histogram_and_hits_decoupling(tmp_path: Path):
    """A-15 grep matches 截断与直方图统计解耦：单文件超 20 行时，matches 截断而 histogram 保留真实总数。"""
    ws = tmp_path / "ws_grep"
    ws.mkdir()

    # 构造一个包含 35 行匹配的文件
    lines = [f"LOG_LINE_{i:02d}: error_detected in subsystem" for i in range(35)]
    (ws / "heavy.log").write_text("\n".join(lines), encoding="utf-8")

    res = grep(str(ws), "error_detected")
    # 验证 matches 严格受 MAX_GREP_HITS_PER_FILE (20) 截断
    assert len(res.matches) == 20
    assert res.matches[0].rel_path == "heavy.log"
    assert res.matches[19].rel_path == "heavy.log"

    # 验证 histogram 真实记录了全部 35 处命中，不受 matches 截断污染
    assert len(res.histogram) == 1
    assert res.histogram[0].rel_path == "heavy.log"
    assert res.histogram[0].count == 35
