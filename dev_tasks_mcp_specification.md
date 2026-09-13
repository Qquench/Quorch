# Quench-DevTasks MCP 服务架构与详细设计规范 (DevTasks Orchestrator Spec)

> **版本**：v1.3.0 (Implemented & Verified)  
> **实施状态**：✔️ 全功能已落地并完成 105+ 项自动化单测验证（覆盖 Antigravity、Cursor 跨工具适配与统一 CLI 控制台）  
> **归属规范**：`dev_tasks_mcp_specification.md`  
> **设计渊源与规范**：[DevTasks Workflow 规范](plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md)  
> **定位**：面向工程仓库的通用开发任务治理与双模型智能调度 MCP 服务。

---

## 一、 原型溯源与核心设计哲学

### 1.1 对标原型协议溯源
本 MCP 服务完全继承并机械化实现了 [DevTasks Workflow 规范](plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md) 中确立的 **“双模型分工审查工作流”**，将其从依赖大模型自觉遵守的“纯文档软约定”，全面升级为带有硬性拦截、物理状态机、分级质量评分的**代码级外部守护进程（MCP Server）**。

### 1.2 核心分工基调：Flash 常驻主控 + Opus 按需外置大脑
- **Flash 作为常驻主控与日常执行器（Everyday Co-pilot & Executor）**：
  - 拥有高额度、毫秒级响应特性，常驻主会话窗口；
  - 负责 80%+ 的日常人机交互、查看状态、命令行执行、具体代码改动与单元测试回归；
  - **绝不让高成本模型浪费在日常搬砖与基础排查上**。
- **Opus 作为“外置大脑增强”（On-Demand Strategic Architect）**：
  - 极度克制地消耗稀缺额度，**仅在以下两种情况被唤醒**：
    1. **用户明确指示**：如用户输入“让 Opus 深度审查当前模块并制定任务单”；
    2. **Flash 自行决策上报（Self-Escalation）**：当遇到多模块复杂重构、疑难死锁排查、或 Flash 连续 2 次执行测试未通过陷入循环时，Flash 主动调起 Opus 求助。
  - Opus 完成严密的高质量任务单编写或架构审查后，**立即下线休眠**，由 Flash 接手具体实施。

### 1.3 模型彻底解耦与逻辑角色映射 (Model Decoupling & Role Aliases)
MCP 服务本身为独立 Python 进程（基于 FastMCP / JSON-RPC），**完全不硬编码任何具体模型名称**。通过配置层进行逻辑角色别名映射：

```yaml
# config.yaml (角色别名映射示例)
version: "1.1"
active_profile: "latest_standard"

roles:
  # 架构师角色（外置大脑）：默认指向当前可用的最新 Opus
  PLANNER:
    provider: "anthropic" # 或通过 IDE 代理
    model_alias: "latest-opus"
    temperature: 0.2
    max_tokens: 8192

  # 执行器角色（常驻主控/打工人）：默认指向当前可用的最新 Flash
  EXECUTOR:
    provider: "google"
    model_alias: "latest-flash"
    temperature: 0.1
    max_tokens: 4096

# 未来若接入新产品线或新模型（如 Pro 4、GPT-5），只需在此追加别名，MCP 核心代码零修改
```

---

## 二、 原 README 核心规则的 MCP 机械化实现

本节将原 `docs/dev_tasks/README.md` 中的所有核心守则，转化为 MCP 服务端的执行逻辑与拦截机制。

### 2.1 审查行为守则的机械化 (原 README §7)

| 原 README §7 审查守则 | MCP 机械化执行与守卫机制 |
| :--- | :--- |
| **审查阶段绝不修改任何源码** | 当 MCP 处于 `PLANNER` 审查上下文时，**只暴露只读检索与任务生成工具**，物理切断代码编辑类 Tool，确保审查阶段仅产出任务单。 |
| **先读文档再看代码** | Opus 生成任务时，MCP 校验其引用的上下文。若未包含项目架构设计文档（如 `docs/architecture/internal_system_design.md`），MCP 提出上下文警告。 |
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
  凡涉及业务逻辑、计算规则、模型扩展的任务，**必须在验证命令中包含单元测试断言要求**，强制要求在 `backend/tests/` 中添加断言，确保 `run_safe_tests.py` 覆盖。

---

### 2.3 执行模型 Flash 的行为铁律 (原 README §8.4)

当 Flash 检出任务开始执行时，MCP 自动注入并监控以下执行守则：
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
    [*] --> ⬜_待确认: Opus / Flash 生成任务单
    ⬜_待确认 --> ✅_已确认: 业主明确同意 (confirm_tasks)
    ⬜_待确认 --> ⏭️_已跳过: 业主决策不实施 (skip_tasks)
    
    state "安全屏障 (Hard Gate)" as Gate {
        note right of Gate: Flash 无法从未确认的任务中获取执行权限
        ✅_已确认 --> 🔨_执行中: Flash 检出任务 (checkout_task)
    }

    🔨_执行中 --> ✔️_已完成: Flash 提交且通过 DoD 测试 (complete_task)
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

MCP 对外暴露 7 个原子化强类型工具：

### 1. `dev_tasks_status`
- **调用者**：Flash / Opus
- **作用**：探查激活工作区的 `docs/dev_tasks/` 目录，获取当前未闭环任务单的状态分布与阻塞项。

### 2. `dev_tasks_propose`
- **调用者**：Opus（或具备架构审查权限时的 Flash）
- **作用**：生成/追加符合六大字段规范的标准任务单（`docs/dev_tasks/YYYY-MM-DD_<desc>.md`）。

### 3. `dev_tasks_confirm`
- **调用者**：业主通过自然语言指令由 Flash 调起
- **作用**：将指定任务推进为 `✅ 已确认` 或 `⏭️ 已跳过`。

### 4. `dev_tasks_checkout`
- **调用者**：Flash
- **作用**：获取下一个处于 `✅ 已确认` 状态的任务执行指引，并原子化将其标记为 `🔨 执行中`。若无确认任务，直接抛错拦截。

### 5. `dev_tasks_complete`
- **调用者**：Flash
- **作用**：提交任务完成报告。必须附带 DoD 执行输出日志与新增的断言单测信息。

### 6. `dev_tasks_escalate`
- **调用者**：Flash
- **作用**：自主唤醒 Opus 外置大脑进行深度架构设计或死锁排查。

### 7. `dev_tasks_archive` (原 README §6)
- **调用者**：自动化 / Flash
- **作用**：当任务单所有任务均为 `✔️ 已完成` 或 `⏭️ 已跳过`，自动将该文件移入 `docs/dev_tasks/archive/`，并将任务摘要增量同步至项目根目录 `CHANGELOG.md` 与内部设计手册。

---

## 六、 供 Opus 模型二次审查的重点课题清单 (Review Checklist for Opus)

> **请 Opus 重点对以下 5 个深水区课题进行批判性审查并提出优化建议**：
> 1. **并发与文件锁冲突**：当 Flash 在快速编辑代码并调用 `complete_task` 时，如何防止 Markdown 任务文件被外部 Git 操作或编辑器并发写入损坏？
> 2. **Subagent 调度与增量上下文筛选**：Flash 调用 `escalate` 唤醒 Opus 时，如何最经济地筛选传递给 Opus 的上下文（只传相关文件核心片段与报错，避免灌入全量巨型日志消耗 Token）？
> 3. **单测断言刚性校验 (Mandatory Assertion Rule)**：在 `complete_task` 中，如何确保 Flash 真正添加了单测断言，而非空口虚报？是否应由 MCP 执行一次 `git diff` 针对 `tests/` 目录的物理审计？
> 4. **异常恢复与孤儿任务处置**：如果 Flash 在 `🔨 执行中` 途中会话意外中断、崩溃或死循环退出，MCP 在下一次启动时如何安全恢复或回滚任务状态？
> 5. **模型版本热升级平滑度**：当 Antigravity 引入新一代模型矩阵（如 Pro 4、GPT-5）时，配置切换机制是否做到了最大程度的平滑与无感？

---

## 七、 落地实现与工程交付注册表 (Implementation Registry)

本规范所定义的全部架构设计与工具链已持续迭代至 **2026-09-13**，完整落地于 `plugins/quench-dev-tasks/`，并通过自动化测试验证（105/105 passed）。

| 规范设计章节 | 实际交付文件/模块 | 核心机制与职责 |
| :--- | :--- | :--- |
| **§2.1 审查守则** | `rules/dev-tasks-discipline.md`<br>`skills/dev-tasks-review/` | 常驻约束只提任务不碰源码、三级质量弹性分级规范 |
| **§2.2 状态机** | `server/state_machine.py` | 严格状态枚举单向迁移、`FileLock` 跨进程文件排他锁、Unicode Emoji 兼容正则 |
| **§2.3 六大字段** | `server/schema_validator.py` | 强制六大段落完整性校验、代码块格式提取、粒度超限告警 |
| **§2.4 物理守卫** | `server/hooks/file_scope_guard.py`<br>`server/hooks/context_injector.py`<br>`scripts/git_pre_commit_guard.py` | `PreToolUse` 钩子拦截范围外修改并弹出带理由确认框；`PreInvocation` 注入任务提醒；Git Pre-commit Guard 物理兜底拦截 |
| **§4.0 项目解耦** | `server/project_config.py`<br>`templates/quench_stack.yaml` | 通过 `.agents/quench_stack.yaml` 读取项目专属配置，核心完全解耦，支持版本迁移 |
| **§5.0 8 大工具** | `server/server.py` | 暴露 `status` / `propose` / `confirm` / `checkout` / `complete` / `escalate` / `archive` / `set_bypass` |
| **§1.2 外置大脑** | `agents/reviewer/agent.md` | 定义架构审查与任务规划专家 Subagent 角色 |
| **跨工具适配层** | `server/adapters/` | 单核多适配器架构，支持 Antigravity、Cursor 及通用 CLI 适配器与环境探测 |
| **规则导出器** | `scripts/rules_exporter.py` | 将纪律手册精炼导出为 `.cursorrules` 与 `.cursor/rules/quench-dev-tasks.mdc` |
| **统一终端 CLI** | `server/cli.py` | 提供 `quench status/check/init/archive` 纯命令行入口点，ANSI 彩色自适应 |
| **一键接入脚手架** | `scripts/init_project.py`<br>`scripts/install.py` | 支持 `--ide {antigravity,cursor,all}` 与 `--install-git-hook` 自动化部署与预检 |
| **测试矩阵** | `server/tests/` (105 项单测) | 覆盖状态机、校验器、工具链、适配器、CLI、Hooks 守卫及导出脚手架，100% 通过 |

