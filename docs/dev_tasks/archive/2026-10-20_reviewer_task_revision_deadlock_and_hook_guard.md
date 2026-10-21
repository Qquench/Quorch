# 2026-10-20_reviewer_task_revision_deadlock_and_hook_guard Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

---

### 任务 1.1 ✔️ 已完成 — 修复 Hook 任务状态误杀：header 精准提取 + 多维差分 + 入口穷举（INV-2 加固）

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/state_machine.py
[NEW] plugins/quench-dev-tasks/server/task_status.py
[NEW] plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py
[MODIFY] plugins/quench-dev-tasks/server/tests/conftest.py
[MODIFY] docs/architecture/README.md
```

#### 【缺陷根因与修改目标】
```
1. 缺陷根因：
   - extract_statuses() 对全文执行 STATUS_PATTERN.findall 全局盲扫，任务单 Header 的 Guidance 引用块（> - ... update its status to 🔨 执行中）及代码围栏内示例被误采；
   - 状态正则在 file_scope_guard.py 与 state_machine.py 间双源漂移，解析器与守卫定义不一致；
   - 缺乏旧/新差分机制，导致正文与 DoD 修订遭 100% 误杀；
   - 审查新发现缺口：差分未覆盖任务删除/截断/重命名/重复 ID；delete_file 会误删全可编辑态单据；脏文件自锁死（已有重复 ID 无法就地修复）；未知 mutating 工具未穷举；异常兜底粗糙。
2. 修改目标：
   - 抽离 task_status.py SSOT 模块统一定义状态常量与标题正则（以现有磁盘代码真值 STATUS_PENDING/CONFIRMED/IN_PROGRESS/COMPLETED/SKIPPED/REWORK 为准，未识别状态采用 allow+WARN 的 STATUS_UNKNOWN 容错策略），实现 fence/blockquote-aware 精准提取；
   - 在 file_scope_guard.py 中建立多维差分机制，封堵状态走私、非法状态流转、删除非可编辑任务、截断清空与新增重复 ID（采用重复集差分 new_duplicates - old_duplicates != set() 避免脏文件自锁死）；
   - 对 docs/dev_tasks/**/*.md 下的 delete_file 操作一律触发 ask 审批并引导使用 dev_tasks_confirm(action='revoke')；
   - 穷举变更类工具入口（MUTATING_TOOLS 白名单，未知 mutating 工具默认 ask）；
   - 细化异常策略：读旧文件异常 fail-open (allow + EXCEPTION)，新内容畸形标题定向 fail-closed (ask)；
   - 在 conftest.py 注册测试文件入 TIER1_TARGET_REL_FILES，并在 docs/architecture/README.md 同步模块拓扑。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/server/task_status.py
STATUS_PENDING: Final[str] = "⬜ 待确认"
STATUS_CONFIRMED: Final[str] = "✅ 已确认"
STATUS_IN_PROGRESS: Final[str] = "🔨 执行中"
STATUS_COMPLETED: Final[str] = "✔️ 已完成"
STATUS_SKIPPED: Final[str] = "⏭️ 跳过"
STATUS_REWORK: Final[str] = "🔄 需返工"

ALL_STATUSES: Final[tuple[str, ...]] = (
    STATUS_PENDING, STATUS_CONFIRMED, STATUS_IN_PROGRESS,
    STATUS_COMPLETED, STATUS_SKIPPED, STATUS_REWORK,
)

EMOJI_STATUS_OPTIONS: Final[tuple[str, ...]]
STATUS_REGEX_PART: Final[str]
TASK_HEADER_PATTERN: Final[Pattern[str]]
TASK_FILE_RELATIVE_DIR: Final[str] = "docs/dev_tasks"
STATUS_UNKNOWN: Final[str] = "?? UNKNOWN"  # 纯 ASCII 哨兵，严禁取任何 emoji

@dataclass(frozen=True)
class TaskHeaderScan:
    statuses_ordered: tuple[tuple[str, str], ...]   # 保序，(task_id, normalized_status)
    occurrence_counts: Mapping[str, int]            # task_id -> 出现次数（重数）
    malformed_ids: frozenset[str]

    @property
    def statuses(self) -> Mapping[str, str]:        # last-wins 视图（向后兼容 A1）
        return dict(self.statuses_ordered)
    @property
    def duplicates(self) -> frozenset[str]:
        return frozenset(t for t, c in self.occurrence_counts.items() if c > 1)

def normalize_status(raw: str) -> str: ...
def extract_header_task_statuses(content: str) -> TaskHeaderScan: ...
def is_task_file(rel_path: str) -> bool: ...

# plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
MUTATING_TOOLS: Final[frozenset[str]] = frozenset({
    "write_to_file", "replace_file_content", "multi_replace_file_content",
    "insert_content", "delete_file",
})
READ_ONLY_TOOLS: Final[frozenset[str]] = frozenset({
    "read_file", "view_file", "grep_search", "list_dir",
})
def build_post_image(tool_name: str, args: dict, old_content: str) -> Optional[str]: ...
def diff_task_statuses(old: TaskHeaderScan, new: TaskHeaderScan) -> List[dict]: ...
def check_task_status_guard(target_file: str, tool_name: str, args: dict) -> Optional[dict]: ...
```

#### 【分步改造指引】
1. 新建 `task_status.py`（轻量 SSOT 模块，零重依赖）：以磁盘 `state_machine.py` 既有物理真值迁移 6 种标准状态常量（STATUS_PENDING/CONFIRMED/IN_PROGRESS/COMPLETED/SKIPPED/REWORK，注明确认磁盘无 STATUS_REVOKED 常量，因 revoke 动作流转回 STATUS_PENDING）；`STATUS_UNKNOWN = "?? UNKNOWN"` 采用纯 ASCII 哨兵；`EMOJI_STATUS_OPTIONS` 按长度降序 re.escape 拼接；实现 `normalize_status`（处理 VS16/全半角/空格，未识别状态作为 STATUS_UNKNOWN 返回不抛错）；实现 `extract_header_task_statuses` 围栏状态机（前置剪枝判 `> ` 与 fence，识别 ``` 与 ~~~ 长度匹配与 ≤3 空格缩进，围栏内跳过，`>` 引用块跳过，仅匹配整行 `^###` 标题行，按全序规则解析标题行并产出 `TaskHeaderScan`）；实现跨模块共享的路径归一化判定 `is_task_file`；严禁导入 `state_machine`/`manifest`/`filelock`/`fastmcp`/`yaml`；
2. 重构 `state_machine.py`：改为从 `task_status.py` 导入状态常量与标题正则，`__all__` 保留全部原有导出名与别名，彻底清除 `state_machine.py` 源码内所有状态 emoji 字面量，消除双源漂移；
3. 重构 `file_scope_guard.py`：
   - 增加 `MUTATING_TOOLS` 与 `READ_ONLY_TOOLS` 白名单；`build_post_image` 遇到无法确定 post-image 分支返回 `None` 进而定向 fail-closed 触发 ask(`undeterminable_post_image`)；`delete_file` 命中任务目录直接定向 ask 阻断并提示规范撤单指令；
   - 严格落地全序判定表与多重集（multiset）差分规则：
     * 标题行全序解析：①行首非 `^###` 忽略；②`^###` 且无任务前缀忽略；③前缀命中但 id 缺失 -> `malformed_ids`；④id 存在但状态为空 -> `malformed_ids`；⑤id 与状态均存在但状态 ∉ ALL_STATUSES -> 记 `STATUS_UNKNOWN`；⑥同 id 出现多次记入 `statuses_ordered` 与 `occurrence_counts`；
     * 差分多重集判定：新增重复块（`new.occurrence_counts[id] > old.occurrence_counts.get(id, 0)`）-> ask；非法状态流转（Counter(new.statuses_ordered) 与 Counter(old.statuses_ordered) 存在非 UNKNOWN 状态增加）-> ask；存量重复修复（重数下降）-> allow + WARN；old 为 UNKNOWN、new 为已知状态（或反向）-> ask；old/new 均为 UNKNOWN 且 raw token 相同 -> allow；无旧文件且含非待确认状态 -> ask；新引入 malformed_ids -> ask；旧文件读取/解析异常 -> allow + `EXCEPTION` 日志；未知 mutating 工具且命中任务单路径 -> ask；只读工具直接豁免；
4. 注册与拓扑同步：在 `plugins/quench-dev-tasks/server/tests/conftest.py` 将 `test_file_scope_guard_status.py` 纳入 `TIER1_TARGET_REL_FILES`；在 `docs/architecture/README.md` 补齐 `task_status.py` 模块拓扑；
5. 编写测试套件 `test_file_scope_guard_status.py` 并执行 DoD 门禁（断言清单见下表）。

#### 【防御与边缘校验】
- 行为断言与真值核对：
  * Header 指南引用块含状态 Emoji 覆盖写 -> allow
  * 围栏内（```, ~~~, 未闭合围栏）含状态 Emoji -> allow
  * 待确认任务正文/步骤/DoD 命令修订 -> allow
  * 标题行 待确认 -> 执行中 篡改 -> ask（reason 含 dev_tasks_checkout 指引）
  * 新建单据包含 已确认/执行中 状态 -> ask（状态走私阻断）
  * 删除已有 执行中/已完成 任务块 -> ask（保护审计台账）
  * delete_file 目标任务单文件 -> ask（引导使用 dev_tasks_confirm revoke）
  * 清空/截断文件 -> ask
  * 新引入重复 task_id（含重数增加 2->3 次，F1） -> ask；存量重复修复重数减少时不扩大 -> allow + WARN（避免自锁死）
  * 重复块首部状态篡改（F1 缺口 A） -> ask（Counter 多重集拦截）
  * 缺 id 或缺状态标题行（F2） -> 归入 malformed_ids -> ask
  * insert_content 伪造标题行 -> ask；正文追加 -> allow
  * build_post_image 不可确定落盘时 -> ask(`undeterminable_post_image`)；只读工具直接放行（F3）
  * 未知 mutating 工具操作任务单 -> ask
  * 读旧文件 OSError -> allow + 记录 EXCEPTION 日志（fail-open）
  * normalize_status 兼容 VS16、全半角空格与变体；未识别状态以纯 ASCII 哨兵 "?? UNKNOWN" 记入
  * SSOT 无漂移：全 server/ 源码经 AST 扫描（排除 docstring 与 task_status 自身）零状态 emoji 字符串常量（F5）
  * Hook 轻量导入：子进程导入 file_scope_guard 后断言 filelock、manifest、fastmcp、yaml 均不在 sys.modules 中（F4）
  * 纯函数性能预算：200KB 合成内容 extract_header_task_statuses 单次耗时 < 15ms；端到端 check_task_status_guard < 25ms（F4）

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_file_scope_guard_status.py -q
python -m pytest plugins/quench-dev-tasks/server/tests/test_state_machine.py -q
python -m pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q
python -m pytest plugins/quench-dev-tasks/server/tests/ -m tier1_fast -q
```

---

### 任务 1.2 ✔️ 已完成 — 补齐 MCP 原地修订闭环：write_task_file_guarded 受控原语 + propose(mode) + refine_spec(persist) 去幽灵

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[NEW] plugins/quench-dev-tasks/server/task_writer.py
[NEW] plugins/quench-dev-tasks/server/tests/test_task_file_write_guarded.py
[MODIFY] docs/architecture/ide_tool_schemas.json
[MODIFY] dev_tasks_mcp_specification.md
[MODIFY] docs/architecture/README.md
```

#### 【缺陷根因与修改目标】
```
1. 缺陷根因：
   - dev_tasks_refine_spec 声明了 persist 参数但源码完全不写盘（幽灵参数）；
   - dev_tasks_propose 遇已存在文件无条件 append 追加，重复调用产生脏重复任务；
   - 服务端缺乏受控原地原子覆写原语，导致 Agent 面对审查建议时陷入死锁，被迫删单重写；
   - 审查新发现风险：写入原语若无“新增任务状态固定”，会成为绕过 pre-confirm 审计门禁的走私通道；若采用双锁（Markdown + Manifest）存在潜在锁序超时；若无偏移切片 splice 机制，非可编辑块字节一致性不可达；参数变更未纳入 IDE schema 快照将导致 CI 拦截。
2. 修改目标：
   - 实现 task_writer.py::write_task_file_guarded 受控原子写入原语（前置依赖任务 1.1）：封堵新任务状态走私、严格保持已有任务状态不变、可编辑态范围约束（非可编辑块基于 start/end 偏移区间 splice 逐字复用）、采用方案 C（仅持 Markdown 写锁，manifest 乐观校验）、同分区 fsync 原子替换；
   - 扩展 dev_tasks_propose(mode="append"|"overwrite"|"upsert")，支持幂等覆写与去重，mode 非枚举值 fail-closed；
   - 落地 dev_tasks_refine_spec(persist=True) 写盘能力，persist=True 且 task_file=None 显式抛 PersistTargetRequiredError，异步加锁使用 asyncio.to_thread 保护事件循环；
   - 同步更新 ide_tool_schemas.json 快照、dev_tasks_mcp_specification.md 协议 SSOT 与 docs/architecture/README.md，坚守 16 个工具面预算不变。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/server/task_writer.py
@dataclass(frozen=True)
class RawTaskBlock:
    task_id: str
    status: str
    start_offset: int
    end_offset: int
    raw_text: str

@dataclass(frozen=True)
class TaskDocument:
    preamble: str
    blocks: tuple[RawTaskBlock, ...]
    epilogue: str

def split_task_document(text: str) -> TaskDocument: ...
def compose_task_document(doc: TaskDocument, replaced: Mapping[str, str], appended: Sequence[str]) -> str: ...

EDITABLE_STATES: Final[frozenset[str]] = frozenset({STATUS_PENDING, STATUS_REWORK})

class InvalidTransitionError(RuntimeError): ...
class NonEditableTaskMutatedError(RuntimeError): ...
class NonEditableTaskMissingError(RuntimeError): ...
class DuplicateTaskIdError(ValueError): ...
class StatusSmugglingError(RuntimeError): ...
class StatusManifestMismatchError(RuntimeError): ...
class TaskFileLockTimeoutError(TimeoutError): ...
class PersistTargetRequiredError(ValueError): ...
class TaskNotFoundError(LookupError): ...

def write_task_file_guarded(
    workspace_root: str,
    task_file_path: str,
    tasks_to_write: list[dict],
    mode: Literal["append", "overwrite", "upsert"] = "append",
    *,
    lock_timeout_s: float = 5.0,
    manifest_snapshot: Optional[Mapping[str, str]] = None,
) -> dict: ...  # {"ok": bool, "mode": str, "task_file": str, "written": list, "skipped": list, "reason": Optional[str]}

# plugins/quench-dev-tasks/server/server.py
@mcp.tool()
def dev_tasks_propose(
    workspace_root: str,
    task_file_name: str,
    tasks: list[dict],
    mode: Literal["append", "overwrite", "upsert"] = "append",
) -> dict: ...

@mcp.tool()
async def dev_tasks_refine_spec(
    workspace_root: str,
    draft_task: dict,
    context_files: Optional[list[str]] = None,
    max_hops: int = 1,
    persist: bool = False,
    task_file: Optional[str] = None,
) -> dict: ...
```

#### 【分步改造指引】
1. 前置核验：必须确认任务 1.1 已完成并成功导出 `task_status.py`，严禁颠倒执行顺序；
2. 实现 `task_writer.py` 文档分段与受控原子写入原语：
   - 实现 `split_task_document` 与 `compose_task_document`：记录各任务块的字符偏移区间 `(start_offset, end_offset)`，严格遵守分区不变式 `preamble + Σblock.raw_text + epilogue == original_text`（块起始于 `###` 行首，终止于下一块 `###` 行首，`\n---\n` 归属块尾）；仅重新渲染新增/变更块，非可编辑块与 preamble/epilogue 按原始偏移倒序切片 splice 逐字复用，保留原文件的 CRLF/BOM 与尾随空白；
   - 实现 `write_task_file_guarded`：强制 `path_guard.assert_dir_contained(workspace_root, "docs/dev_tasks")` 并核验 `.md` 后缀；`manifest_snapshot` 必须在获取 Markdown 文件锁之前读取，锁内仅做比较杜绝反向锁死；仅持 Markdown 任务单独占锁 `<task_file>.lock`（超时 5.0s 抛 `TaskFileLockTimeoutError`）；锁内执行五道不变量校验（新增任务状态必须 ∈ EDITABLE_STATES 否则抛 `StatusSmugglingError`；已有任务状态不变否则抛 `InvalidTransitionError`；非可编辑块规范化文本与原始切片双重保护；重复 ID 抛 `DuplicateTaskIdError`；`validate_task_schema` 仅校验新增/变更块）；对 manifest 仅校验本次涉及任务 ID；通过同分区 `tempfile.mkstemp` + `os.fsync` + 保留原 mode + `os.replace`（Windows 重试 3 次）原子落盘；返回结构化契约字典；
   - 模式语义：`append` 遇重复 ID 显式抛 `DuplicateTaskIdError`（指引改用 `upsert`）；`upsert` 命中可编辑块则替换，命中非可编辑块则进 `skipped(reason="non_editable")` 且不抛错；未命中则追加；`overwrite` 全量校验非可编辑块必须完整存在并逐字保留（缺失即 `NonEditableTaskMissingError`），严禁借 overwrite 清空任务块逃避审计台账；
3. 改造 `server.py::dev_tasks_propose`：增加 `mode` 参数，非枚举值 fail-closed，委托至 `write_task_file_guarded`，保持工具清单与总数 16 不变；异常在 server 边界翻译为统一结构化失败契约；
4. 改造 `server.py::dev_tasks_refine_spec`：增加 `task_file: Optional[str] = None` 参数；当 `persist=True` 且 `task_file is None` 时抛出 `PersistTargetRequiredError`（严禁静默不写盘）；`draft_task["id"]` 不存在抛 `TaskNotFoundError`；同步写入必须通过 `await asyncio.to_thread(write_task_file_guarded, ...)` 异步化，绝不阻塞 MCP 事件循环与 long-polling；
5. 同步协议与架构快照并执行 DoD：更新 `dev_tasks_mcp_specification.md` 三处参数契约；在 `docs/architecture/README.md` 登记 `task_writer.py`；运行 `python scripts/export_ide_schemas.py --write` 重新导出 `docs/architecture/ide_tool_schemas.json`，再通过 `--check` 门禁；编写测试套件 `test_task_file_write_guarded.py` 并全量验证。

#### 【防御与边缘校验】
- 行为断言与契约核对：
  * 无损往返恒等性：任意合法任务单 split + compose roundtrip 字节完全恒等（test_split_compose_roundtrip_identity, N3）
  * append 新增待确认任务成功，preamble/epilogue 逐字不变
  * append 重复 task_id 显式抛 DuplicateTaskIdError，文件 hash 保持原样
  * overwrite 写入携带 已确认 状态的新任务抛 StatusSmugglingError 阻断（BLK-1）
  * overwrite 篡改已有任务状态抛 InvalidTransitionError 阻断
  * overwrite 篡改已确认任务块正文抛 NonEditableTaskMutatedError；未篡改时规范化文本与原始切片均完全相等
  * overwrite 遗漏已有非可编辑任务抛 NonEditableTaskMissingError 阻断
  * upsert 仅更新指定可编辑任务块，其余任务块原始切片完全相等
  * refine_spec(persist=True, task_file=None) 抛 PersistTargetRequiredError，不发生写盘
  * refine_spec(persist=True) 仅更新目标任务块且写盘通过 asyncio.to_thread 非阻塞运行（持锁写入期间并发 ticker 持续推进）
  * manifest 不一致抛 StatusManifestMismatchError；manifest 临时不可用时记录 WARN 并允许写入
  * 写入失败时原子性保证：monkeypatch os.replace 抛错后原文件 sha256 完全不变
  * 保留原文件的 CRLF 换行符与 UTF-8 BOM 标记
  * 越界路径抛 PathTraversalError 阻断
  * 锁超时抛 TaskFileLockTimeoutError，避免死锁
  * 往返一致性：writer 产物经 1.1 的 check_task_status_guard 校验直接返回 allow
  * 工具面守恒：TOOL_COUNT 保持 16 不变，ide_tool_schemas.json diff 仅包含 mode/persist/task_file 参数

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_task_file_write_guarded.py -q
python -m pytest plugins/quench-dev-tasks/server/tests/test_server_tools.py -q
python -m pytest plugins/quench-dev-tasks/server/tests/test_state_machine.py -q
python -m pytest plugins/quench-dev-tasks/server/tests/ -m tier1_fast -q
python scripts/export_ide_schemas.py --check
```
