# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
import pytest
import yaml

from manifest import (
    load_manifest,
    release_lease,
    touch_heartbeat,
)
from project_config import (
    load_project_config,
    QuenchStackConfig,
    ReaperPolicyConfig,
)
from reaper import (
    HealthVerdict,
    ProbeEvidence,
    probe_lease_health,
)
from server import (
    dev_tasks_checkout,
)


@pytest.fixture
def reaper_workspace():
    temp_dir = tempfile.mkdtemp(prefix="quench_reaper_test_")
    agents_dir = os.path.join(temp_dir, ".agents")
    os.makedirs(agents_dir, exist_ok=True)

    config_data = {
        "project_name": "ReaperTestProject",
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
    with open(os.path.join(agents_dir, "quench_stack.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    # 创建任务文件与涉及文件
    tasks_dir = os.path.join(temp_dir, "docs", "dev_tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    src_dir = os.path.join(temp_dir, "src")
    os.makedirs(src_dir, exist_ok=True)
    app_file = os.path.join(src_dir, "app.py")
    with open(app_file, "w", encoding="utf-8") as f:
        f.write("# sample app\n")

    task_file = os.path.join(tasks_dir, "2026-09-24_demo.md")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write(
            "### 任务 1.1 ✅ 已确认 — 核心业务重构 (Core Task)\n\n"
            "#### 【涉及文件】\n"
            "```\n"
            "[MODIFY] src/app.py\n"
            "```\n\n"
            "#### 【缺陷根因与修改目标】\n"
            "测试\n\n"
            "### 任务 1.2 ✅ 已确认 — 纯文档类审查无受管文件 (Review Task)\n\n"
            "#### 【缺陷根因与修改目标】\n"
            "纯文档审查\n"
        )

    yield temp_dir
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_probe_no_lease_and_released(reaper_workspace):
    """测试无租约记录与已释放租约的健康判定。"""
    ws = reaper_workspace

    # 1. 不存在的任务
    ev_none = probe_lease_health(ws, task_id="nonexistent::9.9")
    assert ev_none.verdict == HealthVerdict.NO_LEASE
    assert ev_none.generation == -1
    assert ev_none.holder_token is None

    # 2. 检出任务后立即释放
    res = dev_tasks_checkout(ws, task_file="2026-09-24_demo.md", task_id="1.1")
    token = res["holder_token"]
    gen = res["generation"]
    release_lease(ws, task_id="2026-09-24_demo::1.1", holder_token=token, generation=gen)

    ev_rel = probe_lease_health(ws, task_id="2026-09-24_demo::1.1")
    assert ev_rel.verdict == HealthVerdict.RELEASED
    assert ev_rel.generation == gen
    assert ev_rel.holder_token == token


def test_probe_heartbeat_fresh_files_stale(reaper_workspace):
    """测试心跳新鲜 + 文件陈旧 -> 整体 HEALTHY（保护深度思考/单测中的长任务）。"""
    ws = reaper_workspace
    dev_tasks_checkout(ws, task_file="2026-09-24_demo.md", task_id="1.1")

    base_time = 1700000000.0
    # 文件修改时间设置为 2000 秒前 (远超 600s 阈值，陈旧)
    app_file = os.path.join(ws, "src", "app.py")
    os.utime(app_file, (base_time - 2000, base_time - 2000))

    # 心跳设置为 100 秒前 (小于 900s 阈值，新鲜)
    hb_time = datetime.fromtimestamp(base_time - 100, tz=timezone.utc).isoformat()
    now_wall = datetime.fromtimestamp(base_time, tz=timezone.utc).isoformat()

    m = load_manifest(ws)
    rec = m.records["2026-09-24_demo::1.1"]
    touch_heartbeat(
        ws,
        task_id="2026-09-24_demo::1.1",
        holder_token=rec.holder_token,
        generation=rec.generation,
        now_wall_utc=hb_time,
    )

    ev = probe_lease_health(ws, task_id="2026-09-24_demo::1.1", now_wall_utc=now_wall)
    assert ev.verdict == HealthVerdict.HEALTHY
    assert ev.heartbeat_silence_seconds == pytest.approx(100.0, rel=1e-2)
    assert ev.affected_files_max_mtime_age_seconds == pytest.approx(2000.0, rel=1e-2)
    assert any("心跳新鲜活跃" in r for r in ev.reasons)


def test_probe_heartbeat_stale_files_fresh(reaper_workspace):
    """测试心跳陈旧 + 文件新鲜 -> 整体 HEALTHY（保护高频编码但心跳偶发失联的工作者）。"""
    ws = reaper_workspace
    dev_tasks_checkout(ws, task_file="2026-09-24_demo.md", task_id="1.1")

    base_time = 1700000000.0
    # 文件在 50 秒前刚被修改 (小于 600s 阈值，新鲜)
    app_file = os.path.join(ws, "src", "app.py")
    os.utime(app_file, (base_time - 50, base_time - 50))

    # 心跳设置为 1500 秒前 (大于 900s 阈值，陈旧)
    hb_time = datetime.fromtimestamp(base_time - 1500, tz=timezone.utc).isoformat()
    now_wall = datetime.fromtimestamp(base_time, tz=timezone.utc).isoformat()

    m = load_manifest(ws)
    rec = m.records["2026-09-24_demo::1.1"]
    touch_heartbeat(
        ws,
        task_id="2026-09-24_demo::1.1",
        holder_token=rec.holder_token,
        generation=rec.generation,
        now_wall_utc=hb_time,
    )

    ev = probe_lease_health(ws, task_id="2026-09-24_demo::1.1", now_wall_utc=now_wall)
    assert ev.verdict == HealthVerdict.HEALTHY
    assert ev.heartbeat_silence_seconds == pytest.approx(1500.0, rel=1e-2)
    assert ev.affected_files_max_mtime_age_seconds == pytest.approx(50.0, rel=1e-2)
    assert any("受管文件近期有编辑活跃" in r for r in ev.reasons)


def test_probe_both_stale_suspect(reaper_workspace):
    """测试双陈旧（心跳静默且受管文件无更新）-> 裁定 STALE_SUSPECT（疑似僵尸）。"""
    ws = reaper_workspace
    dev_tasks_checkout(ws, task_file="2026-09-24_demo.md", task_id="1.1")

    base_time = 1700000000.0
    # 文件 2000 秒未修改
    app_file = os.path.join(ws, "src", "app.py")
    os.utime(app_file, (base_time - 2000, base_time - 2000))

    # 心跳 1800 秒未刷新
    hb_time = datetime.fromtimestamp(base_time - 1800, tz=timezone.utc).isoformat()
    now_wall = datetime.fromtimestamp(base_time, tz=timezone.utc).isoformat()

    m = load_manifest(ws)
    rec = m.records["2026-09-24_demo::1.1"]
    touch_heartbeat(
        ws,
        task_id="2026-09-24_demo::1.1",
        holder_token=rec.holder_token,
        generation=rec.generation,
        now_wall_utc=hb_time,
    )

    ev = probe_lease_health(ws, task_id="2026-09-24_demo::1.1", now_wall_utc=now_wall)
    assert ev.verdict == HealthVerdict.STALE_SUSPECT
    assert any("心跳静默超时" in r for r in ev.reasons)
    assert any("受管文件修改超时" in r for r in ev.reasons)


def test_probe_no_affected_files_degraded_handling(reaper_workspace):
    """测试无受管文件任务（只读/审查任务）的维度缺席降级与保护。"""
    ws = reaper_workspace
    # 检出 1.2（纯文档审查，无涉及文件声明）
    dev_tasks_checkout(ws, task_file="2026-09-24_demo.md", task_id="1.2")

    base_time = 1700000000.0
    now_wall = datetime.fromtimestamp(base_time, tz=timezone.utc).isoformat()

    # 1. 心跳新鲜 (100s) -> HEALTHY (受管文件缺席不影响)
    hb_fresh = datetime.fromtimestamp(base_time - 100, tz=timezone.utc).isoformat()
    m = load_manifest(ws)
    rec = m.records["2026-09-24_demo::1.2"]
    touch_heartbeat(
        ws,
        task_id="2026-09-24_demo::1.2",
        holder_token=rec.holder_token,
        generation=rec.generation,
        now_wall_utc=hb_fresh,
    )

    ev_fresh = probe_lease_health(ws, task_id="2026-09-24_demo::1.2", now_wall_utc=now_wall)
    assert ev_fresh.verdict == HealthVerdict.HEALTHY
    assert ev_fresh.affected_files_max_mtime_age_seconds is None

    # 2. 心跳陈旧 (2000s) + 维度缺席 -> 降级合取 STALE_SUSPECT
    hb_stale = datetime.fromtimestamp(base_time - 2000, tz=timezone.utc).isoformat()
    touch_heartbeat(
        ws,
        task_id="2026-09-24_demo::1.2",
        holder_token=rec.holder_token,
        generation=rec.generation,
        now_wall_utc=hb_stale,
    )

    ev_stale = probe_lease_health(ws, task_id="2026-09-24_demo::1.2", now_wall_utc=now_wall)
    assert ev_stale.verdict == HealthVerdict.STALE_SUSPECT
    assert ev_stale.affected_files_max_mtime_age_seconds is None
    assert any("维度缺席降级" in r for r in ev_stale.reasons)


def test_probe_negative_clock_skew_defense(reaper_workspace):
    """测试 NTP 回拨出现负时长时被严格夹为 0.0s。"""
    ws = reaper_workspace
    dev_tasks_checkout(ws, task_file="2026-09-24_demo.md", task_id="1.1")

    base_time = 1700000000.0
    # 心跳时间戳晚于当前检测时间戳 (模拟时钟漂移/NTP回拨)
    hb_time = datetime.fromtimestamp(base_time + 100, tz=timezone.utc).isoformat()
    now_wall = datetime.fromtimestamp(base_time, tz=timezone.utc).isoformat()

    m = load_manifest(ws)
    rec = m.records["2026-09-24_demo::1.1"]
    touch_heartbeat(
        ws,
        task_id="2026-09-24_demo::1.1",
        holder_token=rec.holder_token,
        generation=rec.generation,
        now_wall_utc=hb_time,
    )

    ev = probe_lease_health(ws, task_id="2026-09-24_demo::1.1", now_wall_utc=now_wall)
    assert ev.heartbeat_silence_seconds == 0.0
    assert ev.verdict == HealthVerdict.HEALTHY


def test_probe_parameter_threshold_override(reaper_workspace):
    """测试显式传递阈值优先级高于项目配置默认值。"""
    ws = reaper_workspace
    dev_tasks_checkout(ws, task_file="2026-09-24_demo.md", task_id="1.1")

    base_time = 1700000000.0
    app_file = os.path.join(ws, "src", "app.py")
    os.utime(app_file, (base_time - 500, base_time - 500))

    hb_time = datetime.fromtimestamp(base_time - 500, tz=timezone.utc).isoformat()
    now_wall = datetime.fromtimestamp(base_time, tz=timezone.utc).isoformat()

    m = load_manifest(ws)
    rec = m.records["2026-09-24_demo::1.1"]
    touch_heartbeat(
        ws,
        task_id="2026-09-24_demo::1.1",
        holder_token=rec.holder_token,
        generation=rec.generation,
        now_wall_utc=hb_time,
    )

    # 默认配置下：hb 500s <= 900s，mtime 500s <= 600s -> HEALTHY
    ev_default = probe_lease_health(ws, task_id="2026-09-24_demo::1.1", now_wall_utc=now_wall)
    assert ev_default.verdict == HealthVerdict.HEALTHY

    # 显式覆盖阈值为严格的 300s -> 500s 触发 STALE_SUSPECT
    ev_strict = probe_lease_health(
        ws,
        task_id="2026-09-24_demo::1.1",
        heartbeat_silence_threshold_seconds=300.0,
        affected_files_mtime_threshold_seconds=300.0,
        now_wall_utc=now_wall,
    )
    assert ev_strict.verdict == HealthVerdict.STALE_SUSPECT
