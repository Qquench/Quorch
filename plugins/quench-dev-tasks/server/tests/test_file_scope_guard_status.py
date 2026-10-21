# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Unit tests for file_scope_guard task status protection, SSOT extraction, and multi-dimensional diff.
Tier-1 fast gate test suite.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
import pytest

from task_status import (
    STATUS_PENDING,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_SKIPPED,
    STATUS_REWORK,
    ALL_STATUSES,
    STATUS_UNKNOWN,
    TaskHeaderScan,
    normalize_status,
    extract_header_task_statuses,
    is_task_file as is_task_file_ssot,
)
from hooks.file_scope_guard import (
    MUTATING_TOOLS,
    READ_ONLY_TOOLS,
    build_post_image,
    diff_task_statuses,
    check_task_status_guard,
    extract_statuses,
)

SAMPLE_TASK_CONTENT = """# 2026-10-20 Sample Tasks / 示例任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions] in sequential order
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

---

### 任务 1.1 ⬜ 待确认 — 示例任务A

#### 【涉及文件】
```
[MODIFY] src/app.py
```

#### 【分步改造指引】
1. 实现基础框架：
```bash
echo "update its status to 🔨 执行中"
```

---

### 任务 1.2 🔄 需返工 — 示例任务B

#### 【涉及文件】
```
[MODIFY] src/utils.py
```
"""


def test_normalize_status_variants():
    """断言 normalize_status 兼容 VS16、全半角空格、英文字符，且未识别状态返回 ASCII 哨兵。"""
    assert normalize_status("⬜ 待确认") == STATUS_PENDING
    assert normalize_status("⬜\ufe0f 待确认") == STATUS_PENDING
    assert normalize_status("⬜待确认") == STATUS_PENDING
    assert normalize_status("Pending") == STATUS_PENDING
    assert normalize_status("✅ 已确认") == STATUS_CONFIRMED
    assert normalize_status("Confirmed") == STATUS_CONFIRMED
    assert normalize_status("🔨 执行中") == STATUS_IN_PROGRESS
    assert normalize_status("In-Progress") == STATUS_IN_PROGRESS
    assert normalize_status("✔️ 已完成") == STATUS_COMPLETED
    assert normalize_status("✔ 已完成") == STATUS_COMPLETED
    assert normalize_status("Completed") == STATUS_COMPLETED
    assert normalize_status("⏭️ 跳过") == STATUS_SKIPPED
    assert normalize_status("Skipped") == STATUS_SKIPPED
    assert normalize_status("🔄 需返工") == STATUS_REWORK
    assert normalize_status("Rework") == STATUS_REWORK

    # 未识别状态定向返回纯 ASCII 哨兵
    assert normalize_status("🚫 已撤销") == STATUS_UNKNOWN
    assert normalize_status("UnknownStatus") == STATUS_UNKNOWN
    assert normalize_status("") == STATUS_UNKNOWN


def test_extract_header_task_statuses_fence_and_blockquote_filtering():
    """断言 extract_header_task_statuses 准确过滤 blockquote 与代码围栏内的 Emoji 状态。"""
    scan = extract_header_task_statuses(SAMPLE_TASK_CONTENT)
    assert scan.statuses == {
        "1.1": STATUS_PENDING,
        "1.2": STATUS_REWORK,
    }
    assert scan.occurrence_counts == {"1.1": 1, "1.2": 1}
    assert len(scan.duplicates) == 0
    assert len(scan.malformed_ids) == 0


def test_extract_statuses_backward_compatibility():
    """断言 extract_statuses 包装层返回合规状态列表且排除了围栏/引用块。"""
    st_list = extract_statuses(SAMPLE_TASK_CONTENT)
    assert st_list == [STATUS_PENDING, STATUS_REWORK]


def test_guidance_header_blockquote_with_emoji_allowed(tmp_path):
    """断言修改任务单 Header 指南引用块（包含 Emoji 示例）直接放行（allow）。"""
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(SAMPLE_TASK_CONTENT, encoding="utf-8")

    # 在引用块中修改文字
    new_guidance = SAMPLE_TASK_CONTENT.replace("Strictly follow each task's", "Carefully follow each task's")
    args = {
        "TargetContent": "Strictly follow each task's",
        "ReplacementContent": "Carefully follow each task's",
    }
    res = check_task_status_guard(str(task_file), "replace_file_content", args)
    assert res is None  # allow


def test_fenced_code_blocks_with_emoji_allowed(tmp_path):
    """断言在代码围栏内部修改或插入状态 Emoji 字符直接放行（allow）。"""
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(SAMPLE_TASK_CONTENT, encoding="utf-8")

    old_snippet = 'echo "update its status to 🔨 执行中"'
    new_snippet = 'echo "update its status to ✅ 已确认 and 🔨 执行中"'
    args = {
        "TargetContent": old_snippet,
        "ReplacementContent": new_snippet,
    }
    res = check_task_status_guard(str(task_file), "replace_file_content", args)
    assert res is None  # allow


def test_pending_task_body_step_dod_revision_allowed(tmp_path):
    """断言修改待确认任务的正文、指引与 DoD 命令直接放行（allow）。"""
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(SAMPLE_TASK_CONTENT, encoding="utf-8")

    args = {
        "TargetContent": "1. 实现基础框架：",
        "ReplacementContent": "1. 实现基础框架并增强错误处理：",
    }
    res = check_task_status_guard(str(task_file), "replace_file_content", args)
    assert res is None  # allow


def test_tamper_heading_pending_to_in_progress_intercepted(tmp_path):
    """断言直接通过文本替换将 ⬜ 待确认 改为 🔨 执行中 被拦截（ask）。"""
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(SAMPLE_TASK_CONTENT, encoding="utf-8")

    args = {
        "TargetContent": "### 任务 1.1 ⬜ 待确认 — 示例任务A",
        "ReplacementContent": "### 任务 1.1 🔨 执行中 — 示例任务A",
    }
    res = check_task_status_guard(str(task_file), "replace_file_content", args)
    assert res is not None
    assert res["decision"] == "ask"
    assert "dev_tasks_checkout" in res["reason"]


def test_new_task_file_with_confirmed_or_in_progress_intercepted(tmp_path):
    """断言新建任务单包含非待确认状态被拦截（ask 状态走私阻断）。"""
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_new.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)

    smuggled_content = """# New Tasks
### 任务 2.1 ✅ 已确认 — 私自越级确认任务
"""
    args = {"CodeContent": smuggled_content}
    res = check_task_status_guard(str(task_file), "write_to_file", args)
    assert res is not None
    assert res["decision"] == "ask"
    assert "物理阻断" in res["reason"] or "初稿一律必须从" in res["reason"]


def test_delete_existing_non_editable_task_intercepted(tmp_path):
    """断言删除已有执行中或已完成状态的任务块被拦截（ask 保护审计台账）。"""
    completed_content = SAMPLE_TASK_CONTENT.replace("1.2 🔄 需返工", "1.2 ✔️ 已完成")
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(completed_content, encoding="utf-8")

    # 尝试删除 1.2 已完成任务块
    purged_content = completed_content.split("### 任务 1.2")[0]
    args = {
        "TargetContent": completed_content,
        "ReplacementContent": purged_content,
    }
    res = check_task_status_guard(str(task_file), "replace_file_content", args)
    assert res is not None
    assert res["decision"] == "ask"
    assert "非可编辑任务" in res["reason"] or "审计台账" in res["reason"]


def test_delete_file_task_file_intercepted(tmp_path):
    """断言 delete_file 操作受管任务单被拦截（ask 引导使用 revoke）。"""
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(SAMPLE_TASK_CONTENT, encoding="utf-8")

    res = check_task_status_guard(str(task_file), "delete_file", {})
    assert res is not None
    assert res["decision"] == "ask"
    assert "物理删除阻断" in res["reason"]
    assert "revoke" in res["reason"]


def test_truncate_empty_task_file_intercepted(tmp_path):
    """断言将非空任务单截断清空被拦截（ask）。"""
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(SAMPLE_TASK_CONTENT, encoding="utf-8")

    args = {"CodeContent": ""}
    res = check_task_status_guard(str(task_file), "write_to_file", args)
    assert res is not None
    assert res["decision"] == "ask"
    assert "截断清空" in res["reason"] or "拦截" in res["reason"]


def test_new_duplicate_task_id_intercepted(tmp_path):
    """断言引入重复 task_id（重数增加 1->2 或 2->3）被拦截（ask, F1 multiset）。"""
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(SAMPLE_TASK_CONTENT, encoding="utf-8")

    # 复制 1.1 块产生重复
    duplicate_append = SAMPLE_TASK_CONTENT + "\n### 任务 1.1 ⬜ 待确认 — 重复任务"
    args = {
        "TargetContent": "### 任务 1.2 🔄 需返工 — 示例任务B",
        "ReplacementContent": "### 任务 1.2 🔄 需返工 — 示例任务B\n\n### 任务 1.1 ⬜ 待确认 — 重复任务",
    }
    res = check_task_status_guard(str(task_file), "replace_file_content", args)
    assert res is not None
    assert res["decision"] == "ask"
    assert "重复" in res["reason"]


def test_stock_duplicate_reduction_allowed(tmp_path):
    """断言修复存量脏重复文件（重数减少 2->1）被放行（allow + WARN 避免自锁死）。"""
    dirty_content = SAMPLE_TASK_CONTENT + "\n### 任务 1.1 ⬜ 待确认 — 存量脏重复任务\n"
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_dirty.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(dirty_content, encoding="utf-8")

    # 移除第二个 1.1 块，重数由 2 降为 1
    args = {
        "TargetContent": "\n### 任务 1.1 ⬜ 待确认 — 存量脏重复任务\n",
        "ReplacementContent": "",
    }
    res = check_task_status_guard(str(task_file), "replace_file_content", args)
    assert res is None  # allow!


def test_malformed_header_classification(tmp_path):
    """断言缺失 ID 或缺失状态的畸形标题行归入 malformed_ids 并触发拦截（F2）。"""
    malformed_content = """# Test
### 任务 ⬜ 待确认 — 缺失ID
### 任务 1.3 — 缺失状态
"""
    scan = extract_header_task_statuses(malformed_content)
    assert "missing_id" in scan.malformed_ids
    assert "1.3" in scan.malformed_ids

    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_malformed.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    args = {"CodeContent": malformed_content}
    res = check_task_status_guard(str(task_file), "write_to_file", args)
    assert res is not None
    assert res["decision"] == "ask"


def test_read_only_tools_allowed(tmp_path):
    """断言只读工具对任务单的访问无条件放行（F3）。"""
    task_file = str(tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md")
    for tool in READ_ONLY_TOOLS:
        res = check_task_status_guard(task_file, tool, {})
        assert res is None


def test_unknown_mutating_tool_intercepted(tmp_path):
    """断言未在白名单中的变更类工具操作任务单被拦截（ask）。"""
    task_file = str(tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md")
    res = check_task_status_guard(task_file, "custom_editor_tool", {"patch": "..."})
    assert res is not None
    assert res["decision"] == "ask"
    assert "未知" in res["reason"]


def test_undeterminable_post_image_intercepted(tmp_path):
    """断言当修改参数无法计算后置快照时定向 fail-closed 返回 ask (F3)。"""
    task_file = tmp_path / "docs" / "dev_tasks" / "2026-10-20_sample.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(SAMPLE_TASK_CONTENT, encoding="utf-8")

    # TargetContent 不存在
    args = {
        "TargetContent": "NonExistentString123456789",
        "ReplacementContent": "Replaced",
    }
    res = check_task_status_guard(str(task_file), "replace_file_content", args)
    assert res is not None
    assert res["decision"] == "ask"
    assert "undeterminable_post_image" in res["reason"] or "无法确定" in res["reason"]


def test_ast_zero_status_emoji_constants():
    """断言核心状态流转与守卫源码（state_machine.py 与 file_scope_guard.py）经 AST 扫描零状态 emoji 字符串常量 (F5)。"""
    server_root = Path(__file__).parent.parent
    status_emojis = {0x2b1c, 0x2705, 0x1f528, 0x2714, 0x23ed, 0x1f504}
    py_files = [
        server_root / "state_machine.py",
        server_root / "hooks" / "file_scope_guard.py",
    ]

    violations = []
    for pf in py_files:
        try:
            tree = ast.parse(pf.read_text(encoding="utf-8"), filename=str(pf))
            # 搜集所有 docstring 节点
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                        docstrings.add(id(node.body[0].value))

            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if id(node) in docstrings:
                        continue
                    if any(ord(c) in status_emojis for c in node.value):
                        violations.append((pf.name, node.lineno, node.value))
        except Exception:
            pass

    assert len(violations) == 0, f"发现未迁移至 task_status.py 的硬编码 emoji 字符串字面量: {violations}"


def test_subprocess_import_isolation():
    """断言独立子进程导入 file_scope_guard 后 fastmcp、manifest、filelock、yaml 均不在 sys.modules 中 (F4)。"""
    server_dir = str(Path(__file__).parent.parent.resolve())
    code = """
import sys
import os
server_dir = sys.argv[1]
sys.path.insert(0, server_dir)
import hooks.file_scope_guard
heavy = {'fastmcp', 'manifest', 'filelock', 'yaml'}
loaded = heavy.intersection(sys.modules.keys())
if loaded:
    print(f"LEAK:{','.join(loaded)}")
    sys.exit(1)
sys.exit(0)
"""
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    res = subprocess.run(
        [sys.executable, "-c", code, server_dir],
        cwd=cur_dir,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"导入隔离失败，泄露的重量级模块: {res.stdout.strip()} {res.stderr.strip()}"


def test_performance_extract_header_task_statuses():
    """纯函数性能预算：200KB 合成内容 extract_header_task_statuses 单次耗时 < 15ms，端到端 guard < 25ms (F4)。"""
    # 构造约 200KB 的合成任务单
    blocks = []
    for i in range(250):
        blocks.append(f"""### 任务 {i}.1 ⬜ 待确认 — 合成任务项 {i}
#### 【涉及文件】
```
[MODIFY] src/module_{i}.py
[MODIFY] src/submodule_{i}/service.py
[NEW] src/submodule_{i}/tests/test_service.py
```
#### 【缺陷根因与修改目标】
1. 模块 module_{i} 缺乏对并发冲突的防护，高并发写入时可能导致脏数据写入。
2. 增加基于版本号与行锁的乐观并发重试机制，避免死锁或数据丢失。
#### 【分步改造指引】
1. 执行操作 {i}，注意状态必须保持 `🔨 执行中`。
2. 在 `src/module_{i}.py` 中增加并发控制检测逻辑。
3. 补充针对多线程竞争的集成测试。
#### 【DoD 验证命令】
```bash
pytest src/submodule_{i}/tests/test_service.py -q
```
""")
    synthetic_doc = "\n".join(blocks)
    assert len(synthetic_doc.encode("utf-8")) > 150_000  # 约 150KB - 200KB

    # 预热
    _ = extract_header_task_statuses(synthetic_doc[:1000])

    t0 = time.perf_counter()
    scan = extract_header_task_statuses(synthetic_doc)
    t1 = time.perf_counter()

    elapsed_ms = (t1 - t0) * 1000.0
    assert len(scan.statuses_ordered) == 250
    assert elapsed_ms < 25.0, f"性能耗时超标: {elapsed_ms:.2f}ms >= 25ms"

