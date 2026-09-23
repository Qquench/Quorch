# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from manifest import (
    FencedTokenError,
    Manifest,
    TaskRecord,
    MANIFEST_REL_PATH,
    atomic_replace_manifest,
    compare_and_swap,
    commit_lease,
    compute_normalized_md_hash,
    load_manifest,
    release_lease,
)
from server import (
    dev_tasks_checkout,
    dev_tasks_complete,
    dev_tasks_confirm,
    dev_tasks_propose,
)


@pytest.fixture
def mock_workspace():
    temp_dir = tempfile.mkdtemp(prefix="quench_manifest_test_")
    agents_dir = os.path.join(temp_dir, ".agents")
    os.makedirs(agents_dir, exist_ok=True)

    config_data = {
        "project_name": "ManifestTestProject",
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

    yield temp_dir
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_normalized_md_hash_status_invariance():
    """验证状态图标与词汇变更不影响正文哈希 (B1 规范化哈希)。"""
    base_md = (
        "# 2026-09-24_feature.md\n\n"
        "### 任务 1.1 ⬜ 待确认 — 第一项任务 (Task One)\n\n"
        "#### 【涉及文件】\n"
        "```\n"
        "[MODIFY] src/app.py\n"
        "```\n\n"
        "#### 【缺陷根因与修改目标】\n"
        "测试正文内容说明。\n"
    )

    h_pending = compute_normalized_md_hash(base_md)

    # 模拟流转为 ✅ 已确认
    md_confirmed = base_md.replace("⬜ 待确认", "✅ 已确认")
    assert compute_normalized_md_hash(md_confirmed) == h_pending

    # 模拟流转为 🔨 执行中
    md_in_progress = base_md.replace("⬜ 待确认", "🔨 执行中")
    assert compute_normalized_md_hash(md_in_progress) == h_pending

    # 模拟流转为 ✔️ 已完成
    md_completed = base_md.replace("⬜ 待确认", "✔️ 已完成")
    assert compute_normalized_md_hash(md_completed) == h_pending

    # 模拟英文变体 In Progress
    md_en = base_md.replace("⬜ 待确认", "🔨 In Progress")
    assert compute_normalized_md_hash(md_en) == h_pending


def test_normalized_md_hash_comment_invariance_and_tamper_detection():
    """验证 HTML 元注释不影响哈希，但正文篡改能够被立刻检测。"""
    base_md = (
        "### 任务 1.1 ✅ 已确认 — 核心业务重构\n\n"
        "- 步骤 1: 编写核心逻辑\n"
    )
    h_orig = compute_normalized_md_hash(base_md)

    # 添加单行及多行 HTML 注释
    with_comment = base_md + "\n<!-- 实施期人类非结构性备注说明 -->\n<!--\n多行注释\n-->"
    assert compute_normalized_md_hash(with_comment) == h_orig

    # 篡改任务正文
    tampered = base_md.replace("核心业务重构", "未核准越权修改")
    assert compute_normalized_md_hash(tampered) != h_orig


def test_load_and_atomic_replace_manifest(mock_workspace):
    """验证首次加载自动初始化容器与原子写入/损坏自愈能力。"""
    ws = mock_workspace

    # 首次加载：不存在 manifest.json，自动初始化空容器
    m = load_manifest(ws)
    assert m.schema_version == "1.0"
    assert len(m.records) == 0

    # 写入记录
    rec = TaskRecord(
        task_id="test_spec::1.1",
        md_sha256="abc123hash",
        generation=1,
        holder_token="tok_test_001",
        last_heartbeat_monotonic_ns=1000,
        last_heartbeat_wall_utc="2026-09-24T00:00:00Z",
        git_head_sha="deadbeef",
        git_index_mtime=1700000000.0,
        released=False,
    )
    m.records["test_spec::1.1"] = rec
    atomic_replace_manifest(ws, m)

    # 重新加载
    reloaded = load_manifest(ws)
    assert "test_spec::1.1" in reloaded.records
    assert reloaded.records["test_spec::1.1"].generation == 1
    assert reloaded.records["test_spec::1.1"].holder_token == "tok_test_001"

    # 损坏恢复：故意破坏 manifest.json
    manifest_file = os.path.join(ws, MANIFEST_REL_PATH)
    with open(manifest_file, "w", encoding="utf-8") as f:
        f.write("{invalid_json: true, broken...")

    recovered = load_manifest(ws)
    assert recovered.schema_version == "1.0"
    assert len(recovered.records) == 0


def test_commit_lease_lifecycle_and_split_brain_prevention(mock_workspace):
    """测试 commit_lease 租约签发、单调自增与防分裂脑冲突校验。"""
    ws = mock_workspace
    md_dir = os.path.join(ws, "docs", "dev_tasks")
    os.makedirs(md_dir, exist_ok=True)
    task_file = os.path.join(md_dir, "2026-09-24_demo.md")

    with open(task_file, "w", encoding="utf-8") as f:
        f.write("### 任务 1.1 ✅ 已确认 — 测试演示\n\n正文细节\n")

    # 初始签发：expected_generation 必须为 0
    with pytest.raises(FencedTokenError, match="expected_generation must be 0"):
        commit_lease(
            ws,
            task_id="1.1",
            holder_token="token_A",
            expected_generation=1,
            md_path=task_file,
        )

    gen1 = commit_lease(
        ws,
        task_id="1.1",
        holder_token="token_A",
        expected_generation=0,
        md_path=task_file,
    )
    assert gen1 == 1

    # 校验命名空间键
    m = load_manifest(ws)
    expected_key = "2026-09-24_demo::1.1"
    assert expected_key in m.records
    assert m.records[expected_key].generation == 1
    assert m.records[expected_key].holder_token == "token_A"
    assert m.records[expected_key].released is False

    # 分裂脑防御 1：另一个 token 试图签发正处于租期中的任务
    with pytest.raises(FencedTokenError, match="lease is currently held"):
        commit_lease(
            ws,
            task_id="1.1",
            holder_token="token_B_rogue",
            expected_generation=1,
            md_path=task_file,
        )

    # 分裂脑防御 2：携带过期代际
    with pytest.raises(FencedTokenError, match="Generation mismatch"):
        commit_lease(
            ws,
            task_id="1.1",
            holder_token="token_A",
            expected_generation=0,
            md_path=task_file,
        )

    # 正常续签 / 晋升代际
    gen2 = commit_lease(
        ws,
        task_id="1.1",
        holder_token="token_A",
        expected_generation=1,
        md_path=task_file,
    )
    assert gen2 == 2


def test_commit_lease_rejects_altered_markdown(mock_workspace):
    """测试若任务正文在租约周期内被越权篡改，拒绝 commit_lease。"""
    ws = mock_workspace
    md_dir = os.path.join(ws, "docs", "dev_tasks")
    os.makedirs(md_dir, exist_ok=True)
    task_file = os.path.join(md_dir, "2026-09-24_tamper.md")

    with open(task_file, "w", encoding="utf-8") as f:
        f.write("### 任务 1.1 ✅ 已确认 — 原始任务描述\n")

    gen1 = commit_lease(
        ws,
        task_id="1.1",
        holder_token="token_X",
        expected_generation=0,
        md_path=task_file,
    )
    assert gen1 == 1

    # 越权篡改任务正文
    with open(task_file, "w", encoding="utf-8") as f:
        f.write("### 任务 1.1 ✅ 已确认 — 恶意篡改任务描述\n")

    with pytest.raises(FencedTokenError, match="content hash mismatch"):
        commit_lease(
            ws,
            task_id="1.1",
            holder_token="token_X",
            expected_generation=1,
            md_path=task_file,
        )


def test_compare_and_swap_atomicity(mock_workspace):
    """测试 compare_and_swap 原子代际更新与单调性校验。"""
    ws = mock_workspace
    md_dir = os.path.join(ws, "docs", "dev_tasks")
    os.makedirs(md_dir, exist_ok=True)
    task_file = os.path.join(md_dir, "2026-09-24_cas.md")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write("### 任务 1.1 ✅ 已确认 — CAS 测试\n")

    commit_lease(ws, task_id="1.1", holder_token="tok_1", expected_generation=0, md_path=task_file)

    # 1. 成功 CAS
    ok = compare_and_swap(
        ws,
        task_id="2026-09-24_cas::1.1",
        expected_generation=1,
        new_generation=2,
        holder_token="tok_2",
    )
    assert ok is True

    # 2. 失败 CAS：非单调（new <= expected）
    fail_non_monotonic = compare_and_swap(
        ws,
        task_id="2026-09-24_cas::1.1",
        expected_generation=2,
        new_generation=2,
        holder_token="tok_3",
    )
    assert fail_non_monotonic is False

    # 3. 失败 CAS：过期代际
    fail_stale = compare_and_swap(
        ws,
        task_id="2026-09-24_cas::1.1",
        expected_generation=1,
        new_generation=3,
        holder_token="tok_3",
    )
    assert fail_stale is False


def test_release_lease_tombstone_preservation(mock_workspace):
    """测试 release_lease 留痕墓碑（released=True，保留 generation 永不回退，B5）。"""
    ws = mock_workspace
    md_dir = os.path.join(ws, "docs", "dev_tasks")
    os.makedirs(md_dir, exist_ok=True)
    task_file = os.path.join(md_dir, "2026-09-24_tombstone.md")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write("### 任务 1.1 ✅ 已确认 — 墓碑留痕\n")

    gen = commit_lease(ws, task_id="1.1", holder_token="tok_owner", expected_generation=0, md_path=task_file)
    assert gen == 1

    # 分裂脑防御：旧/错 token 试图释放
    assert release_lease(ws, task_id="1.1", holder_token="wrong_token", generation=1) is False
    # 分裂脑防御：错误 generation 试图释放
    assert release_lease(ws, task_id="1.1", holder_token="tok_owner", generation=99) is False

    # 正常释放
    assert release_lease(ws, task_id="1.1", holder_token="tok_owner", generation=1) is True

    # 检查墓碑状态
    m = load_manifest(ws)
    rec = m.records["2026-09-24_tombstone::1.1"]
    assert rec.released is True
    assert rec.generation == 1  # 代际完好保留，不被重置或物理删除

    # 幂等释放
    assert release_lease(ws, task_id="1.1", holder_token="tok_owner", generation=1) is True


def test_monotonic_clock_and_git_drift_snapshot(mock_workspace):
    """测试单调纳秒时钟在墙钟漂移时的稳定性与 Git 容错快照。"""
    ws = mock_workspace
    md_dir = os.path.join(ws, "docs", "dev_tasks")
    os.makedirs(md_dir, exist_ok=True)
    task_file = os.path.join(md_dir, "2026-09-24_clock.md")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write("### 任务 1.1 ✅ 已确认 — 时钟测试\n")

    # 模拟墙钟发生回拨（如 NTP 调整）
    wall_past = "2020-01-01T00:00:00Z"
    with patch("manifest.datetime") as mock_dt:
        mock_dt.now.return_value.isoformat.return_value = wall_past
        commit_lease(ws, task_id="1.1", holder_token="tok_c", expected_generation=0, md_path=task_file)

    m = load_manifest(ws)
    rec = m.records["2026-09-24_clock::1.1"]
    # 墙钟记录了指定时间，而 monotonic_ns 始终为正单调整数
    assert rec.last_heartbeat_wall_utc == wall_past
    assert rec.last_heartbeat_monotonic_ns > 0


def test_server_checkout_complete_lease_integration(mock_workspace):
    """测试 MCP 工具 dev_tasks_checkout 与 dev_tasks_complete 的租约签发、校验与释放全链路。"""
    ws = mock_workspace

    # 1. 提出并确认任务
    tasks = [
        {
            "id": "1.1",
            "title": "租约集成任务",
            "affected_files": ["[MODIFY] src/app.py"],
            "root_cause_and_goal": "测试租约机制",
            "type_contracts": "无",
            "steps": ["1. 实施"],
            "defensive_checks": ["无"],
            "dod_commands": ["pytest"],
        }
    ]
    dev_tasks_propose(ws, "2026-09-24_integration.md", tasks)
    dev_tasks_confirm(ws, "2026-09-24_integration.md", ["1.1"], action="confirm")

    # 2. 检出领单 checkout
    chk = dev_tasks_checkout(ws, task_file="2026-09-24_integration.md", task_id="1.1")
    assert chk["status"] == "🔨 执行中"
    assert "holder_token" in chk
    assert chk["generation"] == 1
    token = chk["holder_token"]
    gen = chk["generation"]

    # 检查 manifest.json
    m = load_manifest(ws)
    key = "2026-09-24_integration::1.1"
    assert key in m.records
    assert m.records[key].holder_token == token
    assert m.records[key].generation == 1
    assert m.records[key].released is False

    # 3. 模拟分裂脑：携带伪造的 token 尝试 complete，必须被拦截
    rogue_complete = dev_tasks_complete(
        ws,
        task_file="2026-09-24_integration.md",
        task_id="1.1",
        dod_output="All ok",
        holder_token="fake_token_rogue",
        generation=gen,
    )
    assert rogue_complete["status"] == "rejected"
    assert "conflict" in rogue_complete["reason"]

    # 4. 模拟分裂脑：携带过期 generation 尝试 complete，必须被拦截
    stale_complete = dev_tasks_complete(
        ws,
        task_file="2026-09-24_integration.md",
        task_id="1.1",
        dod_output="All ok",
        holder_token=token,
        generation=999,
    )
    assert stale_complete["status"] == "rejected"
    assert "mismatch" in stale_complete["reason"]

    # 5. 合法持有者提交完成
    valid_complete = dev_tasks_complete(
        ws,
        task_file="2026-09-24_integration.md",
        task_id="1.1",
        dod_output="All ok",
        test_evidence="[EXEMPTION: config-only]",
        holder_token=token,
        generation=gen,
    )
    assert valid_complete["status"] == "completed"

    # 6. 检查租约已被留痕标记为 released
    m_after = load_manifest(ws)
    assert m_after.records[key].released is True
    assert m_after.records[key].generation == 1
