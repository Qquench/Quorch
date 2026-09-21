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
根因：当前 dev_tasks_complete 虽然会校验 DoD 文本，但对业务受管代码缺乏物理层面的单测增量强制审计；终端缺乏独立的审查引擎连通性体检入口。目标：强化 dev_tasks_complete 的 Mandatory Assertion Rule；在 cli.py 增加 check-engine 子命令。
```

#### 【目标签名与类型契约】
```
def _verify_test_increment_and_assertions(workspace_root: str, task: Task) -> Tuple[bool, str]: ...
```

#### 【分步改造指引】
1. 在 server.py 的 dev_tasks_complete 中强化受管文件改动时的单测增量与断言检测。
2. 在 cli.py 中新增 check-engine 命令，输出审查引擎配置、连通性与缓存状态报告。
3. 编写 tests/test_dod_guard.py 验证缺少单测时阻断 complete。

#### 【防御与边缘校验】
- 区分代码与文档：纯文档/配置改动不强制要求单测增量，通过 Dual-Track 引擎豁免

#### 【DoD 验证命令】
```bash
.\venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_dod_guard.py
.\venv\Scripts\python.exe plugins/quench-dev-tasks/server/cli.py check-engine
```

---

### 任务 5 ⬜ 待确认 — Milestone 4: 双轨工作流自适应与交接卡协议升级 (Dual-Track Workflow & Adaptive Handoff Protocol)

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md
[NEW] plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py
```

#### 【缺陷根因与修改目标】
```
根因：dev_tasks_checkout（批次完工时触发）与 dev_tasks_escalate（卡点升级时触发）硬编码了离线手动交接卡逻辑，假定人类必须复制上下文并在新会话中切换至 Reviewer 模型。在接入外部审查引擎（reviewer_engine.provider='deepseek'）或 IDE subagent 后，该手动切换变成冗余步骤并与自动化流转冲突；但若为此分化两个 Git 分支将导致严重的版本碎片与维护噩梦。
目标：坚持单一代码库、基于配置驱动的双轨（Dual-Track）自适应协议——provider='none' 保持 100% 经典手动交接卡（字节级向后兼容）；provider='deepseek' 将相同调用点升级为就地自动化决策报告（提供 A/B 方案与执行建议，消除手动切换会话提示）；并在引擎已声明但不可用（无 Key / 离线）时平滑优雅降级回手动交接卡。
```

#### 【目标签名与类型契约】
```python
# ---- server/project_config.py ----
@dataclass
class ReviewerEngineConfig:
    # dual-track selector. Canonical values: "none" (manual track) | "deepseek" (auto track).
    # Any other/missing value MUST be normalized to "none" (fail-safe, never raise).
    provider: str = "none"

# ---- server/server.py ----
HandoffMode = Literal["manual", "auto"]

def _resolve_handoff_mode(config: Any) -> tuple[HandoffMode, Optional[str]]:
    """Return (handoff_mode, degraded_reason).
    'auto'   -> reviewer_engine.provider is a KNOWN live engine (e.g. 'deepseek') AND its
                credentials are present (is_available()==True).
    'manual' -> provider is 'none'/missing/unknown, OR engine declared but unavailable.
    PURITY GUARANTEE: pure, side-effect-free, NO network I/O; credential presence check only.
    degraded_reason is non-None ONLY when 'auto' was requested but fell back to 'manual'.
    """

def _render_handoff_payload(mode: HandoffMode, legacy_card: str, context: dict) -> dict:
    """Adaptive handoff object.
    mode='manual' -> {'mode': 'manual', 'card_markdown': <legacy_card>}  (identical legacy output)
    mode='auto'   -> {'mode': 'auto',
                      'options': [{'id': 'A', 'summary': str, 'next_action': str},
                                  {'id': 'B', 'summary': str, 'next_action': str}],
                      'suggested_action': str}
                     (manual session-switch instructions SUPPRESSED)
    """

# ---- ADDITIVE response schema (backward compatible) for dev_tasks_checkout / dev_tasks_escalate ----
# {
#   ...ALL existing keys preserved unchanged (status, task_id, instructions, handoff_card, ...)...,
#   "handoff_mode": "manual" | "auto",            # NEW - additive
#   "handoff": { ...adaptive payload above... },  # NEW - additive
#   "degraded_reason": Optional[str]              # NEW - present only on auto->manual fallback
# }
```

#### 【分步改造指引】
1. 在 `project_config.py` 中规范 `ReviewerEngineConfig.provider` 的归一化解析，将非 {'none','deepseek'}（包括 None、空串或缺失）安全归一化为字面量 `"none"`，发出 warning 而不 raise，保证未配置工作区 100% 保持经典手动轨行为。
2. 在 `server.py` 实现两个纯函数（Pure Helpers）：`_resolve_handoff_mode(config) -> (mode, degraded_reason)`，仅做本地凭据存在性检测（无网络 I/O，50ms 工具响应预算保证）；`_render_handoff_payload(mode, legacy_card, context)` 构建自适应结构体。
3. 重构 `dev_tasks_checkout`（批次完工且存在待确认/返工任务分支）：保留现有状态迁移与全部已有返回字段，计算 `(mode, degraded_reason) = _resolve_handoff_mode(config)` 并增量附加 `handoff_mode`、`handoff` 与 `degraded_reason`。`mode == 'manual'` 时保持原交接卡内容完全一致；`mode == 'auto'` 时生成具体 A/B 方案与 `suggested_action`，消除切会话提示。
4. 重构 `dev_tasks_escalate`：统一使用相同的 helper 生成自适应交接对象。确保状态机 `FileLock` 在渲染交接负载前已完全释放，杜绝持有锁期间组装数据。
5. 更新 `skills/dev-tasks-workflow/SKILL.md` 与 `skills/dev-tasks-review/SKILL.md`，记录双轨协议（provider='none' -> 经典手动交接卡；provider='deepseek' -> 就地自动化决策报告与 A/B 方案）以及自动降级规则。编写 `tests/test_handoff_protocol.py` 覆盖双轨判定、降级防护与历史字段兼容性。

#### 【防御与边缘校验】
- 缺省保全防线：未配置或空 `reviewer_engine` 块必须静默解析为 'manual'，绝不抛出未捕获异常。
- 未知 provider 防线：未知 provider 值（如拼写错误）必须降级为 'manual' 并仅记录 warning。
- 离线/缺 Key 降级防线：provider='deepseek' 但 `is_available() == False` 时必须平滑降级为 'manual'，并明确赋值 `degraded_reason`。
- 零同步网络 I/O：`_resolve_handoff_mode` 严禁发起 HTTP 网络探测，确保纯本地判定维持 50ms 治理预算。
- 历史契约绝对兼容：所有既有顶级字段（`status`, `task_id`, `instruction`, `prompt_hint` 等）在 manual 模式下保持原有字节级语义。
- 并发锁安全防线：严禁在持有 `FileLock` 时进行复杂字符串与字典装配，必须遵循“先释锁、后渲染”。
- 单任务执行不变量：重构严禁破坏“全工作区最多一个 `🔨 执行中` 任务”的硬性不变量。
- 跨进程 JSON 序列化：返回对象必须为纯 JSON-safe 类型（严禁残留 Enum 或 Dataclass 实例）。
- 确定性与易测性：`_resolve_handoff_mode` 行为纯粹由配置决定，可在单测中脱敏测试。

#### 【DoD 验证命令】
```bash
# 1. 验证双轨协议新增单测（覆盖双轨选择、经典卡片对齐、未知降级与无 Key 降级）
cd plugins/quench-dev-tasks/server && python -m pytest tests/test_handoff_protocol.py -v

# 2. 全量零回归验证
cd plugins/quench-dev-tasks/server && python -m pytest tests/ -v

# 3. 语法与导入完整性校验
cd plugins/quench-dev-tasks/server && python -c "import ast; ast.parse(open('server.py', encoding='utf-8').read()); ast.parse(open('project_config.py', encoding='utf-8').read()); print('AST OK')"

# 4. 向后兼容冒烟测试：缺省 provider 必须解析为 manual
cd plugins/quench-dev-tasks/server && python -c "from project_config import ReviewerEngineConfig; c=ReviewerEngineConfig(); assert getattr(c,'provider','none')=='none'; print('manual-default OK')"
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

