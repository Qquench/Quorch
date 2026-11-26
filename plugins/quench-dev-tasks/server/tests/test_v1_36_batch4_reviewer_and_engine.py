# -*- coding: utf-8 -*-
"""Regression tests for v1.36 Batch 4 (Tasks 36.8 & 36.9): reviewer_jobs & engine."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import time

import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from reviewer_jobs import (
    POLL_TERMINAL_FIELDS,
    JobProgress,
    JobRecord,
    JobState,
    ReviewerJobSupervisor,
    ReviewerPhase,
    is_record_orphaned,
)
import server


@pytest.mark.anyio
async def test_poll_returns_terminal_orphaned_after_watch_without_disk_write(tmp_path, monkeypatch):
    """W10 + 孤儿终态投影：watch() 识别 ORPHANED 后，2s 节流窗内调用 poll() 不回弹 RUNNING，且零写盘。"""
    monkeypatch.setattr(ReviewerJobSupervisor, "_launch_worker", lambda self, record, req: None)
    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = supervisor.submit({"query": "orphan check", "session_id": "sess_orphan"})

    old_wall = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    stale_rec = replace(
        rec,
        state=JobState.RUNNING,
        updated_wall_utc=old_wall,
        updated_monotonic=time.monotonic() - 600,
    )
    supervisor._save_job_record(stale_rec)

    rec_path = supervisor._get_record_path(stale_rec.session_id, stale_rec.job_id)
    disk_bytes_before = rec_path.read_bytes()

    snaps = []
    async for s in supervisor.watch(
        stale_rec.job_id,
        deadline_monotonic=time.monotonic() + 2.0,
        liveness_probe_interval_s=2.0,
    ):
        snaps.append(s)

    assert len(snaps) == 1
    assert snaps[0].state == "ORPHANED"

    # 紧接着在 2s 节流窗内调用 poll() 与 dev_reviewer_poll()，绝不能回弹 RUNNING
    poll_res = supervisor.poll(stale_rec.job_id, session_id="sess_orphan")
    assert set(poll_res.keys()) == POLL_TERMINAL_FIELDS
    assert poll_res["state"] == "ORPHANED"
    assert poll_res["degraded_reason"] == "orphaned"
    assert poll_res["result"]["status"] == "degraded"
    assert poll_res["result"]["findings"] == ""

    mcp_res = await server.dev_reviewer_poll(
        workspace_root=str(tmp_path),
        job_id=stale_rec.job_id,
        session_id="sess_orphan",
        wait_max_s=1,
    )
    assert mcp_res["state"] == "ORPHANED"
    assert mcp_res["result"]["findings"] == ""

    # 严守 W10 零磁盘写入契约：磁盘 record.json 字节完全未变
    assert rec_path.read_bytes() == disk_bytes_before


@pytest.mark.anyio
async def test_on_prog_refreshes_wall_clock_and_cancel_bills_live_tokens(tmp_path, monkeypatch):
    """on_prog() 加锁更新 progress 与 updated_wall_utc（防 >300s 假孤儿），且 cancel() 保留运行期 _live_tokens。"""
    import consultation

    started_event = asyncio.Event()
    release_event = asyncio.Event()

    async def fake_execute(req, log_path, *, cancel_event=None, abort_handle=None, config=None, ctx=None, on_progress=None):
        # 在 RUNNING 状态下先将 updated_wall_utc 伪造为 >300s 前，再调用 on_progress 验证其主动刷新墙钟
        curr_rec = supervisor._load_job_record(req.session_id, rec.job_id)
        if curr_rec is not None:
            stale_wall = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
            supervisor._save_job_record(
                replace(curr_rec, created_wall_utc=stale_wall, updated_wall_utc=stale_wall)
            )
        if on_progress is not None:
            on_progress(512, 12.5, "streaming", 0.2)
        started_event.set()
        while not (cancel_event and cancel_event.is_set()) and not release_event.is_set():
            await asyncio.sleep(0.02)
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError()
        return consultation.ConsultResult(
            status="ok",
            findings="done",
            mode=req.mode,
            session_id=req.session_id,
            log_path=log_path,
        )

    monkeypatch.setattr(consultation, "_execute_consultation", fake_execute)

    supervisor = ReviewerJobSupervisor(tmp_path)
    rec = supervisor.submit({"query": "long streaming", "session_id": "sess_prog_wall"})

    await asyncio.wait_for(started_event.wait(), timeout=2.0)

    loaded = supervisor._load_job_record(rec.session_id, rec.job_id)
    assert loaded is not None
    assert loaded.state == JobState.RUNNING
    assert loaded.progress is not None
    assert loaded.progress.approx_reasoning_tokens == 512
    assert is_record_orphaned(loaded, now_wall_s=time.time(), ttl_s=300.0) is False

    cancel_res = supervisor.cancel(rec.job_id, session_id="sess_prog_wall")
    assert cancel_res["state"] == "CANCELLED"
    final_rec = supervisor._load_job_record(rec.session_id, rec.job_id)
    assert final_rec is not None
    assert final_rec.tokens_billed_after_cancel is not None
    assert final_rec.tokens_billed_after_cancel >= 512
    supervisor.shutdown()


def test_windows_scandir_zero_inode_keeps_distinct_files(tmp_path, monkeypatch):
    """_snapshot_business_state_scandir 在 (st_dev, st_ino)==(0,0) 时按路径区分多文件不碰撞。"""
    from types import SimpleNamespace
    from reviewer_jobs import _new_tracker_for_poll, _snapshot_business_state_scandir

    ws = Path(tmp_path)
    fa = ws / "a.txt"
    fb = ws / "b.txt"
    fa.write_text("1", encoding="utf-8")
    fb.write_text("22", encoding="utf-8")

    orig_scandir = os.scandir

    class FakeEntry:
        def __init__(self, real_entry):
            self._e = real_entry
            self.name = real_entry.name
            self.path = real_entry.path

        def is_dir(self, follow_symlinks=False):
            return self._e.is_dir(follow_symlinks=follow_symlinks)

        def stat(self, follow_symlinks=False):
            st = self._e.stat(follow_symlinks=follow_symlinks)
            return SimpleNamespace(
                st_dev=0,
                st_ino=0,
                st_size=st.st_size,
                st_mtime_ns=st.st_mtime_ns,
                st_mode=st.st_mode,
            )

    class FakeScandir:
        def __init__(self, p):
            self._cm = orig_scandir(p)

        def __enter__(self):
            return [FakeEntry(e) for e in self._cm.__enter__()]

        def __exit__(self, *args):
            return self._cm.__exit__(*args)

    monkeypatch.setattr(os, "scandir", FakeScandir)

    tracker = _new_tracker_for_poll()
    snap = _snapshot_business_state_scandir(ws, exempt=tracker)
    assert len(snap) == 2


# ---------------------------------------------------------------------------
# Task 36.9 Regression Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stream_incomplete_read_propagates_as_degraded_not_eof(tmp_path, monkeypatch):
    """_iter_sse_payloads 遇 IncompleteRead 不得吞为正常 EOF，须上抛并在 consultation 降级为 network。"""
    import http.client
    import consultation
    from project_config import QuenchStackConfig, ReviewerEngineConfig
    from reviewer_engine import ReviewerClient

    class TruncatedSSEResp:
        def __init__(self):
            self._calls = 0
            self.closed = False

        def read(self, n: int = 8192) -> bytes:
            self._calls += 1
            if self._calls == 1:
                return b'data: {"choices":[{"delta":{"reasoning_content":"partial"}}]}\n'
            raise http.client.IncompleteRead(b"", 100)

        def close(self):
            self.closed = True

    monkeypatch.setattr("reviewer_engine._open_sse_response", lambda *a, **k: TruncatedSSEResp())
    client = ReviewerClient(
        ReviewerEngineConfig(provider="custom", base_url="http://127.0.0.1:9999/v1", max_retries=0)
    )
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: client)

    cfg = QuenchStackConfig(
        workspace_root=str(tmp_path),
        project_name="TruncSSE",
        reviewer_engine=ReviewerEngineConfig(
            provider="custom", base_url="http://127.0.0.1:9999/v1", max_retries=0
        ),
    )
    req = consultation.ConsultRequest(workspace_root=str(tmp_path), query="check stream truncation", session_id="sess_trunc")
    res = await consultation._execute_consultation(req, str(tmp_path / "trunc.log"), config=cfg)
    assert res.status == "degraded"
    assert res.findings == ""
    assert res.degraded_reason == "network"


@pytest.mark.anyio
async def test_abort_handle_binds_response_and_prevents_worker_deadlock(tmp_path, monkeypatch):
    """AbortHandle.set_target 绑定响应流且早退关闭不死锁 _stream_worker。"""
    import threading
    from consultation import AbortHandle
    from project_config import ReviewerEngineConfig
    from reviewer_engine import ReviewerClient

    worker_done = threading.Event()
    resp_closed = threading.Event()

    class HugeFloodSSEResp:
        def __init__(self):
            self.count = 0

        def read(self, n: int = 8192) -> bytes:
            if resp_closed.is_set():
                worker_done.set()
                raise OSError("closed")
            self.count += 1
            if self.count > 250:
                worker_done.set()
                return b""
            return b'data: {"choices":[{"delta":{"content":"x"}}]}\n'

        def close(self):
            resp_closed.set()
            worker_done.set()

    fake_resp = HugeFloodSSEResp()
    monkeypatch.setattr("reviewer_engine._open_sse_response", lambda *a, **k: fake_resp)
    client = ReviewerClient(
        ReviewerEngineConfig(provider="custom", base_url="http://127.0.0.1:9999/v1", max_retries=0)
    )
    handle = AbortHandle()

    agen = client.stream_chat("sys", "user", abort_handle=handle)
    first = await agen.__anext__()
    assert first.text == "x"
    handle.abort()
    assert resp_closed.is_set()
    await agen.aclose()
    assert worker_done.wait(timeout=2.0)


def test_rotating_file_sink_thread_safe_concurrent_writes(tmp_path):
    """RotatingFileSink 多线程并发写、flush 与轮转在 RLock 下无撕裂/异常。"""
    import threading
    from reviewer_engine import RotatingFileSink

    sink = RotatingFileSink(str(tmp_path), session_id="conc_rot", max_bytes=1024, flush_interval_s=0.1)
    errors: list[Exception] = []

    def writer(tid: int):
        try:
            for i in range(40):
                sink.write_chunk_text(f"thread-{tid}-line-{i}-" + ("A" * 30) + "\n")
                if i % 10 == 0:
                    sink.flush()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sink.close()

    assert errors == []
    assert Path(sink.log_file).exists()


def test_consultation_telemetry_sink_normalizes_path_and_preserves_cache_api(tmp_path):
    """_get_consultation_telemetry_sink 归一化等价路径命中同一实例并保留 cache_info/cache_clear。"""
    from observability_policy import (
        _get_consultation_telemetry_sink,
        reset_consultation_telemetry_sink_cache,
    )

    reset_consultation_telemetry_sink_cache()
    sub = tmp_path / "sub"
    sub.mkdir()
    p1 = str(sub / "t.jsonl")
    p2 = str(tmp_path / "sub" / ".." / "sub" / "t.jsonl")

    s1 = _get_consultation_telemetry_sink(p1)
    s2 = _get_consultation_telemetry_sink(p2)
    assert s1 is s2
    assert _get_consultation_telemetry_sink.cache_info().currsize == 1
    _get_consultation_telemetry_sink.cache_clear()
    assert _get_consultation_telemetry_sink.cache_info().currsize == 0


def test_audit_gate_interoperates_with_file_verdict_audit_sink(tmp_path):
    """server._check_audit_gate 可直接识别 FileVerdictAuditSink 写入的 ts + payload 记录。"""
    import yaml
    from observability_policy import FileVerdictAuditSink
    from project_config import canonical_artifact_ref, load_project_config
    from state_machine import TaskItem

    ws = tmp_path
    (ws / ".agents").mkdir(parents=True, exist_ok=True)
    (ws / "docs" / "dev_tasks").mkdir(parents=True, exist_ok=True)
    v_path = ws / ".agents" / "logs" / "reviewer" / "verdicts.jsonl"
    (ws / ".agents" / "quench_stack.yaml").write_text(
        yaml.safe_dump(
            {
                "project_name": "GateInterop",
                "dev_tasks_dir": "docs/dev_tasks",
                "governance_scope": {"managed_paths": ["src/**"], "unmanaged_paths": ["docs/**"]},
                "observability": {"verdict_path": ".agents/logs/reviewer/verdicts.jsonl"},
                "audit_gate": {"enabled": True, "on_missing_record": "block", "on_degraded": "block"},
            }
        ),
        encoding="utf-8",
    )
    cfg = load_project_config(str(ws))
    ref = canonical_artifact_ref(str(ws), "docs/dev_tasks/t.md", "36.9")

    sink = FileVerdictAuditSink(str(v_path))
    sink.emit_verdict(
        task_id="36.9",
        verdict_hash="sha256:test",
        payload={"context_files": [ref], "status": "ok"},
    )

    task = TaskItem(id="36.9", title="T", status="⬜ 待确认", line_number=1, raw_line="")
    setattr(task, "affected_files", ["[MODIFY] src/app.py"])
    res = server._check_audit_gate(str(ws), "docs/dev_tasks/t.md", task, cfg)
    assert res["allowed"] is True
    assert res["reason"] == "matched"


def test_architecture_doc_path_traversal_confined(tmp_path):
    """PromptAssembler.build_static_system_prefix 与 consultation.build_static_prefix 禁锢越界 architecture_doc。"""
    import consultation
    from project_config import QuenchStackConfig
    from reviewer_engine import PromptAssembler

    outside = tmp_path / "outside_secret_arch.md"
    outside.write_text("TOP_SECRET_OUTSIDE_CONTENT", encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = QuenchStackConfig(
        workspace_root=str(ws),
        project_name="ConfineTest",
        architecture_doc="../outside_secret_arch.md",
    )
    prefix1 = PromptAssembler.build_static_system_prefix(str(ws), cfg)
    prefix2 = consultation.build_static_prefix(str(ws), cfg)
    assert "TOP_SECRET_OUTSIDE_CONTENT" not in prefix1
    assert "TOP_SECRET_OUTSIDE_CONTENT" not in prefix2

