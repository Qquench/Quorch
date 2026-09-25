# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import os
import sys
import pytest

# Ensure server module is in sys.path
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from reviewer_jobs import (
    JobProgress,
    JobRecord,
    JobState,
    MAX_LOG_REF_CHARS,
    MAX_NONTERMINAL_SNAPSHOT_BYTES,
    POLL_NONTERMINAL_FIELDS,
    POLL_TERMINAL_FIELDS,
    PollSnapshot,
    ReviewerPhase,
    SnapshotContractViolation,
    canonical_snapshot_bytes,
    format_progress,
    project_nonterminal,
    project_terminal,
    validate_job_id,
    ReviewerJobSupervisor,
)


def test_i5_poll_zero_lock_and_bounded_metadata_no_text():
    """I5: Poll 只读零锁与极简白名单契约：非终态严格等于 6 字段且 <= 1024 字节，不含 reasoning 文本。"""
    prog = JobProgress(
        elapsed_s=15.42,
        approx_reasoning_tokens=520,
        phase=ReviewerPhase.STREAMING,
        idle_s=1.2,
    )
    snap = PollSnapshot(
        job_id="job_20260925_abc123",
        session_id="session_test_001",
        state=JobState.RUNNING,
        retry_after_seconds=5,
        log_ref="20260925_001_session_test_001.log",
        progress=prog,
    )

    projected = project_nonterminal(snap)
    assert set(projected.keys()) == POLL_NONTERMINAL_FIELDS
    assert projected["job_id"] == "job_20260925_abc123"
    assert projected["session_id"] == "session_test_001"
    assert projected["state"] == "RUNNING"
    assert projected["retry_after_seconds"] == 5
    assert projected["log_ref"] == "20260925_001_session_test_001.log"
    assert projected["progress"]["phase"] == "streaming"
    assert projected["progress"]["approx_reasoning_tokens"] == 520

    # 严禁泄露文本
    forbidden = {"findings", "reasoning", "raw_reasoning", "chain_of_thought", "text", "content"}
    assert not (set(projected.keys()) & forbidden)

    # 序列化度量必须 <= 1024 字节
    size = canonical_snapshot_bytes(projected)
    assert size <= MAX_NONTERMINAL_SNAPSHOT_BYTES


def test_i5b_snapshot_over_cap_raises_not_truncates(monkeypatch):
    """I5-B: 白名单纯净与防溢出：超限 1KB 抛 SnapshotContractViolation 严禁截断。"""
    prog = JobProgress(
        elapsed_s=15.42,
        approx_reasoning_tokens=520,
        phase=ReviewerPhase.STREAMING,
        idle_s=1.2,
    )
    snap = PollSnapshot(
        job_id="job_20260925_abc123",
        session_id="session_test_001",
        state=JobState.RUNNING,
        retry_after_seconds=5,
        log_ref="20260925_001_test.log",
        progress=prog,
    )

    # 模拟超大 payload 触发 1024 字节上限
    orig_canonical = canonical_snapshot_bytes
    monkeypatch.setattr(
        "reviewer_jobs.canonical_snapshot_bytes",
        lambda p: 1025,
    )

    with pytest.raises(SnapshotContractViolation) as exc_info:
        project_nonterminal(snap)
    assert "exceeds 1024 bytes limit" in str(exc_info.value)


def test_i5c_terminal_snapshot_bounded_and_no_raw_cot():
    """I5-C: 终态契约与对称投影：终态经 project_terminal 双源投影，findings 受字符预算截断，断言交集无 reasoning/raw_reasoning。"""
    rec = JobRecord(
        job_id="job_terminal_1",
        session_id="session_terminal_1",
        workspace_root="/test/ws",
        mode="critique",
        owner_pid=1234,
        owner_boot_nonce="nonce_test",
        generation=2,
        state=JobState.COMPLETED,
        created_monotonic=100.0,
        updated_monotonic=120.0,
        created_wall_utc="2026-09-25T00:00:00Z",
        updated_wall_utc="2026-09-25T00:00:20Z",
        log_path="/path/to/log.log",
        progress=JobProgress(20.0, 1000, ReviewerPhase.FINALIZING, 0.5),
        result_ref="/path/to/result.json",
        degraded_reason=None,
    )

    # 1. 正常终态结果
    result = {
        "status": "success",
        "findings": "All looks good.",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    terminal = project_terminal(rec, result)
    assert set(terminal.keys()) == POLL_TERMINAL_FIELDS
    assert terminal["job_id"] == "job_terminal_1"
    assert terminal["state"] == "COMPLETED"
    assert terminal["log_path"] == "/path/to/log.log"
    assert terminal["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert terminal["result"]["findings"] == "All looks good."

    # 2. 注入禁止的 reasoning keys 必须抛出断言错误
    for bad_key in ["reasoning", "raw_reasoning", "chain_of_thought"]:
        bad_result = dict(result)
        bad_result[bad_key] = "secret chain of thought"
        with pytest.raises(AssertionError) as exc_info:
            project_terminal(rec, bad_result)
        assert "forbidden raw reasoning keys" in str(exc_info.value)

    # 3. findings 超过 40000 字符必须被截断
    huge_result = {
        "status": "success",
        "findings": "A" * 45000,
        "usage": {},
    }
    bounded = project_terminal(rec, huge_result)
    assert len(bounded["result"]["findings"]) == 40000


def test_i6_retry_after_clamped_and_min_interval_gate(tmp_path):
    """I6: 退避钳制防风暴：服务端 retry_after_seconds 严格钳制在 [2, 30] 闭区间。"""
    supervisor = ReviewerJobSupervisor(tmp_path)
    # elapsed = 0 -> clamped to 2
    assert supervisor._compute_retry_after(0.0) == 2
    # elapsed = 5.0 -> 2 + 1 = 3
    assert supervisor._compute_retry_after(5.0) == 3
    # elapsed = 50.0 -> 2 + 10 = 12
    assert supervisor._compute_retry_after(50.0) == 12
    # elapsed = 200.0 -> clamped to 30
    assert supervisor._compute_retry_after(200.0) == 30
    # negative elapsed -> clamped to 2
    assert supervisor._compute_retry_after(-10.0) == 2


def test_i9_job_id_path_traversal_rejected():
    """I9: 严格校验与路径隔离：validate_job_id 拒绝 Windows 保留名与路径穿越。"""
    # 正常 job_id
    assert validate_job_id("job_123_abc") == "job_123_abc"
    assert validate_job_id("valid-job-99") == "valid-job-99"

    # 空值或纯空格
    with pytest.raises(ValueError):
        validate_job_id("")
    with pytest.raises(ValueError):
        validate_job_id(None)
    with pytest.raises(ValueError):
        validate_job_id("   ")

    # 路径穿越
    for bad_id in ["../job", "job/1", "job\\1", "..", "../../etc/passwd"]:
        with pytest.raises(ValueError):
            validate_job_id(bad_id)

    # Windows 保留设备名 (不区分大小写，支持扩展名前缀)
    for res_name in ["con", "CON", "prn", "AUX", "nul", "COM1", "lpt2", "aux.json"]:
        with pytest.raises(ValueError):
            validate_job_id(res_name)

    # 非法字符
    for bad_char in ["job*1", "job?2", "job:3", "job|4", "job\"5", "job<6", "job>7"]:
        with pytest.raises(ValueError):
            validate_job_id(bad_char)

    # 长度超限 (> 64)
    with pytest.raises(ValueError):
        validate_job_id("a" * 65)


def test_i18n_progress_formatting_default_en_and_zh():
    """I18N: 本地化转译验证：format_progress 验证默认英文及中文嗅探输出，3相2语6种状态全覆盖。"""
    prog = JobProgress(
        elapsed_s=65.0,  # 1m 5s
        approx_reasoning_tokens=300,
        phase=ReviewerPhase.ASSEMBLING,
        idle_s=4.0,
    )

    # 1. 显式 en
    msg_en_asm = format_progress(prog, locale="en")
    assert msg_en_asm == "Thinking (assembling) · 1m 5s · idle 4s"

    # 2. 显式 zh
    msg_zh_asm = format_progress(prog, locale="zh")
    assert msg_zh_asm == "正在思考 (组装中) · 1min 5s · 静默 4s"

    # 3. 覆盖 streaming 和 finalizing
    prog_stream = JobProgress(elapsed_s=120.0, approx_reasoning_tokens=500, phase=ReviewerPhase.STREAMING, idle_s=2.0)
    assert format_progress(prog_stream, locale="en") == "Thinking (streaming) · 2m 0s · idle 2s"
    assert format_progress(prog_stream, locale="zh") == "正在思考 (思考中) · 2min 0s · 静默 2s"

    prog_fin = JobProgress(elapsed_s=185.0, approx_reasoning_tokens=800, phase=ReviewerPhase.FINALIZING, idle_s=0.0)
    assert format_progress(prog_fin, locale="en") == "Thinking (finalizing) · 3m 5s · idle 0s"
    assert format_progress(prog_fin, locale="zh") == "正在思考 (总结中) · 3min 5s · 静默 0s"

    # 4. 环境变量优先级：locale > LC_ALL > LC_MESSAGES > LANG > 'en'
    # LC_ALL 为 zh
    assert format_progress(prog, env={"LC_ALL": "zh_CN.UTF-8"}) == "正在思考 (组装中) · 1min 5s · 静默 4s"
    # LC_ALL 为空，LC_MESSAGES 为 zh
    assert format_progress(prog, env={"LC_ALL": "", "LC_MESSAGES": "zh_CN"}) == "正在思考 (组装中) · 1min 5s · 静默 4s"
    # 前两者为空，LANG 为 zh
    assert format_progress(prog, env={"LC_ALL": "", "LC_MESSAGES": "", "LANG": "zh_TW.UTF-8"}) == "正在思考 (组装中) · 1min 5s · 静默 4s"
    # 全部为空，默认 'en'
    assert format_progress(prog, env={"LC_ALL": "", "LC_MESSAGES": "", "LANG": ""}) == "Thinking (assembling) · 1m 5s · idle 4s"
    # 入参 locale 优先于环境变量
    assert format_progress(prog, locale="en", env={"LC_ALL": "zh_CN"}) == "Thinking (assembling) · 1m 5s · idle 4s"
