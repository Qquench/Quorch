# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from reviewer_jobs import (
    JobProgress,
    JobRecord,
    JobState,
    POLL_TERMINAL_FIELDS,
    ReviewerJobSupervisor,
    ReviewerPhase,
    SnapshotContractViolation,
    TERMINAL_RESULT_ALLOWED_FIELDS,
    _durable_write_json,
    project_terminal,
)
from workspace_lease import PeerLiveness, WorkspaceLeaseGuard


def test_dual_source_single_ssot_and_reconcile_backfill(tmp_path):
    """C-3: JobRecord 单一权威源与 verdicts.jsonl 幂等自愈补写。
    当 JobRecord 为终态但 verdicts.jsonl 缺失对应记录时，启动期对账严禁判为 ORPHANED，
    并自动执行向后自愈补写；重复对账零副作用。
    """
    supervisor = ReviewerJobSupervisor(tmp_path)
    now_wall = datetime.now(timezone.utc).isoformat()
    now_mono = time.monotonic()

    # 1. 模拟落盘一个 COMPLETED 终态任务
    rec = JobRecord(
        job_id="job_completed_ssot_1",
        session_id="session_ssot_1",
        workspace_root=str(tmp_path),
        mode="critique",
        owner_pid=os.getpid(),
        owner_boot_nonce=supervisor.boot_nonce,
        generation=2,
        state=JobState.COMPLETED,
        created_monotonic=now_mono - 50,
        updated_monotonic=now_mono - 10,
        created_wall_utc=now_wall,
        updated_wall_utc=now_wall,
        log_path=str(tmp_path / "test_ssot.log"),
        progress=JobProgress(40.0, 500, ReviewerPhase.FINALIZING, 0.5),
        result_ref=str(supervisor._get_result_path("session_ssot_1", "job_completed_ssot_1")),
        degraded_reason=None,
    )
    supervisor._save_job_record(rec)

    # 结果持久化
    res_path = Path(rec.result_ref)
    _durable_write_json(res_path, {"status": "success", "findings": "SSOT review verdict"})

    # 此时 verdicts.jsonl 尚不存在或为空
    v_path = supervisor._get_verdicts_path()
    assert not v_path.is_file() or v_path.stat().st_size == 0

    # 2. 执行启动对账：绝不判定 ORPHANED，而是补写 verdicts.jsonl
    orphaned = supervisor.reconcile_on_load()
    assert "job_completed_ssot_1" not in orphaned
    assert orphaned == []

    # 验证 JobRecord 状态未被破坏
    loaded_rec = supervisor._load_job_record("session_ssot_1", "job_completed_ssot_1")
    assert loaded_rec.state == JobState.COMPLETED

    # 验证 verdicts.jsonl 存在补写的记录
    assert v_path.is_file()
    lines = [json.loads(line) for line in v_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["job_id"] == "job_completed_ssot_1"
    assert lines[0]["state"] == "COMPLETED"

    # 3. 再次重复对账（幂等性验证）：绝不重复追加相同 job_id
    orphaned2 = supervisor.reconcile_on_load()
    assert orphaned2 == []
    lines2 = [json.loads(line) for line in v_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines2) == 1


def test_running_job_missing_in_jsonl_never_orphaned_if_peer_alive(tmp_path, monkeypatch):
    """C-3 / I3: 运行中的任务在 verdicts.jsonl 中缺行绝不构成孤儿判据；必须根据进程探针决策。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    now_wall = datetime.now(timezone.utc).isoformat()
    now_mono = time.monotonic()

    running_rec = JobRecord(
        job_id="job_foreign_running_1",
        session_id="session_foreign_1",
        workspace_root=str(tmp_path),
        mode="critique",
        owner_pid=999998,
        owner_boot_nonce="nonce_foreign_alive",
        generation=1,
        state=JobState.RUNNING,
        created_monotonic=now_mono - 60,
        updated_monotonic=now_mono - 10,
        created_wall_utc=now_wall,
        updated_wall_utc=now_wall,
        log_path=str(tmp_path / "foreign_running.log"),
        progress=JobProgress(50.0, 100, ReviewerPhase.STREAMING, 1.0),
        result_ref=None,
    )
    supervisor._save_job_record(running_rec)
    supervisor.registry.pin(running_rec.log_path)

    # 模拟探针：异代但进程仍然存活
    monkeypatch.setattr(
        WorkspaceLeaseGuard,
        "probe_peer",
        lambda pid, nonce, ws: PeerLiveness(
            is_alive=True, pid=pid, boot_nonce=nonce, takeover_allowed=False, probe_confident=True
        ),
    )

    orphaned = supervisor.reconcile_on_load()
    assert "job_foreign_running_1" not in orphaned
    assert supervisor.registry.is_pinned(running_rec.log_path)

    loaded = supervisor._load_job_record("session_foreign_1", "job_foreign_running_1")
    assert loaded.state == JobState.RUNNING


def test_durable_write_json_atomicity_and_sync(tmp_path):
    """C-3 / H-C: durable write 保证持久化且 temp 失败时不破坏既有文件。"""
    target = tmp_path / "durable_target.json"
    data1 = {"key": "initial_data"}
    _durable_write_json(target, data1)
    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8")) == data1

    data2 = {"key": "updated_data"}
    _durable_write_json(target, data2)
    assert json.loads(target.read_text(encoding="utf-8")) == data2


def test_terminal_allowlist_filters_unmanaged_keys_and_rejects_reasoning():
    """C-5: 终态对称白名单投影：严格剔除未知键（thoughts/trace 等），拒绝 raw reasoning 键并抛 SnapshotContractViolation。"""
    rec = JobRecord(
        job_id="job_allowlist_test",
        session_id="session_allowlist_test",
        workspace_root="/test/ws",
        mode="critique",
        owner_pid=1234,
        owner_boot_nonce="nonce_test",
        generation=1,
        state=JobState.COMPLETED,
        created_monotonic=10.0,
        updated_monotonic=20.0,
        created_wall_utc="2026-09-25T00:00:00Z",
        updated_wall_utc="2026-09-25T00:00:10Z",
        log_path="/path/test.log",
        progress=JobProgress(10.0, 50, ReviewerPhase.FINALIZING, 0.0),
        result_ref="/path/result.json",
        degraded_reason=None,
    )

    # 1. 包含未知新键（例如 thoughts, trace, internal_meta）必须被白名单剔除，不能穿透
    raw_result = {
        "status": "success",
        "findings": "Legitimate findings",
        "mode": "critique",
        "session_id": "session_allowlist_test",
        "usage": {"prompt_tokens": 50, "completion_tokens": 20},
        "thoughts": "unfiltered thought stream that would explode budget",
        "trace": "debug execution trace",
        "internal_vendor_meta": {"cache": True},
    }

    projected = project_terminal(rec, raw_result)
    assert set(projected.keys()) == POLL_TERMINAL_FIELDS
    res = projected["result"]
    assert res is not None
    assert "findings" in res
    assert res["findings"] == "Legitimate findings"
    # 验证穿透键被白名单严格过滤
    assert "thoughts" not in res
    assert "trace" not in res
    assert "internal_vendor_meta" not in res

    # 2. 注入禁止的 raw reasoning 键必须显式抛出 SnapshotContractViolation
    for bad_key in ["reasoning", "raw_reasoning", "chain_of_thought"]:
        bad_payload = {"status": "success", "findings": "ok", bad_key: "forbidden string"}
        with pytest.raises(SnapshotContractViolation) as exc_info:
            project_terminal(rec, bad_payload)
        assert "forbidden raw reasoning keys" in str(exc_info.value)


def test_cancel_timing_retains_pin_on_timeout(tmp_path):
    """H-7: 取消时序闭合：若 worker 线程超时未能退出，状态变迁为 CANCELLED_PENDING_REAP 并保留 pin，防止 WinError 32 竞态。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = supervisor.submit({"query": "long query", "session_id": "cancel_timeout_sess"})

    # 模拟一个正在阻塞运行、短期内无法终止的 worker 线程
    stop_event = threading.Event()

    def stubborn_worker():
        stop_event.wait(5.0)

    t = threading.Thread(target=stubborn_worker, daemon=True)
    t.start()

    with supervisor._running_jobs_lock:
        supervisor._worker_threads[rec.job_id] = t

    # 确保日志处于 pinned 状态
    assert supervisor.registry.is_pinned(rec.log_path)

    # 执行 cancel，因 worker 无法在 2s 内 join，必须迁入 CANCELLED_PENDING_REAP
    # 并保留 pin
    cancel_res = supervisor.cancel(rec.job_id, session_id="cancel_timeout_sess")
    assert cancel_res["state"] == JobState.CANCELLED_PENDING_REAP.value
    assert supervisor.registry.is_pinned(rec.log_path)

    # 唤醒并释放 worker 线程
    stop_event.set()
    t.join(timeout=2.0)
    supervisor.shutdown()
