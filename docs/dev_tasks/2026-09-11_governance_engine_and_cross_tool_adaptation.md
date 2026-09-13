# Quench MCP 任务治理引擎深化与跨开发工具适配架构审查任务单

> **审查与执行模型须知**
> - 本任务单用于对近期在 Quench MCP 中落地的一系列重大架构特性（三层旁路治理体系、物理会话锁、双轨生产代码边界划分引擎、开源跨工具适配体系）进行**工程留痕与深度架构审查**。
> - **设计参考文档**：
>   - [dev_tasks_mcp_specification.md](file:///D:/Work/Quench/MCP/dev_tasks_mcp_specification.md)
>   - [rules/dev-tasks-discipline.md](file:///D:/Work/Quench/MCP/plugins/quench-dev-tasks/rules/dev-tasks-discipline.md)
>   - [OPEN_SOURCE_RELEASE_GUIDE.md](file:///D:/Work/Quench/MCP/OPEN_SOURCE_RELEASE_GUIDE.md)
> - **审查指引**：架构审查模型（由用户自选的高阶推理模型）需针对当前实现的严密性、边界抗脆弱性、防滥用闭环以及开源生态中向 Cursor / Claude Code / Windsurf / Git Hooks 移植的可行性出具诊断意见。
> - 所有任务当前处于 `⬜ 待确认` 状态，待审查修订或确认通过后方可检出执行。

---

## 阶段规划概览

| 任务编号 | 任务名称 | 当前状态 | 关注维度 |
| :--- | :--- | :---: | :--- |
| 任务 1 | 三层快速旁路与物理会话锁安全审查与防御加固 | ⬜ 待确认 | 安全性、防越权、会话隔离 |
| 任务 2 | 双轨管控边界判定引擎与多语言仓库启发式算法调优 | ⬜ 待确认 | 准确率、误报率、异构语言兼容 |
| 任务 3 | 跨开发工具（Cursor / Claude Code / Git Hooks）适配抽象层设计 | ⬜ 待确认 | 开源架构解耦、客户端降级容错 |

---

### 任务 1 ⬜ 待确认 — 三层快速旁路与物理会话锁安全审查与防御加固

#### 【涉及文件】

```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py
```

#### 【缺陷根因与修改目标】

根因：当前已落地物理会话锁（绑定 `conversationId`）与 4 小时租期，但对于短时间内高频发起的并发 Tool 调用、以及多工作区/多工作树并行开发场景，会话锁文件的原子写入和异常损坏缺少自愈与回滚备份机制。此外需防范 Agent 构造虚假 `conversationId` 绕过校验。
目标：审查并强化 `dev_tasks_set_bypass` 与 `file_scope_guard.py` 的并发文件锁（`FileLock`）保护，完善会话损坏时的自动修复逻辑，确保会话旁路在任何极端异常下均不发生静默穿透或误杀。

#### 【目标签名与类型契约】

```python
def verify_session_integrity(bypass_data: dict, incoming_conversation_id: Optional[str]) -> tuple[bool, str]:
    """
    校验会话旁路完整性与租约状态。
    返回: (is_valid, reject_reason)
    """

def safe_clean_corrupted_bypass(bypass_path: Path) -> None:
    """原子化清理或重命名已失效/损坏的会话旁路文件。"""
```

#### 【分步改造指引】

1. 在 `file_scope_guard.py` 中，将直接文件读写包裹进 `FileLock`（使用已引入的 `filelock` 库），避免极速多文件并发写入时的读写竞态。
2. 强化 `server.py` 的 `dev_tasks_set_bypass` 工具：增加对非法字符、超长 reason 或恶意伪造 session_id 的输入净化校验。
3. 补充并发竞态与畸形 JSON bypass 文件的单元测试用例，确保测试覆盖率保持 100%。

#### 【防御与边缘校验】

- 锁文件写入中途进程被强杀：使用临时文件 + 原子替换（`replace`）写盘，防止残留半截 JSON。
- 租约时间戳时区异常：严格使用 `datetime.now(timezone.utc)` 计算与对比，避免本地时区切换造成的租约失效错乱。

#### 【DoD 验证命令】

```bash
pytest plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py -k "session_lock" -v
```

---

### 任务 2 ⬜ 待确认 — 双轨管控边界判定引擎与多语言仓库启发式算法调优

#### 【涉及文件】

```
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_project_config.py
```

#### 【缺陷根因与修改目标】

根因：当前已实现“显式清单（`quench_stack.yaml`）+ 启发式文件后缀兜底”的双轨判定。但启发式识别规则中，对微前端 monorepo、嵌套测试目录（如 `__tests__`、`frontend/e2e`）、以及配置文件（`.env.example`、`docker-compose.override.yml`）的识别粒度尚需架构审查评估是否需要细化，以防在无显式配置的第三方仓库中产生误拦或漏管。
目标：优化 `QuenchStackConfig.is_path_governed` 的匹配算法与默认规则集，支持多层级 Glob 通配与更丰富的工程资产分类，使任意第三方新项目在零配置情况下也能智能获得合理的安全边界。

#### 【目标签名与类型契约】

```python
class GovernanceScope(BaseModel):
    managed_paths: list[str] = Field(default_factory=list)
    unmanaged_paths: list[str] = Field(default_factory=list)
    heuristic_exempt_extensions: set[str] = Field(default_factory=...)
    heuristic_governed_extensions: set[str] = Field(default_factory=...)

def is_path_governed(self, target_file: str | Path, workspace_root: Optional[Path] = None) -> bool:
    """双轨边界智能仲裁：显式清单优先 -> 目录属性感知 -> 扩展名与特征匹配。"""
```

#### 【分步改造指引】

1. 审查 `project_config.py` 中 `NON_CODE_EXTENSIONS` 与 `CODE_EXTENSIONS` 的分类边界，评估文档类、素材类、数据类文件的覆盖完备性。
2. 引入路径属性感知（例如区分根目录说明文档与子模块内的同名说明文档）。
3. 扩充 `test_project_config.py`，新增包含 monorepo、C/C++、Go、Rust、Java 等多语言典型工程结构的文件判定用例。

#### 【防御与边缘校验】

- 大小写不敏感文件系统（Windows/macOS）与敏感系统（Linux）的 Glob 差异：统一在匹配前进行规范化标准化。
- 相对路径越界穿越（`../../`）：进行路径规范化并强制校验是否落于工作区内。

#### 【DoD 验证命令】

```bash
pytest plugins/quench-dev-tasks/server/tests/test_project_config.py -k "governance_scope" -v
```

---

### 任务 3 ⬜ 待确认 — 跨开发工具（Cursor / Claude Code / Git Hooks）适配抽象层设计

#### 【涉及文件】

```
[NEW] plugins/quench-dev-tasks/server/adapters/base_adapter.py
[NEW] plugins/quench-dev-tasks/server/adapters/antigravity_adapter.py
[NEW] plugins/quench-dev-tasks/server/adapters/cursor_claude_adapter.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_adapters.py
```

#### 【缺陷根因与修改目标】

根因：当前 `file_scope_guard.py` 与 `conversationId` 绑定较深，直接解析 Antigravity IDE 的 Hook 报文。在向开源生态发布时，面对不支持 PreToolUse Hook 的工具（如 Cursor、Windsurf）或机制不同的工具（如 Claude Code Pre-tool hooks、Git Pre-commit hooks），需要有一套优雅的解耦与降级抽象，否则外部开发者难以直接接入。
目标：设计适配器模式（Adapter Pattern），将“环境与会话感知”、“决策动作输出（allow/deny/ask）”抽象为标准接口。针对 Antigravity 输出专有 Hook 报文；针对 Cursor/Claude Code/标准命令行输出适配 CLI 提示或 Git 校验报告。

#### 【目标签名与类型契约】

```python
class EnvironmentAdapter(ABC):
    @abstractmethod
    def extract_session_id(self, context_input: Any) -> Optional[str]:
        """从客户端上下文中提取会话唯一标识符"""

    @abstractmethod
    def format_decision(self, decision: str, reason: str) -> dict | str:
        """根据客户端类型格式化输出决策（如 Antigravity JSON 字典，或 Git hook 退出码）"""

class AntigravityAdapter(EnvironmentAdapter): ...
class GenericCLIAdapter(EnvironmentAdapter): ...
```

#### 【分步改造指引】

1. 创建 `server/adapters/` 目录与 `base_adapter.py`，定义通用环境上下文与决策输出契约。
2. 将当前 `file_scope_guard.py` 的 Antigravity 解析逻辑迁移至 `antigravity_adapter.py`。
3. 实现 `GenericCLIAdapter`，当通过标准终端或 Git Hook 调用时，根据返回值直接映射为 exit code 0 / 1，并打印清晰的人类可读指引。
4. 编写 `test_adapters.py` 验证不同环境下的行为表现与无缝降级。

#### 【防御与边缘校验】

- 无法识别的客户端环境：默认安全降级至 Generic 模式，避免崩溃阻断。
- 缺失会话 ID 时：降级至工作区或 Git 分支级别的安全租约，并在日志中输出友好的引导说明。

#### 【DoD 验证命令】

```bash
pytest plugins/quench-dev-tasks/server/tests/ -v
```
