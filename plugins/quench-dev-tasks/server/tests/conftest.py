"""Pytest conftest hook for centralized test tiering."""

from __future__ import annotations

import os
from typing import Final
import pytest

# Final constant tuple of relative file basenames for Tier-1 Fast Gate (<=5s budget)
TIER1_TARGET_REL_FILES: Final[tuple[str, ...]] = (
    "test_python_floor_discipline.py",
    "test_touch_outcome_no_truthiness.py",
    "test_import_mode_contract.py",
    "test_schema_validator.py",
    "test_agents_md_sync.py",
    "test_anti_roleplay_discipline_contract.py",
    "test_forgery_prevention_contract.py",
    "test_ide_schema_export.py",
    "test_tool_surface_contract.py",
    "test_spec_param_defaults_contract.py",
    "test_snapshot_drift_gate_contract.py",
    "test_missing_sentinel_singleton.py",
    "test_file_scope_guard_status.py",
)


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: heavy cross-platform CLI integration cases")
    config.addinivalue_line("markers", "tier1_fast: fast gate Tier-1 tests")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Inject tier1_fast marker into items belonging to explicit white-listed modules."""
    tier1_marker = pytest.mark.tier1_fast
    for item in items:
        item_path_str = str(getattr(item, "path", getattr(item, "fspath", "")))
        basename = os.path.basename(item_path_str)
        if basename in TIER1_TARGET_REL_FILES:
            item.add_marker(tier1_marker)


@pytest.fixture(autouse=True)
def _isolate_user_global_config(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """自动隔离用户全局配置 (~/.quorch/config.yaml)，确保本地开发与 CI 单测执行环境确定性。"""
    dummy_path = tmp_path_factory.mktemp("no_global_config") / "__non_existent_global_config__.yaml"
    monkeypatch.setenv("QUORCH_GLOBAL_CONFIG", str(dummy_path))
    monkeypatch.delenv("QUORCH_DISABLE_GLOBAL_CONFIG", raising=False)

