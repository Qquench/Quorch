"""Tests for documentation and prompt contract hygiene (v1.25 dual-mode and autopilot contracts).

Physical text/regex assertions ensuring that governance contracts, envelope routing,
subagent status call bans, C3 delivery card triggers, and deprecation notices remain synchronized.
"""

from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _read_doc(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    assert path.is_file(), f"Expected document file does not exist: {path}"
    return path.read_text(encoding="utf-8")


def test_subagent_exempt_from_status_call():
    """Assert AGENTS.md and SKILL.md state Subagents are exempt from calling dev_tasks_status."""
    agents_md = _read_doc("AGENTS.md")
    skill_md = _read_doc("plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md")

    assert "Subagent" in agents_md or "subagent" in agents_md
    assert re.search(r"exempt from calling `dev_tasks_status`|子代理免调 status", agents_md), (
        "AGENTS.md must declare Subagents exempt from calling dev_tasks_status."
    )

    assert re.search(r"exempt from calling `dev_tasks_status`|子代理免调 status", skill_md), (
        "SKILL.md must declare Subagents exempt from calling dev_tasks_status."
    )


def test_c3_card_three_states_trigger():
    """Assert AGENTS.md and dev-tasks-discipline.md restrict C3 card to 3 stopping states."""
    agents_md = _read_doc("AGENTS.md")
    discipline_md = _read_doc("plugins/quench-dev-tasks/rules/dev-tasks-discipline.md")

    for doc_name, content in [("AGENTS.md", agents_md), ("dev-tasks-discipline.md", discipline_md)]:
        assert "PAUSE_FOR_ACCEPTANCE" in content, f"{doc_name} must mention PAUSE_FOR_ACCEPTANCE"
        assert "BLOCKED" in content, f"{doc_name} must mention BLOCKED"
        assert "ROADMAP_DONE" in content, f"{doc_name} must mention ROADMAP_DONE"


def test_quench_dispatch_envelope_present():
    """Assert AGENTS.md, agent.md, and external-executor-onboarding.md declare QUENCH-DISPATCH envelopes."""
    agents_md = _read_doc("AGENTS.md")
    agent_md = _read_doc("plugins/quench-dev-tasks/agents/reviewer/agent.md")
    onboarding_md = _read_doc("docs/guides/external-executor-onboarding.md")

    for doc_name, content in [
        ("AGENTS.md", agents_md),
        ("agent.md", agent_md),
        ("external-executor-onboarding.md", onboarding_md),
    ]:
        assert "QUENCH-DISPATCH" in content, f"{doc_name} must declare [QUENCH-DISPATCH: ...] envelope"
        assert re.search(r"\[QUENCH-DISPATCH:\s*RUNNER", content), (
            f"{doc_name} must declare [QUENCH-DISPATCH: RUNNER ...]"
        )


def test_quench_role_marked_deprecated():
    """Assert SKILL.md and external-executor-onboarding.md mark QUENCH_ROLE as deprecated."""
    skill_md = _read_doc("plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md")
    onboarding_md = _read_doc("docs/guides/external-executor-onboarding.md")

    for doc_name, content in [
        ("SKILL.md", skill_md),
        ("external-executor-onboarding.md", onboarding_md),
    ]:
        assert "QUENCH_ROLE" in content, f"{doc_name} must mention QUENCH_ROLE"
        assert re.search(
            r"\[DEPRECATED\].*QUENCH_ROLE|QUENCH_ROLE.*(?:\[DEPRECATED\]|deprecated|Deprecated)",
            content,
            re.DOTALL,
        ), f"{doc_name} must mark QUENCH_ROLE as deprecated"


def test_host_neutral_verbs_in_prompts():
    """Assert prompt/doc sections regarding session_role_contract avoid host-specific tool names (INV-5)."""
    docs_to_check = [
        "AGENTS.md",
        "plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md",
        "plugins/quench-dev-tasks/agents/reviewer/agent.md",
        "docs/guides/external-executor-onboarding.md",
    ]
    host_specific_tools = [
        "run_command",
        "replace_file_content",
        "read_file_content",
        "ask_question",
        "browser_subagent",
        "multi_replace_file_content",
    ]

    for rel_path in docs_to_check:
        content = _read_doc(rel_path)
        for tool in host_specific_tools:
            pattern = rf"session_role_contract[^\n]*{tool}|abstract verbs[^\n]*{tool}|Verbs:[^\n]*{tool}"
            match = re.search(pattern, content, re.IGNORECASE)
            assert not match, (
                f"Found forbidden host-specific tool '{tool}' in role contract/verb section of {rel_path}"
            )
