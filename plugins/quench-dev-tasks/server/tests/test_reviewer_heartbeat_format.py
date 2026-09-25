# -*- coding: utf-8 -*-
r"""Unit tests for Reviewer heartbeat formatting SSOT and pure English projection.

Verifies:
1. Canonical heartbeat display line strict regex contract:
   r'^\[Reviewer thinking: \d+ tokens \| \d+\.\d+s\]$'
2. Pure English invariant: Zero Chinese characters in heartbeat pulse line.
3. AdaptiveHeartbeatSink integration emits canonical heartbeat line to file log.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from reviewer_engine import AdaptiveHeartbeatSink, format_heartbeat_line

CANONICAL_HEARTBEAT_PATTERN = re.compile(r"^\[Reviewer thinking: \d+ tokens \| \d+\.\d+s\]$")
CJK_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def test_canonical_heartbeat_format_regex_contract():
    """format_heartbeat_line MUST strictly match the canonical regex contract."""
    test_cases = [
        (0, 0.0, "[Reviewer thinking: 0 tokens | 0.0s]"),
        (42, 1.23, "[Reviewer thinking: 42 tokens | 1.2s]"),
        (250, 5.0, "[Reviewer thinking: 250 tokens | 5.0s]"),
        (1048576, 3600.49, "[Reviewer thinking: 1048576 tokens | 3600.5s]"),
    ]

    for tokens, elapsed_s, expected in test_cases:
        actual = format_heartbeat_line(tokens, elapsed_s)
        assert actual == expected, f"Expected {expected!r}, got {actual!r}"
        assert CANONICAL_HEARTBEAT_PATTERN.match(actual), (
            f"Heartbeat line {actual!r} does not match canonical pattern {CANONICAL_HEARTBEAT_PATTERN.pattern}"
        )


def test_pure_english_display_no_cjk():
    """Heartbeat line must be strictly pure English with zero CJK characters."""
    samples = [
        format_heartbeat_line(0, 0.0),
        format_heartbeat_line(150, 2.5),
        format_heartbeat_line(9999, 88.8),
    ]
    for sample in samples:
        assert not CJK_CHAR_PATTERN.search(sample), (
            f"Heartbeat display contains forbidden CJK characters: {sample}"
        )
        assert "Reviewer thinking:" in sample
        assert "tokens" in sample


def test_adaptive_heartbeat_sink_uses_canonical_format():
    """AdaptiveHeartbeatSink must write format_heartbeat_line into the file log."""
    emitted_lines: list[str] = []
    sink = AdaptiveHeartbeatSink(
        file_emit=emitted_lines.append,
        interval_ms=500,
    )

    sink.on_heartbeat(tokens_so_far=88, elapsed_s=1.5)
    assert len(emitted_lines) == 1
    expected_inner = format_heartbeat_line(88, 1.5)
    assert f"[progress] {expected_inner}" in emitted_lines[0]
    assert not CJK_CHAR_PATTERN.search(emitted_lines[0])
