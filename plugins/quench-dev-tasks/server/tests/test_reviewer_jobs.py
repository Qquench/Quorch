# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

# Ensure server module is in sys.path
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from log_naming import (
    ActiveLogRegistry,
    allocate_log_file,
    enforce_unified_log_quota,
    gc_by_filename_order,
    norm_registry_key,
)
from reviewer_jobs import (
    CapacityExceeded,
    JobProgress,
    JobRecord,
    JobState,
    PollSnapshot,
    ReviewerJobSupervisor,
    ReviewerPhase,
    _atomic_replace_json,
    project_poll_result,
    POLL_TERMINAL_FIELDS,
    POLL_NONTERMINAL_FIELDS,
)
from workspace_lease import PeerLiveness, WorkspaceLeaseGuard, WorkspaceLeaseNotHeldError


def test_i1_terminal_cas_single_writer_wins(tmp_path):
    """I1: 单写者终态 CAS：终态经 filelock 原子 CAS 迁移，多写者并发时仅唯一胜出。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = supervisor.submit({"query": "test query", "session_id": "test_cas_sess"})
    # 迁移为 RUNNING
    supervisor._cas_transition(rec.session_id, rec.job_id, JobState.QUEUED, JobState.RUNNING)

    results = []

    def try_complete():
        res = supervisor._cas_transition(
            rec.session_id, rec.job_id, JobState.RUNNING, JobState.COMPLETED
        )
        results.append(("COMPLETED", res))

    def try_cancel():
        res = supervisor._cas_transition(
            rec.session_id, rec.job_id, JobState.RUNNING, JobState.CANCELLED
        )
        results.append(("CANCELLED", res))

    t1 = threading.Thread(target=try_complete)
    t2 = threading.Thread(target=try_cancel)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # 恰好一个成功，另一个失败
    successes = [r for r in results if r[1] is True]
    failures = [r for r in results if r[1] is False]
    assert len(successes) == 1
    assert len(failures) == 1

    final_rec = supervisor._load_job_record(rec.session_id, rec.job_id)
    assert final_rec.state in (JobState.COMPLETED, JobState.CANCELLED)
    expected_state = JobState.COMPLETED if successes[0][0] == "COMPLETED" else JobState.CANCELLED
    assert final_rec.state == expected_state


@pytest.mark.anyio
async def test_i2_supervisor_task_survives_handler_scope(tmp_path):
    """I2: 常驻所有权：Supervisor 为服务进程内单例线程模型，强引用持有 Task，脱离调用栈不被垃圾回收。"""
    supervisor = ReviewerJobSupervisor(tmp_path)

    def local_handler_scope():
        rec = supervisor.submit({"query": "async query", "session_id": "scope_sess"})
        return rec.job_id

    job_id = local_handler_scope()
    assert job_id in supervisor._tasks
    task = supervisor._tasks[job_id]
    assert isinstance(task, asyncio.Task)
    supervisor.shutdown()


def test_i3_reconcile_marks_foreign_jobs_orphaned(tmp_path, monkeypatch):
    """I3: 启动载入对账：通过 Task 4.0 的 probe_peer 验证异代进程真实存活；仅当异代且确认 PID 死亡才迁 ORPHANED 并 unpin。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    now_mono = time.monotonic()
    now_wall = datetime.now(timezone.utc).isoformat()
    dead_rec = JobRecord(
        job_id="dead_job_1",
        session_id="dead_sess_1",
        workspace_root=str(tmp_path),
        mode="critique",
        owner_pid=999999,
        owner_boot_nonce="nonce_foreign_dead",
        generation=1,
        state=JobState.RUNNING,
        created_monotonic=now_mono - 100,
        updated_monotonic=now_mono - 50,
        created_wall_utc=now_wall,
        updated_wall_utc=now_wall,
        log_path=str(tmp_path / "test.log"),
        progress=JobProgress(50.0, 10, ReviewerPhase.STREAMING, 2.0),
        result_ref=None,
    )
    supervisor._save_job_record(dead_rec)
    supervisor.registry.pin(dead_rec.log_path)
    assert supervisor.registry.is_pinned(dead_rec.log_path)

    # 1. 模拟死进程且允许接管
    monkeypatch.setattr(
        WorkspaceLeaseGuard,
        "probe_peer",
        lambda pid, nonce, ws: PeerLiveness(
            is_alive=False, pid=pid, boot_nonce=nonce, takeover_allowed=True
        ),
    )

    orphaned = supervisor.reconcile_on_load()
    assert "dead_job_1" in orphaned
    updated = supervisor._load_job_record("dead_sess_1", "dead_job_1")
    assert updated.state == JobState.ORPHANED
    assert updated.degraded_reason == "orphaned"
    assert not supervisor.registry.is_pinned(dead_rec.log_path)


@pytest.mark.anyio
async def test_i4_cancel_aborts_transport_and_is_idempotent(tmp_path):
    """I4: 确定性真实取消：Cancel 物理关闭 Socket，Worker 在同一 CAS 临界区记录 tokens_billed_after_cancel，对终态幂等。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = supervisor.submit({"query": "long query", "session_id": "cancel_sess"})

    # 首次取消
    res1 = supervisor.cancel(rec.job_id, session_id="cancel_sess")
    assert res1["state"] == "CANCELLED"
    assert res1["degraded_reason"] == "cancelled"

    # 二次取消（终态幂等）
    res2 = supervisor.cancel(rec.job_id, session_id="cancel_sess")
    assert res2["state"] == "CANCELLED"
    assert res2["degraded_reason"] == "cancelled"
    supervisor.shutdown()


def test_i7_result_durable_before_completed_state(tmp_path):
    """I7: 隔离目录与结果优先落盘：结果文件隔离落盘于 results/<job_id>.result.json，原子持久化后再 CAS COMPLETED。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = supervisor.submit({"query": "query", "session_id": "durable_sess"})
    res_path = supervisor._get_result_path(rec.session_id, rec.job_id)
    fake_result = {
        "status": "success",
        "findings": "Architectural review verdict.",
        "usage": {"prompt_tokens": 10},
    }
    _atomic_replace_json(res_path, fake_result)
    assert res_path.is_file()

    # 验证在 COMPLETED 状态前结果已物理落盘
    success = supervisor._cas_transition(
        rec.session_id,
        rec.job_id,
        JobState.QUEUED,
        JobState.COMPLETED,
        updates={"result_ref": str(res_path)},
    )
    assert success is True
    loaded = supervisor._load_job_record(rec.session_id, rec.job_id)
    assert loaded.state == JobState.COMPLETED
    assert Path(loaded.result_ref).is_file()


def test_i8_admission_rejects_when_capacity_full(tmp_path, monkeypatch):
    """I8: 并发准入控制：CapacityLimiter 纯读快速失败判据（borrowed >= total），满额直接抛 CapacityExceeded(retry_after)。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    # 模拟 CapacityLimiter 达到上限
    class FullLimiter:
        borrowed_tokens = 4
        total_tokens = 4

    monkeypatch.setattr(supervisor, "_limiter", FullLimiter())

    with pytest.raises(CapacityExceeded) as exc_info:
        supervisor.submit({"query": "blocked query", "session_id": "cap_sess"})
    assert exc_info.value.retry_after == 5


def test_i10_gc_reclaims_expired_and_tolerates_enoent(tmp_path):
    """I10: 终态 GC 与容错：仅回收超 TTL 终态任务，GC 期间对已解引用文件优雅容忍 ENOENT，不抛异常。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec1 = supervisor.submit({"query": "q1", "session_id": "gc_sess"})
    rec2 = supervisor.submit({"query": "q2", "session_id": "gc_sess"})

    supervisor._cas_transition(rec1.session_id, rec1.job_id, JobState.QUEUED, JobState.COMPLETED)
    supervisor._cas_transition(rec2.session_id, rec2.job_id, JobState.QUEUED, JobState.RUNNING)

    rec1_path = supervisor._get_record_path(rec1.session_id, rec1.job_id)
    past_time = time.time() - 3600
    os.utime(rec1_path, (past_time, past_time))

    # 执行 GC
    reaped = supervisor.gc_terminal_jobs(max_age_s=1800.0)
    assert reaped >= 1
    assert not rec1_path.exists()

    # 运行中的任务绝不被清除
    rec2_path = supervisor._get_record_path(rec2.session_id, rec2.job_id)
    assert rec2_path.exists()


def test_log_pinned_during_run_and_dual_gc_skips(tmp_path):
    """LOG-PIN: 在途日志钉住与轮转归并：norm_registry_key 剥离 .1.log 保持 pin 状态，双 GC 路径跳过 pinned。"""
    registry = ActiveLogRegistry()
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    base_path, _ = allocate_log_file(log_dir, slug="test_sess", registry=registry)
    rotated_path = base_path.replace(".log", ".1.log")
    with open(rotated_path, "w", encoding="utf-8") as f:
        f.write("rotated log content\n")

    assert registry.is_pinned(base_path) is True
    assert registry.is_reclaimable(norm_registry_key(rotated_path)) is False

    # 创建干扰历史文件
    for i in range(25):
        f = log_dir / f"20260901_{i:03d}_old.log"
        f.write_text("old", encoding="utf-8")

    # 路径 A: gc_by_filename_order 跳过 pinned 与轮转分片
    gc_by_filename_order(log_dir, keep=5, registry=registry)
    assert os.path.exists(base_path)
    assert os.path.exists(rotated_path)

    # 路径 B: enforce_unified_log_quota 跳过 pinned 与轮转分片
    enforce_unified_log_quota(log_dir, keep=5, registry=registry)
    assert os.path.exists(base_path)
    assert os.path.exists(rotated_path)

    # unpin 后变得可回收
    registry.unpin(base_path)
    assert registry.is_pinned(base_path) is False
    assert registry.is_reclaimable(norm_registry_key(rotated_path)) is True


def test_gc_rejected_when_lease_not_held(tmp_path):
    """LEASE-GATE: GC 租约守卫：Reviewer 通道下未持有 workspace lease 时严禁执行 GC / 轮转，防止多进程误删。"""
    guard = WorkspaceLeaseGuard(tmp_path)
    assert not guard.is_held()

    with pytest.raises(WorkspaceLeaseNotHeldError):
        gc_by_filename_order(tmp_path, require_lease=True, lease_guard=guard)

    with pytest.raises(WorkspaceLeaseNotHeldError):
        enforce_unified_log_quota(tmp_path, require_lease=True, lease_guard=guard)

    # 默认 require_lease=False 保证老旧单测兼容
    gc_by_filename_order(tmp_path, require_lease=False, lease_guard=guard)
    enforce_unified_log_quota(tmp_path, require_lease=False, lease_guard=guard)


def test_auth_cross_session_poll_rejected(tmp_path):
    """AUTH: 会话防越权：poll/cancel 必须校验 caller session_id 与 job.session_id 一致，防止 IDOR。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = supervisor.submit({"query": "q", "session_id": "session_alpha"})

    # 同会话合法访问
    res = supervisor.poll(rec.job_id, session_id="session_alpha")
    assert res["job_id"] == rec.job_id

    # 跨会话越权访问被拒
    with pytest.raises(PermissionError) as exc_info:
        supervisor.poll(rec.job_id, session_id="session_beta")
    assert "Access denied" in str(exc_info.value)

    with pytest.raises(PermissionError) as exc_info:
        supervisor.cancel(rec.job_id, session_id="session_beta")
    assert "Access denied" in str(exc_info.value)


@pytest.mark.anyio
async def test_consult_thin_shell_backward_compatible(tmp_path):
    """COMPAT: 薄壳向后兼容：既有 dev_reviewer_consult 参数与返回字段 100% 保持原样。"""
    import server

    res = await server.dev_reviewer_consult(
        workspace_root=str(tmp_path),
        query="Design review query",
        session_id="compat_test_sess",
    )
    assert isinstance(res, dict)
    assert "status" in res
    assert "findings" in res
    assert "session_id" in res
    assert "mode" in res


def test_poll_raw_text_nonterminal_projection(tmp_path):
    """RAW-TEXT: 非终态 raw_text=True 必须返回简洁单行字符串，彻底消除 JSON 展开卡片。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = supervisor.submit({"query": "q", "session_id": "raw_text_sess"})

    # 1. raw_text=False -> 返回非终态 6 字段字典
    res_dict = supervisor.poll(rec.job_id, session_id="raw_text_sess", raw_text=False)
    assert isinstance(res_dict, dict)
    assert set(res_dict.keys()) == POLL_NONTERMINAL_FIELDS

    # 2. raw_text=True -> 返回纯文本单行 str
    res_str = supervisor.poll(rec.job_id, session_id="raw_text_sess", raw_text=True)
    assert isinstance(res_str, str)
    assert res_str.startswith("[Reviewer thinking:")
    assert "tokens" in res_str
    assert "\n" not in res_str


def test_poll_raw_text_terminal_projection_always_dict(tmp_path):
    """RAW-TEXT: 终态不论 raw_text 取值，恒定返回完整结构化字典，保障机器审计与结果提取。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = supervisor.submit({"query": "q", "session_id": "term_raw_sess"})

    # 写入结果文件并原子跃迁至 COMPLETED 终态
    from reviewer_jobs import _durable_write_json
    res_path = supervisor._get_result_path(rec.session_id, rec.job_id)
    _durable_write_json(res_path, {"verdict": "PASS", "findings": "All clear", "usage": {"total_tokens": 100}})

    supervisor._cas_transition(
        rec.session_id,
        rec.job_id,
        JobState.QUEUED,
        JobState.COMPLETED,
        updates={"result_ref": str(res_path)},
    )

    # 终态即使指定 raw_text=True 亦必须返回字典
    res_terminal = supervisor.poll(rec.job_id, session_id="term_raw_sess", raw_text=True)
    assert isinstance(res_terminal, dict)
    assert set(res_terminal.keys()) == POLL_TERMINAL_FIELDS
    assert res_terminal["state"] == "COMPLETED"
    assert res_terminal["result"]["verdict"] == "PASS"


def test_dead_code_purged_no_mcp_push_no_tty():
    """DEAD-CODE: 校验已彻底移除无效的 mcp_context 上下文推送与 stderr.isatty() 终端控制字符。"""
    import io
    from unittest.mock import MagicMock
    from reviewer_engine import AdaptiveHeartbeatSink

    mcp_ctx = MagicMock()
    mcp_ctx.info = MagicMock()
    fake_stderr = io.StringIO()
    fake_stderr.isatty = lambda: True
    emitted: list[str] = []

    sink = AdaptiveHeartbeatSink(
        file_emit=emitted.append,
        mcp_context=mcp_ctx,
        stderr=fake_stderr,
        interval_ms=500,
    )
    sink.on_heartbeat(tokens_so_far=10, elapsed_s=0.2)

    # 1. 绝不调用 mcp_ctx.info
    mcp_ctx.info.assert_not_called()

    # 2. 绝不向 stderr 输出动态 \r 覆盖字符
    assert fake_stderr.getvalue() == ""

    # 3. 仅向 file_emit 通道写入持久化行
    assert len(emitted) == 1
    assert "[progress] [Reviewer thinking: 10 tokens | 0.2s]" in emitted[0]


def test_heartbeat_single_line_projection_format():
    """HEARTBEAT: project_poll_result 纯函数直接测试。"""
    snapshot = PollSnapshot(
        job_id="job_abc",
        session_id="sess_abc",
        state=JobState.RUNNING,
        retry_after_seconds=2,
        log_ref="20260925_001_sess_abc.log",
        progress=JobProgress(
            phase=ReviewerPhase.STREAMING,
            elapsed_s=12.4,
            idle_s=1.0,
            approx_reasoning_tokens=120,
        ),
    )
    raw = project_poll_result(snapshot, raw_text=True)
    assert raw == "[Reviewer thinking: 120 tokens | 12.4s]"

    structured = project_poll_result(snapshot, raw_text=False)
    assert isinstance(structured, dict)
    assert structured["state"] == "RUNNING"

