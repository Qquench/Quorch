"""Pytest conftest hook for centralized test tiering."""

from __future__ import annotations

import os
from pathlib import Path
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
    config.addinivalue_line("markers", "concurrent_moat: heavy concurrency and CAS race moat tests")
    config.addinivalue_line("markers", "heavy: heavyweight integration or stress tests")


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Skip collecting non-Tier-1 test modules when running `-m tier1_fast` to stay within cold-start budget."""
    markexpr = (getattr(config.option, "markexpr", "") or "").strip()
    if markexpr == "tier1_fast" and collection_path.suffix == ".py" and collection_path.name.startswith("test_"):
        if collection_path.name not in TIER1_TARGET_REL_FILES:
            try:
                if b"mark.tier1_fast" in collection_path.read_bytes():
                    return None
            except OSError:
                return None
            return True
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Inject tier1_fast marker into items belonging to explicit white-listed modules."""
    tier1_marker = pytest.mark.tier1_fast
    for item in items:
        item_path_str = str(getattr(item, "path", getattr(item, "fspath", "")))
        basename = os.path.basename(item_path_str)
        if basename in TIER1_TARGET_REL_FILES:
            item.add_marker(tier1_marker)


@pytest.fixture(scope="session")
def _global_config_isolation_sentinel(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Session-scoped non-existent sentinel path avoiding per-test mktemp disk I/O."""
    return str(tmp_path_factory.mktemp("no_global_config") / "__non_existent_global_config__.yaml")


@pytest.fixture(autouse=True)
def _isolate_user_global_config(monkeypatch: pytest.MonkeyPatch, _global_config_isolation_sentinel: str) -> None:
    """自动隔离用户全局配置 (~/.quorch/config.yaml) 及真仓本地私有覆盖，确保单测确定性。"""
    monkeypatch.setenv("QUORCH_GLOBAL_CONFIG", _global_config_isolation_sentinel)
    monkeypatch.delenv("QUORCH_DISABLE_GLOBAL_CONFIG", raising=False)
    monkeypatch.setenv("QUORCH_IGNORE_REPO_ROOT_LOCAL_OVERRIDE", "1")

