# Manifest Compaction & Generational Archiving Contract (清单分代归档架构契约)

> **文档版本**: 1.0 (Phase 0 契约冻结)  
> **适用范围**: Quench Dev-Orchestrator 治理微内核权威清单 (`.agents/.quorch/manifest.json`)  
> **制定背景**: 经资深架构 Reviewer 红队审查，为防止未来清单规模扩大后进行分代压缩时击穿治理不变量，在具体实现前将四项核心架构约束进行不可变冻结。

---

## 1. 契约目标与触发闸门 (Objective & Trigger Gates)

分代归档的目标是在 `manifest.json` 累积大量历史任务时，将已完成并归档的任务元数据下沉至冷存储 (`manifest_archive.json`)，保证热层清单常驻轻量化（< 256 KB），同时维持 Fencing Token 租约安全与双向互锁完整性。

### 触发启动阈值 (Trigger Gates)
在满足以下**任一**客观事实前，严禁盲目实施全量分代迁移（拒绝过早优化）：
1. **清单物理体积**: `manifest.json` 磁盘体积 > 256 KB；
2. **对账耗时**: `dev_tasks_status` 中 `reconcile_workspace` 耗时 > 100 ms；
3. **单项目任务量**: 单个工作区累计创建任务数 > 500 条。

---

## 2. 四大核心不变量 (Four Core Architectural Invariants)

未来在实施分代归档（Compaction）时，实现代码必须无条件服从以下四项铁律：

### 铁律一：Fencing Token 水位线永不回退 (Generation Watermark Invariant)
- **风险**: 若压缩时将已释放记录从热层抹除，一旦相同命名空间的任务重新出现（如返工重开或相似 ID），其 `generation` 将重置回 0。持有旧 Token（代际 ≥ 1）的滞后进程将穿透代际校验。
- **约束规范**:
  1. 系统必须维护紧凑的 `generation_watermark: Dict[str, int]`（记录 `<namespaced_id>` 历史最大代际）；
  2. 派发新租约时强制满足：`new_generation = max(hot.generation, watermark.get(id, 0)) + 1`；
  3. 水位线映射永不随压缩清零，代际跨会话严格单调递增。

### 铁律二：冷热分层边界与生命周期强绑定 (Lifecycle Boundary Invariant)
- **风险**: 若热层记录被下沉至冷层，而对应的 `.md` 任务文件仍位于 `docs/dev_tasks/` 活跃目录，`reconcile_workspace` 只读热层将误将合法任务判定为 `[UNAUTHORIZED_BYPASS]`，引发假阳性可用性 DoS。
- **约束规范**:
  1. 冷热迁移边界必须且仅能以 [`dev_tasks_archive`](file:///d:/Work/Quench/quorch/plugins/quench-dev-tasks/server/server.py#L2006) 生命周期为准；
  2. **当且仅当** 任务单 `.md` 物理移动至 `docs/dev_tasks/archive/` 之后，其对应的清单记录才允许移出热层进入冷层；
  3. 活跃目录 `docs/dev_tasks/*.md` 中的所有任务单在热层清单中必须 100% 保持权威登记。

### 铁律三：双 Tier 紧凑索引权威对账 (Dual-Tier Compact Index Invariant)
- **约束规范**:
  1. `manifest.json` 为热层完整账本（包含当前全部未归档任务的独占租约、心跳戳与哈希基线）；
  2. `manifest_archive.json` 为冷层紧凑账本，剥离瞬态字段（心跳纳秒、持有者临时令牌），仅保留 `task_id`, `md_sha256`, `generation`, `released: true` 审计链；
  3. 历史对账或审计以 `hot ∪ cold` 双 Tier 联合视图进行，保证 Git 历史追溯完整性。

### 铁律四：事务性锁序与原子落盘 (Transactional Lock Ordering & Crash Consistency)
- **风险**: 若压缩操作未受排他锁保护，并发心跳或领单可能被陈旧热层覆写；若先清空热层再写入冷层，中途崩溃将导致墓碑永久丢失。
- **约束规范**:
  1. **单一排他锁**: 整个迁移过程（读热层 $\to$ 写冷层 $\to$ 替换热层）必须在同一个 `manifest.json.lock` 排他文件锁内原子完成；
  2. **冷先行、热后行**:
     - 步骤 1: 将迁移条目追加至冷归档文件并执行 `os.fsync` 确保物理刷盘；
     - 步骤 2: 将精简后的热层写入临时文件并通过 `os.replace` 原子替换；
     - 保证即使在步骤 1 与步骤 2 之间发生断电或崩溃，记录也仅是两层冗余（幂等可恢复），绝对不会发生“墓碑丢失、代际回退”。
