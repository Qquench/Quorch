# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import asyncio
import os
import pytest
import yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path

from manifest import (
    load_manifest,
    touch_heartbeat,
    TaskRecord,
    MANIFEST_REL_PATH,
    atomic_replace_manifest,
)
from reaper import reclaim_stale_task
from server import dev_tasks_confirm, dev_tasks_reclaim
from state_machine import (
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    parse_task_file,
    transition_task,
)


@pytest.fixture
def mock_reclaim_workspace(tmp_path):
    """构建用于测试 CAS 幂等任务回收的工作区。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir(parents=True)
    manifest_dir = agents_dir / ".quorch"
    manifest_dir.mkdir(parents=True)

    config_data = {
        "project_name": "ReclaimTestProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "changelog_path": "CHANGELOG.md",
        "test_dir": "tests",
        "test_runner": "pytest",
        "reaper_policy": {
            "heartbeat_silence_threshold_seconds": 900,
            "affected_files_mtime_threshold_seconds": 600,
        },
    }
    with open(agents_dir / "quench_stack.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    tasks_dir = ws / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True)

    task_file = tasks_dir / "2026-09-24_reclaim_test.md"
    content = """# Reclaim Test Spec

### 任务 1.1 🔨 执行中 — 测试回收与代际门禁
#### 【涉及文件】
```
[MODIFY] src/app.py
```
#### 【缺陷根因与修改目标】
测试僵尸任务回收
#### 【目标签名与类型契约】
无
#### 【分步改造指引】
无
#### 【防御与边缘校验】
无
#### 【DoD 验证命令】
```bash
pytest
```
"""
    task_file.write_text(content, encoding="utf-8")

    src_dir = ws / "src"
    src_dir.mkdir()
    app_py = src_dir / "app.py"
    app_py.write_text("print('hello')\n", encoding="utf-8")

    return str(ws), "2026-09-24_reclaim_test.md"


def _setup_stale_lease(ws: str, namespaced_id: str, generation: int = 1, holder_token: str = "token_stale_123"):
    """辅助函数：在 manifest 中植入心跳超时的僵尸租约，同时将受管文件 mtime 推向过去。"""
    m = load_manifest(ws)
    stale_wall = (datetime.now(timezone.utc) - timedelta(seconds=1500)).isoformat()
    record = TaskRecord(
        task_id=namespaced_id,
        md_sha256="test_hash",
        generation=generation,
        holder_token=holder_token,
        last_heartbeat_monotonic_ns=0,
        last_heartbeat_wall_utc=stale_wall,
        git_head_sha="sha_stale",
        git_index_mtime=0.0,
        released=False,
    )
    m.records[namespaced_id] = record
    atomic_replace_manifest(ws, m)

    # 确保涉及文件 mtime 也超过阈值 (700s 前)
    app_py = os.path.join(ws, "src", "app.py")
    if os.path.isfile(app_py):
        old_mtime = datetime.now().timestamp() - 700.0
        os.utime(app_py, (old_mtime, old_mtime))


def test_reclaim_stale_task_success(mock_reclaim_workspace):
    """测试常规僵尸任务在探针判为 STALE_SUSPECT 时的成功 CAS 回收。"""
    ws, md_name = mock_reclaim_workspace
    namespaced_id = "2026-09-24_reclaim_test::1.1"
    _setup_stale_lease(ws, namespaced_id, generation=1, holder_token="tok_abc")

    # 执行回收
    ok, reason = reclaim_stale_task(
        ws,
        task_id="1.1",
        expected_generation=1,
        expected_holder_token="tok_abc",
        force=False,
    )

    assert ok is True
    assert reason == "reclaimed"

    # 验证清单状态：代际单调递增至 2，留痕墓碑 released=True
    m = load_manifest(ws)
    record = m.records[namespaced_id]
    assert record.generation == 2
    assert record.released is True

    # 验证任务单 Markdown 状态原子流转回 ✅ 已确认
    md_path = os.path.join(ws, "docs", "dev_tasks", md_name)
    tasks = parse_task_file(md_path)
    assert len(tasks) == 1
    assert tasks[0].status == STATUS_CONFIRMED


def test_reclaim_target_healthy_rejected_without_force(mock_reclaim_workspace):
    """测试健康任务在非 force 情况下被探针拦截拒绝回收。"""
    ws, md_name = mock_reclaim_workspace
    namespaced_id = "2026-09-24_reclaim_test::1.1"

    # 植入新鲜活跃租约 (心跳在 10s 前)
    m = load_manifest(ws)
    fresh_wall = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    record = TaskRecord(
        task_id=namespaced_id,
        md_sha256="test_hash",
        generation=1,
        holder_token="tok_active",
        last_heartbeat_monotonic_ns=0,
        last_heartbeat_wall_utc=fresh_wall,
        git_head_sha="sha_fresh",
        git_index_mtime=0.0,
        released=False,
    )
    m.records[namespaced_id] = record
    atomic_replace_manifest(ws, m)

    ok, reason = reclaim_stale_task(
        ws,
        task_id=namespaced_id,
        expected_generation=1,
        expected_holder_token="tok_active",
        force=False,
    )

    assert ok is False
    assert reason == "target_is_healthy"

    # 验证状态未被篡改
    m = load_manifest(ws)
    assert m.records[namespaced_id].generation == 1
    assert m.records[namespaced_id].released is False

    md_path = os.path.join(ws, "docs", "dev_tasks", md_name)
    tasks = parse_task_file(md_path)
    assert tasks[0].status == STATUS_IN_PROGRESS


def test_reclaim_target_healthy_forced(mock_reclaim_workspace):
    """测试健康任务在指定 force=True 时的强制回收。"""
    ws, md_name = mock_reclaim_workspace
    namespaced_id = "2026-09-24_reclaim_test::1.1"

    # 植入新鲜活跃租约
    m = load_manifest(ws)
    fresh_wall = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    m.records[namespaced_id] = TaskRecord(
        task_id=namespaced_id,
        md_sha256="test_hash",
        generation=3,
        holder_token="tok_active",
        last_heartbeat_monotonic_ns=0,
        last_heartbeat_wall_utc=fresh_wall,
        git_head_sha="sha_fresh",
        git_index_mtime=0.0,
        released=False,
    )
    atomic_replace_manifest(ws, m)

    ok, reason = reclaim_stale_task(
        ws,
        task_id=namespaced_id,
        expected_generation=3,
        expected_holder_token="tok_active",
        force=True,
    )

    assert ok is True
    assert reason == "reclaimed"

    m = load_manifest(ws)
    assert m.records[namespaced_id].generation == 4
    assert m.records[namespaced_id].released is True


def test_reclaim_already_reclaimed_or_fenced_mismatches(mock_reclaim_workspace):
    """测试代际、令牌不匹配或已释放状态下的 CAS 幂等返回 already_reclaimed_or_fenced。"""
    ws, md_name = mock_reclaim_workspace
    namespaced_id = "2026-09-24_reclaim_test::1.1"
    _setup_stale_lease(ws, namespaced_id, generation=5, holder_token="tok_correct")

    # 1. generation 校验不通过 (传入预期 4 != 实际 5)
    ok, reason = reclaim_stale_task(
        ws,
        task_id=namespaced_id,
        expected_generation=4,
        expected_holder_token="tok_correct",
    )
    assert ok is True
    assert reason == "already_reclaimed_or_fenced"

    # 2. holder_token 校验不通过
    ok, reason = reclaim_stale_task(
        ws,
        task_id=namespaced_id,
        expected_generation=5,
        expected_holder_token="wrong_token",
    )
    assert ok is True
    assert reason == "already_reclaimed_or_fenced"

    # 3. 租约已经 released=True (此前已被回收或完成)
    m = load_manifest(ws)
    rec = m.records[namespaced_id]
    m.records[namespaced_id] = TaskRecord(
        task_id=rec.task_id,
        md_sha256=rec.md_sha256,
        generation=rec.generation,
        holder_token=rec.holder_token,
        last_heartbeat_monotonic_ns=rec.last_heartbeat_monotonic_ns,
        last_heartbeat_wall_utc=rec.last_heartbeat_wall_utc,
        git_head_sha=rec.git_head_sha,
        git_index_mtime=rec.git_index_mtime,
        released=True,
    )
    atomic_replace_manifest(ws, m)

    ok, reason = reclaim_stale_task(
        ws,
        task_id=namespaced_id,
        expected_generation=5,
        expected_holder_token="tok_correct",
    )
    assert ok is True
    assert reason == "already_reclaimed_or_fenced"


def test_reclaim_no_such_lease(mock_reclaim_workspace):
    """测试对不存在租约的任务进行回收时返回 no_such_lease。"""
    ws, _ = mock_reclaim_workspace
    ok, reason = reclaim_stale_task(
        ws,
        task_id="99.9",
        expected_generation=1,
        expected_holder_token="tok_any",
    )
    assert ok is False
    assert reason == "no_such_lease"


def test_reclaim_fences_out_zombie_heartbeat(mock_reclaim_workspace):
    """测试回收后代际递增，僵尸工作者复活续签心跳被 fail-closed 拒认。"""
    ws, _ = mock_reclaim_workspace
    namespaced_id = "2026-09-24_reclaim_test::1.1"
    _setup_stale_lease(ws, namespaced_id, generation=1, holder_token="zombie_token")

    # 回收成功
    ok, reason = reclaim_stale_task(
        ws,
        task_id=namespaced_id,
        expected_generation=1,
        expected_holder_token="zombie_token",
    )
    assert ok is True
    assert reason == "reclaimed"

    # 僵尸子代理唤醒，试图以旧代际 gen=1 刷新心跳 -> 必须被拒绝
    hb_ok = touch_heartbeat(
        ws,
        task_id=namespaced_id,
        holder_token="zombie_token",
        generation=1,
    )
    assert hb_ok is False


def test_dev_tasks_confirm_anti_bypass_guard(mock_reclaim_workspace):
    """测试 dev_tasks_confirm 阻断 In Progress -> Confirmed 状态流转绕行后门。"""
    ws, md_name = mock_reclaim_workspace

    # 任务 1.1 当前为 🔨 执行中
    res = dev_tasks_confirm(ws, md_name, ["1.1"], action="confirm")
    assert len(res["errors"]) == 1
    assert "Cannot transition task '1.1' from 'In Progress' to 'Confirmed'" in res["errors"][0]["error"]
    assert len(res["updated"]) == 0

    # 任务状态必须保持 🔨 执行中
    md_path = os.path.join(ws, "docs", "dev_tasks", md_name)
    tasks = parse_task_file(md_path)
    assert tasks[0].status == STATUS_IN_PROGRESS


def test_dev_tasks_reclaim_mcp_tool(mock_reclaim_workspace):
    """测试 dev_tasks_reclaim FastMCP 工具的异步调用与响应格式。"""
    ws, md_name = mock_reclaim_workspace
    namespaced_id = "2026-09-24_reclaim_test::1.1"
    _setup_stale_lease(ws, namespaced_id, generation=2, holder_token="tok_reclaim_tool")

    async def _run_async_checks():
        # 1. 成功回收
        res = await dev_tasks_reclaim(
            workspace_root=ws,
            task_id="1.1",
            expected_generation=2,
            expected_holder_token="tok_reclaim_tool",
        )
        assert res["status"] == "reclaimed"
        assert res["task_id"] == "1.1"

        # 2. 幂等再次回收 (代际已递增)
        res_idempotent = await dev_tasks_reclaim(
            workspace_root=ws,
            task_id="1.1",
            expected_generation=2,
            expected_holder_token="tok_reclaim_tool",
        )
        assert res_idempotent["status"] == "already_reclaimed_or_fenced"
        assert res_idempotent["task_id"] == "1.1"

        # 3. 缺失 task_id
        res_err = await dev_tasks_reclaim(
            workspace_root=ws,
            task_id="",
        )
        assert res_err["status"] == "rejected"
        assert res_err["reason"] == "missing_task_id"

    asyncio.run(_run_async_checks())
