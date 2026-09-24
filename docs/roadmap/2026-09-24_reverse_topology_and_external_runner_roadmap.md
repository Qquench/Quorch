# Reverse-Topology & External-Runner Roadmap
## 逆向拓扑与外部执行器接入落地路线图

> **文档定位**：非规范性演进规划文档 (Non-Normative Planning Artifact)  
> **文档路径**：`docs/roadmap/2026-09-24_reverse_topology_and_external_runner_roadmap.md`  
> **发布日期**：2026-09-24  
> **当前状态**：Draft（架构红队裁决与推演草案）  
> **关联 SSOT**：[`docs/architecture/`](../architecture/README.md), [`dev_tasks_mcp_specification.md`](../../dev_tasks_mcp_specification.md), [`docs/ci_incident_tracker_and_compatibility_guide.md`](../ci_incident_tracker_and_compatibility_guide.md)  
> **权威性声明**：本文档仅供路线规划与方案推演。若本文档与 `docs/architecture/` 或 `dev_tasks_mcp_specification.md` 产生冲突，一律以后两者（SSOT）为准。

---

## 0. 核心结论与概念辨析摘要 (TL;DR)

针对用户关于“完全不需要 harness、在 Codex 环境里用外部 API 做执行器、Codex 内置高价模型被 MCP 调用作为 Reviewer”的设想，经 Reviewer 深度红队推演与架构诊断，裁定如下：

### 0.1 概念严格化辨析表

| 设想命题 | 架构裁定 | 事实依据与技术机理 |
| :--- | :---: | :--- |
| **「完全不需要 harness」** | ❌ **表述失真** | **Quench 绝不需要在仓内自研并内置一套庞大的 Agentic 执行框架**（轻量中枢非目标）。但**执行器侧必须寄生在一个现有的 Agent 客户端/harness 进程之上**（如 Codex CLI、Claude Code、Aider 等）。纯文本 API（如 DeepSeek `/chat/completions`）本身只有 token 推理能力，无本地文件读写、无终端执行、无工具调度循环，无法单凭 API 自身修改代码或跑测试。 |
| **「Codex 内置高价模型被 MCP 反向调用作为 Reviewer」** | ❌ **物理不可行**<br>*(自相矛盾)* | 1. **单会话单模型约束**：在单一客户端会话中，若会话配置了便宜模型作为 Runner，MCP Sampling 请求只会解析到当前会话的便宜模型（`modelPreferences` 仅为建议性 hint，客户端通常忽略）；<br>2. **配额与认证物理隔离**：Codex 内置的高价模型属于**客户端专属订阅额度（Subscription Quota）**，其认证凭据封装在客户端二进制内，MCP 作为一个 stdio 子进程，既没有凭据，在协议和技术上也无法跨越沙箱“借用”订阅额度；<br>3. **死锁风险**：多数客户端不支持反向 Sampling，且在处理正在进行的工具调用时极易发生 stdio 单管 JSON-RPC 嵌套死锁。 |
| **「真实可行的极简替代拓扑」** | ✅ **非对称双宿主**<br>*(Asymmetric Dual-Host)* | **执行宿主 (Runner)**：配置了外部 API 的本地客户端（如 Codex CLI / Aider），挂载 Quench MCP，负责读写与执行；<br>**审查宿主 (Reviewer)**：独立会话/独立窗口中的旗舰模型（人工中转 Paradigm A 或 API Key 直连 Paradigm B）；<br>**同步介质**：二者以**文件系统与 Git**（任务单 Markdown、Handoff Card、`verdicts.jsonl`）为非对称松耦合契约面，严禁依赖实时反向 RPC。 |

---

## 1. 宿主能力矩阵与 Phase 0 探针原则

在没有实际测试探针验证之前，**严禁凭文档假设或幻想判定某一客户端的功能可用性**。所有客户端适配必须以可复现的运行时探针为准。

### 1.1 客户端能力探针矩阵 (Capability Matrix)

| 宿主客户端 (Client) | MCP 工具调用 | 钩子拦截 (PreToolUse) | 基础端点覆盖 (base_url override) | MCP Sampling (`sampling/*`) | 拓扑可行性评级 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Antigravity (IDE)** | 原生完整支持 | 原生支持 (`hooks.json`) | 需插件适配或外部代理 | 待探针实测 | ⭐⭐⭐⭐⭐ (基准环境) |
| **Codex CLI** | 支持 stdio MCP | ❌ 无 PreToolUse 钩子 | 支持 (`model_providers`) | 待探针实测 (极可能不支持) | ⭐⭐⭐ (需 B1/B3 下沉) |
| **Claude Code (CLI)** | 支持 stdio MCP | ❌ 无 PreToolUse 钩子 | 需第三方代理网关 | 待探针实测 | ⭐⭐⭐ (需 B1 下沉) |
| **Aider** | ❌ 原生无 MCP | ❌ 无 PreToolUse 钩子 | 原生原生支持 `--openai-api-base` | ❌ 不支持 | ⭐⭐ (需 MCP Bridge) |
| **Cursor / Windsurf** | 支持 stdio MCP | 规则级拦截 (非物理) | 支持模型自定义 | ❌ 明确不支持 | ⭐⭐⭐ (需 B1 状态跃迁对账) |

> 📌 **核心原则**：只要宿主缺少 `PreToolUse` 物理钩子，原本依赖 IDE 钩子的一级文件防线（Tier-1）在外部客户端侧**物理清空**。安全防线必须全面下沉至 Tier-2（状态机检查）与 Tier-3（Git 物理守卫）。

---

## 2. 目标拓扑：非对称双宿主架构 (Asymmetric Dual-Host)

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Reviewer 审查宿主 (旗舰模型)                     │
│  - 独立 Codex 会话 (旗舰模型) / 独立 Web UI / 外部 Frontier API       │
│  - 职责：阅读上下文切片，输出批判性裁决、架构推演、任务单拆分          │
│  - 访问权限：纯只读 (Read-Only)，严禁文件写入与代码变更                │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Handoff Card (人桥中转)
                                    │ 或 verdicts.jsonl / task.md
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      Quench 文件系统与 Git 治理中枢                     │
│  - .agents/.quorch/manifest.json (CAS 锁与单活控制)                   │
│  - docs/dev_tasks/*.md (六大字段规范，唯一状态真源)                    │
│  - scripts/git_pre_commit_guard.py (物理提交拦截)                      │
└───────────────────────────────────▲────────────────────────────────────┘
                                    │
                                    │ stdio JSON-RPC (11 个原子工具)
                                    │
┌───────────────────────────────────┴────────────────────────────────────┐
│                        Runner 执行宿主 (高性价比模型)                   │
│  - Codex CLI / Claude Code / Aider 挂载 quench-dev-tasks MCP 服务       │
│  - 模型引擎：DeepSeek / 本地 Ollama 等高性价比推理模型                  │
│  - 职责：领单 (`checkout`)、实施代码 (`whitelist`)、跑测并交付 (`complete`)│
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 关键技术壁垒攻坚方案 (B1 / B3 / B4 / B7)

在反向与外部执行器拓扑下，系统必须攻克以下四大核心工程断点：

### 3.1 B1：白名单管控物理下沉 (Hook-free Scope Enforcement)
- **缺陷根因**：`.agents/hooks.json` 仅在 Antigravity 内由 IDE 在派发工具前拦截。外部 CLI 不调用此钩子，Runner 可随意写越界文件。
- **下沉解法（三段式物理防线）**：
  1. **检出基线快照 (Baseline Snapshot)**：在 `dev_tasks_checkout` 时，记录当前工作区的 Git HEAD 与待管文件变更哈希；
  2. **状态跃迁前工作树对账 (Pre-transition Reconciliation)**：在 `dev_tasks_complete` 与 `dev_tasks_escalate` 时，服务器主动执行 `git diff --name-only <baseline>`。若变更文件集不是任务单 `【涉及文件】` 的严格子集，**直接熔断状态跃迁并报错拒绝**，给出需恢复或补充任务单的具体指引；
  3. **提交级拦截 (Commit Guard)**：通过 `scripts/git_pre_commit_guard.py` 阻止任何越界文件的 Git commit。

### 3.2 B3：租约心跳与外部活性判定 (External Lease Heartbeat & Liveness)
- **缺陷根因**：外部 CLI 在执行耗时较长的大规模文件重构或测试运行期间，不会调用 MCP 工具，导致 `manifest_lease.py` 判定租约过期并被后台 Reaper 误回收，引发并发写冲突。
- **解法**：
  1. **隐式心跳刷新**：持有活跃任务会话的任意 MCP 调用自动顺延租约 TTL；
  2. **轻量显式心跳**：约定 `dev_tasks_status` 在由持有人会话调用时隐式充当低开销心跳探针；
  3. **基于文件系统 mtime 的防杀保护**：Reaper 在回收租约前，检查工作区 `【涉及文件】` 的最后修改时间。若 mtime 在活跃窗口内，判定为“沉浸式编码中”，禁止强行收回。

### 3.3 B4：双进程并发 CAS 锁 (Dual-Process CAS & Cross-Client Concurrency)
- **缺陷根因**：Reviewer 宿主与 Runner 宿主可能各自以独立的 stdio 启动一个 `server.py` 进程，形成两个 MCP 守护进程并发读写同一个 `manifest.json`。
- **解法**：
  1. **临界区内重读 (Read-Under-Lock CAS)**：在跨进程 `filelock` 保护的临界区内，必须重新读取磁盘上的最新清单与版本号（generation），完成比较并交换（Compare-And-Swap），禁止信任任何模块级进程内存缓存；
  2. **配置单向不可变**：`project_config` 保持每进程单次加载与只读视图，可变任务状态完全委托给带锁的清单存储。

### 3.4 B7：能力令牌与审查凭证防伪 (Capability Tokens & Verdict Provenance)
- **缺陷根因**：外部拓扑中若由 Runner 代理输入 Reviewer 结论，容易诱发 Runner 伪造“审查通过”以绕过阻断（触碰 INV-3 反向角色扮演硬停）。
- **解法**：
  1. **令牌权限隔离**：通过环境变量或客户端配置传入 `QUENCH_CAPABILITY_ROLE=runner|reviewer`，限制 Reviewer 宿主只能调用只读端点；
  2. **简报哈希校验 (Card-Hash Binding)**：Reviewer 咨询生成的 Handoff Card 计算 SHA-256 签名，回填裁决时必须携带该签名字段，服务器校验简报与结论的一致性并在 `verdicts.jsonl` 中标记 `provenance: "human_attested"` 或 `provenance: "external_engine"`。

---

## 4. 阶段演进规划 (Phases 0 ~ 5)

```mermaid
flowchart LR
    P0[Phase 0: 客户端探针与冻结] --> P1[Phase 1: B1 白名单物理下沉]
    P1 --> P2[Phase 2: B3 租约心跳与防杀]
    P2 --> P3[Phase 3: B4 双进程 CAS 锁]
    P3 --> P4[Phase 4: B7 令牌与取证防伪]
    P4 --> P5[Phase 5: 外部客户端配置包落地]
```

### Phase 0：可行性探针与能力边界冻结 (Capability Probe & Freeze)
- **目标**：以独立测探脚本实测 Codex CLI 与目标客户端的 stdio 行为与 sampling 真实支持度，确立物理边界。
- **核心交付物**：
  - `plugins/quench-dev-tasks/scripts/probe_client_capabilities.py`：独立能力探针
  - `docs/ci_incident_tracker_and_compatibility_guide.md`：记录实测数据
- **退出条件与熔断开关 (Gate D0)**：
  - 若实测证明客户端不支持 sampling，**永久终止** MCP 反向调用宿主私有模型的幻想分支，将路线锁定为非对称双宿主 (T-A/T-B)。

### Phase 1：B1 白名单物理下沉与工作树对账 (Hook-free Scope Reconciliation)
- **目标**：彻底消除对 IDE 专有 `PreToolUse` 钩子的单一依赖，保证任何外部 CLI 都在硬物理管控之下。
- **核心交付物**：
  - `plugins/quench-dev-tasks/server/manifest.py`：扩展 `reconcile_workspace_against_whitelist`
  - `plugins/quench-dev-tasks/server/state_machine.py`：在 `complete` / `escalate` 增加对账熔断拦截
- **验收单测**：`tests/test_external_runner_scope_reconciliation.py`

### Phase 2：B3 租约心跳与长耗时防杀 (Lease Heartbeat & Liveness)
- **目标**：保障外部 Runner 长期编码期间租约稳定，消除误回收死锁与并发写入冲突。
- **核心交付物**：
  - `plugins/quench-dev-tasks/server/manifest_lease.py`：心跳续约与工作区 mtime 保护
  - `plugins/quench-dev-tasks/server/reaper.py`：防杀边界检查
- **验收单测**：`tests/test_lease_heartbeat_external.py`

### Phase 3：B4 双进程并发 CAS 与清单存储加固 (Dual-Process CAS Lock)
- **目标**：支持 Reviewer 宿主与 Runner 宿主同时各自挂载独立的 MCP 服务进程并安全并发访问。
- **核心交付物**：
  - `plugins/quench-dev-tasks/server/manifest.py`：严格的 Read-Under-Lock CAS 实现
- **验收单测**：`tests/test_dual_process_cas.py` (多子进程并发压测)

### Phase 4：B7 能力令牌与审查结论凭证取证 (Capability Tokens & Verdict Provenance)
- **目标**：强化反向角色扮演防御，确保外部 Reviewer 结论的真实可溯源性。
- **核心交付物**：
  - `plugins/quench-dev-tasks/server/consultation.py`：简报 SHA-256 签名签发与回填校验
  - `plugins/quench-dev-tasks/server/observability_policy.py`：审计日志落盘携带来源标记
- **验收单测**：`tests/test_verdict_provenance.py`

### Phase 5：主流外部执行器配置模板与接入指南 (External Runner Onboarding Kit)
- **目标**：为 Codex CLI、Claude Code、Aider 提供开箱即用的配置模板与操作手册。
- **核心交付物**：
  - `docs/external_runner_onboarding.md`
  - 配置样例：`examples/codex_config.toml`, `examples/claude_code_config.json`

---

## 5. 外部执行器典型配置范例 (参考实现)

### 5.1 Codex CLI 接入配置示例 (`~/.codex/config.toml`)

```toml
# 1. 将执行模型指定为外部高性价比推理端点
model = "deepseek-chat"
model_provider = "deepseek"

[model_providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com/v1"
env_key = "DEEPSEEK_API_KEY"
wire_api = "chat"

# 2. 挂载 Quench DevTasks MCP 服务
[mcp_servers.quench-dev-tasks]
command = "python"
args = ["<workspace-root>/plugins/quench-dev-tasks/server/server.py"]
env = { QUENCH_CAPABILITY_ROLE = "runner" }
```

### 5.2 Aider 启动命令示例

```bash
aider \
  --openai-api-base https://api.deepseek.com/v1 \
  --openai-api-key $DEEPSEEK_API_KEY \
  --model deepseek/deepseek-chat
```

---

## 6. 严正非目标 (Non-Goals)

为了防止项目定位漂移和代码库过度膨胀，以下事项**明确列为本项目的永久非目标**：

1. **绝不在仓内自研重型 Agentic Harness**：不编写代码编辑循环、不实现命令行交互 REPL、不维护复杂的上下文多轮自动截断。执行循环必须交给第三方客户端；
2. **绝不做无法穿透的私有模型反向 RPC 逆向工程**：不尝试通过内存挂钩、逆向工程私有 API 等手段偷调宿主订阅额度；
3. **绝不在服务端代行无限制的 Shell 命令执行**：`dev_tasks_complete` 仅负责核对测试输出文本，绝不作为远端 RCE 引擎执行任意未经沙箱校验的代码；
4. **绝不破坏 11 个 MCP 核心工具的接口纯净度**：除非通过正式架构评审与全量单测，严禁为单一客户端特异化新增非标工具。

---

## 7. 红队风险登记表 (Risk Registry)

| 风险编号 | 严重度 | 风险场景与触发条件 | 架构影响与后果 | 对应防御阶段 |
| :--- | :---: | :--- | :--- | :---: |
| **RSK-CR-01** | **CRITICAL** | 外部 CLI 无 `PreToolUse` 钩子，模型擅自修改未报备代码 | 白名单管控物理失效，随意越界污染 | **Phase 1** (B1 工作树对账) |
| **RSK-CR-02** | **CRITICAL** | Runner 模型自行填写伪造的 Reviewer 审查结论 | INV-3 纪律失守，审查形同虚设 | **Phase 4** (B7 简报签名校验) |
| **RSK-HI-01** | **HIGH** | 试图通过 MCP Sampling 反向调用宿主，客户端阻塞死锁 | stdio 单管调用挂起，会话超时熔断 | **Phase 0** (探针判定与熔断) |
| **RSK-HI-02** | **HIGH** | 外部 Runner 编码时间长无 MCP 调用，租约被误回收 | 任务状态被置空，引发并发踩踏 | **Phase 2** (B3 租约防杀) |
| **RSK-HI-03** | **HIGH** | 两个宿主进程并发写清单，脏读覆盖 | 任务状态回滚或并发单冲突 | **Phase 3** (B4 锁内重读 CAS) |
| **RSK-MED-01** | **MEDIUM** | Windows 与 Linux/WSL 路径大小写或斜杠方言不一致 | 工作树对账误判为越界修改 | **Phase 1** (路径规范化对齐) |

---

## 8. 不变量在新拓扑下的重述 (Invariant Mapping)

| 核心不变量 | 原始约束 | 外部执行器 / 双宿主拓扑下的重述与落实 |
| :--- | :--- | :--- |
| **INV-1** | 单核串行全局唯一 | **加固**：跨进程 `filelock` 确保即使用户在不同客户端窗口同时执行 checkout，也只有第一个能拿到锁。 |
| **INV-2** | 状态机纯 MCP 驱动 | **保持**：禁止人工手改 Markdown，任何客户端都必须通过 stdio MCP 工具发起跃迁。 |
| **INV-3** | 防角色扮演与审查只读 | **加固**：Reviewer 与 Runner 物理分离于两个独立进程/会话，物理上阻断单会话角色扮演。 |
| **INV-4** | Stdio 纯净度 | **保持**：任何非标日志一律写入独立 log 文件，stdout 100% 留给 JSON-RPC。 |
| **INV-5** | 厂商中立性 | **保持**：所有客户端接入仅依赖标准 OpenAI/Anthropic 兼容协议与配置注入，代码零厂商硬编码。 |
| **INV-6** | 审查过程只读 | **加固**：通过 B7 令牌在服务端层级禁用审查宿主的文件写入类工具。 |
| **INV-7** | 物理可行性门禁 | **保持**：草案晋升与检出前必须保证文件路径物理存在且 pytest dry-run 可运行。 |
| **INV-8** | 上下文预算上限 | **保持**：Handoff Card 与注入上下文严格钳制在 40,000 字符内，保障跨宿主传递低成本。 |
