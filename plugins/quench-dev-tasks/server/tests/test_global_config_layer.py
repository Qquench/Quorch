# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import pytest
import yaml
from project_config import (
    load_project_config,
    resolve_global_config_path,
    ConfigError,
    ConfigFault,
    ReviewerEngineConfig,
)
from reviewer_engine import ReviewerClient


@pytest.fixture
def mock_ws(tmp_path):
    """创建临时工作区，包含最小合法 .agents/quench_stack.yaml 基线。"""
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    stack_yaml = agents_dir / "quench_stack.yaml"
    base_data = {
        "schema_version": "1.0",
        "config_version": 1,
        "project_name": "test-global-cfg",
        "reviewer_engine": {
            "provider": "none",
            "model": "default",
            "thinking": True,
            "reasoning_effort": "high",
        },
        "audit_gate": {
            "enabled": True,
            "on_missing_record": "block",
            "on_degraded": "warn",
        },
    }
    stack_yaml.write_text(yaml.dump(base_data), encoding="utf-8")
    return tmp_path


def test_global_config_overrides_baseline_effort(mock_ws, tmp_path, monkeypatch):
    """T1: 基线 reasoning_effort: high + 全局 max -> 最终为 max"""
    global_file = tmp_path / "global_quorch.yaml"
    global_file.write_text(
        yaml.dump({
            "schema_version": "1.0",
            "reviewer_engine": {
                "reasoning_effort": "max",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUORCH_GLOBAL_CONFIG", str(global_file))

    cfg = load_project_config(str(mock_ws))
    assert cfg.reviewer_engine.reasoning_effort == "max"
    assert cfg.reviewer_engine.provider == "none"  # 其余字段保留基线


def test_local_override_wins_over_global(mock_ws, tmp_path, monkeypatch):
    """T2: 基线 high + 全局 max + 本地 local high -> 最终以 local high 胜出 (L3 > L2)"""
    global_file = tmp_path / "global_quorch.yaml"
    global_file.write_text(
        yaml.dump({
            "reviewer_engine": {
                "reasoning_effort": "max",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUORCH_GLOBAL_CONFIG", str(global_file))

    local_yaml = mock_ws / ".agents" / "quench_stack.local.yaml"
    local_yaml.write_text(
        yaml.dump({
            "reviewer_engine": {
                "reasoning_effort": "high",
            },
        }),
        encoding="utf-8",
    )

    cfg = load_project_config(str(mock_ws))
    assert cfg.reviewer_engine.reasoning_effort == "high"


def test_global_overrides_baseline_provider_and_url(mock_ws, tmp_path, monkeypatch):
    """T3: 全局自定义 provider/base_url 覆盖基线 none"""
    global_file = tmp_path / "global_quorch.yaml"
    global_file.write_text(
        yaml.dump({
            "reviewer_engine": {
                "provider": "custom-gateway",
                "base_url": "https://gateway.internal.net/v1",
                "reasoning_effort": "max",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUORCH_GLOBAL_CONFIG", str(global_file))

    cfg = load_project_config(str(mock_ws))
    assert cfg.reviewer_engine.provider == "custom-gateway"
    assert cfg.reviewer_engine.base_url == "https://gateway.internal.net/v1"
    assert cfg.reviewer_engine.reasoning_effort == "max"


def test_global_disallowed_keys_fail_fast(mock_ws, tmp_path, monkeypatch):
    """T4: 全局配置若包含非 reviewer_engine / schema_version 顶层键，立即抛 ConfigError (INV-A)"""
    global_file = tmp_path / "global_quorch.yaml"
    global_file.write_text(
        yaml.dump({
            "audit_gate": {
                "enabled": False,
            },
            "reviewer_engine": {
                "reasoning_effort": "max",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUORCH_GLOBAL_CONFIG", str(global_file))

    with pytest.raises(ConfigError) as exc_info:
        load_project_config(str(mock_ws))
    assert "disallowed top-level keys" in str(exc_info.value)
    assert "audit_gate" in str(exc_info.value)


def test_global_cannot_loosen_audit_gate_via_local(mock_ws, tmp_path, monkeypatch):
    """T5: 全局层即使存在，local 试图放宽基线 audit_gate 依然被单调收紧硬门禁拦截 (INV-B)"""
    global_file = tmp_path / "global_quorch.yaml"
    global_file.write_text(
        yaml.dump({
            "reviewer_engine": {
                "reasoning_effort": "max",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUORCH_GLOBAL_CONFIG", str(global_file))

    local_yaml = mock_ws / ".agents" / "quench_stack.local.yaml"
    local_yaml.write_text(
        yaml.dump({
            "audit_gate": {
                "on_missing_record": "allow",  # 试图从 block 放宽至 allow
            },
        }),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_project_config(str(mock_ws))
    assert ConfigFault.SAFETY_DOWNGRADE_DENIED.value in str(exc_info.value)


def test_env_disable_global_config(mock_ws, tmp_path, monkeypatch):
    """T8: QUORCH_DISABLE_GLOBAL_CONFIG=1 时强制忽略全局配置"""
    global_file = tmp_path / "global_quorch.yaml"
    global_file.write_text(
        yaml.dump({
            "reviewer_engine": {
                "reasoning_effort": "max",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUORCH_GLOBAL_CONFIG", str(global_file))
    monkeypatch.setenv("QUORCH_DISABLE_GLOBAL_CONFIG", "1")

    cfg = load_project_config(str(mock_ws))
    assert cfg.reviewer_engine.reasoning_effort == "high"  # 保持基线默认


def test_global_plaintext_api_key_forbidden(mock_ws, tmp_path, monkeypatch):
    """T9: 全局配置中填写明文 api_key 必须被拒绝"""
    global_file = tmp_path / "global_quorch.yaml"
    global_file.write_text(
        yaml.dump({
            "reviewer_engine": {
                "api_key": "sk-1234567890abcdef",
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("QUORCH_GLOBAL_CONFIG", str(global_file))

    with pytest.raises(ConfigError) as exc_info:
        load_project_config(str(mock_ws))
    assert "Plaintext api_key is forbidden" in str(exc_info.value)


def test_local_plaintext_api_key_in_reviewer_engine_forbidden(mock_ws):
    """T10: local.yaml 在 reviewer_engine 中填写明文 api_key 必须被拒绝"""
    local_yaml = mock_ws / ".agents" / "quench_stack.local.yaml"
    local_yaml.write_text(
        yaml.dump({
            "reviewer_engine": {
                "api_key": "sk-1234567890abcdef",
            },
        }),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_project_config(str(mock_ws))
    assert "Plaintext api_key is forbidden" in str(exc_info.value)


def test_reasoning_effort_null_and_custom_strings(mock_ws):
    """T11 & T12: reasoning_effort 为 null 解析为空字符串；自定义字符串原样保留"""
    local_yaml = mock_ws / ".agents" / "quench_stack.local.yaml"

    # null 场景 -> 空串（不发送）
    local_yaml.write_text(
        yaml.dump({
            "reviewer_engine": {
                "reasoning_effort": None,
            },
        }),
        encoding="utf-8",
    )
    cfg_null = load_project_config(str(mock_ws))
    assert cfg_null.reviewer_engine.reasoning_effort == ""

    # custom 场景 -> 原样透传
    local_yaml.write_text(
        yaml.dump({
            "reviewer_engine": {
                "reasoning_effort": "EXTREME",
            },
        }),
        encoding="utf-8",
    )
    cfg_custom = load_project_config(str(mock_ws))
    assert cfg_custom.reviewer_engine.reasoning_effort == "EXTREME"


def test_reviewer_client_sentinel_fix():
    """T14 & T15: 修复哨兵逻辑：显式传 'high' 覆盖 config 的 'max'；显式传 None 继承 config 的 'max'"""
    cfg = ReviewerEngineConfig(
        provider="custom",
        model="test-m",
        base_url="https://api.test/v1",
        reasoning_effort="max",
    )

    # 1. 显式传 "high"，必须成功覆盖 config 中的 "max"，不能被 sentinel 吞掉
    client_high = ReviewerClient(cfg, reasoning_effort="high")
    assert client_high.reasoning_effort == "high"

    # 2. 传 None，必须继承 config 中的 "max"
    client_inherited = ReviewerClient(cfg, reasoning_effort=None)
    assert client_inherited.reasoning_effort == "max"

    # 3. 传自定义字符串 "extreme"
    client_extreme = ReviewerClient(cfg, reasoning_effort="extreme")
    assert client_extreme.reasoning_effort == "extreme"
