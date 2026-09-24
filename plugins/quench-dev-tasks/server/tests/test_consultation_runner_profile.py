import asyncio
import os
from pathlib import Path
import sys
from typing import Any, List, Optional
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consultation import ConsultRequest, ConsultResult, run_consultation
from project_config import (
    QuenchStackConfig,
    ReviewerEngineConfig,
    RunnerProfile,
    check_self_verification_warning,
    load_project_config,
    normalize_model_identity,
)
from reviewer_engine import StreamChunk
import server


class FakeReviewerClient:
    """Mock Reviewer client for testing runner profile behavior."""

    def __init__(
        self,
        chunks: Optional[List[StreamChunk]] = None,
        *,
        is_avail: bool = True,
        raise_err: Optional[Exception] = None,
    ):
        self.chunks = chunks or [
            StreamChunk(text="Architectural Assessment:\n", reasoning="Analyzing...\n"),
            StreamChunk(text="The architecture is decoupled and safe.\n", reasoning="Done.\n"),
        ]
        self._is_avail = is_avail
        self.raise_err = raise_err
        self.provider_label = "fake-provider"

    def is_available(self) -> bool:
        return self._is_avail

    def resolve_api_key(self) -> str:
        return "mock-key"

    async def stream_chat(self, messages: Any, *, session_id: Optional[str] = None):
        if self.raise_err:
            raise self.raise_err
        for c in self.chunks:
            yield c

    async def acomplete(self, messages: Any, **kwargs):
        if self.raise_err:
            raise self.raise_err
        full_text = "".join(c.text for c in self.chunks)
        full_reasoning = "".join(c.reasoning for c in self.chunks)
        return {
            "choices": [{"message": {"content": full_text, "reasoning_content": full_reasoning}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }


def test_runner_profile_dataclass_defaults():
    """断言 RunnerProfile 默认值为 unknown。"""
    rp = RunnerProfile()
    assert rp.provider == "unknown"
    assert rp.model == "unknown"


def test_runner_profile_parsing_from_yaml(tmp_path: Path):
    """断言 quench_stack.yaml 中配置的 runner_profile 正常反序列化，未配置时安全降级。"""
    ws = tmp_path / "ws_rp"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()

    # 1. 显式配置 runner_profile
    cfg_file = agents_dir / "quench_stack.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "project_name": "rp_test",
            "runner_profile": {
                "provider": "openai",
                "model": "gpt-4o",
            },
        }),
        encoding="utf-8",
    )
    loaded = load_project_config(str(ws))
    assert loaded.runner_profile.provider == "openai"
    assert loaded.runner_profile.model == "gpt-4o"

    # 2. 未配置 runner_profile 时平滑降级为 unknown
    cfg_file.write_text(
        yaml.safe_dump({
            "project_name": "rp_default",
        }),
        encoding="utf-8",
    )
    loaded_default = load_project_config(str(ws))
    assert loaded_default.runner_profile.provider == "unknown"
    assert loaded_default.runner_profile.model == "unknown"

    # 3. 畸形配置 (非 dict) 平滑降级为 unknown
    cfg_file.write_text(
        yaml.safe_dump({
            "project_name": "rp_malformed",
            "runner_profile": "invalid_string",
        }),
        encoding="utf-8",
    )
    loaded_malformed = load_project_config(str(ws))
    assert loaded_malformed.runner_profile.provider == "unknown"
    assert loaded_malformed.runner_profile.model == "unknown"


def test_normalize_model_identity_and_aliases():
    """断言模型别名映射与默认模型归一化。"""
    # 别名映射
    assert normalize_model_identity("deepseek", "deepseek") == ("deepseek", "deepseek-chat")
    assert normalize_model_identity("deepseek", "deepseek-v3") == ("deepseek", "deepseek-chat")
    assert normalize_model_identity("deepseek", "deepseek-r1") == ("deepseek", "deepseek-reasoner")
    assert normalize_model_identity("deepseek-compatible", "default") == ("deepseek", "deepseek-chat")
    assert normalize_model_identity("openai", "gpt-4") == ("openai", "gpt-4o")
    assert normalize_model_identity("openai", "default") == ("openai", "gpt-4o")

    # 未知厂商与自定义模型保持原样
    assert normalize_model_identity("custom", "my-model-1") == ("custom", "my-model-1")


def test_check_self_verification_warning_logic():
    """断言同模型核对逻辑：同模型告警，不同模型放行，unknown/none 放行。"""
    # 1. 相同模型（显式相同）
    runner = RunnerProfile(provider="deepseek", model="deepseek-chat")
    warn = check_self_verification_warning(runner, "deepseek", "deepseek-chat")
    assert warn is not None
    assert "homogeneous bias" in warn or "self-verification" in warn

    # 2. 相同模型（通过别名与默认归一相同）
    runner_alias = RunnerProfile(provider="deepseek-compatible", model="deepseek")
    warn_alias = check_self_verification_warning(runner_alias, "deepseek", "default")
    assert warn_alias is not None

    # 3. 不同模型（放行）
    runner_diff = RunnerProfile(provider="openai", model="gpt-4o")
    warn_diff = check_self_verification_warning(runner_diff, "deepseek", "deepseek-chat")
    assert warn_diff is None

    # 4. Runner 未配置 (unknown) -> 放行
    runner_unk = RunnerProfile(provider="unknown", model="unknown")
    assert check_self_verification_warning(runner_unk, "deepseek", "deepseek-chat") is None

    # 5. Reviewer 为 none -> 放行
    assert check_self_verification_warning(runner, "none", "default") is None

    # 6. Runner 为 None -> 放行
    assert check_self_verification_warning(None, "deepseek", "deepseek-chat") is None


@pytest.mark.anyio
async def test_consultation_degraded_when_provider_none(tmp_path: Path):
    """断言 provider='none' 时 reviewer_identity.status 标为 'degraded'，self_verification_warning 提示 'reviewer_not_configured'。"""
    ws = tmp_path / "ws_none"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    cfg_file = agents_dir / "quench_stack.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "project_name": "test_none",
            "reviewer_engine": {
                "provider": "none",
            },
        }),
        encoding="utf-8",
    )

    res = await server.dev_reviewer_consult(
        workspace_root=str(ws),
        query="Are there concurrency issues?",
    )

    assert res["status"] == "degraded"
    assert res["degraded_reason"] == "reviewer_not_configured"
    assert res["findings"] == ""
    assert res["reviewer_identity"] == {
        "provider": "none",
        "model": "default",
        "thinking": True,
        "status": "degraded",
    }
    assert res["self_verification_warning"] == "reviewer_not_configured"


@pytest.mark.anyio
async def test_consultation_same_model_soft_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """断言同模型配置时激活自我验证软预警，且咨询流非阻塞正常返回。"""
    ws = tmp_path / "ws_same"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    cfg_file = agents_dir / "quench_stack.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "project_name": "test_same",
            "runner_profile": {
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
            "reviewer_engine": {
                "provider": "deepseek",
                "model": "default",
                "base_url": "https://api.deepseek.com",
            },
        }),
        encoding="utf-8",
    )

    fake_client = FakeReviewerClient()
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    res = await server.dev_reviewer_consult(
        workspace_root=str(ws),
        query="Evaluate decoupling architecture.",
    )

    # 1. 咨询流非阻塞正常执行
    assert res["status"] == "ok"
    assert "decoupled and safe" in res["findings"]

    # 2. 审查身份与状态透明暴露
    assert res["reviewer_identity"]["status"] == "active"
    assert res["reviewer_identity"]["provider"] == "deepseek"
    assert res["reviewer_identity"]["model"] == "default"

    # 3. 激活非阻塞预警字段
    assert res["self_verification_warning"] is not None
    assert "self-verification" in res["self_verification_warning"]

    # 4. 确认预警已注入日志文件
    log_path = Path(res["log_path"])
    assert log_path.is_file()
    log_content = log_path.read_text(encoding="utf-8")
    assert "[warning]" in log_content
    assert "self-verification" in log_content


@pytest.mark.anyio
async def test_consultation_distinct_model_no_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """断言异构双模型配置时不触发自我验证预警。"""
    ws = tmp_path / "ws_diff"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    cfg_file = agents_dir / "quench_stack.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "project_name": "test_diff",
            "runner_profile": {
                "provider": "openai",
                "model": "gpt-4o",
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
        query="Evaluate decoupling architecture.",
    )

    assert res["status"] == "ok"
    assert res["reviewer_identity"]["status"] == "active"
    assert res["self_verification_warning"] is None


@pytest.mark.anyio
async def test_consultation_default_runner_profile_no_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """断言未配置 runner_profile 时平滑放行，不产生假阳性告警。"""
    ws = tmp_path / "ws_no_rp"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    cfg_file = agents_dir / "quench_stack.yaml"
    cfg_file.write_text(
        yaml.safe_dump({
            "project_name": "test_no_rp",
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
        query="Evaluate decoupling architecture.",
    )

    assert res["status"] == "ok"
    assert res["reviewer_identity"]["status"] == "active"
    assert res["self_verification_warning"] is None
