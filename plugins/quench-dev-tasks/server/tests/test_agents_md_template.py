"""
test_agents_md_template.py
──────────────────────────
Unit tests for AGENTS.md template generation:
  1. Template file exists and respects the ≤ 120-line budget.
  2. Template contains all 8 core discipline items.
  3. generate_agents_md() produces a correctly substituted AGENTS.md.
  4. generate_agents_md() is idempotent (skip on second call without --force).
  5. generate_agents_md(force=True) overwrites existing file.
  6. AGENTS.md generated in real project root (quorch itself) meets constraints.
  7. Missing template file degrades gracefully (no exception, no file written).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
PLUGIN_DIR = os.path.dirname(SERVER_DIR)
SCRIPTS_DIR = os.path.join(PLUGIN_DIR, "scripts")
TEMPLATES_DIR = os.path.join(PLUGIN_DIR, "templates")
TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "AGENTS.md")

# Root of the quorch repository itself:
#   TESTS_DIR  = quorch/plugins/quench-dev-tasks/server/tests
#   SERVER_DIR = quorch/plugins/quench-dev-tasks/server
#   PLUGIN_DIR = quorch/plugins/quench-dev-tasks
#   PLUGINS_DIR = quorch/plugins
#   QUORCH_ROOT = quorch/
PLUGINS_DIR = os.path.dirname(PLUGIN_DIR)
QUORCH_ROOT = os.path.dirname(PLUGINS_DIR)
# AGENTS.md that lives at the quorch repo root (generated manually)
QUORCH_AGENTS_MD = os.path.join(QUORCH_ROOT, "AGENTS.md")


# ---------------------------------------------------------------------------
# Helper: import generate_agents_md without executing __main__
# ---------------------------------------------------------------------------
def _import_init_project() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "init_project",
        os.path.join(SCRIPTS_DIR, "init_project.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# 1. Template file budget & existence
# ---------------------------------------------------------------------------
def test_template_exists():
    assert os.path.isfile(TEMPLATE_PATH), (
        f"AGENTS.md template missing at: {TEMPLATE_PATH}"
    )


def test_template_line_count_within_budget():
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) <= 120, (
        f"AGENTS.md template has {len(lines)} lines — exceeds 120-line token budget"
    )


# ---------------------------------------------------------------------------
# 2. Template contains all 8 hard-stop discipline markers
# ---------------------------------------------------------------------------
REQUIRED_MARKERS = [
    "INV-1",
    "INV-2",
    "INV-3",
    "INV-4",
    "INV-5",
    "INV-6",
    "INV-7",
    "INV-8",
]


@pytest.mark.parametrize("marker", REQUIRED_MARKERS)
def test_template_contains_invariant_marker(marker):
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        content = f.read()
    assert marker in content, (
        f"AGENTS.md template is missing required invariant: {marker}"
    )


# ---------------------------------------------------------------------------
# 3. generate_agents_md produces correctly substituted output
# ---------------------------------------------------------------------------
def test_generate_agents_md_substitutes_project_name(tmp_path):
    mod = _import_init_project()
    project_name = "MyAwesomeProject"
    mod.generate_agents_md(str(tmp_path), project_name)

    out_path = tmp_path / "AGENTS.md"
    assert out_path.exists(), "AGENTS.md was not created"

    content = out_path.read_text(encoding="utf-8")
    assert project_name in content, (
        "{{PROJECT_NAME}} placeholder was not substituted in generated AGENTS.md"
    )
    assert "{{PROJECT_NAME}}" not in content, (
        "Unreplaced {{PROJECT_NAME}} placeholder remains in generated AGENTS.md"
    )


def test_generate_agents_md_line_count_within_budget(tmp_path):
    mod = _import_init_project()
    mod.generate_agents_md(str(tmp_path), "TestProject")

    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    line_count = content.count("\n") + 1
    assert line_count <= 120, (
        f"Generated AGENTS.md has {line_count} lines — exceeds 120-line budget"
    )


# ---------------------------------------------------------------------------
# 4. Idempotency: second call without force is a no-op
# ---------------------------------------------------------------------------
def test_generate_agents_md_idempotent(tmp_path):
    mod = _import_init_project()
    mod.generate_agents_md(str(tmp_path), "ProjectA")

    first_content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    # Second call — should skip (file already exists)
    mod.generate_agents_md(str(tmp_path), "ProjectB")
    second_content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    assert first_content == second_content, (
        "generate_agents_md should be idempotent without force=True"
    )


# ---------------------------------------------------------------------------
# 5. force=True overwrites existing file
# ---------------------------------------------------------------------------
def test_generate_agents_md_force_overwrites(tmp_path):
    mod = _import_init_project()
    mod.generate_agents_md(str(tmp_path), "ProjectA")

    mod.generate_agents_md(str(tmp_path), "ProjectB", force=True)
    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    assert "ProjectB" in content, (
        "force=True should overwrite AGENTS.md with new project name"
    )


# ---------------------------------------------------------------------------
# 6. The quorch root AGENTS.md (hand-crafted) meets budget & contains INV markers
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not os.path.isfile(QUORCH_AGENTS_MD),
    reason="quorch root AGENTS.md not yet generated",
)
def test_quorch_root_agents_md_line_count():
    with open(QUORCH_AGENTS_MD, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) <= 120, (
        f"quorch/AGENTS.md has {len(lines)} lines — exceeds 120-line budget"
    )


@pytest.mark.skipif(
    not os.path.isfile(QUORCH_AGENTS_MD),
    reason="quorch root AGENTS.md not yet generated",
)
@pytest.mark.parametrize("marker", REQUIRED_MARKERS)
def test_quorch_root_agents_md_contains_invariant(marker):
    with open(QUORCH_AGENTS_MD, encoding="utf-8") as f:
        content = f.read()
    assert marker in content, (
        f"quorch/AGENTS.md is missing required invariant: {marker}"
    )


# ---------------------------------------------------------------------------
# 7. Missing template degrades gracefully
# ---------------------------------------------------------------------------
def test_generate_agents_md_missing_template_degrades(tmp_path, monkeypatch):
    """When template file does not exist, no exception is raised and no file is written."""
    mod = _import_init_project()

    # Point plugin_dir to a location with no templates/AGENTS.md
    empty_plugin = tmp_path / "fake_plugin"
    (empty_plugin / "templates").mkdir(parents=True, exist_ok=True)
    # Do NOT create AGENTS.md template

    import unittest.mock as mock

    # Patch os.path.dirname chain so the function resolves to our empty_plugin
    original_abspath = os.path.abspath

    def patched_abspath(p):
        if "init_project.py" in str(p):
            return str(empty_plugin / "scripts" / "init_project.py")
        return original_abspath(p)

    target_agents_md = tmp_path / "AGENTS.md"

    with mock.patch.object(mod.os.path, "abspath", side_effect=patched_abspath):
        # Should not raise
        mod.generate_agents_md(str(tmp_path), "TestProject")

    # File must NOT be created since template was missing
    assert not target_agents_md.exists(), (
        "AGENTS.md should not be created when template is missing"
    )
