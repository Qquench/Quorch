# -*- coding: utf-8 -*-
"""Unit tests for Quench Reviewer Engine: ReviewerClient & PromptAssembler.
Protocol-neutral test suite covering happy path, failure modes, async offload, deadline budgets,
malformed corporate proxy responses, and Prompt Cache stability.
"""
import io
import json
import os
import shutil
import tempfile
import urllib.error
import warnings
from unittest.mock import MagicMock, patch

import anyio
import pytest

from project_config import QuenchStackConfig, ReviewerEngineConfig
import reviewer_engine
from reviewer_engine import (
    PromptAssembler,
    ReviewerAuthenticationError,
    ReviewerBadRequestError,
    ReviewerClient,
    ReviewerEngineError,
    ReviewerEngineUnavailableError,
    _read_windows_env_var,
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
            provider="custom",
            base_url="https://reviewer.internal.net/v1",
            model="reviewer-eval-v1",
            api_key_env="MOCK_TEST_KEY_NOT_EXIST",
            timeout_seconds=30,
        ),
    )
    yield temp_dir, cfg
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_default_config_provider_none_backward_compat():
    """断言红线 2：缺省配置下 provider 必须为 'none'，引擎不可用，100% 向后兼容。"""
    default_cfg = ReviewerEngineConfig()
    assert default_cfg.provider == "none"
    client = ReviewerClient(default_cfg)
    assert client.is_available() is False


def test_prompt_assembler_static_prefix_purity_and_hash(mock_ws):
    ws_root, cfg = mock_ws
    prefix1 = PromptAssembler.build_static_system_prefix(ws_root, cfg)
    prefix2 = PromptAssembler.build_static_system_prefix(ws_root, cfg)

    # 1. 绝对静态纯洁性断言（两次生成必须逐字节一致，100% 稳定以命中 Prompt Cache）
    assert prefix1 == prefix2
    assert "MES Test Architecture" in prefix1
    assert "WorkOrder" in prefix1
    assert "All state changes must be thread-safe" in prefix1
    assert "Six Core Fields" in prefix1

    # 2. SHA256 指纹稳定性
    h1 = PromptAssembler.get_prefix_hash(prefix1)
    h2 = PromptAssembler.get_prefix_hash(prefix2)
    assert len(h1) == 16
    assert h1 == h2

    # 3. 消息组装器：强制系统静态前缀作为第 1 个消息
    turns = [{"role": "user", "content": "review draft"}]
    msgs = PromptAssembler.assemble_messages(prefix1, turns)
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == prefix1
    assert msgs[1] == turns[0]


def test_reviewer_client_unavailable_when_provider_none(mock_ws):
    _, cfg = mock_ws
    cfg.reviewer_engine.provider = "none"
    client = ReviewerClient(cfg.reviewer_engine)

    assert client.is_available() is False
    with pytest.raises(ReviewerEngineUnavailableError):
        client.complete([{"role": "user", "content": "hello"}])


def test_reviewer_client_successful_completion_with_thinking_payload_assertions(mock_ws):
    """验证 Thinking 提取、模型参数、URL、请求头与 Timeout 真实断言。"""
    _, cfg = mock_ws
    client = ReviewerClient(cfg.reviewer_engine)

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
            # 严格断言实际发送给网关的网络载荷 (Wire Contract)
            sent_req = mock_urlopen.call_args.args[0]
            sent_payload = json.loads(sent_req.data.decode("utf-8"))
            assert sent_payload["model"] == "reviewer-eval-v1"
            assert sent_payload["thinking"] == {"type": "enabled"}
            assert sent_payload["reasoning_effort"] == "high"
            assert sent_payload["stream"] is False
            assert sent_req.full_url == "https://reviewer.internal.net/v1/chat/completions"
            assert sent_req.headers["Authorization"] == "Bearer mock-sk-123456"
            assert mock_urlopen.call_args.kwargs["timeout"] == 30.0

            assert result["content"] == "This is reviewed spec output."
            assert result["reasoning_content"] == "Red team thinking: edge case identified."
            assert result["usage"]["prompt_cache_hit_tokens"] == 96


def test_reviewer_client_401_no_retry_even_with_retries_configured(mock_ws):
    """即使配置了 max_retries=3，遇到 401 Unauthorized 必须单次即崩溃，严禁重试；文案只依赖注入的 provider_label。"""
    _, cfg = mock_ws
    cfg.reviewer_engine.max_retries = 3
    client = ReviewerClient(cfg.reviewer_engine, provider_label="ollama")

    err_fp = io.BytesIO(b'{"error": {"message": "Invalid API Key"}}')
    http_err_401 = urllib.error.HTTPError(
        url="https://reviewer.internal.net/v1/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=err_fp,
    )

    with patch.object(client, "resolve_api_key", return_value="bad-sk"):
        with patch("urllib.request.urlopen", side_effect=http_err_401) as mock_urlopen:
            with pytest.raises(ReviewerAuthenticationError) as exc_info:
                client.complete([{"role": "user", "content": "review draft"}])

            assert mock_urlopen.call_count == 1
            err_text = str(exc_info.value)
            assert "ollama" in err_text
            assert "deepseek" not in err_text.casefold()


def test_reviewer_client_400_bad_request_fast_fail(mock_ws):
    """400 Bad Request 参数错误：单次快速失败，严禁盲目重试。"""
    _, cfg = mock_ws
    cfg.reviewer_engine.max_retries = 3
    client = ReviewerClient(cfg.reviewer_engine)

    err_fp = io.BytesIO(b'{"error": {"message": "Invalid model parameter"}}')
    http_err_400 = urllib.error.HTTPError(
        url="https://reviewer.internal.net/v1/chat/completions",
        code=400,
        msg="Bad Request",
        hdrs={},
        fp=err_fp,
    )

    with patch.object(client, "resolve_api_key", return_value="valid-sk"):
        with patch("urllib.request.urlopen", side_effect=http_err_400) as mock_urlopen:
            with pytest.raises(ReviewerBadRequestError):
                client.complete([{"role": "user", "content": "review draft"}])

            assert mock_urlopen.call_count == 1


def test_reviewer_client_proxy_html_malformed_response_resilience(mock_ws):
    """企业代理/VPN 拦截并返回 HTTP 200 + HTML 登录页时，防御性解析为 ReviewerEngineError。"""
    _, cfg = mock_ws
    client = ReviewerClient(cfg.reviewer_engine)

    html_bytes = b"<html><head><title>Corporate Proxy Login</title></head><body>Please login</body></html>"
    mock_resp = MagicMock()
    mock_resp.read.return_value = html_bytes
    mock_resp.__enter__.return_value = mock_resp

    with patch.object(client, "resolve_api_key", return_value="mock-sk"):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(ReviewerEngineError) as exc_info:
                client.complete([{"role": "user", "content": "test"}])

            assert "[Malformed Response]" in str(exc_info.value)
            assert "非合法 JSON" in str(exc_info.value)


def test_reviewer_client_empty_choices_resilience(mock_ws):
    """服务端返回 200 但缺少 choices 列表时的防御。"""
    _, cfg = mock_ws
    client = ReviewerClient(cfg.reviewer_engine)

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"id": "test", "choices": []}'
    mock_resp.__enter__.return_value = mock_resp

    with patch.object(client, "resolve_api_key", return_value="mock-sk"):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(ReviewerEngineError) as exc_info:
                client.complete([{"role": "user", "content": "test"}])

            assert "缺少 choices" in str(exc_info.value)


def test_reviewer_client_total_deadline_exhaustion(mock_ws):
    """总耗时预算熔断：测试重试耗时超出 total_deadline_s 时主动熔断。"""
    _, cfg = mock_ws
    cfg.reviewer_engine.max_retries = 2
    client = ReviewerClient(cfg.reviewer_engine)

    # 设极短总预算（-1.0s）立即触发熔断
    with patch.object(client, "resolve_api_key", return_value="mock-sk"):
        with patch("reviewer_engine.time.sleep"):
            with pytest.raises(ReviewerEngineError) as exc_info:
                client.complete([{"role": "user", "content": "test"}], total_deadline_s=-1.0)

            assert "[Deadline Exceeded]" in str(exc_info.value)


def test_reviewer_client_429_retry_and_succeed_with_retry_after(mock_ws):
    """429 流控重试：支持 Retry-After 头与指数退避抖动重试。"""
    _, cfg = mock_ws
    cfg.reviewer_engine.max_retries = 2
    client = ReviewerClient(cfg.reviewer_engine)

    err_fp = io.BytesIO(b'{"error": "rate limit exceeded"}')
    http_err_429 = urllib.error.HTTPError(
        url="https://reviewer.internal.net/v1/chat/completions",
        code=429,
        msg="Too Many Requests",
        hdrs={"Retry-After": "2"},
        fp=err_fp,
    )

    mock_success = {
        "choices": [{"message": {"content": "ok after retry", "reasoning_content": "thinking ok"}}],
        "usage": {"total_tokens": 10},
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_success).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch.object(client, "resolve_api_key", return_value="valid-sk"):
        with patch("urllib.request.urlopen", side_effect=[http_err_429, mock_resp]) as mock_urlopen:
            with patch("reviewer_engine.time.sleep") as mock_sleep:
                res = client.complete([{"role": "user", "content": "hi"}])
                assert mock_urlopen.call_count == 2
                assert mock_sleep.call_count == 1
                # 必须采纳 Retry-After 的 2.0s
                mock_sleep.assert_called_with(2.0)
                assert res["content"] == "ok after retry"


def test_read_windows_env_var_fallback_seam(mock_ws):
    """测试 Windows 注册表读取 Seam 穿透能力与 CI 隔离性。"""
    _, cfg = mock_ws
    client = ReviewerClient(cfg.reviewer_engine)

    with patch.dict(os.environ, {}, clear=True):
        with patch("reviewer_engine._read_windows_env_var", return_value="registry-secret-key"):
            key = client.resolve_api_key()
            assert key == "registry-secret-key"


@pytest.mark.anyio
async def test_reviewer_client_acomplete_async(mock_ws):
    """验证异步门面 acomplete 使用 AnyIO 卸载至后台线程，不阻塞主事件循环。"""
    _, cfg = mock_ws
    client = ReviewerClient(cfg.reviewer_engine)

    mock_resp_json = {
        "choices": [{"message": {"content": "async response", "reasoning_content": "async thinking"}}],
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_resp_json).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch.object(client, "resolve_api_key", return_value="valid-sk"):
        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = await client.acomplete([{"role": "user", "content": "hello async"}])
            assert res["content"] == "async response"
            assert res["reasoning_content"] == "async thinking"


def test_deepseek_client_backward_compat_alias_warning():
    """断言向后兼容别名 DeepSeekClient 映射至 ReviewerClient 且抛出 DeprecationWarning。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        deprecated_cls = reviewer_engine.DeepSeekClient
        assert deprecated_cls is ReviewerClient
        assert any(issubclass(item.category, DeprecationWarning) for item in w)
        assert any("ReviewerClient" in str(item.message) for item in w)
