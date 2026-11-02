# Plan: Reviewer Anti-Anchoring & Runtime Verification Architecture
# (Reviewer 防锚定与运行时反向探针治理蓝图)

> **版本**: v1.28-proposal / Architecture Blueprint  
> **状态**: 📋 Pending Blueprint / 提案阶段  
> **上下文与触发场景**:  
> Quorch 最初是为辅助精密制造执行系统（MES）开发而设计的治理框架。但在多 Agent 协同演化中，发现主 Agent（敏捷执行模型，如轻量级快速模型）在向评审模型（Reviewer）或外部推理引擎咨询时，存在普遍的“事实-推断坍缩”与“预设性提问注入”。  
> 本规划旨在评估此类认知偏置在 MES 等经典软件工程与复杂排障场景中的差异，并为 Quorch Reviewer 的未来演进提供结构性解耦方案。

---

## 1. 软件工程 (MES) vs 探索性场景 (ML/泛用排障) 的认知失效差异

### 1.1 为什么 MES 等经典开发场景中，锚定效应的破坏性相对受控？

在典型的 MES（制造执行系统，如工单排产、设备状态机、物料追溯、批次流转、ERP 接口对接）开发中，主 Agent 产生偏见或诱导 Reviewer 时，其**系统性破坏力通常显著小于开放式/生成式场景**：

1. **客观物理底线的自动化证伪（Deterministic Hard Constraints）**：
   - 传统软件开发拥有由编译器、静态类型检查器（TypeScript/Mypy）、单元测试框架（Pytest/Jest）、数据库 ACID 约束和外键关系构成的“客观裁判”。
   - 即使主 Agent 误导 Reviewer 批准了一份错误的接口设计或数据迁移方案，代码在执行阶段几乎必然遭遇 `SyntaxError`、`TypeError`、`AssertionError` 或 DB 唯一性索引冲突。物理世界的执行失败会强行中断错误链条。
2. **问题边界与状态机高度收敛（Bounded State Space）**：
   - MES 业务规则（如“工单在未质检完成前不得进入包装库”）是白纸黑字的规格书（Spec）。代码正确与否有清晰的真值表与期望行为，不依赖主观解释。
3. **Quorch 自身的硬性管控制约**：
   - Quorch 内建的 `DoD Verification Commands`（DoD 验证命令）要求每个任务单必须附带可执行的自动化测试命令。即便 Reviewer 被叙事锚定，只要 DoD 测试未全绿，任务便无法流转关闭。

### 1.2 MES 场景中依然存在的隐蔽锚定风险（不可盲目乐观）

尽管有上述底线保护，主 Agent 仍可能在以下三种**“测试无法自动捕获的暗区”**中误导 Reviewer：

1. **高并发与死锁/竞争条件（Concurrency & Race Conditions）**：
   - 主 Agent：“*这段设备状态上报只会有单线程顺序写入，加互斥锁是过度设计，请确认。*”
   - Reviewer 若轻信该假定，在本地单测全绿的情况下放行，但在车间多台 PLC 同时瞬时上报时将发生隐蔽的数据覆盖与死锁。
2. **业务逻辑漂移与隐性假设违背（Spec Erosion）**：
   - 主 Agent 误读了离线/断网重传机制，向 Reviewer 提交了一套“简化版”的幂等去重方案。Reviewer 在单一代码文件范围内审查，未能察觉这破坏了跨站点的物料批次守恒。
3. **过拟合单测（Test Cheating / Confirmation Bias）**：
   - 主 Agent 围绕自己的错误理解编写了自圆其说的测试用例，并在 Query 中强调“*测试已全通*”，Reviewer 放弃了对真实业务边界用例（如异常断电、缓冲区溢出）的深度推演。

---

## 2. Quorch Reviewer 机制现状的结构性盲区复盘

勘查当前 Quorch 源码（`server.py`、`consultation.py`、`reviewer_engine.py`），发现现有机制在防锚定层面存在以下四大瓶颈：

```
主 Agent (Runner)                      Quorch 服务端                       Reviewer 模型
┌──────────────────┐               ┌──────────────────┐               ┌──────────────────┐
│ 产生主观推断       │ ── query ──► │  直接拼装提示词   │ ── prompt ──► │ 接纳为既定事实    │
│ "已确认微调导致.." │  (单字段)    │ 无事实推断隔离     │               │ 编织自洽论证      │
└──────────────────┘               └──────────────────┘               └──────────────────┘
                                             │                                  │
                                             │ ◄─── <<<NEED-FILES>>> (静态补全) ─┘
                                             ▼
                                  从磁盘抓取更多代码切片
                                  (无运行时证据 / 无法执行探针)
```

1. **入口无解耦契约**：
   - `dev_reviewer_submit` 的入参仅有单一 `query: str`，直接拼入 Prompt：`### Consultation Query\n{query.strip()}`。
   - 事实（观测数据）与推断（主观解释）完全坍缩，没有标记信道。
2. **`<<<NEED-FILES>>>` 是“静态补全”，不是“动态实验”**：
   - 当前的“多跳询问”机制只能从本地磁盘读取静态源码切片，**无法执行代码，无法获取运行时环境的动态遥测**（如数据库连接池实时状态、Redis 内存指标、张量 shape/stride 等）。
3. **多跳门控冷启动（Gate Skip）**：
   - `evaluate_multi_hop_gate` 要求历史上必须有 `>=20` 条样本且 `demand>30%` 才放行多跳。在低频突发或冷启动阶段，Reviewer 连静态文件补全的机会都会被熔断。
4. **证据控制权倒置**：
   - `context_files` 和初始范围均由被审查的主 Agent 选择，容易造成“选择性供给证据”。

---

## 3. Quorch Reviewer 后续演进规划建议 (Evolution Roadmap)

为彻底阻断主 Agent 认知偏置对 Reviewer 的穿透，建议在 Quorch 后续大版本中分步实施以下改造：

### Epic A: 输入双平面解耦 (Epistemic Input Plane)
- **目标**：在 `dev_reviewer_submit` 接口中引入可选的解耦输入，区分遥测数据与调用者主张。
- **改动**：
  ```python
  async def dev_reviewer_submit(
      workspace_root: str,
      query: str,
      context_files: list[str] | None = None,
      mode: str = "evaluate",
      observations: str | None = None,      # 原始日志、报错堆栈、命令原始输出
      caller_hypotheses: str | None = None, # 标记为待验证假说
      ...
  )
  ```
- **收益**：Reviewer 在系统层面获得“未污染证据”，优先依据 `observations` 建立独立假说。

### Epic B: 认知探针协议替换静态补全 (Dynamic Probe Protocol)
- **目标**：超越 `<<<NEED-FILES>>>`，允许 Reviewer 向 Quorch 发起动态探针请求。
- **协议草案**：
  ```text
  <<<PROBE_REQUEST>>>
  goal: 检查车间物料流水号高并发竞争状态
  eval_command: pytest tests/integration/test_concurrency_race.py -k test_lot_generation
  expected_invariants: no duplicate lot IDs across 100 concurrent workers
  <<<END>>>
  ```
- **收益**：Reviewer 可直接要求运行环境给出裁决结果，而非靠理论空对空脑补。

### Epic C: 承重前提审计与翻转条件 (Premise Audit & Flip Invariants)
- **目标**：强制 Reviewer 输出必须附带“支撑该审查意见的核心假定”与“翻转条件”。
- **规范**：
  - Reviewer 在批准（LGTM）或否定时，必须显式列出：
    1. `【审查前提】`: 如“假定本模块为单机单实例部署，无多节点共享内存”；
    2. `【翻转条件】`: 如“若未来接入集群式负载均衡，本方案必须重构为分布式悲观锁”。

---

## 4. 总结与分工备忘

- **Quorch 的定位**：围绕实际项目（如 MES 系统），依托工程文件、单测套件、DoD 门禁和静态多跳提供**高度受控的工程质量保证**；
- **外部推理工具（如 Advisor MCP）的定位**：作为跨场景的高维外脑，在遇到探索性难题或认知死局时，击破主 Agent 的固有天花板。
- 本规划作为 Quorch 下一阶段架构演进的储备蓝图，后续在专门的 Quorch 演进分支中细化实施。

