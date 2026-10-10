# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Unit tests for Tier-2 dynamic duration envelope ratcheting, false-red guards, and SSOT alignment."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_test_duration_baselines as gate
from check_test_duration_baselines import (
    TIER2_ABSOLUTE_FLOOR_S,
    TIER2_WARN_MULTIPLIER,
    TIER2_PANIC_MULTIPLIER,
    RATCHET_CONFIRM_ROUNDS,
    PANIC_DOWNGRADE_STREAK,
    TIER2_DEFAULT_BASELINE_S,
    robust_baseline,
    next_baseline,
    load_tier2_baseline,
    save_tier2_baseline,
    classify_tier2,
    classify_tier2_samples,
    Tier2Verdict,
)


@pytest.mark.tier1_fast
def test_envelope_respects_absolute_floor():
    """断言基线单向下移时严格受控于 30s 安全地板，严禁突破地板。"""
    assert TIER2_ABSOLUTE_FLOOR_S == 30.0
    # 正常下移但低于地板 -> 截断至地板 30.0
    assert next_baseline(50.0, 20.0) == 30.0
    assert next_baseline(30.0, 15.0) == 30.0
    # 当前已在地板 -> 保持地板
    assert next_baseline(30.0, 30.0) == 30.0
    # 异常快速瞬态估计量 -> 截断至地板 30.0
    assert next_baseline(40.0, 0.001) == 30.0
    # 正常下移在地板之上 -> 成功下移
    assert next_baseline(50.0, 42.0) == 42.0


@pytest.mark.tier1_fast
def test_envelope_ratchets_down_only_after_confirmation():
    """断言单向下移收敛性：仅向下收紧，向上不漂移，需经确认轮次。"""
    prev = 60.0
    # 向上恶化样本 (70.0s) -> 坚决不下移亦不上浮，基线锁定在 prev
    assert next_baseline(prev, 70.0) == 60.0

    # 3 轮有效样本确认后下移
    samples = [45.0, 44.0, 46.0]
    assert len(samples) >= RATCHET_CONFIRM_ROUNDS
    rob_est = robust_baseline(samples)
    assert rob_est == 45.0
    nb = next_baseline(prev, rob_est)
    assert nb == 45.0


@pytest.mark.tier1_fast
def test_panic_requires_consecutive_streak():
    """双向假红防护：单次瞬态毛刺降级为 panic_pending / warn，连续 K 次超限才硬阻断。"""
    baseline = 40.0
    # warn = 40 * 1.15 = 46.0s, panic = 40 * 1.30 = 52.0s
    assert PANIC_DOWNGRADE_STREAK == 2

    # 单次毛刺 (streak=1 < 2) -> panic_pending (不硬红)
    v1 = classify_tier2(55.0, baseline=baseline, panic_streak=1)
    assert v1 == "panic_pending"
    assert v1 != "panic"

    # 连续超限 (streak=2 >= 2) -> panic (硬阻断)
    v2 = classify_tier2(55.0, baseline=baseline, panic_streak=2)
    assert v2 == "panic"

    # 多样本测试：3 样本仅 1 个超限 -> 鲁棒中位数保护，不硬阻断
    v_samples_single = classify_tier2_samples([38.0, 39.0, 60.0], baseline=baseline)
    assert v_samples_single != "panic"

    # 多样本测试：连续 2 个超限 -> 硬阻断
    v_samples_multi = classify_tier2_samples([38.0, 55.0, 60.0], baseline=baseline)
    assert v_samples_multi == "panic"


@pytest.mark.tier1_fast
def test_retry_samples_do_not_pollute_baseline():
    """异常快或异常慢的单点毛刺被鲁棒中位数估计量剔除，不污染基线。"""
    # 异常快速采样毛刺（如 CI 缓存空转 5.0s）
    glitch_fast = [40.0, 41.0, 5.0]
    assert robust_baseline(glitch_fast) == 40.0

    # 异常慢毛刺（如宿主 GC 停顿 100.0s）
    glitch_slow = [40.0, 41.0, 100.0]
    assert robust_baseline(glitch_slow) == 41.0


@pytest.mark.tier1_fast
def test_sidecar_persistence_atomic_and_fallback(tmp_path: Path):
    """侧车基线持久化测试：原子写入、缺失 fail-safe 与损坏回退。"""
    sidecar = tmp_path / "test_baseline.json"

    # 1. 文件缺失 -> fail-safe 保守默认
    assert load_tier2_baseline(sidecar) == TIER2_DEFAULT_BASELINE_S

    # 2. 损坏文件 -> fail-safe 保守默认
    sidecar.write_text("{invalid json", encoding="utf-8")
    assert load_tier2_baseline(sidecar) == TIER2_DEFAULT_BASELINE_S

    # 3. 写入非法低于地板的数值 -> fail-safe 忽略
    sidecar.write_text(json.dumps({"baseline_s": 10.0}), encoding="utf-8")
    assert load_tier2_baseline(sidecar) == TIER2_DEFAULT_BASELINE_S

    # 4. 正常原子写入
    ok = save_tier2_baseline(38.5, sidecar)
    assert ok is True
    assert load_tier2_baseline(sidecar) == 38.5


@pytest.mark.tier1_fast
def test_ssot_constants_aligned_across_readme_roadmap_code():
    """SSOT 三向一致物理门：README §3.5 = 路线图 §3.5 = 代码常数严格一致。"""
    code_text = (REPO_ROOT / "scripts/check_test_duration_baselines.py").read_text(encoding="utf-8")
    readme_text = (REPO_ROOT / "docs/architecture/README.md").read_text(encoding="utf-8")
    roadmap_path = REPO_ROOT / "docs/roadmap/v1.23_resource_efficiency_and_doc_compaction_roadmap.md"
    if not roadmap_path.is_file():
        roadmap_path = REPO_ROOT / "docs/roadmap/archive/v1.23_resource_efficiency_and_doc_compaction_roadmap.md"
    roadmap_text = roadmap_path.read_text(encoding="utf-8")

    # 1. 安全地板常数 == 30.0
    m = re.search(r"TIER2_ABSOLUTE_FLOOR_S\s*:\s*Final\[float\]\s*=\s*([0-9.]+)", code_text)
    assert m and float(m.group(1)) == 30.0

    # 2. 三处均包含 30、1.15、1.30
    for doc in (code_text, readme_text, roadmap_text):
        assert "30" in doc
        assert "1.15" in doc
        assert "1.30" in doc

    # 3. 文档均包含 min 与 max 运算
    assert "min" in readme_text and "max" in readme_text
    assert "min" in roadmap_text and "max" in roadmap_text

    # 4. 文档均显式声明单向下移与假红防护
    assert "单向下移 + 双向假红防护" in readme_text
    assert "单向下移 + 双向假红防护" in roadmap_text
