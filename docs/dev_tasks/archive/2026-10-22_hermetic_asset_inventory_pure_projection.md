# 2026-10-22_hermetic_asset_inventory_pure_projection Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-22

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 资产清单门禁密封化重构：语义投影哈希取代文本剥离比对与测试解耦

#### 【涉及文件】
```
[MODIFY] scripts/asset_inventory.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_asset_inventory.py
[MODIFY] docs/architecture/over_engineering_inventory.md
[MODIFY] plugins/quench-dev-tasks/server/tests/fixtures/asset_inventory_default_golden.txt
```

#### 【缺陷根因与修改目标】
```
1. 缺陷根因：
- 根因 1（测试隔离性失守）：test_12_check_three_way_exit_semantics 的分支 2 直接以真实工作仓绝对路径 REPO_ROOT 运行未隔离的 --check，将单元测试的三值退出码契约（0/1/2）与真实物理工作树的文件卫生、会话内前序用例的写盘状态强行耦合，导致工作区符号未同步或被污染时单元测试发生级联失败。
- 根因 2（封闭性脆弱）：当前纯投影与门禁比对强依赖 <!-- BEGIN TELEMETRY (non-gated) --> 文本剥离，遥测样本数（verdicts.jsonl）和跨平台换行（CRLF/LF）易造成剥离两侧不对称，引发假阳性漂移。
- 根因 3（可诊断性缺失）：EXIT_DRIFT 仅输出单行 "Drift detected between codebase and inventory report pure projection!"，无具体分歧字段（drift_keys）、无双侧 sha256，故障无法自解释。
- 根因 4（错误映射不精准）：基线缺失或 marker 畸形等异常若未分流，易被混淆为 EXIT_DRIFT，掩盖环境损坏。

2. 修改目标：
- 密封化纯投影：重构 asset_inventory.py 中的门禁比对逻辑，在数据结构构造期严格排除易变量（verdicts 日志统计、样本数、时间戳、文件大小），以规范化语义投影（PureProjection）的 SHA-256 哈希值取代脆弱的 Markdown 标记文本剥离比对。
- 嵌入规范化投影块：--write 时在 Markdown 尾部嵌入 <!-- QUENCH-PROJECTION-BEGIN:v1 -->...<!-- QUENCH-PROJECTION-END --> 机器可读 JSON 注释块；--check 解析该块与 fresh PureProjection 计算双侧哈希，分歧时通过 diagnose_drift 枚举准确的 drift_keys。
- 测试解耦与绝对路径清除：重构 test_12_check_three_way_exit_semantics，其 EXIT_OK、EXIT_DRIFT、EXIT_USAGE 三分支全部在独立沙箱（mini_repo_fixture / tmp_path）中验证，彻底清除真实仓物理路径硬依赖；真仓自检若保留则独立为专用用例并使用动态发现根目录，杜绝写死盘符路径。
- 增强可诊断性：--check 发现漂移（EXIT_DRIFT=1）时，在 stderr 输出结构化诊断（drift sha256_on_disk=<hex> sha256_fresh=<hex> drift_keys=<k1,k2,...>）；环境与标记损坏严格返回 EXIT_USAGE=2。
- 保证 100% 单测与加性守卫绿灯，确保所有现有不变式与性能预算无回归。
```

#### 【目标签名与类型契约】
```
PROJECTION_SCHEMA_VERSION: Final[str] = "quench-inventory-projection/v1"
PROJECTION_BEGIN_MARK: Final[str] = "<!-- QUENCH-PROJECTION-BEGIN:v1 -->"
PROJECTION_END_MARK: Final[str] = "<!-- QUENCH-PROJECTION-END -->"

class ProjectionSchemaMismatchError(Exception):
    """on-disk 投影块缺失、schema_version 不识别或 marker 失衡时抛出（映射至 EXIT_USAGE=2）。"""

@dataclass(frozen=True)
class PureProjection:
    schema_version: str
    modules: tuple[ModuleNode, ...]
    consumers: tuple[ConsumerEdge, ...]
    tools: tuple[ToolSurface, ...]
    removal_candidates: tuple[ConsumerEdge, ...]
    must_not_remove: tuple[str, ...]
    g1prime_gaps: tuple[str, ...]
    doc_drift_ledger: tuple[str, ...]

def build_pure_projection(report: InventoryReport) -> PureProjection: ...
def canonical_projection_json(proj: PureProjection) -> bytes: ...
def compute_pure_projection_sha256(proj: PureProjection) -> str: ...
def diagnose_drift(on_disk: PureProjection, fresh: PureProjection) -> tuple[str, ...]: ...
def render_projection_block(proj: PureProjection) -> str: ...
def extract_projection_block(markdown: str) -> PureProjection: ...
```

#### 【分步改造指引】
1. 类型层重构：
   - 在 scripts/asset_inventory.py 中定义 PROJECTION_SCHEMA_VERSION = "quench-inventory-projection/v1"、PROJECTION_BEGIN_MARK = "<!-- QUENCH-PROJECTION-BEGIN:v1 -->"、PROJECTION_END_MARK = "<!-- QUENCH-PROJECTION-END -->" 以及 ProjectionSchemaMismatchError(Exception)；
   - 定义 PureProjection 冻结数据类，保留 ConsumerEdge 完整结构（保真 defined_in 与测试引用）。
2. 构造层重构：
   - 实现 build_pure_projection(report: InventoryReport) -> PureProjection，构造期严格排除 audit_reason_histogram、telemetry_meta、skipped_files，元组各字段内部按明确键排序（modules 按 rel_path；consumers 按 (defined_in, symbol)；tools 按 registered_name；params 按 name；其余元组按字母序）；
   - 若 report.skipped_files 非空，向 stderr 打印单行警告（'[inventory] N file(s) skipped'），但不计入投影。
3. 序列化与哈希：
   - 实现 canonical_projection_json(proj: PureProjection) -> bytes，锁定 sort_keys=True, separators=(",", ":"), ensure_ascii=False，utf-8 严格编码；
   - 实现 compute_pure_projection_sha256(proj: PureProjection) -> str 基于上述字节计算 sha256 十六进制字符串。
4. 嵌入与提取层：
   - 实现 render_projection_block(proj: PureProjection) -> str 生成包含注释标签与规范 JSON 的文本块；
   - 实现 extract_projection_block(markdown: str) -> PureProjection 精准提取与反序列化，缺块、重复块、marker 失衡或 schema_version 未知时抛出 ProjectionSchemaMismatchError；
   - 更新 write_inventory_with_delta 与 --write 流程，在 Markdown 尾部追加投影块。
5. 诊断层：
   - 实现 diagnose_drift(on_disk: PureProjection, fresh: PureProjection) -> tuple[str, ...] 对比 8 个顶层字段，返回升序排列的不匹配字段名列表。
6. 门禁层（main --check）：
   - 提取 on-disk 投影与扫描 fresh 投影，比对双侧 sha256；
   - 哈希一致返回 EXIT_OK(0)；
   - 哈希不一致输出 'drift sha256_on_disk=<hex> sha256_fresh=<hex> drift_keys=k1,k2,...' 并返回 EXIT_DRIFT(1)；
   - ProjectionSchemaMismatchError / FrozenSnapshotMissingError / DeltaBlockMalformedError 等环境异常严格输出对应诊断并返回 EXIT_USAGE(2)。
7. 测试层重构（test_asset_inventory.py）：
   - 彻底重构 test_12_check_three_way_exit_semantics，三分支全部基于 tmp_path / mini_repo_fixture 沙箱化执行，消除真实仓 REPO_ROOT 硬依赖与任何盘符绝对路径；
   - 新增 test_13_pure_projection_sort_invariance（乱序输入哈希恒定）；
   - 新增 test_14_drift_diagnostic_format（capsys 断言 stderr drift 格式正则）；
   - 新增 test_15_verdicts_append_no_drift（追加 50+ 条 verdicts 日志不漂移）；
   - 新增 test_16_pythonhashseed_invariance（subprocess 子进程切换 seed 0 与 31337 断言哈希恒等）；
   - 新增 test_17_crlf_lf_equivalence（CRLF 仓与 LF 仓投影字节恒等）；
   - 新增 test_18_schema_version_mismatch_exit_usage（未知 schema 版本 fail-closed 返回 2）；
   - 新增 test_19_skipped_file_stderr_warning（超限跳过文件单行警告且不漂移）；
   - 新增 test_20_symbol_deletion_detected（删除符号漂移可检出）；
   - 新增 test_21_idempotent_projection_block（多次写入无重复投影块）；
   - 维护 test_additive_regression 与 test_write_idempotent 兼容性。
8. 资产与固件重生成：
   - 执行 python scripts/asset_inventory.py --write --repo-root . 重新生成 over_engineering_inventory.md，同步更新 asset_inventory_default_golden.txt；
   - 执行全量 DoD 命令确保 100% 通过。

#### 【防御与边缘校验】
1. 零假红（抗干扰不变量）：
   - verdicts.jsonl 追加 50+ 条日志 → --check 仍恒定返回 EXIT_OK(0)；
   - PYTHONHASHSEED ∈ {0, 31337} 两次独立子进程验证 → sha256 恒等；
   - 同源内容写 CRLF 仓与 LF 仓，两者 --write 后 canonical_projection_json 字节恒等；
   - doc_drift_ledger 内容重排但语义不变 → 排序后 sha256 恒等。
2. 零假绿（真实漂移可检出）：
   - 删除被管理模块的已登记符号 → drift_keys 包含 modules 与 removal_candidates；
   - 新增测试引用 → drift_keys 包含 consumers；
   - 同一符号从模块 A 迁移至模块 B → drift_keys 包含 modules（保留 defined_in 保真）；
   - tools 参数描述或签名变更 → drift_keys 包含 tools。
3. 退出码精确性（Fail-Closed 闭锁）：
   - ProjectionSchemaMismatchError（投影块缺失/失衡/schema_version 不识别）→ 严格返回 EXIT_USAGE(2)；
   - FrozenSnapshotMissingError / FrozenSnapshotUnparsableError / DeltaBlockMalformedError → 严格返回 EXIT_USAGE(2)；
   - 仅当双侧投影均成功构建且哈希差异时 → 返回 EXIT_DRIFT(1)。严禁以 except Exception 全捕获将环境/输入错误误报为 DRIFT。
4. 平台中立与绝对路径防御：
   - 测试文件及 mini_repo_fixture 中严禁出现任何形如 [A-Za-z]:\\ 的绝对路径字面量，所有路径由 Path(__file__).resolve() 或 tmp_path 派生。
5. 写操作纯度与幂等性：
   - write(write(x)) == write(x)，写入前后纯投影与 Delta 块保持 byte-identical；
   - PROJECTION_BEGIN_MARK 出现次数严格 == 1，QUENCH-DELTA-BEGIN 出现次数严格 == 1，禁止重复嵌套。
6. 可观测性回退：
   - report.skipped_files 非空时 → 向 stderr 单次输出 [inventory] N file(s) skipped 警告，不阻断、不计入漂移。
7. 版本迁移防御：
   - 未知 schema_version → 强制 EXIT_USAGE(2)，stderr 提示 'projection schema ... not recognized; run --write to refresh'。

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_asset_inventory.py -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_asset_inventory.py -k "three_way or projection or idempotent or drift or pythonhashseed or crlf or schema_version or skip" -v
python scripts/asset_inventory.py --write --repo-root .
python scripts/asset_inventory.py --check --repo-root .
git diff --exit-code docs/architecture/over_engineering_inventory.md
git diff --exit-code plugins/quench-dev-tasks/server/tests/fixtures/asset_inventory_default_golden.txt
python -m pytest -m tier1_fast -q
python -c "import ast; ast.parse(open('plugins/quench-dev-tasks/server/tests/test_asset_inventory.py', encoding='utf-8').read()); print('fixture-ast-ok')"
```

---

