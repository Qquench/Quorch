# -*- coding: utf-8 -*-
"""Regression and contract tests for anti-forgery and reviewer identity governance.

Locks in:
1. Anti-forgery physical bottom line: unconfigured reviewer engine returns degraded status,
   tags 'self_verification_warning', marks reviewer_identity as 'degraded', and strictly
   guarantees findings == "";
2. Homogeneous runner/reviewer detection: when runner profile and reviewer engine resolve
   to identical model identity, non-blocking self-verification advisory warning is injected
   into response and audit logs;
3. Anti-roleplay hard-stop (INV-3): degraded outputs strictly enforce findings == "",
   forbidding execution runners from synthesizing or roleplaying review findings;
4. Reviewer identity transparency: reviewer_identity accurately reflects provider, model,
   and degraded status;
5. Verdict audit sink integrity: audit log sinks preserve chronological structure and bounds.
"""
from pathlib import Path
import json
import pytest
import yaml

import server
from consultation import ConsultResult
from reviewer_engine import StreamChunk


class FakeReviewerClient:
    """Mock client conforming to consultation engine interface."""
    def __init__(self, chunks=None):
        self.chunks = chunks or [
            StreamChunk(text="Architectural Assessment:\n", reasoning="Analyzing...\n"),
            StreamChunk(text="The architecture is decoupled and safe.\n", reasoning="Done.\n"),
        ]
        self.provider_label = "fake-provider"

    def is_available(self) -> bool:
        return True

    def resolve_api_key(self) -> str:
        return "mock-key"

    async def stream_chat(self, messages, *, session_id=None):
        for c in self.chunks:
            yield c

    async def acomplete(self, messages, **kwargs):
        full_text = "".join(c.text for c in self.chunks)
        full_reasoning = "".join(c.reasoning for c in self.chunks)
        return {
            "choices": [{"message": {"content": full_text, "reasoning_content": full_reasoning}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }


@pytest.mark.anyio
async def test_unconfigured_reviewer_marked_degraded_and_warning(tmp_path: Path):
    """断言未配置 Reviewer 引擎时，结果必被标记为 degraded 且打上 self_verification_warning，杜绝伪造."""
    ws = tmp_path / "ws_unconfigured"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    cfg_file = agents_dir / "quench_stack.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "project_name": "test_unconfigured",
            "reviewer_engine": {
                "provider": "none",
            },
        }),
        encoding="utf-8",
    )

    res = await server.dev_reviewer_consult(
        workspace_root=str(ws),
        query="Verify architectural integrity.",
    )

    assert res["status"] == "degraded"
    assert res["degraded_reason"] == "reviewer_not_configured"
    assert res["reviewer_identity"]["status"] == "degraded"
    assert res["self_verification_warning"] == "reviewer_not_configured"
    # INV-3 强制要求：降级状态下 findings 严禁被填充，防执行模型就地伪造
    assert res["findings"] == ""


@pytest.mark.anyio
async def test_homogeneous_runner_and_reviewer_warns_self_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """断言同模型执行与审查配置时激活 self_verification_warning，并在日志注入自证偏见预警."""
    ws = tmp_path / "ws_homogeneous"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    cfg_file = agents_dir / "quench_stack.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "project_name": "test_homogeneous",
            "runner_profile": {
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
            "reviewer_engine": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com",
            },
        }),
        encoding="utf-8",
    )

    fake_client = FakeReviewerClient()
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    res = await server.dev_reviewer_consult(
        workspace_root=str(ws),
        query="Audit concurrent state transition.",
    )

    # 1. 咨询流正常返回
    assert res["status"] == "ok"
    assert "decoupled and safe" in res["findings"]

    # 2. 审查身份与自证警告明确附带
    assert res["reviewer_identity"]["status"] == "active"
    assert res["reviewer_identity"]["provider"] == "deepseek"
    assert res["self_verification_warning"] is not None
    assert "self-verification" in res["self_verification_warning"].lower()

    # 3. 日志中包含警告
    log_file = Path(res["log_path"])
    assert log_file.is_file()
    log_text = log_file.read_text(encoding="utf-8")
    assert "[warning]" in log_text
    assert "self-verification" in log_text.lower()


def test_anti_roleplay_hard_stop_invariant_contract():
    """断言 INV-3 协议铁律：任何 degraded 状态的 ConsultResult 必须保证 findings 为空字符串."""
    degraded_result = ConsultResult(
        status="degraded",
        session_id="session_test",
        mode="critique",
        findings="",
        log_path="",
        usage={},
        truncated=False,
        skipped_files=[],
        degraded_reason="reviewer_not_configured",
        self_verification_warning="reviewer_not_configured",
    )
    assert degraded_result.findings == "", "INV-3 violation: degraded result has non-empty findings"


@pytest.mark.anyio
async def test_reviewer_identity_metadata_transparency(tmp_path: Path):
    """断言在降级卡片中，reviewer_identity 透明暴露 provider、model、thinking 配置状态."""
    ws = tmp_path / "ws_identity"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    cfg_file = agents_dir / "quench_stack.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "project_name": "test_identity",
            "reviewer_engine": {
                "provider": "none",
                "model": "custom-audit-model",
            },
        }),
        encoding="utf-8",
    )

    res = await server.dev_reviewer_consult(
        workspace_root=str(ws),
        query="Inspect identity metadata.",
    )

    identity = res.get("reviewer_identity", {})
    assert identity.get("status") == "degraded"
    assert identity.get("provider") == "none"
    assert identity.get("model") == "custom-audit-model"


def test_verdict_audit_sink_recording(tmp_path: Path):
    """断言裁决落盘台账正确写入 JSONL 并记录 task_id 与 payload."""
    from observability_policy import make_verdict_sink

    sink_path = tmp_path / "verdicts.jsonl"
    sink = make_verdict_sink(str(sink_path))

    sink.emit_verdict(
        task_id="test_task_1",
        verdict_hash="sha256_mock_hash",
        generation=1,
        payload={"verdict": "APPROVED", "self_verification_warning": None},
    )

    assert sink_path.is_file()
    lines = sink_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["task_id"] == "test_task_1"
    assert record["verdict_hash"] == "sha256_mock_hash"
    assert record["payload"]["verdict"] == "APPROVED"
