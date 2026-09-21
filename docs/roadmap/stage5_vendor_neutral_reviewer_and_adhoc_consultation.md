# Stage 5: 厂商中立 Reviewer 架构净化、即时架构咨询通道 (dev_reviewer_consult) 与防角色扮演治理
(Stage 5: Vendor-Neutral Reviewer Architecture, Ad-Hoc Consultation Tool & Anti-Role-Playing Governance)

> **路线图状态**: 🔨 活跃推进中 (Active Planning & Development)  
> **起始时间**: 2026-09-21  
> **前置里程碑**: ✔️ Stage 4 交付归档 (`docs/roadmap/archive/stage4_automated_subagent_delegation_and_codebase_inspection.md`)  
> **核心目标**: 
> 1. 彻底根除代码库中的特定厂商硬编码（实现真正的通用协议中立与可插拔 ReviewerClient 工厂）；
> 2. 新增免任务单绑定的通用架构咨询原子工具 `dev_reviewer_consult`，支持随性灵感评估、红队挑刺与实时思考流落盘；
> 3. 硬化主模型防角色扮演治理规则，消除自证偏见与虚假二审漏洞。

---

## 1. 背景与演进契机 (Context & Motivation)

在 Stage 4 交付了基于外部 API 的 `ReviewerClient` 与 `dev_tasks_refine_spec` 之后，系统在实际生产演练与开发者使用中暴露出三大深层痛点与架构暗坑（Architectural Smells）：

1. **主模型“角色扮演”引发的虚假二审漏洞 (Role-Playing Loophole)**：
   - 当用户明确要求“调用 Reviewer 进行评估”时，由于缺乏针对自由问答的专用 MCP 工具，主模型退化为在当前对话中“角色扮演”Reviewer。
   - 这严重违背了“引入异构外部强推理大脑打破执行模型盲区与自证偏见（LLM-as-a-judge blindness）”的系统立项初衷。
2. **“名义上解耦，实装中偷懒绑定”的代码硬编码 (Vendor Coupling Smells)**：
   - 尽管配置层宣称支持 OpenAI、Ollama 等通用端点，但在实现层（`reviewer_engine.py`、`server.py`、`project_config.py`）大量直接导入并实例化了 `DeepSeekClient`，并在报错信息和分支判断中硬编码了特定厂商名称。
3. **“无任务单即无审查”的治理仪式感枷锁 (Workflow Deadlock)**：
   - 现有的全部 10 个 MCP 工具均死死围绕 `dev_tasks_*` 任务单生命周期构建。当开发者突然产生架构灵感、需要比对技术选型或对现有模块做只读诊断时，必须先“伪造一份 Task 1.0 草案”，严重阻碍了探索性研发的流畅度。

---

## 2. 核心架构规划 (Core Architecture)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Quench Stage 5 架构全景                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [ 用户自由提问 / 架构灵感 / 方案评估 / 模块挑刺 ]                       │
│                           │                                             │
│                           ▼                                             │
│               dev_reviewer_consult (新增 MCP 工具)                       │
│                           │                                             │
│       ┌───────────────────┴───────────────────┐                         │
│       ▼                                       ▼                         │
│ 静态前缀组装器 (PromptAssembler)         AST 代码探查 (CodeExplorer)     │
│  • 全局架构基线 (quench_stack.yaml)        • 种子文件切片读取           │
│  • 六大字段契约与审查纪律规范             • 精准 30-50 行高危逻辑截取   │
│       └───────────────────┬───────────────────┘                         │
│                           ▼                                             │
│             ReviewerClient (通用中立客户端工厂)                          │
│    OpenAI / DeepSeek / Ollama / vLLM / Generic /chat/completions       │
│                           │                                             │
│                           ├──> 实时思考流分块落盘 (.agents/logs/reviewer)│
│                           ├──> 自适应 1.0s 低频进度心跳                 │
│                           └──> 通用协议探针提取 Thinking & Usage       │
│                           │                                             │
│                           ▼                                             │
│  [ Reviewer 深度思考报告 / 决策权衡建议 / (可选) 一键生成 DevTask 草案 ]│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 史诗级任务拆解 (Epic Breakdown)

### Epic 1: 通用厂商中立 Reviewer 客户端架构彻底净化 (Vendor Neutrality)
- **目标**: 根除代码中所有特定厂商的硬编码，将客户端实现重构为标准规范的通用架构。
- **改造清单**:
  - `plugins/quench-dev-tasks/server/reviewer_engine.py`:
    - 将 `class DeepSeekClient` 重构为通用的 `class ReviewerClient`；
    - 通用化异常报错信息（如 `ReviewerAuthenticationError(f"[HTTP 401] Reviewer API ({provider}) 鉴权失败")`）；
    - 抽象通用协议探针（Probe）：支持从 `message.reasoning_content`、`message.thought` 或流式 `delta.reasoning_content` 提取思考链，无差别支持 DeepSeek、OpenAI o-series、Ollama 与 vLLM；
    - 消除默认候选变量中对特定厂商 Key 的硬编码偏好。
  - `plugins/quench-dev-tasks/server/project_config.py`:
    - 将 `ReviewerEngineConfig` 的默认值净化为通用标准占位（`provider: "none"`, `model: "default"`, `base_url: "https://api.openai.com/v1"`）。
  - `plugins/quench-dev-tasks/server/server.py`:
    - 将所有 `DeepSeekClient(...)` 强行绑定调用替换为 `ReviewerClient(...)` 工厂模式；
    - 移除 `if config.reviewer_engine.provider in ("deepseek", "deepseek-compatible"):` 的厂商硬分支。

### Epic 2: 新增非任务单架构咨询原子工具 `dev_reviewer_consult`
- **目标**: 突破任务单流水线限制，提供面向即时架构评估、方案推演与红队挑刺的通用入口。
- **接口契约设计**:
  ```python
  @mcp.tool()
  async def dev_reviewer_consult(
      workspace_root: str,
      query: str,
      context_files: Optional[List[str]] = None,
      mode: Literal["critique", "evaluate", "brainstorm", "audit"] = "critique",
      max_hops: int = 1,
      session_id: Optional[str] = None,
  ) -> Dict[str, Any]:
      """Directly consult the senior architecture Reviewer engine without creating a DevTask.
      Mounts global architecture baseline, streams reasoning CoT to .agents/logs/reviewer/thinking.log,
      and provides deep architectural critique, trade-off analysis, or spec suggestions.
      """
  ```
- **核心能力**:
  - **自动挂载稳定缓存前缀**: 调用 `PromptAssembler.build_static_system_prefix`，保证全局架构规格文档全额命中 Prompt Cache；
  - **按需代码切片**: 借助 `CodeExplorer` 仅读取关键上下文，防 Token 泛滥；
  - **实时思考流透明化**: 实时分块写入 `.agents/logs/reviewer/latest-<session_id>.log`，确保审查全过程具备物理可观测性；
  - **一键沉淀任务草案**: 当分析结论建议重构时，返回结构化的建议草案，支持主模型调用 `dev_tasks_propose` 一键转正。

### Epic 3: 主模型防角色扮演治理规则与协议硬化 (Anti-Role-Playing Protocol)
- **目标**: 从提示词与协议上杜绝主模型在审查要求下的自作主张与就地伪装。
- **改造清单**:
  - `plugins/quench-dev-tasks/rules/dev-tasks-discipline.md`:
    - 增加 **【防自证偏见与严禁角色扮演纪律 (Strict Ban on In-Context Reviewer Impersonation)】**；
    - 明确行为红线：主模型收到“审查/评估/二审”明确意图时，严禁自行以 Reviewer 口吻伪造结论，必须通过 `dev_reviewer_consult` 或外部引擎接口发起物理调用；
  - `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`:
    - 完善调用指引，明确自由咨询与任务规约强化的分流时机；
  - 优雅降级体验：当 Reviewer 引擎未配置（`provider: "none"`）或 API 离线时，明确返回 `degraded` 状态卡与人工在新会话切换的提示，禁止静默角色扮演掩盖离线事实。

### Epic 4: 测试套件加固与端到端验收 (Test Suite & DoD)
- **目标**: 保证 100% 测试覆盖与零破坏性。
- **验收命令**:
  - `pytest plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py` (加固通用客户端与探针)
  - `pytest plugins/quench-dev-tasks/server/tests/test_reviewer_consult.py` (新增咨询工具测试)
  - `pytest plugins/quench-dev-tasks/server/tests` (全量 167+ 单测全绿)

---

## 4. 实施阶段规划 (Execution Phases)

1. **阶段 5.1**: 通用客户端重构与厂商硬编码全面清洗（重命名、配置默认值中立化、去除 server.py 厂商分支）；
2. **阶段 5.2**: `dev_reviewer_consult` MCP 工具实现、上下文挂载与思考流落盘联调；
3. **阶段 5.3**: 规则库与技能说明硬化（防角色扮演）；
4. **阶段 5.4**: 新增测试矩阵与全量回归验证。
