# Quench Dev-Orchestrator — Reviewer 轮询硬契约、状态栏扩展与跨宿主端侧可观测性蓝图 (已归档 / 部分平替)
> *(MCP Reviewer Polling Contract Hardening, Status Bar Extension & Cross-Host Observability Blueprint — Archived / Partially Superseded)*

> **Document Type**: Architecture Blueprint (Archived during 2026-10-31 Post-Gemini-4 & Antigravity 2.0 Ledger Audit)  
> **Status**: 📦 ARCHIVED / PARTIALLY SUPERSEDED (2026-10-31)  
> **Preceding Baseline**: [v1.24 原生心跳自刷新、长轮询降压与 Poll 极简瘦身路线图](./v1.24_mcp_progress_heartbeat_and_poll_slimming_roadmap.md) (🟢 COMPLETED)  
> **2026-10-31 Audit Disposition**:
> - **Task `TBD.1` (`POLL_WAIT_MAX_S_HARD_CEILING = 25.0s` 常量化与 Loop 契约文档)**：**✅ 保留微增量卫生项**，已转入 [`docs/future_roadmap_ideas.md`](../future_roadmap_ideas.md) 作为后续版本轻量收口项（注：`server.py` 中 `_clamp_wait` 已实现 `25.0s` 截断）。
> - **Task `TBD.2` (`extensions/quench-statusbar/` VS Code 状态栏扩展)**：**❌ 废弃（已被宿主原生能力平替）**。Antigravity 2.0 为独立 Electron 应用（UI 插件基于 `sidecar.json` 侧边面板而非 `.vsix` `createStatusBarItem`），且右侧原生内置 **Auxiliary Pane（Subagents / Background Tasks / Terminals）** 配合 `v1.24` 原生 MCP `notifications/progress` 工具卡片原地刷新，叠加 `v1.25` 委派模式（`inverted`）下 Argon 直接在主会话流式可见，无需额外维护第三方状态栏扩展。
> - **Task `TBD.3`（L1/L2/L3 状态栏分级文档）**：**❌ 随 `TBD.2` 一并简化取消**，统一以纯 MCP 协议层 `notifications/progress` + `20s` 长轮询服务跨宿主环境。
> **Original Scope**: 客户端轮询契约强化（`POLL_WAIT_MAX_S_HARD_CEILING = 25.0s` 硬上限及 Loop 规范）、进度流逝单调流与本地 100ms 转动解耦（`⠋ Reviewer · Streaming (00:14)`）、`quench-statusbar` VS Code / Antigravity IDE 扩展（`createStatusBarItem` + `createFileSystemWatcher` 零 CPU 事件驱动 + 智能显示/完全隐藏生命周期）、以及面向 Desktop IDE、Antigravity App 与无头 CLI 的 L1/L2/L3 跨宿主分级适配矩阵。  
> **Explicit Non-Scope**: 16-tool 工具面不变量破坏（严禁新增独立轮询或状态栏控制工具）、跨进程状态机 CAS 机制弱化（INV-1）、非受管日志物理绕过（INV-9）。  
> **Authority**: 遵循 v1.20 核心不可触碰清单、奥卡姆剃刀公理及 2026-10-22 资深 Reviewer 架构全盘评审结论。

---

## 0. 结论与背景综述（Verdict & Background）

在 v1.24 中，Quench 成功交付了 FastMCP 原生 `notifications/progress` 通道集成、`wait_max_s` 长轮询以及非终态快照 V2 极简瘦身（6 字段，~160B）。在实际工程落地与用户体验走查中，团队进一步确立了以下核心认知与改进诉求：

1. **异步轮询的本质澄清**：异步长轮询（Long-Polling）与长连接（Long-Lived Connection）具有本质区别。长轮询保持了无状态单次调用的纯粹性；而"单次 300s 超长轮询管总"存在致命的网关超时（504 Gateway Timeout）、崩溃感知滞后与通道独占风险，必须予以否决。
2. **拒绝虚假百分比**：大模型深度推演与代码切片分析的时长不可先验计算。将进度改为明确的耗时流逝计数器与呼吸动画（`⠋ Reviewer · Streaming (00:14)`）是最诚实、干扰最小的用户界面表达。
3. **底边栏可观测性扩展**：在开发者的 IDE 环境中，底边栏（Status Bar）已被证明可以与模型用量插件等扩展和谐共生。通过设计轻量的 `quench-statusbar` 扩展，可以在无任务时**完全物理隐藏**、任务运行期实时展示动画，彻底解决用户"不知道 Reviewer 是否还在活着"的心智负担。
4. **跨宿主分级适配**：针对 VS Code 桌面端、Antigravity IDE、Antigravity App 独立桌面端/Web 端以及无头 CLI/CI 环境，确立清晰的 L1/L2/L3 分级降级阶梯，保证在无法加载第三方扩展的宿主中依旧享受长轮询与原生进度通知红利。

---

## 1. 异步轮询范式权衡与硬上限契约固化（Hard-Capped Polling Contract）

### 1.1 轮询范式深度权衡

| 维度 | **方案 A：20s 长轮询 + 客户端 Loop（采纳）** | 方案 B：高频短轮询（1s 间隔） | 方案 C：单次 300s 超长轮询（FFAIL 否决） |
|---|---|---|---|
| **网络与调用开销** | 极低（20s 一次请求，终态即时返回） | 极高（大量 HTTP/IPC 往返与上下文消耗） | 单次看似最小，但隐藏巨大风险 |
| **崩溃与死锁感知** | ≤ 20s 快速感知 Worker 故障并触发自愈 | 极快（~1s） | **严重滞后（300s 盲等期）** |
| **网关与代理穿透** | 安全（低于多数反向代理 30s 超时阈值） | 安全 | 🚨 **极高频触发 504 Gateway Timeout** |
| **信道并发与取消** | stdio 通道快速释放，支持交错取消与诊断 | 频次高，挤占通道 | 🚨 **300s 独占阻塞 stdio 管道** |
| **连接状态模型** | 严格无状态客户端，遵循 REST/RPC 原语 | 严格无状态客户端 | 伪装成长连接，破坏幂等与隔离契约 |

### 1.2 300s 超长轮询否决根因（FFAIL 判定细则）
- **崩溃感知黑洞**：底层 Worker 进程若在初期异常退出（如 OOM Kill），客户端将盲等余下的数百秒，严重破坏故障自愈契约。
- **中间件超时切断**：企业级反向代理（Nginx 默认 60s、Cloudflare 100s）会在超时时主动切断 TCP 连接抛出 504，导致客户端捕获非预期异常。
- **RPC 通道独占阻塞**：在 stdio 单信道 JSON-RPC 模型下，单次超长阻塞请求会阻碍通道调度其他高优先级带外指令（如紧急取消任务 `dev_reviewer_cancel`）。

### 1.3 契约常量与客户端 Loop 规范
- **服务端硬上限常数**：
  ```python
  POLL_WAIT_MAX_S_HARD_CEILING: Final[float] = 25.0
  ```
  服务端 `_clamp_wait()` 必须对任何传入的 `wait_max_s` 进行显式封顶截断：`min(v, POLL_WAIT_MAX_S_HARD_CEILING)`。
- **推荐客户端 Loop 模式**：
  ```python
  # 客户端标准调度伪代码
  while True:
      res = await client.call_tool("dev_reviewer_poll", {"job_id": jid, "wait_max_s": 20.0})
      if res.get("state") in TERMINAL_STATES:
          return res
      # 非终态立即进入下一轮 20s 轮询，保持故障检测窗口 <= 20s
  ```

---

## 2. 进度展示形态契约与本地转动解耦（Streamlined Progress & Decoupled Ticker）

### 2.1 极简形态规范
- 格式标准：`⠋ Reviewer · Streaming (00:14)`
- 彻底摒弃虚假百分比（如 `45%`）：推理任务的 token 长度与思维链深度在物理上无法先验获知，静态估算会导致假死与认知偏差。
- 文本组成：`[Spinner 动画帧]` + `Reviewer` + `·` + `[当前 Phase: Initializing / AstExploration / Reasoning / Streaming]` + `([mm:ss 耗时])`。

### 2.2 服务端与客户端权责严格切分
- **服务端权责（数据流 SSOT）**：
  - 推送严格单调的整数耗时：`elapsed_s = int(max(0, monotonic() - started_monotonic))`。
  - 推送单行简洁描述：`message: "[RUNNING] phase=streaming elapsed=14s #3"`（<= 120 字符，不含换行与 markdown 反引号）。
  - 服务端**严禁发送高频动画帧字符**（如每 100ms 推送一次 `⠋`、`⠙`），避免网络风暴与 IPC 信道拥塞。
- **客户端权责（本地平滑渲染）**：
  - 客户端本地维护 100ms 刷新率的 Ticker 定时器，负责原地旋转 Braille Spinner（`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`）。
  - 本地转动与服务端 1.0s 冷却的通知节流彻底解耦，消除每秒跳一帧的卡顿感。

---

## 3. `quench-statusbar` 状态栏扩展与全自动隐藏生命周期

### 3.1 扩展架构与底边栏定位
在 VS Code 与 Antigravity IDE 中，底边栏右侧区域通常包含语言模式、Git 分支、编码格式以及各类模型用量监控插件。
`quench-statusbar` 定位为极简、非侵入式伴生扩展：
- 使用 VS Code 标准 API：`vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100)`。
- 优先级设为 100，确保紧邻核心状态，与现有用量监控扩展和平共处。

### 3.2 零 CPU 开销状态感知（Zero-CPU Event-Driven Watcher）
- **反模式警示**：严禁在扩展后台启动 `setInterval` 定时轮询磁盘上的状态文件。
- **最佳实践**：采用 VS Code 原生 `vscode.workspace.createFileSystemWatcher(".agents/jobs/*.json")`。
  - 底层基于 OS 内核通知（Windows `ReadDirectoryChangesW` / Linux `inotify` / macOS `FSEvents`）。
  - 当无 Reviewer 任务运行时，扩展处于完全休眠状态，**CPU 占用率严格为 0.00%**。

### 3.3 全自动显示与完全物理隐藏生命周期（Dynamic Auto-Hide Lifecycle）

```
 [Idle: 初始/空闲]
       │
       │ (FSWatcher: 检测到 .agents/jobs/<jid>.json 创建)
       ▼
 [Active: 任务在途] ──────► 调用 statusBarItem.show()
       │                   展示: ⠋ Reviewer · Streaming (00:14)
       │                   本地 Ticker 100ms 旋转动画
       │
       │ (FSWatcher: 检测到 state 变为 COMPLETED / FAILED / CANCELLED)
       ▼
 [Terminal: 终态确认] ────► 展示: $(check) Reviewer Done 或 $(error) Reviewer Failed
       │                   保持 3.0s 确定性视觉反馈
       │
       │ (3.0s 定时器触发)
       ▼
 [Hidden: 物理隐形] ──────► 调用 statusBarItem.hide()，彻底释放底边栏空间
```

- **完全隐藏保证**：无审查任务时，底边栏不留下任何占位图标、文字或空白间隙，丝毫不挤占用户的编辑视线与空间。
- **可交互动作**：点击在途状态栏项可快速触发 `workbench.action.quickOpen` 定位至最新 `.agents/logs/reviewer/latest-*.log` 查看流式思考输出。

---

## 4. 跨宿主分级适配矩阵（Tiered Cross-Host Architecture）

### 4.1 Chat 对话窗口内的 Tool Call 气泡机制解析
- **概念说明**：在 AI 智能编程助手（如 Copilot Chat、Antigravity Chat）的对话面板中，当 Agent 调用 MCP 外部工具（如 `dev_reviewer_poll`）时，宿主会在消息列表中渲染一个可折叠的卡片部件（即"工具调用气泡"）。
- **原地刷新行为**：
  - **支持 MCP Progress 的宿主**：在工具调用挂起期间，收到的 `notifications/progress` 会原地覆写该气泡的头部状态文本与旋转进度环，**不会产生新气泡**。
  - **不支持 MCP Progress 的宿主**：气泡在等待期间保持静态；如果客户端使用单次 20s 轮询，长轮询结束后该气泡折叠归档，下一轮循环产生下一个气泡（得益于 v1.24 降压，气泡数量已从几十个锐减至每分钟 2~3 个）。

### 4.2 L1 / L2 / L3 分级适配策略

| 层级 | 运行环境 | 可观测性呈现形态 | 降级机制 |
|---|---|---|---|
| **L1 级：桌面富 IDE** | VS Code, Antigravity IDE (Desktop) | `quench-statusbar` 动态底边栏（主） + Chat 气泡原地刷新（副） | 若未安装扩展，平滑退化至 Chat 气泡 |
| **L2 级：应用与 Web 端** | Antigravity App (独立桌面/Web沙箱), Theia Web | 宿主内建 MCP Progress 浮层 / Chat 消息流卡片原地自刷新 | 不依赖 VS Code 扩展；纯 MCP 协议驱动；20s 长轮询与 160B 瘦身保障平稳运行 |
| **L3 级：无头 CLI 与 CI** | 终端命令行、GitHub Actions、CI 自动化脚本 | 终端单行 ANSI Escape 原地重绘 (`\r⠋ Reviewer...`) 或静默日志输出 | 纯标准流与日志流输出，零 GUI 依赖 |

- **Antigravity App 特殊说明**：Antigravity App 通常具有高度定制的前端 UI，且不兼容安装未打包的 VS Code 原生插件。L2 方案确保了服务端不强绑定 VS Code 宿主能力，通过 MCP 原生通知向 App 前端推送事件，由 App 自由决定渲染为原生 Toast、顶栏指示器还是气泡动画。

---

## 5. 历史规划任务去留结案（2026-10-31 Disposition）

### 任务 TBD.1 ➡️ 已并入后续卫生收口池 — `dev_reviewer_poll` 轮询硬上限常数封顶与客户端 Loop 契约规格固化
- **【处置结论】**：`_clamp_wait` 物理截断已在 `server.py` 生效；协议常量提取（`POLL_WAIT_MAX_S_HARD_CEILING = 25.0`）与规范同步已并入 [`docs/future_roadmap_ideas.md`](../future_roadmap_ideas.md) §1.1 候选池。
- **【原涉及文件】**：
  - `[MODIFY] plugins/quench-dev-tasks/server/tool_surface_constants.py`（增加 `POLL_WAIT_MAX_S_HARD_CEILING = 25.0`）
  - `[MODIFY] plugins/quench-dev-tasks/server/server.py`（`_clamp_wait` 绑定常量）
  - `[MODIFY] dev_tasks_mcp_specification.md`（更新契约文档）
  - `[NEW] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_ceiling_contract.py`

### 任务 TBD.2 ❌ 已废弃（宿主原生能力平替） — `quench-statusbar` VS Code / Antigravity IDE 状态栏扩展原型实现
- **【处置结论】**：因 Antigravity 2.0 架构迁移（独立桌面端采用 `sidecar.json` 侧边面板而非 `.vsix` 状态栏，且原生内置 Auxiliary Pane 与 MCP `notifications/progress` 卡片原地刷新）而正式取消，不再新建 `extensions/quench-statusbar/`。

### 任务 TBD.3 ❌ 已废弃（随 TBD.2 简化合并） — 跨宿主（Desktop IDE vs App vs CLI）分级适配规范与可观测性架构固化
- **【处置结论】**：无需维护单独的 L1 第三方扩展分级，统一由 MCP 原生 `notifications/progress` 与 `20s` 长轮询覆盖跨宿主场景。
