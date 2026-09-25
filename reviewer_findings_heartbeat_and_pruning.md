# 🔴 Architectural Critique — Red-Team Findings

> Reviewed surfaces: `reviewer_engine.py` (AdaptiveHeartbeatSink / ProgressSink), `consultation.py` (heartbeat worker wiring), `reviewer_jobs.py` (poll contract, terminal field whitelist). Step 03 task documents are **not in the provided context** — see `NEED-FILES` for the two artifacts required to make Q2 a *final* verdict rather than a *provisional* one.

---

## 0. Executive Verdict (结论先行)

| 议题 | 裁决 | 严重度 |
|---|---|---|
| Q1.1 心跳频率 | 1Hz **不是 I/O 灾难，但冗余显著且事件盲**；应改**自适应阶梯 + token-delta 事件门控**，而非统一放宽到 3s/5s | Medium |
| Q1.2 前端回显 | 当前 `AdaptiveHeartbeatSink` 声称的"多通道分发"**是死代码**（`mcp_context`/`stderr` 从未被调用）。前台上报应走 **MCP `ctx.report_progress`（请求作用域）**；异步路径只能保持 pull。**严禁** stdout/ANSI/`/dev/tty` | **High（功能缺口）** |
| Q2.1/2.2 3.1 & 3.2 | **两任务的核心能力在代码中已基本落地**（`self_verification_warning`、`reviewer_identity`、`verdict`、`VerdictAuditSink`）。**建议不作为独立施工任务，降级为文档 + 回归断言，Step 03 聚焦 3.3** | — |
| Q2.3 治理闭环 | 取消本身**不破坏**防伪，因为防伪锚点是 **sole-egress 不变量 + 引擎产出字段**，不是任务单；**唯一硬约束**：必须保留一条"伪造 verdict 不可产出/可检出"的回归测试 | **High（条件性）** |
| Q2.4 权威方案 | **"审计优先 → 取消独立任务 → 残余缺口并入 3.3 + 测试"** | 见 §2.4 |

---

## 1. 问题一：心跳机制与前端回显

### F1.1 【High】"多通道分发"是死代码，前台上报通道根本不存在

**证据**：`AdaptiveHeartbeatSink.__init__` 存了 `self.mcp_context` 与 `self.stderr`，但 `on_heartbeat()` 与 `apulse()` 的 body **只调用 `self.file_emit(...)`**；`on_chunk` / `on_finish` 均为 `pass`。类的 docstring 宣称 *"多通道能力分发 + FILE 常驻兜底"*，实际只有 FILE 单通道。

```python
async def apulse(self, *, tokens_so_far, elapsed_s, step="thinking"):
    ...
    try:
        self.file_emit(file_msg)      # ← 唯一出口；mcp_context / stderr 从未被引用
    except Exception:
        pass
```

**触发场景**：任何期望"前端看到点什么"的路径 → 什么也看不到。
**影响**：这正是 Q1.2 想解决的问题的根因——**回显能力不是"体验弱"，而是"根本没接线"**。这是客观缺陷，不是偏好。

### F1.2 【Medium】有效频率 ≈ 1Hz，双重节流且**事件盲**

**证据**：worker 侧 `asyncio.sleep(1.0)`，sink 侧再节流 `interval_s + jitter`（≈1.0–1.015s）。两处都是**纯时钟驱动**，与 token 增量无关。

- **磁盘**：受 `MAX_LOG_FILE_BYTES(2MB)` × `MAX_LOG_FILES_QUOTA(20)` 约束 → 稳态风险 **Low**。
- **上下文污染**：只有当 `dev_reviewer_poll(raw_text=True)` 的输出被喂回模型时才发生；而 `raw_text` 属 operator-only（`TERMINAL_RESULT_ALLOWED_FIELDS` 的"反思维链"设计本就是为了让模型路径**不**读原文）→ 稳态 **Low**，但任何"轮询即回显"的自动化把它抬到 **Medium**。
- **真正的缺陷是冗余**：模型卡顿 30s 时会产出 ~30 行**完全相同**的 token 计数 → 纯噪声。

### F1.3 【Medium】心跳文件 I/O 跑在事件循环线程上

**证据**：`apulse` 是 `async def`，但在释放 `threading.Lock` 后**同步**调用 `self.file_emit(msg)`（= `RotatingFileSink.write_chunk_text`）。该调用仍在 event-loop 线程上执行，可能触发 flush/fsync。
**触发**：网络盘 / AV 实时扫描 / 慢盘 → 流式接收期间 event-loop 抖动。
**缓解**：`anyio.to_thread.run_sync` 卸载，或让 `file_emit` 严格为内存 append（flush 交给既有 `flush_interval_s=0.2`）。

### F1.4 【Low / Informational】同步心跳路径疑似死路

`consultation.py` 只用 `apulse`；`on_heartbeat` 同步口无调用点。若确实无调用者，`on_heartbeat` 应标注或移除，避免双路径维护。

---

### 1.1 频率裁决：自适应阶梯 > 统一放宽

**否决"统一放宽到 3s/5s"**：最差的静默点是**启动后的头几秒**（感知延迟最敏感处），统一放宽会放大它。
**推荐**：`[0.5s(首帧), 1s, 1s, 2s, 2s, 3s, 5s(cap)]` 阶梯，并叠加**事件门控**：

```
emit = (token_delta >= threshold) OR (now - last_emit >= keepalive_floor)
```

即"**有进展即报 + 无进展保活**"。保留 `MIN=500ms` 与 jitter（并发 job 防雷群）。

---

### 1.2 前端回显裁决：唯一合法通道是 MCP 通知

**约束推导**：stdio 传输下 stdout 承载 JSON-RPC 帧 → **不可写裸文本**。因此：

| 通道 | 是否合规 | 说明 |
|---|---|---|
| `ctx.report_progress` / `ctx.info`（FastMCP） | ✅ **唯一推荐** | 走 JSON-RPC，**不**污染 stdout；跨平台；IDE 原生渲染 |
| stderr | ⚠️ 兜底 | 不破协议，但多数 IDE 聊天 UI 不呈现 |
| stdout 裸文本 / ANSI | ❌ **禁止** | 破坏 JSON-RPC 帧 |
| 直写 `/dev/tty` / `CONOUT$` | ❌ **禁止** | 非跨平台，违反边界约束 |

**关键区分（这就是回答 Q1.2 的核心）**：

- **`dev_reviewer_consult`（阻塞、请求作用域）**：**可以且应该**推送 → 把死字段 `mcp_context` 接到节流后的 `ctx.report_progress`。这就是该字段被设计出来却没接线的本意。
- **异步 `submit/poll`**：**没有活着的请求可挂载** → 结构上无法 push → **必须保持 pull**。提升体验只能靠：(a) 非终态快照返回**稳定单行 `progress` 摘要**；(b) 文档给出**推荐轮询节奏**；(c) 明确 `raw_text` 不得进入模型上下文。

> **结论**：最佳工程路径 = **"请求作用域走 `report_progress`，异步作用域走 pull + 结构化 progress 摘要"** 的**双模态**设计；放弃"把文件日志当回显"的幻觉。

---## 2. 问题二：Step 03 削减 / 全盘取消评估

### 2.1 关键证据：3.1 / 3.2 的核心能力**已经在代码里**

| 任务 | 其"本质"对应的已存在实体 |
|---|---|
| 3.1 角色隔离 | `check_self_verification_warning`（`project_config`）+ 结果字段 `self_verification_warning` / `reviewer_identity` + 降级卡 |
| 3.2 裁决台账 | `observability_policy.VerdictAuditSink` / `make_verdict_sink` + `TERMINAL_RESULT_ALLOWED_FIELDS` 中的 `verdict` |
| 防伪锚点 | `IS_SOLE_PROVIDER_EGRESS`（唯一出网通道不变量）|

**这意味着：两个任务有很高概率是在"重新实现已存在的东西"**，与《拒绝过度设计》纪律直接冲突。

### 2.2 威胁模型（红队）

| ID | 威胁 | 现有防线 | 尚缺 |
|---|---|---|---|
| T1 | **自证伪造**：主模型凭空编造"Reviewer 裁决" | sole-egress + 引擎产出 `usage`/`reviewer_identity` + 降级卡 | 一条**可执行**的伪造检出回归测试 |
| T2 | **跨会话重放**：复用陈旧裁决 | 日志落盘 + 会话 ID | 机器可查询的时序校验（弱） |
| T3 | **事后篡改**：改日志/台账 | 无（纯文本日志无不可否认性）| 仅当威胁模型含"改文件对手"才需要 |
| T4 | **角色混淆**：把主模型输出当 Reviewer | `self_verification_warning` | —（已覆盖）|

**核心判断**：**防伪的物理锚点是"外部引擎是唯一 egress + 字段由引擎产出"，不是任务单本身。** 一个 `roles` 注册表**无法**增加主模型无法绕过的物理保证——模型总能吐文本；真正的不可伪造性来自"外部引擎产出了它"。

**决定性分歧点（T3）**：是否把"篡改磁盘文件"纳入威胁模型？
- 本地单人开发治理工具 → **不纳入** → 哈希链台账 = **过度设计**。
- 若纳入 → 才值得一个最小不可否认台账。

### 2.3 收益 / 代价矩阵

| 动作 | 收益 | 代价 | 裁决 |
|---|---|---|---|
| 全盘取消 3.1 | 任务面收敛；无新抽象 | 几乎无损（能力已存在）| ✅ **取消独立任务，降级文档** |
| 取消 / 极简 3.2 | 避免哈希链复杂度 | 损失"机器可查询 + 不可否认"历史（但日志 + `VerdictAuditSink` 已兜底）| ⚠️ **降为最小 MVP + 文档** |
| 只靠文档、零回归测试 | — | **治理闭环断裂**（T1 无物理检出）| ❌ **禁止** |

### 2.4 【权威裁决】Step 03 精简方案

1. **3.1 角色隔离 → 取消独立施工，降级为文档**。
   理由：物理强制不可由注册表提供；本质能力（自证告警 + 身份字段 + 降级卡）**已上线**。残余内容并入 3.3 的 SKILL.md/架构文档"角色与身份契约"一节。

2. **3.2 裁决台账 → 降为最小 MVP**（**先审计 `VerdictAuditSink` 现状**）：
   - 若 `VerdictAuditSink` 已满足"append-only 结构化裁决记录" → **取消独立施工**，仅补 schema 文档。
   - 若缺口真实存在 → **只补 append-only JSON 行**（复用现有 sink），**禁止**引入哈希链/DB（过度设计）。
   - `verdict` 字段已存在 → 不做二次定义，单一 SSOT。

3. **3.3 外部执行器接入规范与 SKILL.md → 唯一施工焦点**（保留）。

4. **【硬性前置条件 — 不可省】** Step 03 无论如何精简，**必须包含一条防伪回归断言**：验证"未真实调用引擎的伪造裁决"无法通过 `reviewer_identity`/日志关联校验（或在终态被标记 `self_verification_warning`/`degraded_reason`）。**这是治理闭环的命门；取消它可以，取消这条测试不可以。**

5. **执行顺序**：**审计优先（audit-first）** → 确认现有覆盖 → 再执行取消。禁止"先删任务再补测"。

---

<<<NEED-FILES>>>
plugins/quench-dev-tasks/server/observability_policy.py
plugins/quench-dev-tasks/server/project_config.py
<<<END>>>

> 附注：为对 Q2 给出**最终权威裁决**（而非 provisional），我需核对 `VerdictAuditSink` 的真实落盘语义（是否已是 append-only 台账），并确认 `check_self_verification_warning` 的覆盖边界。同时请将 **Step 03 的现行任务单文件**（`docs/dev_tasks/` 下含 3.1/3.2/3.3 者）表面化——`NEED-FILES` 无法用通配符，故此行请你手动指向。

---

<<<TASK_DRAFT>>>
### 任务 X.Y ⬜ 待确认 — Reviewer 心跳自适应降频与前台上报通道修复（Question 1）

#### 【涉及文件】
- `[MODIFY]` `plugins/quench-dev-tasks/server/reviewer_engine.py`
- `[MODIFY]` `plugins/quench-dev-tasks/server/consultation.py`
- `[ADD/MODIFY]` `plugins/quench-dev-tasks/tests/test_reviewer_heartbeat.py`

#### 【缺陷根因与修改目标】
1. **死通道**：`AdaptiveHeartbeatSink` 存入 `mcp_context` / `stderr` 却从不调用，docstring 宣称的"多通道分发"为死代码 (F1.1, High)。
2. **事件盲 1Hz 冗余**：纯时钟驱动、无 token-delta 门控，卡顿时产出重复行 (F1.2, Medium)。
3. **event-loop 阻塞**：`apulse` 在协程内同步执行 `file_emit`，慢盘下抖动流式 (F1.3, Medium)。
4. **目标**：请求作用域经 MCP `report_progress` 回显；异步作用域保持 pull 并返回稳定 progress 摘要；频率改自适应阶梯 + 事件门控。

#### 【目标签名与类型契约】
```
# reviewer_engine.py
class AdaptiveHeartbeatSink:
    def __init__(self, *, file_emit, progress_emit: Optional[Callable[[int,float],None]] = None,
                 interval_ms: int = 1000, clock=None) -> None: ...
    # 阶梯: first<=500ms, then [1,1,2,2,3,5]s cap
    # 门控: token_delta>=DELTA_MS 或 now-last>=keepalive_floor
    def _should_emit(self, tokens: int, now: float) -> bool: ...
# consultation.py: 请求作用域注入 progress_emit=部分应用 ctx.report_progress（节流后）
```

#### 【分步改造指引】
1. 将 `mcp_context`/`stderr` 替换为显式 `progress_emit` 回调；`apulse` 内改调用 `anyio.to_thread.run_sync(self.file_emit, msg)`（或保证 file_emit 纯内存 append）。
2. 实现 `_should_emit`：token 增量阈值 OR keepalive_floor（默认 5s），保留 `MIN=500ms` + jitter。
3. `consultation.py`：在**请求作用域**构造 sink 时注入 `ctx.report_progress` 适配器；异步 job 路径注入 `None`，改为在非终态快照输出单行 `progress` 摘要。
4. worker 的 `asyncio.sleep(1.0)` 改为由 sink 阶梯驱动（worker 仅作 ticker，节流权归 sink）。

#### 【防御与边缘校验】
- `progress_emit` 抛异常必须 `except: pass`，不得中断流式（现 `file_emit` 已如此，保持一致）。
- `MIN >= 500ms` 硬钳制；jitter 仅正向，防并发雷群。
- 严禁任何 stdout/ANSI/`/dev/tty` 写路径（新增断言扫描）。
- 异步路径不引入 push，维持 stdio 纯净。

#### 【DoD 验证命令】
```bash
cd plugins/quench-dev-tasks && python -m pytest tests/test_reviewer_heartbeat.py -q
# 断言：
#  a) 注入伪造 file_emit/progress_emit 可观测调用次数；t=0 首帧 <=500ms 触发一次
#  b) token 无增量时，keepalive_floor 内仅 1 行（事件门控生效）
#  c) progress_emit 抛异常时流式不中断
#  d) 全仓 grep 断言无裸 stdout 心跳写路径
```
<<<END>>>