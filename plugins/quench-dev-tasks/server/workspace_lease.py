# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Optional, Union

from filelock import FileLock


class WorkspaceLeaseNotHeldError(RuntimeError):
    """当破坏性清理操作未持有有效 workspace 租约时抛出。"""
    pass


@dataclass(frozen=True)
class PeerLiveness:
    is_alive: bool
    pid: int
    boot_nonce: str
    takeover_allowed: bool  # 仅当确认进程真实死亡或租约超时且 PID 无复用时为 True


def _atomic_write_json(file_path: Path, data: dict) -> None:
    """原子化写入 JSON 文件，带 Windows WinError 32 共享冲突有界重试。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = file_path.with_suffix(f".tmp.{os.getpid()}.{time.time_ns()}")
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(payload)

    max_retries = 5
    for attempt in range(max_retries):
        try:
            os.replace(temp_file, file_path)
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
        while not self._stop_event.wait(timeout=self._interval_s):
            if not self._guard.is_held():
                break
            try:
                if not self._guard.touch():
                    break
            except Exception:
                pass

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
    ) -> None:
        assert 0 < heartbeat_interval_s < lease_ttl_s, (
            f"heartbeat_interval_s ({heartbeat_interval_s}) must be > 0 and < lease_ttl_s ({lease_ttl_s})"
        )
        self._workspace_root = Path(workspace_root).resolve()
        self._lease_ttl_s = float(lease_ttl_s)
        self._heartbeat_interval_s = float(heartbeat_interval_s)

        self._lease_dir = self._workspace_root / ".agents" / "logs" / "reviewer"
        self._lease_file = self._lease_dir / "workspace.lease.json"
        self._lock_file = self._lease_dir / "workspace.lease.lock"

        self._boot_nonce: Optional[str] = None
        self._is_held: bool = False
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

    def is_held(self) -> bool:
        """运行时租约持有判定 (F5/B6)。"""
        return self._is_held

    def acquire_or_probe(self, boot_nonce: str) -> bool:
        """尝试获取或接管 workspace 租约。若已被合法进程持有则返回 False。"""
        if not boot_nonce:
            raise ValueError("boot_nonce must not be empty")

        self._lease_dir.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(self._lock_file), timeout=5.0):
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
                        return True

                    # 探测已存在租约持有者是否存活
                    if owner_pid is not None:
                        peer = self.probe_peer(int(owner_pid), str(owner_nonce or ""), self._workspace_root)
                        if not peer.takeover_allowed:
                            self._is_held = False
                            return False

                # 租约空闲或原持有者已确认死亡，安全接管
                now = time.time()
                data = {
                    "pid": os.getpid(),
                    "boot_nonce": boot_nonce,
                    "acquired_at": now,
                    "updated_at": now,
                    "lease_ttl_s": self._lease_ttl_s,
                    "heartbeat_interval_s": self._heartbeat_interval_s,
                }
                _atomic_write_json(self._lease_file, data)
                self._is_held = True
                self._boot_nonce = boot_nonce
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

    def touch(self) -> bool:
        """更新租约心跳时间戳。仅当持有租约时有效。"""
        if not self._is_held or not self._boot_nonce:
            return False

        try:
            with FileLock(str(self._lock_file), timeout=2.0):
                if not self._lease_file.is_file():
                    self._is_held = False
                    return False
                try:
                    with open(self._lease_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    self._is_held = False
                    return False

                if data.get("pid") != os.getpid() or data.get("boot_nonce") != self._boot_nonce:
                    self._is_held = False
                    return False

                data["updated_at"] = time.time()
                _atomic_write_json(self._lease_file, data)
                return True
        except Exception:
            return False

    def release(self) -> None:
        """保证幂等：多次调用、未持有锁或盘上文件已删均安全返回 (N1)。"""
        self.stop_heartbeat_thread()
        if not self._is_held:
            return

        try:
            if self._lease_file.is_file():
                try:
                    with FileLock(str(self._lock_file), timeout=2.0):
                        if self._lease_file.is_file():
                            try:
                                with open(self._lease_file, "r", encoding="utf-8") as f:
                                    data = json.load(f)
                                if data.get("pid") == os.getpid() and data.get("boot_nonce") == self._boot_nonce:
                                    try:
                                        self._lease_file.unlink()
                                    except FileNotFoundError:
                                        pass
                            except Exception:
                                pass
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
            return PeerLiveness(is_alive=True, pid=pid, boot_nonce=boot_nonce, takeover_allowed=False)
        except (ProcessLookupError, OSError):
            return PeerLiveness(is_alive=False, pid=pid, boot_nonce=boot_nonce, takeover_allowed=True)

        # 进程物理存活，核对盘上记录的代际 boot_nonce 是否匹配
        cls._verify_disk_nonce_match(pid, boot_nonce, workspace_root)
        return PeerLiveness(is_alive=True, pid=pid, boot_nonce=boot_nonce, takeover_allowed=False)

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
            if err == 5:  # ERROR_ACCESS_DENIED
                return PeerLiveness(is_alive=True, pid=pid, boot_nonce=boot_nonce, takeover_allowed=False)
            return PeerLiveness(is_alive=False, pid=pid, boot_nonce=boot_nonce, takeover_allowed=True)

        try:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                if exit_code.value == STILL_ACTIVE:
                    is_alive = True
                else:
                    return PeerLiveness(is_alive=False, pid=pid, boot_nonce=boot_nonce, takeover_allowed=True)
            else:
                return PeerLiveness(is_alive=False, pid=pid, boot_nonce=boot_nonce, takeover_allowed=True)

            # 可选读取创建时间推导代际信息
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
        return PeerLiveness(is_alive=True, pid=pid, boot_nonce=boot_nonce, takeover_allowed=False)

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
                    # PID 存活但与盘上 nonce 不一致，异代进程
                    pass
            except Exception:
                pass

    @classmethod
    def probe_peer(cls, pid: int, boot_nonce: str, workspace_root: Union[Path, str]) -> PeerLiveness:
        """跨平台高可靠进程存活与代际探针。
        - POSIX: os.kill(pid, 0) 遇 PermissionError (EPERM) => is_alive=True, takeover_allowed=False
        - Windows: OpenProcess + GetExitCodeProcess == STILL_ACTIVE
        - PID 存活但 boot_nonce 不匹配 => is_alive=True, takeover_allowed=False (保守拒绝接管)
        - 仅当 ProcessLookupError 或 ExitCode != STILL_ACTIVE => is_alive=False, takeover_allowed=True
        """
        if sys.platform == "win32":
            return cls._probe_windows(pid, boot_nonce, workspace_root)
        return cls._probe_posix(pid, boot_nonce, workspace_root)
