# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import unicodedata
from pathlib import Path
from unittest.mock import patch
import warnings
import pytest
import yaml

from project_config import (
    CURRENT_CONFIG_VERSION,
    AuditGatePolicy,
    ConfigError,
    ConfigFault,
    SAFETY_KEY_DOMAINS,
    is_protected_config_path,
    load_project_config,
    migrate_and_validate,
)


def _get_repo_root() -> Path:
    # 向上寻找包含 .git 或 .agents 的目录
    cur = Path(__file__).resolve().parent
    while cur.parent != cur:
        if (cur / ".agents" / "quench_stack.yaml").is_file():
            return cur
        cur = cur.parent
    raise RuntimeError("Could not find repository root")


def test_version_gate():
    """断言：config_version > CURRENT -> raise ConfigError；合法版本正常放行。"""
    # 1) 合法版本当前值
    cfg, faults = migrate_and_validate({
        "project_name": "test_v1",
        "config_version": CURRENT_CONFIG_VERSION,
    })
    assert cfg.config_version == CURRENT_CONFIG_VERSION
    assert ConfigFault.VERSION_UNSUPPORTED not in faults

    # 2) 未来版本 -> 物理中断 fail-closed
    with pytest.raises(ConfigError) as exc_info:
        migrate_and_validate({
            "project_name": "test_future",
            "config_version": CURRENT_CONFIG_VERSION + 1,
        })
    assert "config_version_unsupported" in str(exc_info.value) or "高于当前系统支持版本" in str(exc_info.value) or "Unsupported" in str(exc_info.value)

    # 3) 格式非法（非整数字符串） -> raise ConfigError
    with pytest.raises(ConfigError) as exc_info_invalid:
        migrate_and_validate({
            "project_name": "test_invalid_ver",
            "config_version": "v1_alpha",
        })
    assert "config_version" in str(exc_info_invalid.value)


def test_missing_version_migrates():
    """断言：缺失 config_version 视作 v1 幂等迁移。"""
    raw = {
        "project_name": "migrated_project",
        "dev_tasks_dir": "docs/tasks",
    }
    assert "config_version" not in raw
    cfg, faults = migrate_and_validate(raw)
    assert cfg.config_version == CURRENT_CONFIG_VERSION
    assert cfg.project_name == "migrated_project"
    assert ConfigFault.VERSION_UNSUPPORTED not in faults


def test_unknown_key_warn():
    """断言：未知键 -> 降级为 UNKNOWN_KEY warn 并安全忽略，不抛错中断。"""
    raw = {
        "project_name": "tolerant_app",
        "config_version": 1,
        "experimental_feature_flag_x": True,
        "future_slimming_option_y": {"deep": "value"},
    }
    with pytest.warns(UserWarning, match="将被安全忽略降级|safely ignored"):
        cfg, faults = migrate_and_validate(raw)

    assert cfg.project_name == "tolerant_app"
    assert ConfigFault.UNKNOWN_KEY in faults
    # 统计未知键个数
    assert faults.count(ConfigFault.UNKNOWN_KEY) == 2


def test_safety_value_fail_closed():
    """断言：安全键非法值（如 on_missing_record: blcok）-> raise ConfigError（fail-closed）。"""
    # 1) 拼写错误 (typo)
    with pytest.raises(ConfigError) as exc_typo:
        migrate_and_validate({
            "project_name": "test_safety",
            "config_version": 1,
            "audit_gate": {
                "on_missing_record": "blcok",
            },
        })
    assert "audit_gate.on_missing_record" in str(exc_typo.value)
    assert "invalid_safety_value" in str(exc_typo.value)

    # 2) 非法取值
    with pytest.raises(ConfigError) as exc_degraded:
        migrate_and_validate({
            "project_name": "test_safety",
            "config_version": 1,
            "audit_gate": {
                "on_degraded": "silent_pass",
            },
        })
    assert "audit_gate.on_degraded" in str(exc_degraded.value)

    # 3) tail_window_exhausted_policy 非法值
    with pytest.raises(ConfigError) as exc_tail:
        migrate_and_validate({
            "project_name": "test_safety",
            "config_version": 1,
            "audit_gate": {
                "tail_window_exhausted_policy": "bypass",
            },
        })
    assert "audit_gate.tail_window_exhausted_policy" in str(exc_tail.value)


def test_real_stack_config_clean_load():
    """断言：现行 .agents/quench_stack.yaml 含 on_degraded: warn 加载零 fault（C-1 回归防护，必测）。"""
    repo_root = _get_repo_root()
    stack_yaml = repo_root / ".agents" / "quench_stack.yaml"
    assert stack_yaml.is_file(), f"quench_stack.yaml not found at {stack_yaml}"

    with open(stack_yaml, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # 验证现网实值
    ag = data.get("audit_gate", {})
    assert ag.get("on_degraded") == "warn", "现网配置应包含 on_degraded: warn"
    assert ag.get("tail_window_exhausted_policy") is None
    assert ag.get("on_missing_record") == "block"
    assert ag.get("on_internal_error") == "allow"

    # 执行 migrate_and_validate
    cfg, faults = migrate_and_validate(data)
    assert faults == [], f"现行配置必须零 fault 清爽加载，实际收到: {faults}"
    assert cfg.config_version == 1
    assert cfg.audit_gate.on_degraded == "warn"
    assert cfg.audit_gate.tail_window_exhausted_policy is None

    # 执行完整的 load_project_config
    loaded = load_project_config(str(repo_root))
    assert loaded.config_version == 1
    assert loaded.audit_gate.on_degraded == "warn"


def test_protected_config_fail_closed():
    """断言：受保护配置「词法 + realpath」双错 -> 返回 True（fail-closed）。"""
    # 1) 标准受保护路径
    assert is_protected_config_path(".agents/quench_stack.yaml") is True
    assert is_protected_config_path("quench_stack.yaml") is True
    assert is_protected_config_path("sub/dir/quench_stack.local.yaml") is True

    # 2) 非受保护文件
    assert is_protected_config_path("plugins/quench-dev-tasks/server/server.py") is False
    assert is_protected_config_path("docs/dev_tasks/some_task.md") is False

    # 3) 模拟 realpath 抛出异常 (双错场景) -> fail-closed 返回 True
    with patch("os.path.realpath", side_effect=OSError("Disk hardware error / 模拟底层 IO 故障")):
        # 即使传普通路径，因发生底层解析错误，必须 fail-closed 拦截
        assert is_protected_config_path("any_file.py") is True

    # 4) 模拟类型非法或异常传参
    class BadObj:
        def __str__(self):
            raise RuntimeError("Corrupted string conversion")
    assert is_protected_config_path(BadObj()) is True


def test_nfd_mismatch():
    """断言：非 NFC 输入 -> NFD_MISMATCH，不静默归一，fail-closed 拦截。"""
    # 构造带有重音/多字节的 NFD 字符串
    raw_name = "quench_stáck.yaml"
    nfd_name = unicodedata.normalize("NFD", raw_name)
    assert unicodedata.is_normalized("NFC", nfd_name) is False

    faults: list[ConfigFault] = []
    # 1) is_protected_config_path 遇到非 NFC 输入，返回 True（fail-closed 拒绝静默归一）并记录 NFD_MISMATCH
    res = is_protected_config_path(nfd_name, faults)
    assert res is True
    assert ConfigFault.NFD_MISMATCH in faults

    # 2) migrate_and_validate 顶层键遇到非 NFC 字符时上报 NFD_MISMATCH
    nfd_key = unicodedata.normalize("NFD", "project_nâme")
    raw_with_nfd = {
        nfd_key: "my_proj",
        "project_name": "clean_proj",
    }
    _, m_faults = migrate_and_validate(raw_with_nfd)
    assert ConfigFault.NFD_MISMATCH in m_faults


def test_ads_component():
    """断言：Windows ADS（交替数据流）与尾随点等价类规范化识别为受保护配置。"""
    # 1) Windows ADS 语法 (file:stream)
    assert is_protected_config_path("quench_stack.yaml:hidden_stream") is True
    assert is_protected_config_path(".agents/quench_stack.yaml::$DATA") is True
    assert is_protected_config_path("d:/repo/.agents/quench_stack.local.yaml:zone_identifier") is True

    # 2) Windows 尾随点与空格等价类绕过
    assert is_protected_config_path("quench_stack.yaml.") is True
    assert is_protected_config_path("quench_stack.yaml... ") is True
    assert is_protected_config_path(".agents/quench_stack.yaml. ") is True

    # 3) 普通非保护文件的 ADS 不应误报为保护配置
    assert is_protected_config_path("regular_script.py:stream") is False
    assert is_protected_config_path("docs/task.md.") is False


def test_hook_latency_budget():
    """断言：Hook 路径防护与迁移校验聚合耗时稳定在 50ms 预算内（高频调用单次 < 0.5ms）。"""
    path = ".agents/quench_stack.yaml"
    raw_cfg = {
        "project_name": "bench_test",
        "config_version": 1,
        "audit_gate": {
            "on_missing_record": "block",
            "on_degraded": "warn",
            "on_internal_error": "allow",
        }
    }

    # 预热
    is_protected_config_path(path)
    migrate_and_validate(raw_cfg)

    # 连续执行 100 次综合防护判断
    start = time.perf_counter()
    for _ in range(100):
        is_protected_config_path(path)
        migrate_and_validate(raw_cfg)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # 100 次调用的总耗时必须远低于 50ms（平均每次 < 0.5ms）
    assert elapsed_ms < 50.0, f"100 次聚合防护耗时 {elapsed_ms:.2f}ms 超过 50ms 预算"


def test_retired_dead_fields_safely_ignored():
    """断言：退役死字段 (freshness_anchor, future_skew_policy) 安全忽略，不影响加载，亦不挂载于对象上。"""
    raw = {
        "project_name": "test_retired",
        "config_version": 1,
        "audit_gate": {
            "freshness_anchor": "recency_only",
            "future_skew_policy": "timestamp_invalid",
            "on_degraded": "warn",
        },
    }
    cfg, faults = migrate_and_validate(raw)
    assert faults == []
    assert not hasattr(cfg.audit_gate, "freshness_anchor")
    assert not hasattr(cfg.audit_gate, "future_skew_policy")
    assert cfg.audit_gate.on_degraded == "warn"


def test_alias_deprecation_warning():
    """断言：声明 tail_window_exhausted_policy 别名时，在解析期发出包含迁移指引的 DeprecationWarning。"""
    with pytest.deprecated_call(match="tail_window_exhausted_policy"):
        p = AuditGatePolicy(tail_window_exhausted_policy="warn")
    assert p.tail_window_exhausted_policy == "warn"

    # 未声明别名时不发警告
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        p_clean = AuditGatePolicy()
        assert p_clean.tail_window_exhausted_policy is None
