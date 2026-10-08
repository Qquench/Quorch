#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quench DevTasks - 测试套件耗时基线冻结与守卫工具 (TR-3).

退出码矩阵 (Exit Code Matrix):
  --check : 硬失败族 -> 1 (budget > HARD_FAIL / 两轮 CV > MAX_CV / 非零退出 / 超时 / 解析失败 /
            样本不足(iterations < MEASURED_ITERATIONS) / min_duration<=0 或 mean<=0);
            WARN (mean > 5.0 且 <= 8.0) / INFO (mean <= 3.0) -> 0;
  --tier2 : 除子进程异常外 -> 0 (> TIER2_TARGET_S 仅 WARN);
  无参数  : 等价于 --check.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Final, Mapping, NamedTuple, Sequence

# 确保可复用 scripts/check_test_tiering_invariants.py
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from check_test_tiering_invariants import sanitized_env  # noqa: E402

# --- Tier-1 阈值（三级语义显式化）---
TIER1_HARD_FAIL_S: Final[float] = 8.0   # 超此值 fail-closed（CI 阻断；与 test_tier1_fast_budget_execution 同源）
TIER1_TARGET_S: Final[float] = 5.0      # 超此值 WARN（放行，exit 0）
TIER1_FAST_GOAL_S: Final[float] = 3.0   # 报告项（info，对应路线图 §4.3 观测口径，不作门禁）

# --- Tier-2 阈值 ---
TIER2_TARGET_S: Final[float] = 35.0     # 软目标（WARN，exit 0；40s 为里程碑 DoD 另行核验）

# --- 方差门禁 ---
TIER1_MAX_CV: Final[float] = 0.15       # std_dev(ddof=1) / mean
MAX_CV_RETRY_ROUNDS: Final[int] = 1     # 有界重测：两轮皆越界才 fail-closed
WARMUP_ITERATIONS: Final[int] = 1       # 预热次数（不计入方差采样）
MEASURED_ITERATIONS: Final[int] = 3     # 正式采样次数（iterations 语义 = 仅正式采样数）

# --- 物理隔离与超时 ---
REENTRY_GUARD_ENV: Final[str] = "QUENCH_TEST_DURATION_BENCH_ACTIVE"
HARNESS_TEST_FILENAME: Final[str] = "test_duration_baselines_contract.py"
TIER1_ITERATION_TIMEOUT_S: Final[float] = 15.0   # 与既有 budget 测试对齐
TIER2_TOTAL_TIMEOUT_S: Final[float] = 300.0

# --- 计时 argv（必须与 test_tier1_fast_budget_execution 逐元素一致；严禁 NEUTRALIZE_ARGS）---
TIER1_ARGV: Final[tuple[str, ...]] = ("-m", "tier1_fast", "-q")


class BaselineMetrics(NamedTuple):
    iterations: int          # == len(durations)
    durations: tuple[float, ...]
    mean: float
    min_duration: float
    max_duration: float
    std_dev: float           # statistics.stdev(durations)（ddof=1）；len<2 时未定义，由调用侧 fail-closed
    cv: float                # std_dev / mean；mean == 0.0 时定义为 0.0


def calculate_metrics(durations: Sequence[float]) -> BaselineMetrics:
    """纯函数（零副作用、零 I/O）。

    空样本抛 ValueError；len==1 时 std_dev=0.0, cv=0.0。
    """
    if not durations:
        raise ValueError("durations sequence cannot be empty / 耗时序列不能为空")

    d_tuple = tuple(float(x) for x in durations)
    count = len(d_tuple)
    mean_val = sum(d_tuple) / count
    min_val = min(d_tuple)
    max_val = max(d_tuple)

    if count == 1:
        return BaselineMetrics(
            iterations=1,
            durations=d_tuple,
            mean=mean_val,
            min_duration=min_val,
            max_duration=max_val,
            std_dev=0.0,
            cv=0.0,
        )

    std_dev_val = statistics.stdev(d_tuple)  # ddof=1
    cv_val = (std_dev_val / mean_val) if mean_val != 0.0 else 0.0

    return BaselineMetrics(
        iterations=count,
        durations=d_tuple,
        mean=mean_val,
        min_duration=min_val,
        max_duration=max_val,
        std_dev=std_dev_val,
        cv=cv_val,
    )


def should_skip_benchmark_harness(env: Mapping[str, str]) -> bool:
    """纯函数：env 含 REENTRY_GUARD_ENV 即 True（契约测试模块导入期据此 pytest.skip）。"""
    return bool(env.get(REENTRY_GUARD_ENV))


def _has_executed_tests(output: str) -> bool:
    """解析子进程输出，确认 executed/collected 用例数 > 0。"""
    # 匹配诸如 "25 passed", "1 failed", "collected 25 items" 等模式
    if re.search(r"\b(\d+)\s+passed\b", output):
        m = re.search(r"\b(\d+)\s+passed\b", output)
        if m and int(m.group(1)) > 0:
            return True
    if re.search(r"\b(\d+)\s+failed\b", output):
        return True
    if re.search(r"collected\s+(\d+)\s+items", output):
        m = re.search(r"collected\s+(\d+)\s+items", output)
        if m and int(m.group(1)) > 0:
            return True
    # 摘要行诸如 "=== 25 passed in 1.50s ==="
    if "passed" in output and re.search(r"\d+\.?\d*s", output):
        return True
    return False


def run_tier1_benchmark(
    repo_root: Path,
    iterations: int = MEASURED_ITERATIONS,
    *,
    allow_retry: bool = True,
    runner_func=None,
) -> tuple[bool, BaselineMetrics, list[str]]:
    """运行 Tier-1 基线测试与方差判定。

    bool == 「未触发硬失败族」(ok)；WARN/INFO 由 main() 依据 metrics.mean 派生。
    iterations 仅计正式采样；实际子进程数 = WARMUP_ITERATIONS + iterations（首轮）。
    若首轮 CV 超标且 allow_retry=True，触发至多 1 轮有界重测。返回最后一次实际执行轮的 metrics；
    ok=False 当且仅当重测耗尽后仍越界。
    权威计时 = time.monotonic() 差分（与 budget 测试同源）；
    解析失败定义为：子进程输出中无法确认 collected/executed 用例数 > 0（用例数=0 或摘要行完全缺失报红）。
    """
    logs: list[str] = []

    # 库层假绿封堵 (R-A): iterations 必须 >= 2
    if iterations < 2:
        logs.append(
            f"Fail-closed: iterations={iterations} < 2 (library-level false-green guard R-A)"
        )
        dummy_metrics = BaselineMetrics(
            iterations=iterations,
            durations=tuple([0.0] * iterations),
            mean=0.0,
            min_duration=0.0,
            max_duration=0.0,
            std_dev=0.0,
            cv=0.0,
        )
        return False, dummy_metrics, logs

    def default_runner(cmd: list[str], env: dict[str, str], timeout: float) -> tuple[int, str, float]:
        t0 = time.monotonic()
        res = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        elapsed = time.monotonic() - t0
        output = (res.stdout or "") + "\n" + (res.stderr or "")
        return res.returncode, output, elapsed

    runner = runner_func or default_runner

    child_env = sanitized_env()
    child_env[REENTRY_GUARD_ENV] = "1"
    tier1_cmd = [sys.executable, "-m", "pytest", *TIER1_ARGV]

    max_rounds = 1 + (MAX_CV_RETRY_ROUNDS if allow_retry else 0)
    current_round = 0
    final_metrics: BaselineMetrics | None = None

    while current_round < max_rounds:
        current_round += 1
        round_tag = f"[Round {current_round}/{max_rounds}]"

        # 1. 预热运行 (WARMUP_ITERATIONS = 1)
        try:
            w_code, w_out, _ = runner(tier1_cmd, child_env, TIER1_ITERATION_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            logs.append(f"{round_tag} Warmup run timed out (> {TIER1_ITERATION_TIMEOUT_S}s)")
            dummy = BaselineMetrics(0, (), 0.0, 0.0, 0.0, 0.0, 0.0)
            return False, dummy, logs
        except Exception as exc:
            logs.append(f"{round_tag} Warmup run failed with exception: {exc}")
            dummy = BaselineMetrics(0, (), 0.0, 0.0, 0.0, 0.0, 0.0)
            return False, dummy, logs

        if w_code != 0:
            logs.append(f"{round_tag} Warmup run failed with exit code {w_code}:\n{w_out.strip()}")
            dummy = BaselineMetrics(0, (), 0.0, 0.0, 0.0, 0.0, 0.0)
            return False, dummy, logs

        if not _has_executed_tests(w_out):
            logs.append(f"{round_tag} Warmup run parse failure: no executed tests found in output")
            dummy = BaselineMetrics(0, (), 0.0, 0.0, 0.0, 0.0, 0.0)
            return False, dummy, logs

        # 2. 正式采样运行 (iterations 次)
        durations: list[float] = []
        for i in range(iterations):
            try:
                code, out, elapsed = runner(tier1_cmd, child_env, TIER1_ITERATION_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                logs.append(
                    f"{round_tag} Iteration {i+1} timed out (> {TIER1_ITERATION_TIMEOUT_S}s)"
                )
                dummy = BaselineMetrics(len(durations), tuple(durations), 0.0, 0.0, 0.0, 0.0, 0.0)
                return False, dummy, logs
            except Exception as exc:
                logs.append(f"{round_tag} Iteration {i+1} failed with exception: {exc}")
                dummy = BaselineMetrics(len(durations), tuple(durations), 0.0, 0.0, 0.0, 0.0, 0.0)
                return False, dummy, logs

            if code != 0:
                logs.append(
                    f"{round_tag} Iteration {i+1} failed with exit code {code}:\n{out.strip()}"
                )
                dummy = BaselineMetrics(len(durations), tuple(durations), 0.0, 0.0, 0.0, 0.0, 0.0)
                return False, dummy, logs

            if not _has_executed_tests(out):
                logs.append(
                    f"{round_tag} Iteration {i+1} parse failure: no executed tests found in output"
                )
                dummy = BaselineMetrics(len(durations), tuple(durations), 0.0, 0.0, 0.0, 0.0, 0.0)
                return False, dummy, logs

            durations.append(elapsed)

        metrics = calculate_metrics(durations)
        final_metrics = metrics

        # 校验 min_duration <= 0.0 或 mean <= 0.0
        if metrics.min_duration <= 0.0 or metrics.mean <= 0.0:
            logs.append(
                f"{round_tag} Fail-closed: invalid non-positive duration detected (min={metrics.min_duration:.4f}s, mean={metrics.mean:.4f}s)"
            )
            return False, metrics, logs

        # 校验 budget 硬失败 (mean > TIER1_HARD_FAIL_S 或 max > TIER1_HARD_FAIL_S)
        if metrics.mean > TIER1_HARD_FAIL_S or metrics.max_duration > TIER1_HARD_FAIL_S:
            logs.append(
                f"{round_tag} Budget hard-fail: Tier-1 mean={metrics.mean:.2f}s (max={metrics.max_duration:.2f}s) exceeded hard threshold ({TIER1_HARD_FAIL_S:.1f}s)"
            )
            return False, metrics, logs

        # 校验方差门禁 (CV <= TIER1_MAX_CV)
        if metrics.cv <= TIER1_MAX_CV:
            logs.append(
                f"{round_tag} Tier-1 passed: mean={metrics.mean:.3f}s (target<={TIER1_TARGET_S}s), CV={metrics.cv*100:.2f}% (max<={TIER1_MAX_CV*100:.0f}%)"
            )
            return True, metrics, logs
        else:
            logs.append(
                f"{round_tag} Variance gate exceeded: CV={metrics.cv*100:.2f}% > {TIER1_MAX_CV*100:.0f}%"
            )
            if current_round < max_rounds:
                logs.append(f"Triggering bounded retry round ({current_round}/{MAX_CV_RETRY_ROUNDS})...")
                continue
            else:
                logs.append(
                    f"Fail-closed: CV={metrics.cv*100:.2f}% exceeded {TIER1_MAX_CV*100:.0f}% after retries"
                )
                return False, metrics, logs

    assert final_metrics is not None
    return False, final_metrics, logs


def run_tier2_benchmark(
    repo_root: Path,
    runner_func=None,
) -> tuple[bool, float, list[str]]:
    """全量回归计时报告；强制 --deselect <HARNESS_TEST_FILENAME>（由模块路径派生）；不参与 --check 硬判定。"""
    logs: list[str] = []

    def default_runner(cmd: list[str], env: dict[str, str], timeout: float) -> tuple[int, str, float]:
        t0 = time.monotonic()
        res = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        elapsed = time.monotonic() - t0
        output = (res.stdout or "") + "\n" + (res.stderr or "")
        return res.returncode, output, elapsed

    runner = runner_func or default_runner

    child_env = sanitized_env()
    child_env[REENTRY_GUARD_ENV] = "1"

    # --deselect 路径由相对模块路径派生
    harness_rel = Path("plugins") / "quench-dev-tasks" / "server" / "tests" / HARNESS_TEST_FILENAME
    deselect_arg = str(harness_rel).replace("\\", "/")

    tier2_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--deselect",
        deselect_arg,
    ]

    try:
        code, out, elapsed = runner(tier2_cmd, child_env, TIER2_TOTAL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        logs.append(f"Tier-2 run timed out (> {TIER2_TOTAL_TIMEOUT_S}s)")
        return False, 0.0, logs
    except Exception as exc:
        logs.append(f"Tier-2 run failed with exception: {exc}")
        return False, 0.0, logs

    if code != 0:
        logs.append(f"Tier-2 run failed with exit code {code}:\n{out.strip()}")
        return False, elapsed, logs

    if elapsed > TIER2_TARGET_S:
        logs.append(
            f"Tier-2 baseline warning: took {elapsed:.2f}s > target {TIER2_TARGET_S:.1f}s (WARN, exit 0)"
        )
    else:
        logs.append(
            f"Tier-2 baseline OK: took {elapsed:.2f}s <= target {TIER2_TARGET_S:.1f}s"
        )

    return True, elapsed, logs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check test duration baselines and variance (TR-3)")
    parser.add_argument("--repo-root", default=None, help="Explicit repository root")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Perform Tier-1 baseline checks with variance guard (default if no mode specified)",
    )
    parser.add_argument(
        "--tier2",
        action="store_true",
        help="Run Tier-2 full regression timing benchmark (deselecting harness)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=MEASURED_ITERATIONS,
        help=f"Number of measured iterations (default: {MEASURED_ITERATIONS})",
    )

    args = parser.parse_args(argv)

    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = Path(__file__).resolve().parent.parent

    # 默认模式为 --check
    do_check = args.check or (not args.tier2)

    exit_code = 0

    if do_check:
        # 反绕过检查：--check 模式下 iterations < MEASURED_ITERATIONS 必须 fail-closed
        if args.iterations < MEASURED_ITERATIONS:
            err_msg = (
                f"[Baseline Gate] [FAIL] Sub-measured iterations bypass detected: "
                f"--iterations {args.iterations} < {MEASURED_ITERATIONS} (fail-closed).\n"
            )
            try:
                sys.stderr.write(err_msg)
            except UnicodeEncodeError:
                sys.stderr.write(err_msg.encode("ascii", "replace").decode("ascii"))
            sys.stderr.flush()
            return 1

        ok, metrics, logs = run_tier1_benchmark(repo_root, iterations=args.iterations)

        for line in logs:
            out_str = f"  * {line}\n"
            try:
                sys.stdout.write(out_str)
            except UnicodeEncodeError:
                sys.stdout.write(out_str.encode("ascii", "replace").decode("ascii"))
        sys.stdout.flush()

        if not ok:
            err_msg = "[Baseline Gate] [FAIL] Tier-1 baseline or variance check failed.\n"
            try:
                sys.stderr.write(err_msg)
            except UnicodeEncodeError:
                sys.stderr.write(err_msg.encode("ascii", "replace").decode("ascii"))
            sys.stderr.flush()
            return 1

        # 检查 WARN 或 INFO 提示
        if metrics.mean > TIER1_TARGET_S:
            warn_msg = (
                f"[Baseline Gate] [WARN] Tier-1 mean duration {metrics.mean:.2f}s > "
                f"target {TIER1_TARGET_S:.1f}s (tolerance <= {TIER1_HARD_FAIL_S:.1f}s, exit 0).\n"
            )
            try:
                sys.stdout.write(warn_msg)
            except UnicodeEncodeError:
                sys.stdout.write(warn_msg.encode("ascii", "replace").decode("ascii"))
        elif metrics.mean <= TIER1_FAST_GOAL_S:
            info_msg = (
                f"[Baseline Gate] [INFO] Tier-1 ultra-fast goal achieved: "
                f"{metrics.mean:.2f}s <= {TIER1_FAST_GOAL_S:.1f}s.\n"
            )
            try:
                sys.stdout.write(info_msg)
            except UnicodeEncodeError:
                sys.stdout.write(info_msg.encode("ascii", "replace").decode("ascii"))

        success_msg = (
            f"[Baseline Gate] [OK] Tier-1 benchmarks passed: mean={metrics.mean:.3f}s, "
            f"min={metrics.min_duration:.3f}s, max={metrics.max_duration:.3f}s, "
            f"CV={metrics.cv*100:.2f}% (samples={metrics.iterations}).\n"
        )
        try:
            sys.stdout.write(success_msg)
        except UnicodeEncodeError:
            sys.stdout.write(success_msg.encode("ascii", "replace").decode("ascii"))
        sys.stdout.flush()

    if args.tier2:
        ok_t2, elapsed_t2, logs_t2 = run_tier2_benchmark(repo_root)
        for line in logs_t2:
            out_str = f"  * [Tier-2] {line}\n"
            try:
                sys.stdout.write(out_str)
            except UnicodeEncodeError:
                sys.stdout.write(out_str.encode("ascii", "replace").decode("ascii"))
        sys.stdout.flush()

        if not ok_t2:
            err_msg = "[Baseline Gate] [FAIL] Tier-2 regression failed or timed out.\n"
            try:
                sys.stderr.write(err_msg)
            except UnicodeEncodeError:
                sys.stderr.write(err_msg.encode("ascii", "replace").decode("ascii"))
            sys.stderr.flush()
            return 1

        t2_msg = f"[Baseline Gate] [OK] Tier-2 benchmark completed: took {elapsed_t2:.2f}s.\n"
        try:
            sys.stdout.write(t2_msg)
        except UnicodeEncodeError:
            sys.stdout.write(t2_msg.encode("ascii", "replace").decode("ascii"))
        sys.stdout.flush()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
