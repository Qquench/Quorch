# Quench-DevTasks MCP 服务架构与详细设计规范 (DevTasks Orchestrator Spec)

[English](dev_tasks_mcp_specification.md) | [简体中文](dev_tasks_mcp_specification_zh.md)

> **版本**：v1.4.0 (Implemented & Verified)  
> **实施状态**：✔️ 全功能已落地并完成 167+ 项自动化单测验证（覆盖 Antigravity、Cursor 跨工具适配、ReviewerClient 解耦引擎、RotatingFileSink 流式落盘观测、Draft 草案物理 Lint 门禁与统一 CLI 控制台）  
> **归属规范**：`dev_tasks_mcp_specification.md`  
> **设计渊源与规范**：[DevTasks Workflow 规范](plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md)  
> **定位**：面向工程仓库的通用开发任务治理与双模型智能调度 MCP 服务。

---

## 一、 原型溯源与核心设计哲学

### 1.1 对标原型协议溯源
本 MCP 服务完全继承并机械化实现了 [DevTasks Workflow 规范](plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md) 中确立的 **“双模型分工审查工作流”**，将其从依赖大模型自觉遵守的“纯文档软约定”，全面升级为带有硬性拦截、物理状态机、分级质量评分的**代码级外部守护进程（MCP Server）**。

### 1.2 核心分工基调：日常执行模型 (Runner) + 架构审查外置大脑 (Reviewer)
- **日常执行模型 Runner（Everyday Co-pilot & Executor）**：
  - 拥有高吞吐、毫秒级响应特性，常驻主会话窗口；
  - 负责 80%+ 的日常人机交互、查看状态、命令行执行、具体代码改动与单元测试回归；
  - **绝不让高成本/稀缺推理模型浪费在日常搬砖与基础排查上**。
- **架构审查外置大脑 Reviewer（On-Demand Strategic Architect）**：
  - 极度克制地消耗稀缺额度，**仅在以下两种情况被唤醒**：
    1. **用户明确指示**：如用户输入“让 Reviewer 深度审查当前模块并制定任务单”；
    2. **Runner 自行决策上报（Self-Escalation）**：当遇到多模块复杂重构、疑难死锁排查、或 Runner 连续 2 次执行测试未通过陷入循环时，Runner 主动调起 Reviewer 求助。
  - Reviewer 完成严密的高质量任务单编写或架构审查后，**立即下线休眠**，由 Runner 接手具体实施。

### 1.3 模型彻底解耦与可插拔 ReviewerClient 抽象 (Model Decoupling & Pluggable ReviewerClient)
MCP 服务本身为独立 Python 进程（基于 FastMCP / JSON-RPC），**完全不硬编码任何具体模型名称**。通过目标项目工作区配置 `.agents/quench_stack.yaml::reviewer_engine` 声明审查后端：

```yaml
# 工作区 .agents/quench_stack.yaml 配置
schema_version: "1.0"
project_name: "MyProject"

reviewer_engine:
  mode: "auto"                    # "auto" | "subagent" | "engine" | "manual"
  strategy_order:                 # 回退策略链
    - "subagent"                  # 1. 优先调用 IDE 宿主的原生 Subagent
    - "engine"                    # 2. 直连上游 API 引擎 (DeepSeek/OpenAI/Ollama)
    - "manual"                    # 3. 网络与 API 均不可用时优雅降级为交互式引导
  provider: "deepseek"            # "deepseek" | "openai" | "ollama" | "custom"
  model: "deepseek-flash"         # 极高性价比思考模型
  api_key_env: "DEEPSEEK_API_KEY_Quench" # 环境变量名称，杜绝明文凭证硬编码
  base_url: "https://api.deepseek.com"
  thinking: true                  # 启用思考流 (reasoning_content) 流式输出
  reasoning_effort: "high"        # 思考深度配额 ("low" | "medium" | "high")
  timeout_seconds: 60
  max_retries: 2
  max_tool_hops: 3
```

上游后端由可扩展的 `ReviewerClient` 统一抽象分发：
- **`DeepSeekReviewerClient`**：原生支持 CoT 思考流增量输出与 Prompt Cache 缓存命中计费探测；
- **`OpenAIReviewerClient`**：无缝对接 OpenAI 兼容 Chat Completions 标准接口；
- **`OllamaReviewerClient`**：支持本地零遥测、全离线工业车间推理；
- **`SubagentReviewerClient`**：向 IDE 宿主（如 Antigravity / Cursor）委派 Reviewer 智能体；
- **`ManualFallbackClient`**：在网络全部断连时降级为模板引导开发者直接填写。

---

## 二、 原 README 核心规则的 MCP 机械化实现

本节将原 `docs/dev_tasks/README.md` 中的所有核心守则，转化为 MCP 服务端的执行逻辑与拦截机制。

### 2.1 审查行为守则的机械化 (原 README §7)

| 原 README §7 审查守则 | MCP 机械化执行与守卫机制 |
| :--- | :--- |
| **审查阶段绝不修改任何源码** | 当 MCP 处于 `PLANNER` 审查上下文时，**只暴露只读检索与任务生成工具**，物理切断代码编辑类 Tool，确保审查阶段仅产出任务单。 |
| **先读文档再看代码** | Reviewer 生成任务时，MCP 校验其引用的上下文。若未包含项目架构设计文档（如 `docs/architecture/internal_system_design.md`），MCP 提出上下文警告。 |
| **区分“问题”与“偏好”** | 任务输入校验器强制要求：每条修改必须具备“会导致 bug、数据丢失、安全风险、构建失败”的客观论证，拒绝代码风格微调。 |
| **尊重离线局域网工业定位** | 提示词注入层强制声明项目边界：**严禁将公网互联网高安全标准强加于离线车间局域网系统**（如公网 JWT 轮转、复杂防刷策略等）。 |
| **每条问题必须可复现或可论证** | 【缺陷根因】字段必须给出明确的触发场景、数据边界或代码冲突点。 |
| **不替业主做架构决定** | 遇到多方案权衡（如合表 vs 外键），MCP 校验器要求提供选项 A/B 供业主选择，并自动标记该任务为 `⬜ 待决策`。 |

---

### 2.2 任务六大固定字段的结构化契约 (原 README §8.2)

原 `README.md` 要求每条独立任务必须包含固定顺序的六项内容。MCP 将其定义为强类型 Schema，并废除死板行数限制，引入**弹性质量分级**：

#### 1. 【涉及文件】 (`affected_files`)
- **格式要求**：项目相对路径或绝对路径，且必须明确标注操作类型：
  `[MODIFY]` / `[NEW]` / `[DELETE]` / `[RENAME]`。
- **粒度守卫**：若单个任务涉及超过 3 个核心文件，MCP 返回 `TaskGranularityWarning`，提示建议拆分。

#### 2. 【缺陷根因与修改目标】 (`root_cause_and_goal`)
- **格式要求**：用 1~2 句话明确说明：
  - 当前代码的问题根因（而非表层症状）；
  - 修改后应达到的明确工程效果。

#### 3. 【目标签名与类型契约】 (`type_contracts`) —— **弹性放宽区**
- **原则**：**只写新增或变更的签名行，禁止贴无关的完整 class 复制**。
- **质量弹性豁免**：
  - 彻底取消原文档死板的 “≤ 5 行” 限制；
  - 允许完整编写 20~30 行的复杂 TypeScript `interface`、Pydantic `BaseModel`、SQL DDL 或 CSS 动画定义，**保证类型契约 100% 严密，杜绝隐式 any**。

#### 4. 【分步改造指引】 (`steps`) —— **过程精炼区**
- **原则**：3~5 个带动作说明的编号步骤。
- **MCP 拦截机制**：
  - 步骤必须采用“一句话动作描述 + 关键伪代码/注释”。
  - **红线拦截**：若在步骤中发现贴出超过 15 行的连续具体业务实现代码，MCP 视为“越俎代庖写全量实现”，拦截并提示浓缩为关键骨架。

#### 5. 【防御与边缘校验】 (`defensive_checks`) —— **鼓励穷尽区**
- **格式要求**：必须采用 `- ` 列表格式，逐条列出异常情况与预期行为。
- **质量加分机制**：MCP 鼓励详尽列出空值处理、溢出、并发脏读、掉线冷灰等边界。**此部分内容不受任何总行数限制**。

#### 6. 【DoD 验证命令】 (`dod_commands`) —— **改逻辑必加单测断言**
- **原则**：必须提供可直接在终端执行的测试验证命令。
- **核心铁律（Mandatory Assertion Rule）**：
  凡涉及业务逻辑、计算规则、模型扩展的任务，**必须在验证命令中包含单元测试断言要求**，强制要求在测试套件中添加断言，确保测试全量覆盖。

### 2.4 零轮询可观测性与 RotatingFileSink 机制
长耗时架构审查推导过程中，为兼顾开发者实时进度监控与 FastMCP 协议纯净度：
- **低频 MCP 心跳通知**：以稳健的 ~1.0s 间隔向客户端发送 `progress_pct` 预估百分比与步骤进度通知，严禁高频打扰；
- **零 stdout 通道污染**：服务端标准输出（`sys.stdout`）严格专用于 JSON-RPC 协议帧封包，全链路杜绝任何裸 print 文本外泄；
- **RotatingFileSink 独立落盘**：思考过程与思维链增量实时写入 `.agents/.logs/reviewer_live.log`（单文件 10MB，自动保留 3 份历史轮转），开发者可在终端直接通过 `tail -f` 旁路查看；
- **防死循环中断保护**：设立 32,000 Token 思考软上限与超时强制熔断机制，杜绝模型幻觉无限打转。

### 2.5 Draft 任务草案态与物理可行性 Lint 闸门
为防止审查模型脑补虚构文件路径或虚构命令直接流入正式队列：
- **Draft 任务草案态 (`📝 草案`)**：任务标题包含 `(草案)` 或带有 `<!-- quench-task-meta: {"draft": true} -->` 元数据注释；
- **队列天然隔离**：`dev_tasks_status` 默认设置 `include_drafts=False`，将草案任务隔离至 `draft_queue`，绝不混入正式 `pending_queue`；
- **物理可行性 Lint 校验 (`lint_task_physical_feasibility`)**：
  1. *路径穿越设防*：所有受影响文件路径严格锚定在 `workspace_root` 之内，校验 `os.path.commonpath`；
  2. *物理存在验证*：标记为 `[MODIFY]` 或 `[DELETE]` 的目标文件必须在磁盘物理存在 (`os.path.exists == True`)；
  3. *覆盖冲突排查*：标记为 `[NEW]` 的目标文件在磁盘严禁预先存在，父目录必须合法；
  4. *DoD 命令语法安全*：以白名单 dry-run 模式预检单测命令（`pytest --collect-only -q -o pythonpath=.`），拦截危险 Shell 元字符（`;`, `&`, `|`, `$`, `` ` ``, `>`, `<`）；
- **原子化安全晋升**：`dev_tasks_promote_draft` 在文件排他锁与临时原子替换保障下重新校验物理门禁，全绿自动擦除草案标记晋升为正式 `⬜ 待确认`。

---

### 2.6 执行模型 Runner 的行为铁律 (原 README §8.4)

当 Runner 检出任务开始执行时，MCP 自动注入并监控以下执行守则：
1. **严格按指引顺序执行**，不得跨越步骤；
2. **不得修改任务未涉及的文件**（MCP 可通过 `git status` 监控修改范围，若发现漂移立即告警）；
3. **保留所有现有注释与文档字符串**，除非任务明确要求修改；
4. **遇到指引不明确时，停止并说明问题，严禁猜测**；
5. **改逻辑必加单测断言**，提交任务完成时必须提供测试通过证明。

---

## 三、 任务生命周期与物理安全状态机 (原 README §4)

MCP 充当严密的状态机看门狗，杜绝任何未经业主确认的代码改动：

```mermaid
stateDiagram-v2
    [*] --> 📝_草案: Reviewer 推导草案 / 物理 Lint 拦截 (refine_spec)
    📝_草案 --> ⬜_待确认: 物理 Lint 全绿晋升 (promote_draft)
    [*] --> ⬜_待确认: 直接提单 (propose)
    ⬜_待确认 --> ✅_已确认: 业主明确同意 (confirm action=confirm)
    ⬜_待确认 --> ⏭️_已跳过: 业主决策不实施 (confirm action=skip)
    
    state "安全屏障 (Hard Gate)" as Gate {
        note right of Gate: Runner 无法从未确认的任务中获取执行权限
        ✅_已确认 --> 🔨_执行中: Runner 检出任务 (checkout)
    }

    🔨_执行中 --> ✔️_已完成: Runner 提交且通过物理单测断言审计 (complete)
    🔨_执行中 --> 🔄_需返工: DoD 验证失败或逻辑偏离
    🔄_需返工 --> 🔨_执行中: 重新修改并验证
    
    ✔️_已完成 --> 📦_已归档: 全单 100% 完成，自动归档并更新 CHANGELOG
    ⏭️_已跳过 --> 📦_已归档: 全单无遗留未关闭项
```

---

## 四、 项目特有技术栈速查与环境边界 (原 README §9)

为了使该 MCP 能够在跨项目复用时准确感知各项目的特定陷阱，MCP 引入 **项目环境感知机制（Project Stack Manifest）**：
* 在各项目根目录 `.agents/quench_stack.yaml` 声明技术栈与专属规则，由 MCP 自动加载；
* 针对具体业务项目（例如嵌入式工控或 Web 全栈项目），MCP 自动注入技术栈速查示例：
  - **后端**：Python 3.11 + FastAPI + SQLAlchemy，ORM 必须使用 `SessionLocal()`，路由必须位于 `backend/routers/`；
  - **前端**：Vue 3 + Vite + Element Plus，SPA 构建产物由后端静态托管；
  - **边缘通信**：MQTT (paho-mqtt) Broker 端口 `11883`，Modbus TCP 双寄存器安全互锁；
  - **离线安全**：SQLite (WAL mode)，看门狗指数退避与滑动窗口熔断；
  - **环境约束**：严禁调用系统级全局 Python，强制使用项目局部虚拟环境。

---

## 五、 MCP 工具接口详细契约 (Tools Specification)

MCP 对外暴露 10 个原子化强类型工具：

### 1. `dev_tasks_status`
- **调用者**：Runner / Reviewer
- **作用**：探查激活工作区的任务单目录，获取当前未闭环任务单的状态分布与阻塞项。支持 `include_drafts` 参数控制草案队列隔离。

### 2. `dev_tasks_propose`
- **调用者**：Reviewer / 业主
- **作用**：生成/追加符合六大字段规范的标准正式任务单。

### 3. `dev_tasks_confirm`
- **调用者**：业主通过自然语言指令调起
- **作用**：将指定任务推进为 `✅ 已确认` 或 `⏭️ 已跳过`，或置为 `🔄 需返工`。

### 4. `dev_tasks_checkout`
- **调用者**：Runner
- **作用**：获取下一个处于 `✅ 已确认` 状态的任务执行指引，并原子化将其标记为 `🔨 执行中`。若无确认任务，直接抛错拦截。

### 5. `dev_tasks_complete`
- **调用者**：Runner
- **作用**：提交任务完成报告。通过 `git diff` 针对测试文件与断言标记执行物理审计，全部通过后标记为 `✔️ 已完成`。

### 6. `dev_tasks_escalate`
- **调用者**：Runner
- **作用**：自主唤醒 Reviewer 外置大脑进行深度架构设计或死锁排查。

### 7. `dev_tasks_refine_spec`
- **调用者**：Runner / 外部客户端
- **作用**：调用 ReviewerClient 后端进行多轮规格审查推导，流式输出思考日志，并接入物理可行性门禁。

### 8. `dev_tasks_promote_draft`
- **调用者**：Runner / 业主
- **作用**：运行物理可行性 Lint 闸门校验草案，全绿后原子化抹除草案标记并晋升为正式 `⬜ 待确认`。

### 9. `dev_tasks_archive`
- **调用者**：自动化 / Runner
- **作用**：当任务单所有任务均为 `✔️ 已完成` 或 `⏭️ 已跳过`，自动将该文件移入 `docs/dev_tasks/archive/`，并将任务摘要增量同步至项目根目录 `CHANGELOG.md`。

### 10. `dev_tasks_set_bypass`
- **调用者**：业主授权紧急通道
- **作用**：管理临时时间窗口快速旁路令牌，附带严格的审计日志记录。

---

## 六、 落地实现与工程交付注册表 (Implementation Registry)

本规范所定义的全部架构设计与工具链已完整落地于 `plugins/quench-dev-tasks/`，并通过自动化测试验证（167/167 passed）。

| 规范设计章节 | 实际交付文件/模块 | 核心机制与职责 |
| :--- | :--- | :--- |
| **§2.1 审查守则** | `rules/dev-tasks-discipline.md`<br>`skills/dev-tasks-review/` | 常驻约束只提任务不碰源码、三级质量弹性分级规范 |
| **§2.2 状态机** | `server/state_machine.py` | 严格状态枚举单向迁移、`FileLock` 跨进程文件排他锁、Unicode Emoji 兼容正则 |
| **§2.3 六大字段** | `server/schema_validator.py` | 强制六大段落完整性校验、代码块格式提取、粒度超限告警 |
| **§2.4 零轮询观测** | `server/observability.py` | `RotatingFileSink` 独立落盘、~1.0s 低频心跳、FastMCP 传输零污染 |
| **§2.5 草案与物理门禁** | `server/schema_validator.py`<br>`server/server.py` | `[MODIFY]` 物理存在、`[NEW]` 覆盖排查、pytest dry-run 收集、`dev_tasks_promote_draft` |
| **§1.3 审查引擎** | `server/reviewer_client.py` | 可插拔 DeepSeek (思考流与 Prompt Cache)、OpenAI、Ollama、Subagent 及 Manual 调度 |
| **§2.6 物理守卫** | `server/hooks/file_scope_guard.py`<br>`server/hooks/context_injector.py`<br>`scripts/git_pre_commit_guard.py` | `PreToolUse` 钩子拦截范围外修改并弹出带理由确认框；`PreInvocation` 注入任务提醒；Git Pre-commit Guard 物理兜底拦截 |
| **§4.0 项目解耦** | `server/project_config.py`<br>`templates/quench_stack.yaml` | 通过 `.agents/quench_stack.yaml` 读取项目专属配置与审查后端，核心完全解耦 |
| **§5.0 10 大工具** | `server/server.py` | 暴露 `status` / `propose` / `confirm` / `checkout` / `complete` / `escalate` / `refine_spec` / `promote_draft` / `archive` / `set_bypass` |
| **§1.2 外置大脑** | `agents/reviewer/agent.md` | 定义架构审查与任务规划专家 Subagent 角色 |
| **跨工具适配层** | `server/adapters/` | 单核多适配器架构，支持 Antigravity、Cursor 及通用 CLI 适配器与环境探测 |
| **规则导出器** | `scripts/rules_exporter.py` | 将纪律手册精炼导出为 `.cursorrules` 与 `.cursor/rules/quench-dev-tasks.mdc` |
| **统一终端 CLI** | `server/cli.py` | 提供 `quench status/check/init/archive` 纯命令行入口点，ANSI 彩色自适应 |
| **一键接入脚手架** | `scripts/init_project.py`<br>`scripts/install.py` | 支持 `--ide {antigravity,cursor,all}` 与 `--install-git-hook` 自动化部署与预检 |
| **测试矩阵** | `server/tests/` (167 项单测) | 覆盖状态机、校验器、工具链、适配器、CLI、Hooks 守卫、观测落盘与草案门禁，100% 通过 |


