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

### 任务 1 ⬜ 待确认 — Milestone 0: 独立轻量验证脚本与 Thinking / Prompt Cache 探测

#### 【涉及文件】
```
[NEW] scratch/test_deepseek_call.py
```

#### 【缺陷根因与修改目标】
```
根因：在对服务端进行生产级改造前，需要先行独立验证 DeepSeek-V4.1-Flash API 的连通性、Thinking 思考流结构 (reasoning_content) 与 Prompt Cache 计费命中特征，避免在 MCP 服务端进行盲目试错。目标：编写零外部依赖的标准库脚本，提供清晰的连通性诊断、Token 消耗统计与环境变量指引。
```

#### 【目标签名与类型契约】
```
def call_deepseek_api(api_key: str, prompt: str, system_prefix: str = "", model: str = "deepseek-v4.1-flash") -> dict
```

#### 【分步改造指引】
1. 读取环境变量 DEEPSEEK_API_KEY，若不存在则打印友好提示和配置说明。
2. 使用 urllib.request 发送兼容 OpenAI 规范的 chat/completions POST 请求。
3. 解析响应中的 reasoning_content 与 content，打印 Thinking 思考过程与最终输出。
4. 提取并打印 usage 中的 prompt_cache_hit_tokens 与 prompt_cache_miss_tokens。

#### 【防御与边缘校验】
- 凭据安全：严禁将 API Key 硬编码在脚本内，仅从环境变量读取
- 网络异常防御：捕获 urllib.error.HTTPError / URLError 并给出 HTTP 状态码与详细排查建议
- 结构兼容防御：兼容 message 字典中存在与不存在 reasoning_content 的双重情形

#### 【DoD 验证命令】
```bash
.\venv\Scripts\python.exe scratch/test_deepseek_call.py
```

---

### 任务 2 ⬜ 待确认 — Milestone 1: Quench MCP 审查引擎与项目配置解耦接入

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[NEW] plugins/quench-dev-tasks/server/reviewer_engine.py
[NEW] plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py
```

#### 【缺陷根因与修改目标】
```
根因：当前 MCP 服务端缺乏集成的审查模型后端与解耦配置，无法自动唤醒深度思考模型进行 Spec 强化与架构把关。目标：在 project_config 中新增 ReviewerEngineConfig 数据类支持 quench_stack.yaml 声明；实现轻量可靠的 ReviewerEngine（含 DeepSeekClient 与基于 architecture_doc 的静态 PromptAssembler）；配套完整 Mock 单测矩阵确保零破坏性。
```

#### 【目标签名与类型契约】
```
@dataclass
class ReviewerEngineConfig:
    provider: str = "none"  # deepseek | none
    model: str = "deepseek-v4.1-flash"
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url: str = "https://api.deepseek.com"
    thinking: bool = True
    timeout_seconds: int = 30
    max_tool_hops: int = 3
```

#### 【分步改造指引】
1. 在 project_config.py 中定义 ReviewerEngineConfig，并在 load_project_config 中解析 reviewer_engine 节点，默认 provider='none' 实现向后兼容。
2. 新建 reviewer_engine.py，实现 DeepSeekClient（支持超时、退避重试、无 Key 优雅降级）与 PromptAssembler（加载 architecture_doc 与 dev-tasks-discipline.md 建立稳定前缀）。
3. 编写 tests/test_reviewer_engine.py，Mock 网络层测试正常解析、Thinking 提取、重试与降级逻辑。

#### 【防御与边缘校验】
- 零依赖膨胀：优先使用标准库 urllib.request，避免外部重量级 SDK 引起版本冲突
- 超时死锁防线：网络请求严格设置 timeout（默认 30s），防止 IDE 客户端长时间挂起
- 向后兼容性：未配置 API Key 或未启用引擎时，必须静默降级，不中断原有本地测试与流转

#### 【DoD 验证命令】
```bash
.\venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py
.\venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests
```

---

### 任务 3 ⬜ 待确认 — Milestone 2: 任务规约强化与智能升级工具闭环

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

### 任务 5 ⬜ 待确认 — Milestone 4: 规约文档更新与架构规范归档

#### 【涉及文件】
```
[MODIFY] dev_tasks_mcp_specification.md
[MODIFY] dev_tasks_mcp_specification_zh.md
[MODIFY] plugins/quench-dev-tasks/templates/quench_stack.yaml
```

#### 【缺陷根因与修改目标】
```
根因：底层工具增强后，系统架构规约与项目模板需要同步升级至 v1.4.0，明确审查引擎标准与平滑迁移路线。目标：更新双语规范文档与配置模板，固化零 Opus 自举和未来向 Gemini 4 Pro 原生平滑迁移的机制。
```

#### 【目标签名与类型契约】
```
None (Documentation and schema specification updates)
```

#### 【分步改造指引】
1. 更新 dev_tasks_mcp_specification.md 与 dev_tasks_mcp_specification_zh.md，记录 ReviewerEngine 与 refine_spec 规范。
2. 更新 templates/quench_stack.yaml，提供 reviewer_engine 声明示例与注释。
3. 回归验证全量 pytest 测试套件。

#### 【防御与边缘校验】
- 双语同步性：英文与中文规约保持版本号与章节结构 1:1 对齐

#### 【DoD 验证命令】
```bash
.\venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests
```

---

