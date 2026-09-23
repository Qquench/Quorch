# 2026-09-21_stage5_vendor_neutrality_and_consultation Development Tasks / 开发任务单

> **路线图来源**: `docs/roadmap/v1.05_vendor_neutral_reviewer_and_adhoc_consultation.md`
> **批次划分**: Batch 1（厂商中立重构，任务 1.1–1.3）→ Batch 2（即时咨询工具与防角色扮演治理，任务 2.1–2.3）
> **串行约束**: 严格遵守单核串行施工原则，同一时间仅允许一个任务处于 `🔨 执行中`；Batch 1 全绿归档后方可启动 Batch 2（Batch 2 直接依赖 Batch 1 产出的 `create_reviewer_client` 工厂与 `ProviderPreset` 契约）。
> **语言约定**: 本任务单采用中文正文与中文六字段标题，执行时严禁翻译或改写为英文标题（镜像契约）。
> **回归基线**: `pytest plugins/quench-dev-tasks/server/tests -q` 当前 167 项全绿，任何批次交付必须保持 100% 通过且零破坏性。

---

## 批次 1 (Batch 1): 厂商中立客户端重构与硬编码清洗

### 任务 1.1 ✔️ 已完成 — 将 DeepSeekClient 重构为厂商中立 ReviewerClient 并抽象通用推理草稿协议探针 (Vendor-Neutral ReviewerClient & Generic CoT Probe)

#### 【涉及文件】

- `[MODIFY]` `plugins/quench-dev-tasks/server/reviewer_engine.py`
- `[NEW]` `plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py`

#### 【缺陷根因与修改目标】

**根因**：`reviewer_engine.py` 把上游厂商协议差异（思考链字段名、Prompt Cache 计费字段、401 报错文案、默认 Key 环境变量候选）全部硬编码为 DeepSeek 单厂商假设。后果是：接入任意 OpenAI 兼容端点（vLLM / LM Studio / Azure 代理）时，流式解析会**静默丢弃** `reasoning_content` 思考链与缓存命中计量（不报错、不告警，日志看起来"正常"），而 401 时会抛出误导性的厂商专属提示，诱导开发者去排查错误的环境变量。

**目标**：以单一 `ReviewerClient` 承载任意 `/chat/completions` 兼容端点；思考链与用量计量通过**字段路径探针**（Probe）无差别提取；全部异常文案参数化为 `(provider_label)` 占位，核心模块内不得残留任何厂商常量；保留一个带弃用告警的 `DeepSeekClient` 兼容别名，保证 Stage 5 期间外部调用点零破坏。

#### 【目标签名与类型契约】

```python
# ---- 数据结构 ----
@dataclass(frozen=True)
class UsageSnapshot:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0          # Prompt Cache 命中（跨厂商归一化）
    reasoning_tokens: int = 0
    provider_label: str = "generic"  # 运行时注入，禁止模块级厂商常量

@dataclass(frozen=True)
class StreamChunk:
    text: str = ""
    reasoning: str = ""
    usage: UsageSnapshot | None = None
    done: bool = False

# ---- 通用探针（纯函数，无副作用，禁止抛异常）----
def extract_reasoning_text(payload: Mapping[str, Any]) -> str: ...
def extract_cached_tokens(payload: Mapping[str, Any]) -> int: ...
def extract_usage(payload: Mapping[str, Any]) -> UsageSnapshot: ...

# ---- 客户端 ----
class ReviewerClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env: str | None = None,
        provider_label: str = "generic",
        timeout_seconds: int = 60,
        max_retries: int = 2,
        thinking: bool = True,
        reasoning_effort: Literal["low", "medium", "high"] = "high",
        sink: "Sink | None" = None,
    ) -> None: ...

    async def stream_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        session_id: str | None = None,
    ) -> AsyncIterator[StreamChunk]: ...

# ---- 异常（文案禁止厂商常量）----
class ReviewerError(RuntimeError): ...
class ReviewerAuthError(ReviewerError): ...            # HTTP 401 / 403
class ReviewerTimeoutError(ReviewerError): ...
class ReviewerNotConfiguredError(ReviewerError): ...

# 文案模板（参数化，非硬编码）
f"[HTTP {status}] Reviewer API ({self.provider_label}) 鉴权失败：请检查环境变量 {self.api_key_env} 是否已导出"
f"[HTTP {status}] Reviewer API ({self.provider_label}) 请求被拒：{detail}"

# ---- PEP 562 兼容层（模块级）----
def __getattr__(name: str) -> Any:
    if name == "DeepSeekClient":
        warnings.warn("DeepSeekClient 已弃用，请改用 ReviewerClient", DeprecationWarning, stacklevel=2)
        return ReviewerClient
    raise AttributeError(name)
```

#### 【分步改造指引】

1. **探针优先**：新增模块级私有 `_dig(payload: Mapping[str, Any], *path: str) -> Any`，逐级 `.get()` 取值，任一层缺失即返回 `None`。思考链按以下顺序探测首个非空字符串：
   `("delta","reasoning_content")` → `("delta","thought")` → `("delta","reasoning")` → `("message","reasoning_content")` → `("message","thought")` → `("reasoning_content",)` → `("thought",)` → `("reasoning",)`；全部未命中返回 `""`。
2. **缓存计量归一化**：`extract_cached_tokens` 依次探测 `usage.prompt_cache_hit_tokens`、`usage.prompt_tokens_details.cached_tokens`、`usage.cache_read_input_tokens`、`usage.cached_tokens`，缺失或非 int 返回 `0`。
3. **统一请求路径**：`stream_chat` 统一 `POST {base_url}/chat/completions`（若 `base_url` 已以 `/v1` 或 `/chat/completions` 结尾则做幂等拼接，不重复追加 `/v1`），`stream=True`；逐行消费 SSE，识别 `data: ` 前缀，遇 `[DONE]` 置 `done=True` 并 break。**单行 JSON 解析失败只写 sink 的 debug 级别并继续，禁止中断整条流**。
4. **鉴权解析去硬编码**：构造签名中 `api_key_env` 默认值改为 `None`，运行时 `os.environ.get(api_key_env)`；当 `api_key_env` 为空且 `base_url` 主机为 `127.0.0.1` / `localhost` / `::1` 时**跳过 Authorization 头**（本地 Ollama / vLLM 场景）。
5. **异常映射**：HTTP 401/403 → `ReviewerAuthError`；`asyncio.TimeoutError` → `ReviewerTimeoutError`；`httpx.ConnectError` / `httpx.ReadError` / `httpx.RemoteProtocolError` → `ReviewerError`；所有 message 中**不得出现任何厂商字面量**。
6. **重试策略**：仅对非 4xx 的 `ReviewerError` 重试，指数退避，次数上限 `max_retries`；`ReviewerAuthError` 与 `ReviewerNotConfiguredError` **严禁重试**（避免撞锁账号 / 无效空转）。
7. **兼容层**：文件末尾追加 PEP 562 `__getattr__` 兼容别名，保证 `from reviewer_engine import DeepSeekClient` 在 Stage 5 期间仍可用（触发 `DeprecationWarning`）。
8. **新增 `tests/test_reviewer_engine_probe.py`**：
   - 参数化 9 组字段路径组合，断言 `extract_reasoning_text` 命中值一致；
   - 参数化 4 种 usage 形态，断言 `extract_cached_tokens` 返回值正确、缺失时为 `0`；
   - 构造 `provider_label="ollama"` 的客户端，模拟 401 响应，断言异常文案包含 `"ollama"` 且**不包含** `"deepseek"`（大小写不敏感）；
   - 断言 `DeepSeekClient` 别名可用且触发 `DeprecationWarning`。

#### 【防御与边缘校验】

- **探针必须是纯函数**：对 `None`、空 dict、字段值为 `None`、字段值为非字符串（int / list / dict）的输入，一律返回 `""` / `0`，**绝不抛** `AttributeError` / `TypeError`。
- **SSE 单行长度上限**：单行缓冲超过 1 MiB 即截断并记 debug 日志，防止恶意或异常端点撑爆内存。
- **生成器提前关闭**：使用 `async with httpx.AsyncClient(...).stream(...)` 承载，生成器被 `aclose()` 时必须释放连接，防止长会话连接泄漏耗尽 fd。
- **弃用告警与 `filterwarnings=error` 冲突**：若仓库 `pytest.ini` / `pyproject.toml` 配置了 `filterwarnings = error`，`DeprecationWarning` 会让既有测试失败；此时将告警降级为 sink 一次性 `warn` 日志，并把兼容层用例改为断言"别名可用且不抛异常"。**无论何种情况都不得删除兼容层**。
- **模块归属兜底**：若实测发现 `DeepSeekClient` 定义位于 `reviewer_client.py` 而非 `reviewer_engine.py`，则在 `reviewer_engine.py` 中完成等价重构并保留 re-export 中转，且必须在任务单追加一行实测结论（禁止在无记录的情况下改变目标文件）。
- **流式分块不得跨 chunk 切割 UTF-8 多字节字符**：使用增量解码器（`codecs.getincrementaldecoder("utf-8")`）而非逐行 `bytes.decode`，防止中文思考流出现乱码。

#### 【DoD 验证命令】

```
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py -q
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py -q
pytest plugins/quench-dev-tasks/server/tests -q
```

**强制断言要求**：`test_reviewer_engine_probe.py` 必须包含 ≥ 14 条有效断言（9 组探针字段路径 + 4 组 usage 形态 + 401 文案中立性 + 别名弃用行为）；第二条命令证明既有引擎测试在兼容层保护下 **100% 保持通过**（零破坏性回归）；第三条命令证明全量套件无回归。

---

### 任务 1.2 ✔️ 已完成 — 引入 PROVIDER_PRESETS 声明式中立工厂并清除 server.py 厂商硬分支 (Declarative Provider Registry & Branch Removal)

#### 【涉及文件】

- `[MODIFY]` `plugins/quench-dev-tasks/server/project_config.py`
- `[MODIFY]` `plugins/quench-dev-tasks/server/server.py`
- `[NEW]` `plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py`

#### 【缺陷根因与修改目标】

**根因**：`project_config.py` 的 `ReviewerEngineConfig` 把 DeepSeek 的 `base_url` 与 Key 环境变量当成**全局默认值**，`server.py` 又直接 `DeepSeekClient(...)` 实例化并用 `if provider in ("deepseek", "deepseek-compatible")` 做分支判断。后果是：新增任意 OpenAI 兼容端点（vLLM、LM Studio、Azure 代理、自建网关）必须修改三处源码，且默认配置会诱导用户把厂商 Key 注入到未声明的环境变量上；`provider` 未配置时链路直接抛异常中断 MCP stdio 会话，而非干净降级。

**目标**：默认值净化为 `provider="none"`；全部端点差异收敛进单一**声明式** `PROVIDER_PRESETS` 注册表（唯一允许出现厂商字面量的区域）；`server.py` 只调用 `create_reviewer_client(config)` 工厂，源码中不再出现任何厂商名分支；引擎缺失时返回结构化降级卡而非抛栈。

**工厂置于 `project_config.py` 的设计理由**：`provider → endpoint` 的唯一 SSOT 必须与配置模型同处一文件，避免 `engine` 与 `config` 形成双向依赖；`ReviewerClient` 采用**函数体内延迟导入**以规避循环导入。此为主动架构决策，非偷懒合并。

#### 【目标签名与类型契约】

```python
# ---- project_config.py ----
class ReviewerEngineConfig(BaseModel):
    mode: Literal["auto", "subagent", "engine", "manual"] = "auto"
    strategy_order: list[Literal["subagent", "engine", "manual"]] = ["subagent", "engine", "manual"]
    provider: str = "none"                       # 不再默认任何厂商
    model: str = "default"                       # 通用占位，不再默认厂商模型名
    api_key_env: str | None = None               # 不再默认厂商 Key 变量名
    base_url: str = ""                           # 空 -> 由 preset 推导；preset 亦缺失 -> 判定未配置
    thinking: bool = True
    reasoning_effort: Literal["low", "medium", "high"] = "high"
    timeout_seconds: int = 60
    max_retries: int = 2
    max_tool_hops: int = 3

@dataclass(frozen=True)
class ProviderPreset:
    base_url: str
    api_key_env: str | None
    requires_thinking_flag: bool = False

# -- vendor-presets:start
PROVIDER_PRESETS: Mapping[str, ProviderPreset] = MappingProxyType({
    "openai":  ProviderPreset("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "deepseek": ProviderPreset("https://api.deepseek.com",  "DEEPSEEK_API_KEY"),
    "ollama":  ProviderPreset("http://127.0.0.1:11434/v1", None),
    "vllm":    ProviderPreset("http://127.0.0.1:8000/v1",  None),
    "custom":  ProviderPreset("", None),
    "none":    None,
})
PROVIDER_ALIASES: Mapping[str, str] = MappingProxyType({
    "deepseek-compatible": "deepseek",
    "openai-compatible": "openai",
})
# -- vendor-presets:end

def resolve_preset(provider: str) -> ProviderPreset | None: ...

def create_reviewer_client(
    config: ReviewerEngineConfig,
    *,
    sink: "Sink | None" = None,
) -> "ReviewerClient | None":
    """返回 None 表示引擎未配置（调用方必须走降级卡，严禁自行扮演 Reviewer）。"""
```

#### 【分步改造指引】

1. **建立声明式注册表**：把 `provider → (base_url, api_key_env)` 全部收敛进 `# -- vendor-presets:start` / `# -- vendor-presets:end` 哨兵块，用 `types.MappingProxyType` 冻结为只读映射；别名表 `PROVIDER_ALIASES` 同样置于块内（任务 1.3 的中立性扫描器仅豁免该块）。
2. **净化默认值**：按上述签名改写 `ReviewerEngineConfig`，`provider` 默认 `"none"`、`model` 默认 `"default"`、`api_key_env` 默认 `None`、`base_url` 默认 `""`。
3. **迁移兼容（只读补全，绝不回写）**：在 `schema_version` 迁移函数中增加一条 deprecated 读取路径——当用户旧配置含 `provider: "deepseek"`／`"deepseek-compatible"` 且未显式声明 `base_url` 时，从 `PROVIDER_PRESETS` 补齐 `base_url` 与 `api_key_env`，并通过 `sink.warn` 提示"已按旧配置自动补全，建议显式声明"。该兼容行必须带行内标记 `# vendor-literal: allow`。**严禁把厂商名写回任何默认值，严禁改写用户 YAML 落盘。**
4. **工厂语义（三态明确）**：
   - `provider in ("none", "", None)` → 返回 `None`（调用方据此返回降级卡）；
   - `provider` 未在注册表且 `base_url` 为空 → 抛 `ReviewerNotConfiguredError`（携带配置修复指引）；
   - `provider` 未在注册表但 `base_url` 非空 → 按通用路径 `ProviderPreset(base_url=配置值, api_key_env=配置值)` 构造（这正是 vLLM / LM Studio / 自建网关的接入方式，不得强迫用户新增注册表项）。
5. **清除 `server.py` 硬分支**：删除全部 `if config.reviewer_engine.provider in (...)` 判断与 `DeepSeekClient(...)` 直接实例化，统一替换为：

   ```python
   client = create_reviewer_client(config.reviewer_engine, sink=get_live_sink())
   if client is None:
       return _degraded_card(reason="reviewer_not_configured", config=config)
   ```

   `_degraded_card` 返回结构化 dict：`{"status": "degraded", "reason": "reviewer_not_configured", "hint": <配置修复指引>, "handoff_prompt": <新会话切换旗舰模型提示>}`，**绝不包含任何伪造的审查正文**。
6. **零残留自检**：执行 `grep -cin "deepseek" plugins/quench-dev-tasks/server/server.py`，结果必须为 `0`。
7. **冒烟自检（不联网）**：构造 `ReviewerEngineConfig(provider="vllm", base_url="http://127.0.0.1:8000/v1", model="qwen2.5")`，断言 `create_reviewer_client` 返回实例的 `base_url` / `model` / `provider_label` 与配置一致且未发起任何网络请求。
8. **新增 `tests/test_reviewer_factory_neutrality.py`**：断言 `provider="none"` 返回 `None`；断言未知 provider + 空 base_url 抛 `ReviewerNotConfiguredError`；断言未知 provider + 非本地 base_url 且无 `api_key_env` 抛 `ReviewerNotConfiguredError`；断言 `deepseek-compatible` 与 `deepseek` 解析出**同一个** preset 对象；断言 `PROVIDER_PRESETS` 赋值触发 `TypeError`（只读性）；断言默认配置下所有字段均无厂商字面量。

#### 【防御与边缘校验】

- **URL 校验**：`base_url` 必须经 `urllib.parse.urlparse` 校验——拒绝非 `http`/`https` scheme、拒绝空 host、拒绝含 userinfo（`@`，防凭据泄漏进日志）的 URL。
- **本地端点豁免鉴权，远端端点强制鉴权**：host 为 `127.0.0.1` / `localhost` / `::1` 时允许 `api_key_env=None`；其余 host 在 `api_key_env` 为空时**必须**抛 `ReviewerNotConfiguredError`，杜绝空 Key 明文请求。
- **迁移幂等性**：重复调用 `load_workspace_config` 不得重复告警（用已见 provider 集合去重），且不得产生任何磁盘写入副作用。
- **`strategy_order` 兜底不变量**：`provider="none"` 时 `strategy_order` 仍必须保留 `manual` 项，保证 `mode="auto"` 链路降级而非抛异常中断 MCP 会话。
- **别名单映射**：`deepseek-compatible` 与 `openai-compatible` 必须映射到既有 preset 键，禁止在注册表中产生语义重复的两个条目（防止 preset 数量随别名的增加而无序膨胀）。
- **禁止阻塞事件循环**：工厂与其校验逻辑内不得出现同步 `httpx.get` / `requests` 调用，全部 I/O 必须为 `async`。
- **配置热加载安全**：`PROVIDER_PRESETS` 为 `MappingProxyType`，任何运行时篡改尝试必须抛 `TypeError` 且不污染已加载会话。

#### 【DoD 验证命令】

```
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py -q
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py -q
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py -q
pytest plugins/quench-dev-tasks/server/tests -q
```

**强制断言要求**：中立工厂测试必须包含 ≥ 8 条断言，其中至少两条为**负向断言**（未知 provider 必须抛 `ReviewerNotConfiguredError`；`PROVIDER_PRESETS` 运行时赋值必须抛 `TypeError`）；第三条命令证明任务 1.1 的探针用例在重构后仍全绿；第四条命令证明全量 167+ 套件零破坏性。

---

### 任务 1.3 ✅ 已确认 — 建立源码级中立性防回归扫描闸门并重构引擎既有测试为协议中立形态 (Neutrality Regression Gate)

#### 【涉及文件】

- `[NEW]` `plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py`
- `[MODIFY]` `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py`

#### 【缺陷根因与修改目标】

**根因**：本次清洗**没有任何机械化闸门**守护——今天删除 `DeepSeekClient`，明天任何一次提交都可以悄悄把厂商名、厂商 Key 环境变量或厂商域名重新写回核心模块，且 CI 无法察觉（因为功能测试依然全绿）。同时 `test_reviewer_engine.py` 内部仍以 DeepSeek 语义命名 fixture 与断言，既误导后续维护者，也会在下一轮重构时产生误报，掩盖真实回归。

**目标**：新增读取源码文本的**中立性扫描闸门**（带两条最小且可审计的豁免规则、且自带"植入即检出"的自证用例防止假绿）；同步把 `test_reviewer_engine.py` 重写为协议中立形态（去厂商化命名、断言只依赖注入的 `provider_label`），并消除与任务 1.1 探针测试的重复覆盖。

#### 【目标签名与类型契约】

```python
SCAN_ROOT: Path = Path("plugins/quench-dev-tasks/server")
SCAN_GLOB: str = "*.py"                       # 仅顶层，不递归
EXCLUDED_DIRS: tuple[str, ...] = ("tests", "adapters", "hooks", "__pycache__")

BANNED_VENDOR_TOKENS: tuple[str, ...] = (
    "deepseek", "claude", "gemini", "mistral", "qwen", "llama", "gpt-4", "gpt-3", "o1-",
)
BANNED_VENDOR_HOSTS: tuple[str, ...] = (
    "api.openai.com", "api.deepseek.com", "api.anthropic.com", "generativelanguage.googleapis.com",
)

PRESET_BLOCK_START: str = "# -- vendor-presets:start"
PRESET_BLOCK_END: str = "# -- vendor-presets:end"
LINE_PRAGMA: str = "# vendor-literal: allow"

@dataclass(frozen=True)
class VendorViolation:
    path: str
    lineno: int
    token: str
    snippet: str

def iter_scannable_lines(root: Path) -> Iterator[tuple[Path, int, str]]: ...
def find_vendor_violations(root: Path) -> list[VendorViolation]: ...
```

> **注**：`"openai"` **不在** token 黑名单中——"OpenAI-compatible protocol" 是合法的中立协议术语；网关与文档中的 `https://api.openai.com/v1` 由 `BANNED_VENDOR_HOSTS` 在同一豁免框架下管控。`docs/`、`templates/`、`.cursorrules` **不在扫描范围**：模板中保留厂商接入示例是合法的。

#### 【分步改造指引】

1. **扫描范围限定**：`iter_scannable_lines` 仅遍历 `SCAN_ROOT.glob("*.py")`，**不递归子目录**（`tests/`、`adapters/`、`hooks/` 天然被排除）；明确跳过 `__pycache__`、隐藏文件、非 `*.py` 后缀文件。
2. **唯一的两种豁免规则（都必须可审计）**：
   - a. 行内含 `# vendor-literal: allow` → 跳过该行；
   - b. 位于 `PRESET_BLOCK_START` 与 `PRESET_BLOCK_END` 之间的行 → 跳过；跨行状态用 `in_preset_block: bool` 维护，遇 `start` 置真、遇 `end` 置假；**文件读取结束时若仍为真 → 直接断言失败**（防止用未闭合哨兵块吞掉整份文件）。
3. **匹配逻辑**：统一 `line.casefold()` 后做子串匹配；命中任一 `BANNED_VENDOR_TOKENS` 或 `BANNED_VENDOR_HOSTS` 即追加一条 `VendorViolation`（含 `path` / `lineno` / `token` / 截断到 120 字符的 `snippet`，便于定位）。
4. **测试用例矩阵（五条，缺一不可）**：
   - `test_core_modules_have_no_vendor_literals`：断言 `find_vendor_violations(SCAN_ROOT) == []`；
   - `test_scanner_detects_planted_vendor_literal`：在 `tmp_path` 伪造一个含 `DeepSeekClient` 的模块，断言扫描器**必须命中**——这是防止"扫描器恒空"假绿的自证断言；
   - `test_pragma_suppresses_single_line_only`：断言带 pragma 的行被豁免，且**其下一行**仍可被检出；
   - `test_unclosed_preset_block_fails`：断言未闭合哨兵块直接失败；
   - `test_preset_registry_is_only_exempted_region`：断言 `project_config.py` 在哨兵块之外确实不存在厂商字面量。
5. **重构 `test_reviewer_engine.py`**：将 DeepSeek 语义 fixture 改名为协议中性命名（如 `PROBE_PAYLOAD_CASES` / `HTTP_ERROR_CASES`）；HTTP 401 用例断言文案只依赖**注入的** `provider_label`（构造为 `"ollama"` 断言不含 `"deepseek"`）；`DeepSeekClient` 相关用例改为 `ReviewerClient` + 一条兼容性别名弃用断言。
6. **去重纪律**：若 `test_reviewer_engine_probe.py`（任务 1.1）已覆盖同一断言语义，本条**只做去厂商化改名与断言收敛**，严禁复制粘贴产生重复用例；重复覆盖率提升不计入本任务成果。

#### 【防御与边缘校验】

- **防自我命中**：本测试文件位于 `tests/` 下天然不被扫描；但必须显式断言扫描结果中不存在任何以 `test_` 开头的路径，防止未来把 `SCAN_GLOB` 改为 `**/*.py` 时扫描器命中自身导致自证失败。
- **编码健壮性**：文件读取必须使用 `encoding="utf-8", errors="replace"`，防止残余二进制脏文件触发 `UnicodeDecodeError` 使闸门失效。
- **性能护栏**：扫描耗时必须 < 200 ms；超时即视为扫描根被误设为递归，直接失败（顶层文件数量有限，超时必定是配置错误）。
- **哨兵块不变量**：`PRESET_BLOCK_START` 与 `END` 必须成对且不得嵌套；出现两个 `start` 或 `end` 早于 `start` 一律失败。
- **禁止整文件豁免**：豁免粒度只有"单行 pragma"与"哨兵块区间"两级；任何绕过手段（如在文件头加 pragma 覆盖全文）在代码评审中必须被驳回。
- **负向用例必须真实失败**：`test_scanner_detects_planted_vendor_literal` 若通过空结果集"恰好"通过，等同于假绿——必须断言命中条数 `>= 1` 且 `token == "deepseek"`。
- **不得误伤中文注释**：匹配基于 `casefold()` 的子串，不做正则词边界，避免中文语境下 `DeepSeek客户端` 这类连写漏判。

#### 【DoD 验证命令】

```
pytest plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py -q
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py -q
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_engine_probe.py -q
pytest plugins/quench-dev-tasks/server/tests -q
```

**强制断言要求**：中立性扫描器必须通过"植入即检出"自证用例（`test_scanner_detects_planted_vendor_literal` 断言命中 `>= 1` 条且 token 为 `deepseek`），否则本闸门视为假绿，任务不予验收；第四条命令证明 Batch 1 全量交付后 167+ 套件 100% 全绿，批次可独立回归归档。

---

## 批次 2 (Batch 2): 即时架构咨询工具 dev_reviewer_consult 与防角色扮演治理

> **批次前置**：Batch 1 已交付 `create_reviewer_client` 工厂与 `ProviderPreset` 契约、`ReviewerClient` 通用探针、中立性扫描闸门。本批次**严禁**以任何形式新增厂商字面量（否则 1.3 的闸门会在本批次 DoD 中直接红）。

### 任务 2.1 ⬜ 待确认 — 实现免任务单绑定的架构咨询原子工具 dev_reviewer_consult (Ad-Hoc Consultation Tool)

#### 【涉及文件】

- `[MODIFY]` `plugins/quench-dev-tasks/server/server.py`
- `[NEW]` `plugins/quench-dev-tasks/server/consultation.py`
- `[NEW]` `plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py`

#### 【缺陷根因与修改目标】

**根因**：现有 11 个工具中的 10 个全部死死绑定 `dev_tasks_*` 任务单生命周期。当开发者突然产生架构灵感、需要比对技术选型，或希望对现有模块做只读诊断时，**必须先伪造一份 Task 1.0 草案**才能触发外部审查引擎——治理仪式感直接阻断了探索性研发的流畅度。更严重的是，由于缺少针对自由问答的专用 MCP 工具，主模型会在当前对话中"角色扮演"Reviewer，彻底摧毁"异构外部强推理大脑打破执行模型自证偏见"的立项初衷。

**目标**：新增 `dev_reviewer_consult` 原子工具——以 `workspace_root + query` 为最小输入，自动挂载全局架构基线作为**稳定可缓存的静态前缀**，按需切片关键代码上下文（防 Token 泛滥），把思考流实时分块落盘至 `.agents/logs/reviewer/`，并在引擎缺失/超时/离线时返回**结构化降级卡**而非伪造结论。工具本体严禁写入任何源码文件。

#### 【目标签名与类型契约】

```python
# ---- consultation.py ----
ConsultMode = Literal["critique", "evaluate", "brainstorm", "audit"]

@dataclass(frozen=True)
class CodeSlice:
    rel_path: str
    start_line: int
    end_line: int
    text: str                       # 头部含 "# file: <rel_path>:<start>-<end>" 锚点

@dataclass(frozen=True)
class ConsultRequest:
    workspace_root: str
    query: str
    context_files: tuple[str, ...] = ()
    mode: ConsultMode = "critique"
    max_hops: int = 1               # 允许的上下文扩展轮次，钳制 [0, 3]
    session_id: str | None = None

@dataclass(frozen=True)
class ConsultResult:
    status: Literal["ok", "degraded"]
    session_id: str
    mode: ConsultMode
    findings: str
    log_path: str
    usage: dict[str, int]
    truncated: bool
    skipped_files: list[str]
    degraded_reason: str | None = None      # "reviewer_not_configured" | "timeout" | "auth" | "network" | "reasoning_budget_exceeded"
    handoff_prompt: str | None = None
    suggested_task_draft: dict[str, Any] | None = None

def sanitize_session_id(raw: str | None) -> str: ...
def resolve_context_files(workspace_root: str, rel_paths: Sequence[str], *, max_files: int = 6, window_lines: int = 50) -> tuple[list[CodeSlice], list[str], bool]: ...
def build_static_prefix(workspace_root: str, config: Any) -> str: ...
def render_mode_prompt(mode: ConsultMode, query: str, slices: Sequence[CodeSlice]) -> str: ...
async def run_consultation(req: ConsultRequest, *, config: Any, ctx: Any = None) -> ConsultResult: ...

# ---- server.py ----
@mcp.tool()
async def dev_reviewer_consult(
    workspace_root: str,
    query: str,
    context_files: list[str] | None = None,
    mode: str = "critique",
    max_hops: int = 1,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Directly consult the senior architecture Reviewer engine without creating a DevTask.
    Mounts the global architecture baseline as a prompt-cache-friendly static prefix, streams
    reasoning CoT to .agents/logs/reviewer/latest-<session_id>.log, and returns deep architectural
    critique, trade-off analysis, or spec suggestions. Never mutates source files.

    免任务单地直接咨询资深架构 Reviewer：挂载全局架构基线（命中 Prompt Cache），思考流实时落盘，
    返回红队挑刺 / 方案权衡 / 规格建议，并在引擎未配置时显式降级（严禁就地角色扮演）。
    """
```

#### 【分步改造指引】

1. **模块归属先探明**：执行 `grep -rn "class PromptAssembler" plugins/quench-dev-tasks/server` 与 `grep -rn "class CodeExplorer" plugins/quench-dev-tasks/server` 确认真实模块名与 API。若已存在则复用；若缺失则在 `consultation.py` 内实现满足本任务契约的最小内联版本（**不得为此新增第四、第五个文件**）。
2. **路径安全解析 `resolve_context_files`**：每个相对路径经 `os.path.realpath` 归一后，用 `os.path.commonpath([real_path, real_workspace_root]) == real_workspace_root` 校验必须落在工作区内。越界（`..`、绝对路径、UNC、跨盘符、符号链接外逃）一律**跳过并计入 `skipped_files`，不得抛异常**；超出 `max_files`（默认 6）时截断并置 `truncated=True`。
3. **切片读取（防 Token 泛滥）**：对每个文件产出 ≤ `window_lines`（默认 50，硬下限 30）的高危窗口，切片头部写入 `# file: <rel_path>:<start>-<end>` 锚点；**严禁整文件回填**。总注入预算上限 12000 字符，超限截断并置 `truncated=True`。
4. **静态前缀 `build_static_prefix`**：拼装 `quench_stack.yaml` 声明的 `architecture_doc` 全文 + 六大核心字段契约 + 审查纪律摘要。结果按 `(real_workspace_root, 各源文件 mtime 元组)` 做**进程内 dict 缓存 + 显式锁**（`functools.lru_cache` 不适用于 dict 形态参数）。前缀内容必须**字节级稳定**：严禁插入时间戳、随机数、绝对行号、会话 ID 等易变内容，否则 Prompt Cache 全额失效。
5. **模式提示词 `render_mode_prompt`**：
   - `critique`：红队挑刺，必须给出风险等级与具体触发场景，**禁止**风格偏好类意见；
   - `evaluate`：技术选型 A/B 权衡表（收益 / 成本 / 风险 / 回退路径）；
   - `brainstorm`：发散方案 + 可行性标注 + 最小验证实验；
   - `audit`：只读一致性审计（契约声明 vs 实际实现漂移点）。
6. **上下文扩展轮次 `max_hops`**：第 1 轮返回后，若响应包含 `<<<NEED-FILES>>> ... <<<END>>>` 包裹块，则解析其中路径再补充一轮切片（每轮仍受 `max_files`/`window_lines`/总预算约束），最多 `max_hops` 轮；钳制 `[0, 3]`，越界在工具层直接返回结构化错误。
7. **流式落盘**：`RotatingFileSink(Path(workspace_root)/".agents/logs/reviewer"/f"latest-{session_id}.log", max_bytes=2_000_000, backup_count=2)`；思考分块每累计 512 字符或每 200 ms flush 一次，行格式 `<ISO8601> [reasoning] <chunk>`，`tail -f` 可直接阅读。
8. **低频心跳**：以 1.0 s 间隔（`asyncio` 定时任务，**不得 `await asyncio.sleep` 阻塞主流**）上报 `progress_pct` 与 `hops`；`ctx is None` 或 `ctx.report_progress` 抛异常时**静默吞掉**，绝不中断审查。
9. **超时熔断**：`await asyncio.wait_for(_stream_loop(), timeout=config.reviewer_engine.timeout_seconds)`（兼容 3.10，不用 `asyncio.timeout`）；超时 → `status="degraded"`, `degraded_reason="timeout"`，**保留已落盘的部分思考流，严禁删除日志**。
10. **降级链（核心防伪）**：`create_reviewer_client(...)` 返回 `None` 或抛 `ReviewerError` 子类时，一律转 `ConsultResult(status="degraded", findings="")`，并填充 `handoff_prompt`（提示开发者"开启新会话、切换到旗舰 Reviewer 模型、重新提问"）。**严禁**在 `findings` 中写入任何由主模型自产的"伪审查"正文。
11. **任务草案沉淀**：若响应尾部含 `<<<TASK_DRAFT>>> ... <<<END>>>` 包裹块，解析为 `suggested_task_draft` 字段返回；**不直接落盘、不直接调用 `dev_tasks_propose`**，由主模型决定是否转正。
12. **`server.py` 注册**：工具体只做参数校验——`mode` 必须属于 4 值枚举、`workspace_root` 必须为存在的目录、`query` 非空且长度 ≤ 8000 字符、`max_hops` 钳制在 `[0, 3]`；校验失败返回结构化 error dict 而非抛栈（避免反序列化层直接暴露调用栈）。docstring 与参数 `description` 必须双语显式声明。
13. **新增 `tests/test_consultation_context_guard.py`**：断言工具已注册可检索（FastMCP `get_tools()` / tool manager，若 API 名不同按实测调整）；断言 `..`、绝对路径、符号链接外逃三类输入均被拒绝且不抛异常；断言切片行数 ≤ `window_lines` 且总字符 ≤ 预算；断言 `build_static_prefix` 连续两次调用返回**完全相同的字符串**（缓存前缀稳定性）；断言 `sanitize_session_id` 拒绝含 `/`、`..`、`\`、长度 > 64 的输入。

#### 【防御与边缘校验】

- **只读铁律**：本工具路径内严禁写入任何源码文件，唯一允许的写入目标是 `<workspace_root>/.agents/logs/reviewer/`。
- **零 stdout 污染**：`run_consultation` 全路径内**禁止任何 `print`**；所有诊断走 sink。`sys.stdout` 严格保留给 JSON-RPC 帧。
- **同会话并发隔离**：以 `session_id` 为键维护进程内 `asyncio.Lock` 注册表（`WeakValueDictionary[str, asyncio.Lock]`），杜绝两条流交错写同一日志文件产生乱码；`session_id` 缺省使用 `uuid4().hex[:12]`，用户传值必须匹配 `^[0-9a-zA-Z_-]{1,64}$`（防文件名注入）。
- **日志磁盘配额**：`.agents/logs/reviewer/` 内保留最近 20 个 `latest-*.log`，超出按 mtime 淘汰；单文件 `max_bytes=2_000_000`，防止长会话撑爆磁盘。
- **思考预算天花板**：reasoning 累计超过 32000 tokens 立即中断，置 `degraded_reason="reasoning_budget_exceeded"`，并保留已落盘轨迹。
- **编码健壮性**：日志写入必须 `encoding="utf-8", errors="replace"`，防止非 UTF-8 端点响应触发 `UnicodeEncodeError` 中断整个 MCP 会话。
- **参数边界**：`query` 上限 8000 字符；`context_files` 上限 6 项；`max_hops` 钳制 `[0, 3]`；`mode` 非法值返回结构化错误并列出合法值。
- **降级不可静默**：任何 `degraded` 结果必须在 `handoff_prompt` 中显式提示"引擎未配置 / 离线，请勿以当前模型自行替代 Reviewer"，禁止用空 `findings` 伪装成功。
- **无网络挂死**：连接层必须复用 `ReviewerClient` 的 `timeout_seconds`，禁止出现无超时的裸 `await`。

#### 【DoD 验证命令】

```
pytest plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py -q
pytest plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py -q
pytest plugins/quench-dev-tasks/server/tests -q
```

**强制断言要求**：上下文守门测试必须包含 ≥ 10 条断言，其中至少三条为**负向断言**（越界路径必须被拒绝、非法 `session_id` 必须被拒绝、非法 `mode` 必须返回结构化错误而非抛栈）；第二条命令证明本任务未引入任何厂商字面量（Batch 1 闸门持续生效）；第三条命令证明新增工具未破坏既有 167+ 用例。

---

### 任务 2.2 ⬜ 待确认 — 硬化主模型防角色扮演红线与无引擎显式降级卡片 (Anti-Role-Playing Governance)

#### 【涉及文件】

- `[MODIFY]` `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`
- `[MODIFY]` `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`
- `[NEW]` `plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py`

#### 【缺陷根因与修改目标】

**根因**：治理规则库对这一漏洞**完全失语**。当用户说"让 Reviewer 审一下这段设计"时，主模型没有任何协议红线阻止它在当前对话中就地伪装 Reviewer 并输出结论——这正是"自证偏见（LLM-as-a-judge blindness）"：同一模型既实现又审查，无法证伪自身假设，评审结论退化为对自身假设的复述。此外，引擎未配置或 API 离线时缺乏显式降级契约，主模型倾向于用自身输出"填空"以维持对话流畅度，静默掩盖离线事实。

**目标**：在纪律规则中确立**防角色扮演红线**（明确意图识别 → 唯一合法通道 → 禁止就地输出）；在技能文档中补充分流决策树（自由咨询 vs 任务规约强化 vs 上报升级）；并以契约测试锁定两份文档的关键条款，防止后续被无声改写或回退。

#### 【目标签名与类型契约】

**`rules/dev-tasks-discipline.md` 新增章节**（追加为 `## 5` 的同级兄弟节点，**不得打乱既有编号**；若文档编号已变更则追加为末位顶级章节）：

```markdown
## 6. 防自证偏见与严禁就地角色扮演纪律 (Strict Ban on In-Context Reviewer Impersonation)

### ① 触发意图识别 (Trigger Recognition)
当用户表达包含但不限于「审查 / 评估 / 二审 / 复盘 / 挑刺 / 红队 / 让 Reviewer 看一下 / 这个设计有没有问题」
等意图时，主模型必须判定为**审查类意图**，进入本纪律管辖范围。

### ② 唯一合法通道 (Mandatory External Channels)
审查类意图的结论只能来自异构外部推理通道，且必须通过 MCP 工具物理发起：
- 自由问答 / 灵感评估 / 方案权衡 / 只读诊断 → `dev_reviewer_consult`；
- 任务规约强化 / 六字段草案打磨 → `dev_tasks_refine_spec`；
- 执行受阻上报 → `dev_tasks_escalate`。

### ③ 行为红线 (Hard Red Lines)
- 严禁在当前对话中以 Reviewer 口吻直接输出评审结论（就地伪装）；
- 严禁把主模型自身的分析包装为「Reviewer 的意见 / 二审结论」；
- 严禁在引擎未配置或离线时，用主模型输出填充 `findings` 掩盖降级事实；
- 严禁声称已调用 Reviewer 而实际未发起任何 MCP 工具调用。

### ④ 引擎缺失时的显式降级 (Mandatory Degraded Card)
`dev_reviewer_consult` 返回 `status="degraded"` 或 `degraded_reason="reviewer_not_configured"` 时，
主模型必须原样转呈降级卡，并明确告知开发者：
> 审查引擎未配置或当前离线。请开启新会话并切换到旗舰 Reviewer 模型后重新提问；
> 当前会话的实现模型不会、也不得代行架构审查职责。
```

**`skills/dev-tasks-review/SKILL.md` 新增分流小节**：

```markdown
### 分流决策树 (Consult vs Refine vs Escalate)
1. 只想知道"这样设计行不行" / 想被挑刺 / 比选方案 → `dev_reviewer_consult`（无需任何 DevTask）；
2. 已有草案但六字段不达标 / 需拆分 / 需重估可行性 → `dev_tasks_refine_spec`；
3. 执行中反复失败 / 需要架构层面重新裁决 → `dev_tasks_escalate`；
4. 引擎不可用 → 输出 degraded 卡片并停机，**不得**在本会话内自行给出审查结论。
```

```python
# tests/test_anti_roleplay_discipline_contract.py
RULES_PATH = Path("plugins/quench-dev-tasks/rules/dev-tasks-discipline.md")
SKILL_PATH = Path("plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md")

REQUIRED_RULE_TOKENS: tuple[str, ...] = (
    "角色扮演", "dev_reviewer_consult", "dev_tasks_refine_spec",
    "degraded", "reviewer_not_configured", "自证偏见",
)
REQUIRED_SKILL_TOKENS: tuple[str, ...] = (
    "dev_reviewer_consult", "dev_tasks_refine_spec", "dev_tasks_escalate", "degraded",
)
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "由你扮演 Reviewer", "可以模拟 Reviewer", "自行扮演", "无需外部模型即可审查",
)

def heading_outline(md_text: str) -> list[str]: ...
```

#### 【分步改造指引】

1. **追加章节而非改写**：在 `rules/dev-tasks-discipline.md` 追加 `## 6. 防自证偏见与严禁就地角色扮演纪律`（含上述四小节）。**严格保留**既有 `## 1`–`## 5` 全部标题、编号与正文语义，禁止重排、禁止翻译既有英文小节标题。
2. **技能文档补充分流**：在 `skills/dev-tasks-review/SKILL.md` 中追加"分流决策树"小节与一段 degraded 卡片样例（样例须包含字面量 `status: degraded` 与 `reviewer_not_configured`，与 `consultation.py` 的字段名严格一致）。
3. **术语一致性**：文档中引用的工具名、状态字面量（`degraded` / `reviewer_not_configured` / `handoff_prompt`）必须与任务 2.1 实现**逐字符一致**，禁止使用近义词（如 `fallback` / `unavailable`）造成规则与代码漂移。
4. **新增契约测试 `test_anti_roleplay_discipline_contract.py`**：
   - `test_rules_contain_anti_roleplay_clause`：断言 `REQUIRED_RULE_TOKENS` 全部出现（大小写不敏感）；
   - `test_skill_contains_triage_tree`：断言 `REQUIRED_SKILL_TOKENS` 全部出现；
   - `test_no_roleplay_legitimizing_phrases`：断言 `FORBIDDEN_PHRASES` 一条都不出现（负向断言）；
   - `test_existing_headings_not_removed`：抽取两份文档的标题大纲，断言结果为**既有基线标题集合的超集**（禁止破坏性重写）；
   - `test_degraded_card_literal_matches_implementation`：断言两份文档中的 `reviewer_not_configured` 字面量与 `consultation.py` 中常量（或文档中显式声明的一致）匹配。
5. **基线快照策略**：`test_existing_headings_not_removed` 的基线以测试文件内的**显式常量列表**形式固化（而非动态读取磁盘），确保后续任何删除标题的行为都会红；新增标题只需追加到该列表。

#### 【防御与边缘校验】

- **禁止破坏性重写**：本任务只允许**追加**，不得删除、不得改写既有纪律条款；编号冲突时以"追加为末位顶级章节"处理，绝不允许重排既有编号（既有 DevTask 与技能文档存在对节号的交叉引用）。
- **术语漂移防御**：状态字面量必须与代码逐字符一致；若任务 2.1 最终采用了不同的字段名，本任务必须同步更新而非单方面改文档。
- **负向断言不可为空**：`FORBIDDEN_PHRASES` 至少 4 条，且必须包含"合法化就地扮演"的典型表述；负向用例若因列表为空而恒真，视为假绿。
- **编码与换行**：文档读写必须 `encoding="utf-8"`，比较前统一 `\r\n` → `\n` 归一化，防止 Windows 换行导致 token 匹配失败。
- **不得写入业务代码**：本任务仅触碰规则、技能与测试文件，严禁顺手修改 `server.py` / `consultation.py`（文件白名单硬约束）。
- **中文与英文标题共存**：匹配使用 `casefold()` 子串匹配，不得使用正则词边界（中文无空格分词），避免 `Reviewer` 与 `Reviewer模型` 连写漏判。

#### 【DoD 验证命令】

```
pytest plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py -q
pytest plugins/quench-dev-tasks/server/tests -q
```

**强制断言要求**：契约测试必须包含 ≥ 6 条断言，其中至少两条为**负向断言**（禁止性短语零命中、既有标题集合只增不减）；第一条命令必须以非空 `FORBIDDEN_PHRASES` 与固化标题基线运行（不得因基线为空而恒真）。

---

### 任务 2.3 ⬜ 待确认 — 新增 dev_reviewer_consult 全行为矩阵单测并完成 Stage 5 端到端验收 (Consultation E2E Matrix)

#### 【涉及文件】

- `[NEW]` `plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py`

#### 【缺陷根因与修改目标】

**根因**：任务 2.1 只交付了上下文守门（路径安全 / 切片预算 / 前缀缓存）与工具注册冒烟，**尚未覆盖工具的核心行为面**——参数校验语义、上下文扩展轮次 `max_hops`、超时熔断、思考流分块落盘、离线降级卡、零 stdout 污染、同会话并发隔离。这些正是"防角色扮演"能否成立的技术底座：只要降级路径未被单测锁定，一次不经意的重构就可能让工具在离线时静默返回成功，角色扮演漏洞立刻复现。

**目标**：以单文件全行为矩阵覆盖 `dev_reviewer_consult` 的全部对外契约与异常路径，并以全量套件作为 Stage 5 的端到端验收闸门。

#### 【目标签名与类型契约】

```python
# tests/test_reviewer_consult.py —— 测试侧契约（全部为离线可跑的确定性用例）
FAKE_STREAM_CHUNKS: list[dict] = [...]          # 交替 text / reasoning 分块，含一个畸形行
DEGRADED_SCENARIOS: tuple[str, ...] = (
    "provider_none", "auth_401", "timeout", "connect_error", "reasoning_budget_exceeded",
)

async def test_tool_is_registered_with_full_schema() -> None: ...
async def test_mode_enum_rejects_illegal_value_without_raising() -> None: ...
async def test_query_length_upper_bound_enforced() -> None: ...
async def test_max_hops_clamped_and_out_of_range_returns_structured_error() -> None: ...
async def test_reasoning_stream_is_persisted_chunkwise_to_session_log() -> None: ...
async def test_log_path_contains_sanitized_session_id() -> None: ...
async def test_timeout_breaker_returns_degraded_and_keeps_partial_log() -> None: ...
@pytest.mark.parametrize("scenario", DEGRADED_SCENARIOS)
async def test_degraded_paths_never_fabricate_findings(scenario: str) -> None: ...
async def test_engine_unconfigured_returns_handoff_prompt_and_empty_findings() -> None: ...
async def test_no_stdout_pollution_during_consultation(capsys) -> None: ...
async def test_concurrent_same_session_serializes_log_writes() -> None: ...
async def test_context_extension_round_respects_max_hops() -> None: ...
async def test_suggested_task_draft_parsed_but_not_persisted() -> None: ...
```

#### 【分步改造指引】

1. **完全离线可测**：全部用例通过 monkeypatch / 依赖注入替换 `create_reviewer_client`，注入返回 `FAKE_STREAM_CHUNKS` 的假客户端；**严禁**任何真实网络调用，**严禁**依赖真实 API Key。测试文件内不得出现任何厂商字面量（Batch 1 闸门虽不扫 `tests/`，仍需遵守纪律）。
2. **参数校验组**：`mode="unknown"` → 返回结构化错误且列出 4 个合法值（断言不抛异常）；`query` 长度 8001 → 结构化错误；`query=""` → 结构化错误；`max_hops=9` → 钳制为 3 并继续执行；`max_hops=-1` → 钳制为 0。
3. **思考流落盘组**：断言日志文件位于 `<workspace_root>/.agents/logs/reviewer/latest-<session_id>.log`；断言文件内容包含全部 reasoning 分块的关键片段且顺序与流式顺序一致；断言写入为**分块追加**（≥ 2 次 flush 痕迹，可用行数或 sink 计数断言）；断言畸形行（如 `data: {bad json`）不影响后续分块落盘。
4. **超时熔断组**：假客户端 `stream_chat` 首块后 `await asyncio.sleep(timeout + 1)`；断言返回 `status="degraded"`, `degraded_reason="timeout"`；断言**首块已落盘的日志仍存在**（不删除部分轨迹）；断言调用总耗时 < `timeout + 2`（熔断真实生效）。
5. **降级矩阵组**：参数化 5 种降级场景，统一断言三条不变量——`findings == ""`（**绝不伪造正文**）、`handoff_prompt` 非空且包含切换到旗舰模型的指引、`status == "degraded"`。`provider_none` 场景额外断言 `degraded_reason == "reviewer_not_configured"`。
6. **零 stdout 污染组**：使用 `capsys`，在完整调用周期后断言 `capsys.readouterr().out == ""`（`sys.stdout` 严格保留给 JSON-RPC 帧）。
7. **并发隔离组**：以同一 `session_id` 并发发起两次调用（`asyncio.gather`），断言两次写入未交错——可通过"日志中每个 reasoning 块均为完整行且无半截行"来断言。
8. **上下文扩展组**：假客户端首轮返回含 `<<<NEED-FILES>>> ... <<<END>>>` 的响应，断言扩展轮次恰好等于 `max_hops`；当 `max_hops=0` 时断言**零次**扩展。
9. **草案沉淀组**：假客户端返回含 `<<<TASK_DRAFT>>> ... <<<END>>>` 块，断言 `suggested_task_draft` 已解析，且断言 `docs/dev_tasks/` 目录**未新增任何文件**（严禁直接落盘）。
10. **Stage 5 端到端验收**：最后以全量套件确认 Batch 1 + Batch 2 组合交付后零破坏性。

#### 【防御与边缘校验】

- **测试隔离**：所有用例必须使用 `tmp_path` 作为 `workspace_root`，绝不在仓库真实 `.agents/logs/` 下写入测试产物；结束后断言 `tmp_path` 外无副作用文件产生。
- **时序稳定性**：涉及心跳 / flush 的断言必须使用事件或计数器而非真实等待时长，避免 Windows CI 抖动导致偶发失败；熔断用例的超时值必须显式注入小值（如 1 秒）。
- **不得依赖未配置的 GitHub/网络环境**：所有降级场景必须在**无网络**环境同样通过。
- **异步测试框架一致性**：必须使用仓库现有异步测试机制（`pytest-asyncio` 或 `anyio`，按现有 `tests/` 的一致写法），禁止引入新测试依赖。
- **假客户端契约保真**：假客户端必须实现与 `ReviewerClient.stream_chat` **完全一致**的签名（含 `session_id` 关键字参数），防止因签名漂移而误判为通过。
- **日志配额不影响断言**：断言前需确保 `.agents/logs/reviewer/` 目录配额清理逻辑不会删除当前会话文件（若触发 20 文件淘汰，本组用例须显式提高配额或固定为最近文件）。
- **测试不得引入厂商字面量**：即使 Batch 1 扫描器不覆盖 `tests/`，仍须遵守中立性纪律，使用 `provider_label="generic"` 等中性占位。

#### 【DoD 验证命令】

```
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py -q
pytest plugins/quench-dev-tasks/server/tests/test_consultation_context_guard.py -q
pytest plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py -q
pytest plugins/quench-dev-tasks/server/tests -q
```

**强制断言要求**：降级矩阵组 5 个参数化场景**每一个**都必须断言 `findings == ""` 且 `handoff_prompt` 非空（这是防角色扮演的技术底线，任一场景缺失即视为该任务未完成）；并发隔离组必须断言日志中不存在半截行；末条命令作为 Stage 5 端到端验收闸门，必须 100% 全绿（包含 Batch 1 的全部 167+ 既有用例）。

---

## 批次验收与停机上报约定

| 批次 | 交付判定 | 归档前强制动作 |
| :--- | :--- | :--- |
| Batch 1（任务 1.1–1.3） | `test_no_vendor_literals_in_core.py` 全绿 + 全量套件全绿 | Batch 1 全部任务 `✔️ 已完成` 后，方可 `dev_tasks_checkout` Batch 2 首个任务 |
| Batch 2（任务 2.1–2.3） | 降级矩阵 5 场景全部断言 `findings == ""` + 全量套件全绿 | 完成后调用 `dev_tasks_archive` 归档并更新 CHANGELOG |

> 若执行过程中发现任务 1.1 的 `DeepSeekClient` 实际归属模块与任务单描述不符，或任务 2.1 发现 `PromptAssembler` / `CodeExplorer` 模块缺失且内联实现超出单文件预算，**必须立即停机并通过 `dev_tasks_escalate` 上报**，输出标准交接卡（Awaiting Architecture Review）后切换旗舰模型重新裁决，**严禁就地扩写任务范围**。
