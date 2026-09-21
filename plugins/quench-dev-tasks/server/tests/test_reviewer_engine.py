# -*- coding: utf-8 -*-
import io
import json
import os
import shutil
import tempfile
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from project_config import QuenchStackConfig, ReviewerEngineConfig
from reviewer_engine import (
    DeepSeekClient,
    PromptAssembler,
    ReviewerAuthenticationError,
    ReviewerBadRequestError,
    ReviewerEngineError,
    ReviewerEngineUnavailableError,
)


@pytest.fixture
def mock_ws():
    temp_dir = tempfile.mkdtemp(prefix="quorch_reviewer_ws_")
    agents_dir = os.path.join(temp_dir, ".agents")
    docs_dir = os.path.join(temp_dir, "docs", "architecture")
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(docs_dir, exist_ok=True)

    arch_doc = os.path.join(docs_dir, "system_design.md")
    with open(arch_doc, "w", encoding="utf-8") as f:
        f.write("# MES Test Architecture\nCore Entity: WorkOrder, Lot, Machine")

    cfg = QuenchStackConfig(
        workspace_root=temp_dir,
        project_name="TestQuorch",
        architecture_doc="docs/architecture/system_design.md",
        constraints=["All state changes must be thread-safe", "Do not break offline queues"],
        reviewer_engine=ReviewerEngineConfig(
            provider="deepseek",
            model="deepseek-flash",
            api_key_env="MOCK_TEST_KEY_NOT_EXIST",
        ),
    )
    yield temp_dir, cfg
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_prompt_assembler_static_prefix_purity(mock_ws):
    ws_root, cfg = mock_ws
    prefix1 = PromptAssembler.build_static_system_prefix(ws_root, cfg)
    prefix2 = PromptAssembler.build_static_system_prefix(ws_root, cfg)

    # 1. 绝对静态纯洁性断言（两次生成必须逐字节一致，100% 稳定以命中 Prompt Cache）
    assert prefix1 == prefix2
    # 2. 包含架构文档内容
    assert "MES Test Architecture" in prefix1
    assert "WorkOrder" in prefix1
    # 3. 包含项目工程约束
    assert "All state changes must be thread-safe" in prefix1
    # 4. 包含六大字段指引
    assert "Six Core Fields" in prefix1


def test_deepseek_client_unavailable_when_provider_none(mock_ws):
    _, cfg = mock_ws
    cfg.reviewer_engine.provider = "none"
    client = DeepSeekClient(cfg.reviewer_engine)

    assert client.is_available() is False
    with pytest.raises(ReviewerEngineUnavailableError):
        client.complete([{"role": "user", "content": "hello"}])


def test_deepseek_client_successful_completion_with_thinking(mock_ws):
    _, cfg = mock_ws
    client = DeepSeekClient(cfg.reviewer_engine)

    mock_response_json = {
        "id": "chatcmpl-test-123",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "This is reviewed spec output.",
                    "reasoning_content": "Red team thinking: edge case identified.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "total_tokens": 165,
            "prompt_cache_hit_tokens": 96,
        },
    }
    raw_bytes = json.dumps(mock_response_json).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_bytes
    mock_resp.__enter__.return_value = mock_resp

    with patch.object(client, "resolve_api_key", return_value="mock-sk-123456"):
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = client.complete([{"role": "user", "content": "review draft"}])

            assert mock_urlopen.call_count == 1
            assert result["content"] == "This is reviewed spec output."
            assert result["reasoning_content"] == "Red team thinking: edge case identified."
            assert result["usage"]["prompt_cache_hit_tokens"] == 96


def test_deepseek_client_401_no_retry(mock_ws):
    _, cfg = mock_ws
    client = DeepSeekClient(cfg.reviewer_engine)

    err_fp = io.BytesIO(b'{"error": {"message": "Invalid API Key"}}')
    http_err_401 = urllib.error.HTTPError(
        url="https://api.deepseek.com/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=err_fp,
    )

    with patch.object(client, "resolve_api_key", return_value="bad-sk"):
        with patch("urllib.request.urlopen", side_effect=http_err_401) as mock_urlopen:
            with pytest.raises(ReviewerAuthenticationError):
                client.complete([{"role": "user", "content": "review draft"}])

            # 关键防线断言：401 必须单次快速失败，绝对严禁盲目重试
            assert mock_urlopen.call_count == 1


def test_deepseek_client_429_retry_and_succeed(mock_ws):
    _, cfg = mock_ws
    cfg.reviewer_engine.max_retries = 2
    client = DeepSeekClient(cfg.reviewer_engine)

    err_fp = io.BytesIO(b'{"error": "rate limit exceeded"}')
    http_err_429 = urllib.error.HTTPError(
        url="https://api.deepseek.com/chat/completions",
        code=429,
        msg="Too Many Requests",
        hdrs={},
        fp=err_fp,
    )

    mock_success = {
        "choices": [{"message": {"content": "ok after retry", "reasoning_content": "thinking ok"}}],
        "usage": {"total_tokens": 10},
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_success).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    # 第一次 429，第二次成功
    with patch.object(client, "resolve_api_key", return_value="valid-sk"):
        with patch("urllib.request.urlopen", side_effect=[http_err_429, mock_resp]) as mock_urlopen:
            with patch("time.sleep") as mock_sleep:
                res = client.complete([{"role": "user", "content": "hi"}])
                assert mock_urlopen.call_count == 2
                assert mock_sleep.call_count == 1
                assert res["content"] == "ok after retry"


def test_deepseek_client_network_timeout(mock_ws):
    _, cfg = mock_ws
    cfg.reviewer_engine.max_retries = 1
    client = DeepSeekClient(cfg.reviewer_engine)

    with patch.object(client, "resolve_api_key", return_value="valid-sk"):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")) as mock_urlopen:
            with patch("time.sleep"):
                with pytest.raises(ReviewerEngineError) as exc_info:
                    client.complete([{"role": "user", "content": "hi"}])

                assert "网络通信超时或异常" in str(exc_info.value)
                assert mock_urlopen.call_count == 2
