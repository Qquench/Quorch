# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from progress_bridge import ProgressBridge
from reviewer_jobs import PollSnapshot, SnapshotContractViolation


class FakeRequestContext:
    def __init__(self, token: str | None = "token_123"):
        self.meta = {"progressToken": token} if token is not None else {}


class FakeContext:
    def __init__(self, token: str | None = "token_123", supports_message: bool = True):
        self.request_context = FakeRequestContext(token)
        self.emitted_progress: list[dict[str, Any]] = []
        self._supports_message = supports_message

    def report_progress(self, progress: int, total: int | None = None, message: str | None = None):
        entry = {"progress": progress, "total": total, "message": message}
        self.emitted_progress.append(entry)
        return None


class FakeContextLegacy:
    """老版本 FastMCP，report_progress 不支持 message 形参。"""
    def __init__(self, token: str = "token_123"):
        self.request_context = FakeRequestContext(token)
        self.emitted_progress: list[dict[str, Any]] = []

    def report_progress(self, progress: int, total: int | None = None):
        entry = {"progress": progress, "total": total}
        self.emitted_progress.append(entry)
        return None


def make_snapshot(
    job_id: str = "job_1",
    state: str = "RUNNING",
    phase: str = "streaming",
    elapsed_s: int = 10,
    progress: dict | None = None,
) -> PollSnapshot:
    return PollSnapshot(
        job_id=job_id,
        session_id="sess_1",
        state=state,
        retry_after_seconds=5,
        log_ref="20261022_001_sess.log",
        elapsed_s=elapsed_s,
        progress=progress if progress is not None else {},
        generation=1,
        phase=phase,
    )


@pytest.mark.tier1_fast
def test_from_context_none_when_no_token():
    """严格遵循 MCP 规范：客户端未显式提供 progressToken 时 MUST NOT 发送进度通知。"""
    ctx_no_meta = FakeContext(token=None)
    assert ProgressBridge.from_context(ctx_no_meta) is None

    assert ProgressBridge.from_context(None) is None
    assert ProgressBridge.from_context(object()) is None


@pytest.mark.tier1_fast
def test_from_context_with_token_and_signature_detection():
    """正常嗅探 progressToken 并探测 report_progress 是否支持 message 形参。"""
    ctx = FakeContext(token="valid_token")
    bridge = ProgressBridge.from_context(ctx)
    assert bridge is not None
    assert bridge._supports_message is True

    ctx_legacy = FakeContextLegacy(token="valid_token")
    bridge_legacy = ProgressBridge.from_context(ctx_legacy)
    assert bridge_legacy is not None
    assert bridge_legacy._supports_message is False


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_emit_first_frame_not_over_coalesced():
    """B-1: 穿透判据精细拆分与首帧防风暴。
    - 首帧（_last_phase is None）不豁免合流；
    - 同一状态/phase 在 1.0s 内重复调用被正常合流过滤；
    - 非首帧且 phase 变迁（self._last_phase is not None）穿透合流限制。
    """
    ctx = FakeContext()
    cur_time = 100.0
    clock = lambda: cur_time
    bridge = ProgressBridge.from_context(ctx, min_interval_s=1.0, clock=clock)
    assert bridge is not None

    snap1 = make_snapshot(state="RUNNING", phase="assembling", elapsed_s=1)
    await bridge.emit(snap1)
    assert len(ctx.emitted_progress) == 1
    assert ctx.emitted_progress[0]["progress"] == 1

    # 0.1s 后，同一状态与 phase，且未 force：被合流过滤
    cur_time = 100.1
    snap2 = make_snapshot(state="RUNNING", phase="assembling", elapsed_s=1)
    await bridge.emit(snap2)
    assert len(ctx.emitted_progress) == 1

    # 0.2s 后，phase 发生变化 (assembling -> streaming) 且 _last_phase 不为 None：强制穿透！
    cur_time = 100.2
    snap3 = make_snapshot(state="RUNNING", phase="streaming", elapsed_s=1)
    await bridge.emit(snap3)
    assert len(ctx.emitted_progress) == 2
    assert ctx.emitted_progress[1]["progress"] == 2
    assert "streaming" in str(ctx.emitted_progress[1]["message"])


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_penetration_on_state_change():
    """B-1: 任务状态发生变迁时（如 QUEUED -> RUNNING），强制穿透合流窗口。"""
    ctx = FakeContext()
    cur_time = 100.0
    clock = lambda: cur_time
    bridge = ProgressBridge.from_context(ctx, min_interval_s=1.0, clock=clock)

    snap1 = make_snapshot(state="QUEUED", phase="QUEUED")
    await bridge.emit(snap1)
    assert len(ctx.emitted_progress) == 1

    # 仅间隔 0.05s，但 state 变为 RUNNING：强制穿透
    cur_time = 100.05
    snap2 = make_snapshot(state="RUNNING", phase="streaming")
    await bridge.emit(snap2)
    assert len(ctx.emitted_progress) == 2
    assert "[RUNNING]" in ctx.emitted_progress[1]["message"]


@pytest.mark.tier1_fast
def test_emit_must_not_read_progress_fields():
    """B-1 / INV-3 / INV-8: 零 progress 直读。
    静态断言 progress_bridge.py 源码中零 'snapshot.progress' 引用，严禁直读 progress 容器。
    """
    bridge_file = Path(__file__).resolve().parent.parent / "progress_bridge.py"
    content = bridge_file.read_text(encoding="utf-8")
    assert "snapshot.progress" not in content, "Direct reading of snapshot.progress is forbidden by INV-3/INV-8"


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_emit_raises_contract_violation():
    """P1-NEW-3: 契约违规异常优先透传。
    SnapshotContractViolation 必须重抛，绝不被当作普通网络错误被吞灭或触发熔断。
    """
    ctx = FakeContext()
    bridge = ProgressBridge.from_context(ctx)

    # 传入非 PollSnapshot 类型
    with pytest.raises(SnapshotContractViolation):
        await bridge.emit("not_a_snapshot")  # type: ignore

    # 熔断开关必须依然为 False
    assert bridge._disabled is False


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_fail_open_on_network_exception():
    """网络与传输异常时执行一次性熔断 fail-open，不阻塞主业务。"""
    ctx = FakeContext()

    def buggy_report(*args, **kwargs):
        raise ConnectionResetError("Remote client disconnected")

    ctx.report_progress = buggy_report
    bridge = ProgressBridge.from_context(ctx)

    snap = make_snapshot()
    # emit 绝不抛出 ConnectionResetError
    await bridge.emit(snap)
    assert bridge._disabled is True

    # 后续 emit 直接静默跳过
    await bridge.emit(snap)
    assert bridge._disabled is True


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_thinking_content_leak_defense():
    """P1-9 / INV-3 / INV-8: 思考文本泄露防线。
    进度 message 必须单行、UTF-8 长度 <= 120 字节，严禁泄露任何 reasoning/findings 敏感文本。
    """
    ctx = FakeContext()
    bridge = ProgressBridge.from_context(ctx)

    secret_findings = "CONFIDENTIAL_THINKING_COT_DATA_XYZ"
    snap = make_snapshot(
        state="RUNNING",
        phase="streaming",
        elapsed_s=15,
        progress={"findings": secret_findings, "reasoning": secret_findings},
    )
    await bridge.emit(snap)

    assert len(ctx.emitted_progress) == 1
    msg = ctx.emitted_progress[0]["message"]
    assert secret_findings not in msg
    assert len(msg.encode("utf-8")) <= 120
    assert "\r" not in msg
    assert "\n" not in msg
    assert "`" not in msg


@pytest.mark.tier1_fast
@pytest.mark.anyio
async def test_cancelled_error_passthrough():
    """W8: 取消透传：CancelledError 自然向上透传，不被当作普通 Exception 吞灭。"""
    ctx = FakeContext()

    async def cancelled_report(*args, **kwargs):
        raise asyncio.CancelledError()

    ctx.report_progress = cancelled_report
    bridge = ProgressBridge.from_context(ctx)

    with pytest.raises(asyncio.CancelledError):
        await bridge.emit(make_snapshot())
