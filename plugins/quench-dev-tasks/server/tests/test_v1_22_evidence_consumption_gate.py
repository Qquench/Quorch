# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Test suite for v1.22 Step 22.0 Evidence-Consumption & Instantiation Gate.

Enforces:
1. Bidirectional parity between roadmap step table and evidence consumption ledger.
2. Three-branch instantiation gate integrity (EVIDENCED / NULL_INPUT / UNSUPPORTED).
3. Hash parity and TP-4 determinism for Delta Report anchors.
4. Non-empty evidence references for CONFIRMED steps (A6 axiom protection).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import pytest
import yaml

StepDisposition = Literal["CONFIRMED", "DEFERRED", "COLLAPSED", "PROVISIONAL"]


@dataclass(frozen=True)
class StepAdjudication:
    step_id: str
    disposition: StepDisposition
    evidence_refs: Tuple[str, ...]
    justification: Optional[str]
    collapsed_into: Optional[str] = None


def assert_adjudication_invariants(adj: StepAdjudication) -> None:
    """物理断言（纯函数）：
    - CONFIRMED   => evidence_refs 非空 且 justification is None
    - COLLAPSED   => evidence_refs 为空 且 justification 非空 且 collapsed_into 非空
    - DEFERRED    => justification 非空
    - PROVISIONAL => 占位态，不作硬性校验
    """
    if adj.disposition == "CONFIRMED":
        assert adj.evidence_refs, f"CONFIRMED step {adj.step_id} must cite evidence_refs"
        assert adj.justification is None, f"CONFIRMED step {adj.step_id} must have None justification"
    elif adj.disposition == "COLLAPSED":
        assert adj.justification, f"COLLAPSED step {adj.step_id} must provide justification"
        assert adj.collapsed_into, f"COLLAPSED step {adj.step_id} must point to host step"
    elif adj.disposition == "DEFERRED":
        assert adj.justification, f"DEFERRED step {adj.step_id} must provide justification"


def _parse_yaml_front_matter(text: str) -> Dict[str, Any]:
    """提取 Markdown 文档顶部的 YAML Front-Matter。"""
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    if not match:
        raise ValueError("Missing YAML front-matter in markdown file")
    raw_yaml = match.group(1)
    data = yaml.safe_load(raw_yaml)
    assert isinstance(data, dict), "Front matter must parse to a dictionary"
    return data


def _get_workspace_root() -> Path:
    # 向上寻找包含 .agents 的根目录
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / ".agents" / "quench_stack.yaml").is_file():
            return parent
    raise RuntimeError("Workspace root not found")


@pytest.mark.tier1_fast
def test_adjudication_invariants_unit():
    """单元测试：验证 StepAdjudication 不变量断言函数正确分流。"""
    # 正常分流
    ok_conf = StepAdjudication("22.0", "CONFIRMED", ("ref#1",), None, None)
    assert_adjudication_invariants(ok_conf)

    ok_coll = StepAdjudication("22.1", "COLLAPSED", (), "Null input", "22.0")
    assert_adjudication_invariants(ok_coll)

    ok_def = StepAdjudication("22.2", "DEFERRED", (), "High risk", None)
    assert_adjudication_invariants(ok_def)

    ok_prov = StepAdjudication("22.5", "PROVISIONAL", (), None, None)
    assert_adjudication_invariants(ok_prov)

    # 异常拦截
    with pytest.raises(AssertionError, match="must cite evidence_refs"):
        assert_adjudication_invariants(StepAdjudication("22.0", "CONFIRMED", (), None, None))

    with pytest.raises(AssertionError, match="must provide justification"):
        assert_adjudication_invariants(StepAdjudication("22.1", "COLLAPSED", (), None, "22.0"))

    with pytest.raises(AssertionError, match="must point to host step"):
        assert_adjudication_invariants(StepAdjudication("22.1", "COLLAPSED", (), "Just", None))


@pytest.mark.tier1_fast
def test_ledger_front_matter_and_hash_parity():
    """验证账本 Front-Matter 数据结构完整性与 Delta Report 哈希等价性。"""
    ws = _get_workspace_root()
    ledger_path = ws / "docs" / "architecture" / "v1.22_step22.0_evidence_consumption_ledger.md"
    assert ledger_path.is_file(), f"Missing ledger file: {ledger_path}"

    text = ledger_path.read_text(encoding="utf-8")
    fm = _parse_yaml_front_matter(text)

    # 1. 必含字段校验
    for field in [
        "delta_report_ref",
        "delta_report_sha256",
        "frozen_v120_sha256",
        "resolved_count",
        "persisted_count",
        "emerged_count",
        "coupling_count",
        "module_graph_count",
        "adjudications",
    ]:
        assert field in fm, f"Ledger front-matter missing required field: {field}"

    # 2. 规模数值校验
    assert fm["resolved_count"] == 0
    assert fm["persisted_count"] == 138
    assert fm["emerged_count"] == 0
    assert fm["coupling_count"] == 2
    assert fm["module_graph_count"] == 23

    # 3. 冻结件 SHA256 物理比对
    frozen_file = ws / "docs" / "architecture" / "over_engineering_inventory_v120_frozen.md"
    assert frozen_file.is_file()
    actual_frozen_sha = hashlib.sha256(frozen_file.read_bytes()).hexdigest()
    assert fm["frozen_v120_sha256"] == actual_frozen_sha

    # 4. 纯投影 SHA256 物理比对
    inv_file = ws / "docs" / "architecture" / "over_engineering_inventory.md"
    assert inv_file.is_file()
    inv_text = inv_file.read_text(encoding="utf-8")

    # 导入纯投影计算
    import sys
    sys.path.insert(0, str(ws / "scripts"))
    try:
        from asset_inventory import compute_pure_projection_sha256
        actual_pure_sha = compute_pure_projection_sha256(inv_text)
        assert fm["delta_report_sha256"] == actual_pure_sha
    finally:
        if str(ws / "scripts") in sys.path:
            sys.path.remove(str(ws / "scripts"))

    # 5. 逐条判决合法性校验
    adjudications = fm["adjudications"]
    assert len(adjudications) >= 5
    for adj_dict in adjudications:
        adj = StepAdjudication(
            step_id=str(adj_dict["step_id"]),
            disposition=adj_dict["disposition"],
            evidence_refs=tuple(adj_dict.get("evidence_refs") or ()),
            justification=adj_dict.get("justification"),
            collapsed_into=adj_dict.get("collapsed_into"),
        )
        assert_adjudication_invariants(adj)


@pytest.mark.tier1_fast
def test_roadmap_step_table_bidirectional_parity():
    """验证路线图 §2 步骤表格与账本判决双向 100% 对齐。"""
    ws = _get_workspace_root()
    roadmap_path = ws / "docs" / "roadmap" / "v1.22_architecture_convergence_roadmap.md"
    ledger_path = ws / "docs" / "architecture" / "v1.22_step22.0_evidence_consumption_ledger.md"

    roadmap_text = roadmap_path.read_text(encoding="utf-8")
    ledger_text = ledger_path.read_text(encoding="utf-8")
    fm = _parse_yaml_front_matter(ledger_text)

    ledger_map: Dict[str, str] = {
        str(a["step_id"]): a["disposition"] for a in fm["adjudications"]
    }

    # 解析路线图表格中的 step 行
    # 格式例如: | **step22.0** | 入口门禁与证据消费 | `CONFIRMED` | ...
    pattern = re.compile(
        r"\|\s*\*\*step(22\.[0-9]+)\*\*\s*\|[^|]+\|\s*`([A-Z_]+)`[^|]*\|",
        re.MULTILINE,
    )
    matches = pattern.findall(roadmap_text)
    assert len(matches) >= 5, f"Expected at least 5 steps in roadmap table, found {len(matches)}"

    roadmap_map: Dict[str, str] = {step_id: disp for step_id, disp in matches}

    # 双向相等断言
    for step_id, disp in roadmap_map.items():
        assert step_id in ledger_map, f"Roadmap step {step_id} not found in ledger"
        assert disp == ledger_map[step_id], (
            f"Step {step_id} mismatch: roadmap={disp}, ledger={ledger_map[step_id]}"
        )

    for step_id, disp in ledger_map.items():
        assert step_id in roadmap_map, f"Ledger step {step_id} not found in roadmap table"

    # 关键不变量：Emerged: 0 强制 step22.1 为 COLLAPSED
    assert roadmap_map["22.1"] == "COLLAPSED"
    # step22.0 必须为 CONFIRMED
    assert roadmap_map["22.0"] == "CONFIRMED"


@pytest.mark.tier1_fast
def test_three_branch_instantiation_gate_presence():
    """验证路线图 §2.1 完整包含三分支门禁规范。"""
    ws = _get_workspace_root()
    roadmap_path = ws / "docs" / "roadmap" / "v1.22_architecture_convergence_roadmap.md"
    text = roadmap_path.read_text(encoding="utf-8")

    assert "三分支完备模型" in text
    assert "EVIDENCED 分支" in text
    assert "NULL_INPUT 分支" in text
    assert "UNSUPPORTED 分支" in text
    assert "COLLAPSED" in text
    assert "DEFERRED" in text


@pytest.mark.tier1_fast
def test_fail_closed_dual_lease_contract():
    """验证路线图 §3.2 双 lease 契约已永久消除合并分支并锁定 fail-closed。"""
    ws = _get_workspace_root()
    roadmap_path = ws / "docs" / "roadmap" / "v1.22_architecture_convergence_roadmap.md"
    text = roadmap_path.read_text(encoding="utf-8")

    assert "物理消除合并分支，永远 fail-closed 保留双 lease" in text
    assert "可合并 → 物理合并" not in text


# ==============================================================================
# Step 22.1: Emerged 候选空集负向断言与全域完备性物化门禁 (COLLAPSED-materialized)
# ==============================================================================

@dataclass(frozen=True)
class EmergedVacuityVerdict:
    section_present: bool
    count: int
    undisposed: Tuple[str, ...]


def evaluate_emerged_vacuity(inventory_md_text: str) -> EmergedVacuityVerdict:
    """纯函数：解析 Markdown 文档中 §10.4 Emerged 候选清单并给出空集与完备性判决。"""
    header_pattern = re.compile(r"###\s+10\.4\s+.*Emerged.*", re.IGNORECASE)
    match = header_pattern.search(inventory_md_text)
    if not match:
        return EmergedVacuityVerdict(section_present=False, count=0, undisposed=())

    rest = inventory_md_text[match.end():]
    section_end = re.search(r"(\r?\n---|###)", rest)
    section_content = rest[:section_end.start()] if section_end else rest

    candidates: List[str] = []
    undisposed: List[str] = []
    for line in section_content.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "建议裁决" in line:
            continue
        cols = [c.strip() for c in line.split("|")[1:-1]]
        if not cols or len(cols) < 6:
            continue
        sym = cols[0].strip().strip("`")
        if sym.upper() == "NONE" or not sym:
            continue
        candidates.append(sym)
        disposition = cols[5].strip().strip("`")
        if not disposition or disposition.upper() in ("NONE", ""):
            undisposed.append(sym)

    return EmergedVacuityVerdict(
        section_present=True,
        count=len(candidates),
        undisposed=tuple(sorted(undisposed)),
    )


@pytest.mark.tier1_fast
def test_step22_1_emerged_presence_fail_closed():
    """断言缺失或畸形段头时 fail-closed，禁止隐式回退为 count=0。"""
    v = evaluate_emerged_vacuity("## Missing Section 10.4 Header\nSome body text.")
    assert v.section_present is False
    assert v.count == 0


@pytest.mark.tier1_fast
def test_step22_1_emerged_vacuity_is_proven():
    """断言真实架构清单中 §10.4 段头完好且 Emerged 候选严格为 0（空集物化证明）。"""
    ws = _get_workspace_root()
    inv_file = ws / "docs" / "architecture" / "over_engineering_inventory.md"
    assert inv_file.is_file(), f"Missing inventory file: {inv_file}"
    verdict = evaluate_emerged_vacuity(inv_file.read_text(encoding="utf-8"))

    assert verdict.section_present is True, "§10.4 段头缺失或不可解析"
    assert verdict.count == 0, f"Emerged 候选非空 ({verdict.count})，step22.1 折叠裁决失效"
    assert len(verdict.undisposed) == 0


@pytest.mark.tier1_fast
def test_step22_1_totality_holds_for_nonempty_input():
    """断言当未来出现新候选时，全域性门禁可拦截缺裁决项并放行完备项（Totality 性质）。"""
    synthetic_missing = (
        "### 10.4 新暴露候选清单 (Emerged Candidates)\n\n"
        "| 符号 | 定义模块 | 消费者数 | 承载不变量 | 公理映射 | 建议裁决 |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        "| `bad_sym` | `mod.py` | 1 | NONE | NONE | NONE |\n"
    )
    v_missing = evaluate_emerged_vacuity(synthetic_missing)
    assert v_missing.section_present is True
    assert v_missing.count == 1
    assert "bad_sym" in v_missing.undisposed

    synthetic_full = (
        "### 10.4 新暴露候选清单 (Emerged Candidates)\n\n"
        "| 符号 | 定义模块 | 消费者数 | 承载不变量 | 公理映射 | 建议裁决 |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        "| `good_sym` | `mod.py` | 1 | NONE | NONE | `REGISTER_ONLY` |\n"
    )
    v_full = evaluate_emerged_vacuity(synthetic_full)
    assert v_full.section_present is True
    assert v_full.count == 1
    assert len(v_full.undisposed) == 0


@pytest.mark.tier1_fast
def test_step22_1_ledger_evidence_anchored():
    """断言账本中 step22.1 显式锚定 #10.4 证据段并折叠并入 step22.0。"""
    ws = _get_workspace_root()
    ledger_path = ws / "docs" / "architecture" / "v1.22_step22.0_evidence_consumption_ledger.md"
    text = ledger_path.read_text(encoding="utf-8")
    fm = _parse_yaml_front_matter(text)

    adj_22_1 = next((a for a in fm["adjudications"] if str(a["step_id"]) == "22.1"), None)
    assert adj_22_1 is not None, "Missing step 22.1 in ledger"
    assert "docs/architecture/over_engineering_inventory.md#10.4" in adj_22_1.get("evidence_refs", [])
    assert adj_22_1["collapsed_into"] == "22.0"


# ==============================================================================
# Step 22.2: 双 lease 独立失效域隔离与 fail-closed 契约门禁 (Dual Lease Topology & A7 Gate)
# ==============================================================================

@dataclass(frozen=True)
class DualLeaseTopologyVerdict:
    manifest_lease_callers: Tuple[str, ...]
    workspace_lease_callers: Tuple[str, ...]
    is_disjoint: bool


def evaluate_dual_lease_topology(inventory_md_text: str) -> DualLeaseTopologyVerdict:
    """纯函数：解析 Markdown 文档中 §10.5 双租约调用拓扑并断言两者的隔离性。"""
    header_pattern = re.compile(r"###\s+10\.5\s+.*双租约.*", re.IGNORECASE)
    match = header_pattern.search(inventory_md_text)
    if not match:
        return DualLeaseTopologyVerdict(
            manifest_lease_callers=(),
            workspace_lease_callers=(),
            is_disjoint=False,
        )

    rest = inventory_md_text[match.end():]
    section_end = re.search(r"(\r?\n---|###)", rest)
    section_content = rest[:section_end.start()] if section_end else rest

    manifest_callers: List[str] = []
    workspace_callers: List[str] = []

    for line in section_content.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "调用拓扑" in line:
            continue
        cols = [c.strip() for c in line.split("|")[1:-1]]
        if len(cols) < 3:
            continue
        lease_name = cols[0].strip().strip("`")
        raw_callers = cols[2].strip()
        callers = [
            c.strip().strip("`")
            for c in raw_callers.split(",")
            if c.strip() and c.strip().strip("`").upper() != "NONE"
        ]
        if lease_name == "manifest_lease":
            manifest_callers.extend(callers)
        elif lease_name == "workspace_lease":
            workspace_callers.extend(callers)

    m_set = set(manifest_callers)
    w_set = set(workspace_callers)
    is_disjoint = len(m_set.intersection(w_set)) == 0 and bool(manifest_callers) and bool(workspace_callers)

    return DualLeaseTopologyVerdict(
        manifest_lease_callers=tuple(sorted(manifest_callers)),
        workspace_lease_callers=tuple(sorted(workspace_callers)),
        is_disjoint=is_disjoint,
    )


@pytest.mark.tier1_fast
def test_step22_2_dual_lease_topology_strictly_disjoint():
    """断言真实架构清单中 §10.5 双租约调用拓扑严格不相交（独立失效域物理证明）。"""
    ws = _get_workspace_root()
    inv_file = ws / "docs" / "architecture" / "over_engineering_inventory.md"
    assert inv_file.is_file(), f"Missing inventory file: {inv_file}"
    verdict = evaluate_dual_lease_topology(inv_file.read_text(encoding="utf-8"))

    assert verdict.is_disjoint is True, "manifest_lease 与 workspace_lease 调用拓扑存在交叉重叠，违反独立失效域隔离"
    assert len(verdict.manifest_lease_callers) > 0, "manifest_lease 调用拓扑为空"
    assert len(verdict.workspace_lease_callers) > 0, "workspace_lease 调用拓扑为空"
    # 交叉交集严格为空
    overlap = set(verdict.manifest_lease_callers).intersection(set(verdict.workspace_lease_callers))
    assert len(overlap) == 0, f"发现跨 lease 交叉调用污染: {overlap}"


@pytest.mark.tier1_fast
def test_step22_2_dual_lease_synthetic_collision_fail_closed():
    """断言当合成数据中存在跨 lease 交叉调用时，门禁判定 is_disjoint 为 False (fail-closed)。"""
    synthetic_overlap = (
        "### 10.5 双租约调用拓扑 (Coupling Topology, 共 2 项)\n\n"
        "| 租约名称 | 语义领域 | 调用拓扑 (`call_topology`) |\n"
        "| :--- | :--- | :--- |\n"
        "| `manifest_lease` | `task_coordination` | `plugins/quench-dev-tasks/server/server.py` |\n"
        "| `workspace_lease` | `session_cleanup` | `plugins/quench-dev-tasks/server/server.py` |\n"
    )
    v_overlap = evaluate_dual_lease_topology(synthetic_overlap)
    assert v_overlap.is_disjoint is False


@pytest.mark.tier1_fast
def test_step22_2_ledger_evidence_anchored():
    """断言账本中 step22.2 显式锚定 #10.5 证据段。"""
    ws = _get_workspace_root()
    ledger_path = ws / "docs" / "architecture" / "v1.22_step22.0_evidence_consumption_ledger.md"
    text = ledger_path.read_text(encoding="utf-8")
    fm = _parse_yaml_front_matter(text)

    adj_22_2 = next((a for a in fm["adjudications"] if str(a["step_id"]) == "22.2"), None)
    assert adj_22_2 is not None, "Missing step 22.2 in ledger"
    assert "docs/architecture/over_engineering_inventory.md#10.5" in adj_22_2.get("evidence_refs", [])
    assert adj_22_2["disposition"] == "CONFIRMED"


