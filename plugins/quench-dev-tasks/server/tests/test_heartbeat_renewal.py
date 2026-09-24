# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import concurrent.futures
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
import anyio
import pytest
import yaml

from manifest import (
    FencedTokenError,
    Manifest,
    ManifestIntegrityError,
    TaskRecord,
    MANIFEST_REL_PATH,
    atomic_replace_manifest,
    commit_lease,
    load_manifest,
    release_lease,
    touch_heartbeat,
)
from server import (
    dev_tasks_checkout,
    dev_tasks_complete,
    dev_tasks_heartbeat,
)


@pytest.fixture
def mock_workspace():
    temp_dir = tempfile.mkdtemp(prefix="quench_heartbeat_test_")
    agents_dir = os.path.join(temp_dir, ".agents")
    os.makedirs(agents_dir, exist_ok=True)

    config_data = {
        "project_name": "HeartbeatTestProject",
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

    # 创建初始任务文件
    tasks_dir = os.path.join(temp_dir, "docs", "dev_tasks")
    os.makedirs(tasks_dir, exist_ok=True)
    task_file = os.path.join(tasks_dir, "2026-09-24_feature.md")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write(
            "### 任务 1.1 ✅ 已确认 — 第一项任务 (Task One)\n\n"
            "#### 【涉及文件】\n"
            "```\n"
            "[MODIFY] src/app.py\n"
            "```\n\n"
            "#### 【缺陷根因与修改目标】\n"
            "测试正文内容说明。\n"
        )

    yield temp_dir
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_touch_heartbeat_valid_renewal(mock_workspace):
    """测试合法 generation 与 holder_token 成功续期心跳，且代际不递增。"""
    ws = mock_workspace
    checkout_res = dev_tasks_checkout(ws, task_file="2026-09-24_feature.md", task_id="1.1")
    assert checkout_res.get("status") == "🔨 执行中"
    token = checkout_res["holder_token"]
    gen = checkout_res["generation"]

    m1 = load_manifest(ws)
    rec1 = m1.records["2026-09-24_feature::1.1"]
    initial_monotonic = rec1.last_heartbeat_monotonic_ns
    initial_wall = rec1.last_heartbeat_wall_utc

    # 显式注入未来时钟
    future_monotonic = initial_monotonic + 5_000_000_000
    future_wall = "2026-09-24T12:00:00Z"
    renewed = touch_heartbeat(
        ws,
        task_id="2026-09-24_feature::1.1",
        holder_token=token,
        generation=gen,
        now_monotonic_ns=future_monotonic,
        now_wall_utc=future_wall,
    )
    assert renewed is True

    m2 = load_manifest(ws)
    rec2 = m2.records["2026-09-24_feature::1.1"]
    assert rec2.generation == gen  # 心跳刷新代际保持稳定
    assert rec2.holder_token == token
    assert rec2.last_heartbeat_monotonic_ns == future_monotonic
    assert rec2.last_heartbeat_wall_utc == future_wall
    assert rec2.released is False


def test_touch_heartbeat_stale_generation_rejected(mock_workspace):
    """测试陈旧代际请求被阻断（Fail-Closed）。"""
    ws = mock_workspace
    checkout_res = dev_tasks_checkout(ws, task_file="2026-09-24_feature.md", task_id="1.1")
    token = checkout_res["holder_token"]
    gen = checkout_res["generation"]

    # 尝试使用陈旧代际 (gen - 1)
    renewed = touch_heartbeat(
        ws,
        task_id="2026-09-24_feature::1.1",
        holder_token=token,
        generation=gen - 1,
    )
    assert renewed is False

    # 尝试使用未来未授权代际 (gen + 1)
    renewed_future = touch_heartbeat(
        ws,
        task_id="2026-09-24_feature::1.1",
        holder_token=token,
        generation=gen + 1,
    )
    assert renewed_future is False


def test_touch_heartbeat_mismatched_token_rejected(mock_workspace):
    """测试非法或冒名 Token 请求被阻断。"""
    ws = mock_workspace
    checkout_res = dev_tasks_checkout(ws, task_file="2026-09-24_feature.md", task_id="1.1")
    gen = checkout_res["generation"]

    renewed = touch_heartbeat(
        ws,
        task_id="2026-09-24_feature::1.1",
        holder_token="rogue_token_hacker",
        generation=gen,
    )
    assert renewed is False


def test_touch_heartbeat_released_task_rejected(mock_workspace):
    """测试已释放任务（墓碑标记 released=True）禁止心跳续约。"""
    ws = mock_workspace
    checkout_res = dev_tasks_checkout(ws, task_file="2026-09-24_feature.md", task_id="1.1")
    token = checkout_res["holder_token"]
    gen = checkout_res["generation"]

    # 释放租约
    rel_ok = release_lease(ws, task_id="2026-09-24_feature::1.1", holder_token=token, generation=gen)
    assert rel_ok is True

    # 尝试续约已释放的任务
    renewed = touch_heartbeat(
        ws,
        task_id="2026-09-24_feature::1.1",
        holder_token=token,
        generation=gen,
    )
    assert renewed is False


def test_manifest_integrity_error_fail_closed(mock_workspace):
    """测试清单文件损坏时严格抛出 ManifestIntegrityError，杜绝静默重置与代际归零。"""
    ws = mock_workspace
    manifest_path = os.path.join(ws, MANIFEST_REL_PATH)
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)

    # 1. 损坏的 JSON 语法
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("{broken json: [unclosed")

    with pytest.raises(ManifestIntegrityError) as exc_info:
        load_manifest(ws)
    assert "Failed to read or parse manifest" in str(exc_info.value)

    with pytest.raises(ManifestIntegrityError):
        touch_heartbeat(ws, task_id="any::1", holder_token="tok", generation=1)

    # 2. 根结构非 JSON 字典
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("[\"not\", \"a\", \"dict\"]")

    with pytest.raises(ManifestIntegrityError) as exc_info2:
        load_manifest(ws)
    assert "Corrupted manifest format" in str(exc_info2.value)

    # 3. records 字段畸形
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"schema_version": "1.0", "records": "not-a-dict"}))

    with pytest.raises(ManifestIntegrityError) as exc_info3:
        load_manifest(ws)
    assert "records" in str(exc_info3.value)

    # 4. 单条记录字段类型损坏
    corrupted_records = {
        "schema_version": "1.0",
        "records": {
            "demo::1.1": {
                "task_id": "demo::1.1",
                "generation": "not-an-int",
            }
        },
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(corrupted_records))

    with pytest.raises(ManifestIntegrityError) as exc_info4:
        load_manifest(ws)
    assert "Corrupted record fields" in str(exc_info4.value)


@pytest.mark.anyio
async def test_mcp_dev_tasks_heartbeat_auto_resolve(mock_workspace):
    """测试 FastMCP 原生工具 dev_tasks_heartbeat 自动解析当前执行中任务。"""
    ws = mock_workspace
    checkout_res = dev_tasks_checkout(ws, task_file="2026-09-24_feature.md", task_id="1.1")
    assert checkout_res.get("status") == "🔨 执行中"

    # 省略 task_id，自动解析
    res = await dev_tasks_heartbeat(ws)
    assert res["status"] == "ok"
    assert res["task_id"] == "2026-09-24_feature::1.1"
    assert res["generation"] == 1
    assert "holder_token" in res


@pytest.mark.anyio
async def test_mcp_dev_tasks_heartbeat_explicit_and_rejected(mock_workspace):
    """测试 FastMCP dev_tasks_heartbeat 显式参数与错误防卫。"""
    ws = mock_workspace
    checkout_res = dev_tasks_checkout(ws, task_file="2026-09-24_feature.md", task_id="1.1")
    token = checkout_res["holder_token"]

    # 显式传递有效 task_id 与 holder_token
    res_ok = await dev_tasks_heartbeat(ws, task_id="1.1", holder_token=token)
    assert res_ok["status"] == "ok"

    # 传递错误 token
    res_bad_tok = await dev_tasks_heartbeat(ws, task_id="1.1", holder_token="invalid_token")
    assert res_bad_tok["status"] == "rejected"

    # 传递不存在的任务
    res_no_task = await dev_tasks_heartbeat(ws, task_id="99.99")
    assert res_no_task["status"] == "rejected"
    assert "No lease record found" in res_no_task["reason"]


@pytest.mark.anyio
async def test_mcp_dev_tasks_heartbeat_session_isolation(mock_workspace):
    """测试多会话隔离、session_id 校验与跨会话租约冲突防卫。"""
    ws = mock_workspace

    # 非法 session_id 注入防卫
    res_invalid_sid = await dev_tasks_heartbeat(ws, session_id="../../traversal_sid")
    assert res_invalid_sid["status"] == "rejected"
    assert "非法的 session_id 格式" in res_invalid_sid["reason"]

    # 会话 A 检出任务
    session_a = "session-alpha-123"
    res_checkout = dev_tasks_checkout(ws, task_file="2026-09-24_feature.md", task_id="1.1", session_id=session_a)
    assert res_checkout["status"] == "🔨 执行中"
    assert res_checkout.get("session_id") == session_a
    token_a = res_checkout["holder_token"]
    assert session_a in token_a

    # 会话 A 正常续期心跳
    hb_a = await dev_tasks_heartbeat(ws, session_id=session_a)
    assert hb_a["status"] == "ok"
    assert hb_a.get("session_id") == session_a

    # 会话 B 冒名尝试刷新属于会话 A 的租约
    session_b = "session-beta-456"
    hb_b = await dev_tasks_heartbeat(ws, session_id=session_b)
    assert hb_b["status"] == "rejected"
    assert "跨会话租约冲突" in hb_b["reason"]
    assert session_a in hb_b["reason"]
    assert session_b in hb_b["reason"]


@pytest.mark.anyio
async def test_mcp_dev_tasks_heartbeat_fail_closed_manifest(mock_workspace):
    """测试 manifest 损坏时 dev_tasks_heartbeat 返回 fail-closed 结构化响应。"""
    ws = mock_workspace
    dev_tasks_checkout(ws, task_file="2026-09-24_feature.md", task_id="1.1")

    # 破坏 manifest 文件
    manifest_path = os.path.join(ws, MANIFEST_REL_PATH)
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("{corrupt_json: true...")

    hb_res = await dev_tasks_heartbeat(ws)
    assert hb_res["status"] == "rejected"
    assert "Fail-Closed" in hb_res["reason"]


def test_concurrent_heartbeat_renewal_atomicity(mock_workspace):
    """测试多线程高并发心跳刷新下的原子性与数据文件完整性。"""
    ws = mock_workspace
    checkout_res = dev_tasks_checkout(ws, task_file="2026-09-24_feature.md", task_id="1.1")
    token = checkout_res["holder_token"]
    gen = checkout_res["generation"]

    task_id = "2026-09-24_feature::1.1"

    def worker_renew(thread_idx: int) -> bool:
        now_mono = time.monotonic_ns() + thread_idx * 1000
        now_wall = datetime.now(timezone.utc).isoformat()
        return touch_heartbeat(
            ws,
            task_id=task_id,
            holder_token=token,
            generation=gen,
            now_monotonic_ns=now_mono,
            now_wall_utc=now_wall,
        )

    # 20 个并发线程同时调用 touch_heartbeat
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker_renew, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results) is True
    # 验证最终清单结构完好且可正常解析
    final_m = load_manifest(ws)
    rec = final_m.records[task_id]
    assert rec.generation == gen
    assert rec.holder_token == token
    assert rec.released is False
