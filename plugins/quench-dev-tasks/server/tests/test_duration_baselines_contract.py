"""Unit tests for test suite duration baselines, variance guards, and anti-reentry contracts (TR-3)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure scripts dir is accessible
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_test_duration_baselines as bench_tool  # noqa: E402
import check_test_tiering_invariants as tiering_gate  # noqa: E402

# 重入哨兵物理隔离：若父进程已注入 REENTRY_GUARD_ENV，立即 skip 本模块
if bench_tool.should_skip_benchmark_harness(os.environ):
    pytest.skip("Benchmark re-entry guard active / 基线测量自递归重入保护触发", allow_module_level=True)


def test_calculate_metrics_analytic_fixture():
    """M1: 验证 statistics.stdev(ddof=1) 解析可验证夹具 (1.0, 2.0, 3.0) -> mean=2.0, std_dev=1.0, cv=0.5。"""
    metrics = bench_tool.calculate_metrics([1.0, 2.0, 3.0])
    assert metrics.iterations == 3
    assert metrics.durations == (1.0, 2.0, 3.0)
    assert metrics.mean == 2.0
    assert metrics.min_duration == 1.0
    assert metrics.max_duration == 3.0
    assert metrics.std_dev == 1.0
    assert metrics.cv == 0.5


def test_calculate_metrics_single_and_empty():
    """验证单样本与空样本除零边界。"""
    m_single = bench_tool.calculate_metrics([2.5])
    assert m_single.iterations == 1
    assert m_single.mean == 2.5
    assert m_single.std_dev == 0.0
    assert m_single.cv == 0.0

    with pytest.raises(ValueError, match="durations sequence cannot be empty"):
        bench_tool.calculate_metrics([])


def test_should_skip_benchmark_harness():
    """验证重入哨兵纯函数。"""
    assert bench_tool.should_skip_benchmark_harness({bench_tool.REENTRY_GUARD_ENV: "1"}) is True
    assert bench_tool.should_skip_benchmark_harness({bench_tool.REENTRY_GUARD_ENV: "true"}) is True
    assert bench_tool.should_skip_benchmark_harness({}) is False
    assert bench_tool.should_skip_benchmark_harness({"OTHER_ENV": "1"}) is False


def test_argv_parity_with_budget_test():
    """M2: 验证 TIER1_ARGV 计时参数与既有 budget 测试逐元素一致。"""
    assert bench_tool.TIER1_ARGV == ("-m", "tier1_fast", "-q")


def test_harness_not_in_tier1_ground_truth():
    """归属断言：基于真值采集断言本契约测试文件绝对不落入 Tier-1。"""
    tier1_nodes = tiering_gate.collect_selection(REPO_ROOT, marker=tiering_gate.TIER1_MARKER)
    assert len(tier1_nodes) > 0
    harness_matches = [n for n in tier1_nodes if bench_tool.HARNESS_TEST_FILENAME in n]
    assert harness_matches == [], f"Harness leaked into Tier-1: {harness_matches}"


def test_deselect_honoured_by_pytest():
    """R3: 验证 pytest --collect-only 真实 honour 本文件的 --deselect 参数。"""
    harness_rel = Path("plugins") / "quench-dev-tasks" / "server" / "tests" / bench_tool.HARNESS_TEST_FILENAME
    deselect_arg = str(harness_rel).replace("\\", "/")

    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--deselect",
            deselect_arg,
        ],
        cwd=str(REPO_ROOT),
        env=tiering_gate.sanitized_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert res.returncode == 0, f"pytest --collect-only failed:\n{res.stderr}\n{res.stdout}"
    assert bench_tool.HARNESS_TEST_FILENAME not in res.stdout


def test_library_level_false_green_defense():
    """R-A: 库层假绿封堵：直调 run_tier1_benchmark(iterations=1) 必须 fail-closed。"""
    ok, metrics, logs = bench_tool.run_tier1_benchmark(REPO_ROOT, iterations=1, allow_retry=False)
    assert ok is False
    assert any("iterations=1 < 2" in log for log in logs)


def test_cli_anti_bypass_sub_measured_iterations():
    """M4: 反绕过物理证明：--check 模式下传入 --iterations 1 必须以非零退出码阻断。"""
    code = bench_tool.main(["--repo-root", str(REPO_ROOT), "--check", "--iterations", "1"])
    assert code != 0


def test_tier1_real_anchor_execution():
    """TP-2 真仓唯一端到端锚点：allow_retry=False，子进程数严格等于 4 (1 预热 + 3 采样)。"""
    ok, metrics, logs = bench_tool.run_tier1_benchmark(
        REPO_ROOT, iterations=bench_tool.MEASURED_ITERATIONS, allow_retry=False
    )
    assert ok is True, f"Tier-1 real anchor failed: {logs}"
    assert metrics.iterations == 3
    assert metrics.mean <= bench_tool.TIER1_HARD_FAIL_S
    assert metrics.cv <= bench_tool.TIER1_MAX_CV


def test_synthetic_cv_overrun_retry_behavior():
    """A3: 模拟 CV 超标重测：断言返回最后一次执行轮 metrics，两轮越界即 fail-closed，次轮合格即 ok。"""
    # 模拟：第 1 轮 [1.0, 2.0, 3.0] (CV=0.5 > 0.15)
    # 第 2 轮 [2.0, 2.01, 2.02] (CV=0.005 <= 0.15)
    call_count = 0

    def mock_runner_recover(cmd, env, timeout):
        nonlocal call_count
        call_count += 1
        output = "collected 25 items\n25 passed in 1.50s"
        # 预热 run 1, 采样 1, 2, 3 -> calls 1..4
        if call_count == 1:
            return 0, output, 1.0  # warmup 1
        elif call_count == 2:
            return 0, output, 1.0
        elif call_count == 3:
            return 0, output, 2.0
        elif call_count == 4:
            return 0, output, 3.0
        # 重测轮：预热 run 2, 采样 4, 5, 6 -> calls 5..8
        elif call_count == 5:
            return 0, output, 2.0  # warmup 2
        elif call_count == 6:
            return 0, output, 2.00
        elif call_count == 7:
            return 0, output, 2.01
        elif call_count == 8:
            return 0, output, 2.02
        return 0, output, 2.0

    ok, metrics, logs = bench_tool.run_tier1_benchmark(
        REPO_ROOT, iterations=3, allow_retry=True, runner_func=mock_runner_recover
    )
    assert ok is True
    # 返回第二轮实际指标
    assert metrics.durations == (2.00, 2.01, 2.02)
    assert any("Triggering bounded retry round" in log for log in logs)

    # 模拟两轮皆越界 -> fail-closed 并返回第二轮指标
    call_count_fail = 0

    def mock_runner_always_fail(cmd, env, timeout):
        nonlocal call_count_fail
        call_count_fail += 1
        output = "collected 25 items\n25 passed in 1.50s"
        # 采样恒为 [1.0, 2.0, 3.0]
        if call_count_fail in (2, 6):
            return 0, output, 1.0
        elif call_count_fail in (3, 7):
            return 0, output, 2.0
        elif call_count_fail in (4, 8):
            return 0, output, 3.0
        return 0, output, 1.0  # warmups

    ok_f, metrics_f, logs_f = bench_tool.run_tier1_benchmark(
        REPO_ROOT, iterations=3, allow_retry=True, runner_func=mock_runner_always_fail
    )
    assert ok_f is False
    assert metrics_f.durations == (1.0, 2.0, 3.0)
    assert any("exceeded 15% after retries" in log for log in logs_f)


def test_synthetic_budget_overrun_fails_closed():
    """对抗注入：耗时均值超过 TIER1_HARD_FAIL_S (8.0s) 必须 fail-closed。"""
    def mock_slow_runner(cmd, env, timeout):
        return 0, "25 passed in 9.0s", 8.5

    ok, metrics, logs = bench_tool.run_tier1_benchmark(
        REPO_ROOT, iterations=3, allow_retry=False, runner_func=mock_slow_runner
    )
    assert ok is False
    assert any("exceeded hard threshold" in log for log in logs)


def test_synthetic_zero_duration_fails_closed():
    """对抗注入：非正耗时 (min_duration <= 0) 必须 fail-closed，严禁假绿。"""
    def mock_zero_runner(cmd, env, timeout):
        return 0, "25 passed in 0.0s", 0.0

    ok, metrics, logs = bench_tool.run_tier1_benchmark(
        REPO_ROOT, iterations=3, allow_retry=False, runner_func=mock_zero_runner
    )
    assert ok is False
    assert any("invalid non-positive duration detected" in log for log in logs)


def test_synthetic_nonzero_exit_fails_closed():
    """对抗注入：子进程非零退出必须 fail-closed。"""
    def mock_fail_runner(cmd, env, timeout):
        return 1, "pytest internal error", 1.0

    ok, metrics, logs = bench_tool.run_tier1_benchmark(
        REPO_ROOT, iterations=3, allow_retry=False, runner_func=mock_fail_runner
    )
    assert ok is False
    assert any("failed with exit code 1" in log for log in logs)


def test_synthetic_tier2_runner():
    """B-3: 契约测试内禁止真跑 Tier-2；使用 mock 验证 argv 拼接与 WARN 行为。"""
    captured_cmd = []

    def mock_tier2_runner(cmd, env, timeout):
        captured_cmd.extend(cmd)
        return 0, "809 passed in 38.0s", 38.5

    ok, elapsed, logs = bench_tool.run_tier2_benchmark(REPO_ROOT, runner_func=mock_tier2_runner)
    assert ok is True
    assert elapsed == 38.5
    # 验证包含了 --deselect
    assert "--deselect" in captured_cmd
    harness_rel = Path("plugins") / "quench-dev-tasks" / "server" / "tests" / bench_tool.HARNESS_TEST_FILENAME
    expected_deselect = str(harness_rel).replace("\\", "/")
    assert expected_deselect in captured_cmd
    # 耗时 > 35.0s 产生警告但依然返回 ok=True
    assert any("Tier-2 baseline warning" in log for log in logs)
