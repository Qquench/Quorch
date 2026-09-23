# -*- coding: utf-8 -*-
"""Unit tests for ReviewerEngine declarative factory neutrality,
PROVIDER_PRESETS registry, and configuration edge cases.
"""
import pytest

from project_config import (
    PROVIDER_ALIASES,
    PROVIDER_PRESETS,
    ProviderPreset,
    ReviewerEngineConfig,
    create_reviewer_client,
    resolve_preset,
)
from reviewer_engine import ReviewerClient, ReviewerNotConfiguredError


def test_provider_presets_immutability():
    """断言 PROVIDER_PRESETS 与 PROVIDER_ALIASES 具有运行时只读性（负向断言）。"""
    with pytest.raises(TypeError):
        PROVIDER_PRESETS["new_vendor"] = ProviderPreset("http://example.com", "KEY")  # type: ignore

    with pytest.raises(TypeError):
        PROVIDER_ALIASES["alias"] = "openai"  # type: ignore


def test_reviewer_engine_config_defaults_are_neutral():
    """断言默认配置下所有字段均为中立占位符，不包含任何厂商字面量。"""
    cfg = ReviewerEngineConfig()
    assert cfg.provider == "none"
    assert cfg.model == "default"
    assert cfg.api_key_env is None
    assert cfg.base_url == ""
    assert cfg.mode == "auto"
    assert "manual" in cfg.strategy_order


def test_create_reviewer_client_none_returns_none():
    """断言 provider in ('none', '', None) 时工厂明确返回 None，触发调用方降级卡。"""
    assert create_reviewer_client(ReviewerEngineConfig(provider="none")) is None
    assert create_reviewer_client(ReviewerEngineConfig(provider="")) is None
    assert create_reviewer_client(None) is None  # type: ignore


def test_unknown_provider_empty_base_url_raises_not_configured():
    """断言未知 provider 且未指定 base_url 时抛出带修复指引的 ReviewerNotConfiguredError（负向断言）。"""
    cfg = ReviewerEngineConfig(provider="unknown-cloud-ai", base_url="")
    with pytest.raises(ReviewerNotConfiguredError) as exc_info:
        create_reviewer_client(cfg)

    err = str(exc_info.value)
    assert "未知 Reviewer provider='unknown-cloud-ai'" in err
    assert "quench_stack.yaml" in err


def test_unknown_provider_remote_url_without_key_raises_not_configured():
    """断言远端端点缺少 api_key_env 时必须抛出 ReviewerNotConfiguredError，杜绝空 Key 明文请求（负向断言）。"""
    cfg = ReviewerEngineConfig(
        provider="custom-remote",
        base_url="https://remote-llm.example.com/v1",
        api_key_env=None,
    )
    with pytest.raises(ReviewerNotConfiguredError) as exc_info:
        create_reviewer_client(cfg)

    assert "必须配置 api_key_env" in str(exc_info.value)


def test_url_validation_rejections():
    """断言非法 URL（非 http/https、空 host、含 @ userinfo）均被严格拒绝（负向断言）。"""
    # 1. 非 http/https 协议
    with pytest.raises(ReviewerNotConfiguredError) as e1:
        create_reviewer_client(ReviewerEngineConfig(provider="custom", base_url="ftp://localhost:8000"))
    assert "必须为 http 或 https 协议" in str(e1.value)

    # 2. 空 host
    with pytest.raises(ReviewerNotConfiguredError) as e2:
        create_reviewer_client(ReviewerEngineConfig(provider="custom", base_url="http:///path"))
    assert "必须包含有效的 host" in str(e2.value)

    # 3. 包含 @ userinfo
    with pytest.raises(ReviewerNotConfiguredError) as e3:
        create_reviewer_client(ReviewerEngineConfig(provider="custom", base_url="https://user:pass@example.com/v1"))
    assert "不得包含 userinfo 凭据" in str(e3.value)


def test_preset_resolution_and_alias_mapping():
    """断言别名正确映射到预设规范条目，且解析出同一个 preset 对象。"""
    deepseek_preset = resolve_preset("deepseek")  # vendor-literal: allow
    alias_preset = resolve_preset("deepseek-compatible")  # vendor-literal: allow
    assert deepseek_preset is not None
    assert alias_preset is not None
    assert deepseek_preset is alias_preset

    openai_preset = resolve_preset("openai")
    openai_alias = resolve_preset("openai-compatible")
    assert openai_preset is not None
    assert openai_alias is not None
    assert openai_preset is openai_alias


def test_local_endpoint_exempt_from_auth_and_factory_instantiation():
    """断言本地端点（localhost / 127.0.0.1）豁免 api_key_env，且工厂正确构造 ReviewerClient 实例。"""
    cfg = ReviewerEngineConfig(
        provider="vllm",
        base_url="http://127.0.0.1:8000/v1",
        model="qwen2.5",
    )
    client = create_reviewer_client(cfg)
    assert isinstance(client, ReviewerClient)
    assert client.base_url == "http://127.0.0.1:8000/v1"
    assert client.model == "qwen2.5"
    assert client.provider_label == "vllm"
    assert client.api_key_env is None
