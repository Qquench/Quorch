# -*- coding: utf-8 -*-
"""Unit tests for guarded task document writer, partition roundtrip, and MCP in-place revision loop.

Tests all boundary defenses:
- N3: Lossless partition identity (preamble + Σblocks + epilogue == text)
- BLK-1: Status smuggling defense (new tasks must be EDITABLE_STATES)
- Invariant transitions (existing task statuses cannot be altered via writer)
- Non-editable task mutation and deletion defenses
- Mode semantics: append, overwrite, upsert
- Atomic tempfile + fsync + os.replace crash-safety
- BOM and CRLF preservation
- Path containment in docs/dev_tasks
- Lock timeout safety
- FastMCP tool surface preservation (16 tools)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Mapping
import pytest
import yaml

from task_status import (
    STATUS_PENDING,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_SKIPPED,
    STATUS_REWORK,
    STATUS_UNKNOWN,
)
from task_writer import (
    EDITABLE_STATES,
    RawTaskBlock,
    TaskDocument,
    split_task_document,
    compose_task_document,
    write_task_file_guarded,
    InvalidTransitionError,
    NonEditableTaskMutatedError,
    NonEditableTaskMissingError,
    DuplicateTaskIdError,
    StatusSmugglingError,
    StatusManifestMismatchError,
    TaskFileLockTimeoutError,
    PersistTargetRequiredError,
    TaskNotFoundError,
)
from path_guard import PathTraversalError
from tool_surface_constants import TOOL_COUNT, EXPECTED_TOOL_NAMES
from hooks.file_scope_guard import check_task_status_guard
import server
from server import (
    dev_tasks_propose,
    dev_tasks_refine_spec,
    dev_tasks_status,
)


@pytest.fixture
def mock_workspace():
    temp_dir = tempfile.mkdtemp(prefix="quench_writer_test_ws_")
    agents_dir = os.path.join(temp_dir, ".agents")
    os.makedirs(agents_dir, exist_ok=True)
    dev_tasks_dir = os.path.join(temp_dir, "docs", "dev_tasks")
    os.makedirs(dev_tasks_dir, exist_ok=True)

    config_data = {
        "project_name": "WriterTestProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "changelog_path": "CHANGELOG.md",
        "test_dir": "tests",
        "test_runner": "pytest",
    }
    with open(os.path.join(agents_dir, "quench_stack.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    yield temp_dir
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


SAMPLE_VALID_TASK_1 = {
    "id": "1.1",
    "title": "任务一",
    "status": STATUS_PENDING,
    "affected_files": ["[MODIFY] src/app.py"],
    "root_cause_and_goal": "根因目标说明。",
    "type_contracts": "class App: ...",
    "steps": ["1. 第一步", "2. 第二步"],
    "defensive_checks": ["- 边界检查 A"],
    "dod_commands": ["pytest tests/test_app.py"],
}

SAMPLE_VALID_TASK_2 = {
    "id": "1.2",
    "title": "任务二",
    "status": STATUS_PENDING,
    "affected_files": ["[NEW] src/util.py"],
    "root_cause_and_goal": "新增工具类。",
    "type_contracts": "def helper(): ...",
    "steps": ["1. 编写代码", "2. 测试验证"],
    "defensive_checks": ["- 防御检查 B"],
    "dod_commands": ["pytest tests/test_util.py"],
}


# ==============================================================================
# 1. N3: Lossless Partition Roundtrip Identity
# ==============================================================================

def test_split_compose_roundtrip_identity():
    """Arbitrary valid task document split and compose must be byte-for-byte identical."""
    doc_text = (
        "# 2026-10-20 Sample / 示例任务\n\n"
        "> Guidelines blockquote\n"
        "> More guidelines\n\n"
        "---\n\n"
        "### 任务 1.1 ⬜ 待确认 — 第一项任务\n\n"
        "#### 【涉及文件】\n"
        "```\n"
        "[MODIFY] file_a.py\n"
        "```\n\n"
        "#### 【分步改造指引】\n"
        "1. 步骤一\n"
        "```bash\n"
        "echo '### this is inside a code fence and must NOT be parsed as header'\n"
        "```\n\n"
        "---\n\n"
        "> > Nested blockquote with ### 任务 9.9 ⬜ 待确认 should NOT be a header\n\n"
        "### 任务 1.2 ✅ 已确认 — 第二项任务\n\n"
        "#### 【涉及文件】\n"
        "```\n"
        "[NEW] file_b.py\n"
        "```\n\n"
        "---\n\n"
        "## Epilogue Notes\n"
        "Trailing text at the end of document.\n"
    )

    doc = split_task_document(doc_text)
    assert len(doc.blocks) == 2
    assert doc.blocks[0].task_id == "1.1"
    assert doc.blocks[0].status == STATUS_PENDING
    assert doc.blocks[1].task_id == "1.2"
    assert doc.blocks[1].status == STATUS_CONFIRMED

    # Slice identity
    for b in doc.blocks:
        assert doc_text[b.start_offset:b.end_offset] == b.raw_text

    # Recomposed identity
    recomposed = compose_task_document(doc, {}, ())
    assert recomposed == doc_text

    # Empty document test
    empty_doc = split_task_document("")
    assert empty_doc.preamble == ""
    assert len(empty_doc.blocks) == 0
    assert empty_doc.epilogue == ""
    assert compose_task_document(empty_doc, {}, ()) == ""


# ==============================================================================
# 2. Append Mode: New Task Creation & Duplicate ID Defense
# ==============================================================================

def test_append_new_pending_task(mock_workspace):
    """append mode adds new task while keeping preamble and prior tasks verbatim unchanged."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    # Initial proposal with Task 1.1
    res1 = write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1], mode="append")
    assert res1["ok"] is True
    assert res1["written"] == ["1.1"]

    abs_path = os.path.join(ws, "docs", "dev_tasks", task_file)
    with open(abs_path, "r", encoding="utf-8") as f:
        content_after_1 = f.read()

    # Append Task 1.2
    res2 = write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_2], mode="append")
    assert res2["ok"] is True
    assert res2["written"] == ["1.2"]

    with open(abs_path, "r", encoding="utf-8") as f:
        content_after_2 = f.read()

    doc2 = split_task_document(content_after_2)
    assert len(doc2.blocks) == 2
    assert doc2.blocks[0].task_id == "1.1"
    assert doc2.blocks[1].task_id == "1.2"
    # Task 1.1 block text must be exactly preserved
    assert doc2.blocks[0].raw_text in content_after_1


def test_append_duplicate_task_id_raises(mock_workspace):
    """append mode encountering duplicate task_id raises DuplicateTaskIdError, preserving file hash."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1], mode="append")
    abs_path = os.path.join(ws, "docs", "dev_tasks", task_file)
    with open(abs_path, "rb") as f:
        initial_hash = hashlib.sha256(f.read()).hexdigest()

    # Attempt to append duplicate task 1.1
    with pytest.raises(DuplicateTaskIdError) as exc_info:
        write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1], mode="append")

    assert "1.1" in str(exc_info.value)

    # File hash must be untouched
    with open(abs_path, "rb") as f:
        final_hash = hashlib.sha256(f.read()).hexdigest()
    assert initial_hash == final_hash


# ==============================================================================
# 3. Status Smuggling Defense (BLK-1) & Invariant Transitions
# ==============================================================================

def test_overwrite_status_smuggling_blocked(mock_workspace):
    """Writing a new task with Confirmed or In Progress status raises StatusSmugglingError."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    # New file proposal with CONFIRMED status -> BLOCKED
    smuggle_task = dict(SAMPLE_VALID_TASK_1)
    smuggle_task["status"] = STATUS_CONFIRMED

    with pytest.raises(StatusSmugglingError) as exc_info:
        write_task_file_guarded(ws, task_file, [smuggle_task], mode="append")
    assert "non-editable status" in str(exc_info.value)

    # Existing file proposal with newly smuggled task -> BLOCKED
    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1], mode="append")

    smuggle_task_2 = dict(SAMPLE_VALID_TASK_2)
    smuggle_task_2["status"] = STATUS_IN_PROGRESS

    with pytest.raises(StatusSmugglingError) as exc_info2:
        write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1, smuggle_task_2], mode="overwrite")
    assert "non-editable status" in str(exc_info2.value)


def test_overwrite_invalid_transition_blocked(mock_workspace):
    """Altering existing task status via writer raises InvalidTransitionError."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1], mode="append")

    # Attempt to overwrite Task 1.1 changing status to IN_PROGRESS
    mutated_status_task = dict(SAMPLE_VALID_TASK_1)
    mutated_status_task["status"] = STATUS_IN_PROGRESS

    with pytest.raises(InvalidTransitionError) as exc_info:
        write_task_file_guarded(ws, task_file, [mutated_status_task], mode="overwrite")
    assert "Invalid status modification" in str(exc_info.value)


# ==============================================================================
# 4. Non-Editable Task Protection: Mutation and Deletion Defenses
# ==============================================================================

def test_overwrite_non_editable_task_mutated_blocked(mock_workspace):
    """Mutating non-editable task body raises NonEditableTaskMutatedError; untouched reuses original slice."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1, SAMPLE_VALID_TASK_2], mode="append")

    # Manually transition 1.1 to CONFIRMED on disk to simulate confirmed state
    abs_path = os.path.join(ws, "docs", "dev_tasks", task_file)
    with open(abs_path, "r", encoding="utf-8") as f:
        text = f.read()
    text = text.replace("### 任务 1.1 ⬜ 待确认", "### 任务 1.1 ✅ 已确认")
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(text)

    # 1. Attempt to mutate Task 1.1 steps during overwrite -> BLOCKED
    mutated_task_1 = dict(SAMPLE_VALID_TASK_1)
    mutated_task_1["status"] = STATUS_CONFIRMED
    mutated_task_1["steps"] = ["1. 恶意篡改已确认任务步骤"]

    with pytest.raises(NonEditableTaskMutatedError) as exc_info:
        write_task_file_guarded(ws, task_file, [mutated_task_1, SAMPLE_VALID_TASK_2], mode="overwrite")
    assert "1.1" in str(exc_info.value)

    # 2. When non-editable task is passed untouched, overwrite succeeds and reuses slice byte-for-byte
    untouched_task_1 = dict(SAMPLE_VALID_TASK_1)
    untouched_task_1["status"] = STATUS_CONFIRMED

    refined_task_2 = dict(SAMPLE_VALID_TASK_2)
    refined_task_2["steps"] = ["1. 新的合法步骤", "2. 第二步"]

    res = write_task_file_guarded(ws, task_file, [untouched_task_1, refined_task_2], mode="overwrite")
    assert res["ok"] is True
    assert "1.2" in res["written"]

    with open(abs_path, "r", encoding="utf-8") as f:
        new_text = f.read()
    new_doc = split_task_document(new_text)
    assert new_doc.blocks[0].status == STATUS_CONFIRMED
    assert "恶意篡改" not in new_text
    assert "新的合法步骤" in new_text


def test_overwrite_non_editable_task_missing_blocked(mock_workspace):
    """Omitting an existing non-editable task in overwrite raises NonEditableTaskMissingError."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1, SAMPLE_VALID_TASK_2], mode="append")

    abs_path = os.path.join(ws, "docs", "dev_tasks", task_file)
    with open(abs_path, "r", encoding="utf-8") as f:
        text = f.read()
    text = text.replace("### 任务 1.1 ⬜ 待确认", "### 任务 1.1 ✅ 已确认")
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(text)

    # Overwrite payload omits Task 1.1 entirely
    with pytest.raises(NonEditableTaskMissingError) as exc_info:
        write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_2], mode="overwrite")
    assert "1.1" in str(exc_info.value)


# ==============================================================================
# 5. Upsert Mode Semantics
# ==============================================================================

def test_upsert_editable_task_updated(mock_workspace):
    """upsert updates editable task block and appends new task, leaving other blocks identical."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1, SAMPLE_VALID_TASK_2], mode="append")

    abs_path = os.path.join(ws, "docs", "dev_tasks", task_file)
    with open(abs_path, "r", encoding="utf-8") as f:
        orig_doc = split_task_document(f.read())
    orig_task_2_raw = orig_doc.blocks[1].raw_text

    # Update Task 1.1 via upsert
    updated_1 = dict(SAMPLE_VALID_TASK_1)
    updated_1["root_cause_and_goal"] = "更新后的根因与目标。"

    res = write_task_file_guarded(ws, task_file, [updated_1], mode="upsert")
    assert res["ok"] is True
    assert res["written"] == ["1.1"]

    with open(abs_path, "r", encoding="utf-8") as f:
        new_doc = split_task_document(f.read())

    assert "更新后的根因与目标" in new_doc.blocks[0].raw_text
    # Task 1.2 raw_text must be 100% byte-for-byte identical
    assert new_doc.blocks[1].raw_text == orig_task_2_raw


def test_upsert_non_editable_task_skipped(mock_workspace):
    """upsert targeting a non-editable task skips it into skipped list without error."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1], mode="append")

    abs_path = os.path.join(ws, "docs", "dev_tasks", task_file)
    with open(abs_path, "r", encoding="utf-8") as f:
        text = f.read()
    text = text.replace("### 任务 1.1 ⬜ 待确认", "### 任务 1.1 ✔️ 已完成")
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(text)

    # Attempt to upsert Task 1.1
    updated_1 = dict(SAMPLE_VALID_TASK_1)
    updated_1["root_cause_and_goal"] = "尝试修改已完成任务"

    res = write_task_file_guarded(ws, task_file, [updated_1], mode="upsert")
    assert res["ok"] is True
    assert res["written"] == []
    assert len(res["skipped"]) == 1
    assert res["skipped"][0]["id"] == "1.1"
    assert res["skipped"][0]["reason"] == "non_editable"

    # Verify disk content is untouched
    with open(abs_path, "r", encoding="utf-8") as f:
        assert "尝试修改已完成任务" not in f.read()


# ==============================================================================
# 6. refine_spec Parameter Validation & Async Thread Safety
# ==============================================================================

@pytest.mark.anyio
async def test_refine_spec_persist_target_required(mock_workspace):
    """refine_spec with persist=True and task_file=None raises PersistTargetRequiredError."""
    ws = mock_workspace

    with pytest.raises(PersistTargetRequiredError) as exc_info:
        await dev_tasks_refine_spec(
            workspace_root=ws,
            draft_task=SAMPLE_VALID_TASK_1,
            persist=True,
            task_file=None,
        )
    assert "task_file must be specified" in str(exc_info.value)


@pytest.mark.anyio
async def test_refine_spec_persist_success_async_thread(mock_workspace):
    """refine_spec with persist=True persists updates without blocking the event loop."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    # Create task file with Task 1.1
    dev_tasks_propose(ws, task_file, [SAMPLE_VALID_TASK_1], mode="append")

    # Run refine_spec with concurrent ticker to verify non-blocking event loop
    ticker_count = 0
    ticker_running = True

    async def ticker():
        nonlocal ticker_count
        while ticker_running:
            ticker_count += 1
            await asyncio.sleep(0.01)

    tick_task = asyncio.create_task(ticker())

    draft = dict(SAMPLE_VALID_TASK_1)
    draft["title"] = "强化后的任务一标题"
    draft["root_cause_and_goal"] = "审查引擎强化后的缺陷根因与目标。"

    refined = await dev_tasks_refine_spec(
        workspace_root=ws,
        draft_task=draft,
        persist=True,
        task_file=task_file,
    )

    ticker_running = False
    await tick_task

    assert refined.get("refined") is True
    assert ticker_count > 0

    # Verify disk persistence
    abs_path = os.path.join(ws, "docs", "dev_tasks", task_file)
    with open(abs_path, "r", encoding="utf-8") as f:
        saved_text = f.read()
    assert "审查引擎强化后的缺陷根因与目标" in saved_text


# ==============================================================================
# 7. Manifest Snapshot Consistency & Availability
# ==============================================================================

def test_manifest_mismatch_raises(mock_workspace):
    """Contradiction between markdown and manifest raises StatusManifestMismatchError."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1], mode="append")

    # Provide manifest snapshot where Task 1.1 is recorded as COMPLETED,
    # but markdown has it as PENDING
    snapshot = {"1.1": STATUS_COMPLETED}

    with pytest.raises(StatusManifestMismatchError) as exc_info:
        write_task_file_guarded(
            ws,
            task_file,
            [SAMPLE_VALID_TASK_1],
            mode="upsert",
            manifest_snapshot=snapshot,
        )
    assert "Manifest status mismatch for task '1.1'" in str(exc_info.value)


# ==============================================================================
# 8. Atomic Write & Fault Tolerance
# ==============================================================================

def test_atomic_write_failure_preserves_file(mock_workspace, monkeypatch):
    """Crash/failure during os.replace leaves original file completely intact."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1], mode="append")

    abs_path = os.path.join(ws, "docs", "dev_tasks", task_file)
    with open(abs_path, "rb") as f:
        orig_bytes = f.read()
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()

    # Monkeypatch os.replace to simulate power loss or disk failure
    def faulty_replace(src, dst):
        raise OSError("Simulated atomic replace failure: device I/O error")

    monkeypatch.setattr(os, "replace", faulty_replace)

    with pytest.raises(OSError) as exc_info:
        write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_2], mode="append")
    assert "Simulated atomic replace failure" in str(exc_info.value)

    # Assert original file content and sha256 are unchanged
    with open(abs_path, "rb") as f:
        curr_bytes = f.read()
    assert hashlib.sha256(curr_bytes).hexdigest() == orig_hash
    assert curr_bytes == orig_bytes


# ==============================================================================
# 9. Format Preservation: BOM and CRLF
# ==============================================================================

def test_preserves_crlf_and_bom(mock_workspace):
    """Task writer must preserve existing UTF-8 BOM and Windows CRLF line endings."""
    ws = mock_workspace
    task_file = "2026-10-20_crlf_bom.md"
    dev_tasks_dir = os.path.join(ws, "docs", "dev_tasks")
    abs_path = os.path.join(dev_tasks_dir, task_file)

    initial_content = (
        "\ufeff# 2026-10-20 CRLF BOM Test\r\n\r\n"
        "### 任务 1.1 ⬜ 待确认 — 测试\r\n\r\n"
        "#### 【涉及文件】\r\n"
        "```\r\n"
        "[MODIFY] file.py\r\n"
        "```\r\n\r\n"
        "#### 【分步改造指引】\r\n"
        "1. 步骤一\r\n\r\n"
        "---\r\n"
    )

    with open(abs_path, "wb") as f:
        f.write(initial_content.encode("utf-8"))

    # Upsert with new task
    res = write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_2], mode="upsert")
    assert res["ok"] is True

    with open(abs_path, "rb") as f:
        raw_bytes = f.read()

    # Assert BOM is preserved
    assert raw_bytes.startswith(b"\xef\xbb\xbf")

    # Assert CRLF is preserved across file
    raw_str = raw_bytes.decode("utf-8")
    assert "\r\n" in raw_str
    # Check that there are no bare LF line endings without CR
    stripped = raw_str.replace("\r\n", "")
    assert "\n" not in stripped


# ==============================================================================
# 10. Path Traversal & Lock Timeout Defenses
# ==============================================================================

def test_path_traversal_blocked(mock_workspace):
    """Paths escaping docs/dev_tasks are blocked fail-closed."""
    ws = mock_workspace

    with pytest.raises(PathTraversalError):
        write_task_file_guarded(ws, "../escape.md", [SAMPLE_VALID_TASK_1])

    with pytest.raises(PathTraversalError):
        write_task_file_guarded(ws, "src/evil.md", [SAMPLE_VALID_TASK_1])

    with pytest.raises(ValueError):
        write_task_file_guarded(ws, "docs/dev_tasks/bad_ext.txt", [SAMPLE_VALID_TASK_1])


def test_lock_timeout_raises(mock_workspace):
    """FileLock timeout raises TaskFileLockTimeoutError within bounded time."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"
    dev_tasks_dir = os.path.join(ws, "docs", "dev_tasks")
    abs_path = os.path.join(dev_tasks_dir, task_file)
    lock_path = abs_path + ".lock"

    import filelock
    holder_lock = filelock.FileLock(lock_path)
    holder_lock.acquire()

    try:
        start_t = time.perf_counter()
        with pytest.raises(TaskFileLockTimeoutError) as exc_info:
            write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1], lock_timeout_s=0.2)
        elapsed = time.perf_counter() - start_t
        assert elapsed < 1.0
        assert "timed out" in str(exc_info.value)
    finally:
        holder_lock.release()


# ==============================================================================
# 11. Hook Guard Roundtrip Verification
# ==============================================================================

def test_hook_guard_roundtrip_allow(mock_workspace):
    """Writer output must be evaluated as 'allow' by check_task_status_guard."""
    ws = mock_workspace
    task_file = "2026-10-20_test.md"

    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_1], mode="append")

    abs_path = os.path.join(ws, "docs", "dev_tasks", task_file)
    with open(abs_path, "r", encoding="utf-8") as f:
        old_content = f.read()

    # Append Task 1.2
    write_task_file_guarded(ws, task_file, [SAMPLE_VALID_TASK_2], mode="append")

    with open(abs_path, "r", encoding="utf-8") as f:
        new_content = f.read()

    res = check_task_status_guard(
        target_file=abs_path,
        tool_name="write_to_file",
        args={"CodeContent": new_content},
    )
    assert res is None


# ==============================================================================
# 12. FastMCP Tool Surface Preservation (16 Tools)
# ==============================================================================

def test_tool_count_preserved_16():
    """TOOL_COUNT remains exactly 16 and registered tool names match SSOT."""
    assert TOOL_COUNT == 16
    assert len(EXPECTED_TOOL_NAMES) == 16

    # Load IDE schema snapshot
    schema_path = Path(__file__).resolve().parents[4] / "docs" / "architecture" / "ide_tool_schemas.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        snapshot = json.load(f)

    tool_names = {k for k in snapshot.keys() if not k.startswith("_")}
    assert len(tool_names) == 16
    assert tool_names == EXPECTED_TOOL_NAMES

    # Verify propose tool has mode parameter
    propose_tool = snapshot["dev_tasks_propose"]
    prop_props = propose_tool["parameters"]["properties"]
    assert "mode" in prop_props
    assert prop_props["mode"]["default"] == "append"

    # Verify refine_spec tool has persist and task_file parameters
    refine_tool = snapshot["dev_tasks_refine_spec"]
    ref_props = refine_tool["parameters"]["properties"]
    assert "persist" in ref_props
    assert ref_props["persist"]["default"] is False
    assert "task_file" in ref_props
