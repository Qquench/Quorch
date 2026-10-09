"""Unit tests for test suite duration baselines, variance guards, and anti-reentry contracts (TR-3)."""

from __future__ import annotations

import math
import os
import re
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


def test_reentry_guard_round_trip():
    """C1 / B1: 验证重入哨兵魔术值匹配与读写往返。"""
    assert bench_tool.should_skip_benchmark_harness({bench_tool.REENTRY_GUARD_ENV: bench_tool.REENTRY_GUARD_VALUE}) is True
    assert bench_tool.should_skip_benchmark_harness({bench_tool.REENTRY_GUARD_ENV: "1"}) is False
    assert bench_tool.should_skip_benchmark_harness({bench_tool.REENTRY_GUARD_ENV: "true"}) is False
    assert bench_tool.should_skip_benchmark_harness({bench_tool.REENTRY_GUARD_ENV: ""}) is False
    assert bench_tool.should_skip_benchmark_harness({}) is False
    assert bench_tool.should_skip_benchmark_harness({"OTHER_ENV": bench_tool.REENTRY_GUARD_VALUE}) is False


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
    """B-3 / R1: 契约测试内禁止真跑 Tier-2；使用 mock 验证 argv 拼接、assert_self_repo 开关与 WARN/PANIC 双闸分支。"""
    captured_cmd = []

    def mock_tier2_warn_runner(cmd, env, timeout):
        captured_cmd.extend(cmd)
        return 0, "809 passed in 70.0s", 70.5

    ok_warn, elapsed_warn, logs_warn = bench_tool.run_tier2_benchmark(
        REPO_ROOT, runner_func=mock_tier2_warn_runner, assert_self_repo=False
    )
    assert ok_warn is True
    assert elapsed_warn == 70.5
    # 验证包含了 --deselect
    assert "--deselect" in captured_cmd
    harness_rel = Path("plugins") / "quench-dev-tasks" / "server" / "tests" / bench_tool.HARNESS_TEST_FILENAME
    expected_deselect = str(harness_rel).replace("\\", "/")
    assert expected_deselect in captured_cmd
    # 耗时 > 65.0s 产生警告但依然返回 ok=True
    assert any("Tier-2 baseline warning" in log for log in logs_warn)

    # PANIC 分支验证
    def mock_tier2_panic_runner(cmd, env, timeout):
        return 0, "809 passed in 115.0s", 115.5

    ok_panic, elapsed_panic, logs_panic = bench_tool.run_tier2_benchmark(
        REPO_ROOT, runner_func=mock_tier2_panic_runner, assert_self_repo=False
    )
    assert ok_panic is False
    assert elapsed_panic == 115.5
    assert any("Tier-2 panic threshold exceeded" in log for log in logs_panic)


def test_classify_tier2_boundaries():
    """验证 classify_tier2 显式等号临界与异常值防御。"""
    # 异常与非正
    with pytest.raises(ValueError):
        bench_tool.classify_tier2(0.0)
    with pytest.raises(ValueError):
        bench_tool.classify_tier2(-5.0)
    with pytest.raises(ValueError):
        bench_tool.classify_tier2(float("nan"))
    with pytest.raises(ValueError):
        bench_tool.classify_tier2(float("-inf"))

    # OK 边界: <= 65.0
    assert bench_tool.classify_tier2(0.001) == "OK"
    assert bench_tool.classify_tier2(65.0) == "OK"

    # WARN 边界: > 65.0 and <= 110.0
    assert bench_tool.classify_tier2(65.001) == "WARN"
    assert bench_tool.classify_tier2(110.0) == "WARN"

    # PANIC 边界: > 110.0
    assert bench_tool.classify_tier2(110.001) == "PANIC"
    assert bench_tool.classify_tier2(float("inf")) == "PANIC"


def test_classify_tier2_samples_empty_and_nan():
    """V5: 验证 classify_tier2_samples 空序列与 NaN fail-closed 抛 ValueError。"""
    with pytest.raises(ValueError, match="samples sequence cannot be empty"):
        bench_tool.classify_tier2_samples([])

    with pytest.raises(ValueError, match="contains NaN"):
        bench_tool.classify_tier2_samples([60.0, float("nan")])


def test_classify_tier2_samples_outlier_panic():
    """R4: 验证单次灾难性 PANIC 级离群不被均值稀释，由 max(samples) 兜底判定为 PANIC。"""
    # mean = (61.0 + 61.0 + 120.0) / 3 = 80.67s (若仅按 mean 会被稀释为 WARN)，但 max 为 120.0 > 110.0 -> 必须判 PANIC
    assert bench_tool.classify_tier2_samples([61.0, 61.0, 120.0]) == "PANIC"
    assert bench_tool.classify_tier2_samples([60.0, 62.0]) == "OK"
    assert bench_tool.classify_tier2_samples([66.0, 68.0]) == "WARN"


def test_tier2_target_s_alias_removed():
    """断言废弃的 TIER2_TARGET_S 别名已彻底退役，模块不再暴露此符号。"""
    assert not hasattr(bench_tool, "TIER2_TARGET_S")
    assert hasattr(bench_tool, "TIER2_WARN_S")
    assert hasattr(bench_tool, "TIER2_PANIC_S")


def test_tier2_docstring_exit_matrix_sync():
    """R2 / B2: 验证模块 docstring 中退出码矩阵已同步，不含旧常量且含 PANIC。"""
    doc = bench_tool.__doc__ or ""
    assert "TIER2_TARGET_S" not in doc
    assert "PANIC" in doc


def test_assert_running_in_quench_self_repo(tmp_path: Path):
    """M3: 验证相对路径自锚定守卫：真仓正常通过，缺少标记文件的目录抛出 RuntimeError。"""
    bench_tool.assert_running_in_quench_self_repo(REPO_ROOT)

    # 虚拟空白目录测试
    with pytest.raises(RuntimeError, match="Repository self-anchor check failed"):
        bench_tool.assert_running_in_quench_self_repo(tmp_path)


def test_authoritative_regression_command_no_deselect():
    """M1: 双向断言：① 权威全量回归命令严禁包含 --deselect；② 唯一携带 --deselect 构造点绑定反自噬探针单例。"""
    # 权威回归标准命令 (TP-3 零净覆盖损失)
    authoritative_cmd = ["python", "-m", "pytest", "-q"]
    assert "--deselect" not in authoritative_cmd

    # 检查 check_test_duration_baselines.py 源码中 --deselect 仅在 run_tier2_benchmark 内部用于 HARNESS_TEST_FILENAME
    source_path = REPO_ROOT / "scripts" / "check_test_duration_baselines.py"
    source_text = source_path.read_text(encoding="utf-8")
    deselect_matches = re.findall(r'"--deselect"', source_text)
    assert len(deselect_matches) == 1, f"Expected exactly 1 '--deselect' in duration benchmark spawner, got {len(deselect_matches)}"
    assert "HARNESS_TEST_FILENAME" in source_text


def test_no_non_magic_guard_write():
    """R3: 源码静态扫描断言不存在对 REENTRY_GUARD_ENV 赋非魔术值字面量。"""
    source_path = REPO_ROOT / "scripts" / "check_test_duration_baselines.py"
    source_text = source_path.read_text(encoding="utf-8")
    # 匹配任何 child_env[REENTRY_GUARD_ENV] = ...
    writes = re.findall(r"\[REENTRY_GUARD_ENV\]\s*=\s*(.+)", source_text)
    assert len(writes) >= 2, f"Expected at least 2 writes to REENTRY_GUARD_ENV, found {len(writes)}"
    for w in writes:
        assert w.strip() == "REENTRY_GUARD_VALUE", f"Unexpected write value to REENTRY_GUARD_ENV: {w}"

