# 2026-10-21_ci_parity_and_preflight_fix Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-21

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — TP-3 覆盖扩张授权下沉为文件级并派生 token 投影（R1 修订）

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/_hygiene/rules.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_parity_scope.py
```

#### 【缺陷根因与修改目标】
```
1. 粗粒度 ('server',) 哨兵导致新增顶层模块时自动派生 4×30=120 项三元组，而 MERGED_EXPANSION_ALLOWLIST 为空字面量，合法单调正向扩张被 test_tp3_zero_net_coverage_loss_and_allowlist 误报为越权。
2. R1 修订（关闭 P1-1/P1-2/P1-3）：
   - 授权粒度下沉为 (rule_id, rel_path) 文件级，token 维由 RULE_SCOPE 纯派生，字面量 12 条；
   - derive_expansion_allowlist() 抽为可直测纯函数，导入期绑定常量（物理 fail-closed + 分支可单测）；
   - 死条目律（D-17）由三元组级重基线为文件级双向对齐，否则派生集合 ⊃ 实际 expansions，现存断言必红；
   - 失败消息输出 exp_files Δ allow_files 对称差，保证一次运行可收敛。
```

#### 【目标签名与类型契约】
```python
EXPANSION_ELIGIBLE_RULES: Final[frozenset[str]] = frozenset({
    "touch_outcome_truthiness", "vendor_literal_in_core", "api_bypass",
})

MERGED_FILE_SCOPE_ALLOWLIST: Final[frozenset[tuple[str, str]]] = frozenset({
    ('api_bypass', 'server/ide_schema_export.py'),
    ('api_bypass', 'server/task_status.py'),
    ('api_bypass', 'server/task_writer.py'),
    ('api_bypass', 'server/tool_surface_constants.py'),
    ('touch_outcome_truthiness', 'server/ide_schema_export.py'),
    ('touch_outcome_truthiness', 'server/task_status.py'),
    ('touch_outcome_truthiness', 'server/task_writer.py'),
    ('touch_outcome_truthiness', 'server/tool_surface_constants.py'),
    ('vendor_literal_in_core', 'server/ide_schema_export.py'),
    ('vendor_literal_in_core', 'server/task_status.py'),
    ('vendor_literal_in_core', 'server/task_writer.py'),
    ('vendor_literal_in_core', 'server/tool_surface_constants.py'),
})

def derive_expansion_allowlist(
    file_scope: frozenset[tuple[str, str]],
    eligible: frozenset[str],
    scope: Mapping[str, tuple[str, ...]],
) -> frozenset[tuple[str, str, str]]: ...

MERGED_EXPANSION_ALLOWLIST: Final[frozenset[tuple[str, str, str]]] = \
    derive_expansion_allowlist(MERGED_FILE_SCOPE_ALLOWLIST, EXPANSION_ELIGIBLE_RULES, RULE_SCOPE)
```

#### 【分步改造指引】
1. `rules.py`：补 `from typing import Final, Mapping`；声明 `MERGED_FILE_SCOPE_ALLOWLIST` 为精确授权面（非 provisional）：导入期与实测 exp_files 严格双向相等。收缩与扩张均须经 Reviewer 批准后修改本条；Runner 严禁为使测试转绿而增删条目，遇到不等一律 escalate。注释说明授权下沉至 (rule, file) 属于杜绝 120 行伪造三元组的既定安全设计。
2. 【测量已闭合，禁止重开分支】经 Reviewer 复核与实测验证：新增顶层模块恰为 4 个（ide_schema_export.py / task_status.py / task_writer.py / tool_surface_constants.py），RULE_SCOPE 语料 16 / 1 / 13，故 expansions = 4 × 30 = 120，exp_files = 12。实施方案锁定为「文件级 allowlist + token 派生」。若实施时实测 ≠ 120，视为【上下文与现状】失真，不得自行改判方案，须 dev_tasks_escalate 上报。
3. 实现纯函数 `derive_expansion_allowlist(...)`：按固定顺序进行四重校验：
   - file_scope 为空 -> `ValueError("empty file_scope")`
   - rule 不在 eligible -> `ValueError(f"ineligible rule: {rule}")`
   - rule 不在 scope -> `ValueError(f"out_of_scope rule: {rule}")`
   - path 不属 scope[rule] -> `ValueError(f"out_of_scope path: {rule}:{path}")`（与 `scanner._applies_rule_to_path` 前缀逻辑保持同构）；
   常量绑定 `MERGED_EXPANSION_ALLOWLIST: Final = derive_expansion_allowlist(MERGED_FILE_SCOPE_ALLOWLIST, EXPANSION_ELIGIBLE_RULES, RULE_SCOPE)`。
4. `test_parity_scope.py`：补 `from typing import Final`；新增 `test_expansion_allowlist_well_formed`：
   ① `set(RULE_IDS) == set(RULE_SCOPE) == set(SCAN_ROOTS)`；② `EXPANSION_ELIGIBLE_RULES ⊆ set(RULE_IDS)` 且 `"lease_symbol_removal" not in EXPANSION_ELIGIBLE_RULES`；③ 每条 `(PLUGIN_ROOT / rel_path).is_file()`；④ 调用 `scanner._applies_rule_to_path` 验证路径前缀，消除同源自证；⑤ `derive_expansion_allowlist(MERGED_FILE_SCOPE_ALLOWLIST, EXPANSION_ELIGIBLE_RULES, RULE_SCOPE) == MERGED_EXPANSION_ALLOWLIST == frozenset((r,p,t) ...)`。
5. 新增 `test_derive_expansion_allowlist_rejects_ineligible_rule` 与 `test_derive_expansion_allowlist_rejects_out_of_scope` 分支校验：分别使用 `pytest.raises(ValueError, match="ineligible rule")` 和 `pytest.raises(ValueError, match="out_of_scope")` 验证分支断言。
6. 重写 `test_tp3_zero_net_coverage_loss_and_allowlist` 第 3 段为文件级双向对齐，断言消息含 `sorted(exp_files ^ allow_files)` 对称差。
7. 加固 `test_path_conventions_homomorphic` 的 POSIX 纯净断言（无反斜杠、不以分隔符起始、以 `server/` 起始），补 `canonical_bytes` 对真实 BOM+CRLF 载荷的归一化与幂等断言。

#### 【防御与边缘校验】
- 越权伪造：token 不可手写，全部由 `RULE_SCOPE` 派生；文件不得享受部分 token 授权。
- 禁忌规则：`EXPANSION_ELIGIBLE_RULES` 双钥锁（导入期 `ValueError` + 显式 `pytest.raises`）双层阻断 `lease_symbol_removal` 扩充。
- 死条目：文件级双向对齐 + 对称差可读消息，一次运行定位全部偏差。
- 经验测量闭环：断言 `len(MERGED_FILE_SCOPE_ALLOWLIST) == 12` 且与实测 exp_files 完全吻合。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_parity_scope.py -q
pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q
pytest plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py -q
pytest plugins/quench-dev-tasks/server/tests/test_no_api_bypass.py -q
python -c "import json, sys; from pathlib import Path; td = Path('plugins/quench-dev-tasks/server/tests'); sys.path.insert(0, str(td)); from _hygiene.scanner import ArchitectureHygieneScanner; from _hygiene import rules as R; rep = ArchitectureHygieneScanner(td.parent).scope_report(); base = frozenset(map(tuple, json.loads((td/'_parity'/'isolated_scope_v120.json').read_text(encoding='utf-8-sig'))['entries'])); exp = frozenset(rep) - base; exp_files = frozenset((r, p) for (r, p, t) in exp); print('exp_files:', len(exp_files), 'triples:', len(exp)); assert len(exp_files) == 12 and len(exp) == 120, (len(exp_files), len(exp)); assert R.MERGED_FILE_SCOPE_ALLOWLIST == exp_files, sorted(exp_files ^ R.MERGED_FILE_SCOPE_ALLOWLIST); assert R.MERGED_EXPANSION_ALLOWLIST == frozenset((r, p, t) for (r, p) in R.MERGED_FILE_SCOPE_ALLOWLIST for t in R.RULE_SCOPE[r]) == exp; assert frozenset(rep) == base | exp"
git status --porcelain
```

---

### 任务 1.2 ✔️ 已完成 — Pre-flight 探测去副作用化、三态门禁定级与跨平台纯测试隔离（R2 修订）

#### 【涉及文件】
```
[MODIFY] scripts/install.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_install.py
```

#### 【缺陷根因与修改目标】
```
1. os.rename(p_dir, p_dir) 在 Windows 因打开句柄高概率抛 ACCESS_DENIED(5) 产生伪阻断；CPython 将 WinError 32/33 亦映射为 EACCES，简单判定阻断会造成假死。
2. R2 修订（彻底闭合 B-2a/B-2b/B-2c/B-2d 及 R3-b/R3-c）：
   - 以 mkstemp 哨兵替换 rename 探测，并在文案上诚实降级为「目录可写性探测」（不宣称句柄锁定检测）；
   - 抽离 classify_probe_error 纯函数，先 winerror 后 errno，ENOENT 归 blocked（TOCTOU 目录消失属 fail-closed 场景）；
   - run_preflight 增加 keyword-only repo_root / log_dir 注入；MAX_PATH 审计先于目录存在性前置检查，避免早退破坏既有断言；
   - test_max_path_audit_limits 采用目标长度反算填充，杜绝 CI 平台 tmp_path 路径长度差导致的假红；三用例均显式注入 tmp_path/bak 与 tmp_path/logs 隔离，并加入 probe_len <= 259 显式余量断言；
   - 探针断言与 DoD 严格使用被测目录为根（Path('.').rglob('.quench_preflight_*') 恒空）；
   - _LOG_ARTIFACT_RESERVE_CHARS == 40 跨文件平价测试声明接受在 Tier-2 test_install.py 中覆盖。
```

#### 【目标签名与类型契约】
```python
from typing import Dict, Final, List, Literal, Optional, Tuple

ProbeVerdict = Literal["ok", "advisory", "blocked"]
PREFLIGHT_PROBE_ATTEMPTS: Final[int] = 3          # 总尝试次数（非 1+3）
PREFLIGHT_PROBE_BACKOFF_S: Final[float] = 0.05
MAX_PATH_WARN_CHARS: Final[int] = 200
MAX_PATH_BLOCK_CHARS: Final[int] = 250
_LOG_ARTIFACT_RESERVE_CHARS: Final[int] = 40      # 对齐 log_naming.MAX_LOG_REF_CHARS
_PROBE_PREFIX: Final[str] = ".quench_preflight_"

def classify_probe_error(err: OSError) -> ProbeVerdict: ...
def probe_directory_writability(target_dir: str) -> tuple[ProbeVerdict, str]: ...
def get_plugin_dir(repo_root: Optional[str] = None) -> str: ...
def get_backup_path(repo_root: Optional[str] = None, override: Optional[str] = None) -> str: ...
def run_preflight(
    plugin_dir: str,
    backup_path: str,
    *,
    repo_root: Optional[str] = None,
    log_dir: Optional[str] = None,
) -> Tuple[bool, List[str]]: ...
```

#### 【分步改造指引】
1. `classify_probe_error`：`winerror = getattr(err, "winerror", None)`；`in (32, 33) → advisory`；`== 5 → blocked`；`is not None → blocked`；再判 `err.errno`：`ENOENT → blocked`（TOCTOU），`in (EACCES, EPERM, EROFS, ENOSPC, EIO, ENOTDIR) → blocked`，其余（含 None）→ blocked。
2. `probe_directory_writability`：循环 `range(PREFLIGHT_PROBE_ATTEMPTS)`；每轮 `mkstemp(prefix=_PROBE_PREFIX, dir=target_dir)`，`try/finally` 内先 `os.close(fd)` 再 `os.remove(probe)`（remove 失败重试 1 次，最终仍失败 → 返回 `('advisory', f"{detail}; residue={probe}")` 供确定性清理）；捕获 `OSError`：`blocked` 立即返回不重试，`advisory` 退避 `PREFLIGHT_PROBE_BACKOFF_S` 后重试；耗尽返回最后一次 advisory。
3. 重构 `run_preflight`，顺序固定为：**(a) MAX_PATH 审计 → (b) `not os.path.isdir(p_dir)` 则 append `❌ plugin directory missing: {p_dir}`、`passed=False`、跳过探测 → (c) 探测 → (d) 快照备份**。(a) 候选集 `max(len(abspath(plugin_dir)), len(abspath(repo_root or derived)), len(abspath(log_dir or derived)) + 1 + _LOG_ARTIFACT_RESERVE_CHARS)`，纯字符串算术；文案保留 `安全审计通过` / `MAX_PATH 警告` / `MAX_PATH 阻断` 子串，探测行改用 `✅/⚠️/❌ [目录可写性探测]`。
4. `main()` / `get_plugin_dir` / `get_backup_path` 支持 `--repo-root`、`--backup-path`（override 经 `os.path.abspath`），并把 `repo_root` 透传进 `run_preflight(..., repo_root=...)`；`--preflight` 失败时 `return 1`（显式退出码契约）。
5. `test_install.py`：
   - 新增 `_synthetic_oserror(*, errno_val=0, winerror=None)` helper；
   - `test_classify_probe_error_pure` 覆盖 winerror 32/33/5/999/None × errno ENOENT/EACCES/ENOSPC/EROFS/EIO/ENOTDIR/None 全矩阵（显式 `e.winerror = None` 保证 Windows 确定性）；
   - `test_preflight_probe_is_non_mutating` 验证探针正常且以 target_dir 为根 `target_dir.rglob('.quench_preflight_*')` 恒空；
   - advisory/blocked 用 **prefix 判别** 的 `mkstemp` side_effect（非 `_PROBE_PREFIX` 时委托真函数），且打桩 `time.sleep` 避免引入测试延迟；
   - **重写 `test_max_path_audit_limits` (B-2a 目标长度反算精准构造与 R3-b 注入)**：
     - Case 1 (pass): 真实短目录 `d = tmp_path / "short"`, `d.mkdir()`, 传入 `run_preflight(str(d), str(tmp_path / "bak"), repo_root=str(tmp_path), log_dir=str(tmp_path / "logs"))`, 断言 `"安全审计通过"` 且 `passed is True`；
     - Case 2 (warn): 动态反算填充 `target = MAX_PATH_WARN_CHARS + 25` (225), `pad = target - len(str(tmp_path)) - 1`, 断言 `2 <= pad <= 200`, `d = tmp_path / ("a" * pad)`, `d.mkdir()`, 断言 `len(os.path.abspath(d)) + 1 + len(_PROBE_PREFIX) + 8 <= 259`, 验证 `200 < len(abspath(d)) <= 250`, 传入 `run_preflight(str(d), str(tmp_path / "bak"), repo_root=str(tmp_path), log_dir=str(tmp_path / "logs"))`, 断言 `"MAX_PATH 警告"` 且 `passed is True`；
     - Case 3 (block): 构造三段合法组件 `d = tmp_path / ("x"*100) / ("y"*100) / ("z"*100)`（全程不创建目录），传入 `run_preflight(str(d), str(tmp_path / "bak"), repo_root=str(tmp_path), log_dir=str(tmp_path / "logs"))`, 断言 `"MAX_PATH 阻断"` 且 `passed is False`；
   - `test_cli_preflight_flag` 注入临时 `--repo-root`（内含 stub `plugins/quench-dev-tasks` + 模板）与 `--backup-path`，断言对真实工作区零残留；
   - 清理旧断言残留（检查并替换旧文案如“句柄锁定”等）。
6. 断言 `_LOG_ARTIFACT_RESERVE_CHARS == 40` 与 `log_naming.MAX_LOG_REF_CHARS == 40` 的**跨文件平价**（在 Tier-2 明确覆盖）。

#### 【防御与边缘校验】
- Fail-Closed 铁律：未知 winerror、未知 POSIX errno、ENOSPC/EIO/EROFS/ENOTDIR、ENOENT 一律 blocked。
- 零残留：每轮探测路径独立，`finally` 先 close 后 remove；remove 二次失败降级 advisory 并在 detail 回传路径。
- 打桩隔离：`mkstemp` side_effect 必须按 prefix 判别，否则 `atomic_write_file` 连带失败。
- 测试隔离：`test_cli_preflight_flag` 与 MAX_PATH 用例全部落 `tmp_path`，`git status --porcelain` 必须为空。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_install.py -q
pytest -m tier1_fast -q
python -c "from pathlib import Path; r = list(Path('.').rglob('.quench_preflight_*')); assert not r, r"
# [SUPERSEDED BY 1.3-R3] 原等值断言已由 1.3-R3 单向不等式断言替代
python -c "import sys; sys.path.insert(0,'plugins/quench-dev-tasks/server'); from log_naming import LOG_FILENAME_REGEX as R, MAX_LOG_REF_CHARS as M; assert 0 < M <= 40; assert R.match('20261021_001_session_bypass_token.log')"
python -c "import sys,errno; sys.path.insert(0,'scripts'); import install as i; e=OSError(errno.EACCES,'x'); e.winerror=32; assert i.classify_probe_error(e)=='advisory'; e.winerror=5; assert i.classify_probe_error(e)=='blocked'; e.winerror=None; e.errno=errno.ENOSPC; assert i.classify_probe_error(e)=='blocked'; e.errno=errno.ENOENT; assert i.classify_probe_error(e)=='blocked'"
git status --porcelain
```

---

### 任务 1.3 ✔️ 已完成 — Preflight Probe 健壮性补强、ENOENT 幂等清理语义、AST 门禁方法论钉扎与文档锚点闭合（1.3-R10 终审版）

#### 【涉及文件】
```
[MODIFY] docs/dev_tasks/2026-10-21_ci_parity_and_preflight_fix.md
[MODIFY] scripts/install.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_install.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py
[MODIFY] docs/ci_incident_tracker_and_compatibility_guide.md
```

#### 【缺陷根因与修改目标】
```
1. 【写探测缺失】当前探测仅 mkstemp 创建 0 字节文件即 close，未验证真实写权限（Windows/NFS 只读挂载可能允许 touch/create 却在 write 时拒绝）。
2. 【清理假阴性阻断】Windows 上杀毒软件或文件索引服务可能在 mkstemp 后瞬间移走探针文件，导致 os.remove 抛 ENOENT/WinError 2/3。当前判定为阻断或未捕获，造成安装假失败；清理侧 ENOENT 实际代表目标已无残留，属幂等成功。
3. 【语义不对称与双向行为验证 (D2/F-2)】写入侧 ENOENT 属 TOCTOU 严重错误（目录中途消失）必须 fail-closed 判 blocked；清理侧 unlink ENOENT 代表无残留判定为 ok。除 AST 门禁隔离引用外，需通过独立行为用例 test_enoent_semantics_asymmetric_contract 分别断言两函数的相反结论。
4. 【写块类型安全化 (D5/F-7)】写探测块需遵循类型窄化标准：assert fd is not None; local_fd: int = fd; fd = None; os.close(local_fd)，保证异常时 close 与 cleanup 语义清晰。
5. 【AST 门禁方法论钉扎 (D3/F-3/F-4)】在 test_architecture_hygiene.py 中，_is_enoent 门禁需严格按照 AST 节点计数与 span 区间校验：FunctionDef 计数 == 1，Name 计数 == 2，两处 call 的 lineno 必须落在 probe_directory_writability 的行区间内；classify_probe_error 函数子树内 _is_enoent 的 Name 引用列表恒为空。
6. 【文档锚点逐字外锚 (D4/F-5)】在 docs/ci_incident_tracker_and_compatibility_guide.md 中追加 Preflight Probe unlink ENOENT 幂等语义章节与三条不可篡改的锚点句；测试端基于仓库根绝对路径解析并仅作子串断言。
7. 【DoD ⑤ 全量闭合 (D1/F-1)】DoD ⑤ 补全实命令 `python -m pytest plugins/quench-dev-tasks/server/tests -m tier1_fast -q`，满足 ≤5s 契约与非空项验证。
8. 【防御性排除】严禁改动任何 @mcp.tool 签名或 docstring；严禁运行 export_ide_schemas.py --write；test_12 若有任何失败一律 dev_tasks_escalate。
9. 【跨层日志引用上限字面量 (test_snapshot_contract.py)】断言 0 < MAX_LOG_REF_CHARS <= 40，保证其与 install reserve 的单向不等式关系。
```

#### 【目标签名与类型契约】
```python
from typing import Dict, Final, List, Literal, Optional, Tuple

ProbeVerdict = Literal["ok", "advisory", "blocked"]
_PROBE_REMOVE_RETRY_S: Final[float] = 0.01

def _is_enoent(err: OSError) -> bool: ...
def probe_directory_writability(target_dir: str) -> Tuple[ProbeVerdict, str]: ...

# tests/test_install.py
def test_enoent_semantics_asymmetric_contract() -> None: ...
def test_preflight_probe_doc_exists() -> None: ...
def test_is_enoent_predicate() -> None: ...

# tests/test_architecture_hygiene.py
def test_is_enoent_confined_to_unlink_branches_ast() -> None: ...
def test_probe_remove_retry_constant_ast() -> None: ...
def test_install_write_probe_uses_single_byte_constant_ast() -> None: ...
def test_install_reserve_chars_defined_exactly_once_ast() -> None: ...
def test_max_log_ref_chars_within_install_reserve_ast_bound() -> None: ...
```

#### 【分步改造指引】
1. **常量与常量约束**：
   - `scripts/install.py` 中补充 `_PROBE_REMOVE_RETRY_S: Final[float] = 0.01`。
   - `_LOG_ARTIFACT_RESERVE_CHARS: Final[int] = 40` 保持单一定义，附带派生说明注释。
2. **三路 _is_enoent 辅助函数**：
   - 在 `scripts/install.py` 实现 `_is_enoent(err: OSError) -> bool`：
     - 若 `isinstance(err, FileNotFoundError)` 返回 True；
     - 若 `getattr(err, "winerror", None) in (2, 3)` 返回 True；
     - 返回 `getattr(err, "errno", None) == errno.ENOENT`。
   - 严格禁止在 `classify_probe_error` 中调用 `_is_enoent`。
3. **probe_directory_writability 单字节写探测与规范所有权顺序 (S-1)**：
   - 每轮首行重置局部状态：`fd: Optional[int] = None`、`probe_path: Optional[str] = None`、`residue_confirmed = False`。
   - 外层 `try` 捕获 `mkstemp`，并在内层嵌套保证写与关闭所有权：
     ```python
     fd, probe_path = tempfile.mkstemp(prefix=_PROBE_PREFIX, dir=target_dir)
     assert fd is not None
     local_fd: int = fd
     fd = None  # 所有权转移，防双 close
     try:
         if os.write(local_fd, b"\x00") != 1:
             raise OSError(errno.EIO, "probe short write")
     finally:
         os.close(local_fd)  # 顺序铁律：先 write 后 close，write 失败亦必 close
     ```
   - 外层 `finally` 仅覆盖转移前异常（`if fd is not None: try: os.close(fd) except OSError: pass`）。
4. **清理双轮 ENOENT 短路绑定与残留报告 (E-2)**：
   - 首轮 remove 遇 `OSError` 且 `_is_enoent(first_err)` 为真时，`probe_path = None` 并立即返回 `("ok", "目录可写性探测通过")`。
   - 首轮失败后 sleep `_PROBE_REMOVE_RETRY_S`，第二轮 remove 遇 `OSError` 且 `_is_enoent(rm_err)` 为真时同样返回 `("ok", "目录可写性探测通过")`。
   - 仍失败且非 ENOENT，标记 `residue_confirmed = True` 并返回 `("advisory", f"哨兵文件删除失败: {rm_err}; residue={probe_path}")`。
5. **finally 清理防护 (E-3)**：
   - 外层 `finally`：先关闭转移前残留 `fd`（若非空），后安全 remove `probe_path`（`try: os.remove(probe_path) except OSError: pass`，严禁在其中调用 `_is_enoent`，维持 AST 门禁 `ast.Name(id="_is_enoent")` 计数恰为 2；步骤 4 中两处成功清理路径均置 `probe_path = None`）。
6. **架构与门禁清理**：
   - 清理 `plugins/quench-dev-tasks/server/tests/test_install.py` 对 `log_naming` 的任何直接引用。
   - `plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py` 断言 `0 < MAX_LOG_REF_CHARS <= 40`。
7. **回归测试用例 (test_install.py)**：
   - `test_enoent_semantics_asymmetric_contract`：独立双断言，验证 `classify_probe_error(err) == "blocked"` 与 `_is_enoent(err) is True`（兼顾 POSIX 与 Windows 分支）。
   - `test_probe_write_failure_leaves_no_residue`。
   - `test_probe_close_failure_leaves_no_residue`（使用 `close_then_raise` 夹具）。
   - `test_probe_remove_enoent_is_success` 与 `test_probe_remove_enoent_on_retry_is_success` (S-3)：采用忠实模拟（“先真删、后抛 ENOENT”），确保真实探针已被清理，零残留断言与 ok 裁决并存。
   - `test_probe_directory_writability_remove_retry_failure`。
   - `test_is_enoent_predicate`：覆盖真异常与鸭子类型。
   - `test_preflight_probe_doc_exists` (E-1)：基于 `Path(__file__).resolve().parents[4]` 解析仓库根（tests → server → quench-dev-tasks → plugins → repo_root），并在子串断言前先 `assert doc_path.is_file()`。
8. **AST 架构卫生门禁 (test_architecture_hygiene.py)**：
   - `test_is_enoent_confined_to_unlink_branches_ast`：执行 D3 方法论，以 repo-root 绝对路径解析 scripts/install.py，`defs` 计数 1，`names` 计数 2，两处 call 的 lineno 在 probe body 区间，classify 中引用数 0。
   - `test_probe_remove_retry_constant_ast`：常量 == 0.01 且 probe 内无裸 `sleep(0.01)`。
   - `test_install_write_probe_uses_single_byte_constant_ast`。
   - `test_install_reserve_chars_defined_exactly_once_ast`。
   - `test_max_log_ref_chars_within_install_reserve_ast_bound`。
9. **文档沉淀 (docs/ci_incident_tracker_and_compatibility_guide.md)**：
   - 写入三条完整锚点句：
     - `### Preflight Probe — unlink ENOENT / winerror 2|3 幂等语义`
     - `当 os.remove 返回 ENOENT 或 Windows winerror ∈ {2, 3} 时，视为目标文件已不存在，探测判定为 ok，不产生 residue。`
     - `当 os.remove 返回 winerror ∈ {32, 33}（共享冲突）时，判定为 advisory 并保留 residue 路径以支持人工清理。`

#### 【防御与边缘校验】
- D2 断言必须两条独立 assert，严禁 `and` 短路聚合。
- D3 中 FunctionDef.name 计数与 ast.Name.id 计数必须分开断言；定位失败报错而非静默。
- D4/E-1 路径解析必须基于 __file__ 的 parents[4] 解析仓库根路径，严禁依赖当前工作目录 CWD；仅子串断言，禁断言行号。
- D5/S-1 写块必须严格按 write → close 顺序执行，先置空 fd 后在内层 finally 执行 close；类型窄化不得改变运行期行为。
- S-3 清理侧 ENOENT 测试打桩必须忠实模拟“文件已被移走”（先真实 remove 后抛错），避免探针残留在磁盘导致零残留审计失败。
- 短写（os.write 返回值 0）必须抛出 EIO 被捕获判为 blocked。
- 零残留：patch 域内 teardown 必须使用 Path.unlink() / os.unlink，避免污染 os.remove 调用计数。
- S-5/INV-2 防御：任务单自身严禁手改状态 emoji；状态流转仅由 `dev_tasks_*` MCP 工具驱动。

#### 【DoD 验证命令】
```bash
# ① 探针行为与谓词 + 新增 ENOENT 双向语义断言 + 文档只读断言
python -m pytest plugins/quench-dev-tasks/server/tests/test_install.py -q
# ② 架构卫生 AST 门禁（C3 方法论钉扎 / C4 常量钉扎 / 单字节写 / 单一定义 / 动态 floor）
python -m pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q -k "install or log_ref or enoent or probe"
# ③ 跨层预算字面量侧（0 < MAX_LOG_REF_CHARS <= 40）
python -m pytest plugins/quench-dev-tasks/server/tests/test_snapshot_contract.py -q
# ④ 日志引用格式与长度基线
python -m pytest plugins/quench-dev-tasks/server/tests/test_log_naming.py -q
# ⑤ 快速回归全量门禁（≤5s 契约、非空 item 计数）
python -m pytest plugins/quench-dev-tasks/server/tests -m tier1_fast -q
# ⑥ 文档路径与物理存在性快检
python -c "from pathlib import Path; p = Path('plugins/quench-dev-tasks/server/tests/test_install.py').resolve().parents[4] / 'docs' / 'ci_incident_tracker_and_compatibility_guide.md'; print(p); assert p.is_file(), p"
```

---


