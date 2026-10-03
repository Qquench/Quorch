# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Final, Iterator, Optional, Union

from filelock import FileLock, Timeout


class WorkspaceLeaseNotHeldError(RuntimeError):
    """当破坏性清理或独占操作未持有有效 workspace 租约时抛出。"""
    pass


class LeaseGenerationLostError(RuntimeError):
    """当租约代际失配（已被他进程递增夺权）时抛出。"""
    pass


class LeaseTouchOutcome(Enum):
    RENEWED = "renewed"
    LOST = "lost"
    CONTENTION = "contention"


def _atomic_write_json(file_path: Path, data: dict) -> None:
    """原子化写入 JSON 文件，带 Windows WinError 32 共享冲突有界重试与落盘 fsync。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = file_path.with_suffix(f".tmp.{os.getpid()}.{time.time_ns()}")
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())

    max_retries = 5
    for attempt in range(max_retries):
        try:
            os.replace(temp_file, file_path)
            # 尝试 fsync 父目录（POSIX）
            try:
                dir_fd = os.open(str(file_path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception:
                pass
            return
        except (PermissionError, OSError):
            if attempt == max_retries - 1:
                try:
                    if temp_file.exists():
                        temp_file.unlink()
                except Exception:
                    pass
                raise
            time.sleep(0.02 * (2 ** attempt))


class WorkspaceLeaseGuard:
    """基于文件锁与 TTL + generation CAS 的 workspace 独占持有者机制。

    【Touch Checkpoint 契约】
    持有者可安全保留租约的最长无 touch() 间隔必须 < lease_ttl_s * 0.5。
    调用方在执行长任务或跨越该间隔时必须显式调用 touch() 刷新时间戳。
    """

    def __init__(
        self,
        workspace_root: Union[Path, str],
        *,
        lease_ttl_s: float = 300.0,
        heartbeat_interval_s: float = 30.0,
        take_over_stale_multiplier: float = 3.0,
    ) -> None:
        if not (0 < heartbeat_interval_s < lease_ttl_s):
            raise ValueError(
                f"heartbeat_interval_s ({heartbeat_interval_s}) must be > 0 and < lease_ttl_s ({lease_ttl_s})"
            )
        if take_over_stale_multiplier <= 0:
            raise ValueError(
                f"take_over_stale_multiplier ({take_over_stale_multiplier}) must be > 0"
            )

        self._workspace_root = Path(workspace_root).resolve()
        self._lease_ttl_s = float(lease_ttl_s)
        self._heartbeat_interval_s = float(heartbeat_interval_s)
        self._take_over_stale_multiplier = float(take_over_stale_multiplier)

        self._lease_dir = self._workspace_root / ".agents" / "logs" / "reviewer"
        self._lease_file = self._lease_dir / "workspace.lease.json"
        self._lock_file = self._lease_dir / "workspace.lease.lock"

        self._boot_nonce: Optional[str] = None
        self._is_held: bool = False
        self._generation: int = 0
        self._last_touch_monotonic: float = 0.0
        self._lock = FileLock(str(self._lock_file), timeout=5.0)

    @property
    def lease_file(self) -> Path:
        return self._lease_file

    @property
    def lock_file(self) -> Path:
        return self._lock_file

    @property
    def boot_nonce(self) -> Optional[str]:
        return self._boot_nonce

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def lease_ttl_s(self) -> float:
        return self._lease_ttl_s

    def is_held(self) -> bool:
        """纯本地持有标志。新鲜度由调用方按 touch() checkpoint 契约自行维护。"""
        return self._is_held

    def acquire_or_probe(self, boot_nonce: str) -> bool:
        """尝试获取或接管 workspace 租约。若已被合法进程持有则返回 False。"""
        if not boot_nonce:
            raise ValueError("boot_nonce must not be empty")

        self._lease_dir.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock:
                data = {}
                if self._lease_file.is_file():
                    try:
                        with open(self._lease_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        data = {}

                    owner_pid = data.get("pid")
                    owner_nonce = data.get("boot_nonce")

                    # 若当前进程已持有相同 boot_nonce，直接续约成功
                    if owner_pid == os.getpid() and owner_nonce == boot_nonce:
                        data["updated_at"] = time.time()
                        _atomic_write_json(self._lease_file, data)
                        self._is_held = True
                        self._boot_nonce = boot_nonce
                        self._generation = int(data.get("generation", 1))
                        self._last_touch_monotonic = time.monotonic()
                        return True

                    # 若已存在租约持有者，仅以 TTL 超时判定是否可接管（不再嗅探进程）
                    if owner_pid is not None:
                        now_wall = time.time()
                        updated_at = float(data.get("updated_at") or 0.0)
                        is_stale = (now_wall - updated_at) > (self._lease_ttl_s * self._take_over_stale_multiplier)
                        if not is_stale:
                            self._is_held = False
                            return False

                # 租约空闲或原持有者已确认超时，安全接管，递增 generation
                now = time.time()
                old_gen = int(data.get("generation", 0))
                new_gen = old_gen + 1
                data = {
                    "pid": os.getpid(),
                    "boot_nonce": boot_nonce,
                    "generation": new_gen,
                    "acquired_at": now,
                    "updated_at": now,
                    "lease_ttl_s": self._lease_ttl_s,
                    "heartbeat_interval_s": self._heartbeat_interval_s,
                }
                _atomic_write_json(self._lease_file, data)
                self._is_held = True
                self._boot_nonce = boot_nonce
                self._generation = new_gen
                self._last_touch_monotonic = time.monotonic()
                return True
        except Exception:
            self._is_held = False
            return False

    def touch(self) -> LeaseTouchOutcome:
        """更新租约心跳时间戳。返回 LeaseTouchOutcome 枚举。
        
        【Touch Checkpoint 契约】
        持有者可安全保留租约的最长无 touch() 间隔 = lease_ttl_s * 0.5。
        """
        if not self._is_held or not self._boot_nonce:
            return LeaseTouchOutcome.LOST

        try:
            with FileLock(str(self._lock_file), timeout=1.0):
                if not self._lease_file.is_file():
                    self._is_held = False
                    return LeaseTouchOutcome.LOST
                try:
                    with open(self._lease_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    self._is_held = False
                    return LeaseTouchOutcome.LOST

                disk_pid = data.get("pid")
                disk_nonce = data.get("boot_nonce")
                disk_gen = data.get("generation")

                if (
                    disk_pid != os.getpid()
                    or disk_nonce != self._boot_nonce
                    or (self._generation and disk_gen != self._generation)
                ):
                    self._is_held = False
                    return LeaseTouchOutcome.LOST

                data["updated_at"] = time.time()
                _atomic_write_json(self._lease_file, data)
                self._last_touch_monotonic = time.monotonic()
                return LeaseTouchOutcome.RENEWED
        except Timeout:
            return LeaseTouchOutcome.CONTENTION
        except Exception:
            self._is_held = False
            return LeaseTouchOutcome.LOST

    def renew_or_die(self) -> None:
        """心跳续约或立即 fail-stop。"""
        outcome = self.touch()
        if outcome == LeaseTouchOutcome.LOST:
            raise WorkspaceLeaseNotHeldError("Workspace lease has been lost or taken over by another process.")

    @contextmanager
    def destructive_context(self) -> Iterator[None]:
        """破坏性清理操作上下文门禁。必须持有有效租约方可执行。"""
        if not self.is_held():
            raise WorkspaceLeaseNotHeldError("Destructive workspace operations require an active workspace lease.")
        yield

    def force_release_lease(self, reason: str = "") -> bool:
        """强制释放并移除租约文件。"""
        try:
            with self._lock:
                if self._lease_file.is_file():
                    self._lease_file.unlink(missing_ok=True)
            self._is_held = False
            self._boot_nonce = None
            return True
        except Exception:
            self._is_held = False
            return False

    def release(self) -> None:
        """保证幂等：多次调用、未持有锁或盘上文件已删均安全返回 (N1)。"""
        if not self._is_held:
            return

        try:
            with self._lock:
                if self._lease_file.is_file():
                    try:
                        with open(self._lease_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if data.get("pid") == os.getpid() and data.get("boot_nonce") == self._boot_nonce:
                            self._lease_file.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            self._is_held = False
            self._boot_nonce = None
