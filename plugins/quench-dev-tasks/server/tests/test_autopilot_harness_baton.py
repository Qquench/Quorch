"""Unit tests for the pure Autopilot Harness decision engine.

Validates state transition table, candidates-first priority, single-namespace scope,
CAS expect_set_at re-emission, and strict zero-I/O purity.
"""

import builtins
import pytest

from autopilot_harness import (
    compute_next_action,
    TaskStateSnapshot,
    LastEventSnapshot,
    HarnessNextAction,
    DEFAULT_MAX_REVIEW_ROUNDS,
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
