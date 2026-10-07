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
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Inject tier1_fast marker into items belonging to explicit white-listed modules."""
    tier1_marker = pytest.mark.tier1_fast
    for item in items:
        item_path_str = str(getattr(item, "path", getattr(item, "fspath", "")))
        basename = os.path.basename(item_path_str)
        if basename in TIER1_TARGET_REL_FILES:
            item.add_marker(tier1_marker)
