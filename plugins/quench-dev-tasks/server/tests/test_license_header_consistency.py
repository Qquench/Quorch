# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
"""Repository-wide Apache-2.0 license consistency and legacy residue regression guard."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]

FORBIDDEN_FRAGMENTS: Final[tuple[bytes, ...]] = tuple(
    frag.lower().encode("ascii")
    for frag in (
        "Mozilla" + " Public License",
        "MPL" + "-2.0",
        "MPL" + "_2.0",
        "MPL" + "--2.0",
        "MPL" + "%202.0",
        "MPL" + " 2.0",
        "MPL" + "2.0",
        "MPLv" + "2",
        "mozilla" + "." + "org",
    )
)

APACHE_SPDX_LINE: Final[str] = "# SPDX-License-Identifier: Apache-2.0"
APACHE_NOTICE_LINE: Final[str] = (
    "# Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0)."
)

# One-time migration snapshot of existing .py modules that originally carried license headers.
# Any future .py file adopting SPDX headers must also be registered here explicitly.
KNOWN_MPL_BEARING_FILES: Final[tuple[str, ...]] = (
    "plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py",
    "plugins/quench-dev-tasks/server/adapters/base_adapter.py",
    "plugins/quench-dev-tasks/server/hooks/file_scope_guard.py",
    "plugins/quench-dev-tasks/server/manifest.py",
    "plugins/quench-dev-tasks/server/manifest_lease.py",
    "plugins/quench-dev-tasks/server/progress_bridge.py",
    "plugins/quench-dev-tasks/server/project_config.py",
    "plugins/quench-dev-tasks/server/reporting.py",
    "plugins/quench-dev-tasks/server/reviewer_jobs.py",
    "plugins/quench-dev-tasks/server/schema_validator.py",
    "plugins/quench-dev-tasks/server/server.py",
    "plugins/quench-dev-tasks/server/state_machine.py",
    "plugins/quench-dev-tasks/server/task_status.py",
    "plugins/quench-dev-tasks/server/workspace_lease.py",
    "plugins/quench-dev-tasks/server/tests/test_audit_gate.py",
    "plugins/quench-dev-tasks/server/tests/test_crashed_worker_ttl_recovery.py",
    "plugins/quench-dev-tasks/server/tests/test_dual_process_cas.py",
    "plugins/quench-dev-tasks/server/tests/test_dual_source_reconcile.py",
    "plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py",
    "plugins/quench-dev-tasks/server/tests/test_global_config_layer.py",
    "plugins/quench-dev-tasks/server/tests/test_heartbeat_renewal.py",
    "plugins/quench-dev-tasks/server/tests/test_import_mode_contract.py",
    "plugins/quench-dev-tasks/server/tests/test_import_topology_acyclic.py",
    "plugins/quench-dev-tasks/server/tests/test_install.py",
    "plugins/quench-dev-tasks/server/tests/test_lease_heartbeat_external.py",
    "plugins/quench-dev-tasks/server/tests/test_lease_takeover_fencing.py",
    "plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py",
    "plugins/quench-dev-tasks/server/tests/test_manifest_lease.py",
    "plugins/quench-dev-tasks/server/tests/test_manifest_reconciliation.py",
    "plugins/quench-dev-tasks/server/tests/test_no_deleted_module_refs.py",
    "plugins/quench-dev-tasks/server/tests/test_observability.py",
    "plugins/quench-dev-tasks/server/tests/test_poll_nonterminal_contract_v2.py",
    "plugins/quench-dev-tasks/server/tests/test_progress_bridge.py",
    "plugins/quench-dev-tasks/server/tests/test_prompt_cache_padding.py",
    "plugins/quench-dev-tasks/server/tests/test_python_floor_discipline.py",
    "plugins/quench-dev-tasks/server/tests/test_reclaim_cas.py",
    "plugins/quench-dev-tasks/server/tests/test_reclaim_cas_lease_probe.py",
    "plugins/quench-dev-tasks/server/tests/test_reporting_render_golden.py",
    "plugins/quench-dev-tasks/server/tests/test_review_attestation_channel.py",
    "plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py",
    "plugins/quench-dev-tasks/server/tests/test_reviewer_jobs_watch.py",
    "plugins/quench-dev-tasks/server/tests/test_server_daemon_launch_canary.py",
    "plugins/quench-dev-tasks/server/tests/test_server_import_smoke.py",
    "plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py",
    "plugins/quench-dev-tasks/server/tests/test_step_adjudication_invariants.py",
    "plugins/quench-dev-tasks/server/tests/test_templates.py",
    "plugins/quench-dev-tasks/server/tests/test_test_duration_gate.py",
    "plugins/quench-dev-tasks/server/tests/test_tool_surface_snapshot.py",
    "plugins/quench-dev-tasks/server/tests/test_touch_outcome_no_truthiness.py",
    "plugins/quench-dev-tasks/server/tests/test_workspace_lease.py",
    "scripts/check_prompt_surface.py",
    "scripts/install.py",
    "scripts/tool_surface_snapshot.py",
)

SELF_REL_PATH: Final[str] = "plugins/quench-dev-tasks/server/tests/test_license_header_consistency.py"
EXPECTED_SPDX_SET: Final[frozenset[str]] = frozenset(KNOWN_MPL_BEARING_FILES) | {SELF_REL_PATH}

PRUNE_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".agents",
        "build",
        "dist",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".idea",
        ".vscode",
        "notes",
        "scratch",
    }
)
PRUNE_REL_PREFIXES: Final[tuple[str, ...]] = (
    "docs/dev_tasks",
    "docs/archive",
    "docs/architecture/archive",
    "docs/roadmap/archive",
)
SCAN_EXCLUDED_REL_PATHS: Final[frozenset[str]] = frozenset(
    {
        "CHANGELOG.md",
        "docs/roadmap/README.md",
    }
)
SCAN_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".py", ".md", ".toml", ".json", ".txt", ".cfg", ".yml", ".yaml", ""}
)
MAX_SCAN_BYTES: Final[int] = 2 * 1024 * 1024


def _require_quench_core_repo() -> None:
    if not (
        (REPO_ROOT / "docs/architecture/README.md").is_file()
        and (REPO_ROOT / ".agents/quench_stack.yaml").is_file()
    ):
        pytest.skip("not Quench core repo")


def _iter_repo_files(suffix_filter: frozenset[str] | None = None) -> list[tuple[str, Path]]:
    collected: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        rel_dir = Path(dirpath).relative_to(REPO_ROOT).as_posix()
        kept_dirs: list[str] = []
        for d in dirnames:
            if d in PRUNE_DIR_NAMES:
                continue
            sub_rel = d if rel_dir == "." else f"{rel_dir}/{d}"
            if d == "archive" and sub_rel.startswith("docs/"):
                continue
            if any(sub_rel == p or sub_rel.startswith(p + "/") for p in PRUNE_REL_PREFIXES):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fn in filenames:
            p = Path(dirpath) / fn
            if suffix_filter is not None and p.suffix not in suffix_filter:
                continue
            rel = p.relative_to(REPO_ROOT).as_posix()
            if rel in SCAN_EXCLUDED_REL_PATHS:
                continue
            collected.append((rel, p))
    return collected


def _normalize_lines(raw: bytes) -> list[str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.replace(b"\r\n", b"\n").decode("utf-8", errors="replace")
    return text.split("\n")


def test_repo_wide_zero_legacy_license_residue() -> None:
    """Repo-wide read-only byte scan asserting zero legacy license residue."""
    _require_quench_core_repo()
    violations: list[str] = []
    for rel, path in _iter_repo_files(SCAN_SUFFIXES):
        try:
            st = path.stat()
            if st.st_size > MAX_SCAN_BYTES:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        lower_raw = raw.lower()
        for frag in FORBIDDEN_FRAGMENTS:
            if frag in lower_raw:
                violations.append(f"{rel}: matched {frag.decode('ascii')}")
    assert violations == [], f"Legacy license residue detected: {violations}"


def test_known_migrated_files_preserve_apache2_header_block() -> None:
    """Every migrated .py file carries the exact 2-line Apache-2.0 header block in lines[:5]."""
    _require_quench_core_repo()
    failures: list[str] = []
    for rel in KNOWN_MPL_BEARING_FILES:
        path = REPO_ROOT / rel
        if not path.is_file():
            failures.append(f"{rel}: missing file")
            continue
        lines = _normalize_lines(path.read_bytes())
        head = lines[:5]
        spdx_indices = [i for i, ln in enumerate(head) if ln == APACHE_SPDX_LINE]
        if len(spdx_indices) != 1:
            failures.append(f"{rel}: expected 1 SPDX line in head[:5], got {spdx_indices}")
            continue
        idx = spdx_indices[0]
        if idx + 1 >= len(head) or head[idx + 1] != APACHE_NOTICE_LINE:
            failures.append(f"{rel}: missing contiguous Apache notice line at index {idx + 1}")
            continue
        for pre in head[:idx]:
            if not (pre.startswith("#!") or "coding" in pre):
                failures.append(f"{rel}: unexpected line before SPDX header: {pre!r}")
                break
        total_spdx = sum(1 for ln in lines if APACHE_SPDX_LINE in ln)
        if total_spdx != 1:
            failures.append(f"{rel}: expected total SPDX count == 1, got {total_spdx}")
    assert failures == [], f"Header block validation failed: {failures}"


def test_spdx_notice_pair_integrity_and_set_equality() -> None:
    """All .py files satisfy has_spdx == has_notice and exact SPDX file-set equality."""
    _require_quench_core_repo()
    files_with_spdx: set[str] = set()
    pair_errors: list[str] = []

    for rel, path in _iter_repo_files(frozenset({".py"})):
        try:
            lines = _normalize_lines(path.read_bytes())
        except OSError:
            continue
        has_spdx = any("SPDX-License-Identifier:" in ln for ln in lines)
        has_notice = any(APACHE_NOTICE_LINE == ln for ln in lines)
        if has_spdx != has_notice:
            pair_errors.append(f"{rel}: has_spdx={has_spdx}, has_notice={has_notice}")
        if has_spdx:
            if APACHE_SPDX_LINE not in lines[:5]:
                pair_errors.append(f"{rel}: non-Apache-2.0 or misplaced SPDX identifier")
            files_with_spdx.add(rel)

    assert pair_errors == [], f"SPDX/notice pair integrity errors: {pair_errors}"
    assert files_with_spdx == EXPECTED_SPDX_SET, (
        f"SPDX set drift: +{sorted(files_with_spdx - EXPECTED_SPDX_SET)} "
        f"-{sorted(EXPECTED_SPDX_SET - files_with_spdx)}"
    )
    assert len(EXPECTED_SPDX_SET) == 54


def test_license_files_full_apache2_text_and_byte_identical() -> None:
    """Root and plugin LICENSE files are byte-identical and contain full Apache-2.0 text."""
    _require_quench_core_repo()
    root_bytes = (REPO_ROOT / "LICENSE").read_bytes()
    plugin_bytes = (REPO_ROOT / "plugins/quench-dev-tasks/LICENSE").read_bytes()

    assert root_bytes == plugin_bytes
    assert hashlib.sha256(root_bytes).hexdigest() == hashlib.sha256(plugin_bytes).hexdigest()
    assert len(root_bytes) > 10000

    text = root_bytes.decode("utf-8")
    for required in (
        "Apache License",
        "Version 2.0, January 2004",
        "http://www.apache.org/licenses/",
        "END OF TERMS AND CONDITIONS",
    ):
        assert required in text


def test_readme_apache2_badges_and_zero_legacy_residue() -> None:
    """English and Chinese READMEs advertise Apache-2.0 and contain zero legacy residue."""
    _require_quench_core_repo()
    positive_variants = ("Apache-2.0", "Apache_2.0", "Apache--2.0")
    for rel in ("README.md", "README_zh.md"):
        raw = (REPO_ROOT / rel).read_bytes()
        text = raw.decode("utf-8")
        assert any(variant in text for variant in positive_variants), f"{rel} missing Apache-2.0 badge/mention"
        lower_raw = raw.lower()
        for frag in FORBIDDEN_FRAGMENTS:
            assert frag not in lower_raw, f"{rel} contains forbidden fragment {frag.decode('ascii')}"
