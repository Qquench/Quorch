# 2026-10-19_toolchain_metadata_ssot_and_slimming Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - All initial tasks start in Pending state

- **Created Date / 创建日期**：2026-10-19

---

## 任务依赖与推行顺序 / Task Dependencies & Execution Order

- **执行有向链 (I-4)**：`1.1 (常量源与导出器架构下沉) → 1.2 (AST提取器与契约收敛) → {1.3 (Skill文档瘦身) ∥ 1.4 (规格默认值运行时锚定) ∥ 1.5 (快照漂移门禁)} → 1.6 (规格标记块容错测试) → 1.7 (单例哨兵物理单测) → 1.8 (CLI沙箱与异常加固) → 1.9 (全链路分级验收与资产盘点)`
- **串行执行约束**：严格遵循 INV-1 单核串行推进。任务 1.2 须在 1.1 落地常量模块后方可执行；任务 1.3/1.4/1.5 依赖 1.1 的快照与门禁基础设施；任务 1.6/1.7/1.8 作为防御与健壮性加固层；任务 1.9 作为最终闭环门禁。

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成（终审修订版 · 原位替换）— 工具面常量源 + 派生快照 + 原子幂等导出

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[NEW]    plugins/quench-dev-tasks/server/tool_surface_constants.py
[NEW]    plugins/quench-dev-tasks/server/ide_schema_export.py
[MODIFY] plugins/quench-dev-tasks/server/path_guard.py
[NEW]    scripts/export_ide_schemas.py
[NEW]    scripts/_introspect_schemas_child.py
[NEW]    plugins/quench-dev-tasks/server/tests/test_ide_schema_export.py
[NEW]    plugins/quench-dev-tasks/server/tests/test_export_ide_schemas_cli.py
[NEW]    docs/architecture/ide_tool_schemas.json
[MODIFY] plugins/quench-dev-tasks/server/tests/conftest.py
[MODIFY] docs/architecture/README.md
[MODIFY] dev_tasks_mcp_specification.md
```

#### 【缺陷根因与修改目标】
```
R-01 换行断言依赖四层转义（Markdown→shell→python -c→regex），任一层失配即退化为恒真/恒假，P0-1 同类残留。改为零转义字节构造，并以产物自证取代文档自检。
R-02 _MissingSentinel.__reduce__ 返回构造器而非工厂，反序列化产生新实例，is MISSING 与 __deepcopy__ 身份失效。
R-03 mkstemp 未锚定 dir= → 跨设备 EXDEV；0600 权限经 os.replace 成为产物权限；异常路径残留 .tmp。
R-04 canonicalize 的 json.dumps 参数未钉死；_VOLATILE_SCHEMA_KEYS 若仅顶层剔除则无法清除参数级 title；Windows cp936 会击穿 UTF-8 写入。
R-05 探针仅重定向 sys.stdout 对象层，fd 1 仍可被 StreamHandler / C 扩展 / atexit 写者污染，信封完整性无物理保证。
R-06 ide_schema_export.main(argv) 无 schemas 来源，只能反向依赖 scripts/ 或自行 spawn，依赖倒置抵消 B2 收益。
R-07 --check 的 DoD 断言 returncode ∈ (0,1)，允许"写完即漂移"假绿。
R-08 EXPECTED_TOOL_NAMES 未成为 validate_schema_doc 的强制点，哨兵仅停留在测试层。
R-09 移除 from fastmcp import Context 后无悬空引用验证。
R-10 --write --cache-dir 无路径包含约束，可越出仓库根。
R-11 退出码语义未完备（缺失 / 损坏 / 不可读 / 漂移未区分）。
R-13 1.1 内联 AST 扫描器与 1.2 提取器重复，违反单点常量。
```

#### 【目标签名与类型契约】
```python
# tool_surface_constants.py
EXPECTED_TOOL_NAMES: Final[frozenset[str]]           # 完整性哨兵，16 项
TOOL_COUNT: Final[int] = len(EXPECTED_TOOL_NAMES)
TOOL_ALLOWS_CTX: Final[frozenset[str]] = frozenset()
CTX_PARAM_ALIASES: Final[frozenset[str]] = frozenset({"ctx"})
SCHEMA_META_KEY: Final[str] = "_meta"
SNAPSHOT_SCHEMA_VERSION: Final[int] = 1
META_ALLOWED_KEYS: Final[frozenset[str]] = frozenset({"schema_version"})

def _missing_singleton() -> "_MissingSentinel": ...
class _MissingSentinel:
    __slots__ = ()
    def __repr__(self) -> str: return "<MISSING>"
    def __reduce__(self) -> tuple[Callable[[], "_MissingSentinel"], tuple[()]]:
        return (_missing_singleton, ())          # 工厂，保持单例身份
    def __copy__(self) -> "_MissingSentinel": return self
    def __deepcopy__(self, memo: dict[int, Any]) -> "_MissingSentinel": return self
    def __bool__(self) -> bool:
        raise TypeError("MISSING 禁止用于布尔上下文；请使用 has_default()")
MISSING: Final[_MissingSentinel] = _MissingSentinel()

def get_default(snapshot: dict[str, Any], tool: str, param: str) -> Any: ...
def has_default(snapshot: dict[str, Any], tool: str, param: str) -> bool: ...
def iter_param_names(snapshot: dict[str, Any], tool: str) -> frozenset[str]: ...

# ide_schema_export.py —— 模块级禁止 import server / fastmcp / subprocess
CR: Final[bytes] = bytes([13])
LF: Final[bytes] = bytes([10])
ENVELOPE_BEGIN: Final[str] = "@@QUENCH-SCHEMA-BEGIN@@"
ENVELOPE_END: Final[str] = "@@QUENCH-SCHEMA-END@@"
ENVELOPE_MAX_BYTES: Final[int] = 8 * 1024 * 1024
_VOLATILE_SCHEMA_KEYS: Final[frozenset[str]] = frozenset({"$schema", "title"})  # 递归剔除
SNAPSHOT_FILENAME: Final[str] = "ide_tool_schemas.json"
EXIT_OK: Final[int] = 0
EXIT_DRIFT: Final[int] = 1
EXIT_INVALID: Final[int] = 2

class SchemaExportError(Exception): ...
class SentinelLeakError(SchemaExportError): ...
class EnvelopeError(SchemaExportError): ...

def assert_no_sentinel_leak(obj: Any) -> None: ...
def validate_schema_doc(schemas: dict[str, Any]) -> None:
    """键集 == EXPECTED_TOOL_NAMES | {_meta}；_meta == {"schema_version": 1}；
    默认值必须 JSON 可序列化（allow_nan=False）；无下划线前缀工具名。"""
def canonicalize_schemas(schemas: dict[str, Any]) -> str: ...   # 唯一序列化入口
def parse_envelope(stdout: str) -> dict[str, Any]: ...         # 唯一 begin/end，长度上限
def export_ide_schemas(dest_dir: Path, schemas: dict[str, Any], *, dry_run: bool = False) -> list[str]: ...
def run_cli(argv: list[str] | None = None, *, introspect: SchemaProvider) -> int: ...
```

#### 【分步改造指引】
1. `server.py`：物理移除 `from fastmcp import Context`；以 AST 断言全文件 `Name/Attribute` 中 `Context` 零出现；子进程 `import server` 退出码 0 且 `stdout == b""`；
2. 新建 `tool_surface_constants.py`：常量 + 工厂式哨兵（`__reduce__`/`__copy__`/`__deepcopy__`/`__bool__` 抛错）+ 三态访问器；
3. 新建 `ide_schema_export.py`：`assert_no_sentinel_leak` → `validate_schema_doc`（含工具名哨兵 R-08）→ `canonicalize_schemas`（`ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False` + 单个尾 LF；递归剔除 `_VOLATILE_SCHEMA_KEYS`）→ `parse_envelope`（唯一 begin/end、`ENVELOPE_MAX_BYTES` 上限）→ `_atomic_write`（`dir=dest_dir`、`chmod(0o644)` 或保留既有 mode、`finally` 清理 tmp）→ `run_cli(argv, *, introspect)`；
4. `path_guard.py` 新增外部目录安全函数（逐段 `os.lstat` + Reparse Point 跨平台拒绝），供 `_atomic_write` 的 `dest_dir` 包含校验使用；
5. 新建 `scripts/_introspect_schemas_child.py`：**先** `os.dup(1)` 持私有 fd → `os.dup2(2,1)` → `sys.stdout = sys.stderr` → 再 `import server` → 构建 doc → `canonicalize_schemas` → 写私有 fd → `flush` → `os._exit(0)`；
6. 新建 `scripts/export_ide_schemas.py` 薄壳：`_bootstrap_sys_path()` → `argparse(--write/--check/--cache-dir)` → `Popen([sys.executable,"-P",child], stdin=DEVNULL, cwd=_REPO_ROOT, env=净化)` → `communicate(timeout=30)`（超时 `kill()` + `communicate()`）→ `parse_envelope` → `run_cli(..., introspect=...)`；净化 env 须含 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` 且剔除 `PYTHONPATH`；
7. 退出码钉死：`0` 一致 / `1` 漂移（含目标文件缺失）/ `2` 目录缺失、不可读、损坏 JSON、结构或哨兵校验失败；`--check` 全程零写入、零 `mkdir`；`export_ide_schemas` 仅在 `not dry_run` 时建目录；`--write` 的 `dest_dir` 必须解析后位于 `_REPO_ROOT` 内，否则 exit 2；
8. 新建 `test_ide_schema_export.py`（Tier-1，纯函数）：三态访问器（含 `{'default': None}` 与 `{}` 的区分）、pickle/copy 单例身份、哨兵泄漏、信封四态（缺 begin / 缺 end / 多 begin / 内有杂质）、`_meta` 白名单、递归易变键剔除、两次 canonicalize 字节全等、`validate_schema_doc` 对工具名哨兵的强制；
9. 新建 `test_export_ide_schemas_cli.py`（重型，不进 Tier-1）：`--write` 后读回逐字节相等；`CR/LF = bytes([13])/bytes([10])` 三重断言；`--check` 后 `returncode == 0`；手工篡改后 `--check == 1`；损坏 JSON `== 2`；`--check --cache-dir <不存在>` `== 2` 且事后路径不存在；非仓库根 cwd 调用验证默认锚点；产物 `stat.S_IMODE == 0o644` 且无残留 `*.tmp`；
10. `python scripts/export_ide_schemas.py --write` 落地 `docs/architecture/ide_tool_schemas.json`；
11. 以快照实测值校正 README §3.3 与 `dev_tasks_mcp_specification.md` 中的 `raw_text` / `wait_max_s` 默认值字面量；表述统一为「代码为权威 / JSON 为派生证据镜像 / 文档不复述字面量」；§2 的 "16" 改为指向 `tool_surface_constants.TOOL_COUNT`（R-20）；§5 登记 `export_ide_schemas.py`、`ide_schema_export.py`、`tool_surface_constants.py` 并补齐调用边；
12. `conftest.py` 的 `TIER1_TARGET_REL_FILES` 仅追加 `test_ide_schema_export.py`。

#### 【防御与边缘校验】
- **零转义红线**：任何 CRLF/换行断言禁止写字面 `\r` `\n` 转义，一律 `bytes([13])` / `bytes([10])`；
- **单例身份**：`pickle.loads(pickle.dumps(MISSING)) is MISSING`、`copy.deepcopy(MISSING) is MISSING`；
- **原子落盘**：`dir=dest_dir`、mode 保留/0o644、异常 `finally` 清 tmp、目录 fsync 在 Windows 静默忽略但记录 debug 原因；
- **信道纯净**：fd 级 `dup2` + 私有出口 fd + `os._exit(0)`；信封唯一 begin/end 且 `≤ ENVELOPE_MAX_BYTES`；`env` 强制 UTF-8；
- **哨兵物理化**：`validate_schema_doc` 强制 `EXPECTED_TOOL_NAMES`，新增工具未更新常量即 exit 2；
- **只读证明**：`--check` 以「路径事后不存在」与「产物 sha256 不变」双重物理证据；
- **Tier-1 隔离**：`ide_schema_export` 导入后断言 `"fastmcp" not in sys.modules and "yaml" not in sys.modules`；重型 CLI 用例不入 `TIER1_TARGET_REL_FILES`；
- **Tier-2 包络**：CLI 用例标记 `@pytest.mark.slow`，防 1.30× panic 假红；
- **边界**：`export_ide_schemas` 返回列表长度恒 ≤ 1。

#### 【DoD 验证命令】
```bash
python -c "import sys,pickle,copy;sys.path.insert(0,'plugins/quench-dev-tasks/server');import tool_surface_constants as c;assert pickle.loads(pickle.dumps(c.MISSING)) is c.MISSING;assert copy.deepcopy(c.MISSING) is c.MISSING;d={'t':{'p':{'default':None}}};assert c.has_default(d,'t','p') is True;assert c.get_default(d,'t','p') is None;assert c.has_default({'t':{'p':{}}},'t','p') is False;assert c.get_default({'t':{'p':{}}},'t','p') is c.MISSING"
python -c "import sys;sys.path.insert(0,'plugins/quench-dev-tasks/server');import fastmcp" 2>/dev/null; python -c "import sys;sys.path.insert(0,'plugins/quench-dev-tasks/server');import ide_schema_export;assert 'fastmcp' not in sys.modules;assert 'yaml' not in sys.modules"
python -c "import ast,pathlib;s=pathlib.Path('plugins/quench-dev-tasks/server/server.py').read_text(encoding='utf-8');t=ast.parse(s);ids={n.id for n in ast.walk(t) if isinstance(n,ast.Name)}|{n.attr for n in ast.walk(t) if isinstance(n,ast.Attribute)};assert 'Context' not in ids,'dangling Context reference'"
python -c "import os,subprocess,sys;e=dict(os.environ);e.pop('PYTHONPATH',None);r=subprocess.run([sys.executable,'-c','import server'],cwd='plugins/quench-dev-tasks/server',env=e,capture_output=True);assert r.returncode==0,r.stderr.decode('utf-8','replace')[-2000:];assert r.stdout==b'','stdout must stay clean (INV-4)'"
python scripts/export_ide_schemas.py --write
python -c "import subprocess,sys;r=subprocess.run([sys.executable,'scripts/export_ide_schemas.py','--check'],capture_output=True);assert r.returncode==0,(r.returncode,r.stderr.decode('utf-8','replace'))"
python -c "import hashlib,pathlib,subprocess,sys;p=pathlib.Path('docs/architecture/ide_tool_schemas.json');h1=hashlib.sha256(p.read_bytes()).hexdigest();subprocess.run([sys.executable,'scripts/export_ide_schemas.py','--write'],check=True);h2=hashlib.sha256(p.read_bytes()).hexdigest();assert h1==h2,(h1,h2)"
python -c "import pathlib;CR=bytes([13]);LF=bytes([10]);b=pathlib.Path('docs/architecture/ide_tool_schemas.json').read_bytes();assert CR+LF not in b;assert b.endswith(LF);assert b.count(LF)>1;assert not b.endswith(LF*2)"
python -c "import stat,pathlib,sys;p=pathlib.Path('docs/architecture/ide_tool_schemas.json');m=stat.S_IMODE(p.stat().st_mode);assert (m==0o644 if sys.platform!='win32' else (m&0o600)==0o600),oct(m);assert not list(p.parent.glob('.ide_tool_schemas.json.*.tmp'))"
python -c "import json,pathlib,sys;sys.path.insert(0,'plugins/quench-dev-tasks/server');import tool_surface_constants as c;d=json.loads(pathlib.Path('docs/architecture/ide_tool_schemas.json').read_text(encoding='utf-8'));assert d['_meta']=={'schema_version':c.SNAPSHOT_SCHEMA_VERSION};assert set(d)==set(c.EXPECTED_TOOL_NAMES)|{'_meta'};assert len(d)-1==c.TOOL_COUNT"
python -c "import os,subprocess,sys,tempfile;d=tempfile.mkdtemp();p=os.path.join(d,'absent');r=subprocess.run([sys.executable,'scripts/export_ide_schemas.py','--check','--cache-dir',p],capture_output=True);assert r.returncode==2,r.returncode;assert not os.path.exists(p)"
python -c "import pathlib,subprocess,sys,tempfile;d=tempfile.mkdtemp();f=pathlib.Path(d)/'ide_tool_schemas.json';f.write_text('{ not json',encoding='utf-8');r=subprocess.run([sys.executable,'scripts/export_ide_schemas.py','--check','--cache-dir',d],capture_output=True);assert r.returncode==2,r.returncode"
python -c "import subprocess,sys;r=subprocess.run([sys.executable,'-P','scripts/_introspect_schemas_child.py'],capture_output=True);o=r.stdout.decode('utf-8');assert o.count('@@QUENCH-SCHEMA-BEGIN@@')==1 and o.count('@@QUENCH-SCHEMA-END@@')==1;assert o.lstrip().startswith('@@QUENCH-SCHEMA-BEGIN@@'),o[:200]"
pytest plugins/quench-dev-tasks/server/tests/test_ide_schema_export.py -m tier1_fast -q --durations=5
pytest plugins/quench-dev-tasks/server/tests/test_export_ide_schemas_cli.py -q
python scripts/check_test_tiering_invariants.py
python scripts/check_test_duration_baselines.py
python scripts/asset_inventory.py
```

---

### 任务 1.2 ✔️ 已完成（终审修订版 · 原位替换）— 工具面契约单测单点收敛（AST 提取器 + 三态默认值归一化双向比对 + 删除 B5 的物理差分证明）

#### 【涉及文件】
```
[NEW]    plugins/quench-dev-tasks/server/tests/test_tool_surface_contract.py
[NEW]    plugins/quench-dev-tasks/server/tests/_tool_surface_expectations.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py
[MODIFY] plugins/quench-dev-tasks/server/tests/conftest.py
```

#### 【缺陷根因与修改目标】
```
R-12 默认值跨面比对未归一化：AST 侧 ast.literal_eval 得 tuple/complex，JSON 侧为 list/str → 必然假红；ast.Name 默认值（常量引用）无法求值且无显式失败语义。
R-14 test_no_varargs_tools 无输入且 extractor 内部已 assert，测试只能验证"没抛"，近乎恒真。
R-15 删除 B5 的"物理差分证据"仍为文档表格，无 grep 断言，属自证。
R-16 ToolSurfaceEntry(frozen=True, slots=True) 含 dict 字段 → __hash__ 抛 TypeError。
R-17 ctx 不变量仅按形参名判定；未来 context: Context 注解形参将被 FastMCP 静默剥离而 AST 不剥离 → 假红 + 纪律失效。
另：derive_live_tool_surface 未锚定 __file__，快照 fixture 路径未钉死，cwd 变更即假红。
目标：在 _tool_surface_expectations.py 建立强校验 AST 提取器（注解优先的 ctx 识别、literal_eval 失败显式抛错、默认值经 json_projection 归一化），test_tool_surface_contract.py 以冻结快照为证据基准做纯内存双向比对（零 import server / 零子进程 / 零网络）。
顺序依赖：1.1 定稿 → 1.2。
```

#### 【目标签名与类型契约】
```python
# _tool_surface_expectations.py
SERVER_SOURCE_PATH: Final[Path]        # (Path(__file__).resolve().parents[1] / "server.py")
SNAPSHOT_PATH: Final[Path]             # 仓库根 docs/architecture/ide_tool_schemas.json，经 __file__ 锚定

class ToolSurfaceError(Exception): ...

@dataclass(frozen=True, slots=True)
class ToolSurfaceEntry:
    name: str
    params: frozenset[str]          # posonlyargs ∪ args ∪ kwonlyargs
    non_ctx_params: frozenset[str]  # params - ctx_params
    ctx_params: frozenset[str]      # 注解命中 Context 或名称命中 CTX_PARAM_ALIASES
    defaults: tuple[tuple[str, Any], ...]   # 有序不可变，可哈希
    @property
    def default_map(self) -> Mapping[str, Any]: ...

@dataclass(frozen=True, slots=True)
class ToolSurfaceReport:
    entries: tuple[ToolSurfaceEntry, ...]

def json_projection(value: Any) -> Any: ...   # 与 canonicalize_schemas 同一语义
def extract_tool_surface_from_source(source: str, *, filename: str = "<server.py>") -> ToolSurfaceReport: ...
def derive_live_tool_surface() -> ToolSurfaceReport: ...      # 读取 SERVER_SOURCE_PATH
def assert_surface_well_formed(report: ToolSurfaceReport, expected: frozenset[str]) -> None: ...
def assert_ctx_surface(report: ToolSurfaceReport) -> None: ...# {e.name for e in entries if e.ctx_params} == TOOL_ALLOWS_CTX

# test_tool_surface_contract.py（Tier-1，零 import server）
def test_tool_set_matches_frozen_snapshot(snapshot_data) -> None: ...
def test_tool_name_sets_agree_across_surfaces(snapshot_data) -> None: ...
def test_tool_allows_ctx_bidirectional() -> None: ...
def test_no_varargs_tools_rejected() -> None: ...              # 合成源码 → pytest.raises(ToolSurfaceError)
def test_defaults_agree_between_ast_and_snapshot(tool_name, snapshot_data) -> None: ...
def test_live_surface_path_is_file_anchored() -> None: ...
def test_entry_is_hashable() -> None: ...
```

#### 【分步改造指引】
1. 新建 `_tool_surface_expectations.py`：顶层 `from tool_surface_constants import (...)` 单点复用常量与访问器；`extract_tool_surface_from_source` 以 `ast.Call/ast.Attribute + attr == "tool"` 结构判定装饰器，形参取 `posonlyargs + args + kwonlyargs` 并集；`vararg`/`kwarg` 非空 → `ToolSurfaceError`；默认值 `ast.literal_eval` 失败 → `ToolSurfaceError(f"{filename}:{tool}.{param} 默认值非字面量")`；成功值一律过 `json_projection` 归一；
2. ctx 识别**注解优先**：`ast.Name(id="Context")` / `ast.Attribute(attr="Context")` / `ast.Constant("Context")` 命中，或名称命中 `CTX_PARAM_ALIASES`，并入 `ctx_params`；
3. `derive_live_tool_surface()` 一律读 `SERVER_SOURCE_PATH`（`encoding="utf-8"`），禁止裸相对路径；
4. 新建 `test_tool_surface_contract.py`：`snapshot_data` 为 module 级 fixture（单次反序列化，读 `SNAPSHOT_PATH`）；跨面比对消费 `entry.name` 对象属性，严禁解析 `_mcp_sym_` 序列化串；参数以 `entry.non_ctx_params` 与 `iter_param_names(snapshot, tool)` 双向相等；默认值以 `has_default` 划分后，`json_projection(entry.default_map[p])` 与 `get_default(snapshot, tool, p)` 双向相等；
5. `test_no_varargs_tools_rejected` 以合成源码（含 `*args` 与 `**kwargs` 两个用例参数化）断言 `pytest.raises(ToolSurfaceError)`；
6. `conftest.py` 的 `TIER1_TARGET_REL_FILES` 追加 `test_tool_surface_contract.py`（与 1.1 追加项互不重叠）；
7. 从 `test_reviewer_poll_progress.py` 移除 `test_b5_pure_signature_and_no_ctx`，同步模块 docstring 删除 B5 条目并注明「已收敛至 test_tool_surface_contract.py」，保留 B1–B4、B6、B7；
8. B5 断言 → 新断言 映射表（物理承接证据，DoD 双 grep 佐证）：
   - 工具名集合断言 → `test_tool_set_matches_frozen_snapshot` + `test_tool_name_sets_agree_across_surfaces`
   - ctx 形参断言 → `test_tool_allows_ctx_bidirectional` + `assert_ctx_surface`
   - `raw_text` 默认值断言 → `test_defaults_agree_between_ast_and_snapshot[dev_reviewer_poll]`
   - `wait_max_s` 默认值断言 → `test_defaults_agree_between_ast_and_snapshot[dev_reviewer_poll]`

#### 【防御与边缘校验】
- **零覆盖退化**：映射表 + DoD 双 grep（B5 名消失 / conftest 注册项存在）形成物理证据链；
- **纯净性**：契约测试零子进程、零网络、零 `import server`；导入后断言 `"fastmcp" not in sys.modules`；
- **单点常量**：仓库 `.py` 不得出现第二份工具名单或裸 `16`；展示与报错统一 `sorted()`；
- **符号隔离**：跨面消费对象属性而非序列化串；
- **默认值归一**：`tuple` / `list` / `None` / `False` / `0` / `""` 五类边界必须各有一例显式断言，杜绝 `if default:` 式三态坍缩；
- **可变参数防御**：`*args` / `**kwargs` 必须抛 `ToolSurfaceError`，而非被并集静默忽略；
- **路径锚定**：`SERVER_SOURCE_PATH` / `SNAPSHOT_PATH` 均为 `__file__` 派生的绝对路径且 `.is_file()`；
- **可哈希性**：`hash(entry)` 不得抛 `TypeError`。

#### 【DoD 验证命令】
```bash
python -c "import sys;sys.path.insert(0,'plugins/quench-dev-tasks/server');sys.path.insert(0,'plugins/quench-dev-tasks/server/tests');import _tool_surface_expectations as e,tool_surface_constants as c;r=e.derive_live_tool_surface();e.assert_surface_well_formed(r,c.EXPECTED_TOOL_NAMES);e.assert_ctx_surface(r);assert e.SERVER_SOURCE_PATH.is_absolute() and e.SERVER_SOURCE_PATH.is_file();assert e.SNAPSHOT_PATH.is_file();assert all(hash(x) is not None for x in r.entries)"
python -c "import sys;sys.path.insert(0,'plugins/quench-dev-tasks/server');sys.path.insert(0,'plugins/quench-dev-tasks/server/tests');import _tool_surface_expectations as e;e.extract_tool_surface_from_source('def f(*args): pass') if False else None
try:
    e.extract_tool_surface_from_source('class M:\n    def tool(self,*a,**k):\n        def f(self,*args): pass\n        return f\n')
except e.ToolSurfaceError: pass
else: raise AssertionError('varargs not rejected')"
python -c "import pathlib;s=pathlib.Path('plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py').read_text(encoding='utf-8');assert 'test_b5_pure_signature_and_no_ctx' not in s,'B5 not removed'"
python -c "import pathlib;s=pathlib.Path('plugins/quench-dev-tasks/server/tests/conftest.py').read_text(encoding='utf-8');assert 'test_tool_surface_contract.py' in s;assert 'test_export_ide_schemas_cli.py' not in s,'heavy CLI test must stay out of Tier-1'"
python -c "import sys;sys.path.insert(0,'plugins/quench-dev-tasks/server');sys.path.insert(0,'plugins/quench-dev-tasks/server/tests');import test_tool_surface_contract;assert 'fastmcp' not in sys.modules"
pytest plugins/quench-dev-tasks/server/tests/test_tool_surface_contract.py -m tier1_fast -q --durations=5
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py -q
python scripts/check_test_tiering_invariants.py
```

---

### 任务 1.3 ✔️ 已完成 — Skill 文档去形参字面量瘦身并加防漂移物理锚点

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md
[MODIFY] plugins/quench-dev-tasks/server/tests/test_onboarding_doc_contract.py
```

#### 【缺陷根因与修改目标】
```
根因：两份 SKILL.md 与 README §3.3 硬编码工具形参默认值与冗长 16 工具参数清单，底层默认值微调即产生字面量漂移；且现有 doc-contract 测试未断言「无默认值字面量」，漂移无物理防线（Reviewer §5 L3 缺口）。目标：清除 Skill 文档中非必要的形参默认值硬编码，调用示例精简为意图级调用，规格超链接锚定 dev_tasks_mcp_specification.md；并在 test_onboarding_doc_contract.py 增补针对散文默认值短语的代码块剥离检测断言（覆盖两份 SKILL.md 与 README §3.3），使散文漂移可假红。可与任意阶段并行。
```

#### 【目标签名与类型契约】
```python
FORBIDDEN_PROSE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)\bdefaults?\s+to\s+`?[a-z0-9_]+`?"),
    re.compile(r"默认\s*`?[a-z0-9_]+`?"),
    re.compile(r"(?i)\bdefault\s*[:=]\s*`?[a-z0-9_]+`?"),
    re.compile(r"\b(raw_text|wait_max_s)\s*=\s*(?:True|False|\d+)"),
)
def strip_fenced_code_blocks(text: str) -> str: ...
def iter_prose_default_violations(text: str) -> list[tuple[int, str]]: ...
# 文档契约：Skill 示例仅展示必填/核心业务参数；禁止散文中匹配 FORBIDDEN_PROSE_PATTERNS；超链接相对 SKILL.md 所在目录正确回溯；豁免显式传参调用示例与代码块。遵守语言镜像契约。
```

#### 【分步改造指引】
1. 清理 dev-tasks-review/SKILL.md 第 5 节等处对 raw_text=False 等默认值的硬编码陈述，改为意图级说明 + 规格超链接；保持既有双语标题与章节结构；
2. 清理 dev-tasks-workflow/SKILL.md 速查表中的参数默认值陈述，精炼为职责与使用时机；保持既有双语六核心字段模板完整性；
3. 在 test_onboarding_doc_contract.py 增补 test_skill_docs_and_readme_have_no_param_default_literals()：使用 strip_fenced_code_blocks 结合行状态机精确剥离代码围栏与行内反引号，扫描两份 SKILL.md 与 docs/architecture/README.md §3.3 散文段落行，断言匹配 FORBIDDEN_PROSE_PATTERNS 违规列表为空，规避代码示例误报假红；并断言相对链接可解析。

#### 【防御与边缘校验】
- 语言镜像红线：不改动中英文既有章节结构与双语标题，不做非请求翻译；
- 六核心字段完整性：既有示范模板语义与结构必须完整保留；
- 假红规避：字面量禁令采用剥离代码块的散文扫描算法，精准匹配陈述性短语，允许带有业务意图的显式调用传参示例；
- 相对路径解析：链接检查必须基于 SKILL.md 文件所在目录相对解析。

#### 【DoD 验证命令】
```bash
python scripts/asset_inventory.py
pytest plugins/quench-dev-tasks/server/tests/test_onboarding_doc_contract.py -q
```

---

### 任务 1.4 ✔️ 已完成 — 规格 SSOT 参数默认值运行时锚定测试（规格 → 快照 → 运行时 三级一致性）

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/server/tests/test_spec_param_defaults_contract.py
[MODIFY] dev_tasks_mcp_specification.md
[MODIFY] plugins/quench-dev-tasks/server/tests/conftest.py
```

#### 【缺陷根因与修改目标】
```
根因：任务 1.1/1.3 将「参数默认值 SSOT」统一重定向至 dev_tasks_mcp_specification.md，但该文档此前无自动化断言将其声明值与运行时实际默认值绑定。目标：建立「规格文档声明默认值 ≡ 受控快照声明默认值」的 Tier-1 纯内存断言，形成「运行时 → 快照 → 规格」三级单源链；在规格文档中规范化参数参照表；引入哨兵与全量覆盖校验防御空过；校准 dev_tasks_mcp_specification.md，仅以 docs/architecture/ide_tool_schemas.json 实测值为唯一校准依据。顺序依赖：1.1 → 1.4。
```

#### 【目标签名与类型契约】
```python
# test_spec_param_defaults_contract.py
from tool_surface_constants import MISSING as _MISSING  # 哨兵身份由 tool_surface_constants 唯一锚定
JSONLiteral = str | int | float | bool | None

@dataclass(frozen=True)
class DefaultDiff:
    tool: str
    param: str
    documented: Any
    snapshot: Any
    kind: Literal["mismatch", "missing_in_snapshot", "not_documented"]

def extract_documented_defaults(spec_markdown: str) -> dict[str, dict[str, JSONLiteral]]: ...
def compare_documented_with_snapshot(documented: dict[str, dict[str, JSONLiteral]], snapshot: dict[str, Any]) -> list[DefaultDiff]: ...
def test_spec_documented_defaults_match_snapshot() -> None: ...
def test_single_sentinel_identity_and_missing_detection() -> None: ...  # 守卫的守卫测试
```

#### 【分步改造指引】
1. 在 dev_tasks_mcp_specification.md 中新增受 <!-- QUENCH-PARAM-DEFAULTS-BEGIN --> / <!-- QUENCH-PARAM-DEFAULTS-END --> 包裹的机器可读默认值块（块体为单一标准 JSON 对象，ensure_ascii=False），同时清理 spec 散文中的参数默认值陈述（去布尔/数值字面量，统一引用机器可读块，与 1.3 政策对齐）；在 test_spec_param_defaults_contract.py 中实现 extract_documented_defaults，仅解析该标记块（散文表不参与正则，规避假红）；增补块体损坏或非合规 JSON 时 fail-closed 负例断言；
2. 从 tool_surface_constants 单点导入 MISSING 哨兵并别名 _MISSING，compare_documented_with_snapshot 明确区分“缺失”与“默认值为 null”，断言 mismatch、missing_in_snapshot、not_documented 三者均为硬失败；并实现 test_single_sentinel_identity_and_missing_detection：构造内存快照中删除某参数，断言产出且仅产出一条 kind == "missing_in_snapshot"；
3. 将 test_spec_param_defaults_contract.py 加入 conftest.py 的 TIER1_TARGET_REL_FILES 白名单；编写单测断言差异列表为空，且 documented 覆盖全部 16 工具；纯函数 fixture 用例归入 Tier-1；
4. 仅以 docs/architecture/ide_tool_schemas.json 的 properties.<param>.default 实测值为唯一校准依据，逐条校准 dev_tasks_mcp_specification.md 中机器可读块与相关表述，保持英文 SSOT 结构；快照变更必须同 PR 修改 spec。

#### 【防御与边缘校验】
- 零子进程红线：纯文档/快照内存解析比对，严格满足 Tier-1 预算；
- 防空通过：单点哨兵 + 守卫的守卫单测，确保缺失检测真实有效；documented 覆盖率不足 100%、快照缺失或 properties 为空显式失败；mismatch/missing_in_snapshot/not_documented 全部硬失败；
- 假红防护与政策统一：解析仅限 <!-- QUENCH-PARAM-DEFAULTS-BEGIN/END --> 块，散文去字面量，不出现块正确而散文陈旧的分裂（H2）；
- 只读边界：测试运行期零写盘。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_spec_param_defaults_contract.py -m tier1_fast -q
pytest plugins/quench-dev-tasks/server/tests/test_onboarding_doc_contract.py -q
python scripts/export_ide_schemas.py --check
python scripts/asset_inventory.py
```

---

### 任务 1.5 ✔️ 已完成 — Snapshot 漂移门禁接线与跨平台字节确定性（pre-commit + gitattributes）

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/server/tests/test_snapshot_drift_gate_contract.py
[MODIFY] plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py
[MODIFY] docs/architecture/README.md
[MODIFY] plugins/quench-dev-tasks/server/tests/conftest.py
```

#### 【缺陷根因与修改目标】
```
根因：① 1.1 仅在本地手动 DoD 运行 export_ide_schemas.py --check，无提交/CI 物理门禁，漂移仍可合入；② Windows core.autocrlf=true 若未正确定位可能引起 CRLF 污染；③ 1.4 若门禁未严加防范，CI 若允许 --write 会把意外默认值回归合法化；④ git_pre_commit_guard 对 exit 2 若 fail-open 会造成门禁逃逸；⑤ is_antigravity_environment 命中时若降级豁免 schema 漂移会破坏契约。
目标：在 pre-commit 层增加 evaluate_schema_check 判定，对相关源文件变更触发只读 --check，严密划分 SchemaCheckOutcome（SKIP, PASS, DRIFT, UNVERIFIABLE, GUARD_ERROR；rc==1 与 rc==2/超时必须 fail-closed 阻断，仅变更集获取异常 fail-open）；枚举 SCHEMA_TRIGGER_PATHS 触发集；明确 Antigravity 裁决序（schema 漂移不豁免）；由 .gitattributes 既有 *.json text eol=lf 确保生效；同时在 README 明示「CI 只校验、写入需人审」策略。
```

#### 【目标签名与类型契约】
```python
# git_pre_commit_guard.py
class SchemaCheckOutcome(enum.Enum):
    SKIP = "skip"          # 变更集未命中：零子进程，<50ms
    PASS = "pass"          # rc == 0
    DRIFT = "drift"        # rc == 1 → 阻断
    UNVERIFIABLE = "unverifiable"  # rc == 2 / TimeoutExpired → 阻断（fail-closed）
    GUARD_ERROR = "guard_error"    # 仅变更集获取失败 → fail-open

SCHEMA_TRIGGER_PATHS: Final[frozenset[str]] = frozenset({
    "plugins/quench-dev-tasks/server/server.py",
    "plugins/quench-dev-tasks/server/tool_surface_constants.py",
    "scripts/export_ide_schemas.py",
    "docs/architecture/ide_tool_schemas.json",
})

def should_run_schema_check(changed_paths: Sequence[str]) -> bool: ...
def evaluate_schema_check(changed_paths: Sequence[str], *, repo_root: Path) -> SchemaCheckOutcome: ...
```

#### 【分步改造指引】
1. 在 plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py 增加 SCHEMA_TRIGGER_PATHS、should_run_schema_check 与 evaluate_schema_check：仅当变更集命中 SCHEMA_TRIGGER_PATHS 时触发；未命中返回 SKIP（零子进程，<50ms）；命中时运行 subprocess.run([sys.executable, "scripts/export_ide_schemas.py", "--check"], cwd=str(repo_root), timeout=30)；rc==0 返回 PASS；rc==1 返回 DRIFT 并阻断提交；rc==2 或 TimeoutExpired 返回 UNVERIFIABLE 并阻断提交（fail-closed）；仅当变更集读取失败时返回 GUARD_ERROR（fail-open 告警放行）；
2. 固化 Antigravity 裁决序：schema 漂移检查为独立硬门禁，不受 is_antigravity_environment 豁免；
3. 新增 test_snapshot_drift_gate_contract.py：断言 .gitattributes 生效行为、should_run_schema_check 真值表、5 分支参数化覆盖与未命中路径零子进程；并登记入 conftest.py 的 TIER1_TARGET_REL_FILES；
4. 在 docs/architecture/README.md §3.3 追加策略：CI 仅执行 --check；--write 仅限本地/人工，snapshot diff 需 Reviewer 批准，并登记 SCHEMA_TRIGGER_PATHS。

#### 【防御与边缘校验】
- 50ms 预算：未命中变更集时禁止 subprocess；
- 门禁不可逃逸：exit 2 与超时一律 fail-closed 阻断；fail-open 严格受限于无法取得变更集；
- 明确裁决序：Antigravity 环境下 DRIFT / UNVERIFIABLE 照常阻断；
- 网络零依赖；测试零写盘。

#### 【DoD 验证命令】
```bash
python -c "import sys; sys.path.insert(0,'plugins/quench-dev-tasks/scripts'); from git_pre_commit_guard import should_run_schema_check as f; assert not f(['README.md']); assert f(['plugins/quench-dev-tasks/server/server.py'])"
pytest plugins/quench-dev-tasks/server/tests/test_snapshot_drift_gate_contract.py -m tier1_fast -q
python scripts/export_ide_schemas.py --check
python scripts/check_test_tiering_invariants.py
python scripts/asset_inventory.py
```
### 任务 1.6 ✅ 已确认 — 规格 SSOT 标记块损坏容错与非合规输入阻断测试

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_spec_param_defaults_contract.py
```

#### 【缺陷根因与修改目标】
```
根因：任务 1.4 建立了规格文档 <!-- QUENCH-PARAM-DEFAULTS-BEGIN/END --> 机器可读块的正向提取与快照比对，但缺乏对非法输入、语法损坏、边界缺损的鲁棒性断言；若标记块缺失、重复出现、块内包含非 JSON 散文、顶层不是字典、或包含无法识别的未知工具，现有 extract_documented_defaults 可能未受检崩溃或静默返回空，导致门禁失效。
目标：在 test_spec_param_defaults_contract.py 补充负例与边界用例集，断言：① 缺失 BEGIN 或 END 标签抛出 SpecFormatError 并阻断；② 多对标签抛出 SpecFormatError；③ JSON 语法非法 fail-closed；④ 顶层非 dict 阻断；⑤ 未知工具名在比对时标记为 not_documented 或引发校验异常；⑥ 确保异常信息具备明确行号与修复指引。
顺序依赖：1.1 → 1.4 → 1.6。
```

#### 【目标签名与类型契约】
```python
# test_spec_param_defaults_contract.py
class SpecFormatError(Exception):
    """Raised when the machine-readable defaults block in specification is missing or corrupted."""
    pass

def test_spec_defaults_block_missing_tags_raises() -> None: ...
def test_spec_defaults_block_duplicate_tags_raises() -> None: ...
def test_spec_defaults_block_invalid_json_raises() -> None: ...
def test_spec_defaults_block_top_level_non_dict_raises() -> None: ...
```

#### 【分步改造指引】
1. 在 test_spec_param_defaults_contract.py 中定义 SpecFormatError；
2. 改造 extract_documented_defaults：使用严格正则匹配恰好一对标记块，不符合时 raise SpecFormatError；解析 JSON 时捕获 json.JSONDecodeError 并包装为 SpecFormatError；校验顶层必须为 dict[str, dict[str, Any]]；
3. 编写参数化单测覆盖以上 4 种负例场景；全部断言为纯内存操作，归入 Tier-1。

#### 【防御与边缘校验】
- 纯内存零 I/O，单测执行时间 < 50ms；
- fail-closed 原则，任何格式瑕疵均不可逃逸；
- 与 1.4 严格单调递增，无任何重叠或冲突。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_spec_param_defaults_contract.py -m tier1_fast -q
python scripts/check_test_tiering_invariants.py
```

---

### 任务 1.7 ✅ 已确认 — 缺失哨兵跨导入路径物理单例锚定（守卫的守卫）

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/server/tests/test_missing_sentinel_singleton.py
[MODIFY] plugins/quench-dev-tasks/server/tests/conftest.py
```

#### 【缺陷根因与修改目标】
```
根因：_MISSING 哨兵此前仅依赖 is 身份比较与纪律性「禁止二次定义」，一旦同一源文件经 sys.path 正规导入与 importlib.spec_from_file_location 自定义名导入两条路径进入同一进程，将产生两个互斥模块实例与两个互斥哨兵对象，导致 get_default(...) is _MISSING 恒为 False，missing_in_snapshot 分类静默空过；同时 Python 的 reload() 语义会重新执行模块体导致类对象与单例重建，不可满足 reload 单例（MF-2）。目标：将 tool_surface_constants 严格定义为「禁止 reload」的基础契约模块（标注 DO NOT RELOAD）；以物理测试锁定跨 sys.path 正规导入与 spec_from_file_location 规范导入下哨兵 is 身份唯一性；提供 is_missing(val) 辅助谓词；全仓 AST 静态扫描禁止裸 object() 哨兵二次赋值。顺序依赖：1.1 → 1.2 → 1.4 → 1.7。本任务不修改任何生产逻辑，仅新增物理断言，防止 F-A 类「词法单点、导入层碎裂」缺陷再次发生。
```

#### 【目标签名与类型契约】
```
# test_missing_sentinel_singleton.py
def test_sentinel_is_identical_across_sys_path_import() -> None: ...
    # 断言 tool_surface_constants.MISSING is export_ide_schemas._MISSING
def test_sentinel_is_identical_across_spec_from_file_location() -> None: ...
    # 断言以规范 spec_from_file_location 加载 tool_surface_constants 时，单例身份唯一
def test_is_missing_predicate_truth_table() -> None: ...
def test_get_default_returns_canonical_sentinel_on_missing_param() -> None: ...
    # 构造删除 param 的快照，断言返回对象 is tool_surface_constants.MISSING
def test_only_one_missing_sentinel_definition_in_repo() -> None: ...
    # AST 静态扫描全仓 *_MISSING* = object() 字面构造，断言计数 == 0
```

#### 【分步改造指引】
1. 新建 test_missing_sentinel_singleton.py，全部断言基于 is 身份比较，禁止 == 或 isinstance 退化；
2. 明确删除 reload 单例条款（MF-2 闭环），在 tool_surface_constants 模块 docstring 显式声明 DO NOT RELOAD 契约；test_only_one_missing_sentinel_definition_in_repo 使用 ast 解析 plugins/quench-dev-tasks/server/ 与 scripts/ 下全部 .py，匹配「模块级赋值 object() 且左值名含 MISSING」的节点，断言计数为 0（哨兵必须由类实例构造而非裸 object()）；
3. 将 test_missing_sentinel_singleton.py 加入 conftest.py 的 TIER1_TARGET_REL_FILES（纯 AST + 内存操作，预算 < 100ms）；
4. 在模块 docstring 声明本任务为 F-A 的回归防线，并指向任务 1.1 §【目标签名与类型契约】作为唯一哨兵定义源。

#### 【防御与边缘校验】
- 身份比较红线：全部断言使用 is / is not，不得使用 ==，否则哨兵的「可比较化」会重新引入可伪造性；
- 零子进程与零 server 导入：AST 扫描 + 内存导入，严格受 Tier-1 ≤5s 预算约束；
- 导入路径无关性：显式覆盖 sys.path 正规导入与 importlib 自定义名导入两条路径，任一碎裂立即假红；
- 假红防护：importlib 用例在装入后必须 finally 清理临时 sys.modules 键，避免污染同 session 的其他测试。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_missing_sentinel_singleton.py -m tier1_fast -q --durations=5
pytest plugins/quench-dev-tasks/server/tests/test_tool_surface_contract.py -m tier1_fast -q
python scripts/export_ide_schemas.py --check
python scripts/check_test_tiering_invariants.py
```

---

### 任务 1.8 ✅ 已确认 — CLI 跨平台沙箱边界与文件系统异常映射加固

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_export_ide_schemas_cli.py
```

#### 【缺陷根因与修改目标】
```
根因：scripts/export_ide_schemas.py 作为面向 IDE 与 CI 的薄壳入口，需在各种恶劣文件系统与环境变量配置下稳定工作；需严防目录穿越、跨符号链接写入以及未预期权限错误造成的半成品快照；现有 CLI 测试主要覆盖正常 --write 与 --check，对于跨平台权限异常、符号链接拒绝、非只读环境下的隔离性缺乏完备测试。
目标：加固 test_export_ide_schemas_cli.py，覆盖边界测试矩阵：① --cache-dir 指向符号链接或 Reparse Point 时的物理阻断；② --cache-dir 为只读目录或无权限父目录时的干净 exit 2 映射（绝不抛出未捕获的 PermissionError 堆栈）；③ 环境变量含有污染性 PYTHONPATH 时，子进程探针仍能利用 -P 纯净运行；④ 确保 CLI 测试被严格隔离在 Tier-1 之外（因其调用真实 Python 子进程）。顺序依赖：1.1 → 1.8。
```

#### 【目标签名与类型契约】
```python
# test_export_ide_schemas_cli.py
def test_cli_cache_dir_reparse_point_rejected(tmp_path: Path) -> None: ...
def test_cli_cache_dir_permission_denied_maps_to_exit_2(tmp_path: Path) -> None: ...
def test_cli_isolated_pythonpath_does_not_pollute_probe() -> None: ...
def test_cli_repeated_write_is_strictly_idempotent(tmp_path: Path) -> None: ...
```

#### 【分步改造指引】
1. 在 test_export_ide_schemas_cli.py 中新增沙箱边界测试用例：
   - 构造指向目录的符号链接或 Reparse Point 作为 --cache-dir，断言其退出码为 2，且未写入任何文件；
   - 构造无写权限的临时目录执行 --write，断言其退出码为 2 且 stderr 输出格式化错误信息（无 Python 原始 traceback 抛出）；
   - 在传入带有虚假/恶意 PYTHONPATH 的 env 下执行 --check，验证 -P 参数生效，子进程能够正常返回 0 或 1；
   - 连续执行两次 --write，通过文件的 st_mtime 或 hash 断言写前比对命中、零二次写入。
2. 确保 test_export_ide_schemas_cli.py 不登记入 conftest.py 的 TIER1_TARGET_REL_FILES（保持其重型子进程测试隔离）。

#### 【防御与边缘校验】
- 跨平台防线：Windows 与 POSIX 差异以 best-effort 处理，测试中针对 Windows Reparse Point 进行适配跳过或专用判定；
- 零半成品快照：任何写入故障退出码恒为 2，绝不在目标目录遗留临时文件；
- Tier-1 洁净：本文件所有用例均不带 tier1_fast 标记，不影响快速测试流。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_export_ide_schemas_cli.py -q
python scripts/check_test_tiering_invariants.py
```

---

### 任务 1.9 ✅ 已确认 — 工具链重构全链路验收、测试分级基线与资产盘点门禁

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/conftest.py
[MODIFY] docs/architecture/README.md
```

#### 【缺陷根因与修改目标】
```
根因：在完成工具面常量源、AST 契约、文档去字面量、规格三级一致性与 pre-commit 漂移门禁后，必须对全仓进行端到端的架构完整性复验；防止新增测试用例突破 Tier-1 ≤ 5s 性能预算、防止未声明文件残留、防止 conftest 白名单存在未被检测到的漏洞。
目标：作为本开发任务单的最终闭环门禁：① 运行 check_test_tiering_invariants.py 校验所有新增测试严格符合分级契约；② 运行 check_test_duration_baselines.py 确认 Tier-1 性能基线无劣化；③ 运行 asset_inventory.py 校验无孤儿未追踪资产；④ 执行 git diff 审计确保变更完全符合任务涉及文件白名单；⑤ 在 docs/architecture/README.md 最终核对架构设计与实现的一致性。顺序依赖：1.1 ~ 1.8 全部完成后执行。
```

#### 【目标签名与类型契约】
```python
# conftest.py
TIER1_TARGET_REL_FILES: frozenset[str] = frozenset({
    # 严格仅包含纯内存、<100ms 的轻量契约测试文件
    "test_ide_schema_export.py",
    "test_tool_surface_contract.py",
    "test_spec_param_defaults_contract.py",
    "test_snapshot_drift_gate_contract.py",
    "test_missing_sentinel_singleton.py",
    ...,
})
```

#### 【分步改造指引】
1. 核对 conftest.py 中的 TIER1_TARGET_REL_FILES 白名单，确保仅轻量测试登记入库，test_export_ide_schemas_cli.py 坚决排除在外；
2. 运行 scripts/check_test_tiering_invariants.py 验证分级不变式（$H \cap \text{Tier-1} = \emptyset$）；
3. 运行 scripts/check_test_duration_baselines.py --tier1 验证 Tier-1 耗时基线无超标（≤ 5s）；
4. 运行 scripts/asset_inventory.py 校验仓库资产，确认所有新增代码和测试均已合法纳入受管清单；
5. 在 docs/architecture/README.md 完成全部架构演化记录核对。

#### 【防御与边缘校验】
- 全量门禁闭环：所有门禁脚本 exit 0 方可通过；
- 零未受管资产：asset_inventory 绝无孤儿文件报警；
- 零 Tier-1 污染：坚决防止重型测试混入。

#### 【DoD 验证命令】
```bash
python scripts/export_ide_schemas.py --check
pytest plugins/quench-dev-tasks/server/tests/test_ide_schema_export.py -m tier1_fast -q
pytest plugins/quench-dev-tasks/server/tests/test_tool_surface_contract.py -m tier1_fast -q
pytest plugins/quench-dev-tasks/server/tests/test_spec_param_defaults_contract.py -m tier1_fast -q
pytest plugins/quench-dev-tasks/server/tests/test_snapshot_drift_gate_contract.py -m tier1_fast -q
pytest plugins/quench-dev-tasks/server/tests/test_missing_sentinel_singleton.py -m tier1_fast -q
pytest plugins/quench-dev-tasks/server/tests/test_export_ide_schemas_cli.py -q
python scripts/check_test_tiering_invariants.py
python scripts/check_test_duration_baselines.py --tier1
python scripts/asset_inventory.py
```

---

