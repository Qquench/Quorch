# 2026-11-11_v1_33_mcp_response_slimming Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-11

---

## Task List & Status / 任务清单与状态

### 任务 33.0 ✔️ 已完成 — 预算 SSOT 去重、溢出常量化与 INV-10 措辞对账 (Budget SSOT De-duplication & Overflow Constants)

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tool_surface_constants.py
[MODIFY] plugins/quench-dev-tasks/server/reviewer_jobs.py
[MODIFY] docs/architecture/README.md
[MODIFY] docs/roadmap/plan_mcp_response_slimming_and_compact_contract.md
[NEW] plugins/quench-dev-tasks/server/tests/test_response_budget_ssot.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py
```

#### 【缺陷根因与修改目标】
```
【缺陷根因】
1. 33.0 声明 RESPONSE_BUDGET_BYTES 但未登记 HOOK_LOG_CODES / CHECKOUT_REASON_CODES，导致 33.1 与 33.3 依赖悬空（D-01）。
2. 33.0 E1 "所有值均为 ast.Name" 与 step 1 "仅新增 4 个常量" 自相矛盾（D-02）。
3. measure_payload_bytes 与未来 canonical_json 使用不同 json.dumps 参数，存在尺寸口径双源漂移（D-05）。
4. INV-10 在 33.0 阶段即被宣称为 Runtime-Clamped，但钳制在 33.1 才落地（D-12）。

【修改目标】在 33.0 内补齐 HOOK_LOG_CODES、CHECKOUT_REASON_CODES；将 E1 修正为「去重断言」；统一 measure_payload_bytes 为 sort_keys=True 的规范序列化；README INV-10 采用两阶段措辞；同步修订任务书中 33.0/33.1/33.2/33.3 的对应条款。
```

#### 【目标签名与类型契约】
```python
from types import MappingProxyType
from typing import Final, Mapping

MAX_NONTERMINAL_SNAPSHOT_BYTES: Final[int] = 1024
STATUS_COMPACT_MAX_TASKS: Final[int] = 5
STATUS_COMPACT_MAX_HOOK_ENTRIES: Final[int] = 3
HOOK_LOG_TAIL_BYTES: Final[int] = 65536

HOOK_LOG_CODES: Final[frozenset[str]] = frozenset({
    "ASK_MODAL_BLOCKED", "SCOPE_VIOLATION", "BYPASS_ACTIVE",
    "TASK_STATUS_TAMPER", "PATH_OUT_OF_SCOPE", "OTHER",
})
CHECKOUT_REASON_CODES: Final[frozenset[str]] = frozenset({
    "REWORK_REQUIRED", "PENDING_REVIEW", "NO_CONFIRMED_TASKS",
})

RESPONSE_BUDGET_BYTES: Final[Mapping[str, int]] = MappingProxyType({
    "dev_tasks_status": 2048,
    "dev_tasks_checkout": 800,
    "dev_tasks_refine_spec": 600,
    "dev_tasks_promote_draft": 1200,
    "dev_tasks_escalate": 1500,
    "dev_reviewer_submit": 400,
    "dev_reviewer_poll": MAX_NONTERMINAL_SNAPSHOT_BYTES,
    "dev_reviewer_cancel": 512,
    "dev_tasks_propose": 800,
    "dev_tasks_confirm": 800,
    "dev_tasks_complete": 800,
    "dev_tasks_heartbeat": 512,
    "dev_tasks_reclaim": 512,
    "dev_tasks_archive": 800,
    "dev_tasks_set_bypass": 800,
    "dev_tasks_export_handoff_card": 2048,
})

def measure_payload_bytes(payload: Any) -> int:
    """Return canonical UTF-8 byte length of ``payload`` under sorted compact JSON."""
    ...
```

#### 【分步改造指引】
1. 在 `tool_surface_constants.py` 登记 `HOOK_LOG_CODES`、`CHECKOUT_REASON_CODES`、`MAX_NONTERMINAL_SNAPSHOT_BYTES`、`STATUS_COMPACT_MAX_TASKS`、`STATUS_COMPACT_MAX_HOOK_ENTRIES`、`HOOK_LOG_TAIL_BYTES` 6 个常量与 `RESPONSE_BUDGET_BYTES`（键集 == `EXPECTED_TOOL_NAMES`），仅 `dev_reviewer_poll` 使用常量引用；其余保持字面量。
2. 实现 `measure_payload_bytes`（`sort_keys=True`，函数内 import json，顶层零依赖），`measure_tool_schema_bytes` 委托至新原语（保留原 docstring + 追加去重说明）。
3. 检索 `reviewer_jobs.py` 中非终态快照上限定义：若为本地字面量，删除并改为 `from tool_surface_constants import MAX_NONTERMINAL_SNAPSHOT_BYTES`；若已是同类常量，仅收敛引用。不得改变任何现网阈值语义。
4. `README §4` 标题改为 `(10 Core — All Test-Anchored)`；INV-10 名称定为 `Response Budget SSOT (Declared & Test-Anchored)`，描述注明 *"Runtime clamp enforced from 33.1; asserted in `test_response_compactor.py`"*；测试锚点登记包含 `test_response_budget_ssot.py`。
5. `roadmap §3.1` 的预算表去掉 `dev_reviewer_poll: 1024` 字面量，改注 `= MAX_NONTERMINAL_SNAPSHOT_BYTES`。
6. 在 `test_response_budget_ssot.py` 落地 E1-A 到 E1-F 测试用例与交叉文件锚点断言。

#### 【防御与边缘校验】
- **E1-A 去重断言（替代旧 E1 全文）**：`ast.parse` 后遍历 `RESPONSE_BUDGET_BYTES` 内嵌 `Dict` 节点，断言：① 不存在与模块中任意 `Final[int]` 常量值相同的输入字面量（`literal ∩ constant_literals == ∅`）；② `dev_reviewer_poll` 的 value 节点为 `ast.Name` 且 `id == "MAX_NONTERMINAL_SNAPSHOT_BYTES"`；③ 不因注释或在 docstring 中出现 "1024" 而误红（AST 扫描不含 `ast.Expr(Constant)` 的注释/文档节点）。
- **E1-B 常量存在性**：`HOOK_LOG_CODES == frozenset({...6 码...})`；`CHECKOUT_REASON_CODES == frozenset({...3 码...})`；`type(RESPONSE_BUDGET_BYTES) is MappingProxyType`。
- **E1-C 赋值抛 TypeError**：`RESPONSE_BUDGET_BYTES["x"] = 1` 触发 `TypeError`。
- **E1-D 键集等式**：`set(RESPONSE_BUDGET_BYTES) == set(EXPECTED_TOOL_NAMES)` 且 `len == 16`。
- **E1-E 计量口径单点**：`measure_payload_bytes({"b":1,"a":2}) == measure_payload_bytes({"a":2,"b":1})` 且 `== len(canonical_json_equivalent(...))`；同输入两次相等。
- **E1-F 词表与 README 对账**：`"test_response_budget_ssot.py" in README_INV10_ANCHORS`（README §4 正则解析，解析失败时 fail-closed 并携带可读诊断）。
- **交叉文件锚点（对齐 D-10）**：`assert MAX_NONTERMINAL_SNAPSHOT_BYTES == getattr(reviewer_jobs, "MAX_NONTERMINAL_SNAPSHOT_BYTES", MAX_NONTERMINAL_SNAPSHOT_BYTES)` — 即 reviewer_jobs 若已定义同名常量，二者数值必须相同；若 reviewer_jobs 尚未定义，仅断言本任务新值 == 1024。注意使用 `==` 而非 `is`。
- 回滚锚点：git checkout -- plugins/quench-dev-tasks/server/tool_surface_constants.py plugins/quench-dev-tasks/server/reviewer_jobs.py docs/architecture/README.md docs/roadmap/plan_mcp_response_slimming_and_compact_contract.md plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py docs/dev_tasks/2026-11-11_v1_33_mcp_response_slimming.md && rm -f plugins/quench-dev-tasks/server/tests/test_response_budget_ssot.py

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_response_budget_ssot.py -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -v
python -m pytest -m tier1_fast -q
python scripts/check_test_tiering_invariants.py
python scripts/export_ide_schemas.py --check
python scripts/check_prompt_surface.py
python scripts/check_no_api_bypass.py
```

---

### 任务 33.1 ✔️ 已完成 — 运行时预算钳制管道与分类器可达性对账 (Runtime Budget Clamp & Classifier Reachability Reconciliation)

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/server/response_compactor.py
[NEW] plugins/quench-dev-tasks/server/tests/fixtures/response_payloads.py
[NEW] plugins/quench-dev-tasks/server/tests/test_response_compactor.py
[NEW] scripts/measure_tool_response_sizes.py
[MODIFY] docs/architecture/README.md
```

#### 【缺陷根因与修改目标】
```
【缺陷根因】草案仅有 assert_response_budget（测试期断言），生产路径无任何有界钳制；INV-10 无法对真实载荷成立。且 classify_hook_log_entry 的可达码集与 HOOK_LOG_CODES 未做对账。
【修改目标】新增纯函数 fit_to_budget 实施「列表截断 → 按优先级丢键 → 终态保底收敛」的单趟确定性钳制；定义 ResponseBudgetExceeded（测试专用，落位本模块）；classify_hook_log_entry 增加未知码 OTHER 兜底；建立可达码集对账测试。
```

#### 【目标签名与类型契约】
```
STATUS_COMPACT_DROP_ORDER: Final[tuple[str, ...]] = ("last_hook_log_entries_compact", "files", "tasks")
STATUS_COMPACT_ALWAYS_KEEP: Final[tuple[str, ...]] = ("ok", "harness_next_action", "entitlements_hash")
def compact_mapping(data, *, always_keep=(), drop_if_empty=()) -> dict[str, Any]: ...
def canonical_json(data: Any) -> str: ...
def classify_hook_log_entry(raw_line: str) -> str: ...        # 恒 ∈ HOOK_LOG_CODES
def fit_to_budget(tool_name, payload, *, drop_order=None, always_keep=None, phase="default") -> dict[str, Any]: ...
def assert_response_budget(tool_name, payload, *, phase="default") -> None: ...
class ResponseBudgetExceeded(AssertionError): ...
```

#### 【分步改造指引】
1. response_payloads.py 提供全 16 工具典型载荷 + 1 份 40 任务超载载荷（纯 JSON 原生结构，禁 datetime/Path/Decimal）。
2. response_compactor.py：预算与 HOOK_LOG_CODES、STATUS_COMPACT_MAX_TASKS、HOOK_LOG_TAIL_BYTES 一律从 tool_surface_constants import，零字面量复制。
3. fit_to_budget 实现：① 列表字段截断至各自 cap；② 按 drop_order 逐键剔除；③ drop_order 耗尽仍超则触发 tier-2 判别器保底与 tier-3 可观测标记。永不 raise，always_keep 永不被剔除。
4. classify_hook_log_entry 末尾强制 return code if code in HOOK_LOG_CODES else "OTHER"。
5. scripts/measure_tool_response_sizes.py 引导 sys.path（或单向 import fixtures），支持 --check，零磁盘产物。
6. docs/architecture/README.md §5 登记 response_compactor，职责注明“确定性钳制 + 封闭码分类，零模型介入（INV-3）”。

#### 【防御与边缘校验】
- E1 无硬编码：ast 扫描 response_compactor 源码，不含数字/字符串字面量（1024/2048/"ASK_MODAL_BLOCKED" 等），仅常量引用。
- E2 钳制有界性与三级终态：对 40 任务载荷执行 fit_to_budget("dev_tasks_status", ...)，若含 "over_budget_bytes" 则断言 size <= RESPONSE_BUDGET_BYTES["dev_tasks_status"] + 64 (marker overhead)，否则断言 <= 预算；drop_order 耗尽仍超预算时触发 tier-2 判别器保底（harness_next_action={"action": ...}）与 tier-3 可观测标记，全程不抛。
- E3 地板可达性：{ok, harness_next_action, entitlements_hash, tasks[:1]} 单独计量 ≤ 1024B。
- E4 幂等确定性：同一输入连续两次钳制，canonical_json 完全相同。
- E5 分类器对账：使用规范测试桩 (canonical fixtures) 对每种 HOOK_LOG_CODES 码值及未知异常行断言输出；AST 递归扫描 classify_hook_log_entry 的 return 字面量集合 ⊆ HOOK_LOG_CODES。
- E6 哈希稳定性：两个独立子进程计算 entitlements_hash 取值一致；measure_payload_bytes(x) == len(canonical_json(x).encode("utf-8"))。
- 回滚锚点：git checkout -- docs/architecture/README.md && rm -f plugins/quench-dev-tasks/server/response_compactor.py plugins/quench-dev-tasks/server/tests/fixtures/response_payloads.py plugins/quench-dev-tasks/server/tests/test_response_compactor.py scripts/measure_tool_response_sizes.py

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_response_compactor.py -v
python scripts/measure_tool_response_sizes.py --check
python -m pytest -m tier1_fast -q
python scripts/check_no_api_bypass.py
```

---

### 任务 33.2 ✔️ 已完成 — dev_tasks_status 有界钳制接入、Hook 日志尾部读与 full 超集不变量

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/autopilot_harness.py
[MODIFY] docs/architecture/ide_tool_schemas.json
[MODIFY] plugins/quench-dev-tasks/server/tests/test_observability.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_dual_mode_runtime_switch.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_response_compactor.py
[MODIFY] scripts/measure_tool_response_sizes.py
```

#### 【缺陷根因与修改目标】
```
【缺陷根因】草案仅在测试中断言预算，生产路径无界；Hook 日志读取无尾部上界与 fail-open 规约，长会话下每轮 status 调用存在无界 IO 与抛出风险；默认 payload 切换 compact 后，无任何断言保证信息可通过 verbosity="full" 取回。
【修改目标】compact 路径末尾必须经过 fit_to_budget；Hook 日志仅尾部 HOOK_LOG_TAIL_BYTES 字节有界读取并 fail-open（不改变 hooks/* 写侧）；新增 full 超集不变量测试。
```

#### 【目标签名与类型契约】
```
def dev_tasks_status(..., verbosity: Literal["compact", "full"] = "compact") -> Dict[str, Any]: ...
def _read_hook_log_tail(path: Path, max_bytes: int = HOOK_LOG_TAIL_BYTES) -> list[str]: ...  # 失败返回 []
```

#### 【分步改造指引】
1. 只读预检：python -m pytest plugins/quench-dev-tasks/server/tests -x -q，记录受默认形态切换影响的断言。
2. autopilot_harness.HarnessNextAction.to_compact_dict()：action 缺失抛 ValueError，其余空值省略。
3. 拆分 _build_full_status_sync（返回字节级等价于 v1.32 的超集）与 compact 构建路径。
4. compact 路径：常驻 entitlements_hash；_read_hook_log_tail + classify_hook_log_entry 折叠为 ≤ STATUS_COMPACT_MAX_HOOK_ENTRIES 条，附相对路径 log_ref；tasks 内联 ≤ STATUS_COMPACT_MAX_TASKS 条并附 tasks_total；末尾调用 fit_to_budget(...) 兜底。
5. python scripts/export_ide_schemas.py --write 刷新快照；若 dev_tasks_status schema 越过 1000B 或余量 < 50B，在同一任务内精简参数描述取回字节，不得放行漂移。
6. 在 test_observability.py 落地批量门禁与 full 超集不变量（B2/D-03 修正断言）；适配 test_dual_mode_runtime_switch.py。fixture 构造使用 tmp_path_factory，禁止污染工作区 (D-14)。

#### 【防御与边缘校验】
- E1 判别器永不剔除：compact 下 harness_next_action["action"] 恒存在。
- E2 运行期有界：构造 40 任务工作区调用 compact，断言实测 ≤ RESPONSE_BUDGET_BYTES["dev_tasks_status"]，且 truncated_sections 非空；软目标 1024B 用 pytest warning 语义。
- E3 full 超集不变量（D-03 修正）：COMPACT_ONLY_KEYS = frozenset({"truncated_sections", "tasks_total", "entitlements_hash", "last_hook_log_entries_compact"}); 断言 set(full) - set(compact) <= {"session_role_contract", "governance_scope", "hook_log"}; set(compact) - set(full) == COMPACT_ONLY_KEYS; full["tasks"][:len(compact["tasks"])] == compact["tasks"]; len(full["tasks"]) == compact["tasks_total"]。
- E4 日志读有界与 fail-open：桩化超大日志（>10× tail）与包含跨边界 CJK/多字节 UTF-8 坏字节，断言读取字节数 ≤ HOOK_LOG_TAIL_BYTES、首行破损丢弃、异常路径返回 [] 且 dev_tasks_status 不抛。
- E5 依赖预检与升级：若白名单外测试/模块依赖被折叠的键，必须 dev_tasks_escalate 扩白名单，严禁越界修改。
- 回滚锚点：git checkout -- plugins/quench-dev-tasks/server/server.py plugins/quench-dev-tasks/server/autopilot_harness.py docs/architecture/ide_tool_schemas.json plugins/quench-dev-tasks/server/tests/test_observability.py plugins/quench-dev-tasks/server/tests/test_dual_mode_runtime_switch.py

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_observability.py plugins/quench-dev-tasks/server/tests/test_dual_mode_runtime_switch.py -v
python -m pytest -m tier1_fast -q
python scripts/export_ide_schemas.py --check
python scripts/check_prompt_surface.py
python scripts/check_no_api_bypass.py
```

---

### 任务 33.3 ✔️ 已完成 — 交互工具冻结词表对账、回显剥离与全表面预算回归

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tool_surface_constants.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] docs/architecture/ide_tool_schemas.json
[NEW] plugins/quench-dev-tasks/server/tests/test_tool_response_slim.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_tools.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_spec_refine.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_eradicate_legacy_handoff_interrupts.py
```
> *(注：tool_surface_constants.py 仅允许扩展 CHECKOUT_REASON_CODES，不得改动任何其他常量)*

#### 【缺陷根因与修改目标】
```
【缺陷根因】CHECKOUT_REASON_CODES 在 33.0 冻结为 3 码，但未与 dev_tasks_checkout 真实分支对账；refine_spec 剥离正文回显可能击穿既有断言，而 33.3 缺 33.2 E5 式预检/升级条款。
【修改目标】先只读枚举 checkout 场景分支与 refine_spec 回显依赖，判定冻结词表是否完备；complete 后 compact 载荷经 fit_to_budget 收敛；建立全 16 工具全表面预算回归。
```

#### 【目标签名与类型契约】
```
class CheckoutResponseCompact(TypedDict, total=False):
    task_id: str
    status: str
    reason_code: str # CHECKOUT_REASON_CODES
    harness_next_action: dict[str, Any]

class RefineSpecResponseCompact(TypedDict, total=False):
    ok: bool
    task_id: str
    path: str
    content_sha256: str
    bytes_written: int
    validation: dict[str, Any]
```

#### 【分步改造指引】
1. 对账预检（只读）：grep -n "reason_code\|CHECKOUT_REASON_CODES" -A3 plugins/quench-dev-tasks/server/server.py，列出 checkout 所有返回分支；若分支集合 ⊄ CHECKOUT_REASON_CODES，立即 dev_tasks_escalate 请求回改 33.0R 的 frozenset，严禁就地私增码值。
2. 同法核查 test_server_tools.py 与 cli.py 是否消费 refine_spec 的正文回显；需要时升级白名单后同步断言。
3. checkout 场景 3 返回 CheckoutResponseCompact（reason_code ∈ CHECKOUT_REASON_CODES + harness_next_action），经 fit_to_budget 收敛至 800B。
4. refine_spec 返回 RefineSpecResponseCompact（path、content_sha256、bytes_written、validation 摘要），经 fit_to_budget 收敛至 600B。
5. test_tool_response_slim.py 加载 fixtures/response_payloads.py，对全 16 工具断言 fit_to_budget 输出 ≤ 对应预算（终态 poll 豁免），并对 dev_tasks_export_handoff_card 单独验证长卡片场景。
6. python scripts/export_ide_schemas.py --write 刷新快照。

#### 【防御与边缘校验】
- E1 词表封闭：任何响应中的 reason_code 必须 ∈ CHECKOUT_REASON_CODES，测试遍历全码值 + 断言无词表外值。
- E2 回显剥离等价性：content_sha256 与写入磁盘内容重算哈希一致，且响应体不含正文片段。
- E3 全表面预算：16 工具逐一断言 ≤ 预算；超载变体（40 任务 / 长卡片）经钳制后仍达标；终态 poll 显式豁免。
- E4 白名单纪律：所有越界依赖一律升级，不得就地修改。
- 回滚锚点：git checkout -- plugins/quench-dev-tasks/server/server.py docs/architecture/ide_tool_schemas.json plugins/quench-dev-tasks/server/tests/test_server_tools.py && rm -f plugins/quench-dev-tasks/server/tests/test_tool_response_slim.py

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_tool_response_slim.py plugins/quench-dev-tasks/server/tests/test_server_tools.py -v
python -m pytest -m tier1_fast -q
python scripts/check_test_duration_baselines.py
python scripts/export_ide_schemas.py --check
python scripts/check_prompt_surface.py
```

---

