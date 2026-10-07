"""Unit tests for test tiering gate contracts, invariant isolation, and fail-closed behaviors."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts dir is accessible for importing check_test_tiering_invariants
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_test_tiering_invariants as tiering_gate  # noqa: E402


def test_tiering_gate_clean_repo_passes():
    """Verify that the active clean repository passes all test tiering invariants."""
    ok, violations = tiering_gate.check_tiering_invariants(REPO_ROOT)
    assert ok is True, f"Expected clean check, but got violations: {violations}"
    assert len(violations) == 0


def test_main_cli_returns_zero_on_check():
    """Verify check_test_tiering_invariants CLI returns 0 on clean repository."""
    code = tiering_gate.main(["--repo-root", str(REPO_ROOT), "--check"])
    assert code == 0


def test_concurrency_hard_gate_isolation_ground_truth():
    """Verify that ground-truth collections strictly satisfy H ∩ Tier-1 = ∅."""
    tier1_nodes = tiering_gate.collect_selection(REPO_ROOT, marker=tiering_gate.TIER1_MARKER)
    h_nodes = tiering_gate.collect_selection(REPO_ROOT, expr=tiering_gate.CONCURRENCY_SELECTOR_EXPR)
    assert len(tier1_nodes) > 0, "Tier-1 collection must be non-empty"
    assert len(h_nodes) > 0, "Concurrency collection H must be non-empty"

    intersection = tier1_nodes & h_nodes
    assert intersection == frozenset(), f"H ∩ Tier-1 must be empty, but matched: {intersection}"


def test_env_sanitization_strips_disruptive_keys():
    """Verify that sanitized_env scrubs PYTEST_* keys and xdist prefixes."""
    dirty_env = {
        "PATH": "C:\\Windows",
        "PYTEST_ADDOPTS": "-m tier1_fast",
        "PYTEST_PLUGINS": "evil_plugin",
        "PYTEST_CURRENT_TEST": "test_foo",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_DEBUG": "1",
        "PYTEST_XDIST_WORKER": "gw0",
        "PYTEST_XDIST_TESTRUNUID": "123",
        "CUSTOM_VAR": "safe_value",
    }
    clean = tiering_gate.sanitized_env(dirty_env)
    assert "CUSTOM_VAR" in clean
    assert "PATH" in clean
    for key in tiering_gate.ENV_SCRUB_KEYS:
        assert key not in clean
    for k in clean:
        assert not any(k.startswith(p) for p in tiering_gate.ENV_SCRUB_PREFIXES)


def test_fail_closed_on_synthetic_concurrency_leak():
    """Synthetic injection: contaminating Tier-1 with an H nodeid must fail-closed."""
    fake_full = frozenset(["test_foo.py::test_a", "test_state_machine.py::test_cas"])
    fake_t1 = frozenset(["test_foo.py::test_a", "test_state_machine.py::test_cas"])
    fake_h = frozenset(["test_state_machine.py::test_cas"])

    with patch.object(
        tiering_gate,
        "collect_selection",
        side_effect=[fake_full, fake_t1, fake_h],
    ):
        ok, violations = tiering_gate.check_tiering_invariants(REPO_ROOT)
        assert ok is False
        assert any("并发不变量硬门禁" in v for v in violations)


def test_fail_closed_on_synthetic_anchor_leak():
    """Synthetic injection: putting anchor test into Tier-1 must fail-closed."""
    fake_full = frozenset(["test_foo.py::test_a", "test_asset_inventory.py::test_check"])
    fake_t1 = frozenset(["test_foo.py::test_a", "test_asset_inventory.py::test_check"])
    fake_h = frozenset(["test_foo.py::test_other"])

    with patch.object(
        tiering_gate,
        "collect_selection",
        side_effect=[fake_full, fake_t1, fake_h],
    ):
        ok, violations = tiering_gate.check_tiering_invariants(REPO_ROOT)
        assert ok is False
        assert any("真仓锚点隔离违规" in v for v in violations)


def test_fail_closed_on_empty_tier1():
    """Synthetic injection: empty Tier-1 must fail-closed."""
    fake_full = frozenset(["test_foo.py::test_a"])
    fake_t1 = frozenset()
    fake_h = frozenset(["test_foo.py::test_a"])

    with patch.object(
        tiering_gate,
        "collect_selection",
        side_effect=[fake_full, fake_t1, fake_h],
    ):
        ok, violations = tiering_gate.check_tiering_invariants(REPO_ROOT)
        assert ok is False
        assert any("Tier-1 collection is empty" in v for v in violations)


def test_no_double_import_identity_r3():
    """R3: Verify pythonpath does not cause split module identities."""
    import manifest
    import state_machine
    import manifest_lease

    assert sys.modules["manifest"] is manifest
    assert sys.modules["state_machine"] is state_machine
    assert sys.modules["manifest_lease"] is manifest_lease


def test_tier1_fast_budget_execution():
    """Verify that running pytest -m tier1_fast executes within budget (<=8s, target <=5s)."""
    t0 = time.monotonic()
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "tier1_fast", "-q"],
        cwd=str(REPO_ROOT),
        env=tiering_gate.sanitized_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    elapsed = time.monotonic() - t0
    assert res.returncode == 0, f"pytest -m tier1_fast failed:\n{res.stderr}\n{res.stdout}"
    assert elapsed <= 8.0, f"Tier-1 budget exceeded: took {elapsed:.2f}s (budget <= 8.0s)"
