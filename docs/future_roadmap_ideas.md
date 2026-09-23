# 💡 Future Roadmap Ideas & Prospective Proposals (未来路线构想与灵感暂存)

<!-- quench-doc-meta: {"normative": false, "generates_tasks": false} -->

> ⚠️ **Non-Normative Brainstorm Pool / 非当期排期承诺**  
> This document serves as a dedicated holding area for future architectural brainstorms, exploratory RFCs, and prospective feature ideas not scheduled for the active version milestone.  
> **Notice for Agents & Reviewer**: Ideas documented here represent exploratory proposals. Do NOT automatically decompose entries from this file into DevTasks until they are formally matured and scheduled into an active roadmap under `docs/roadmap/`.

---

## 🧭 How to Use This Idea Pool (使用指引)

- **Adding a new idea**: When a spontaneous idea or future feature comes up that does not belong in the current milestone, simply append a new section below with:
  - `## YYYY-MM-DD — <Idea Title>`
  - **Motivation & Background (背景与契机)**
  - **Why not now? (为什么当期不做)**
  - **Key Architecture & Preconditions (核心构想与前置条件)**
- **No catalog maintenance**: You do NOT need to maintain a separate README index or table for this file.
- **Graduating an idea**: When an idea matures and is scheduled into a release cycle, move it to `docs/roadmap/` as part of that stage's roadmap.
- **Rejecting an idea**: If an idea is evaluated and rejected, mark it as `❌ Rejected: <Reason>` and keep the record to prevent future AI agents or maintainers from repeatedly revisiting the same dead-end.

---

## 🔀 Hybrid Reviewer: Native Subagent & External API Dynamic Routing
*(Originally drafted for Stage 5 exploratory research)*

### 1. Motivation & Context
Developers frequently have access to multiple complementary reviewer capabilities:
1. **Host-Native Subagents**: Built-in IDE agents (Antigravity, Claude Code) with native access to IDE workspace state, browser simulators, and zero external API token costs.
2. **External / Local Deep Reasoning APIs**: Frontier thinking models (DeepSeek-Reasoner / Flash, OpenAI o-series, local Ollama models) with strong deadlock detection and exhaustive branch reasoning.

The current system relies on a static priority waterfall (`strategy_order: ["subagent", "engine", "manual"]`). A future dynamic router would allow intelligent, context-aware traffic splitting.

### 2. Core Architecture: Dynamic Reviewer Router
- **Task-Aware Semantic Routing**:
  - *UI / Visual / Accessibility Tasks*: Route preferentially to native subagents with DOM/screenshot inspection capabilities.
  - *Concurrency / State Machine / Crypto Core*: Route to external thinking reasoning models to exhaustively probe race conditions and edge states.
  - *Documentation / Configuration Tweaks*: Rapid pass-through or lightweight local check.
- **Red-Team Duel (Adversarial Cross-Validation)**:
  - For high-risk refactorings (`[P0-CRITICAL]`), employ host subagents for readability and architectural design review, combined with external reasoning models acting as an adversarial red-team to search for boundary flaws before task checkout.
- **Quota & Cost Elasticity**:
  - Dynamically fallback between host quotas and external API tokens when encountering 429 rate limits or context window exhaustion.

---

## 🛡️ Cross-Language Zoning Governance & Anti-Degradation Guards
*(Originally drafted for multi-language enterprise codebases)*

### 1. Motivation & Context
File-path whitelists alone do not prevent semantic degradation inside allowed files:
1. AI models may silently prune error handling branches or weaken assertions during refactoring.
2. AI may lower assertion strictness in unit tests to artificially turn DoD green.
3. AI tends to rewrite multi-thousand-line files from scratch, accidentally destroying concurrency locks and performance optimizations.

### 2. Core Architecture: Four-Zone Model & Frozen Overlay
- **`Z-KERNEL` (Logic Microkernel)**: Core state machines, critical algorithms. Rule: error handling branches and assertion counts must never net-decrease.
- **`Z-CONTRACT` (Interface Layer)**: Public APIs, Protocol/Trait definitions, `.d.ts`. Rule: breaking changes mandate companion migration tests and task records.
- **`Z-TEST` (Adversarial Test Suite)**: Unit and integration tests. Rule: test coverage and assertion strength must not be diluted.
- **`Z-GLUE` (Glue & Wiring)**: CLI wiring, adapter glue. Rule: business logic expansion inside glue code is intercepted.
- **`⊕ FROZEN` (Frozen Overlay)**: Machine-generated code, lockfiles. Rule: immutable, any write triggers physical DENY.
- **Pluggable Adapters (`LanguageZoningAdapter`)**: AST-based auditing for Python and TypeScript, with lexical fallback for Go, Rust, and C++.

---

## 2026-09-21 — Cross-Host Hard Interception Bridge & Universal Hook Proxy (跨宿主硬性拦截桥接与通用 Hook 代理)

### 1. Motivation & Background (背景与契机)
当前在 Antigravity 宿主环境下，系统借助原生 `PreToolUse` Hook 实现了针对未授权文件修改的真实交互式弹窗阻断（`force_ask`）。然而在 Cursor, Windsurf, Claude Code 等外部 IDE 环境中，目前主要退化为依托 `.cursorrules` / `.mdc` 等提示词软约束与 Git 提交前的后置防护 (`git_pre_commit_guard.py`)。缺乏跨编辑器的统一中途物理拦截能力，导致不同客户端用户的安全防护体验存在非均质性。

### 2. Why not now? (为什么当期不做)
- Antigravity 是当前核心且深度实战验证的主力研发环境，现有方案已满足日常生产闭环。
- 各大 AI 编辑器的拦截与插件生态规范仍在剧烈迭代（例如 Cursor 尚未开放对等的外部进程实时 Tool Call 阻断 Hook），过早深入私有逆向会导致巨大的兼容性负担与脆弱维护成本。

### 3. Key Architecture & Preconditions (核心构想与前置条件)
- **Universal Pre-Tool Proxy / LSP Shim**:
  - 构建轻量级本地文件代理层或语言服务器（LSP）拦截 Shim，在任何外部工具触发写入前透明捕获 I/O 事件并向 `FileScopeGuard` 请求鉴权。
- **Host Extension Bridge**:
  - 开发通用的轻量 VS Code / Cursor 扩展插件，通过 IPC 与本地 Quench FastMCP 进程心跳同步，将文件越界事件投递至编辑器原生 Modal 确认窗口。
- **前置依赖**: 跨平台进程间通信 (IPC) 协议抽象与低开销文件系统监听机制。

---

## 2026-09-21 — DAG-Based Concurrency & Multi-Task State Machine (基于有向无环图的并发任务状态机与资源隔离)

### 1. Motivation & Background (背景与契机)
当前 `state_machine.py` 严格基于 `filelock` 实现跨进程单核排他锁，硬性保证“同一时刻全项目仅有一项任务处于 `In_Progress`”。对于单开发者结对编程而言，这构成了极强的心智防线；但在大型企业协作场景或多 Subagent 树状并行开发（如前端、后端、数据模型互不依赖的模块同时推进）时，该串行设计构成了自动化吞吐瓶颈。

### 2. Why not now? (为什么当期不做)
- 现阶段重心是单兵作战的“防翻车”与“零越界”，全局互斥锁能够杜绝所有死锁与状态竞态，可靠性收益最高。
- 引入并发任务依赖管理将显著复杂化状态转移矩阵与冲突回滚逻辑。

### 3. Key Architecture & Preconditions (核心构想与前置条件)
- **Disjoint File Set Locking (不相交文件集合锁)**:
  - 检出任务时计算任务间 `[Affected Files]` 的交集。若两个已确认任务的作用域集合不重叠（$S_A \cap S_B = \emptyset$），允许不同的 Worker 子代理并行 Checkout 执行。
- **DAG Dependency Graph & Conflict Detection**:
  - 任务元数据支持声明 `depends_on: [Task_ID]`，构建严格拓扑序的有向无环图执行流水线。
- **Phase Merge Gate (阶段合并门禁)**:
  - 当并行分支任务汇合时，触发统一的回归测试与 Git 冲突消解门禁。

---

## 2026-09-21 — Minimal Governance Tier & One-Click Distribution (分级治理门槛与单命令分发包)

### 1. Motivation & Background (背景与契机)
Quench 强制推行的六大核心字段规范（涉及文件、缺陷根因、签名契约、步骤指引、边缘校验、DoD命令）极大保障了高风险复杂业务的交付质量，但对初阶开源使用者和日常极小粒度修补（如修复单点文本、调整常量值）而言，门槛较高、流程偏重，容易在开源社区初次体验阶段产生认知摩擦。

### 2. Why not now? (为什么当期不做)
- 治理套件首要目标是立规矩，先树立“绝对严谨、无死角防御”的技术标杆，避免因过早放松校验而削弱防御护城河。
- 模板与脚手架需等待底层各适配器（Adapters）进一步稳定后再行固化。

### 3. Key Architecture & Preconditions (核心构想与前置条件)
- **Progressive Governance Tier (渐进式治理级别)**:
  - 在 `quench_stack.yaml` 中支持配置治理模式：
    - `strict`: 完整六大字段 + 刚性 DoD 断言审计 + AST 探查；
    - `minimal`: 仅强制约束 `[Affected Files]` 白名单与 `[DoD Verification Commands]`，其余字段转为选填，降低轻度任务负担。
- **One-Click Package Distribution (开箱即用分发)**:
  - 自动化构建并发布至 PyPI，允许外部开发者直接执行 `uvx quorch --init` 或 `pipx run quorch init` 一键初始化任何第三方技术栈项目。
- **Interactive TUI / CLI Wizard**:
  - 增强 `quorch` CLI 交互式向导，支持通过键盘方向键与问答一键生成符合规范的标准任务草案。

---

## 2026-09-23 — Microkernel Decoupling & Inversion of Control: Zero-API-Cost Pure Governance (微内核彻底解耦与控制权反转：零额外 API 费用的纯粹治理微内核)

### 1. Motivation & Background (背景与契机)
随着现代 AI IDE（如 Antigravity / Claude Code）普及原生 Subagent 多智能体协作并提供包月/包年订阅套餐，开发者倾向于将任务规划者（Reviewer）与工程搬砖者（Runner）全部配置为 IDE 内生子代理，实现 $0 额外第三方模型 API 账单。
在此背景下，Quorch 服务端若继续强耦合主动出站 HTTP API 客户端，将导致逻辑冗余并割裂开发者已付费的 IDE 内置配额。需要推演系统从“代理执行编排者”向“纯粹任务治理微内核（Pure Governance Kernel）”的彻底解耦路径。

### 2. Why not now? (为什么当期不做)
- 当前 Stage 5 首要目标是实现厂商中立性（OpenAI 兼容协议标准化）与 `dev_reviewer_consult` 即席咨询支持，现有基于 API 的外部 Reviewer 通路已通过 167 项完整测试验证，稳定性最高。
- 剥离或降级出站调用逻辑属于协议拓扑维度的根本性架构演进，需先沉淀完备的子代理指令契约与租约回收机制，避免激进破坏当期交付节奏。

### 3. Key Architecture & Preconditions (核心构想与前置条件)
- **Control Inversion & Return Contract Seam (控制权反转与返回契约 Seam)**:
  - 架构抽象点收敛于 `dev_tasks_refine_spec` 的返回契约（Discriminated Union）：
    - `mode: subagent`: 返回 `dispatch_directive`（结构化调度指令，由主代理/IDE 分派子代理，零出站请求）；
    - `mode: engine`: 返回 `inline_reasoning`（Quorch 接管多轮推理循环并流式返回，即现状）；
    - `mode: manual`: 返回 `manual_handoff`（交接卡文本与待办指引）。
- **Headless Microkernel Architecture (无头微内核架构)**:
  - 状态机（FileLock 互斥锁）、六大字段校验器、FileScopeGuard 物理拦截、物理可行性门禁与 Git 审计构成不可变内核，绝不感知任何拓扑 `mode` 分支或厂商差异；出站网络请求完全下沉至可插拔扩展层。
- **Lease Timeout & Deadlock Reaper (租约超时与僵尸任务回收器)**:
  - 在 IDE 子代理调度并发域中，为 `In Progress` 检出引入租约生命周期（`lease_expires_at`），防止子代理意外崩溃后全局互斥锁永久死锁。
- **Task Directory Physical Defense & Bypass Audit (任务目录物理防线与旁路拦截)**:
  - 封堵具备文件编辑权限的内生子代理直接通过 `write_to_file` 绕过 `dev_tasks_propose` 篡改任务的漏洞，确保所有任务创建与流转强制通过内核门禁。

