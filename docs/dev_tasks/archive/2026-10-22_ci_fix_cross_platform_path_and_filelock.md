# 2026-10-22_ci_fix_cross_platform_path_and_filelock Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-22

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 修复 `_DRIVE_ABS` 命名常量字符类、加固 W10 单次 Poll 作用域与案例 12 归档（Rev A11 闭环）

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/reviewer_jobs.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_poll_nonterminal_contract_v2.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_longpoll_v124.py
[NEW] plugins/quench-dev-tasks/server/tests/test_ci_case6_zero_stat_harness.py
[NEW] plugins/quench-dev-tasks/server/tests/test_doc_invariants_case12.py
[MODIFY] docs/architecture/README.md
[MODIFY] docs/ci_incident_tracker_and_compatibility_guide.md
```

#### 【缺陷根因与修改目标】
```
【Rev A10 终审闭环（A~H 彻底修复）】
1. [A/B 命名常量字符类] _BACKSLASH 为 chr(0x5C)，_FWD 为 chr(0x2F)；采用 rf"^[A-Za-z]:[{re.escape(_FWD)}{re.escape(_BACKSLASH)}]" 构造 _DRIVE_ABS，彻底杜绝转义模糊；
2. [C/D 向量边界覆盖] 补充 Win32 设备路径 (\\\\?\\C:\\x) 与 3 反斜杠 (\\\\\\srv) 边界向量；23 项向量两两互异且手算逐项自洽；
3. [E 追踪器单次轮询作用域] _ExemptInodeTracker 契约严格绑定单次 poll/watch 调用生命周期，非进程级全局单例，杜绝内存泄漏；
4. [F AST 豁免 DirEntry.stat] 单测明确禁调 os.stat/os.lstat/Path.stat/Path.lstat，明确豁免 entry.stat(follow_symlinks=False)；
5. [G README 3.3.1 精确锚点] 断言 ### 3.3.1 位于 §3.3 之后，且其后紧邻的下一个三级标题即为 ### 3.4；
6. [H DoD 命令完备] 包含 9 项全量验证命令，在 1-210 行区间内完整提供。
```

#### 【目标签名与类型契约】
```python
from enum import Enum
from typing import Final
import re
from pathlib import Path
from typing import Any

class PathFlavor(str, Enum):
    SAFE_RELATIVE = "safe_relative"
    NT_ABSOLUTE = "nt_absolute"
    POSIX_ABSOLUTE = "posix_absolute"
    UNC = "unc"
    DRIVE_RELATIVE = "drive_relative"
    EMPTY_OR_INVALID = "empty_or_invalid"

_BACKSLASH: Final = chr(0x5C)                # U+005C REVERSE SOLIDUS (backslash)
_FWD: Final = chr(0x2F)                      # U+002F SOLIDUS (forward slash)
_UNC_PREFIX_BS4: Final = _BACKSLASH * 4      # 4 backslashes
_UNC_PREFIX_BS2: Final = _BACKSLASH * 2      # 2 backslashes
_NT_ROOT_BS: Final = _BACKSLASH              # 1 leading backslash
_POSIX_ROOT_FS2: Final = _FWD * 2            # "//" 2 forward slashes

_SEP_CLASS: Final = re.escape(_FWD) + re.escape(_BACKSLASH)
_DRIVE_ABS: Final = re.compile(rf"^[A-Za-z]:[{_SEP_CLASS}]")
_DRIVE_ONLY: Final = re.compile(r"^[A-Za-z]:$")
_DRIVE_ANY: Final = re.compile(r"^[A-Za-z]:")

def _inode_key(st_dev: int, st_ino: int) -> tuple[int, int]:
    return (st_dev, st_ino)

def _classify_log_ref_path(s: str) -> PathFlavor:
    if not s or not s.strip():                       # [1] empty/whitespace
        return PathFlavor.EMPTY_OR_INVALID
    if s.startswith(_UNC_PREFIX_BS4):                # [2] 4 backslashes -> UNC
        return PathFlavor.UNC
    if s.startswith(_UNC_PREFIX_BS2):                # [3] 2 backslashes -> UNC
        return PathFlavor.UNC
    if s.startswith(_NT_ROOT_BS):                    # [4] 1 backslash root -> NT_ABSOLUTE
        return PathFlavor.NT_ABSOLUTE
    if _DRIVE_ONLY.fullmatch(s):                     # [5] "C:" -> DRIVE_RELATIVE
        return PathFlavor.DRIVE_RELATIVE
    # 契约约束：_DRIVE_ABS 必须先于 _DRIVE_ANY 求值，保证 "C:\x" 命中 NT_ABSOLUTE
    if _DRIVE_ABS.match(s):                          # [6] "C:/x" or "C:\x" -> NT_ABSOLUTE
        return PathFlavor.NT_ABSOLUTE
    if _DRIVE_ANY.match(s):                          # [7] "C:x" -> DRIVE_RELATIVE
        return PathFlavor.DRIVE_RELATIVE
    if s.startswith(_POSIX_ROOT_FS2):                # [8] "//..." -> POSIX_ABSOLUTE
        return PathFlavor.POSIX_ABSOLUTE
    if s.startswith(_FWD):                           # [9] "/x" -> POSIX_ABSOLUTE
        return PathFlavor.POSIX_ABSOLUTE
    return PathFlavor.SAFE_RELATIVE                  # [10] fallthrough

_CASE12_VECTORS: Final[tuple[tuple[str, PathFlavor], ...]] = (
    ("",                                  PathFlavor.EMPTY_OR_INVALID),
    ("   ",                               PathFlavor.EMPTY_OR_INVALID),
    (chr(9) + chr(13) + chr(10),          PathFlavor.EMPTY_OR_INVALID),
    (chr(0x5C)*4 + "srv" + chr(0x5C)*2 + "share",  PathFlavor.UNC),
    (chr(0x5C)*2 + "srv" + chr(0x5C) + "share",    PathFlavor.UNC),
    (chr(0x5C)*2 + "srv" + chr(0x5C) + "share" + chr(0x5C) + "x", PathFlavor.UNC),
    (chr(0x5C)*2 + "?" + chr(0x5C) + "C:" + chr(0x5C) + "x", PathFlavor.UNC), # Win32 device path
    (chr(0x5C)*3 + "srv",                 PathFlavor.UNC), # 3-backslash boundary
    (chr(0x5C)*2,                         PathFlavor.UNC),
    (chr(0x5C) + "Windows" + chr(0x5C) + "System32", PathFlavor.NT_ABSOLUTE),
    ("C:",                                PathFlavor.DRIVE_RELATIVE),
    ("c:",                                PathFlavor.DRIVE_RELATIVE),
    ("C:/x",                              PathFlavor.NT_ABSOLUTE),
    ("C:" + chr(0x5C) + "x",              PathFlavor.NT_ABSOLUTE),
    ("C:/Windows/System32",               PathFlavor.NT_ABSOLUTE),
    ("C:x",                               PathFlavor.DRIVE_RELATIVE),
    ("Z:relative",                        PathFlavor.DRIVE_RELATIVE),
    ("//srv/share",                       PathFlavor.POSIX_ABSOLUTE),
    ("/",                                 PathFlavor.POSIX_ABSOLUTE),
    ("/etc/passwd",                       PathFlavor.POSIX_ABSOLUTE),
    ("/Windows/System32",                 PathFlavor.POSIX_ABSOLUTE),
    ("..",                                PathFlavor.SAFE_RELATIVE),
    ("20261022_001_sess.log",             PathFlavor.SAFE_RELATIVE),
)

class _ExemptInodeTracker:
    """锁原语豁免追踪器。作用域限定于单次 poll/watch 调用，非长驻单例。"""
    def __init__(self, maxsize: int = 256) -> None:
        self._maxsize = maxsize
        self._registered: set[tuple[int, int]] = set()
        self._baseline_fp: dict[tuple[int, int], tuple[int, int]] = {}
    def register(self, path: Path) -> None:
        try:
            st = path.stat()
            k = _inode_key(st.st_dev, st.st_ino)
            self._registered.add(k)
            self._baseline_fp[k] = (st.st_size, st.st_mtime_ns)
        except OSError:
            pass
    def is_exempt(self, key: tuple[int, int], size: int, mtime_ns: int) -> bool:
        if key not in self._registered:
            return False
        base = self._baseline_fp.get(key)
        if base is None:
            return False
        return base == (size, mtime_ns)

def _snapshot_business_state_scandir(
    ws: Path, *, exempt: _ExemptInodeTracker | None = None
) -> dict[tuple[int, int], tuple[int, int]]:
    out: dict[tuple[int, int], tuple[int, int]] = {}
    try:
        with os.scandir(ws) as it:
            for entry in it:
                if entry.name in {".git", ".venv", "venv", "__pycache__"}:
                    continue
                try:
                    st = entry.stat(follow_symlinks=False)
                    k = _inode_key(st.st_dev, st.st_ino)
                    if exempt is not None and exempt.is_exempt(k, st.st_size, st.st_mtime_ns):
                        continue
                    out[k] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    continue
    except OSError:
        pass
    return out
```

#### 【分步改造指引】
1. `reviewer_jobs.py`：实现 `_DRIVE_ABS = re.compile(rf"^[A-Za-z]:[{_SEP_CLASS}]")` 与 `_classify_log_ref_path`；实现 `_inode_key`、单次调用作用域的 `_ExemptInodeTracker` 与 `_snapshot_business_state_scandir`；在 `_assert_nonterminal_contract` 中校验 `isinstance` 先于分类，并拒绝非 `SAFE_RELATIVE`。
2. `test_poll_nonterminal_contract_v2.py`：载入 23 项唯一向量；断言 `len == len(set) == 23`；参数化断言分类结果；三样本断言：`("C:/x")→NT_ABSOLUTE`、`("C:\\x")→NT_ABSOLUTE`、`("C:x")→DRIVE_RELATIVE`；非 str 校验（None, 123, b"x"）断言 `SnapshotContractViolation`。
3. `test_reviewer_poll_longpoll_v124.py`：W10 使用 `_ExemptInodeTracker` 断言 before == after；新增 `test_exempt_tracker_key_consistency`；新增 `test_register_stat_failure_is_failclosed`；新增 `test_exempt_drift_reincluded_as_business`；标记 `@pytest.mark.heavy`。
4. `test_ci_case6_zero_stat_harness.py`：[NEW] AST 仅 walk `_snapshot_business_state_scandir` 的单个 `FunctionDef` 节点，断言无显式 os.stat/os.lstat/Path.stat/Path.lstat，明确豁免 `entry.stat(follow_symlinks=False)`。
5. `test_doc_invariants_case12.py`：[NEW] 断言 README 包含且仅有一个 `### 3.3.1 W10 Exclusion Domain (锁原语豁免域)`，且位于 §3.3 与 §3.4 之间且其后紧邻标题为 ### 3.4；断言 CI 手册包含且稠密覆盖案例 1..12 与正则 `INC-\d{8}-\d{2}`。
6. `docs/architecture/README.md`：在 §3.3 末尾、`### 3.4 Task Contract & Bilingual Headings SSOT` 紧邻前置位置追加 `### 3.3.1 W10 Exclusion Domain (锁原语豁免域)`。
7. `docs/ci_incident_tracker_and_compatibility_guide.md`：§2.1 增 INC-20261022-01、§3 案例 12、§4 准则 9。

#### 【防御与边缘校验】
1. [P0-2 字符类真值] `_DRIVE_ABS` 匹配 `C:\x` 与 `C:/x`，不匹配 `C:x`；
2. [P0-3 顺序不变量] `_DRIVE_ABS` 先于 `_DRIVE_ANY`，`C:\x` 命中 NT_ABSOLUTE，`C:x` 命中 DRIVE_RELATIVE；
3. [P1-1 stat 失败] 不存在路径 register 不抛异常，is_exempt 恒 False（fail-closed）；
4. [P1-2 key 一致性] register 与 scandir 共用 `_inode_key(st_dev, st_ino)`；
5. [唯一自洽] 23 项向量 `len == len(set) == 23`，包含 Win32 设备路径与 3 反斜杠边界；
6. [R7 预算] Tier-1 fast gate ≤ 5.0s，baseline ≤ 8.0s，heavy 隔离。

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_poll_nonterminal_contract_v2.py -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_reviewer_poll_longpoll_v124.py -v -m heavy
python -m pytest plugins/quench-dev-tasks/server/tests/test_reviewer_poll_longpoll_v124.py -v -k "exempt_tracker_key or register_stat_failure"
python -m pytest plugins/quench-dev-tasks/server/tests/test_ci_case6_zero_stat_harness.py -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_doc_invariants_case12.py -v
pytest -m tier1_fast -q --durations=3
python scripts/check_test_tiering_invariants.py
python scripts/check_test_duration_baselines.py
python -m pytest plugins/quench-dev-tasks/server/tests -q --maxfail=0
```

---
