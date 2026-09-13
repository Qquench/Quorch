# 阶段一演进路线图：个人无缝跨项目治理与实战闭环
(Stage 1 Roadmap: Personal Seamless Multi-Project Governance & E2E Validation)

> **目标定位**：在当前开发者本机环境（Windows + Antigravity IDE）下，实现无论在 `JJW_MES`、`Quench_MCP` 还是未来任意新项目中，都能 **10 秒内无痛接入、环境解释器不脱节、会话锁零冲突、双轨边界精准识别**，并跑通全生命周期的任务流转与自动归档。

---

## 一、 当前基线与差距分析

- **当前现状**：
  - FastMCP 核心工具链（8 个工具）、状态机引擎、六大字段校验器、双轨边界引擎全部就绪（20/20 单测通过）；
  - 下游项目（如 `JJW_MES`）已通过 `init_project.py` 完成基础注册，并在真实 UI 改造场景中验证了初版流转；
- **核心痛点与差距**：
  1. **多窗口/并发会话下的文件锁脆弱性**：高频编辑或多会话切换时，`.quench_bypass.json` 缺乏原子替换与 `FileLock` 保护；
  2. **新项目资产启发式识别边界尚待微调**：针对微前端、单测子目录、各种配置后缀（如 `.env.example`、`vite.config.ts`），偶发误拦纯文档或漏管高危配置；
  3. **新项目接入指令偏长**：每次接入新项目仍需敲击较长的绝对路径调用 `init_project.py`；
  4. **全生命周期实战归档演练**：需将活跃任务单从需求起草 ➔ 审查 ➔ 施工 ➔ 审计 ➔ `dev_tasks_archive` 完整落盘验证。

---

## 二、 史诗级任务拆解 (Epics & Tasks)

### Epic 1.1: 落实会话锁并发加固与自愈机制 (对应当前活跃任务 1)
- **背景**：当前会话动态旁路绑定了 `conversationId` 和租期，但并发读写可能产生文件竞争。
- **任务项**：
  - [ ] 在 `file_scope_guard.py` 中引入 `filelock.FileLock`，包裹 `.quench_bypass.json` 的读写与清理操作；
  - [ ] 在 `server.py` 的 `dev_tasks_set_bypass` 工具中引入临时文件原子替换（`os.replace`），防范断电/强杀产生的半截畸形 JSON；
  - [ ] 强化时区处理，统一使用 `datetime.now(timezone.utc)` 避免本地时区变动导致租约失效错乱；
  - [ ] 扩充 `test_file_scope_guard.py`，模拟并发读写与畸形文件自愈测试。

### Epic 1.2: 调优双轨管控边界判定引擎 (对应当前活跃任务 2)
- **背景**：使任意新接入项目在未手写繁琐配置的情况下，也能智能识别生产代码与放行文档。
- **任务项**：
  - [ ] 在 `project_config.py` 中扩充启发式免管扩展名（`.drawio`, `.puml`, `.svg`, `.ico`, `.sample` 等）；
  - [ ] 细化高危构建/配置文件识别（`docker-compose.*.yml`, `.env.example`, `tsconfig.*.json`）；
  - [ ] 增强多层 Glob 递归匹配（支持 `backend/tests/**` 与 `frontend/**/__tests__/**`）；
  - [ ] 扩充 `test_project_config.py`，覆盖多语言经典工程目录判定。

### Epic 1.3: 全局脚手架轻量化与 PowerShell 快捷接入
- **背景**：消除每次初始化新项目时繁琐的命令输入。
- **任务项**：
  - [ ] 编写轻量 PowerShell 快捷脚本 / 函数 `quench-init`（加入用户 `$PROFILE` 或提供一键安装脚本）；
  - [ ] 在 `init_project.py` 中加入项目环境自检：自动探测当前工作区 Git 状态、Python 解释器与目录结构；
  - [ ] 优化 `.agents/plugins.json` 生成逻辑，确保多项目注册时的幂等性与绝对路径规范化。

### Epic 1.4: 真实开发全生命周期端到端实战归档
- **背景**：通过本仓库自身治理推进上述任务，跑通从检出到归档封板的全流程。
- **任务项**：
  - [ ] 将本阶段任务落地到 [docs/dev_tasks/](file:///d:/Work/Quench/MCP/docs/dev_tasks/) 活跃任务单中；
  - [ ] 完成上述功能实现并通过所有 DoD 单元测试；
  - [ ] 调用 `dev_tasks_complete` 触发单测断言物理审计；
  - [ ] 调用 `dev_tasks_archive`，验证自动移入 `docs/dev_tasks/archive/` 且自动增量追加 [CHANGELOG.md](file:///d:/Work/Quench/MCP/CHANGELOG.md)。

---

## 三、 DoD 验收标准 (Definition of Done)

1. **测试基线**：`pytest plugins/quench-dev-tasks/server/tests/` 全部通过（用例数从 20 项增至 25+ 项，无失败）；
2. **接入耗时**：任意本地新项目运行 `quench-init`，10 秒内完成配置注入并可通过 Antigravity IDE 正常拉起；
3. **闭环留痕**：至少完成一次完整的 `dev_tasks_archive` 归档动作，[CHANGELOG.md](file:///d:/Work/Quench/MCP/CHANGELOG.md) 正确生成增量版本摘要。
