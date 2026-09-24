# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import os
from dataclasses import asdict
import pytest

from manifest import (
    Manifest,
    TaskRecord,
    ManifestRecordOverflowError,
    ManifestMetrics,
    compute_manifest_metrics,
    atomic_replace_manifest,
    load_manifest,
    MANIFEST_REL_PATH,
)
from observability_policy import MAX_RECORD_BYTES


@pytest.fixture
def manifest_bounds_workspace(tmp_path):
    ws = tmp_path / "bounds_ws"
    ws.mkdir(parents=True)
    manifest_dir = ws / ".agents" / ".quorch"
    manifest_dir.mkdir(parents=True)
    return ws


def test_compute_manifest_metrics_purity_and_accuracy(manifest_bounds_workspace):
    ws = manifest_bounds_workspace
    rec1 = TaskRecord(
        task_id="demo::1.1",
        md_sha256="a" * 64,
        generation=1,
        holder_token="tok1",
        last_heartbeat_monotonic_ns=1000,
        last_heartbeat_wall_utc="2026-09-24T00:00:00Z",
        git_head_sha="git1",
        git_index_mtime=100.0,
        released=False,
    )
    rec2 = TaskRecord(
        task_id="demo::1.2",
        md_sha256="b" * 64,
        generation=2,
        holder_token="tok2",
        last_heartbeat_monotonic_ns=2000,
        last_heartbeat_wall_utc="2026-09-24T01:00:00Z",
        git_head_sha="git2",
        git_index_mtime=200.0,
        released=True,
    )

    manifest = Manifest(schema_version="1.0", records={"demo::1.1": rec1, "demo::1.2": rec2})
    orig_records = dict(manifest.records)

    metrics = compute_manifest_metrics(manifest)

    assert isinstance(metrics, ManifestMetrics)
    assert metrics.record_count == 2
    assert metrics.total_bytes > 0
    assert metrics.max_record_bytes == MAX_RECORD_BYTES
    # 纯函数保证：输入对象无任何副作用
    assert manifest.records == orig_records


def test_overflow_raises_error_and_preserves_disk(manifest_bounds_workspace):
    ws = manifest_bounds_workspace
    initial_rec = TaskRecord(
        task_id="valid::1.1",
        md_sha256="c" * 64,
        generation=1,
        holder_token="valid_token",
        last_heartbeat_monotonic_ns=5000,
        last_heartbeat_wall_utc="2026-09-24T02:00:00Z",
        git_head_sha="git_valid",
        git_index_mtime=500.0,
        released=False,
    )
    initial_manifest = Manifest(schema_version="1.0", records={"valid::1.1": initial_rec})
    atomic_replace_manifest(str(ws), initial_manifest)

    manifest_file = ws / MANIFEST_REL_PATH
    initial_content = manifest_file.read_text(encoding="utf-8")

    # 构造一条单条序列化后超过 16KB (MAX_RECORD_BYTES) 的恶意超长记录
    huge_holder_token = "X" * (MAX_RECORD_BYTES + 100)
    overflow_rec = TaskRecord(
        task_id="overflow::9.9",
        md_sha256="d" * 64,
        generation=99,
        holder_token=huge_holder_token,
        last_heartbeat_monotonic_ns=9999,
        last_heartbeat_wall_utc="2026-09-24T09:00:00Z",
        git_head_sha="git_huge",
        git_index_mtime=999.0,
        released=False,
    )

    bad_manifest = Manifest(
        schema_version="1.0",
        records={"valid::1.1": initial_rec, "overflow::9.9": overflow_rec},
    )

    with pytest.raises(ManifestRecordOverflowError) as exc_info:
        atomic_replace_manifest(str(ws), bad_manifest)

    assert "exceeds MAX_RECORD_BYTES" in str(exc_info.value)
    assert "Fail-Closed" in str(exc_info.value)

    # 磁盘原子性验证：磁盘清单文件内容保持完全不变，没有半写损坏
    assert manifest_file.read_text(encoding="utf-8") == initial_content
    loaded = load_manifest(str(ws))
    assert "overflow::9.9" not in loaded.records
    assert "valid::1.1" in loaded.records


def test_utf8_cjk_multibyte_byte_length_accuracy(manifest_bounds_workspace):
    ws = manifest_bounds_workspace
    # 中文字符每个字符在 UTF-8 下占用 3 字节
    cjk_prefix = "中文字符测试超长"
    # 构造一个字符数不足 16K，但 UTF-8 字节数恰好超过 16KB 的超长 token
    # 6000 个中文字符 = 18,000 字节 > 16,384 字节 (MAX_RECORD_BYTES)
    cjk_token = cjk_prefix * 750

    overflow_cjk_rec = TaskRecord(
        task_id="cjk::1.1",
        md_sha256="e" * 64,
        generation=1,
        holder_token=cjk_token,
        last_heartbeat_monotonic_ns=1111,
        last_heartbeat_wall_utc="2026-09-24T12:00:00Z",
        git_head_sha="git_cjk",
        git_index_mtime=111.0,
        released=False,
    )

    cjk_manifest = Manifest(schema_version="1.0", records={"cjk::1.1": overflow_cjk_rec})

    with pytest.raises(ManifestRecordOverflowError):
        atomic_replace_manifest(str(ws), cjk_manifest)


def test_normal_sized_record_persists_successfully(manifest_bounds_workspace):
    ws = manifest_bounds_workspace
    normal_rec = TaskRecord(
        task_id="normal::1.1",
        md_sha256="f" * 64,
        generation=1,
        holder_token="token_normal_123",
        last_heartbeat_monotonic_ns=3333,
        last_heartbeat_wall_utc="2026-09-24T15:00:00Z",
        git_head_sha="git_normal",
        git_index_mtime=333.0,
        released=True,
    )
    manifest = Manifest(schema_version="1.0", records={"normal::1.1": normal_rec})

    atomic_replace_manifest(str(ws), manifest)
    loaded = load_manifest(str(ws))

    assert "normal::1.1" in loaded.records
    assert loaded.records["normal::1.1"].holder_token == "token_normal_123"
    assert loaded.records["normal::1.1"].released is True
