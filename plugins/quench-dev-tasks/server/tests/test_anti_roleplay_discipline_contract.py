# -*- coding: utf-8 -*-
"""Contract tests for anti-roleplaying governance and review triage rules.

Locks in:
1. Anti-roleplaying clauses and hard red lines in dev-tasks-discipline.md;
2. Triage decision tree in dev-tasks-review/SKILL.md;
3. Zero tolerance for phrases that legitimize in-context roleplaying;
4. Baseline heading preservation across both governance documents;
5. Exact literal alignment between degraded cards and consultation implementation.
"""
from pathlib import Path
import re
import pytest

from consultation import ConsultResult

SERVER_DIR = Path(__file__).resolve().parent.parent
PLUGIN_DIR = SERVER_DIR.parent
RULES_PATH = PLUGIN_DIR / "rules" / "dev-tasks-discipline.md"
SKILL_PATH = PLUGIN_DIR / "skills" / "dev-tasks-review" / "SKILL.md"

REQUIRED_RULE_TOKENS: tuple[str, ...] = (
    "角色扮演", "dev_reviewer_consult", "dev_tasks_refine_spec",
    "degraded", "reviewer_not_configured", "自证偏见",
)
REQUIRED_SKILL_TOKENS: tuple[str, ...] = (
    "dev_reviewer_consult", "dev_tasks_refine_spec", "dev_tasks_escalate", "degraded",
)
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "由你扮演 Reviewer", "可以模拟 Reviewer", "自行扮演", "无需外部模型即可审查",
)

BASELINE_DISCIPLINE_HEADINGS: tuple[str, ...] = (
    "# Quench Dev-Tasks Resident Discipline (开发任务常驻执行纪律)",
    "## 1. State Machine Progression Discipline (状态机推进纪律)",
    "## 2. Implementation Scope Discipline (执行阶段纪律)",
    "## 3. Review & Planning Discipline (审查与规划纪律)",
    "## 4. Reviewer Handoff & Resume Discipline (架构审查交接与多会话复工纪律)",
    "### ① When to Halt (停机与上报触发条件)",
    "### ② Handoff Card Format (标准上报格式)",
    "### ③ Resume Verification (复工确认机制)",
    "## 5. Fast-Track & Anti-Abuse Discipline (快速通道与反滥用纪律)",
    "### ① Three-Tier Progressive Protection",
    "### ② Pre-Commit Guard (Git 提交物理防线配合)",
)

BASELINE_SKILL_HEADINGS: tuple[str, ...] = (
    "# Quench Architecture & Task Review Guide (架构与任务审查指南)",
    "## 1. Core Review Discipline (核心审查纪律)",
    "## 2. Graded Quality Auditing (质量弹性分级规范)",
    "## 3. Standard Task Proposal Format (任务交付标准模板)",
    "## 4. Escalation Handling (升级处理流程)",
)


def heading_outline(md_text: str) -> list[str]:
    """提取 Markdown 文档中的所有标题行，去除首尾空白并过滤代码块内注释。"""
    normalized = md_text.replace("\r\n", "\n")
    lines = normalized.splitlines()
    in_code_block = False
    headings: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if not in_code_block and stripped.startswith("#") and not stripped.startswith("# file:"):
            # 只提取标准 markdown 标题格式 (# 开头后跟空格或数字/字符)
            if re.match(r"^#{1,6}\s", stripped):
                headings.append(stripped)

    return headings


def test_rules_contain_anti_roleplay_clause():
    """断言 dev-tasks-discipline.md 包含全部防角色扮演与自证偏见治理核心条款。"""
    assert RULES_PATH.is_file(), f"Discipline rules file missing at {RULES_PATH}"
    content = RULES_PATH.read_text(encoding="utf-8").casefold()

    for token in REQUIRED_RULE_TOKENS:
        assert token.casefold() in content, f"Discipline file missing required token: '{token}'"


def test_skill_contains_triage_tree():
    """断言 dev-tasks-review/SKILL.md 包含全量分流决策树关键路由词。"""
    assert SKILL_PATH.is_file(), f"Skill file missing at {SKILL_PATH}"
    content = SKILL_PATH.read_text(encoding="utf-8").casefold()

    for token in REQUIRED_SKILL_TOKENS:
        assert token.casefold() in content, f"Skill file missing required token: '{token}'"


def test_no_roleplay_legitimizing_phrases():
    """负向断言：两份治理文档严禁包含任何允许或怂恿主模型就地扮演 Reviewer 的表述。"""
    rule_content = RULES_PATH.read_text(encoding="utf-8")
    skill_content = SKILL_PATH.read_text(encoding="utf-8")

    combined_text = f"{rule_content}\n{skill_content}".casefold()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase.casefold() not in combined_text, (
            f"Found forbidden roleplay-legitimizing phrase: '{phrase}'"
        )


def test_existing_headings_not_removed():
    """断言既有标题基线 100% 得到保留（只增不减原则，禁止破坏性重写）。"""
    rule_text = RULES_PATH.read_text(encoding="utf-8")
    skill_text = SKILL_PATH.read_text(encoding="utf-8")

    rule_headings = heading_outline(rule_text)
    skill_headings = heading_outline(skill_text)

    # 1. 纪律文档基线超集断言
    for h in BASELINE_DISCIPLINE_HEADINGS:
        assert h in rule_headings, f"Baseline heading missing from discipline: '{h}'"

    # 2. 技能文档基线超集断言
    for h in BASELINE_SKILL_HEADINGS:
        assert h in skill_headings, f"Baseline heading missing from skill: '{h}'"

    # 3. 新增章节必须存在
    assert any("6. 防自证偏见" in h for h in rule_headings), "Missing Section 6 in discipline rules"
    assert any("5. Review Channel Triage" in h for h in skill_headings), "Missing Section 5 in review skill"


def test_degraded_card_literal_matches_implementation():
    """断言文档中出现的 degraded 状态字面量与 consultation 核心模块的定义严格一致。"""
    rule_text = RULES_PATH.read_text(encoding="utf-8")
    skill_text = SKILL_PATH.read_text(encoding="utf-8")

    expected_literal = "reviewer_not_configured"
    assert expected_literal in rule_text, f"Missing '{expected_literal}' in discipline doc"
    assert expected_literal in skill_text, f"Missing '{expected_literal}' in skill doc"

    # 确保与 ConsultResult 契约中的 degraded_reason 严格对应
    sample_result = ConsultResult(
        status="degraded",
        session_id="test_sess",
        mode="critique",
        findings="",
        log_path="",
        usage={},
        truncated=False,
        skipped_files=[],
        degraded_reason=expected_literal,
    )
    assert sample_result.degraded_reason == expected_literal
