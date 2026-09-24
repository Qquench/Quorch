# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import hashlib
import inspect
import json
import multiprocessing
import os
import shutil
import tempfile
import time
from pathlib import Path
import pytest
import yaml

from manifest import (
    Manifest,
    TaskRecord,
    MANIFEST_REL_PATH,
    FencedTokenError,
    ManifestIntegrityError,
    RetryableManifestError,
    ManifestConflictError,
    mutate_manifest_under_lock,
    commit_lease,
    compare_and_swap,
    release_lease,
    touch_heartbeat,
    register_proposal,
    load_manifest,
    atomic_replace_manifest,
)


@pytest.fixture
def mock_cas_workspace():
    temp_dir = tempfile.mkdtemp(prefix="quench_cas_test_")
    agents_dir = os.path.join(temp_dir, ".agents")
    os.makedirs(agents_dir, exist_ok=True)

    config_data = {
        "project_name": "DualProcessCasTestProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "changelog_path": "CHANGELOG.md",
        "test_dir": "tests",
        "test_runner": "pytest",
        "governance": {
            "manifest_path": ".agents/.quorch/manifest.json",
            "lease_ttl_seconds": 300,
        },
    }
    with open(os.path.join(agents_dir, "quench_stack.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    tasks_dir = os.path.join(temp_dir, "docs", "dev_tasks")
    os.makedirs(tasks_dir, exist_ok=True)
    task_file = os.path.join(tasks_dir, "2026-09-24_cas.md")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write(
            "### 任务 1.1 🔨 执行中 — 并发 CAS 测试\n\n"
            "#### 【涉及文件】\n"
            "```\n"
            "[MODIFY] src/app.py\n"
            "```\n\n"
            "#### 【缺陷根因与修改目标】\n"
            "并发 CAS 验证正文。\n"
        )

    # 预登记 Proposal
    register_proposal(temp_dir, task_id="1.1", md_path=task_file)

    yield temp_dir

    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 1. 异常继承链隔离测试 (ManifestConflictError vs ManifestIntegrityError)
# ==============================================================================

def test_manifest_conflict_error_inheritance():
    """断言 ManifestConflictError 继承 RetryableManifestError，且绝不继承 ManifestIntegrityError。"""
    assert issubclass(ManifestConflictError, RetryableManifestError)
    assert not issubclass(ManifestConflictError, ManifestIntegrityError)
    assert not issubclass(RetryableManifestError, ManifestIntegrityError)

    # 确认 try/except ManifestIntegrityError 不会误捕获 ManifestConflictError
    caught_fatal = False
    caught_retryable = False
    try:
        raise ManifestConflictError("CAS conflict")
    except ManifestIntegrityError:
        caught_fatal = True
    except RetryableManifestError:
        caught_retryable = True

    assert not caught_fatal
    assert caught_retryable


# ==============================================================================
# 2. mutate_manifest_under_lock 事务与异常安全测试
# ==============================================================================

def test_mutator_exception_leaves_manifest_untouched(mock_cas_workspace):
    """测试 mutator 抛异常时：跳过 atomic_replace，释放锁，磁盘内容与哈希绝对不变。"""
    ws = mock_cas_workspace
    manifest_file = os.path.join(ws, MANIFEST_REL_PATH)

    with open(manifest_file, "rb") as f:
        before_bytes = f.read()
    before_hash = hashlib.sha256(before_bytes).hexdigest()

    def bad_mutator(m: Manifest):
        # 尝试在内存修改
        m.records["corrupted"] = TaskRecord(
            task_id="corrupted",
            md_sha256="abc",
            generation=999,
            holder_token="h",
            last_heartbeat_monotonic_ns=0,
            last_heartbeat_wall_utc="",
            git_head_sha="",
            git_index_mtime=0.0,
        )
        raise ValueError("Mutator deliberate explosion")

    with pytest.raises(ValueError) as exc_info:
        mutate_manifest_under_lock(ws, bad_mutator)
    assert "Mutator deliberate explosion" in str(exc_info.value)

    # 验证磁盘内容完全未被更改
    with open(manifest_file, "rb") as f:
        after_bytes = f.read()
    after_hash = hashlib.sha256(after_bytes).hexdigest()

    assert before_hash == after_hash
    reloaded = load_manifest(ws)
    assert "corrupted" not in reloaded.records


def test_reentrancy_guard_raises_runtime_error_not_deadlock(mock_cas_workspace):
    """测试在 mutator 内调用清单取锁 API 时触发重入守护，立即抛出 RuntimeError 而非永久死锁。"""
    ws = mock_cas_workspace

    def reentrant_mutator(m: Manifest):
        # mutator 中违规尝试再次调用 mutate_manifest_under_lock
        mutate_manifest_under_lock(ws, lambda x: (x, None))
        return m, True

    with pytest.raises(RuntimeError) as exc_info:
        mutate_manifest_under_lock(ws, reentrant_mutator)

    assert "Re-entrant manifest lock acquisition detected" in str(exc_info.value)


def test_underlying_cas_detection_on_disk_conflict(mock_cas_workspace):
    """测试兜底 CAS 校验：若在事务内磁盘 generation 被并发覆写，抛出 ManifestConflictError。"""
    ws = mock_cas_workspace

    def conflict_mutator(m: Manifest):
        # 模拟在 mutator 执行过程中外部进程直接修改了磁盘上的 generation
        disk_m = load_manifest(ws)
        # 构造外部变更
        rec = disk_m.records["2026-09-24_cas::1.1"]
        disk_m.records["2026-09-24_cas::1.1"] = TaskRecord(
            task_id=rec.task_id,
            md_sha256=rec.md_sha256,
            generation=rec.generation + 10,
            holder_token=rec.holder_token,
            last_heartbeat_monotonic_ns=rec.last_heartbeat_monotonic_ns,
            last_heartbeat_wall_utc=rec.last_heartbeat_wall_utc,
            git_head_sha=rec.git_head_sha,
            git_index_mtime=rec.git_index_mtime,
        )
        atomic_replace_manifest(ws, disk_m)
        return m, "result_ok"

    with pytest.raises(ManifestConflictError) as exc_info:
        mutate_manifest_under_lock(ws, conflict_mutator)

    assert "Manifest generation on disk conflicted" in str(exc_info.value)


# ==============================================================================
# 3. 五函数外部签名、返回类型与异常等价性测试
# ==============================================================================

def test_five_functions_signatures_and_behavior_equivalence(mock_cas_workspace):
    """断言五大核心操作函数签名未发生任何漂移，异常类型保持等价。"""
    ws = mock_cas_workspace
    task_file = os.path.join(ws, "docs", "dev_tasks", "2026-09-24_cas.md")

    # 1. 签名检查
    sig_commit = inspect.signature(commit_lease)
    assert set(sig_commit.parameters.keys()) == {
        "workspace_root", "task_id", "holder_token", "expected_generation", "md_path"
    }

    sig_cas = inspect.signature(compare_and_swap)
    assert set(sig_cas.parameters.keys()) == {
        "workspace_root", "task_id", "expected_generation", "new_generation", "holder_token"
    }

    sig_release = inspect.signature(release_lease)
    assert set(sig_release.parameters.keys()) == {
        "workspace_root", "task_id", "holder_token", "generation"
    }

    sig_touch = inspect.signature(touch_heartbeat)
    assert set(sig_touch.parameters.keys()) == {
        "workspace_root", "task_id", "holder_token", "generation", "now_monotonic_ns", "now_wall_utc"
    }

    sig_prop = inspect.signature(register_proposal)
    assert set(sig_prop.parameters.keys()) == {
        "workspace_root", "task_id", "md_path"
    }

    # 2. 行为与异常等价性验证
    # FileNotFoundError 等价性
    with pytest.raises(FileNotFoundError):
        commit_lease(ws, task_id="1.1", holder_token="tok", expected_generation=0, md_path="nonexistent.md")

    # 正常提交租约并自增代际
    gen1 = commit_lease(ws, task_id="1.1", holder_token="tok_A", expected_generation=0, md_path=task_file)
    assert gen1 == 1

    # FencedTokenError 等价性（代际冲突）
    with pytest.raises(FencedTokenError):
        commit_lease(ws, task_id="1.1", holder_token="tok_B", expected_generation=0, md_path=task_file)

    # CAS 成功与失败
    assert compare_and_swap(ws, task_id="1.1", expected_generation=1, new_generation=2, holder_token="tok_A") is True
    assert compare_and_swap(ws, task_id="1.1", expected_generation=1, new_generation=3, holder_token="tok_A") is False

    # touch_heartbeat 成功与失败
    assert touch_heartbeat(ws, task_id="1.1", holder_token="tok_A", generation=2) is True
    assert touch_heartbeat(ws, task_id="1.1", holder_token="wrong", generation=2) is False

    # release_lease 成功与失败
    assert release_lease(ws, task_id="1.1", holder_token="wrong", generation=2) is False
    assert release_lease(ws, task_id="1.1", holder_token="tok_A", generation=2) is True


def test_atomic_replace_manifest_same_directory(mock_cas_workspace, monkeypatch):
    """断言 atomic_replace_manifest 写入的临时文件严格位于清单同一物理目录（跨平台原子重命名，杜绝跨文件系统）。"""
    ws = mock_cas_workspace
    m = load_manifest(ws)
    manifest_dir = os.path.dirname(os.path.join(ws, MANIFEST_REL_PATH))

    captured_dirs = []
    orig_mkstemp = tempfile.mkstemp

    def mock_mkstemp(*args, **kwargs):
        captured_dirs.append(kwargs.get("dir"))
        return orig_mkstemp(*args, **kwargs)

    monkeypatch.setattr(tempfile, "mkstemp", mock_mkstemp)

    atomic_replace_manifest(ws, m)
    assert len(captured_dirs) == 1
    assert os.path.samefile(captured_dirs[0], manifest_dir)
    assert os.path.isdir(manifest_dir)
    assert os.path.isfile(os.path.join(ws, MANIFEST_REL_PATH))


# ==============================================================================
# 4. 双进程 Barrier 强制交叠并发 CAS 零脏写测试
# ==============================================================================

def _worker_commit_lease(ws: str, task_file: str, token: str, barrier: multiprocessing.Barrier, queue: multiprocessing.Queue):
    """子进程工作函数：在 Barrier 处同步对齐并发执行 commit_lease。"""
    try:
        barrier.wait(timeout=5.0)
        gen = commit_lease(ws, task_id="1.1", holder_token=token, expected_generation=0, md_path=task_file)
        queue.put(("SUCCESS", token, gen))
    except FencedTokenError as e:
        queue.put(("CONFLICT", token, str(e)))
    except Exception as e:
        queue.put(("ERROR", token, f"{type(e).__name__}: {e}"))


def test_barrier_dual_process_cas_concurrent(mock_cas_workspace):
    """测试双进程使用 multiprocessing.Barrier 强制交叠发起并发租约竞争：
    恰好一方成功、另一方获得可恢复的冲突结果（FencedTokenError），断言零脏写。
    """
    ws = mock_cas_workspace
    task_file = os.path.join(ws, "docs", "dev_tasks", "2026-09-24_cas.md")

    barrier = multiprocessing.Barrier(2)
    queue = multiprocessing.Queue()

    p1 = multiprocessing.Process(
        target=_worker_commit_lease,
        args=(ws, task_file, "token_process_1", barrier, queue),
    )
    p2 = multiprocessing.Process(
        target=_worker_commit_lease,
        args=(ws, task_file, "token_process_2", barrier, queue),
    )

    p1.start()
    p2.start()

    p1.join(timeout=6.0)
    p2.join(timeout=6.0)

    # 超时保护与僵尸进程回收
    if p1.is_alive():
        p1.terminate()
        p1.join(timeout=1.0)
    if p2.is_alive():
        p2.terminate()
        p2.join(timeout=1.0)

    results = []
    while not queue.empty():
        results.append(queue.get_nowait())

    assert len(results) == 2, f"Expected 2 results from child processes, got {results}"

    statuses = [r[0] for r in results]
    # 恰好一方 SUCCESS，另一方 CONFLICT
    assert "SUCCESS" in statuses, f"No process succeeded: {results}"
    assert "CONFLICT" in statuses, f"No conflict was detected: {results}"
    assert statuses.count("SUCCESS") == 1
    assert statuses.count("CONFLICT") == 1

    # 验证最终磁盘上的清单保持零脏写且代际为 1
    m = load_manifest(ws)
    rec = m.records.get("2026-09-24_cas::1.1")
    assert rec is not None
    assert rec.generation == 1
    # 持有者为成功获胜的一方的 token
    winning_token = next(r[1] for r in results if r[0] == "SUCCESS")
    assert rec.holder_token == winning_token
