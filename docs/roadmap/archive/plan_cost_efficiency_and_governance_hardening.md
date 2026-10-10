# Quench 治理用量精简与防御加固路线图 (Resource Efficiency & Governance Hardening Roadmap)

> **路线图状态**: 📋 方案推演与架构蓝图编制 (Architecture Blueprint)  
> **起始时间**: 2026-10-01  
> **权威审查来源**: Reviewer 架构红队审计报告 [`20261001_014_consult_roadmap_opt.log`](../../.agents/logs/reviewer/20261001_014_consult_roadmap_opt.log)  
> **关联 SSOT**: [`docs/architecture/README.md`](../architecture/README.md), [`dev_tasks_mcp_specification.md`](../../dev_tasks_mcp_specification.md), [`quench_stack.yaml`](../../.agents/quench_stack.yaml)  
> **核心原则**: **先保验证（DoD）与授权（Role）正确，再谈吞吐（Fast-Track）；先建度量（Baselines）与预算精确性（Tokens），再谈压缩。**

---

## 0. 架构裁决与红线清单 (Executive Audit & Critical Vulnerabilities)

在审查针对 Token 消耗、网络延迟与模型计费的五项精简策略时，Strategic Reviewer 明确指出：**五项策略方向正确，但若按粗粒度直觉落地，将以「节省 Token」为名，在三处重新击穿 Quench 赖以立足的物理墙：DoD 伪绿屏（INV-7）、工具暴露≠授权（INV-2 旁路）、微任务快速通道 = 写授权旁路（INV-1/INV-7）。**

必须在架构设计层面设立五条绝对红线（C-1 ~ C-5）：

### 0.1 审查发现的五大 Critical 缺陷

| 编号 | 缺陷分类 | 触发场景与机制 | 破坏的不变量 | 架构修正要求 |
| :---: | :--- | :--- | :---: | :--- |
| **C-1** | **DoD 伪绿屏** | 单测命令输出经管道截断（如 `pytest ... \| tail -n 5`），无 `pipefail` 时返回 `tail` 的 `rc=0`；或测试因重命名导致 pytest 退出码为 `5`（`no tests ran`），文本抓取判定为成功。 | **INV-7** (物理门禁) | 判定权威必须为 `subprocess.returncode == 0` 且 `collected > 0`，**人类可读简报仅作为派生展示层，严禁参与逻辑判定**。 |
| **C-2** | **合规伪绿** | 缺乏 API 密钥或运行环境导致 fixture 调用 `skip()`，单行简报显示 `42 passed` 判绿，掩盖了 12 条核心跨进程租约/文件锁断言被跳过。 | **INV-1**, **INV-9** | 任何未在任务单 `【防御与边缘校验】` 显式申报的 `skip` / `xfail`，**一律判定为非绿（阻断 Complete）**。 |
| **C-3** | **客户端礼貌性授权** | 动态裁剪 MCP `tools/list` 仅为展示层过滤。Headless 外部执行器（Codex CLI、Claude Code）可直接绕过列表下发 `tools/call` 执行越权状态流转。 | **INV-2** (状态机硬管控) | **列表可见性 ≠ 物理授权**。必须在服务端 dispatch 层基于 `(session_id, epoch)` 强制实施物理能力鉴权，未授权调用抛出类型化异常。 |
| **C-4** | **极速通道写穿透** | 按「单文件」或文件数量豁免任务流程。`server.py` 或 `state_machine.py` 的单行修改足以瘫痪全局并发锁；且路径 glob 易被符号链接与相对路径穿越绕过。 | **INV-1**, **INV-7** | 快速通道必须按**路径风险等级**（`managed_paths` 核心目录一律强制封锁），而非文件数量授权；必须经过 `path_guard` 物理规范化。 |
| **C-5** | **非交互宿主决策死锁** | Tier 3 交互弹窗（`ask` modal）在非交互式 CLI / 自动化管道下要么阻塞超时，要么静默退化为默认放行。 | 门禁穿透 | 非交互宿主下 `ask` 决策必须**严格 fail-closed（默认 deny）**，严禁安全降级。 |

---

## 1. 演进原则与拓扑全景 (Phased Evolution Topology)

为防止优化目标函数单边化（为了省 Token 而牺牲架构审查质量），工程演进必须严格遵循以下排序：
$$\text{Measurement (度量)} \to \text{Verification (验证)} \to \text{Authorization (授权)} \to \text{Accounting (计量)} \to \text{Compression (压缩)} \to \text{Isolation (隔离)} \to \text{Throughput (吞吐)}$$

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Epic 0: 评测语料与成本/质量双指标基线门禁 (Frozen Corpus & Metric Guard)    │
│         • 确立「无度量不得优化」硬门禁；锁定回归基准语料                    │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ Epic A: 结构化 DoD 权威契约          │ Epic B: 服务端角色物理能力矩阵       │
│ • exit_code == 0 & collected > 0     │ • tools/call dispatch 层强制鉴权     │
│ • 未申报 skip/xfail 强制拒收         │ • 状态机转移完整性 (保留 escalate)   │
│ • 全量日志物理留证 + 会话帧预算简报  │ • 客户端协商与全量列表安全回退       │
├──────────────────────────────────────┴──────────────────────────────────────┤
│ Epic C: 适配器级 Token 预算与真实截断遥测 (对齐模型真实 Tokenizer，保底安全系数)│
├─────────────────────────────────────────────────────────────────────────────┤
│ Epic D: 确定性符号切片 (Repo-Map 增量叠加 + completeness: heuristic)        │
├─────────────────────────────────────────────────────────────────────────────┤
│ Epic E: 异步审查与裁决通道加固 (Session/Epoch 绑定，reject-not-truncate)    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Epic F: 风险分级极速通道 (依赖 Phase 2 Epoch Fencing，核心目录绝对禁止旁路) │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心 Epics 规范与契约设计 (Epics 0 ~ F)

### Epic 0: 评测语料与成本/质量双指标基线门禁 (Measurement Gate)

* **目标**：杜绝为省 Token 而降低 Reviewer 缺陷拦截率的“伪优化”。
* **契约与指标**：
  1. **构建冻结语料库**：收录包含真实并发死锁、路径穿越、静默截断在内的 20 组微型基准任务草案与 Diff。
  2. **双指标回归门禁**：
     * **成本指标**：单任务生命周期平均消耗 Token 量（Prompt + Egress）、总调用延迟；
     * **质量指标**：客观缺陷检出率（Recall Rate）、伪绿放行率（False-Pass Rate）。
  3. **验收门禁**：后续任何压缩 Epic 合并前，**质量指标不得发生统计学显著下降**。

---

### Epic A: 结构化 DoD 权威契约与单行证据链 (DoD Verification Protocol)

* **目标**：消除控制台数千字符输出回灌，杜绝 C-1/C-2 伪绿屏。
* **核心模块**：`plugins/quench-dev-tasks/server/dod_result.py`
* **类型契约**：

```python
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Collection, Mapping, Sequence

class DodOutcome(StrEnum):
    PASS     = "pass"
    FAIL     = "fail"
    ERROR    = "error"       # 收集/用法级故障 (rc in {2,3,4})
    NO_TESTS = "no_tests"    # rc == 5 或 collected == 0
    DEFERRED = "deferred"    # 依赖缺失未执行

@dataclass(frozen=True)
class DodResult:
    outcome: DodOutcome
    exit_code: int
    command: tuple[str, ...]
    collected: int
    passed: int
    failed: int
    errors: int
    skipped: tuple[str, ...]
    xfailed: tuple[str, ...]
    xpassed: tuple[str, ...]
    undeclared_skips: tuple[str, ...]
    duration_s: float
    summary_line: str           # ⚠️ 仅展示，严禁参与判定
    raw_tail: str               # 失败时按异常调用帧预算裁剪
    log_path: str               # 全量证据落盘路径
    log_sha256: str
    truncated: bool

def classify_dod_result(
    *,
    exit_code: int,
    report: Mapping[str, Any],
    command: Sequence[str],
    allowed_skips: Collection[str] = (),
) -> DodResult: ...
```

* **判定权威矩阵**：
  * **绿灯准入（唯一条件）**：`exit_code == 0` 且 `collected > 0` 且 `failed == 0` 且 `errors == 0` 且 `undeclared_skips == ()`；
  * **非绿阻断**：`exit_code == 5` 或 `collected == 0` 判定为 `NO_TESTS`（阻断 Complete）；未申报的 skip 判定为 `FAIL`。
* **工程执行要求**：
  * 全量日志写入 `.agents/logs/dod/<task_id>-<epoch>.log` 物理留证；
  * 主会话仅回传单行简报与 `log_path`；
  * 失败堆栈按**异常调用帧预算**裁剪（保留根因 `__cause__` 与核心错误类），严禁无脑字符截断导致根因丢失。

---

### Epic B: 服务端角色物理能力矩阵与 Dispatch 鉴权 (Role-Based Tool Authorization)

* **目标**：削减 Schema 底噪（由 16+ 工具降至 4~5 个），同时物理封堵 C-3 越权。
* **架构契约**：
  1. **服务端物理鉴权（Dispatch Guard）**：
     * 在 FastMCP 的 `tools/call` 分发入口拦截。外部请求即使知晓工具名称，若当前绑定会话的角色未被授权，直接拒绝：
       ```json
       {"error": "UnauthorizedCapability", "message": "Role 'runner' cannot invoke 'dev_tasks_confirm'"}
       ```
  2. **状态流转完整性闭环（Transition Completeness）**：
     * Runner 角色表面必须包含：`dev_tasks_status`, `dev_tasks_checkout`, `dev_tasks_complete`, `dev_tasks_escalate`；
     * **保留合法求助通路**：严禁隐藏 `dev_tasks_escalate`，防止模型受挫后就地角色扮演（防范 H-1）。
  3. **客户端协商降级**：
     * 若客户端握手声明不支持 `notifications/tools/list_changed`，服务端主动降级为回传**全量静态列表**，但 dispatch 层的鉴权逻辑依然在服务端严格执行。

---

### Epic C: 适配器级真实 Token 计量与截断显式遥测 (Adapter-Aligned Token Budget)

* **目标**：解决中英混排 CJK 字符膨胀（40k 字符导致 50k+ tokens 静默截断）与 H-3 分词器失配。
* **架构规范**：
  1. **适配器对齐**：分词计算下沉至 `ReviewerClient` 适配器（`deepseek` 适配器对齐 DeepSeek 分词算法，严禁通用 `tiktoken` 粗暴代换）。
  2. **安全系数降级**：若运行环境缺乏原生 Tokenizer 库，估算值必须乘以 **安全系数 1.25** 并标记 `token_count_method="heuristic"`。
  3. **模型终止原因（Stop Reason）权威校验**：
     * 若 Provider 响应中的 `finish_reason == "length"`，**直接判定为截断失效**；
     * 该裁决必须标记为 `incomplete: true`，**绝对禁止**写入 `verdicts.jsonl` 作为批准证据，任务禁止完成。

---

### Epic D: 确定性符号子图切片 (Repo-Map Context Injection)

* **目标**：替代粗暴的 200 行行切片，将 Reviewer 上下文有效载荷压缩 60%~75%。
* **安全约束**：
  1. **静态解析，零代码执行**：基于纯 Python `ast` 或轻量解析，**绝对禁止 `import` 目标模块**（防止触发模块级副作用），零 `os.stat`。
  2. **增量叠加而非替换**：符号子图仅填充白名单文件的外围引用关系，必须显式附加标记 `completeness: heuristic`。
  3. **动态派发复核**：检测到涉及 `getattr`、装饰器派发或注册表架构（如 `PROVIDER_PRESETS`）时，自动触发调用点复核提示，避免虚假完整性偏见（防范 H-4）。

---

### Epic E: 裁决通道加固与原子防交错 (Verdict Channel Hardening)

* **目标**：解耦主会话长文本，阻断跨会话裁决串味与写入破碎。
* **安全契约**：
  1. **记录关联性绑定**：每条裁决记录必须携带 `(job_id, session_id, epoch)` 三元组；主会话只能通过专用 MCP 工具消费匹配当前会话的裁决。
  2. **Reject-not-Truncate 策略**：裁决记录超过单条预算（16KB）时，必须**直接拒绝并记录错误**，严禁静默截断尾部关键风险清单。
  3. **原子提交顺序**：ReviewerJobSupervisor 必须先将裁决刷入 `verdicts.jsonl`，再将作业状态跃迁为 `COMPLETED`，防止中间崩溃产生无裁决的假终态。

---

### Epic F: 风险分级极速通道 (Risk-Graded Fast-Track)

* **目标**：提供安全合规的微修旁路，消除小任务走 8 步状态机的过度开销。
* **前置依赖**：**硬性依赖 Epic B（服务端授权）与 Phase 2（Epoch Fencing）**。
* **安全红线**：
  1. **按路径风险等级授权**：`managed_paths`（如 `server/**`, `rules/**`）**绝对不可**被任何极速通道绕过；快速通道仅对已在 `unmanaged_paths` 声明的非核心资产（`docs/**`, `*.md`）或样式白名单开放。
  2. **Epoch 自动失效**：任何会话旁路（`dev_tasks_set_bypass`）的生命周期与当前租约 `epoch` 强绑定，一旦工作区检出新任务或切出新 Epoch，**旧旁路立即作废**（防范 H-6）。
  3. **非交互环境 Fail-Closed**：非交互 CLI 运行时，若未命中预设白名单，一律拒绝，严禁自动通过。

---

## 3. 反模式清单 (Anti-Patterns to Forbid)

在后续实施与代码审查中，以下行为被列为**严重违规并直接拒绝**：

- ❌ **管道截断丢失退出码**：使用 `pytest ... | tail` 而未声明 `set -o pipefail`；
- ❌ **以文件数量定义微任务**：允许“只改 1 个文件”免除单测或审核（单文件可摧毁全局锁）；
- ❌ **仅做 UI 视图裁剪**：在 MCP 客户端隐藏工具，但服务端接收 `tools/call` 时不校验权限；
- ❌ **单向追求低 Token 剥离断言**：通过减少测试用例数量或跳过基线回归来“节约”执行时间；
- ❌ **静默截断失败堆栈**：截断堆栈时丢弃异常的根因（`__cause__`），导致错误归因；
- ❌ **主会话私自读取日志文件**：绕过 MCP 协议直接读取未受管日志并解释给用户。

---

## 4. 实施里程碑映射与跟踪

| 里程碑 | 包含 Epics | 核心交付物 | 预计 Token 降幅 |
|:---:|:---|:---|:---:|
| **M1: 验证与基线** | Epic 0, Epic A | 评测语料集、`dod_result.py` 结构化退出码与简报 | **-25% ~ -35%** (会话内日志噪点清零) |
| **M2: 授权与预算** | Epic B, Epic C | 服务端 dispatch 鉴权、DeepSeek/Tokenizer 精确计量 | **-15% ~ -25%** (Schema 与无谓截断重试消除) |
| **M3: 深度压缩** | Epic D, Epic E | AST Repo-Map 符号切片、裁决原子通道 | **-30% ~ -50%** (Reviewer 输入切片大幅缩减) |
| **M4: 极速分流** | Epic F | Epoch 绑定的安全旁路与微任务极速流水线 | **轻量任务 -70%** (无状态机空转) |
