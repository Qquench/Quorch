# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from reviewer_jobs import PollSnapshot, SnapshotContractViolation


@dataclass
class ProgressBridge:
    _ctx: Any
    _min_interval_s: float = 1.0
    _counter: int = 0
    _disabled: bool = False
    _supports_message: bool = True
    _last_state: Optional[str] = None
    _last_phase: Optional[str] = None
    _last_emit_mono: float = -float("inf")
    _clock: Callable[[], float] = time.monotonic

    @classmethod
    def from_context(
        cls,
        ctx: Any,
        *,
        min_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> Optional["ProgressBridge"]:
        """安全嗅探 ctx.request_context.meta 中的 progressToken。
        客户端未显式提供 progressToken 或非合规 ctx 时，安全返回 None。
        """
        if ctx is None:
            return None

        # 检查 report_progress 方法
        report_fn = getattr(ctx, "report_progress", None)
        if report_fn is None or not callable(report_fn):
            return None

        # 嗅探 progressToken
        token = None
        req_ctx = getattr(ctx, "request_context", None)
        if req_ctx is not None:
            meta = getattr(req_ctx, "meta", None)
            if isinstance(meta, dict):
                token = meta.get("progressToken") or meta.get("progress_token")
            elif meta is not None:
                token = getattr(meta, "progressToken", None) or getattr(meta, "progress_token", None)

        if token is None:
            # 兼容顶层直接属性探测
            token = getattr(ctx, "progress_token", None) or getattr(ctx, "progressToken", None)

        if token is None:
            return None

        # 探测 report_progress 是否支持 message 形参 (P1-10)
        supports_message = True
        try:
            sig = inspect.signature(report_fn)
            supports_message = "message" in sig.parameters
        except Exception:
            supports_message = True

        return cls(
            _ctx=ctx,
            _min_interval_s=min_interval_s,
            _supports_message=supports_message,
            _clock=clock,
        )

    async def emit(self, snapshot: PollSnapshot, *, force: bool = False) -> None:
        """发送进度通知。
        - 语法严格前置的分层异常捕获：先 except SnapshotContractViolation: raise，后置 except Exception: fail-open
        - 严禁读取底层内部 progress 容器字典 (INV-3 / INV-8)
        - 穿透判据：force = (snapshot.state != self._last_state) or (snapshot.phase != self._last_phase and self._last_phase is not None)
        - 首帧明确不豁免合流 (_last_phase is None 时 phase 不强制穿透)
        - 1.0s 最小合流间隔
        - 不超过 120 字符单行消息裁剪，去除 \\r/\\n/`
        - anyio 取消异常自然透传
        """
        if self._disabled:
            return

        # 强类型契约防御 (P1-10)
        if not isinstance(snapshot, PollSnapshot):
            raise SnapshotContractViolation(
                f"ProgressBridge.emit expects PollSnapshot, got {type(snapshot).__name__}"
            )

        now_mono = self._clock()

        # 穿透判据精细拆分 (B-1):
        # 1. 显式 force
        # 2. state 变化 (QUEUED -> RUNNING 等)
        # 3. phase 变化，且显式要求 self._last_phase is not None (首帧防风暴)
        penetrated = force or (snapshot.state != self._last_state) or (
            snapshot.phase != self._last_phase and self._last_phase is not None
        )

        if not penetrated:
            # 未穿透时，遵循 min_interval_s 最小合流间隔
            if (now_mono - self._last_emit_mono) < self._min_interval_s:
                return

        # 计数器单调自增
        self._counter += 1

        # 格式化 <= 120 字符单行无换行消息 (INV-4)
        # 严禁读取底层内部 progress 容器键，严禁泄露 reasoning/findings (P1-9)
        raw_msg = f"[{snapshot.state}] phase={snapshot.phase} elapsed={snapshot.elapsed_s}s #{self._counter}"
        clean_msg = re.sub(r"[\r\n`]+", " ", raw_msg).strip()
        msg_bytes = clean_msg.encode("utf-8")
        if len(msg_bytes) > 120:
            clean_msg = msg_bytes[:120].decode("utf-8", errors="ignore")

        self._last_state = snapshot.state
        self._last_phase = snapshot.phase
        self._last_emit_mono = now_mono

        # 严格前置分层异常捕获：handlers 顺序必须先写 SnapshotContractViolation，后置 Exception (P1-NEW-3)
        try:
            if self._supports_message:
                res = self._ctx.report_progress(self._counter, message=clean_msg)
            else:
                res = self._ctx.report_progress(self._counter)
            if inspect.isawaitable(res):
                await res
        except SnapshotContractViolation:
            raise
        except Exception:
            # 普通网络/传输异常，执行一次性熔断 fail-open
            self._disabled = True
