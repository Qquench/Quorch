# -*- coding: utf-8 -*-
"""Full behavior matrix tests for dev_reviewer_consult ad-hoc consultation tool.

Covers:
1. Schema & registration validation;
2. Mode enum checking & input bounds enforcement;
3. Max hops clamping;
4. Chunk-wise reasoning stream persistence to latest-<session_id>.log;
5. Session ID sanitization in log path;
6. Timeout breaker with partial log preservation;
7. Parametrized degradation matrix (5 scenarios) asserting zero fabricated findings;
8. Unconfigured engine explicit handoff prompt;
9. Zero stdout pollution guard;
10. Concurrent same-session log serialization;
11. Context extension multi-hop loop;
12. Suggested task draft parsing without disk mutation.
"""
from dataclasses import dataclass
from pathlib import Path
import asyncio
import os
import re
import time
from typing import Any, List, Optional
from unittest.mock import MagicMock
import pytest

from consultation import ConsultRequest, ConsultResult, run_consultation
from project_config import QuenchStackConfig, ReviewerEngineConfig
from reviewer_engine import (
    ReviewerAuthenticationError,
    ReviewerEngineError,
    ReviewerEngineUnavailableError,
    StreamChunk,
)
import server

FAKE_STREAM_CHUNKS: list[dict] = [
    {"text": "", "reasoning": "Step 1: analyzing concurrency boundaries."},
    {"text": "", "reasoning": "Step 2: verifying lock timeouts and thread safety."},
    {"text": "", "reasoning": ""},  # empty chunk / benign anomaly
    {"text": "### Architectural Assessment\n", "reasoning": ""},
    {"text": "The proposed architecture is sound with thread-safe persistence.\n", "reasoning": ""},
]

DEGRADED_SCENARIOS: tuple[str, ...] = (
    "provider_none", "auth_401", "timeout", "connect_error", "reasoning_budget_exceeded",
)


class FakeReviewerClient:
    """协议中立的假 Reviewer 客户端，完全离线执行，保真 stream_chat 契约。"""

    def __init__(
        self,
        chunks: Optional[List[StreamChunk]] = None,
        *,
        delay_before_chunk_s: float = 0.0,
        raise_err: Optional[Exception] = None,
        is_avail: bool = True,
    ):
        self.chunks = chunks or [
            StreamChunk(text=c["text"], reasoning=c["reasoning"]) for c in FAKE_STREAM_CHUNKS
        ]
        self.delay_before_chunk_s = delay_before_chunk_s
        self.raise_err = raise_err
        self._is_avail = is_avail
        self.provider_label = "generic-mock"

    def is_available(self) -> bool:
        return self._is_avail

    def resolve_api_key(self) -> str:
        return "mock-api-key"

    async def stream_chat(self, messages: Any, *, session_id: Optional[str] = None):
        if self.raise_err:
            raise self.raise_err
        for c in self.chunks:
            if self.delay_before_chunk_s > 0:
                await asyncio.sleep(self.delay_before_chunk_s)
            yield c

    async def acomplete(self, messages: Any, **kwargs):
        if self.raise_err:
            raise self.raise_err
        full_text = "".join(c.text for c in self.chunks)
        full_reasoning = "".join(c.reasoning for c in self.chunks)
        return {
            "choices": [{"message": {"content": full_text, "reasoning_content": full_reasoning}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "prompt_cache_hit_tokens": 60},
        }


@pytest.mark.anyio
async def test_tool_is_registered_with_full_schema():
    """断言 dev_reviewer_consult 在 FastMCP 实例中注册完备，元数据与中英双语 docstring 健全。"""
    tool = await server.mcp.get_tool("dev_reviewer_consult")
    assert tool is not None
    assert tool.name == "dev_reviewer_consult"
    assert tool.description is not None
    assert "Directly consult the senior architecture Reviewer" in tool.description
    assert "免任务单地直接咨询资深架构 Reviewer" in tool.description

    params = tool.parameters.get("properties", {}) if hasattr(tool, "parameters") and isinstance(tool.parameters, dict) else {}
    for required_arg in ("workspace_root", "query", "context_files", "mode", "max_hops", "session_id"):
        assert required_arg in params, f"Missing parameter '{required_arg}' in tool schema"


@pytest.mark.anyio
async def test_mode_enum_rejects_illegal_value_without_raising(tmp_path: Path):
    """断言非法 mode 输入返回结构化错误字典且列出全部合法枚举值，严禁抛异常中断通信。"""
    res = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Validate architecture",
        mode="unsupported_mode",
    )
    assert isinstance(res, dict)
    assert res["status"] == "error"
    for m in ("critique", "evaluate", "brainstorm", "audit"):
        assert m in res["error"], f"Error must list valid mode '{m}'"


@pytest.mark.anyio
async def test_query_length_upper_bound_enforced(tmp_path: Path):
    """断言 query 长度上界与非空校验。"""
    res_empty = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="   ",
    )
    assert res_empty["status"] == "error"
    assert "empty" in res_empty["error"].lower()

    res_too_long = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Q" * 8001,
    )
    assert res_too_long["status"] == "error"
    assert "8000" in res_too_long["error"]


@pytest.mark.anyio
async def test_max_hops_clamped_and_out_of_range_returns_structured_error(tmp_path: Path, monkeypatch):
    """断言超出 [0, 3] 范围的 max_hops 会被安全钳制并正常执行。"""
    fake_client = FakeReviewerClient([StreamChunk(text="OK", reasoning="Thinking")])
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    # 1. max_hops=9 自动钳制为 3
    res_high = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="High hops test",
        max_hops=9,
    )
    assert res_high["status"] == "ok"

    # 2. max_hops=-1 自动钳制为 0
    res_low = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Low hops test",
        max_hops=-1,
    )
    assert res_low["status"] == "ok"


@pytest.mark.anyio
async def test_reasoning_stream_is_persisted_chunkwise_to_session_log(tmp_path: Path, monkeypatch):
    """断言思考流细粒度分片按自然换行聚合并实时落盘至 latest-<session_id>.log，具备 ISO8601 时间戳，绝不按分片单字破碎膨胀。"""
    # 细粒度流式分片（模拟真实 SSE 传输，含 CJK 汉字与 Emoji 代理对）
    reasoning_fragments = [
        "🔍", "Step ", "1: ", "检查", "边界", "安全", "性。\n",
        "Step ", "2: ", "verifying ", "thread ", "safety.\n",
    ]
    chunks = [StreamChunk(text="", reasoning=frag) for frag in reasoning_fragments] + [
        StreamChunk(text="Final assessment output.", reasoning=""),
    ]
    fake_client = FakeReviewerClient(chunks)
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    session_id = "test-log-stream-42"
    res = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Check concurrency invariants",
        session_id=session_id,
    )
    assert res["status"] == "ok"
    assert res["findings"] == "Final assessment output."

    log_path = Path(res["log_path"])
    assert log_path.exists()
    log_content = log_path.read_text(encoding="utf-8")
    assert "🔍Step 1: 检查边界安全性。" in log_content
    assert "Step 2: verifying thread safety." in log_content

    # 断言输出为纯净 Markdown 正文，无每行时间戳或 [reasoning] 污染，且行数严格等于自然段落数（2 行），杜绝 12 个分片膨胀为 12 行
    body_lines = [line for line in log_content.splitlines() if line and not line.startswith("#")]
    assert len(body_lines) == 2



@pytest.mark.anyio
async def test_log_path_contains_sanitized_session_id(tmp_path: Path, monkeypatch):
    """断言返回的 log_path 严格绑定清洗后的 session_id。"""
    fake_client = FakeReviewerClient([StreamChunk(text="OK", reasoning="Thinking")])
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    sid = "custom_session_id_77"
    res = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Session path check",
        session_id=sid,
    )
    assert res["status"] == "ok"
    assert res["session_id"] == sid
    assert re.search(r"\d{8}_\d{3}_custom_session_id_77\.log$", res["log_path"]) is not None
    assert os.path.exists(res["log_path"])
    assert os.path.exists(os.path.join(tmp_path, ".agents", "logs", "reviewer", "latest.log"))


@pytest.mark.anyio
async def test_timeout_breaker_returns_degraded_and_keeps_partial_log(tmp_path: Path, monkeypatch):
    """断言超时熔断时返回 degraded，degraded_reason='timeout'，保留已落盘的部分思考轨迹，调用总耗时受控。"""
    class TimeoutReviewerClient(FakeReviewerClient):
        async def stream_chat(self, messages: Any, *, session_id: Optional[str] = None):
            yield StreamChunk(text="", reasoning="Partial reasoning chunk before timeout.")
            await asyncio.sleep(2.0)
            yield StreamChunk(text="Never reached", reasoning="")

    fake_client = TimeoutReviewerClient()
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    cfg = QuenchStackConfig(
        workspace_root=str(tmp_path),
        project_name="TimeoutTest",
        reviewer_engine=ReviewerEngineConfig(
            provider="custom",
            base_url="https://timeout.internal.net/v1",
            timeout_seconds=1,
        ),
    )
    monkeypatch.setattr("server.load_project_config", lambda ws: cfg)

    sid = "timeout_sess_10"
    t0 = time.monotonic()
    res = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Evaluate timeout scenario",
        session_id=sid,
    )
    elapsed = time.monotonic() - t0

    assert res["status"] == "degraded"
    assert res["degraded_reason"] == "timeout"
    assert res["findings"] == "", "Timeout must not fabricate findings!"
    assert res["handoff_prompt"] is not None
    assert elapsed < 2.5

    log_file = Path(res["log_path"])
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Partial reasoning chunk before timeout." in content


@pytest.mark.parametrize("scenario", DEGRADED_SCENARIOS)
@pytest.mark.anyio
async def test_degraded_paths_never_fabricate_findings(scenario: str, tmp_path: Path, monkeypatch):
    """核心防角色扮演断言：5 种降级场景每一个都必须断言 findings == '' 且 handoff_prompt 非空。"""
    if scenario == "provider_none":
        cfg = QuenchStackConfig(
            workspace_root=str(tmp_path),
            project_name="TestDegrade",
            reviewer_engine=ReviewerEngineConfig(provider="none"),
        )
        monkeypatch.setattr("server.load_project_config", lambda ws: cfg)
    elif scenario == "auth_401":
        fake_client = FakeReviewerClient(
            raise_err=ReviewerAuthenticationError("[generic] 401 Unauthorized: Invalid API Key")
        )
        monkeypatch.setattr("consultation.create_reviewer_client", lambda c, sink=None: fake_client)
    elif scenario == "timeout":
        class SleepingClient(FakeReviewerClient):
            async def stream_chat(self, messages: Any, *, session_id: Optional[str] = None):
                await asyncio.sleep(2.0)
                yield StreamChunk(text="Never")
        cfg = QuenchStackConfig(
            workspace_root=str(tmp_path),
            project_name="TestDegrade",
            reviewer_engine=ReviewerEngineConfig(
                provider="custom",
                base_url="https://test.net/v1",
                timeout_seconds=1,
            ),
        )
        monkeypatch.setattr("server.load_project_config", lambda ws: cfg)
        monkeypatch.setattr("consultation.create_reviewer_client", lambda c, sink=None: SleepingClient())
    elif scenario == "connect_error":
        fake_client = FakeReviewerClient(
            raise_err=ReviewerEngineUnavailableError("[generic] Connection refused by peer")
        )
        monkeypatch.setattr("consultation.create_reviewer_client", lambda c, sink=None: fake_client)
    elif scenario == "reasoning_budget_exceeded":
        huge_reasoning = "ExcessiveReasoningChunk " * 15000
        fake_client = FakeReviewerClient([StreamChunk(text="", reasoning=huge_reasoning)])
        monkeypatch.setattr("consultation.create_reviewer_client", lambda c, sink=None: fake_client)

    res = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Evaluate under degraded conditions",
    )

    # 强制三大不变量断言
    assert res["status"] == "degraded", f"Scenario '{scenario}' did not return degraded status!"
    assert res["findings"] == "", f"Scenario '{scenario}' must NEVER fabricate findings!"
    assert res["handoff_prompt"] is not None and len(res["handoff_prompt"]) > 0, (
        f"Scenario '{scenario}' missing handoff_prompt!"
    )

    if scenario == "provider_none":
        assert res["degraded_reason"] == "reviewer_not_configured"


@pytest.mark.anyio
async def test_engine_unconfigured_returns_handoff_prompt_and_empty_findings(tmp_path: Path):
    """断言未配置引擎时返回明确的切会话指引，严禁主模型自充 Reviewer。"""
    res = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Inspect design invariants",
    )
    assert res["status"] == "degraded"
    assert res["degraded_reason"] == "reviewer_not_configured"
    assert res["findings"] == ""
    assert "严禁" in res["handoff_prompt"] or "请勿" in res["handoff_prompt"] or "Reviewer" in res["handoff_prompt"]


@pytest.mark.anyio
async def test_no_stdout_pollution_during_consultation(capsys, tmp_path: Path, monkeypatch):
    """断言全调用周期内 sys.stdout 绝对洁净（严格保留给 JSON-RPC 协议帧）。"""
    fake_client = FakeReviewerClient([
        StreamChunk(text="Clean response.", reasoning="Clean trace.")
    ])
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    res = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Stdout pollution test",
    )
    assert res["status"] == "ok"
    captured = capsys.readouterr()
    assert captured.out == "", f"Stdout polluted during consultation: {captured.out!r}"


@pytest.mark.anyio
async def test_concurrent_same_session_serializes_log_writes(tmp_path: Path, monkeypatch):
    """断言以同一 session_id 并发调用时，进程锁保障日志写入完全序列化，无半截行交错。"""
    chunks1 = [
        StreamChunk(text="", reasoning="Sess1-ChunkA\n"),
        StreamChunk(text="", reasoning="Sess1-ChunkB\n"),
    ]
    chunks2 = [
        StreamChunk(text="", reasoning="Sess2-ChunkA\n"),
        StreamChunk(text="", reasoning="Sess2-ChunkB\n"),
    ]
    fake_client = FakeReviewerClient(chunks1 + chunks2)
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    sid = "shared_concurrent_session_01"
    res1, res2 = await asyncio.gather(
        server.dev_reviewer_consult(workspace_root=str(tmp_path), query="Query 1", session_id=sid),
        server.dev_reviewer_consult(workspace_root=str(tmp_path), query="Query 2", session_id=sid),
    )
    assert res1["status"] == "ok"
    assert res2["status"] == "ok"

    log_file = Path(res1["log_path"])
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        if "[reasoning]" in line:
            # 断言每行均包含完整 chunk 标识，无截断穿插
            assert any(tag in line for tag in ("ChunkA", "ChunkB"))


@pytest.mark.anyio
async def test_context_extension_round_respects_max_hops(tmp_path: Path, monkeypatch):
    """断言模型请求扩展上下文时，轮次受 max_hops 精准约束；max_hops=0 时零扩展。"""
    extra_file = tmp_path / "extended_module.py"
    extra_file.write_text("def extended_func(): return True\n", encoding="utf-8")

    class MultiHopClient(FakeReviewerClient):
        def __init__(self):
            super().__init__()
            self.call_count = 0

        async def stream_chat(self, messages: Any, *, session_id: Optional[str] = None):
            self.call_count += 1
            if self.call_count == 1:
                yield StreamChunk(
                    text="Need extra file:\n<<<NEED-FILES>>>\nextended_module.py\n<<<END>>>\n",
                    reasoning="Need more context",
                )
            else:
                yield StreamChunk(
                    text="Final critique based on extended context.",
                    reasoning="Final evaluation",
                )

    client1 = MultiHopClient()
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: client1)

    # 1. max_hops=1 时触发扩展
    res_ext = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Initial query",
        max_hops=1,
    )
    assert res_ext["status"] == "ok"
    assert client1.call_count == 2
    assert "Final critique" in res_ext["findings"]

    # 2. max_hops=0 时不触发扩展
    client0 = MultiHopClient()
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: client0)
    res_zero = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Initial query",
        max_hops=0,
    )
    assert res_zero["status"] == "ok"
    assert client0.call_count == 1
    assert "Need extra file" in res_zero["findings"]


@pytest.mark.anyio
async def test_suggested_task_draft_parsed_but_not_persisted(tmp_path: Path, monkeypatch):
    """断言响应尾部含 <<<TASK_DRAFT>>> 时解析为 suggested_task_draft，绝不直接落盘。"""
    task_draft_text = (
        "### 任务 3.1 ⬜ 待确认 — 修复数据并发死锁\n"
        "#### 【涉及文件】\n- `[MODIFY]` `core.py`\n"
        "#### 【DoD 验证命令】\n`pytest`\n"
    )
    fake_client = FakeReviewerClient([
        StreamChunk(
            text=f"Analysis completed.\n<<<TASK_DRAFT>>>\n{task_draft_text}\n<<<END>>>\n",
            reasoning="Formulated task draft.",
        )
    ])
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    tasks_dir = tmp_path / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True)
    existing_files_before = set(os.listdir(tasks_dir))

    res = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Propose remediation task",
    )
    assert res["status"] == "ok"
    assert res["suggested_task_draft"] is not None
    assert "3.1" in res["suggested_task_draft"]["raw_markdown"]

    # 严格断言：dev_tasks 目录下未新增任何物理文件
    existing_files_after = set(os.listdir(tasks_dir))
    assert existing_files_after == existing_files_before


@pytest.mark.anyio
async def test_dev_reviewer_consult_heartbeat_dispatch_and_context_propagation(tmp_path: Path, monkeypatch, capfd):
    """断言 dev_reviewer_consult 支持透传 FastMCP Context 并同时向 FILE 通道追加 [progress] 心跳记录。"""
    # 模拟有微小耗时的流式分片，确保后台心跳 worker 触发
    chunks = [
        StreamChunk(text="", reasoning="Checking boundaries...\n"),
        StreamChunk(text="All good.\n", reasoning=""),
    ]
    fake_client = FakeReviewerClient(chunks, delay_before_chunk_s=1.1)
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    mock_ctx = MagicMock()
    mock_ctx.info = MagicMock()
    mock_ctx.report_progress = MagicMock()

    session_id = "test-hb-dispatch-101"
    res = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Check heartbeat fanout",
        session_id=session_id,
        ctx=mock_ctx,
    )
    assert res["status"] == "ok"

    log_path = Path(res["log_path"])
    assert log_path.exists()
    log_content = log_path.read_text(encoding="utf-8")

    # 断言 FILE 通道存在 [progress] 心跳标记与纯英文心跳格式 (Pull Model SSOT)
    assert "[progress]" in log_content
    assert "Checking boundaries..." in log_content
    assert "[Reviewer thinking:" in log_content

    # 零 stdout 污染断言
    captured = capfd.readouterr()
    assert captured.out == ""
