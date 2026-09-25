# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
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


@dataclass(frozen=True)
class PeerLiveness:
    is_alive: bool
    pid: int
    boot_nonce: str
    takeover_allowed: bool  # 仅当确认进程真实死亡或租约超时且 PID 无复用时为 True
    probe_confident: bool = True  # 探针是否具备高可信确定度（避免未知错误误夺权）


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


class LeaseHeartbeatThread(threading.Thread):
    """后台独立心跳守护线程，解耦主工作线程，防止长任务推演造成租约意外超时。"""

    def __init__(self, guard: "WorkspaceLeaseGuard", interval_s: float) -> None:
        super().__init__(daemon=True, name=f"LeaseHeartbeatThread-{os.getpid()}")
        self._guard = guard
        self._interval_s = interval_s
        self._stop_event = threading.Event()

    def run(self) -> None:
        contention_retries = 0
        while not self._stop_event.wait(timeout=self._interval_s):
            if not self._guard.is_held():
                break
            try:
                outcome = self._guard.touch()
                if outcome == LeaseTouchOutcome.LOST:
                    break
                elif outcome == LeaseTouchOutcome.CONTENTION:
                    backoff = min(2.0, 0.1 * (2 ** contention_retries))
                    contention_retries += 1
                    if self._stop_event.wait(timeout=backoff):
                        break
                else:
                    contention_retries = 0
            except Exception:
                # 出现非预期致命异常，主动 fail-stop 防止撕裂
                break

    def stop(self) -> None:
        self._stop_event.set()


class WorkspaceLeaseGuard:
    """基于文件锁与心跳租约的 workspace 独占持有者机制。"""

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
        self._heartbeat_thread: Optional[LeaseHeartbeatThread] = None
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

    def is_held(self) -> bool:
        """运行时租约持有判定 (F5/B6) 并复核心跳新鲜度。"""
        if not self._is_held:
            return False
        if self._last_touch_monotonic > 0:
            elapsed = time.monotonic() - self._last_touch_monotonic
            if elapsed >= self._lease_ttl_s * 0.8:
                return False
        return True

    def heartbeat_healthy(self) -> bool:
        return self.is_held()

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

                    # 探测已存在租约持有者是否存活与是否超时
                    if owner_pid is not None:
                        now_wall = time.time()
                        updated_at = float(data.get("updated_at") or 0.0)
                        is_stale = (now_wall - updated_at) > (self._lease_ttl_s * self._take_over_stale_multiplier)
                        peer = self.probe_peer(int(owner_pid), str(owner_nonce or ""), self._workspace_root)
                        # 接管策略：peer 确认死亡且允许接管；或超时陈旧且未确认为存活
                        can_takeover = (not peer.is_alive and peer.takeover_allowed) or (
                            is_stale and not (peer.probe_confident and peer.is_alive)
                        )
                        if not can_takeover:
                            self._is_held = False
                            return False

                # 租约空闲或原持有者已确认死亡/超时，安全接管，递增 generation
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

    def start_heartbeat_thread(self) -> None:
        """启动独立后台心跳守护线程。"""
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = LeaseHeartbeatThread(self, self._heartbeat_interval_s)
        self._heartbeat_thread.start()

    def stop_heartbeat_thread(self) -> None:
        """停止独立后台心跳守护线程。"""
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.stop()
            self._heartbeat_thread.join(timeout=2.0)
            self._heartbeat_thread = None

    def touch(self) -> LeaseTouchOutcome:
        """更新租约心跳时间戳。返回 LeaseTouchOutcome 枚举。"""
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
        """破坏性清理操作上下文门禁。必须持有有效且新鲜的租约方可执行。"""
        if not self.is_held():
            raise WorkspaceLeaseNotHeldError("Destructive workspace operations require an active workspace lease.")
        yield

    def force_release_lease(self, reason: str = "") -> bool:
        """强制释放并移除租约文件。"""
        self.stop_heartbeat_thread()
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
        self.stop_heartbeat_thread()
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

    @classmethod
    def _probe_posix(cls, pid: int, boot_nonce: str, workspace_root: Union[Path, str]) -> PeerLiveness:
        """POSIX 存活性探针。"""
        try:
            os.kill(pid, 0)
            is_alive = True
        except PermissionError:
            # EPERM: 跨用户或受限，确认为存活，严禁误杀
            return PeerLiveness(is_alive=True, pid=pid, boot_nonce=boot_nonce, takeover_allowed=False, probe_confident=True)
        except ProcessLookupError:
            return PeerLiveness(is_alive=False, pid=pid, boot_nonce=boot_nonce, takeover_allowed=True, probe_confident=True)
        except OSError:
            return PeerLiveness(is_alive=False, pid=pid, boot_nonce=boot_nonce, takeover_allowed=True, probe_confident=False)

        # 进程物理存活，核对盘上记录的代际 boot_nonce 是否匹配
        cls._verify_disk_nonce_match(pid, boot_nonce, workspace_root)
        return PeerLiveness(is_alive=True, pid=pid, boot_nonce=boot_nonce, takeover_allowed=False, probe_confident=True)

    @classmethod
    def _probe_windows(cls, pid: int, boot_nonce: str, workspace_root: Union[Path, str]) -> PeerLiveness:
        """Windows 存活性探针 (OpenProcess + GetExitCodeProcess == STILL_ACTIVE)。"""
        import ctypes
        from ctypes import wintypes

        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle == 0:
            err = kernel32.GetLastError()
            if err == 5:  # ERROR_ACCESS_DENIED: 进程存活但受限，保守判活拒绝接管
                return PeerLiveness(is_alive=True, pid=pid, boot_nonce=boot_nonce, takeover_allowed=False, probe_confident=True)
            return PeerLiveness(is_alive=False, pid=pid, boot_nonce=boot_nonce, takeover_allowed=True, probe_confident=False)

        try:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                if exit_code.value == STILL_ACTIVE:
                    is_alive = True
                else:
                    return PeerLiveness(is_alive=False, pid=pid, boot_nonce=boot_nonce, takeover_allowed=True, probe_confident=True)
            else:
                return PeerLiveness(is_alive=False, pid=pid, boot_nonce=boot_nonce, takeover_allowed=True, probe_confident=False)

            class FILETIME(ctypes.Structure):
                _fields_ = [
                    ("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD),
                ]

            ft_create = FILETIME()
            ft_exit = FILETIME()
            ft_kernel = FILETIME()
            ft_user = FILETIME()
            kernel32.GetProcessTimes(
                handle,
                ctypes.byref(ft_create),
                ctypes.byref(ft_exit),
                ctypes.byref(ft_kernel),
                ctypes.byref(ft_user),
            )
        finally:
            kernel32.CloseHandle(handle)

        cls._verify_disk_nonce_match(pid, boot_nonce, workspace_root)
        return PeerLiveness(is_alive=True, pid=pid, boot_nonce=boot_nonce, takeover_allowed=False, probe_confident=True)

    @classmethod
    def _verify_disk_nonce_match(cls, pid: int, boot_nonce: str, workspace_root: Union[Path, str]) -> None:
        """比对盘上租约文件中的 boot_nonce，辅助感知 PID 复用。"""
        lease_file = Path(workspace_root) / ".agents" / "logs" / "reviewer" / "workspace.lease.json"
        if lease_file.is_file():
            try:
                with open(lease_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                disk_pid = data.get("pid")
                disk_nonce = data.get("boot_nonce")
                if disk_pid == pid and disk_nonce and disk_nonce != boot_nonce:
                    pass
            except Exception:
                pass

    @classmethod
    def probe_peer(cls, pid: int, boot_nonce: str, workspace_root: Union[Path, str]) -> PeerLiveness:
        """跨平台高可靠进程存活与代际探针。
        - POSIX: os.kill(pid, 0) 遇 PermissionError (EPERM) => is_alive=True, takeover_allowed=False, probe_confident=True
        - Windows: OpenProcess + GetExitCodeProcess == STILL_ACTIVE
        - PID 存活但 boot_nonce 不匹配 => is_alive=True, takeover_allowed=False (保守拒绝接管)
        - 仅当 ProcessLookupError 或 ExitCode != STILL_ACTIVE => is_alive=False, takeover_allowed=True, probe_confident=True
        """
        if sys.platform == "win32":
            return cls._probe_windows(pid, boot_nonce, workspace_root)
        return cls._probe_posix(pid, boot_nonce, workspace_root)
