# -*- coding: utf-8 -*-
"""test_doc_invariants_case12.py - Documentation invariants gate for Case 12 and W10 Exclusion Domain.

Verifies:
1. README.md contains exactly one `### 3.3.1 W10 Exclusion Domain (锁原语豁免域)` heading.
2. Section 3.3.1 is located after Section 3.3, and the next H3 heading immediately following it is `### 3.4`.
3. CI incident tracker covers cases 1 through 12 densely.
4. CI incident tracker contains regex match for `INC-\\d{8}-\\d{2}` including `INC-20261022-01`.
"""

from __future__ import annotations

import re
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
README_PATH = REPO_ROOT / "docs" / "architecture" / "README.md"
CI_GUIDE_PATH = REPO_ROOT / "docs" / "ci_incident_tracker_and_compatibility_guide.md"


def test_readme_w10_exclusion_domain_heading_invariants():
    """Assert README contains exactly one ### 3.3.1 W10 Exclusion Domain immediately before ### 3.4."""
    assert README_PATH.is_file(), f"README not found at {README_PATH}"
    content = README_PATH.read_text(encoding="utf-8")

    target_heading = "### 3.3.1 W10 Exclusion Domain (锁原语豁免域)"
    occurrences = content.count(target_heading)
    assert occurrences == 1, f"Expected exactly 1 occurrence of '{target_heading}', found {occurrences}"

    # Extract all H3 headings in order
    h3_headings = [
        line.strip()
        for line in content.splitlines()
        if line.startswith("### ")
    ]

    assert target_heading in h3_headings, f"'{target_heading}' not in extracted H3 headings"
    idx = h3_headings.index(target_heading)

    # Must be after at least one previous H3 (e.g. 3.3 / 3.1)
    assert idx > 0, f"'{target_heading}' cannot be the first H3 heading"

    # Immediately following H3 must be ### 3.4 ...
    assert idx + 1 < len(h3_headings), f"'{target_heading}' has no subsequent H3 heading"
    next_heading = h3_headings[idx + 1]
    assert next_heading.startswith("### 3.4"), (
        f"Expected immediately following heading to start with '### 3.4', got '{next_heading}'"
    )


def test_ci_guide_dense_case_coverage_and_incident_ids():
    """Assert CI incident guide covers Cases 1..12 densely and contains INC-\\d{8}-\\d{2}."""
    assert CI_GUIDE_PATH.is_file(), f"CI guide not found at {CI_GUIDE_PATH}"
    content = CI_GUIDE_PATH.read_text(encoding="utf-8")

    # Dense case coverage 1..12
    for case_num in range(1, 13):
        pattern = rf"案例 {case_num}[:\s]"
        assert re.search(pattern, content), f"Missing dense case coverage for Case {case_num} ('{pattern}')"

    # Incident ID regex check
    matches = re.findall(r"INC-\d{8}-\d{2}", content)
    assert len(matches) >= 8, f"Expected at least 8 INC incident IDs, found {len(matches)}: {matches}"
    assert "INC-20261022-01" in matches, "Expected 'INC-20261022-01' in CI incident guide matches"
