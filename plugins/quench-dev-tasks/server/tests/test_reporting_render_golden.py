# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Golden sample byte-fidelity assertions for reporting.py rendering and changelog appending."""

from __future__ import annotations

import datetime
import hashlib
import os
import sys
import tempfile
from pathlib import Path

server_dir = str(Path(__file__).resolve().parent.parent)
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

import pytest
import reporting
from state_machine import TaskItem

# Frozen golden SHA-256 hashes pre-computed from original handoff_card.py and changelog_writer.py
GOLDEN_BASIC_CARD_SHA256 = "fcaf1e0611e85b15a3041ac9d4c74a26c30a497e817392bb389c8d809ce36ea8"
GOLDEN_CONTEXT_CARD_SHA256 = "76419f2994449328b164be544b5024c652ea5c78f56dda5a8a2586434732d2f2"
GOLDEN_CHANGELOG_NEW_SHA256 = "40ac922d577d1063baafd7e8403178ffa2648ccbc8a90127f0f8ce02ec18e197"
GOLDEN_CHANGELOG_EXISTING_SHA256 = "98a4fe122dceb37db2dce546b11301f6d7ccfdfd159388cb40b71b1a6fba5591"


def test_reporting_module_preserves_mpl2_license_header() -> None:
    """[R4] 验证 reporting.py 源码头部忠实保留 MPL-2.0 开源许可证头。"""
    src_content = Path(reporting.__file__).read_text(encoding="utf-8")
    assert "Mozilla Public License, v. 2.0" in src_content
    assert "http://mozilla.org/MPL/2.0/" in src_content


def test_render_handoff_card_golden_byte_fidelity() -> None:
    """[G-3 断言①] 纯渲染字节金样本 SHA-256 比对，跨平台 \\r\\n 统一为 \\n 归一化。"""
    card_basic = reporting.render_handoff_card(
        task_id="1.1",
        task_file="docs/dev_tasks/demo.md",
        reason="rework_required",
        task_meta={"preferred": "subagent", "title": "解耦任务"},
        include_context=False,
    )
    norm_basic = card_basic.replace("\r\n", "\n")
    actual_basic_sha = hashlib.sha256(norm_basic.encode("utf-8")).hexdigest()
    assert actual_basic_sha == GOLDEN_BASIC_CARD_SHA256, (
        f"Basic card SHA mismatch: got {actual_basic_sha}, expected {GOLDEN_BASIC_CARD_SHA256}"
    )

    sample_spec = """
#### 【涉及文件】
```
[MODIFY] a.py
```

#### 【缺陷根因与修改目标】
根因说明

#### 【目标签名与类型契约】
契约说明

#### 【DoD 验证命令】
```bash
pytest
```
"""
    card_ctx = reporting.render_handoff_card(
        task_id="1.1",
        task_file="docs/dev_tasks/demo.md",
        reason="escalation",
        task_meta={"full_spec": sample_spec},
        include_context=True,
    )
    norm_ctx = card_ctx.replace("\r\n", "\n")
    actual_ctx_sha = hashlib.sha256(norm_ctx.encode("utf-8")).hexdigest()
    assert actual_ctx_sha == GOLDEN_CONTEXT_CARD_SHA256, (
        f"Context card SHA mismatch: got {actual_ctx_sha}, expected {GOLDEN_CONTEXT_CARD_SHA256}"
    )


def test_append_changelog_entry_golden_fidelity(monkeypatch: pytest.MonkeyPatch) -> None:
    """[G-3 断言②] 模块级 monkeypatch 冻结 reporting.datetime，验证幂等头追加金样本保真。"""
    class MockDate:
        @classmethod
        def today(cls):
            return datetime.date(2026, 10, 4)

    class MockDatetime:
        date = MockDate

    # 在模块级对 reporting.datetime 注入假日期对象（规避 CPython built-in date 设属性 TypeError）[N1/A3]
    monkeypatch.setattr(reporting, "datetime", MockDatetime)

    tasks = [
        TaskItem(id="1", title="任务一", status="✔️ 已完成", line_number=10, raw_line="### 任务 1 ✔️ 已完成 — 任务一"),
        TaskItem(id="2", title="任务二", status="✔️ 已完成", line_number=20, raw_line="### 任务 2 ✔️ 已完成 — 任务二"),
    ]

    # 场景 1：新建 CHANGELOG 文件
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tf:
        new_cl_path = tf.name
    try:
        reporting.append_changelog_entry(new_cl_path, "2026-10-04_demo.md", tasks)
        with open(new_cl_path, "r", encoding="utf-8") as f:
            content_new = f.read().replace("\r\n", "\n")
        sha_new = hashlib.sha256(content_new.encode("utf-8")).hexdigest()
        assert sha_new == GOLDEN_CHANGELOG_NEW_SHA256, (
            f"New changelog SHA mismatch: got {sha_new}, expected {GOLDEN_CHANGELOG_NEW_SHA256}"
        )
    finally:
        if os.path.exists(new_cl_path):
            os.remove(new_cl_path)

    # 场景 2：已有二级标题的 CHANGELOG 文件增量插入
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tf:
        exist_cl_path = tf.name
        tf.write("# Header\n\n## [2026-10-03] old.md\n\n- **Task 0**: old\n")
    try:
        reporting.append_changelog_entry(exist_cl_path, "2026-10-04_demo.md", tasks)
        with open(exist_cl_path, "r", encoding="utf-8") as f:
            content_exist = f.read().replace("\r\n", "\n")
        sha_exist = hashlib.sha256(content_exist.encode("utf-8")).hexdigest()
        assert sha_exist == GOLDEN_CHANGELOG_EXISTING_SHA256, (
            f"Existing changelog SHA mismatch: got {sha_exist}, expected {GOLDEN_CHANGELOG_EXISTING_SHA256}"
        )
    finally:
        if os.path.exists(exist_cl_path):
            os.remove(exist_cl_path)
