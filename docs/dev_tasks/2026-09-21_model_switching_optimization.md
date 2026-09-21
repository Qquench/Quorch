# 2026-09-21_model_switching_optimization Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-09-21

---

## Task List & Status / 任务清单与状态

### 任务 1 ✔️ 已完成 — Milestone 0: 独立轻量验证脚本与 Thinking / Prompt Cache 探测

#### 【涉及文件】
```
[NEW] scratch/test_deepseek_call.py
```

#### 【缺陷根因与修改目标】
```
根因：在对服务端进行生产级改造前，需要先行独立验证 DeepSeek 官方 API 连通性、Thinking 思考流结构 (reasoning_content) 与 Prompt Cache 计费命中特征，避免在 MCP 服务端进行盲目试错。
审查修订目标：
1. 编写零外部依赖的标准库脚本，提供清晰的连通性诊断、Token 消耗统计与环境变量指引；
2. 兼容官方模型别名（如 deepseek-flash、deepseek-reasoner、deepseek-chat）及请求体 thinking 字段契约；
3. 建立“双轮请求测试模式”（Cold Run 写入缓存 -> Warm Run 验证命中），切实探测 prompt_cache_hit_tokens > 0；
4. 增加 Windows 控制台 UTF-8 输出重定向设防，杜绝 GBK 字符集崩溃。
```

#### 【目标签名与类型契约】
```python
def build_chat_payload(
    prompt: str,
    system_prefix: str = "",
    model: str = "deepseek-flash",
    enable_thinking: bool = True,
    reasoning_effort: str = "high",
) -> dict: ...

def call_deepseek_api(
    api_key: str,
    payload: dict,
    base_url: str = "https://api.deepseek.com",
    timeout: int = 30,
) -> dict: ...

def verify_prompt_cache_two_rounds(
    api_key: str,
    base_url: str = "https://api.deepseek.com",
) -> Tuple[dict, dict]: ...
```

#### 【分步改造指引】
1. 脚本入口处强制设置 `sys.stdout.reconfigure(encoding="utf-8")` 防御 Windows 终端乱码。
2. 读取环境变量 `DEEPSEEK_API_KEY`，若不存在则友好打印配置指南并安全退出（退出码 0，不阻塞 CI）。
3. 实现 `build_chat_payload`，根据 DeepSeek 官方规范封装 `messages`、`model`（默认别名 `deepseek-flash`）、`thinking: {"type": "enabled"}` 与 `reasoning_effort: "high"`。
4. 使用 `urllib.request.Request` 封装 HTTP POST，携带 `Authorization: Bearer <KEY>` 与 `Content-Type: application/json`。
5. 第一轮调用（Cold Run）：发送足够长的公共前缀（> 1024 tokens），记录 `prompt_cache_miss_tokens` 与返回的 Thinking 过程。
6. 第二轮调用（Warm Run）：使用相同公共前缀重复调用，验证并断言 `usage.prompt_cache_hit_tokens > 0`，打印节省比例与缓存命中耗时。

#### 【防御与边缘校验】
- 凭据安全：严禁将 API Key 硬编码在脚本内，仅从环境变量读取；打印日志时掩码脱敏（如 `sk-***1234`）
- 控制台编码防御：Windows UTF-8 控制台设防，防止中文字符与思考流输出报 `UnicodeEncodeError`
- HTTP 状态码快速失败：401 (Key失效) 与 400 (参数非法) 立即抛错并输出指引，严禁盲目重试
- 结构兼容防御：健壮提取 `choices[0].message.reasoning_content`，兼容存在与不存在思考流的双重响应结构
- 缓存探测可靠性：构造的前缀必须大于 1024 tokens（DeepSeek 触发 Prompt Cache 的硬性物理门槛）

#### 【DoD 验证命令】
```bash
.\venv\Scripts\python.exe scratch/test_deepseek_call.py
```

---

### 任务 2 ✔️ 已完成 — Milestone 1: Quench MCP 审查引擎与项目配置解耦接入

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[NEW] plugins/quench-dev-tasks/server/reviewer_engine.py
[NEW] plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py
```

#### 【缺陷根因与修改目标】
```
根因：当前 MCP 服务端缺乏集成的审查模型后端与解耦配置，无法自动唤醒深度思考模型进行 Spec 强化与架构把关。
审查修订目标：
1. 在 project_config.py 新增 ReviewerEngineConfig 数据类，支持 quench_stack.yaml 声明与向后兼容解析（缺省 provider="none"）；
2. 实现轻量可靠的 reviewer_engine.py，包含 DeepSeekClient 与 PromptAssembler；
3. 建立静态 Prompt 缓存前缀纯洁性防线（严禁混入动态时间戳或会话 ID，保障 100% 缓存命中）；
4. 建立精细化重试策略：400/401/403/404 快速失败，仅对 429 和 5xx 进行最多 2 次指数退避重试；
5. 编写针对各种网络异常、Thinking 提取、重试与降级的 5 组独立单测，确保全量 105+ 项测试全绿。
```

#### 【目标签名与类型契约】
```python
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

@dataclass
class ReviewerEngineConfig:
    provider: str = "none"  # "deepseek" | "none"
    model: str = "deepseek-flash"
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url: str = "https://api.deepseek.com"
    thinking: bool = True
    reasoning_effort: str = "high"
    timeout_seconds: int = 30
    max_retries: int = 2
    max_tool_hops: int = 3

class PromptAssembler:
    @staticmethod
    def build_static_system_prefix(workspace_root: str, config: "QuenchStackConfig") -> str:
        """加载 architecture_doc、constraints 与 dev-tasks-discipline.md 拼接绝对纯净的静态系统提示词（无动态时间戳）"""
        ...

class DeepSeekClient:
    def __init__(self, config: ReviewerEngineConfig): ...
    def is_available(self) -> bool: ...
    def complete(self, messages: List[Dict[str, str]], timeout: Optional[int] = None) -> Dict[str, Any]: ...
```

#### 【分步改造指引】
1. 在 `project_config.py` 中定义 `ReviewerEngineConfig`，在 `load_project_config` 中解析 `reviewer_engine` 字典，默认 `provider="none"` 确保老项目 100% 兼容。
2. 在 `reviewer_engine.py` 实现 `PromptAssembler.build_static_system_prefix`，严格读取 `architecture_doc` 规范与 `dev-tasks-discipline.md`。
3. 在 `reviewer_engine.py` 实现 `DeepSeekClient`：
   - `is_available()`: 检测 `provider == "deepseek"` 且环境变量中密钥存在；
   - `complete()`: 使用 `urllib.request` 实现带重试机制的 HTTP POST，401/400 快速失败，429/5xx 进行退避重试，解析 `reasoning_content` 与 `content`。
4. 编写 `plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py`，使用 `unittest.mock` 覆盖 5 种场景（正常解析、401快速报错、429重试成功、网络超时、无Key降级）。

#### 【防御与边缘校验】
- 静态前缀纯洁性：`PromptAssembler` 严禁拼接任何动态时间戳、随机数或会话 ID，确保 System Prompt 字节流 100% 命中缓存
- 智能非重试防线：遇到 401 Unauthorized 或 400 Bad Request 严禁重试，避免死循环造成延迟
- 网络超时死锁防御：网络请求硬性设置 `timeout_seconds`（默认 30s），防止 IDE 进程假死
- 降级幂等性：当 `is_available() == False` 时，调用层直接返回标准结果指示未就绪，绝不抛出未捕获异常中断服务
- 单测隔离性：单测必须通过 Mock 隔离外网依赖，保证在离线环境下 100% 通过

#### 【DoD 验证命令】
```bash
.\venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py -v
$env:PYTHONPATH="."; ..\..\..\venv\Scripts\python.exe -m pytest tests
```

---

### 任务 3 ✔️ 已完成 — Milestone 2: 任务规约强化与智能升级工具闭环

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/server/code_explorer.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[NEW] plugins/quench-dev-tasks/server/tests/test_spec_refine.py
```

#### 【缺陷根因与修改目标】
```
根因：日常 3.8 Flash 产出的任务草案容易遗漏并发锁、边缘校验与 DoD 断言，原有 dev_tasks_escalate 仅输出被动交接卡。目标：在 server.py 增加 dev_tasks_refine_spec 工具，集成轻量 AST/切片代码探索安全阀 (max_hops<=3)，打通自动二审与规约强化闭环；升级 dev_tasks_escalate 支持可选自动诊断。
```

#### 【目标签名与类型契约】
```
def dev_tasks_refine_spec(workspace_root: str, draft_task: Dict[str, Any], context_files: Optional[List[str]] = None) -> Dict[str, Any]: ...
```

#### 【分步改造指引】
1. 新建 code_explorer.py，提供 AST 接口提取与安全切片读取，硬性拦截 max_hops <= 3。
2. 在 server.py 暴露 dev_tasks_refine_spec MCP 工具，调用 ReviewerEngine 补齐六大字段并经由 schema_validator 校验。
3. 增强 dev_tasks_escalate 工具，当引擎可用时自动生成架构深析诊断与方案 A/B 建议。
4. 编写 tests/test_spec_refine.py 测试工具流转与异常回退。

#### 【防御与边缘校验】
- 语义探索防线：max_hops 严格截断，单次切片不超过 100 行，避免上下文膨胀与超时
- 规约刚性保障：生成的任务单必须通过 validate_task_schema，不合规时回退或拦截

#### 【DoD 验证命令】
```bash
.\venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_spec_refine.py
```

---

### 任务 4 ⬜ 待确认 — Milestone 3: 刚性单测门禁与 CLI 终端体检集成

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/cli.py
[NEW] plugins/quench-dev-tasks/server/tests/test_dod_guard.py
```

#### 【缺陷根因与修改目标】
```
根因：dev_tasks_complete 中的 _audit_test_changes 虽通过 git diff 收集测试变动，但审计结果 passed=False 从未物理阻断 complete，导致 [Mandatory Assertion Rule] 形同软约束，受管代码（is_path_governed 命中的 server/** 等）可在零单测增量的情况下被标记为 ✔️ 已完成；同时终端缺少独立验证 ReviewerEngine 配置/连通性/思考流/缓存状态的入口。
目标：将单测增量审计升级为物理刚性门禁（无合法豁免即 status='rejected' 且不改状态机），并在 quorch CLI 新增可退出码判定、输出脱敏、可离线 mock 的 check-engine 体检命令，配套 test_dod_guard.py 全量断言覆盖。
```

#### 【目标签名与类型契约】
```python
# plugins/quench-dev-tasks/server/server.py
_EXEMPTION_PATTERN = re.compile(
    r"\[EXEMPTION:\s*(docs-only|config-only|non-behavioral-refactor)\s*\]",
    re.IGNORECASE,
)
_TEST_FILE_PATTERN = re.compile(r"(^|/)tests?/.*test_.*\.py$|(^|/).*_test\.py$")
_ASSERTION_MARKERS = ("assert ", "assert(", "pytest.raises")

def _audit_test_changes(
    workspace_root: str,
    config: Any,
    test_evidence: str | None = None,
) -> Dict[str, Any]:
    """Return-value contract (backward-compatible, additive keys):
    {
      "passed": bool,                       # assertions_found or exempted or degraded
      "governed_code_changed": list[str],   # rel paths, is_path_governed(hit)
      "test_files_changed": list[str],      # rel paths, _TEST_FILE_PATTERN hit
      "assertions_found": bool,             # new/modified test content has marker
      "detected_markers": list[str],
      "exempted": bool,
      "exemption_reason": str | None,
      "degraded": bool,                     # git missing / not a repo / detached
      "messages": list[str],
    }
    """

# dev_tasks_complete(...) additive return keys:
#   {"status": "completed" | "rejected", "audit": <_audit_test_changes dict>,
#    "guidance": str}   # task state UNCHANGED on 'rejected'

# plugins/quench-dev-tasks/server/cli.py
def _mask_secret(secret: str | None) -> str: ...
#   None -> "NOT SET"; len<=8 -> "****"; else f"{head4}****{tail4}"

def cmd_check_engine(
    workspace_root: str,
    plain: bool = False,
    as_json: bool = False,
) -> int:
    """Exit code: 0 = ok; 1 = not-configured/auth-fail/connect-fail/timeout.
    --json stdout schema (single JSON object):
    {
      "provider": str, "model": str,
      "api_key_env": str, "api_key_present": bool, "api_key_masked": str,
      "connectivity_ok": bool, "latency_ms": int | null,
      "thinking_supported": bool, "thinking_probe": "config" | "live",
      "exit_code": int
    }
    """

# main(argv): subparser 'check-engine' + persistent flag 'check --engine' both
#   delegate to cmd_check_engine; adds '--json' and honors '--plain'.
```

#### 【分步改造指引】
1. 【审计收集重构】重写 `server.py::_audit_test_changes`：以 `config.is_path_governed()` 为唯一受管判定源，通过 `git -C <root> status --porcelain`、`git diff --name-only`、`git diff --cached --name-only` 三路并集收集变更文件（区分 tracked 与 `??` untracked）。对 tracked 文件仅扫描 diff 新增行（`--unified=0`）以规避历史断言误判；对 untracked 文件直接读取全文；在 `_TEST_FILE_PATTERN` 命中的测试文件中匹配 `_ASSERTION_MARKERS`。所有 git 调用包裹在 try/except（`FileNotFoundError`/`CalledProcessError`/非仓库）→ 置 `degraded=True` 并写入 `messages`，严禁抛出异常。
2. 【物理门禁硬化】改造 `server.py::dev_tasks_complete`：在既有状态校验之后执行审计；当 `governed_code_changed` 非空 且 `not assertions_found` 且 `not exempted` 且 `not degraded` 时，**不得调用 `transition_task`**，直接返回 `{"status": "rejected", "audit": {...}, "guidance": <分步修复指引>}`（任务保持 `🔨 执行中`），并向 `.agents/.quench_hook.log` 追加审计拒绝记录（复用幂等日志写入）；合法豁免须由 `test_evidence` 参数精确匹配 `_EXEMPTION_PATTERN`，并抽取 `exemption_reason`。
3. 【CLI 体检实现】在 `cli.py` 新增 `_mask_secret()` 与 `cmd_check_engine()`：经 `load_project_config` 载入配置，实例化 `ReviewerEngineConfig`/`DeepSeekClient`，以 `resolve_api_key()` 判定 `api_key_present` 并掩码；连通性探针复用 `DeepSeekClient.complete` 触发一次极短预算请求（有界超时，默认 ≤5s，可被 `monkeypatch` 注入），记录 `latency_ms`；`thinking_supported` 由 model 名前缀（如 `deepseek-reasoner`/深度思考）静态判定；最终按 `--json` 输出单行结构化 JSON 或 `--plain` 人类可读文本，返回退出码 0/1。
4. 【子命令接线】在 `cli.py::main` 注册 `check-engine` 子解析器并新增持久参数 `--json`；同时为 `check` 子命令挂载 `--engine` 标志，命中时委托 `cmd_check_engine`。强制 `--json` 模式下禁用 ANSI 颜色（与 `should_enable_color`/`reconfigure` 协同），保证 stdout 为可被 `json.loads` 解析的唯一对象。
5. 【单测闭环】新建 `tests/test_dod_guard.py`：使用 `tmp_path` + 伪 git 仓库（或 `monkeypatch` 注入 subprocess 结果）覆盖——(a) 受管代码变更且测试无断言 → `passed=False` 且 complete 返回 `status='rejected'` 且任务状态仍为 `🔨 执行中`；(b) `test_evidence` 携带 `[EXEMPTION: config-only]` → 放行；(c) 仅 `docs/**.md` 变更 → `governed_code_changed` 为空自然放行；(d) untracked 新测试文件含 `assert ` → 被识别；(e) `check_engine` 正常分支退出码 0 与异常/缺 Key 分支退出码 1，且 `--json` 输出键完整、API Key 完全脱敏。

#### 【防御与边缘校验】
- 离线/无 Git 降级：git 二进制缺失、非 git 仓库、detached HEAD 或命令非零退出时置 `degraded=True`，不得抛异常阻塞 complete，但必须写入 `messages` 与 hook 日志，便于离线边缘环境复现审计退化。
- Untracked 反漏：`git diff` 默认不显示 `??` 新增测试文件，必须经 `git status --porcelain` 补采并直接读取全文匹配断言标记，否则本任务自身新增的 `test_dod_guard.py` 将触发自相矛盾的误拒。
- 豁免严格白名单：`_EXEMPTION_PATTERN` 仅接受 `docs-only|config-only|non-behavioral-refactor` 三类；空串、拼写错误或自由文本一律视为“未豁免”，防止以随意文案绕过物理门禁。
- 受管边界单调：受管判定必须复用 `config.is_path_governed()`，禁止另行硬编码路径；纯文档/非受管路径（`docs/**`、`*.md`、`archive/**`）应使 `governed_code_changed` 为空从而天然放行，不得误伤。
- 拒绝只读无副作用：`status='rejected'` 分支严禁申请 FileLock、严禁调用 `_atomic_write_json`/`transition_task`，确保任务状态保持 `🔨 执行中`，且重复调用返回同一拒绝结果（幂等）。
- 连通性探针有界：`cmd_check_engine` 的网络探针必须受总耗时预算熔断（默认 ≤5s），超时/连接错误统一映射退出码 1，严禁在无 Key 或无网络时挂起 CLI。
- 脱敏不可逆：`_mask_secret` 对 `None` 返回 `NOT SET`、长度 ≤8 返回全 `****`、否则仅暴露首4+尾4，任何路径（含异常堆栈）都不得回显完整 API Key。
- Windows 环境穿透：`check-engine` 必须复用 `resolve_api_key()`（含注册表 `_read_windows_env_var` 回退）解析 `DEEPSEEK_API_KEY_Quench`，保证免重启 IDE/终端下的可用性判定一致。
- 输出纯净性：`--json` 模式下必须强制关闭 ANSI 颜色且 stdout 只含单个可 `json.loads` 的对象，人类可读分支不得污染机器可解析输出，保证跨平台（Windows/Ubuntu）确定性。
- 断言匹配健壮：标记匹配须同时覆盖 `assert `、`assert(` 与 `pytest.raises`，仅扫描新增/变更行，避免将历史遗留断言误判为本次增量。

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_dod_guard.py -v
python -m pytest plugins/quench-dev-tasks/server/tests/test_dod_guard.py -k "dod_guard or exemption or untracked or governed or check_engine" -v
python -m pytest plugins/quench-dev-tasks/server/tests/ -q
python plugins/quench-dev-tasks/server/cli.py check-engine --json
python plugins/quench-dev-tasks/server/cli.py check --engine --plain
```

---

### 任务 5 ⬜ 待确认 — Milestone 4: 多层能力自适应交接协议与模型解耦 (Multi-Tier Adaptive Reviewer Handoff Protocol & Model Decoupling)

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/reviewer_engine.py
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md
[NEW] plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py
```

#### 【缺陷根因与修改目标】
```
根因：
1. 现有工具将审查能力与特定模型（DeepSeek）硬编码耦合，但在工程落地中，Reviewer 是一个纯粹的架构审查“角色（Role）”而非具体模型，可由 DeepSeek、Claude、Gemini、本地开源模型（Ollama/vLLM）或人类开发者承担；
2. 现有 checkout/escalate 的交接逻辑假定只有“手动切会话”和“服务端直连 API”两极，忽略了高级宿主（如 Antigravity / Claude Code）原生支持自主调度 Subagent，以及未来平台原生会话内模型切换（In-session Model Switching / Gemini 4 Pro）的事实，造成工作流割裂；
3. 若为此分化 Git 分支将导致严重的版本碎片化与维护灾难。

目标：
1. 架构解耦：将 Reviewer 客户端彻底解耦为通用 OpenAI 兼容协议适配器（ReviewerClient），支持任意第三方服务商或本地 Ollama 端点，DeepSeek 仅作为开箱即用的预置 Provider 之一；
2. 能力协商信封：在 server.py 引入单一响应信封（reviewer_handoff），实现 Subagent -> Session_Switch -> Engine -> Manual 的四层能力声明与自适应匹配；
3. 恪守四大红线：零同步阻塞网络 I/O（50ms 治理预算保证）、manual 恒为终局兜底（R3 不变式）、零客户端指纹嗅探、密钥绝不回显；
4. 100% 向后兼容：所有既有顶级键（status, task_id, instructions, handoff_card 等）完全保留，旧客户端无感兼容。
```

#### 【目标签名与类型契约】
```python
# ---- plugins/quench-dev-tasks/server/project_config.py ----
DispatchStrategy = Literal["subagent", "session_switch", "engine", "manual"]

@dataclass
class ReviewerEngineConfig:
    mode: str = "auto"  # "auto" | "subagent" | "session_switch" | "engine" | "manual"
    strategy_order: list[str] = field(
        default_factory=lambda: ["subagent", "session_switch", "engine", "manual"]
    )
    provider: str = "deepseek"  # "deepseek" | "openai" | "ollama" | "custom" | "none"
    model: str = "deepseek-flash"
    api_key_env: str = "DEEPSEEK_API_KEY_Quench"
    base_url: str = "https://api.deepseek.com"
    thinking: bool = True
    reasoning_effort: str = "high"
    timeout_seconds: int = 60
    max_retries: int = 2
    max_tool_hops: int = 3

# ---- plugins/quench-dev-tasks/server/server.py ----
class ReviewerHandoff(TypedDict, total=False):
    contract_version: Literal["1.0"]
    task_id: str
    task_path: str
    reason: str  # "batch_complete" | "escalation" | "rework_required"
    summary: str
    preferred: DispatchStrategy
    strategies: list[Dict[str, Any]]
    legacy_card_markdown: str

def _resolve_handoff_envelope(
    workspace_root: str,
    config: QuenchStackConfig,
    task_id: str,
    task_path: str,
    reason: str,
    context_files: Optional[List[str]] = None,
    host_capabilities: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Pure, side-effect-free envelope builder with zero synchronous network I/O.
    Enforces R3 invariant: strategies[-1]['strategy'] == 'manual' and available == True.
    """

# ---- plugins/quench-dev-tasks/server/reviewer_engine.py ----
# Generic alias decoupling ReviewerClient from DeepSeek
class ReviewerClient(DeepSeekClient):
    """Generic OpenAI-compatible Reviewer Client supporting any standard /chat/completions provider."""
    pass
```

#### 【分步改造指引】
1. 【模型解耦与配置归一化】：在 `project_config.py` 中重构 `ReviewerEngineConfig`，支持 `mode`（默认 `"auto"`）与 `strategy_order`；在 `reviewer_engine.py` 将客户端抽象升级为模型无关的 `ReviewerClient`（保留 `DeepSeekClient` 作为完全兼容别名），依赖标准 OpenAI 协议参数（`base_url`, `model`, `api_key_env`）；在配置加载时自动平滑迁移老配置（`provider: none` -> `mode: manual`；`provider: deepseek` -> `mode: engine`）。
2. 【信封构造纯函数实现】：在 `server.py` 实现 `_resolve_handoff_envelope` 纯函数。严禁任何网络 I/O；依据本地配置与凭据存在性按优先级组装：
   - `subagent` 载荷：注入只读审查 Prompt、受管文件上下文与 `dev_tasks_confirm` 回调指示；
   - `session_switch` 载荷：注入会话内升级至 REVIEWER 角色的执行指引；
   - `engine` 载荷：登记 provider/model 与 `api_key_present: bool`（严禁输出密钥明文），指引调用 `dev_tasks_refine_spec`；
   - `manual` 载荷：输出 100% 经典的 Markdown 交接卡，并强制设为终局兜底（`available: True`）。
3. 【工具挂载与并发安全】：重构 `dev_tasks_checkout`（批次完工分支）与 `dev_tasks_escalate`，确保在状态机 `FileLock` 释放后再调用 `_resolve_handoff_envelope`；在现有返回字典上增量挂载 `reviewer_handoff` 键，将顶层 `handoff_card` 与 `legacy_card_markdown` 保持严格字节一致。
4. 【技能文档规范同步】：更新 `skills/dev-tasks-workflow/SKILL.md` 与 `skills/dev-tasks-review/SKILL.md`，记录四层能力协商信封契约、宿主 Agent 优先取用第一条 `available` 策略的自治指引、以及模型中立的 Reviewer 审查职责。
5. 【单测刚性闭环】：编写 `tests/test_handoff_protocol.py`，覆盖 15 项核心测试（R3 manual 兜底不变式、未知 mode 自动回落 manual、provider 自动迁移映射、旧客户端字段 100% 存在、密钥零序列化泄露、路径穿越防御、以及零阻塞网络 I/O 验证）。

#### 【防御与边缘校验】
- R3 终局兜底不变式：`strategies` 列表末尾恒为 `strategy == "manual"` 且 `available is True`，从结构上彻底杜绝“策略集为空”或降级断裂。
- 密钥绝对安全防护：序列化结果中严禁出现真实 API 密钥内容，仅暴露 `api_key_present: bool`；`api_key_env` 变量名必须匹配 `^[A-Z][A-Z0-9_]*$` 正则。
- 零同步阻塞网络（50ms 预算）：信封组装全过程为纯内存运算，严禁发起 HTTP 网络探测或外部进程轮询。
- 路径穿越与读取边界：`task_path` 与 `context_files` 严格限制在 `workspace_root` 之内；上下文摘要读取实行流式截断（≤4096 字符，最多 8 个文件），防止大文件 OOM。
- 幂等与锁释放：状态机跃迁完成后立即释放 `FileLock`，再行组装信封，杜绝持锁期间字符串拼接导致死锁。
- 子代理只读防越权：`subagent` 载荷的 Prompt 中必须明确声明“只读审查，严禁直接修改源码，审查结论必须通过 dev_tasks_confirm 回调流转”。
- 零客户端嗅探：严禁检测特定宿主环境变量，能力仅由配置与显式参数声明。

#### 【DoD 验证命令】
```bash
# 1. 验证多层自适应与模型解耦专项单测（15 项核心断言）
cd plugins/quench-dev-tasks/server && python -m pytest tests/test_handoff_protocol.py -v

# 2. 全量回归验证（确保已有 126 项单测 100% 通过）
cd plugins/quench-dev-tasks/server && python -m pytest tests/ -q

# 3. 语法与导入完整性校验
cd plugins/quench-dev-tasks/server && python -c "import ast; ast.parse(open('server.py', encoding='utf-8').read()); ast.parse(open('reviewer_engine.py', encoding='utf-8').read()); print('AST OK')"

# 4. 模型解耦向后兼容验证：Generic ReviewerClient 能够正常无缝实例化
cd plugins/quench-dev-tasks/server && python -c "from reviewer_engine import ReviewerClient, DeepSeekClient; assert issubclass(ReviewerClient, DeepSeekClient); print('Client Decoupling OK')"
```

---

### 任务 6 ⬜ 待确认 — Milestone 5: 规约文档同步与架构规范归档 (Documentation Sync & End-to-End Self-Hosting Validation)

#### 【涉及文件】
```
[MODIFY] dev_tasks_mcp_specification.md
[MODIFY] dev_tasks_mcp_specification_zh.md
[MODIFY] plugins/quench-dev-tasks/templates/quench_stack.yaml
```

#### 【缺陷根因与修改目标】
```
根因：底层工具增强后，系统架构规约与项目模板需要同步升级至 v1.4.0，明确双轨自适应协议、审查引擎标准与平滑迁移路线。
目标：更新双语规范文档与配置模板，固化零 Opus 自举、双轨交接卡规范以及未来向 Gemini 4 Pro 原生平滑迁移的机制。
```

#### 【目标签名与类型契约】
```
None (Documentation and schema specification updates)
```

#### 【分步改造指引】
1. 更新 dev_tasks_mcp_specification.md 与 dev_tasks_mcp_specification_zh.md，记录 ReviewerEngine、refine_spec 以及双轨自适应交接协议（Dual-Track Adaptive Handoff Protocol）。
2. 更新 templates/quench_stack.yaml，提供 reviewer_engine 声明示例与双轨模式注释。
3. 执行端到端自举验证并回归验证全量 pytest 测试套件。

#### 【防御与边缘校验】
- 双语同步性：英文与中文规约保持版本号与章节结构 1:1 对齐
- 配置注释完备性：模板中必须明确标注 provider='none' 与 provider='deepseek' 的行为差异

#### 【DoD 验证命令】
```bash
.\venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests
```

---

