# -*- coding: utf-8 -*-
"""Unit tests for ReviewerEngine generic probes, vendor-neutral ReviewerClient,
and backward-compatible DeepSeekClient alias.
"""
import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

import reviewer_engine
from reviewer_engine import (
    ReviewerAuthError,
    ReviewerAuthenticationError,
    ReviewerClient,
    ReviewerEngineUnavailableError,
    ReviewerError,
    ReviewerNotConfiguredError,
    StreamChunk,
    UsageSnapshot,
    _dig,
    extract_cached_tokens,
    extract_reasoning_text,
    extract_usage,
)


# 1. 参数化 9 组思考链字段路径组合
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"choices": [{"delta": {"reasoning_content": "probe_delta_reasoning_content"}}]}, "probe_delta_reasoning_content"),
        ({"choices": [{"delta": {"thought": "probe_delta_thought"}}]}, "probe_delta_thought"),
        ({"choices": [{"delta": {"reasoning": "probe_delta_reasoning"}}]}, "probe_delta_reasoning"),
        ({"choices": [{"message": {"reasoning_content": "probe_message_reasoning_content"}}]}, "probe_message_reasoning_content"),
        ({"choices": [{"message": {"thought": "probe_message_thought"}}]}, "probe_message_thought"),
        ({"choices": [{"message": {"reasoning": "probe_message_reasoning"}}]}, "probe_message_reasoning"),
        ({"reasoning_content": "probe_root_reasoning_content"}, "probe_root_reasoning_content"),
        ({"thought": "probe_root_thought"}, "probe_root_thought"),
        ({"reasoning": "probe_root_reasoning"}, "probe_root_reasoning"),
    ],
)
def test_extract_reasoning_text_9_paths(payload, expected):
    """断言 9 组跨厂商思考链路径均能被正确提取。"""
    assert extract_reasoning_text(payload) == expected


def test_extract_reasoning_text_edge_cases():
    """断言探针纯函数对畸形/缺失输入绝不抛异常且返回空字符串。"""
    assert extract_reasoning_text({}) == ""
    assert extract_reasoning_text(None) == ""
    assert extract_reasoning_text([]) == ""
    assert extract_reasoning_text("invalid") == ""
    assert extract_reasoning_text({"choices": []}) == ""
    assert extract_reasoning_text({"reasoning": None}) == ""
    assert extract_reasoning_text({"reasoning": 12345}) == ""
    assert extract_reasoning_text({"reasoning": {"dict": "invalid"}}) == ""
    assert extract_reasoning_text({"choices": [{"delta": {"reasoning_content": ""}}]}) == ""


# 2. 参数化 4 种跨厂商 Prompt Cache 计量形态
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"usage": {"prompt_cache_hit_tokens": 120}}, 120),
        ({"usage": {"prompt_tokens_details": {"cached_tokens": 80}}}, 80),
        ({"usage": {"cache_read_input_tokens": 40}}, 40),
        ({"usage": {"cached_tokens": 60}}, 60),
    ],
)
def test_extract_cached_tokens_4_forms(payload, expected):
    """断言 4 种主流厂商 Prompt Cache 命中计量形态均被正确归一化。"""
    assert extract_cached_tokens(payload) == expected


def test_extract_cached_tokens_edge_cases():
    """断言缓存计量探针对扁平结构、缺失和非法值的纯函数安全性。"""
    # 扁平形态直接在 payload 根部
    assert extract_cached_tokens({"prompt_cache_hit_tokens": 55}) == 55
    assert extract_cached_tokens({"cached_tokens": 33}) == 33
    # 缺失或非整数
    assert extract_cached_tokens({}) == 0
    assert extract_cached_tokens(None) == 0
    assert extract_cached_tokens({"usage": {"prompt_tokens": 100}}) == 0
    assert extract_cached_tokens({"usage": {"cached_tokens": "invalid_string"}}) == 0
    assert extract_cached_tokens({"usage": {"cached_tokens": -5}}) == 0
    assert extract_cached_tokens({"usage": {"cached_tokens": True}}) == 0


def test_extract_usage_snapshot():
    """断言 extract_usage 构造出完整的跨厂商 UsageSnapshot。"""
    payload = {
        "usage": {
            "prompt_tokens": 200,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 150},
            "completion_tokens_details": {"reasoning_tokens": 30},
        }
    }
    snapshot = extract_usage(payload, provider_label="test-provider")
    assert isinstance(snapshot, UsageSnapshot)
    assert snapshot.prompt_tokens == 200
    assert snapshot.completion_tokens == 50
    assert snapshot.cached_tokens == 150
    assert snapshot.reasoning_tokens == 30
    assert snapshot.provider_label == "test-provider"

    # 空输入安全降级
    empty_snapshot = extract_usage(None, provider_label="custom")
    assert empty_snapshot.prompt_tokens == 0
    assert empty_snapshot.cached_tokens == 0
    assert empty_snapshot.provider_label == "custom"


# 3. 构造 provider_label="ollama" 客户端，模拟 401 响应，断言文案中立性
def test_client_401_error_message_vendor_neutrality():
    """断言 401 异常文案包含注入的 provider_label ('ollama') 且不含 hardcoded 'deepseek'。"""
    client = ReviewerClient(
        base_url="http://localhost:11434/v1",
        model="llama3",
        provider_label="ollama",
        api_key_env="OLLAMA_API_KEY",
    )

    err_fp = io.BytesIO(b'{"error": "unauthorized"}')
    http_err_401 = urllib.error.HTTPError(
        url="http://localhost:11434/v1/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=err_fp,
    )

    with patch.object(client, "resolve_api_key", return_value="mock-key"):
        with patch("urllib.request.urlopen", side_effect=http_err_401):
            with pytest.raises(ReviewerAuthError) as exc_info:
                client.complete([{"role": "user", "content": "hello"}])

            err_msg = str(exc_info.value)
            # 断言异常同时也是向后兼容的 ReviewerAuthenticationError
            assert isinstance(exc_info.value, ReviewerAuthenticationError)
            assert isinstance(exc_info.value, ReviewerAuthError)
            # 严格断言包含 ollama 且不包含 deepseek (大小写不敏感)
            assert "ollama" in err_msg.lower()
            assert "deepseek" not in err_msg.lower()


# 4. 断言 DeepSeekClient 别名可用且触发 DeprecationWarning
def test_deepseek_client_deprecation_warning_alias():
    """断言 PEP 562 兼容层：DeepSeekClient 别名可用且触发 DeprecationWarning。"""
    with pytest.deprecated_call():
        client_cls = reviewer_engine.DeepSeekClient  # vendor-literal: allow

    assert client_cls is ReviewerClient

    # 验证通过别名实例化客户端功能正常
    client = client_cls(
        base_url="http://127.0.0.1:8000/v1",
        model="qwen",
        provider_label="vllm",
    )
    assert client.provider_label == "vllm"
    assert client.base_url == "http://127.0.0.1:8000/v1"


# 5. 断言 stream_chat 基本通信协议与探针解包能力
@pytest.mark.anyio
async def test_stream_chat_streaming_chunks():
    """验证 stream_chat 能以 StreamChunk 格式流式分块解出 reasoning、text 与 usage。"""
    client = ReviewerClient(
        base_url="http://127.0.0.1:11434/v1",
        model="qwen-coder",
        provider_label="ollama",
    )

    sse_text = (
        'data: {"choices": [{"delta": {"thought": "step 1 知识点分析"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "Hello "}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "world"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}\n\n'
        'data: [DONE]\n\n'
    )

    mock_resp = MagicMock()
    # 模拟逐块读取
    mock_resp.read.side_effect = [sse_text.encode("utf-8"), b""]
    mock_resp.__enter__.return_value = mock_resp

    with patch.object(client, "resolve_api_key", return_value=""):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            chunks = []
            async for chunk in client.stream_chat("sys", "user"):
                chunks.append(chunk)

            assert len(chunks) >= 2
            # 必须包含 done chunk
            assert any(c.done for c in chunks)
            # 必须包含 text
            combined_text = "".join(c.text for c in chunks)
            assert "Hello world" in combined_text
