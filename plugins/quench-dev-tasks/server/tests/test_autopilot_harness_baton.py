"""Unit tests for the pure Autopilot Harness decision engine.

Validates state transition table, candidates-first priority, single-namespace scope,
CAS expect_set_at re-emission, and strict zero-I/O purity.
"""

import builtins
import os
import time
import pytest

from autopilot_harness import (
    compute_next_action,
    compute_batch_overlap_ratio,
    resolve_runner_dispatch_channel,
    TaskStateSnapshot,
    LastEventSnapshot,
    HarnessNextAction,
    DEFAULT_MAX_REVIEW_ROUNDS,
    DEFAULT_MAX_RUNNER_TASKS,
    DEFAULT_BATCH_OVERLAP_THRESHOLD,
)


def test_pause_carries_candidates_and_next_batch_tasks():
    tasks = [
        TaskStateSnapshot(task_id="1.1", status="pending", title="Task 1"),
        TaskStateSnapshot(task_id="1.2", status="pending", title="Task 2"),
    ]
    batches = ["Batch 2: Dual Mode", "Batch 3: Polish"]

    action, consume = compute_next_action(
        task_states=tasks,
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="after_propose",
        stop_at_consumed=False,
        task_file="feature.md",
        roadmap_pending_batches=batches,
        autopilot_set_at="2026-10-24T00:00:00Z",
    )

    assert action.action == "PAUSE_FOR_ACCEPTANCE"
    assert action.stage == "after_propose"
    assert consume is True
    # Crucial: candidates and next_batch_tasks must be non-empty and carry queue context
    assert action.candidates == ("1.1", "1.2")
    assert action.next_batch_tasks == ("Batch 2: Dual Mode", "Batch 3: Polish")
    assert action.expect_set_at == "2026-10-24T00:00:00Z"
    assert action.consume_for == "1.1"


def test_priority_candidates_before_stop_at():
    # Verify Step A (candidates) executes before Step C (stop_at evaluation)
    tasks = [
        TaskStateSnapshot(task_id="25.2", status="confirmed", title="Dual mode"),
        TaskStateSnapshot(task_id="25.3", status="confirmed", title="Harness"),
    ]
    action, consume = compute_next_action(
        task_states=tasks,
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="after_confirm",
        stop_at_consumed=False,
        task_file="batch.md",
    )
    assert action.action == "PAUSE_FOR_ACCEPTANCE"
    # Even when pausing, candidates was already evaluated in Step A
    assert action.candidates == ("25.2", "25.3")


def test_consumed_for_never_uses_task_file_key():
    tasks = [
        TaskStateSnapshot(task_id="25.2", status="confirmed"),
    ]
    # For a task-level stop_at, consume_for must be task_id, NEVER bare task_file
    action, _ = compute_next_action(
        task_states=tasks,
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="after_confirm",
        stop_at_consumed=False,
        task_file="2026-10-24_batch2.md",
    )
    assert action.consume_for == "25.2"
    assert action.consume_for != "2026-10-24_batch2.md"

    # For a batch-level stop_at, consume_for must have __batch__: prefix
    completed_tasks = [
        TaskStateSnapshot(task_id="25.2", status="completed"),
    ]
    action_batch, _ = compute_next_action(
        task_states=completed_tasks,
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="after_batch",
        stop_at_consumed=False,
        task_file="2026-10-24_batch2.md",
        last_event=LastEventSnapshot(tool_name="dev_tasks_archive", success=True, result_data={}),
        roadmap_pending_batches=["Batch 3"],
    )
    assert action_batch.consume_for == "__batch__:2026-10-24_batch2.md"


def test_consumed_for_scoped_per_task():
    tasks = [
        TaskStateSnapshot(task_id="1.1", status="confirmed"),
        TaskStateSnapshot(task_id="1.2", status="confirmed"),
    ]
    # If 1.1 consumed the after_confirm breakpoint, 1.2 at the same breakpoint will NOT be skipped
    action_1_2, consume = compute_next_action(
        task_states=tasks,
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="after_confirm",
        stop_at_consumed=True,
        consumed_for="1.1",  # consumed for 1.1
        current_task_id="1.2",  # now evaluating 1.2
        task_file="batch.md",
    )
    assert action_1_2.action == "PAUSE_FOR_ACCEPTANCE"
    assert action_1_2.consume_for == "1.2"
    assert consume is True


def test_pause_after_consume_reemits_fresh_expect_set_at():
    tasks = [
        TaskStateSnapshot(task_id="1.1", status="pending"),
    ]
    action, consume = compute_next_action(
        task_states=tasks,
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="after_propose",
        stop_at_consumed=False,
        autopilot_set_at="2026-10-24T01:00:00.000Z",
        task_file="batch.md",
    )
    assert consume is True
    assert action.expect_set_at == "2026-10-24T01:00:00.000Z"


def test_max_review_rounds_boundary_exhaustion():
    tasks = [
        TaskStateSnapshot(task_id="1.1", status="rework"),
    ]
    # Under limit -> PROPOSE for revision
    action_rev, _ = compute_next_action(
        task_states=tasks,
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
        review_round=1,
        max_review_rounds=2,
    )
    assert action_rev.action == "PROPOSE"
    assert "review round 1/2" in action_rev.reason

    # At or above limit -> PAUSE_FOR_ACCEPTANCE (review_exhausted), do NOT auto-consume stop_at
    action_exh, consume_exh = compute_next_action(
        task_states=tasks,
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
        review_round=2,
        max_review_rounds=2,
    )
    assert action_exh.action == "PAUSE_FOR_ACCEPTANCE"
    assert action_exh.stage == "review_exhausted"
    assert consume_exh is False


def test_state_matrix_standard_and_inverted():
    # 1. Standard mode + confirmed task -> CHECKOUT
    action_std, _ = compute_next_action(
        task_states=[TaskStateSnapshot(task_id="1.1", status="confirmed")],
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
    )
    assert action_std.action == "CHECKOUT"
    assert action_std.task_id == "1.1"

    # 2. Inverted mode + confirmed task -> DISPATCH_RUNNER
    action_inv, _ = compute_next_action(
        task_states=[TaskStateSnapshot(task_id="1.1", status="confirmed")],
        effective_mode="inverted",
        reviewer_channel=None,
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
    )
    assert action_inv.action == "DISPATCH_RUNNER"
    assert action_inv.task_id == "1.1"

    # 3. Standard mode + pending task -> REVIEW via external_api
    action_rev_std, _ = compute_next_action(
        task_states=[TaskStateSnapshot(task_id="1.1", status="pending")],
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
    )
    assert action_rev_std.action == "REVIEW"
    assert action_rev_std.channel == "external_api"

    # 4. Inverted mode + pending task -> REVIEW via inverted_main_reviewer
    action_rev_inv, _ = compute_next_action(
        task_states=[TaskStateSnapshot(task_id="1.1", status="pending")],
        effective_mode="inverted",
        reviewer_channel=None,
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
    )
    assert action_rev_inv.action == "REVIEW"
    assert action_rev_inv.channel == "inverted_main_reviewer"

    # 5. Blocked on last event failure
    action_blocked, _ = compute_next_action(
        task_states=[TaskStateSnapshot(task_id="1.1", status="confirmed")],
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
        last_event=LastEventSnapshot(tool_name="dev_tasks_checkout", success=False, result_data={"error": "Fenced token mismatch"}),
    )
    assert action_blocked.action == "BLOCKED"
    assert "Fenced token mismatch" in action_blocked.reason


def test_compute_next_action_zero_io_pure(monkeypatch):
    # Monkeypatch open to verify zero I/O execution
    def forbidden_open(*args, **kwargs):
        raise RuntimeError("I/O forbidden in pure autopilot harness")

    monkeypatch.setattr(builtins, "open", forbidden_open)

    tasks = [
        TaskStateSnapshot(task_id="1.1", status="pending"),
        TaskStateSnapshot(task_id="1.2", status="confirmed"),
    ]
    # Call compute_next_action under forbidden I/O
    action, consume = compute_next_action(
        task_states=tasks,
        effective_mode="standard",
        reviewer_channel="external_api",
        mode_source="default",
        stop_at="after_propose",
        stop_at_consumed=False,
        last_event=LastEventSnapshot(tool_name="dev_tasks_propose", success=True, result_data={}),
        task_file="test.md",
        roadmap_pending_batches=["Batch 3"],
    )
    assert action.action == "PAUSE_FOR_ACCEPTANCE"
    assert consume is True
    assert action.candidates == ("1.1", "1.2")


@pytest.mark.tier1_fast
def test_compute_batch_overlap_ratio():
    # 1. Exact file match -> 1.0
    prev = ["[MODIFY] backend/server.py", "[NEW] backend/auth.py"]
    curr = ["backend/server.py", "backend/auth.py"]
    assert compute_batch_overlap_ratio(prev, curr) == 1.0

    # 2. Same module dir match (completely different files) -> 0.5 (0.5 * 1.0)
    prev = ["backend/db.py"]
    curr = ["backend/routes.py"]
    assert compute_batch_overlap_ratio(prev, curr) == 0.5

    # 3. Disjoint module dirs (backend/ vs frontend/) -> 0.0
    prev = ["backend/models/user.py"]
    curr = ["frontend/src/views/User.vue"]
    assert compute_batch_overlap_ratio(prev, curr) == 0.0

    # 4. Empty inputs -> 0.0
    assert compute_batch_overlap_ratio([], ["backend/a.py"]) == 0.0
    assert compute_batch_overlap_ratio(["backend/a.py"], []) == 0.0
    assert compute_batch_overlap_ratio([], []) == 0.0
    assert compute_batch_overlap_ratio(["   ", "```"], ["backend/a.py"]) == 0.0
    assert compute_batch_overlap_ratio(["backend/a.py"], ["   "]) == 0.0

    # 5. Path cleaning: stripping quotes, list markers, links, file:///
    prev_messy = [
        "- [MODIFY] `backend/a.py`",
        "file:///backend/b.py (optional comment)",
        "* [NEW] [docs/README.md](docs/README.md)",
    ]
    curr_clean = ["./backend/a.py", "backend/b.py", "docs/README.md"]
    assert compute_batch_overlap_ratio(prev_messy, curr_clean) == 1.0


@pytest.mark.tier1_fast
def test_resolve_runner_dispatch_channel():
    # Rule 1: Intra-batch completed_in_batch > 0 -> reuse_active
    assert resolve_runner_dispatch_channel(completed_in_batch=1) == "reuse_active"
    assert resolve_runner_dispatch_channel(
        completed_in_batch=3,
        prev_batch_files=["a/x.py"],
        curr_batch_files=["b/y.py"],
    ) == "reuse_active"

    # Rule 1: Rework -> reuse_active
    assert resolve_runner_dispatch_channel(completed_in_batch=0, is_rework=True) == "reuse_active"
    assert resolve_runner_dispatch_channel(
        completed_in_batch=0,
        is_rework=True,
        cumulative_runner_tasks=20,
    ) == "reuse_active"

    # Rule 2: Safety fuse at batch boundary >= 12 -> spawn_fresh
    assert resolve_runner_dispatch_channel(
        completed_in_batch=0,
        is_rework=False,
        prev_batch_files=["backend/a.py"],
        curr_batch_files=["backend/a.py"],
        cumulative_runner_tasks=DEFAULT_MAX_RUNNER_TASKS,
    ) == "spawn_fresh"
    assert resolve_runner_dispatch_channel(
        completed_in_batch=0,
        is_rework=False,
        prev_batch_files=["backend/a.py"],
        curr_batch_files=["backend/a.py"],
        cumulative_runner_tasks=15,
    ) == "spawn_fresh"

    # Rule 3: Cross-batch empty files -> spawn_fresh
    assert resolve_runner_dispatch_channel(
        completed_in_batch=0,
        is_rework=False,
        prev_batch_files=[],
        curr_batch_files=["backend/a.py"],
    ) == "spawn_fresh"
    assert resolve_runner_dispatch_channel(
        completed_in_batch=0,
        is_rework=False,
        prev_batch_files=["backend/a.py"],
        curr_batch_files=[],
    ) == "spawn_fresh"

    # Rule 3: Cross-batch high overlap (>= 0.30) under safety fuse -> reuse_active
    assert resolve_runner_dispatch_channel(
        completed_in_batch=0,
        is_rework=False,
        prev_batch_files=["backend/a.py"],
        curr_batch_files=["backend/b.py"],
        cumulative_runner_tasks=5,
    ) == "reuse_active"

    # Rule 3: Cross-batch disjoint (< 0.30) -> spawn_fresh
    assert resolve_runner_dispatch_channel(
        completed_in_batch=0,
        is_rework=False,
        prev_batch_files=["backend/a.py"],
        curr_batch_files=["frontend/b.py"],
        cumulative_runner_tasks=0,
    ) == "spawn_fresh"


@pytest.mark.tier1_fast
def test_compute_next_action_dispatch_runner_channel_and_model_hint():
    # 1. Inverted mode + confirmed task + cross-batch domain overlap -> reuse_active with model_hint
    action_reuse, _ = compute_next_action(
        task_states=[TaskStateSnapshot(task_id="2.1", status="confirmed")],
        effective_mode="inverted",
        reviewer_channel=None,
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
        runner_subagent_model_hint="flash",
        prev_batch_files=["backend/models.py"],
        curr_batch_files=["backend/views.py"],
        cumulative_runner_tasks=2,
    )
    assert action_reuse.action == "DISPATCH_RUNNER"
    assert action_reuse.task_id == "2.1"
    assert action_reuse.channel == "reuse_active"
    assert action_reuse.model_hint == "flash"
    assert "reuse active runner subagent" in action_reuse.instruction

    # 2. Inverted mode + in_progress task + disjoint domain -> spawn_fresh
    action_fresh, _ = compute_next_action(
        task_states=[TaskStateSnapshot(task_id="2.2", status="in_progress")],
        effective_mode="inverted",
        reviewer_channel=None,
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
        runner_subagent_model_hint="pro",
        prev_batch_files=["backend/models.py"],
        curr_batch_files=["frontend/components/Table.vue"],
        cumulative_runner_tasks=0,
    )
    assert action_fresh.action == "DISPATCH_RUNNER"
    assert action_fresh.task_id == "2.2"
    assert action_fresh.channel == "spawn_fresh"
    assert action_fresh.model_hint == "pro"
    assert "spawn a fresh isolated runner subagent" in action_fresh.instruction

    # 3. Inverted mode + confirmed task + safety fuse reached (>= 12) -> spawn_fresh
    action_fuse, _ = compute_next_action(
        task_states=[TaskStateSnapshot(task_id="3.1", status="confirmed")],
        effective_mode="inverted",
        reviewer_channel=None,
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
        runner_subagent_model_hint="flash",
        prev_batch_files=["backend/models.py"],
        curr_batch_files=["backend/models.py"],
        cumulative_runner_tasks=12,
    )
    assert action_fuse.action == "DISPATCH_RUNNER"
    assert action_fuse.channel == "spawn_fresh"

    # 4. Inverted mode + intra-batch continuation (completed task in batch) -> reuse_active overrides safety fuse
    action_intra, _ = compute_next_action(
        task_states=[
            TaskStateSnapshot(task_id="3.1", status="completed"),
            TaskStateSnapshot(task_id="3.2", status="confirmed"),
        ],
        effective_mode="inverted",
        reviewer_channel=None,
        mode_source="default",
        stop_at="none",
        stop_at_consumed=False,
        runner_subagent_model_hint="flash",
        prev_batch_files=["backend/models.py"],
        curr_batch_files=["frontend/views.vue"],
        cumulative_runner_tasks=15,
    )
    assert action_intra.action == "DISPATCH_RUNNER"
    assert action_intra.channel == "reuse_active"
    assert action_intra.model_hint == "flash"


@pytest.mark.tier1_fast
def test_inject_harness_next_action_cross_batch_overlap_from_markdown(tmp_path):
    from server import _inject_harness_next_action
    from runtime_mode import update_runtime_mode

    # Setup directories
    archive_dir = tmp_path / "docs" / "dev_tasks" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dev_tasks_dir = tmp_path / "docs" / "dev_tasks"
    dev_tasks_dir.mkdir(parents=True, exist_ok=True)

    # 1. Archived markdown task file
    archived_file = archive_dir / "2026-10-24_batch1.md"
    archived_content = (
        "# Batch 1 Tasks\n\n"
        "### 任务 1.1 ✔️ 已完成 — Task 1\n\n"
        "#### 【涉及文件】\n"
        "```\n"
        "- [MODIFY] backend/service.py\n"
        "```\n"
    )
    archived_file.write_text(archived_content, encoding="utf-8")

    # 2. Active markdown task file with overlapping domain (backend/)
    active_file = dev_tasks_dir / "2026-10-24_batch2.md"
    active_content = (
        "# Batch 2 Tasks\n\n"
        "### 任务 2.1 ✅ 已确认 — Task 2\n\n"
        "#### 【涉及文件】\n"
        "```\n"
        "- [MODIFY] backend/router.py\n"
        "```\n"
    )
    active_file.write_text(active_content, encoding="utf-8")

    # 3. Configure inverted mode
    update_runtime_mode(
        workspace_root=str(tmp_path),
        switch_mode="inverted",
        external_api_available=False,
    )

    res_dict = {}
    _inject_harness_next_action(
        str(tmp_path),
        "dev_tasks_confirm",
        res_dict,
        last_success=True,
        task_file="docs/dev_tasks/2026-10-24_batch2.md",
    )

    assert "harness_next_action" in res_dict
    harness_action = res_dict["harness_next_action"]
    assert harness_action["action"] == "DISPATCH_RUNNER"
    assert harness_action["channel"] == "reuse_active"

    # 4. Update active file with disjoint domain (frontend/) -> should recommend spawn_fresh
    active_disjoint_content = (
        "# Batch 2 Tasks\n\n"
        "### 任务 2.1 ✅ 已确认 — Task 2\n\n"
        "#### 【涉及文件】\n"
        "```\n"
        "- [MODIFY] frontend/App.vue\n"
        "```\n"
    )
    active_file.write_text(active_disjoint_content, encoding="utf-8")

    res_dict_disjoint = {}
    _inject_harness_next_action(
        str(tmp_path),
        "dev_tasks_confirm",
        res_dict_disjoint,
        last_success=True,
        task_file="docs/dev_tasks/2026-10-24_batch2.md",
    )

    assert "harness_next_action" in res_dict_disjoint
    harness_action_disjoint = res_dict_disjoint["harness_next_action"]
    assert harness_action_disjoint["action"] == "DISPATCH_RUNNER"
    assert harness_action_disjoint["channel"] == "spawn_fresh"


@pytest.mark.tier1_fast
def test_inject_harness_next_action_standard_mode_bypasses_archive_scan(tmp_path, monkeypatch):
    from server import _inject_harness_next_action
    from runtime_mode import update_runtime_mode
    import server

    dev_tasks_dir = tmp_path / "docs" / "dev_tasks"
    dev_tasks_dir.mkdir(parents=True, exist_ok=True)
    active_file = dev_tasks_dir / "2026-10-24_batch1.md"
    active_file.write_text(
        "# Batch 1 Tasks\n\n### 任务 1.1 ✅ 已确认 — Task 1\n\n#### 【涉及文件】\n```\n- [MODIFY] backend/service.py\n```\n",
        encoding="utf-8",
    )

    update_runtime_mode(
        workspace_root=str(tmp_path),
        switch_mode="standard",
        external_api_available=True,
    )

    archive_scanned = False
    orig_extract = server._extract_batch_scoped_files

    def tracked_extract(filepath, tasks):
        nonlocal archive_scanned
        if "archive" in str(filepath).replace("\\", "/"):
            archive_scanned = True
        return orig_extract(filepath, tasks)

    monkeypatch.setattr(server, "_extract_batch_scoped_files", tracked_extract)

    res_dict = {}
    _inject_harness_next_action(
        str(tmp_path),
        "dev_tasks_confirm",
        res_dict,
        last_success=True,
        task_file="docs/dev_tasks/2026-10-24_batch1.md",
    )
    assert res_dict["harness_next_action"]["action"] == "CHECKOUT"
    assert archive_scanned is False


def test_inject_harness_next_action_ignores_readme_md(tmp_path):
    """验证 _inject_harness_next_action 在隐式扫描 dev_tasks_dir 时严密排除 README.md。"""
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "quench_stack.yaml").write_text(
        "project_name: test-readme-ignore\ndev_tasks_dir: docs/dev_tasks\naudit_gate:\n  enabled: false\n",
        encoding="utf-8",
    )
    dev_tasks_dir = tmp_path / "docs" / "dev_tasks"
    dev_tasks_dir.mkdir(parents=True, exist_ok=True)

    active_file = dev_tasks_dir / "2026-10-25_batch.md"
    active_file.write_text(
        "# Batch Tasks\n\n### 任务 1.1 ✅ 已确认 — Task 1\n\n#### 【涉及文件】\n```\n- [MODIFY] backend/service.py\n```\n",
        encoding="utf-8",
    )

    # 写入一个更新时间更新的 README.md，模拟在任务单创建后被用户或初始化脚本触碰
    readme_file = dev_tasks_dir / "README.md"
    readme_file.write_text("# Documentation and Task Template README\n", encoding="utf-8")
    future_time = time.time() + 100
    os.utime(str(readme_file), (future_time, future_time))

    res_dict = {}
    from server import _inject_harness_next_action

    _inject_harness_next_action(
        workspace_root=str(tmp_path),
        tool_name="dev_tasks_status",
        result_data=res_dict,
        last_success=True,
        task_file=None,  # 强制触发 dev_tasks_dir 隐式扫描
    )

    assert "harness_next_action" in res_dict
    h_action = res_dict["harness_next_action"]
    assert h_action["task_file"] == "docs/dev_tasks/2026-10-25_batch.md"
    assert "readme.md" not in str(h_action["task_file"]).lower()



