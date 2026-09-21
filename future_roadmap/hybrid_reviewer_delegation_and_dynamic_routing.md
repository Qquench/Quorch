# 混合审查：宿主原生 Subagent 与外部推理 API 动态路由规划
(Hybrid Reviewer: Native Subagent & External API Dynamic Routing Architecture Roadmap)

> **状态**：规划预研 (Planned / Future Roadmap)  
> **实施契机**：在完成当前 Milestone 1~5 基础自适应闭环后，面向多模型、多代理异构混合环境的进阶演进。  
> **核心前置**：Task 5 确立的 `reviewer_handoff` 统一能力协商信封契约。

---

## 1. 业务演进契机 (Motivation & Context)

随着开发工具链的演进，开发者工作区常同时并存多种审查能力：
1. **宿主原生 Subagent**：如 Antigravity / Claude Code 内置的 Reviewer 子代理，具备极佳的宿主环境亲和力（可直接访问 IDE 内部状态、DevTools、仿真器），且零额外 API Key 开销；
2. **外部/本地深度推理 API**：如外部 Thinking 深度推理 API 或本地 Ollama 部署的开源大模型，具备强大的分支推演与死锁挖掘能力。

在现有 Task 5 的实现中，系统通过 `strategy_order: ["subagent", "engine", "manual"]` 进行静态优先级瀑布匹配。然而，面对更复杂的现实需求，开发者需要**根据任务性质自适应分流、甚至多方协同审阅的更灵活机制**。

---

## 2. 核心架构设计：动态路由器 (Dynamic Reviewer Router)

```
                            ┌────────────────────────┐
                            │  触发审查 / 批次完工   │
                            └───────────┬────────────┘
                                        │
                                        ▼
                        ┌────────────────────────────────┐
                        │   Dynamic Reviewer Router      │
                        │   (基于语义标签、成本与上下文特征) │
                        └───────┬──────────────┬─────────┘
                                │              │
                ┌───────────────┘              └────────────────┐
                ▼                                               ▼
     【UI / 视觉 / 交互类任务】                       【并发 / 状态机 / 算法核心】
                │                                               │
                ▼                                               ▼
     调度: 宿主原生 Subagent                           调度: 外部 Thinking 深度推理 Reviewer
     - 调取 DevTools / 浏览器仿真                      - 展开 Thinking 思考流穷举分支
     - 视觉回归与无障碍审核                            - 并发竞态与状态机跳步设防
```

### 2.1 任务感知型智能分流策略 (Task-Aware Routing)
- **UI / 前端 / 渲染类任务**：自动将 `preferred` 标定为 `subagent`，利用宿主平台的截图、DOM 树读取与浏览器子代理能力进行验收；
- **核心状态机 / 并发锁 / 跨模块通信**：自动将 `preferred` 标定为 `engine`（外部深度推理引擎），利用其强大的 Thinking 模式穷举边界条件；
- **配置 / 构建清单 / 纯文档类**：自动快速放行或标记为极轻量审查。

### 2.2 双模交叉核验模式 (Cross-Validation / Red-Team Duel)
- 对于声明为 `[P0-CRITICAL]` 的高危重构任务，路由器可输出**双重策略载荷**：
  1. 宿主 Subagent 先行执行架构初审与工程可读性把关；
  2. 外部推理引擎作为“红方挑刺器（Adversarial Red Team）”，对初审规约进行死锁扫描与边界攻击；
  3. 双重通过后方可被主控执行器检出。

### 2.3 配额与成本弹性自适应 (Quota & Cost Elasticity)
- 在 `quench_stack.yaml` 中允许声明配额预算策略（例如 `budget_policy: "subagent_first"` 或 `"cost_optimal"`）；
- 当外部 API 触发 429 流控或配额耗尽时，无缝动态切换为宿主 Subagent；当宿主模型上下文窗口逼近上限时，平滑溢出至外部 Thinking 引擎。

---

## 3. 对当前 Task 5 契约的向前兼容保障 (Backward Compatibility by Design)

本高级规划之所以**不需要在当前周期急于实现，且日后能够随时无缝接入**，是因为 Task 5 确立的信封架构在设计之初就保留了充分的延展性：

1. **信封结构完全中立**：
   `reviewer_handoff` 返回的是 `strategies` 策略列表与一个 `preferred` 推荐指针。当前阶段，`preferred` 是由配置静态决定的；未来引入动态路由时，**信封的字段格式、类型签名与消费方式无需发生任何破坏性改变**，只需在服务端内部接入 `DynamicReviewerRouter.resolve_preferred(...)` 计算函数即可。
2. **多载荷并存能力**：
   信封内同时安全携带了 `subagent` 与 `engine` 的完整执行载荷，客户端无论选择谁、或者同时消费谁，都有完备的上下文输入，杜绝了多次交互握手的延迟。

---

## 4. 后续演进阶段里程碑 (Future Milestones)

- [ ] **Phase A (语义标签解析器)**：在 `task_parser` 增加轻量标签识别（如 `#frontend`, `#concurrency`, `#algorithm`）。
- [ ] **Phase B (DynamicRouter 策略计算)**：在 `reviewer_dispatch.py` 内实现基于标签的规则加权计算器。
- [ ] **Phase C (CLI 调度扩展)**：支持 `quorch reviewer dispatch --target subagent|engine|both` 手动干预分流。
