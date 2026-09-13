# Quench MCP 任务治理引擎深化与跨开发工具适配架构审查任务单

> **审查与执行模型须知**
> - 本任务单用于对近期在 Quench MCP 中落地的一系列重大架构特性（三层旁路治理体系、物理会话锁、双轨生产代码边界划分引擎、开源跨工具适配体系）进行**工程留痕与深度架构审查**。
> - **设计参考文档**：
>   - [dev_tasks_mcp_specification.md](file:///D:/Work/Quench/MCP/dev_tasks_mcp_specification.md)
>   - [rules/dev-tasks-discipline.md](file:///D:/Work/Quench/MCP/plugins/quench-dev-tasks/rules/dev-tasks-discipline.md)
>   - [OPEN_SOURCE_RELEASE_GUIDE.md](file:///D:/Work/Quench/MCP/OPEN_SOURCE_RELEASE_GUIDE.md)
>   - [architecture_review_report.md](file:///C:/Users/asus/.gemini/antigravity-ide/brain/4b138e9a-d661-4e38-b0ff-dfe8f07cb4ee/architecture_review_report.md)（2026-09-13 架构审查报告）
> - **审查状态**：本任务单已通过高阶架构审查模型（Reviewer）于 2026-09-13 完成系统性诊断与修订，所有任务已纳入审查发现的改进项。
> - **改逻辑必加单测断言**：在测试目录追加断言，杜绝回归。
> - **建议执行顺序**：任务 1 → 任务 2 → 任务 3 → 任务 4（任务 1 是安全基石，修复并发竞态隐患，阻塞后续所有依赖文件锁的功能扩展）

---

## 阶段规划概览

| 任务编号 | 任务名称 | 当前状态 | 关注维度 |
| :--- | :--- | :---: | :--- |
| 任务 1 | 三层快速旁路与物理会话锁安全审查与防御加固 | ✅ 已确认 | 安全性、防越权、会话隔离、时区一致性 |
| 任务 2 | 双轨管控边界判定引擎与多语言仓库启发式算法调优 | ✅ 已确认 | 准确率、误报率、异构语言兼容、开源路径清洁 |
| 任务 3 | 跨开发工具环境适配器抽象层设计 | ✅ 已确认 | 开源架构解耦、客户端降级容错、生命周期分离 |
| 任务 4 | Git Pre-commit Guard 物理硬防线独立脚本 | ✅ 已确认 | 零依赖独立运行、双拦截避免、跨工具兜底 |

---

### 任务 1 ✅ 已确认 — 三层快速旁路与物理会话锁安全审查与防御加固

#### 【涉及文件】

```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/state_machine.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_tools.py
```

#### 【缺陷根因与修改目标】

根因：当前已落地物理会话锁（绑定 `conversationId`）与 4 小时租期，但存在以下已确认的工程缺陷：
1. **时区致命隐患**：`server.py` 的 `dev_tasks_set_bypass`（L801）与 `file_scope_guard.py` 的 `is_session_bypass_matched`（L264）均使用 naive `datetime.now()` 生成/校验时间戳。若系统时区在会话期间变更（跨时区笔记本、远程桌面），或 ISO 字符串意外携带时区后缀，`fromisoformat()` 返回 aware datetime 与 naive datetime 比较将直接抛 `TypeError`。
2. **旁路文件无 FileLock 保护**：`file_scope_guard.py` 的 `.quench_bypass.json` 读取-判断-删除链路无排他锁，高频并发 Tool 调用时可能产生瞬态安全穿透（一个 Hook 读到旧数据判有效放行，另一个同时判失效执行删除）。
3. **旁路文件写入非原子**：`server.py` 的 `dev_tasks_set_bypass` 直接 `open("w")` 写入 bypass 文件，进程被强杀可产生半截 JSON。
4. **`session_id` 输入未净化**：Agent 可构造超长或含特殊字符的 `session_id`，导致 JSON 文件膨胀或路径注入。
5. **state_machine.py 写回非原子**：`transition_task` 的锁内写回（L186-L187）直接 `open("w")`，强杀可产生半截文件。
6. **缺少 typing 导入**：`file_scope_guard.py` 使用了 `Optional` 和 `List` 类型注解但未从 `typing` 导入。

目标：统一为 UTC aware datetime，为 bypass 文件读写引入 FileLock，全部文件写入改为 tempfile + `os.replace` 原子模式，对 session_id 做 UUID 正则白名单校验与长度上限，补全类型导入，并为所有 Hook 决策引入结构化日志审计轨迹。

#### 【目标签名与类型契约】

```python
import re
import tempfile
from typing import Optional, List, Tuple
from datetime import datetime, timezone

# === file_scope_guard.py 新增/修改 ===

SESSION_ID_PATTERN = re.compile(r"^[a-f0-9\-]{1,128}$", re.IGNORECASE)

def verify_session_integrity(
    bypass_data: dict, incoming_conversation_id: Optional[str]
) -> Tuple[bool, str]:
    """
    校验会话旁路完整性与租约状态。
    统一使用 UTC aware datetime 进行时间比较。
    返回: (is_valid, reject_reason)
    """

def safe_clean_corrupted_bypass(bypass_path: str) -> None:
    """原子化清理或重命名已失效/损坏的会话旁路文件，带 FileLock 保护。"""

# === server.py 修改 ===

def _atomic_write_json(filepath: str, data: dict) -> None:
    """使用 tempfile + os.replace 原子写入 JSON 文件。"""

def _validate_session_id(session_id: Optional[str]) -> Optional[str]:
    """校验 session_id 格式（UUID 正则白名单，最长 128 字符），返回净化后的值或 None。"""

# === state_machine.py 修改 ===
# transition_task 内部文件写回改为 tempfile + os.replace 原子模式
```

#### 【分步改造指引】

1. **统一 UTC 时区处理**：
   - 在 `server.py` 的 `dev_tasks_set_bypass` 中将 `datetime.datetime.now()` 替换为 `datetime.now(timezone.utc)`（涉及 L801 创建时间与过期时间的生成）；
   - 在 `server.py` 的 `dev_tasks_status` 中将过期检查（L222）同步改为 UTC 比较；
   - 在 `file_scope_guard.py` 的 `is_session_bypass_matched` 中将 `datetime.datetime.now()` 替换为 `datetime.now(timezone.utc)`，并对 `fromisoformat` 解析结果做 aware/naive 兼容处理（若解析结果为 naive，视为 UTC 补齐 `tzinfo`）。
2. **为旁路文件读写引入 FileLock**：
   - 在 `file_scope_guard.py` 的 `is_session_bypass_matched` 中，将 bypass 文件的读取、校验、删除操作包裹进 `FileLock`（锁文件路径：`bypass_file + ".lock"`），防止并发 Hook 实例间的读写竞态。
3. **原子化所有文件写入**：
   - 在 `server.py` 中新增 `_atomic_write_json` 辅助函数，使用 `tempfile.NamedTemporaryFile(delete=False)` 写入临时文件后调用 `os.replace()` 原子替换；
   - 将 `dev_tasks_set_bypass` 的 bypass 文件写入（L818-L819）改用 `_atomic_write_json`；
   - 在 `state_machine.py` 的 `transition_task` 中，将锁内的文件写回（L186-L187）改为 `tempfile` + `os.replace` 原子模式。
4. **session_id 输入净化与 reason 长度限制**：
   - 在 `server.py` 新增 `_validate_session_id` 函数，使用 `SESSION_ID_PATTERN` 正则校验格式，拒绝超长或含非法字符的输入；
   - 对 `reason` 字段增加上限限制（不超过 500 字符，超出部分截断并在返回中 warning）；
   - 在 `dev_tasks_set_bypass` 入口处调用净化函数。
5. **补全 typing 导入**：
   - 在 `file_scope_guard.py` 文件顶部添加 `from typing import Optional, List`。
6. **扩充单元测试**：
   - 在 `test_file_scope_guard.py` 中新增并发竞态模拟测试（使用 `threading` 模拟多 Hook 实例并发读写 bypass 文件）；
   - 新增畸形 JSON bypass 文件自愈测试（创建半截 JSON 文件，验证 Hook 不崩溃并自动清理）；
   - 新增时区混合比较测试（验证 aware 与 naive datetime 不会引发 TypeError）；
   - 在 `test_server_tools.py` 中新增 session_id 非法输入拒绝测试（超长字符串、特殊字符、SQL 注入尝试）。

#### 【防御与边缘校验】

- **锁文件写入中途进程被强杀**：使用 `tempfile.NamedTemporaryFile(delete=False, dir=same_directory)` + `os.replace()` 原子替换，确保目标文件要么是旧版完整内容、要么是新版完整内容，杜绝半截文件。
- **FileLock 死锁防御**：所有 `FileLock` 调用统一设置 `timeout=5.0`，超时后抛异常而非无限等待。Hook 的 except 兜底确保 IDE 流程不死锁。
- **租约时间戳时区异常**：生成端与校验端统一使用 `datetime.now(timezone.utc)`；解析 ISO 字符串时，若结果为 naive datetime，显式附加 `replace(tzinfo=timezone.utc)` 防止 `TypeError`。
- **session_id 伪造攻击**：正则白名单 `^[a-f0-9\-]{1,128}$` 严格限定 UUID 格式与长度，拒绝一切不符合格式的输入。
- **reason 字段注入**：截断至 500 字符上限，且 JSON 序列化时 `ensure_ascii=False` 已覆盖编码安全。
- **异常兜底不变**：Hook 最外层 `except Exception` 保持 `allow` 放行策略，绝不因 Hook 自身异常阻断 IDE 正常工作流。

#### 【DoD 验证命令】

```bash
pytest plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py -v
pytest plugins/quench-dev-tasks/server/tests/test_server_tools.py -v
pytest plugins/quench-dev-tasks/server/tests/test_state_machine.py -v
```

---

### 任务 2 ✅ 已确认 — 双轨管控边界判定引擎与多语言仓库启发式算法调优

#### 【涉及文件】

```
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_project_config.py
```

#### 【缺陷根因与修改目标】

根因：当前已实现"显式清单（`quench_stack.yaml`）+ 启发式文件后缀兜底"的双轨判定，但存在以下已确认的覆盖度与安全缺陷：
1. **启发式扩展名覆盖不全**：`DEFAULT_UNMANAGED_EXTENSIONS` 缺少 `.sample`、`.example`、`.bak`、`.log`、`.csv`、`.tsv`、`.parquet`、`.lock` 等常见数据/模板/日志后缀，可能在零配置第三方仓库中对这些文件误触拦截。
2. **CRITICAL_CODE_MANIFESTS 不支持变体匹配**：当前为精确文件名集合，无法识别 `docker-compose.override.yml`、`docker-compose.prod.yml`、`tsconfig.*.json` 等构建配置变体。
3. **符号链接穿透漏洞**：`is_path_governed` 使用 `os.path.normpath` 但未解析 symlink，恶意或意外的符号链接可绕过边界判定。
4. **错误消息硬编码本机路径**：`load_project_config` 的 `FileNotFoundError` 消息中硬编码了 `D:\\Work\\Quench\\MCP\\plugins\\...` 绝对路径，开源后暴露开发者本机路径，必须改为 `os.path.dirname(__file__)` 动态拼接。
5. **缺少路径越界穿越防御**：未校验 `target_file` 经规范化后是否仍落于 `workspace_root` 之内，`../../` 可能逃逸。

目标：扩充启发式规则集覆盖面，为构建清单引入 Glob 模式匹配，修复路径硬编码，增加 symlink 解析与越界防御，并通过多语言假阳性率测试验证判定精度。

#### 【目标签名与类型契约】

```python
# === project_config.py 修改 ===

DEFAULT_UNMANAGED_EXTENSIONS = {
    # 文档类
    ".md", ".markdown", ".txt", ".rst", ".adoc",
    # 图片与素材类
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    # 设计图类
    ".drawio", ".puml", ".mermaid",
    # 模板与示例类（新增）
    ".sample", ".example", ".bak",
    # 数据与日志类（新增）
    ".log", ".csv", ".tsv", ".parquet",
    # 锁文件（新增，非代码产物）
    ".lock",
}

CRITICAL_CODE_MANIFEST_PATTERNS: list[str] = [
    # 精确匹配
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum",
    "pom.xml", "build.gradle", "build.gradle.kts",
    # Glob 模式匹配（新增）
    "dockerfile*",
    "docker-compose*.yml", "docker-compose*.yaml",
    "tsconfig*.json",
    ".env",  # .env 本身是高危凭据文件
]

def is_path_governed(self, target_file: str | Path, workspace_root: Optional[Path] = None) -> bool:
    """双轨边界智能仲裁（增强版）：
    0. symlink 解析 + 路径越界防御
    1. 显式清单优先
    2. 目录属性感知
    3. 扩展名与 Glob 特征匹配
    """
```

#### 【分步改造指引】

1. **扩充 `DEFAULT_UNMANAGED_EXTENSIONS`**：在 `project_config.py` 中追加 `.sample`、`.example`、`.bak`、`.log`、`.csv`、`.tsv`、`.parquet`、`.lock` 等后缀。
2. **将 `CRITICAL_CODE_MANIFESTS` 升级为 Glob 模式列表**：从 `set` 改为 `list[str]`（重命名为 `CRITICAL_CODE_MANIFEST_PATTERNS`），在 `is_path_governed` 中使用 `fnmatch.fnmatch(basename, pattern)` 进行匹配，支持 `docker-compose*.yml`、`tsconfig*.json`、`dockerfile*` 等变体。
3. **增加 symlink 解析**：在 `is_path_governed` 入口处调用 `os.path.realpath(target_file)` 解析符号链接真实路径，防止通过 symlink 绕过边界。
4. **增加路径越界防御**：解析后使用 `os.path.commonpath([realpath, workspace_root])` 校验目标路径不逃逸出工作区，若逃逸直接返回 `True`（受管，触发拦截）。
5. **修复错误消息硬编码路径**：将 `load_project_config` 中 `FileNotFoundError` 的 init_project.py 路径改为基于 `os.path.dirname(os.path.abspath(__file__))` 动态拼接（`../scripts/init_project.py` 相对于 server 模块目录）。
6. **扩充测试用例**：在 `test_project_config.py` 中新增：
   - 多语言典型工程结构判定用例（Python Web、Vue/React 前端、Go module、Rust crate、Java Maven）；
   - `.sample`、`.example`、`.log` 等新增后缀的判定验证；
   - `docker-compose.override.yml`、`tsconfig.build.json` 等变体的受管判定；
   - symlink 穿透防御测试（创建指向受管目录的 symlink 文件，验证判定正确）；
   - 路径越界穿越测试（`../../etc/passwd` 类路径，验证被判定为受管/拦截）。

#### 【防御与边缘校验】

- **大小写不敏感文件系统（Windows/macOS）与敏感系统（Linux）的 Glob 差异**：已有 `.lower()` 规范化，确保新增的 Glob 模式匹配同样在 lower 后执行。
- **符号链接循环**：`os.path.realpath` 内部处理循环链接，返回尽可能解析的路径，不会死循环。
- **相对路径越界穿越（`../../`）**：`os.path.realpath` + `os.path.commonpath` 双重防御。若 `commonpath` 抛 `ValueError`（跨驱动器），直接判定为受管。
- **`.lock` 文件分类说明**：`yarn.lock`、`Cargo.lock` 等虽以 `.lock` 结尾，但已在 `CRITICAL_CODE_MANIFEST_PATTERNS` 中精确列出为受管，精确匹配优先级高于扩展名兜底，不会被误放行。
- **`.env` 文件高危处理**：`.env` 本身无扩展名后缀，不会命中 `DEFAULT_UNMANAGED_EXTENSIONS`，同时在 `CRITICAL_CODE_MANIFEST_PATTERNS` 中精确列出，确保受管。`.env.example` 因 `.example` 后缀命中免管扩展名集合，正确放行。

#### 【DoD 验证命令】

```bash
pytest plugins/quench-dev-tasks/server/tests/test_project_config.py -v
```

> **假阳性率验收补充**：执行器应在测试用例中构造至少 5 种典型开源项目目录结构（含 Python、JavaScript、Go、Rust、Java），验证 `is_path_governed` 对生产代码与文档资产的判定准确率，确保误报率（文档被误拦）≤ 5%。

---

### 任务 3 ✅ 已确认 — 跨开发工具环境适配器抽象层设计

#### 【涉及文件】

```
[NEW] plugins/quench-dev-tasks/server/adapters/__init__.py
[NEW] plugins/quench-dev-tasks/server/adapters/base_adapter.py
[NEW] plugins/quench-dev-tasks/server/adapters/antigravity_adapter.py
[NEW] plugins/quench-dev-tasks/server/adapters/cursor_adapter.py
[NEW] plugins/quench-dev-tasks/server/adapters/generic_cli_adapter.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[NEW] plugins/quench-dev-tasks/server/tests/test_adapters.py
```

#### 【缺陷根因与修改目标】

根因：当前 `file_scope_guard.py` 与 Antigravity IDE 的 `conversationId` 绑定较深，直接解析其专有 Hook 报文格式。在向开源生态发布时，面对不支持 PreToolUse Hook 的工具（如 Cursor、Windsurf）或机制不同的工具（如 Claude Code），需要有一套优雅的解耦与降级抽象，否则外部开发者难以直接接入。

审查修订要点（相较原始版本的关键改进）：
1. **生命周期分离**：将"环境检测"（一次性，Server 启动时执行）与"决策格式化"（高频，每次 Hook 拦截时执行）分离为独立的 `EnvironmentDetector` 和 `EnvironmentAdapter`，避免每次拦截都重新做环境探测。
2. **适配器拆分**：原 `cursor_claude_adapter.py` 拆分为 `cursor_adapter.py`（`.cursor/mcp.json` 配置）和 `generic_cli_adapter.py`（Claude Code、Windsurf、裸 Git CLI 等通用终端场景），因两者 MCP 配置格式差异较大。
3. **包结构规范化**：新增 `__init__.py` 确保 `adapters/` 为合法 Python 包。

目标：设计适配器模式（Adapter Pattern），将"环境感知"、"会话 ID 提取"、"决策动作输出（allow/deny/ask）"抽象为标准接口。Antigravity 输出专有 JSON 报文与 Ask Modal；Cursor 输出适配其 Rules 的指引文本；Generic CLI 输出控制台彩色文本与标准退出码。

#### 【目标签名与类型契约】

```python
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional

class EnvironmentType(Enum):
    ANTIGRAVITY = "antigravity"
    CURSOR = "cursor"
    GENERIC_CLI = "generic_cli"

# === base_adapter.py ===

class EnvironmentDetector:
    """环境检测器（一次性调用，结果缓存）"""
    
    @staticmethod
    def detect(context_input: dict) -> EnvironmentType:
        """根据上下文信号判断当前运行环境。
        判断依据：payload 中是否含有 conversationId（Antigravity）、
        .cursor 配置目录是否存在（Cursor）、否则降级为 Generic CLI。
        """

class EnvironmentAdapter(ABC):
    """环境适配器抽象基类（高频调用）"""
    
    @abstractmethod
    def extract_session_id(self, context_input: Any) -> Optional[str]:
        """从客户端上下文中提取会话唯一标识符"""

    @abstractmethod
    def format_decision(self, decision: str, reason: str) -> dict | str:
        """根据客户端类型格式化输出决策"""

    @abstractmethod
    def supports_interactive_ask(self) -> bool:
        """是否支持交互式确认弹窗（仅 Antigravity 支持）"""

# === antigravity_adapter.py ===
class AntigravityAdapter(EnvironmentAdapter):
    """Antigravity IDE 专有适配器：JSON payload + Ask Modal"""

# === cursor_adapter.py ===
class CursorAdapter(EnvironmentAdapter):
    """Cursor IDE 适配器：终端文本输出 + 标准退出码"""

# === generic_cli_adapter.py ===
class GenericCLIAdapter(EnvironmentAdapter):
    """通用命令行适配器：适用于 Claude Code、Windsurf、裸 Git CLI 等"""
```

#### 【分步改造指引】

1. **创建 `server/adapters/` 包结构**：创建 `adapters/__init__.py`（导出 `EnvironmentDetector`、`EnvironmentType`、`EnvironmentAdapter`）和 `base_adapter.py`（定义上述抽象契约）。
2. **实现 `AntigravityAdapter`**：将当前 `file_scope_guard.py` 中的 JSON payload 解析（`conversationId` 提取、`decision: "ask"` 格式化）迁移至 `antigravity_adapter.py`。保持原有行为 100% 兼容。
3. **实现 `CursorAdapter`**：针对 Cursor 环境，`extract_session_id` 从工作区路径或 Git branch 推断会话级标识；`format_decision` 输出为人类可读的终端文本（含 ANSI 颜色）。
4. **实现 `GenericCLIAdapter`**：`extract_session_id` 降级为工作区路径哈希；`format_decision` 映射为 `exit code 0/1` 与 stderr 红字告警。
5. **改造 `file_scope_guard.py` 调用链路**：在 `main()` 入口通过 `EnvironmentDetector.detect(payload)` 确定环境类型，实例化对应 Adapter，后续所有 session_id 提取与决策输出均通过 Adapter 接口调用。确保改造后 Antigravity 环境下的行为与改造前 100% 一致。
6. **编写 `test_adapters.py`**：覆盖三种环境模式的模拟行为：Antigravity JSON 解析、Cursor 终端输出格式、Generic CLI 退出码映射，以及未知环境的安全降级。

#### 【防御与边缘校验】

- **无法识别的客户端环境**：`EnvironmentDetector.detect` 在所有判断条件均未命中时，默认安全降级至 `GENERIC_CLI` 模式，确保系统不崩溃、不阻断。
- **缺失会话 ID 时**：各适配器的 `extract_session_id` 在无法获取标准会话 ID 时，降级至工作区路径或 Git 分支级别的哈希标识作为会话代理键，并在日志中输出友好的引导说明。
- **向后兼容保障**：改造后 Antigravity 环境下的 Hook 输出格式必须与改造前完全一致（JSON `{"decision": "allow/ask/deny", "reason": ...}`），确保 IDE 端无需任何适配。
- **适配器无状态设计**：所有 Adapter 实例应为无状态或仅持有不可变配置，确保在多线程/多进程环境下安全共享。

#### 【DoD 验证命令】

```bash
pytest plugins/quench-dev-tasks/server/tests/test_adapters.py -v
pytest plugins/quench-dev-tasks/server/tests/test_hooks.py -v
```

---

### 任务 4 ✅ 已确认 — Git Pre-commit Guard 物理硬防线独立脚本

#### 【涉及文件】

```
[NEW] plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py
[NEW] plugins/quench-dev-tasks/server/tests/test_pre_commit_guard.py
```

#### 【缺陷根因与修改目标】

根因：在不支持 PreToolUse Hook 的开发工具（如 Cursor、Windsurf、Claude Code）中，代码修改的物理拦截点需从"写文件时"平移至"提交代码时"。阶段三路线图（Epic 3.4）定义了 Git Pre-commit Hook 守护脚本作为物理兜底防线，但当前尚未实现。

审查修订要点（从架构审查中提炼的关键约束）：
1. **零依赖独立运行**：Guard 脚本必须仅使用 Python stdlib（`os`、`sys`、`re`、`json`、`subprocess`、`datetime`），严禁 `import` FastMCP、filelock 或任何第三方库，确保在任意 Python 3.7+ 环境下无需安装依赖即可运行。
2. **双拦截避免**：当用户同时在 Antigravity IDE 环境下安装了 Git Pre-commit Guard 时，Guard 应检测当前是否处于 Antigravity 环境（通过 `.agents/plugins.json` 的 IDE 标识字段），若是则降级为 warning-only 模式（打印但不 `exit 1`），将拦截权交给更早生效的 PreToolUse Hook。
3. **与任务 3 的依赖关系**：本任务不依赖任务 3 的 Adapter 抽象层（Guard 独立解析任务文件），可与任务 3 并行开发。

目标：编写轻量独立的 Git Pre-commit 守卫脚本，在 `git commit` 时校验修改文件是否超出当前活跃任务的【涉及文件】白名单，支持一键安装至目标项目的 `.git/hooks/pre-commit`。

#### 【目标签名与类型契约】

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quench Git Pre-commit Guard — 零依赖独立守卫脚本。
仅使用 Python 标准库，无任何第三方依赖。
"""
import os, sys, re, json, subprocess
from typing import List, Optional, Tuple

def find_active_task(dev_tasks_dir: str) -> Optional[Tuple[str, str, List[str]]]:
    """在 dev_tasks 目录中查找处于 🔨 执行中 的任务。
    返回: (task_id, task_title, allowed_files) 或 None
    直接解析 Markdown 文件，不依赖 MCP Server 或第三方库。
    """

def get_staged_files() -> List[str]:
    """通过 git diff --cached --name-only 获取本次待提交文件列表。"""

def check_violations(
    staged_files: List[str], allowed_files: List[str], workspace_root: str
) -> List[str]:
    """校验是否有超出任务白名单的代码文件。
    返回违规文件列表。免管文件（文档/素材）自动排除。
    """

def is_antigravity_environment(workspace_root: str) -> bool:
    """检测当前是否处于 Antigravity IDE 管控环境。
    若是，Pre-commit Guard 降级为 warning-only 模式。
    """

def main() -> int:
    """入口函数。返回 0 允许提交，返回 1 阻断提交。"""
```

#### 【分步改造指引】

1. **编写 `git_pre_commit_guard.py` 核心逻辑**：
   - 定位工作区根目录（通过 `git rev-parse --show-toplevel`）；
   - 读取 `.agents/quench_stack.yaml` 获取 `dev_tasks_dir` 配置（使用纯 Python 解析 YAML 子集，或 `json`/`re` 提取关键字段，避免依赖 `pyyaml`）；
   - 扫描 `dev_tasks_dir/*.md` 查找 `🔨 执行中` 状态的任务，提取其【涉及文件】白名单；
   - 执行 `git diff --cached --name-only` 获取本次 staged 文件；
   - 逐一比对 staged 文件是否在白名单范围内（复用 `fnmatch` 进行 Glob 匹配）；
   - 自动排除文档/素材类文件（`.md`、`.txt`、`.png` 等，内联一份精简版免管扩展名集合）。
2. **实现双拦截避免逻辑**：
   - 检测 `.agents/plugins.json` 是否存在且包含 `quench-dev-tasks` 插件注册（表明 Antigravity IDE 已接管拦截）；
   - 若处于 Antigravity 环境，改为 `stderr` 输出黄色 WARNING（`⚠️ Antigravity IDE PreToolUse Hook 已接管拦截，Pre-commit Guard 降级为 warning-only`），`exit 0` 放行；
   - 若非 Antigravity 环境（Cursor/CLI），对违规文件 `exit 1` 硬阻断。
3. **实现一键安装功能**：
   - 支持 `python git_pre_commit_guard.py --install [project_path]` 参数；
   - 自动将自身复制（或创建 shim 脚本）到目标项目的 `.git/hooks/pre-commit`；
   - 若已存在 pre-commit hook，提供合并提示而非覆盖。
4. **编写 `test_pre_commit_guard.py`**：
   - 创建临时 Git 仓库与任务文件，模拟 staged 文件校验；
   - 验证白名单内文件放行、白名单外文件拦截；
   - 验证无活跃任务时的行为（warning 但不阻断）；
   - 验证 Antigravity 环境检测与降级逻辑。

#### 【防御与边缘校验】

- **无活跃任务时的行为**：若当前无 `🔨 执行中` 任务，Guard 输出 INFO 提示（`ℹ️ 当前无活跃 Quench 任务，Pre-commit Guard 放行`）并 `exit 0`，不阻断正常提交流程。
- **YAML 解析降级**：由于不依赖 `pyyaml`，对 `quench_stack.yaml` 的读取采用正则提取关键字段（`dev_tasks_dir`）；若提取失败，降级为默认路径 `docs/dev_tasks`。
- **Windows 路径分隔符**：所有路径比较前统一 `replace("\\", "/")`，确保跨平台一致性。
- **非 Git 仓库**：若 `git rev-parse --show-toplevel` 失败（非 Git 仓库），静默 `exit 0` 放行。
- **编码安全**：所有文件读取使用 `encoding="utf-8", errors="ignore"` 防止 GBK/BOM 导致崩溃。
- **脚本自身不需要虚拟环境**：作为 Git Hook 运行时使用系统 Python，不依赖项目的 `.venv`。

#### 【DoD 验证命令】

```bash
pytest plugins/quench-dev-tasks/server/tests/test_pre_commit_guard.py -v
python plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py --help
```

---

## 附录 A：缺陷注册表（Defect Registry）

> 来源：2026-09-13 系统性架构审查。各缺陷已映射至对应任务，执行器在施工时应逐一核验。
> 编码标准（修复模式的通用范式）已提炼至自动加载规则：`rules/coding-standards.md`。

### 🔴 高危

| ID | 缺陷 | 位置 | 归属 |
|:---|:---|:---|:---:|
| D1 | naive datetime 时区隐患（跨时区/远程桌面场景下 aware vs naive 比较抛 TypeError） | `file_scope_guard.py` L264、`server.py` L801 | T1 |
| D4 | 错误消息硬编码本机路径 `D:\Work\Quench\MCP\plugins\...`（开源后暴露） | `project_config.py` L155 | T2 |

### 🟡 中危

| ID | 缺陷 | 位置 | 归属 |
|:---|:---|:---|:---:|
| D2 | bypass 文件读写无 FileLock（并发 Hook 瞬态安全穿透） | `file_scope_guard.py` L242-L277 | T1 |
| D3 | bypass 清理 `os.remove` 在锁外执行（D2 同源） | `file_scope_guard.py` L254-L256 | T1 |
| D5 | bypass 写入非原子（进程强杀产生半截 JSON） | `server.py` L818-L819 | T1 |
| D6 | session_id 未做输入净化（超长/特殊字符导致路径注入或 JSON 膨胀） | `server.py` L807 | T1 |
| D10 | 路径规范化未考虑 symlink 穿透（绕过边界判定） | `project_config.py` L100-L103 | T2 |

### 🟢 低危

| ID | 缺陷 | 位置 | 归属 |
|:---|:---|:---|:---:|
| D7 | reason 字段无最长限制 | `server.py` L778 | T1 |
| D8 | `DEFAULT_UNMANAGED_EXTENSIONS` 覆盖不全（缺 `.sample`/`.bak`/`.log`/`.lock` 等） | `project_config.py` L12-L16 | T2 |
| D9 | `CRITICAL_CODE_MANIFESTS` 不支持 Glob 变体匹配 | `project_config.py` L24-L30 | T2 |

---

## 附录 B：任务依赖关系图

```
任务 1 (并发安全加固) ──→ 任务 2 (边界引擎调优)
         │                        │
         └──→ 任务 3 (适配器抽象层) ←──┘
                                       任务 4 (Git Guard) ← 可与 T3 并行
```

**依赖说明**：
- **T1 → T2**：任务 2 的 symlink 防御需参考任务 1 的 `os.path.realpath` 模式
- **T1 → T3**：任务 3 的适配器需复用任务 1 已加固的 bypass 读写逻辑
- **T2 → T3**：任务 3 的 `EnvironmentDetector` 需调用任务 2 已调优的 `is_path_governed`
- **T3 ⇢ T4**：任务 4 **不依赖** 任务 3 的 Adapter 层（Guard 独立解析任务文件），可并行开发

**推荐执行顺序**：T1 → T2 → T3（+ T4 并行）

---

## 附录 C：Git Pre-commit Guard 零依赖约束清单

### ✅ 允许导入（仅 Python stdlib）

```python
import os, sys, re, json, subprocess, fnmatch, glob
from datetime import datetime
from typing import List, Optional, Tuple
```

### ❌ 严禁导入

```python
import fastmcp       # 第三方 MCP 框架
import filelock      # 第三方文件锁
import yaml          # 第三方 YAML 解析
import pydantic      # 第三方数据校验
from server import * # 项目内部模块
```

### YAML 降级解析模式

由于不依赖 `pyyaml`，对 `quench_stack.yaml` 使用正则提取：

```python
def _extract_yaml_field(content: str, field: str) -> str | None:
    """从 YAML 内容中正则提取单行标量字段值"""
    pattern = re.compile(
        rf"^\s*{re.escape(field)}\s*:\s*['\"]?(.+?)['\"]?\s*$",
        re.MULTILINE
    )
    match = pattern.search(content)
    return match.group(1).strip() if match else None
```

---

## 附录 D：文件修改全景地图

| 文件 | T1 | T2 | T3 | T4 |
|:---|:---:|:---:|:---:|:---:|
| `server/server.py` | ✏️ UTC+原子+净化 | | | |
| `server/state_machine.py` | ✏️ 原子写回 | | | |
| `server/hooks/file_scope_guard.py` | ✏️ FileLock+UTC+typing | | ✏️ Adapter调用链 | |
| `server/project_config.py` | | ✏️ 扩展名+Glob+symlink+硬编码 | | |
| `server/adapters/__init__.py` | | | 🆕 | |
| `server/adapters/base_adapter.py` | | | 🆕 Detector+Adapter | |
| `server/adapters/antigravity_adapter.py` | | | 🆕 | |
| `server/adapters/cursor_adapter.py` | | | 🆕 | |
| `server/adapters/generic_cli_adapter.py` | | | 🆕 | |
| `scripts/git_pre_commit_guard.py` | | | | 🆕 零依赖 |
| `tests/test_file_scope_guard.py` | ✏️ 并发+时区+畸形JSON | | | |
| `tests/test_server_tools.py` | ✏️ session_id拒绝 | | | |
| `tests/test_state_machine.py` | ✏️ 原子写回验证 | | | |
| `tests/test_project_config.py` | | ✏️ 多语言+symlink+越界 | | |
| `tests/test_adapters.py` | | | 🆕 三模式 | |
| `tests/test_pre_commit_guard.py` | | | | 🆕 |

> **图例**：✏️ = 修改现有文件，🆕 = 新建文件

### 必须覆盖的测试场景

| 场景类型 | 测试模式 | 归属 |
|:---|:---|:---:|
| 并发竞态 | `threading.Thread` 模拟多 Hook 并发读写 bypass | T1 |
| 畸形数据自愈 | 半截 JSON / 空文件 / 非 JSON → Hook 不崩溃 | T1 |
| 时区混合 | aware 与 naive ISO 字符串混合比较 | T1 |
| 非法输入拒绝 | 超长 session_id / 特殊字符 / 注入尝试 | T1 |
| 多语言假阳性 | Python/JS/Go/Rust/Java 目录结构判定准确率 | T2 |
| 符号链接穿透 | symlink → 受管目录判定正确 | T2 |
| 路径越界穿越 | `../../etc/passwd` 类路径防御 | T2 |
| 适配器模拟 | Antigravity JSON / Cursor 终端 / Generic CLI 三模式 | T3 |
| 环境降级 | 未知环境 → GenericCLI | T3 |
| 双拦截避免 | Antigravity 环境 → Guard 降级 warning-only | T4 |
| 非 Git 仓库 | Guard 静默放行 | T4 |
