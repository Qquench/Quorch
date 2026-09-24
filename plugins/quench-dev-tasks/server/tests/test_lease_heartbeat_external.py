# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
import pytest
import yaml

from manifest import (
    load_manifest,
    touch_heartbeat,
    commit_lease,
    release_lease,
)
from manifest_lease import (
    LeaseContractError,
    MAX_TTL,
    is_workspace_actively_modifying,
    touch_lease_heartbeat,
    extract_session_id_from_holder_token,
)
from reaper import probe_lease_health, HealthVerdict


@pytest.fixture
def mock_lease_workspace():
    temp_dir = tempfile.mkdtemp(prefix="quench_lease_test_")
    agents_dir = os.path.join(temp_dir, ".agents")
    os.makedirs(agents_dir, exist_ok=True)

    config_data = {
        "project_name": "LeaseHeartbeatTestProject",
        "dev_tasks_dir": "docs/dev_tasks",
        "archive_dir": "docs/dev_tasks/archive",
        "changelog_path": "CHANGELOG.md",
        "test_dir": "tests",
        "test_runner": "pytest",
        "governance": {
            "manifest_path": ".agents/.quorch/manifest.json",
            "lease_ttl_seconds": 300,
        },
        "reaper_policy": {
            "heartbeat_silence_threshold_seconds": 900.0,
            "affected_files_mtime_threshold_seconds": 600.0,
        },
    }
    with open(os.path.join(agents_dir, "quench_stack.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(config_data, f)

    tasks_dir = os.path.join(temp_dir, "docs", "dev_tasks")
    os.makedirs(tasks_dir, exist_ok=True)
    task_file = os.path.join(tasks_dir, "2026-09-24_demo.md")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write(
            "### 任务 1.1 🔨 执行中 — 测试租约心跳 (Task One)\n\n"
            "#### 【涉及文件】\n"
            "```\n"
            "[MODIFY] src/app.py\n"
            "[NEW]    src/new_module.py\n"
            "```\n\n"
            "#### 【缺陷根因与修改目标】\n"
            "测试正文说明。\n"
        )

    # 建立测试源码文件目录
    src_dir = os.path.join(temp_dir, "src")
    os.makedirs(src_dir, exist_ok=True)
    with open(os.path.join(src_dir, "app.py"), "w", encoding="utf-8") as f:
        f.write("# app code\n")

    yield temp_dir

    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 1. is_workspace_actively_modifying 单元测试
# ==============================================================================

def test_is_workspace_actively_modifying_fresh_file(mock_lease_workspace):
    """测试白名单中存在新鲜文件时快速返回 True。"""
    ws = mock_lease_workspace
    app_path = os.path.join(ws, "src", "app.py")
    now = time.time()
    os.utime(app_path, (now - 10, now - 10))

    assert is_workspace_actively_modifying(ws, ["src/app.py"], window_seconds=300) is True


def test_is_workspace_actively_modifying_stale_file(mock_lease_workspace):
    """测试白名单文件已过期且父目录亦过期时返回 False。"""
    ws = mock_lease_workspace
    app_path = os.path.join(ws, "src", "app.py")
    src_dir = os.path.join(ws, "src")
    now = time.time()
    # 文件修改于 1000 秒前
    os.utime(app_path, (now - 1000, now - 1000))
    # 父目录修改于 1000 秒前
    os.utime(src_dir, (now - 1000, now - 1000))

    assert is_workspace_actively_modifying(ws, ["src/app.py"], window_seconds=300) is False


def test_is_workspace_actively_modifying_traversal_paths_filtered(mock_lease_workspace, capsys):
    """测试越界/穿越路径（../、跨盘绝对路径）被静默剔除；剔除后无有效目标返回 True（保守存活）。"""
    ws = mock_lease_workspace
    traversal_files = [
        "../../etc/passwd",
        "../outside.py",
        "C:\\Windows\\System32\\cmd.exe" if os.name == "nt" else "/etc/shadow",
    ]

    res = is_workspace_actively_modifying(ws, traversal_files, window_seconds=300)
    assert res is True
    err = capsys.readouterr().err
    assert "returning True (fail-safe conservative alive)" in err


def test_is_workspace_actively_modifying_all_stat_failed_conservative_alive(mock_lease_workspace, capsys):
    """测试全部 stat 失败（如指定不存在且父目录亦不存在的文件）返回 True 且 stderr 告警。"""
    ws = mock_lease_workspace
    ghost_files = ["nonexistent_dir_xyz/ghost_file.py"]

    res = is_workspace_actively_modifying(ws, ghost_files, window_seconds=300)
    assert res is True
    err = capsys.readouterr().err
    assert "returning True (fail-safe conservative alive)" in err


def test_is_workspace_actively_modifying_parent_dir_fallback_cold_start(mock_lease_workspace):
    """测试 [NEW] 文件尚未生成时，父目录近期 mtime 兜底冷启动判定为活跃。"""
    ws = mock_lease_workspace
    src_dir = os.path.join(ws, "src")
    now = time.time()
    # 父目录刚刚被写入/更新
    os.utime(src_dir, (now - 20, now - 20))

    # new_module.py 尚不存在
    new_module_rel = "src/new_module.py"
    assert not os.path.exists(os.path.join(ws, new_module_rel))

    assert is_workspace_actively_modifying(ws, [new_module_rel], window_seconds=300) is True


def test_is_workspace_actively_modifying_max_scan_truncation(mock_lease_workspace, capsys):
    """测试候选目标超过 max_scan 时截断并记录告警。"""
    ws = mock_lease_workspace
    large_list = [f"src/file_{i}.py" for i in range(300)]

    res = is_workspace_actively_modifying(ws, large_list, window_seconds=300, max_scan=50)
    assert res is True  # 全不存在 -> 全部失败保守存活
    err = capsys.readouterr().err
    assert "exceeds max_scan 50, truncating" in err


# ==============================================================================
# 2. touch_lease_heartbeat 单元测试
# ==============================================================================

def test_touch_lease_heartbeat_ttl_boundaries(mock_lease_workspace):
    """测试 TTL 越界（<= 0 或 > MAX_TTL）抛出 LeaseContractError。"""
    ws = mock_lease_workspace
    with pytest.raises(LeaseContractError) as exc_info1:
        touch_lease_heartbeat(ws, session_id="test-session", ttl_seconds=0)
    assert "must be in (0, 3600]" in str(exc_info1.value)

    with pytest.raises(LeaseContractError) as exc_info2:
        touch_lease_heartbeat(ws, session_id="test-session", ttl_seconds=-10)
    assert "must be in (0, 3600]" in str(exc_info2.value)

    with pytest.raises(LeaseContractError) as exc_info3:
        touch_lease_heartbeat(ws, session_id="test-session", ttl_seconds=MAX_TTL + 1)
    assert "must be in (0, 3600]" in str(exc_info3.value)


def test_touch_lease_heartbeat_session_and_token_matching(mock_lease_workspace):
    """测试 session_id 匹配成功续约，不匹配或 token/generation 不符 fail-closed 返回 False。"""
    ws = mock_lease_workspace
    task_file = os.path.join(ws, "docs", "dev_tasks", "2026-09-24_demo.md")
    sid = "session-valid-42"
    token = f"token_{sid}_1700000000_1234"

    # 签发租约
    gen = commit_lease(ws, task_id="1.1", holder_token=token, expected_generation=0, md_path=task_file)
    assert gen == 1

    # 1. 正常续约成功
    assert touch_lease_heartbeat(ws, session_id=sid, ttl_seconds=300) is True

    # 2. session_id 不匹配返回 False
    assert touch_lease_heartbeat(ws, session_id="session-other-99", ttl_seconds=300) is False

    # 3. 显式传入错误的 holder_token 返回 False
    assert touch_lease_heartbeat(ws, session_id=sid, ttl_seconds=300, holder_token="wrong_token") is False

    # 4. 显式传入错误的 generation 返回 False
    assert touch_lease_heartbeat(ws, session_id=sid, ttl_seconds=300, generation=999) is False

    # 5. 租约释放后（墓碑）再调用返回 False
    assert release_lease(ws, task_id="1.1", holder_token=token, generation=1) is True
    assert touch_lease_heartbeat(ws, session_id=sid, ttl_seconds=300) is False


def test_extract_session_id_helper():
    """测试从标准 holder_token 提取 session_id。"""
    assert extract_session_id_from_holder_token("token_my-session-id_1700000_999") == "my-session-id"
    assert extract_session_id_from_holder_token("token_part1_part2_1700000_999") == "part1_part2"
    assert extract_session_id_from_holder_token("plain_token") is None
    assert extract_session_id_from_holder_token("") is None


# ==============================================================================
# 3. reaper.py 沉浸防杀探针联动测试
# ==============================================================================

def test_reaper_probe_immersion_anti_kill_downgrade(mock_lease_workspace):
    """测试心跳静默超时 (hb_stale) 但受管文件活跃时，沉浸防杀探针生效，降级判定为 HEALTHY。"""
    ws = mock_lease_workspace
    task_file = os.path.join(ws, "docs", "dev_tasks", "2026-09-24_demo.md")
    sid = "worker-session-7"
    token = f"token_{sid}_1700000000_1234"

    commit_lease(ws, task_id="1.1", holder_token=token, expected_generation=0, md_path=task_file)

    base_time = 1700000000.0
    # 文件在 50 秒前刚修改（处于活跃编辑状态，<= 600s 阈值）
    app_file = os.path.join(ws, "src", "app.py")
    os.utime(app_file, (base_time - 50, base_time - 50))

    # 心跳设置为 1500 秒前（静默超时，> 900s 阈值）
    hb_time = datetime.fromtimestamp(base_time - 1500, tz=timezone.utc).isoformat()
    now_wall = datetime.fromtimestamp(base_time, tz=timezone.utc).isoformat()

    touch_heartbeat(
        ws,
        task_id="2026-09-24_demo::1.1",
        holder_token=token,
        generation=1,
        now_wall_utc=hb_time,
    )

    ev = probe_lease_health(ws, task_id="2026-09-24_demo::1.1", now_wall_utc=now_wall)
    assert ev.verdict == HealthVerdict.HEALTHY
    assert any("沉浸防杀探针命中" in r or "受管文件处于新鲜活跃状态" in r for r in ev.reasons)


def test_is_workspace_actively_modifying_samples_and_parent_fallback(mock_lease_workspace):
    """测试样本路径穿越（跨盘、相对穿越）与父目录冷启动兜底。"""
    ws = mock_lease_workspace
    samples = [
        "../escape.py",
        "../../escape2.py",
        "Z:\\not_in_ws\\bad.py" if os.name == "nt" else "/tmp/bad.py",
        "src/nonexistent_file.py",
    ]
    # src 目录修改于 10 秒前
    src_dir = os.path.join(ws, "src")
    os.utime(src_dir, (time.time() - 10, time.time() - 10))

    # 穿越路径静默剔除，nonexistent_file.py 的父目录 src 存在且新鲜，返回 True
    assert is_workspace_actively_modifying(ws, samples, window_seconds=300) is True


def test_touch_lease_heartbeat_binding_contract_all_variations(mock_lease_workspace):
    """测试 session_id ∧ holder_token ∧ generation 三者绑定校验的各种失败与成功分支。"""
    ws = mock_lease_workspace
    task_file = os.path.join(ws, "docs", "dev_tasks", "2026-09-24_demo.md")
    sid = "strict-session-99"
    token = f"token_{sid}_1700000000_5678"

    gen = commit_lease(ws, task_id="1.1", holder_token=token, expected_generation=0, md_path=task_file)
    assert gen == 1

    # 1. 全部吻合 -> True
    assert touch_lease_heartbeat(ws, session_id=sid, ttl_seconds=60, holder_token=token, generation=1) is True

    # 2. generation 不符 -> False
    assert touch_lease_heartbeat(ws, session_id=sid, ttl_seconds=60, holder_token=token, generation=2) is False

    # 3. holder_token 不符 -> False
    assert touch_lease_heartbeat(ws, session_id=sid, ttl_seconds=60, holder_token="rogue_token", generation=1) is False

    # 4. session_id 不符 -> False
    assert touch_lease_heartbeat(ws, session_id="wrong-session", ttl_seconds=60, holder_token=token, generation=1) is False

