# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Pure function contract tests for step adjudication invariants (A6 axiom protection).

Decoupled from specific roadmap version and markdown file bindings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

import pytest

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
        assert not adj.evidence_refs, f"COLLAPSED step {adj.step_id} must not cite evidence_refs"
        assert adj.justification, f"COLLAPSED step {adj.step_id} must provide justification"
        assert adj.collapsed_into, f"COLLAPSED step {adj.step_id} must point to host step"
    elif adj.disposition == "DEFERRED":
        assert adj.justification, f"DEFERRED step {adj.step_id} must provide justification"


@pytest.mark.tier1_fast
def test_adjudication_invariants_unit():
    """单元测试：验证 StepAdjudication 不变量断言函数正确分流 (A6 公理行为保护)。"""
    # 正常分流
    ok_conf = StepAdjudication("23.0", "CONFIRMED", ("ref#1",), None, None)
    assert_adjudication_invariants(ok_conf)

    ok_coll = StepAdjudication("23.1", "COLLAPSED", (), "Null input", "23.0")
    assert_adjudication_invariants(ok_coll)

    ok_def = StepAdjudication("23.2", "DEFERRED", (), "High risk", None)
    assert_adjudication_invariants(ok_def)

    ok_prov = StepAdjudication("23.5", "PROVISIONAL", (), None, None)
    assert_adjudication_invariants(ok_prov)

    # 异常拦截
    with pytest.raises(AssertionError, match="must cite evidence_refs"):
        assert_adjudication_invariants(StepAdjudication("23.0", "CONFIRMED", (), None, None))

    with pytest.raises(AssertionError, match="must have None justification"):
        assert_adjudication_invariants(StepAdjudication("23.0", "CONFIRMED", ("ref#1",), "redundant", None))

    with pytest.raises(AssertionError, match="must not cite evidence_refs"):
        assert_adjudication_invariants(StepAdjudication("23.1", "COLLAPSED", ("ref#1",), "Just", "23.0"))

    with pytest.raises(AssertionError, match="must provide justification"):
        assert_adjudication_invariants(StepAdjudication("23.1", "COLLAPSED", (), None, "23.0"))

    with pytest.raises(AssertionError, match="must point to host step"):
        assert_adjudication_invariants(StepAdjudication("23.1", "COLLAPSED", (), "Just", None))

    with pytest.raises(AssertionError, match="must provide justification"):
        assert_adjudication_invariants(StepAdjudication("23.2", "DEFERRED", (), None, None))
