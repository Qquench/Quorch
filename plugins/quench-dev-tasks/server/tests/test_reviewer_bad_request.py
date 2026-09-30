# -*- coding: utf-8 -*-
"""Unit tests for ReviewerBadRequestError symmetry between stream and complete/acomplete paths."""
from __future__ import annotations

import io
import urllib.error
from typing import Any, Mapping
from unittest.mock import patch
import pytest

import reviewer_engine
from reviewer_engine import (
    ReviewerBadRequestError,
    ReviewerClient,
    ReviewerEngineError,
    ReviewerError,
)


def test_reviewer_bad_request_error_inheritance_contract() -> None:
    """断言继承链契约：ReviewerBadRequestError 必须严格继承自 ReviewerEngineError 及基类 ReviewerError。"""
    assert issubclass(ReviewerBadRequestError, ReviewerEngineError)
    assert issubclass(ReviewerBadRequestError, ReviewerError)
    err = ReviewerBadRequestError("test 400/422")
    assert isinstance(err, ReviewerError)
    assert isinstance(err, ReviewerEngineError)


@pytest.mark.parametrize("status_code", [400, 422])
def test_complete_bad_request_fast_fail(status_code: int) -> None:
    """断言 complete 路径对 400 与 422 状态码统一抛出 ReviewerBadRequestError 并单次快速失败。"""
    client = ReviewerClient(
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        provider_label="mock_provider",
        max_retries=3,
    )
    err_fp = io.BytesIO(b'{"error": {"message": "Invalid prompt or parameters"}}')
    http_err = urllib.error.HTTPError(
        url="http://127.0.0.1:11434/v1/chat/completions",
        code=status_code,
        msg="Unprocessable Entity" if status_code == 422 else "Bad Request",
        hdrs={},
        fp=err_fp,
    )

    with patch.object(client, "resolve_api_key", return_value="mock-key"):
        with patch("urllib.request.urlopen", side_effect=http_err) as mock_urlopen:
            with pytest.raises(ReviewerBadRequestError) as exc_info:
                client.complete([{"role": "user", "content": "hello"}])

            # 快速失败，绝不重试
            assert mock_urlopen.call_count == 1
            # 兼容上游捕获面
            assert isinstance(exc_info.value, ReviewerError)


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [400, 422])
async def test_acomplete_bad_request_fast_fail(status_code: int) -> None:
    """断言 acomplete 异步门面同样抛出 ReviewerBadRequestError。"""
    client = ReviewerClient(
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        provider_label="mock_provider",
        max_retries=3,
    )
    err_fp = io.BytesIO(b'{"error": {"message": "Invalid prompt or parameters"}}')
    http_err = urllib.error.HTTPError(
        url="http://127.0.0.1:11434/v1/chat/completions",
        code=status_code,
        msg="Error",
        hdrs={},
        fp=err_fp,
    )

    with patch.object(client, "resolve_api_key", return_value="mock-key"):
        with patch("urllib.request.urlopen", side_effect=http_err) as mock_urlopen:
            with pytest.raises(ReviewerBadRequestError) as exc_info:
                await client.acomplete([{"role": "user", "content": "hello"}])

            assert mock_urlopen.call_count == 1
            assert isinstance(exc_info.value, ReviewerError)


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [400, 422])
async def test_stream_chat_bad_request_fast_fail(monkeypatch: pytest.MonkeyPatch, status_code: int) -> None:
    """断言 stream_chat 路径对 400 与 422 状态码统一抛出 ReviewerBadRequestError 并快速收敛。"""
    client = ReviewerClient(
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        provider_label="mock_provider",
        max_retries=3,
    )
    err_fp = io.BytesIO(b'{"error": {"message": "Stream bad request"}}')
    http_err = urllib.error.HTTPError(
        url="http://127.0.0.1:11434/v1/chat/completions",
        code=status_code,
        msg="Error",
        hdrs={},
        fp=err_fp,
    )

    call_count = 0

    def fake_open_sse(url: str, data: bytes, headers: Mapping[str, str], timeout: float) -> Any:
        nonlocal call_count
        call_count += 1
        raise http_err

    monkeypatch.setattr(reviewer_engine, "_open_sse_response", fake_open_sse)

    with patch.object(client, "resolve_api_key", return_value="mock-key"):
        with pytest.raises(ReviewerBadRequestError) as exc_info:
            async for _ in client.stream_chat("sys", "user"):
                pass

        # 单次快速失败
        assert call_count == 1
        assert isinstance(exc_info.value, ReviewerError)
