# 2026-11-02_v1_29_batch1_reviewer_anti_anchoring_phase1 Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-02

---

## Task List & Status / 任务清单与状态

### 任务 29.1 ✔️ 已完成 — Reviewer 前提审计输出契约与咨询遥测埋点 (Phase 1, r7.2 终极闭环版)

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/consultation.py
[MODIFY] plugins/quench-dev-tasks/server/observability_policy.py
[NEW] plugins/quench-dev-tasks/server/tests/test_premises_parsing.py
[NEW] plugins/quench-dev-tasks/server/tests/test_consultation_telemetry.py
```

#### 【缺陷根因与修改目标】
```
根因：Reviewer findings 为自由文本，承重前提与翻转条件不可被下游消费；无结构化遥测基线。目标（r7.2 终极闭环）：1. 采用语义定义 + 测试反向锚定，任务单不出现易损正则字面量；2. 显式固化覆写优先级：先判定 token 真值，若任一字段超长则强制覆写 falsifiable=False；3. 固化 assert_premises_wellformed 契约：空列表 [] 合法通过，仅超限或非法字段抛 AssertionError；4. _emit_consultation_audit 扩展 keyword-only 形参 findings: str = '', verdict_state: str = 'COMPLETED'，原有位置参数序严格不变；5. is_degraded 采用唯一权威谓词 (verdict_state.upper() in {'DEGRADED', 'FAILED', 'CANCELLED'}) or (degraded_reason is not None)，命中时强制 effective_findings='' 且 premises_parsed_count=0；6. 遥测落盘 .agents/logs/telemetry/，避开 GC 回收；7. FileConsultationTelemetrySink 锁路径独立并精确捕获 (filelock.Timeout, OSError, ValueError) fail-open；8. @functools.lru_cache(maxsize=32) 工厂按 path 分键，测试一律以 tmp_path 隔离。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/server/consultation.py
# 语义定义：PREMISES_PATTERN 满足：匹配 <<<PREMISES>>> 前后可选空白，中间非贪婪任意内容（DOTALL），以 <<<END>>> 闭合。
PREMISES_PATTERN: Final[re.Pattern[str]]
MAX_PREMISES_PER_VERDICT: Final[int] = 12
MAX_PREMISE_FIELD_CHARS: Final[int] = 2048
_FALSIFIABLE_TRUE_TOKENS: Final[frozenset[str]] = frozenset({"true", "yes", "1"})

@dataclass(frozen=True, slots=True)
class PremiseRecord:
    premise: str
    flip_condition: str
    falsifiable: bool

def parse_premises(findings: str) -> list[PremiseRecord]: ...
def assert_premises_wellformed(records: Sequence[PremiseRecord]) -> None: ...

# 注：*, findings, verdict_state 均为 keyword-only；原有位置参数序不得改写。
async def _emit_consultation_audit(
    latch: threading.Event,
    log_dir: Path,
    session_id: str,
    mode: str,
    messages: Sequence[Mapping[str, Any]],
    usage: Mapping[str, int],
    status: str,
    degraded_reason: Optional[str] = None,
    has_need_files: bool = False,
    *,
    findings: str = "",
    verdict_state: str = "COMPLETED",
) -> None: ...

# plugins/quench-dev-tasks/server/observability_policy.py
@dataclass(frozen=True, slots=True)
class ConsultationTelemetryRecord:
    ts: str
    workspace_root: str
    job_id: str
    session_id: str
    prompt_hash: str
    prompt_chars: int
    observations_present: bool
    hypotheses_present: bool
    need_files_present: bool
    premises_parsed_count: int
    verdict_state: str     # 原始状态: COMPLETED/DEGRADED/FAILED/CANCELLED
    is_degraded: bool
    schema_version: int = 1   # N1'：默认值字段必须居末尾

class ConsultationTelemetrySink(Protocol):
    def emit_telemetry(self, record: ConsultationTelemetryRecord) -> None: ...

def make_consultation_telemetry_sink(path: str, lock_path: Optional[str] = None) -> ConsultationTelemetrySink: ...
def _get_consultation_telemetry_sink(path: str) -> ConsultationTelemetrySink: ...
def reset_consultation_telemetry_sink_cache() -> None: ...

```

#### 【分步改造指引】
consultation.py：按语义定义实现 PREMISES_PATTERN（反斜杠空白元字符），紧邻添加反向锚定注释。声明 PremiseRecord、MAX_PREMISES_PER_VERDICT=12、MAX_PREMISE_FIELD_CHARS=2048、_FALSIFIABLE_TRUE_TOKENS=frozenset({'true','yes','1'})。
consultation.py parse_premises：对命中块按换行切分；line.partition(':')，not sep 则 continue；识别 premise/flip_condition/falsifiable 三键；先按 _FALSIFIABLE_TRUE_TOKENS 判定 token 真值（val.strip().lower() in _FALSIFIABLE_TRUE_TOKENS）；若 premise 或 flip_condition 任一字段长度 > MAX_PREMISE_FIELD_CHARS，则强制 falsifiable=False，无论 token 判定结果；字段保留字面不静默截断；前 12 条；try/except 记录 sys.stderr 并 fail-open 返回 []。
consultation.py assert_premises_wellformed：新契约——records == [] 合法通过；len(records) > MAX_PREMISES_PER_VERDICT 抛 AssertionError；任一 record 的 premise/flip_condition 为空字符串或长度 > MAX_PREMISE_FIELD_CHARS 抛 AssertionError。docstring 显式声明测试专用，并明确标注：“调用方保证：生产路径永不将 parse_premises 结果喂入此函数；测试须手工构造非法 records 以触发断言。”
consultation.py _emit_consultation_audit 扩展：新增 keyword-only 形参 *, findings: str = '', verdict_state: str = 'COMPLETED'。在 verdicts.jsonl 旁增加第三段遥测；唯一权威判定 is_degraded = (verdict_state.upper() in {'DEGRADED', 'FAILED', 'CANCELLED'}) or (degraded_reason is not None)；若 is_degraded 为 True 则强制 effective_findings = '' 且 premises_parsed_count = 0；否则 parse_premises(findings)；三布尔 presence 准确映射；写入 _get_consultation_telemetry_sink(path)；精准捕获 (filelock.Timeout, OSError, ValueError) fail-open。
observability_policy.py：声明 ConsultationTelemetryRecord（schema_version=1 居末尾）；扩展 ObservabilityDecision 新增 telemetry_enabled: bool、telemetry_path: str（默认 .agents/logs/telemetry/consultation_telemetry.jsonl，DISABLED 置 False）。实现 FileConsultationTelemetrySink（lock_path 默认为 f'{path}.lock'，在 try 块内、open 之前执行 os.makedirs(os.path.dirname(self.path), exist_ok=True)，精准捕获三异常）与 @functools.lru_cache(maxsize=32) 模块级工厂 _get_consultation_telemetry_sink(path)；导出 def reset_consultation_telemetry_sink_cache() -> None: _get_consultation_telemetry_sink.cache_clear()，docstring 声明“测试 fixture 专用，生产禁止调用”。
test_premises_parsing.py 断言矩阵：(a) 单块全标签 falsifiable 真 -> len==1 且 r[0].falsifiable is True；(b) 无标签 -> []；(c) falsifiable 非真 -> False；(d) 13 块 -> len==12；(e) premise 长度 2049 且末字段 falsifiable 为 true -> r[0].falsifiable is False（覆写优先级 > token）且 len(r[0].premise) == 2049；(f) flip_condition 长度 2049 且 falsifiable 为 true -> r[0].falsifiable is False；(g) premise 长度 2048 且 falsifiable 为 true -> r[0].falsifiable is True（悬崖双锚 2048 vs 2049）；(h) premise 值含额外冒号 -> partition 首冒号分割保留全值；(i) 无冒号行跳过；(j) 手工构造 PremiseRecord 列表：空列表 [] 通过；含空 premise 抛 AssertionError；13 条抛 AssertionError；字段长度 2049 抛 AssertionError；(k) test_premises_pattern_has_no_textual_corruption 断言反斜杠空白元字符、无 '/s'、无双重转义，合法块匹配成功；(l) 大小写与首尾空白归一化：'TRUE' / '  true  ' / 'Yes' 均识别为真。
test_consultation_telemetry.py 断言矩阵：(a) COMPLETED 状态写 1 行 jsonl，job_id 为 ''，session_id 精确匹配；(b1) DEGRADED 状态 -> premises_parsed_count == 0 且 is_degraded is True；(b2) COMPLETED 但 degraded_reason='timeout' -> premises_parsed_count == 0 且 is_degraded is True；(b3) CANCELLED 状态且非空 findings -> premises_parsed_count == 0 且 is_degraded is True；(c) DISABLED 模式 telemetry_enabled is False 不写文件且 sink 未被构造；(d) filelock.Timeout 竞争超时 emit 不抛异常；(e) enforce_unified_log_quota 执行后 telemetry.jsonl 保持存活；(f) SUT 身份等价断言 rec.prompt_hash == compute_prompt_hash(messages)；(g) 三锁路径两两不等；(h) 三布尔 presence 8 组组合覆盖；(i) _get_consultation_telemetry_sink lru_cache 按 path 分键；(m) test_telemetry_sink_cache_is_clearable：两次以不同 tmp_path 调用工厂后 currsize == 2；调用 reset_consultation_telemetry_sink_cache() 后 currsize == 0；cache_info().maxsize == 32。

#### 【防御与边缘校验】
P0' 反伪影语义锚定：任务单禁止出现正则字面量；空白匹配正确性由 test_premises_pattern_has_no_textual_corruption 反向锚定。
P1' 覆写优先级规范：超长强制覆写优先级严格高于 token 真值判定；由 (e)/(f)/(g) 三条断言联合锁定。
P2' assert 空列表契约：records == [] 合法通过，杜绝 false-red 陷阱。
P3 SSOT 埋点：遥测埋点统一下沉至 _emit_consultation_audit；rec.prompt_hash == compute_prompt_hash(messages) 断言哈希身份等价。
D-A 唯一权威判定：is_degraded = (verdict_state.upper() in {'DEGRADED','FAILED','CANCELLED'}) or (degraded_reason is not None)。
D-D keyword-only 契约：*, findings, verdict_state 均为 keyword-only。
D1' 锁物理隔离：FileConsultationTelemetrySink.lock_path 后缀独立；三锁路径两两不等。
N3' GC 免疫：遥测落 .agents/logs/telemetry/（log_naming.py:433 GC 仅枚举 *.log 并排除 *.jsonl）；测试 (e) 覆盖存活。
W10 作用域澄清：遥测写出发生于 reviewer 作业终态 _emit_consultation_audit 路径，与 verdicts.jsonl 同层级，不属于 W10 监管的 poll/watch 只读推演路径。
Fail-Open 精准捕获：仅捕获 (filelock.Timeout, OSError, ValueError) 写 sys.stderr，严禁 bare except。
INV-3/4/6 通道契约：DEGRADED 强制 findings=''；全程零 print 仅 stderr；遥测不触碰 sandbox 只读路径。
lru_cache 隔离：测试一律使用 tmp_path 隔离路径，按 path 分键。
A1 调用方契约：assert_premises_wellformed docstring 显式声明禁止 parse→assert 生产连线。
A2 目录自愈：emit_telemetry 在 try 内、open 前执行 os.makedirs(dirname, exist_ok=True)，杜绝 FileNotFoundError。
A3 句柄回收：reset_consultation_telemetry_sink_cache() 供 fixture 清理，杜绝 Windows 下 FileLock 句柄滞留。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_premises_parsing.py plugins/quench-dev-tasks/server/tests/test_consultation_telemetry.py -v -q && pytest plugins/quench-dev-tasks/server/tests/test_poll_nonterminal_contract_v2.py plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py -q
```

---

