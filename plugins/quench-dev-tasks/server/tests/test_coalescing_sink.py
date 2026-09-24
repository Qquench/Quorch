# -*- coding: utf-8 -*-
"""Unit tests for CoalescingTextSink and CoalescingStats in reviewer_engine.

Covers:
1. Subword / token-by-token aggregation across newline boundaries;
2. Multibyte, CJK and Emoji surrogate pair fragment streaming;
3. Blank line Markdown preservation (emits '\\n' without timestamp);
4. Maximum line length clamping and forced chunking;
5. Clock injection and idle flush triggering;
6. Live watchdog background timer flushing on stalled streams;
7. Zero tail loss on close() and flush(force=True) without trailing newline;
8. CoalescingStats telemetry accuracy across lifecycle;
9. Callback error tolerance (stderr warning without breaking stream);
10. Thread concurrency and race-free aggregation.
"""
from datetime import datetime
import re
import sys
import threading
import time
from typing import List

import pytest

from reviewer_engine import CoalescingStats, CoalescingTextSink


def test_coalescing_stats_dataclass():
    """验证 CoalescingStats 契约字段与不可变性。"""
    stats = CoalescingStats(
        lines_emitted=3,
        total_chars_fed=150,
        chars_currently_buffered=20,
        chunks_fed=10,
    )
    assert stats.lines_emitted == 3
    assert stats.total_chars_fed == 150
    assert stats.chars_currently_buffered == 20
    assert stats.chunks_fed == 10
    with pytest.raises(Exception):
        stats.lines_emitted = 4  # frozen dataclass


def test_basic_token_aggregation_with_newlines():
    """验证细粒度分片按自然换行符聚合成完整行，默认无时间戳污染保持纯净 Markdown。"""
    emitted: List[str] = []
    sink = CoalescingTextSink(emitted.append, tag="reasoning")

    # 模拟逐词甚至逐字符流式喂入
    tokens = ["Step ", "1: ", "analyzing ", "architecture.\n", "Step ", "2: ", "verifying ", "safety.\n"]
    for t in tokens:
        sink.feed(t)

    assert len(emitted) == 2
    assert emitted[0] == "Step 1: analyzing architecture.\n"
    assert emitted[1] == "Step 2: verifying safety.\n"

    sink.close()
    assert sink.stats.lines_emitted == 2
    assert sink.stats.chunks_fed == len(tokens)
    assert sink.stats.chars_currently_buffered == 0


def test_timestamp_and_tag_opt_in():
    """验证显式设置 include_timestamp=True 时正确输出 ISO 时间戳和 tag。"""
    emitted: List[str] = []
    sink = CoalescingTextSink(emitted.append, tag="reasoning", include_timestamp=True)

    sink.feed("Audit line 1.\nAudit line 2.\n")
    assert len(emitted) == 2
    for line in emitted:
        assert line.endswith("\n")
        assert "[reasoning]" in line
        assert re.match(r"^\d{4}-\d{2}-\d{2}T", line)

    sink.close()


def test_cjk_and_emoji_fragment_safety():
    """验证 CJK 汉字与 Emoji 代理对细粒度切片喂入时的聚合完整性与排版正确性。"""
    emitted: List[str] = []
    sink = CoalescingTextSink(emitted.append, tag="reasoning")

    # 逐字甚至 Emoji 切分
    sentence = "💡架构审查正在深入分析中，发现高并发竞争风险🚨！\n"
    for char in sentence:
        sink.feed(char)

    assert len(emitted) == 1
    assert emitted[0] == "💡架构审查正在深入分析中，发现高并发竞争风险🚨！\n"
    sink.close()


def test_markdown_blank_line_preservation():
    """验证连续换行或纯空白行直接输出 '\\n'，绝不插入虚假时间戳，严保 Markdown 语义。"""
    emitted: List[str] = []
    sink = CoalescingTextSink(emitted.append, tag="reasoning")

    # 段落 1，空行，段落 2
    sink.feed("Paragraph 1.\n\nParagraph 2.\n   \nParagraph 3.\n")

    assert len(emitted) == 5
    assert emitted[0] == "Paragraph 1.\n"
    assert emitted[1] == "\n"  # 纯空行
    assert emitted[2] == "Paragraph 2.\n"
    assert emitted[3] == "\n"  # 纯空格行
    assert emitted[4] == "Paragraph 3.\n"

    sink.close()
    assert sink.stats.lines_emitted == 5


def test_max_line_chars_clamping_and_forced_split():
    """验证 max_line_chars 强制下限钳制 (>=64) 以及单行超长无换行时的安全截断。"""
    emitted: List[str] = []
    # 尝试设置非法的极小值 10，应自动钳制为 64
    sink = CoalescingTextSink(emitted.append, max_line_chars=10, tag="audit")
    assert sink.max_line_chars == 64

    # 喂入 150 个字符且无换行
    long_text = "A" * 150
    sink.feed(long_text)

    # 150 字符在 max_line_chars=64 下，应立即切出 2 行（64 + 64 = 128），剩余 22 字符滞留
    assert len(emitted) == 2
    assert emitted[0] == "A" * 64 + "\n"
    assert emitted[1] == "A" * 64 + "\n"
    assert sink.stats.chars_currently_buffered == 22

    # close() 强制刷盘剩余 22 字符
    sink.close()
    assert len(emitted) == 3
    assert emitted[2] == "A" * 22 + "\n"
    assert sink.stats.chars_currently_buffered == 0
    assert sink.stats.lines_emitted == 3



def test_clock_injection_and_idle_flush():
    """验证时钟注入下 idle_flush_seconds 超时触发的确定性切行刷盘。"""
    emitted: List[str] = []
    simulated_time = 1000.0

    def fake_clock() -> float:
        return simulated_time

    # idle_flush_seconds = 0.5s
    sink = CoalescingTextSink(
        emitted.append,
        tag="reasoning",
        idle_flush_seconds=0.5,
        clock=fake_clock,
    )

    sink.feed("Thinking part 1")
    assert len(emitted) == 0
    assert sink.stats.chars_currently_buffered == len("Thinking part 1")

    # 时间只推进 0.2s，未达到 0.5s，flush() 不切行
    simulated_time += 0.2
    sink.flush(force=False)
    assert len(emitted) == 0

    # 时间推进到 0.6s，达到超时，feed("") 或 flush() 触发滞留行切分
    simulated_time += 0.4
    sink.flush(force=False)
    assert len(emitted) == 1
    assert "Thinking part 1" in emitted[0]
    assert sink.stats.chars_currently_buffered == 0

    sink.close()


def test_watchdog_background_idle_timer():
    """验证真实时钟下，后台 watchdog timer 在流式停顿时自动触发刷盘。"""
    emitted: List[str] = []
    sink = CoalescingTextSink(emitted.append, tag="reasoning", idle_flush_seconds=0.1)

    sink.feed("Stalled thought chunk")
    assert len(emitted) == 0

    # 等待 watchdog 触发 (0.1s + 缓冲区间)
    time.sleep(0.25)
    assert len(emitted) == 1
    assert "Stalled thought chunk" in emitted[0]

    sink.close()


def test_tail_flush_on_close_and_force_flush():
    """验证末行尾残（无换行符）在 close() 或 flush(force=True) 下完整落盘（零丢损 D9）。"""
    emitted: List[str] = []
    sink = CoalescingTextSink(emitted.append, tag="reasoning")

    sink.feed("Final conclusion without newline")
    assert len(emitted) == 0

    # force flush
    sink.flush(force=True)
    assert len(emitted) == 1
    assert "Final conclusion without newline" in emitted[0]
    assert sink.stats.chars_currently_buffered == 0

    # 再次喂入尾部片段并 close()
    sink.feed("Additional tail")
    sink.close()
    assert len(emitted) == 2
    assert "Additional tail" in emitted[1]

    # close 后再次调用 close 幂等且不报错
    sink.close()
    assert len(emitted) == 2


def test_emit_line_exception_safety():
    """验证 emit_line 抛异常时不会打断 feed() 流程，且降级捕获。"""
    def bad_emit(line: str) -> None:
        raise OSError("Disk full simulation")

    sink = CoalescingTextSink(bad_emit, tag="reasoning")
    # feed 遇到换行，即便 bad_emit 抛异常亦不传播
    sink.feed("Line that fails to emit\n")
    # 正常走完
    sink.close()


def test_thread_concurrency_stress():
    """多线程并发喂入测试，验证锁竞态保护与指标完整性。"""
    emitted: List[str] = []
    sink = CoalescingTextSink(emitted.append, tag="concurrency")

    num_threads = 5
    chunks_per_thread = 40

    def worker(worker_id: int):
        for i in range(chunks_per_thread):
            sink.feed(f"worker_{worker_id}_chunk_{i}\n")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    sink.close()
    stats = sink.stats
    assert stats.lines_emitted == num_threads * chunks_per_thread
    assert stats.chunks_fed == num_threads * chunks_per_thread
    assert len(emitted) == num_threads * chunks_per_thread
