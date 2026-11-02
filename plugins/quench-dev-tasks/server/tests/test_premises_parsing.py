# -*- coding: utf-8 -*-
"""Unit tests for Reviewer premises parsing and well-formedness contracts.

Covers assertions (a) through (l) for Phase 1 Epic C:
(a) Single block full labels falsifiable=True;
(b) No tags returns empty list;
(c) Non-true tokens parse as False;
(d) 13 blocks clamped to 12;
(e) Premise length 2049 overrides falsifiable to False (override > token precedence);
(f) Flip condition length 2049 overrides falsifiable to False;
(g) Premise length 2048 retains falsifiable=True (cliff double anchor);
(h) Premise with extra colons preserved via first-colon partition;
(i) Lines without colon skipped;
(j) assert_premises_wellformed contract checks;
(k) test_premises_pattern_has_no_textual_corruption;
(l) Case and whitespace normalization for falsifiable tokens.
"""
from __future__ import annotations

import pytest

from consultation import (
    MAX_PREMISES_PER_VERDICT,
    MAX_PREMISE_FIELD_CHARS,
    PREMISES_PATTERN,
    PremiseRecord,
    assert_premises_wellformed,
    parse_premises,
)


def test_single_block_full_labels_falsifiable_true():
    """(a) 单块全标签 falsifiable 真 -> len==1 且 r[0].falsifiable is True。"""
    findings = (
        "Analysis notes:\n"
        "<<<PREMISES>>>\n"
        "premise: Cache key depends on sorted file paths\n"
        "flip_condition: Unsorted paths cause cache miss\n"
        "falsifiable: true\n"
        "<<<END>>>\n"
        "Conclusion."
    )
    records = parse_premises(findings)
    assert len(records) == 1
    assert records[0].premise == "Cache key depends on sorted file paths"
    assert records[0].flip_condition == "Unsorted paths cause cache miss"
    assert records[0].falsifiable is True


def test_no_tags_returns_empty_list():
    """(b) 无标签 -> []。"""
    assert parse_premises("Just free text findings without tags.") == []
    assert parse_premises("") == []
    assert parse_premises(None) == []  # type: ignore[arg-type]


def test_falsifiable_non_true_returns_false():
    """(c) falsifiable 非真 -> False。"""
    for non_true in ["false", "no", "0", "maybe", "unknown", ""]:
        findings = (
            "<<<PREMISES>>>\n"
            "premise: Some premise\n"
            "flip_condition: Some flip\n"
            f"falsifiable: {non_true}\n"
            "<<<END>>>"
        )
        records = parse_premises(findings)
        assert len(records) == 1
        assert records[0].falsifiable is False


def test_thirteen_blocks_clamped_to_twelve():
    """(d) 13 块 -> len==12。"""
    blocks = []
    for i in range(13):
        blocks.append(
            f"<<<PREMISES>>>\npremise: Premise {i}\nflip_condition: Flip {i}\nfalsifiable: true\n<<<END>>>"
        )
    findings = "\n".join(blocks)
    records = parse_premises(findings)
    assert len(records) == MAX_PREMISES_PER_VERDICT
    assert len(records) == 12


def test_premise_length_2049_overrides_falsifiable_to_false():
    """(e) premise 长度 2049 且末字段 falsifiable 为 true -> r[0].falsifiable is False 且 len==2049。"""
    long_premise = "a" * 2049
    findings = (
        "<<<PREMISES>>>\n"
        f"premise: {long_premise}\n"
        "flip_condition: Normal flip\n"
        "falsifiable: true\n"
        "<<<END>>>"
    )
    records = parse_premises(findings)
    assert len(records) == 1
    assert len(records[0].premise) == 2049
    assert records[0].falsifiable is False  # 覆写优先级严格高于 token 真值判定


def test_flip_condition_length_2049_overrides_falsifiable_to_false():
    """(f) flip_condition 长度 2049 且 falsifiable 为 true -> r[0].falsifiable is False。"""
    long_flip = "b" * 2049
    findings = (
        "<<<PREMISES>>>\n"
        "premise: Normal premise\n"
        f"flip_condition: {long_flip}\n"
        "falsifiable: true\n"
        "<<<END>>>"
    )
    records = parse_premises(findings)
    assert len(records) == 1
    assert len(records[0].flip_condition) == 2049
    assert records[0].falsifiable is False


def test_premise_length_2048_retains_falsifiable_true_cliff_double_anchor():
    """(g) premise 长度 2048 且 falsifiable 为 true -> r[0].falsifiable is True（悬崖双锚 2048 vs 2049）。"""
    premise_2048 = "a" * MAX_PREMISE_FIELD_CHARS
    findings = (
        "<<<PREMISES>>>\n"
        f"premise: {premise_2048}\n"
        "flip_condition: Normal flip\n"
        "falsifiable: true\n"
        "<<<END>>>"
    )
    records = parse_premises(findings)
    assert len(records) == 1
    assert len(records[0].premise) == 2048
    assert records[0].falsifiable is True


def test_premise_with_extra_colons_partition_preserves_full_value():
    """(h) premise 值含额外冒号 -> partition 首冒号分割保留全值。"""
    findings = (
        "<<<PREMISES>>>\n"
        "premise: path:to:file.py:10-50:section:extra\n"
        "flip_condition: test::subtest::failure:reason\n"
        "falsifiable: 1\n"
        "<<<END>>>"
    )
    records = parse_premises(findings)
    assert len(records) == 1
    assert records[0].premise == "path:to:file.py:10-50:section:extra"
    assert records[0].flip_condition == "test::subtest::failure:reason"
    assert records[0].falsifiable is True


def test_lines_without_colon_are_skipped():
    """(i) 无冒号行跳过。"""
    findings = (
        "<<<PREMISES>>>\n"
        "This is a line without any colon\n"
        "Another random text line\n"
        "premise: Valid premise\n"
        "Yet another free line\n"
        "flip_condition: Valid flip\n"
        "falsifiable: yes\n"
        "<<<END>>>"
    )
    records = parse_premises(findings)
    assert len(records) == 1
    assert records[0].premise == "Valid premise"
    assert records[0].flip_condition == "Valid flip"
    assert records[0].falsifiable is True


def test_assert_premises_wellformed_contract():
    """(j) 手工构造 PremiseRecord 列表：空列表 [] 通过；含空 premise 抛 AssertionError；13 条抛 AssertionError；字段长度 2049 抛 AssertionError。"""
    # 1. 空列表通过 (P2' assert 空列表契约)
    assert_premises_wellformed([])

    # 2. 合法构造列表通过
    valid_records = [
        PremiseRecord(premise="p1", flip_condition="f1", falsifiable=True),
        PremiseRecord(premise="p2", flip_condition="f2", falsifiable=False),
    ]
    assert_premises_wellformed(valid_records)

    # 3. 含空 premise 抛 AssertionError
    with pytest.raises(AssertionError, match="Premise at index 0 is empty"):
        assert_premises_wellformed([PremiseRecord(premise="", flip_condition="f", falsifiable=True)])

    # 4. 含空 flip_condition 抛 AssertionError
    with pytest.raises(AssertionError, match="Flip condition at index 0 is empty"):
        assert_premises_wellformed([PremiseRecord(premise="p", flip_condition="", falsifiable=True)])

    # 5. 13 条抛 AssertionError
    thirteen = [PremiseRecord(premise=f"p{i}", flip_condition=f"f{i}", falsifiable=True) for i in range(13)]
    with pytest.raises(AssertionError, match="Too many premises: 13 > 12"):
        assert_premises_wellformed(thirteen)

    # 6. premise 字段长度 2049 抛 AssertionError
    long_p = [PremiseRecord(premise="x" * 2049, flip_condition="f", falsifiable=False)]
    with pytest.raises(AssertionError, match="exceeds max length"):
        assert_premises_wellformed(long_p)

    # 7. flip_condition 字段长度 2049 抛 AssertionError
    long_f = [PremiseRecord(premise="p", flip_condition="y" * 2049, falsifiable=False)]
    with pytest.raises(AssertionError, match="exceeds max length"):
        assert_premises_wellformed(long_f)


def test_premises_pattern_has_no_textual_corruption():
    """(k) test_premises_pattern_has_no_textual_corruption 断言反斜杠空白元字符、无 '/s'、无双重转义，合法块匹配成功。"""
    pattern_str = PREMISES_PATTERN.pattern
    # 断言包含反斜杠空白元字符 \s
    assert "\\s" in repr(pattern_str) or r"\s" in pattern_str
    # 严禁出现传输脱落伪影 /s
    assert "/s" not in pattern_str
    # 严禁双重转义 \\s
    assert "\\\\s" not in pattern_str

    # 合法块匹配验证
    match = PREMISES_PATTERN.search("prefix <<<PREMISES>>>\npremise: p\nflip_condition: f\n<<<END>>> suffix")
    assert match is not None
    assert "premise: p" in match.group(1)


def test_falsifiable_case_and_whitespace_normalization():
    """(l) 大小写与首尾空白归一化：'TRUE' / '  true  ' / 'Yes' 均识别为真。"""
    for raw in ["TRUE", "  true  ", "Yes", " YES ", "1"]:
        findings = (
            "<<<PREMISES>>>\n"
            "premise: P\n"
            "flip_condition: F\n"
            f"falsifiable: {raw}\n"
            "<<<END>>>"
        )
        records = parse_premises(findings)
        assert len(records) == 1
        assert records[0].falsifiable is True, f"Failed for token {raw!r}"

