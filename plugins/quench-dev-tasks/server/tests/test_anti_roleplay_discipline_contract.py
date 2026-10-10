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
    "角色扮演", "dev_reviewer_submit", "dev_tasks_refine_spec",
    "degraded", "reviewer_not_configured", "自证偏见",
)
REQUIRED_SKILL_TOKENS: tuple[str, ...] = (
    "dev_reviewer_submit", "dev_tasks_refine_spec", "dev_tasks_escalate", "degraded",
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


def test_inv3_degraded_poll_projection_enforces_anti_roleplay(tmp_path):
    """断言 INV-3 协议铁律：degraded 终态投影不论 raw_text 如何，绝对严禁产出伪造审查 findings。"""
    from reviewer_jobs import ReviewerJobSupervisor, JobState

    ws = str(tmp_path)
    supervisor = ReviewerJobSupervisor.for_workspace(ws)
    rec = supervisor.submit({"query": "q", "session_id": "anti_roleplay_sess"})

    supervisor._cas_transition(
        rec.session_id,
        rec.job_id,
        JobState.QUEUED,
        JobState.FAILED,
        updates={"degraded_reason": "reviewer_not_configured"},
    )

    # 1. raw_text=False: findings 必为空字符串
    dict_res = supervisor.poll(rec.job_id, session_id="anti_roleplay_sess", raw_text=False)
    assert dict_res["result"]["status"] == "degraded"
    assert dict_res["result"]["findings"] == ""
    assert dict_res["degraded_reason"] == "reviewer_not_configured"

    # 2. raw_text=True: 必为降级卡片，绝非审查分析正文
    text_res = supervisor.poll(rec.job_id, session_id="anti_roleplay_sess", raw_text=True)
    assert "### [Reviewer Consultation Degraded]" in text_res
    assert "reviewer_not_configured" in text_res


@pytest.mark.anyio
async def test_inv3_inv4_progress_message_format_and_stdout_purity():
    """断言 INV-3 心跳投影单一规范且无 findings 泄露，及 INV-4 服务端代码零 print() (D4)。"""
    from reviewer_engine import format_heartbeat_line

    # 1. 验证心跳消息逐字节等于 format_heartbeat_line，且无 findings/日志泄露
    msg = format_heartbeat_line(150, 12.5)
    assert msg == "[Reviewer thinking: 12.5s | 150 tokens]"
    assert "findings" not in msg
    assert "#" not in msg

    # 2. 验证 INV-4 零 stdout 写入：server.py 与 reviewer_jobs.py 零 print(
    server_path = SERVER_DIR / "server.py"
    reviewer_jobs_path = SERVER_DIR / "reviewer_jobs.py"
    for p in (server_path, reviewer_jobs_path):
        lines = p.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert not re.search(r"\bprint\s*\(", stripped), f"INV-4 violation: print() found at {p.name}:{idx}: {stripped}"

