# 阶段一演进：脚手架轻量化、Hook 可观测性与配置版本迁移

> **所属阶段**：Stage 1 — 个人无缝跨项目治理与实战闭环  
> **基线分支**：`feat/stage1-scaffolding-observability-migration`  
> **目标**：补齐阶段一剩余的工程化缺口，实现结构化决策审计日志（可观测性）、配置文件向后兼容平滑自动升级（含模板项目中立化清洗）、以及一键初始化脚手架与环境诊断工具。
> **审查状态**：本任务单已通过高阶架构审查模型于 2026-09-13 完成系统性诊断与修订（审查报告 v2），所有任务已纳入审查发现的改进项。
> **推荐执行顺序**：任务 2 → 任务 1 → 任务 3（任务 2 的模板清洗是任务 3 脚手架初始化的前置条件）

---

### 任务 1 ✔️ 已完成 — Hook 决策日志与可观测性基线 (Epic 1.5)

#### 【涉及文件】

```
[MODIFY] plugins/quench-dev-tasks/server/hooks/file_scope_guard.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[NEW]    plugins/quench-dev-tasks/server/tests/test_observability.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_hooks.py
```

> **审查修订说明**：`test_hooks.py`（13,559 字节）是 `file_scope_guard.py` 最主要的集成测试文件。注入 logger 相关调用后，需确认现有测试不因 logger 初始化产生回归。若 logger 采用 module-level 自动初始化且不变更现有 public API 签名，可将 `test_hooks.py` 的修改范围限定为"验证 logger 不干扰原有行为"。

#### 【缺陷根因与修改目标】

根因：当前整个治理套件缺少结构化日志，`file_scope_guard.py` 中的 `except Exception: pass` 模式导致所有运行期异常被静默吞掉。当开发者或 Agent 遇到非预期的拦截或放行时，无法调取排查线索；同时 `dev_tasks_status` 缺乏对近期拦截历史的观测手段。

目标：
1. 引入标准库 `logging.handlers.RotatingFileHandler`（1MB × 3 轮转），在 `.agents/.quench_hook.log` 记录所有 Hook 触发细节（时间戳、调用工具、目标文件、决策结果 allow/ask/deny、理由及 session_id）；
2. 将所有静默吞错的 `pass` 替换为带有详细上下文的 `logger.warning(...)`，确保异常可追溯且依然维持兜底放行策略（IDE 绝不死锁）；
3. 在 `dev_tasks_status` MCP 工具返回值中增加 `last_hook_log_entries: list[str]` 字段，返回最近 10 条日志摘要。

#### 【目标签名与类型契约】

```python
import logging
import logging.handlers

# === file_scope_guard.py ===

class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Windows 安全轮转：轮转失败时保持当前文件继续写入，不中断日志流。"""
    def doRollover(self):
        try:
            super().doRollover()
        except (PermissionError, OSError):
            # 轮转失败（Windows 多进程竞争），继续使用当前日志文件
            pass

def get_hook_logger(workspace_root: str) -> logging.Logger:
    """初始化并缓存基于 workspace_root/.agents/.quench_hook.log 的轮转日志记录器。
    使用 SafeRotatingFileHandler 保障 Windows 多进程安全。
    若 .agents 目录不可写，降级为 NullHandler（仅在初始化阶段）。
    """

def log_guard_event(
    logger: logging.Logger,
    event_type: str,  # "ALLOW", "DENIED", "ASK_MODAL", "BYPASS_CLEAN", "EXCEPTION"
    target_file: str,
    tool_name: str,
    decision: str,
    reason: str = "",
    session_id: Optional[str] = None,
) -> None:
    """记录结构化 Hook 治理决策事件。"""

# === server.py ===
def _get_recent_hook_logs(workspace_root: str, max_lines: int = 10) -> list[str]:
    """读取 .agents/.quench_hook.log 最近 N 条日志，若不存在返回空列表。
    对最后一行做格式完整性校验，若不完整则跳过返回前 N-1 条。
    """
```

#### 【分步改造指引】

1. **日志记录器初始化**：在 `file_scope_guard.py` 中编写 `SafeRotatingFileHandler` 子类（覆盖 `doRollover` 捕获 `PermissionError`/`OSError`），然后编写 `get_hook_logger`，采用 `SafeRotatingFileHandler(maxBytes=1024*1024, backupCount=3, encoding="utf-8")`，日志文件存放在 `workspace_root/.agents/.quench_hook.log`；
2. **埋点全覆盖**：在静态白名单放行、会话旁路命中与失效清理、双轨边界放行、元数据放行、任务单强守卫拦截、范围外拦截处打点写入标准日志；
3. **异常排查增强**：将所有外层与内层 `except Exception` 增加 `logger.warning("...", exc_info=True)`，随后继续走放行兜底；
4. **状态工具透出**：在 `server.py` 的 `dev_tasks_status` 中读取日志尾部 10 行并放入返回字典。对最后一行做格式完整性校验（因 Hook 子进程可能正在写入），若不完整则跳过；
5. **单元测试编写**：在 `test_observability.py` 中模拟 Hook 调用，断言日志文件正确生成、内容包含决策字段、以及日志轮转与异常追溯机制；
6. **回归验证**：运行 `test_hooks.py` 全量测试确认 logger 注入不影响现有 Hook 行为。

#### 【防御与边缘校验】

- **日志初始化权限异常**（两阶段降级策略）：
  - **初始化阶段**：若 `.agents` 目录写权限受限或文件创建失败，`get_hook_logger` 降级为 `logging.NullHandler`，严禁因打日志失败阻断 Hook 正常工作；
  - **运行期轮转失败**：`SafeRotatingFileHandler.doRollover` 捕获 `PermissionError`/`OSError` 后，**保持当前已打开的文件句柄继续写入**（不轮转、不切换 NullHandler），确保后续日志不丢失；
- **多进程日志切分冲突**：Windows 下多进程（多个 IDE workspace 共享同一 `.agents` 目录）轮转同一文件可能遭遇句柄占用。`SafeRotatingFileHandler` 已覆盖此场景；
- **日志文件体积失控**：严格限制单个文件 1MB、保留 3 个备份，磁盘空间占用上限 ≤ 4MB；
- **跨进程读写时序**：`_get_recent_hook_logs`（MCP Server 进程）读取由 Hook 子进程写入的日志文件，最后一行可能不完整。读取后对末行做格式完整性校验，不完整则丢弃。

#### 【DoD 验证命令】

```bash
pytest plugins/quench-dev-tasks/server/tests/test_observability.py -v
pytest plugins/quench-dev-tasks/server/tests/test_file_scope_guard.py -v
pytest plugins/quench-dev-tasks/server/tests/test_hooks.py -v
```

---

### 任务 2 ✔️ 已完成 — 配置文件版本管理、平滑升级迁移与模板项目中立化 (Epic 1.6)

#### 【涉及文件】

```
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/scripts/init_project.py
[MODIFY] plugins/quench-dev-tasks/templates/quench_stack.yaml
[NEW]    plugins/quench-dev-tasks/server/tests/test_config_migration.py
```

> **审查修订说明**：原任务单遗漏了 `templates/quench_stack.yaml`。`init_project.py` 并非内嵌模板——它从 `templates/quench_stack.yaml` 读取文件内容后复制到目标项目（L96-108）。当前模板硬编码了 JJW_MES 工控项目的私有约束（离线车间网络、双寄存器握手、`ipc_client` 目录等），违反了 Quench 工具项目中立的核心定位。在引入 `schema_version` 前必须先完成模板清洗，否则新初始化的项目将同时携带错误的 v1.0 Schema 和私有约束。

#### 【缺陷根因与修改目标】

根因：
1. `quench_stack.yaml` 经历了 `governance_scope`、`fast_track_rules` 等多轮功能升级，但缺少版本标识机制。早期接入的项目缺少这些新配置块，若直接使用可能无法享受新特性；若强制用户重新生成，会导致开发者自定义的项目字段被冲掉。
2. **模板文件项目中立性缺失**：`templates/quench_stack.yaml` 硬编码了 `project_name: "JJW_MES"`、工控专有约束（`离线车间局域网`、`双寄存器握手`、`SQLite WAL`）、以及 JJW_MES 特有目录结构（`backend/**`、`ipc_client/**`），导致任何新项目初始化后都会被注入不相关的私有内容。

目标：
1. **模板项目中立化清洗**：将 `templates/quench_stack.yaml` 中所有 JJW_MES 私有内容替换为通用范例，确保工具对任何技术栈项目保持中立；
2. 在配置模型与模板中正式引入 `schema_version: "1.0"` 规范；
3. 在 `load_project_config` 中增加无感自动升级机制：读取旧版无版本号配置时，采用**文本级补丁插入**方式自动在文件末尾追加缺失字段，**不做 YAML round-trip 序列化**，确保零注释破坏；
4. 保证迁移过程幂等、原子，不破坏现有注释与自定义业务扩展字段。

#### 【目标签名与类型契约】

```python
# === project_config.py ===
CURRENT_SCHEMA_VERSION = "1.0"

# 缺失字段的默认追加文本块（用于文本级补丁插入，非 YAML 序列化产物）
_DEFAULT_SCHEMA_VERSION_PATCH = '\nschema_version: "1.0"\n'
_DEFAULT_FAST_TRACK_PATCH = """
fast_track_rules:
  allow_untracked_patterns: []
"""

@dataclass
class QuenchStackConfig:
    workspace_root: str
    project_name: str
    schema_version: str = "1.0"
    ...

def migrate_config_if_needed(yaml_path: str, data: dict) -> Tuple[dict, bool]:
    """纯文本级追加缺失字段，零注释破坏。
    读取文件原文本，用正则检测缺失的顶层字段，在文件末尾追加补丁文本块。
    使用 tempfile + os.replace 原子写回。
    返回: (migrated_data, has_changes)
    """
```

#### 【分步改造指引】

1. **模板项目中立化清洗**（前置步骤）：直接编辑 `templates/quench_stack.yaml`，将 JJW_MES 私有内容替换为通用版本：
   - `project_name` 改为占位符 `"__PROJECT_NAME__"`（`init_project.py` 已有正则替换逻辑）；
   - 移除全部工控约束（`离线车间`、`双寄存器`、`SQLite WAL`、`ipc_client` 等），替换为三条普适性工程原则（改逻辑必加测试、接口向后兼容、凭据不硬编码）；
   - `architecture_doc`、`test_dir`、`test_runner` 改为注释状态（可选配置）；
   - `governance_scope` 整体改为注释范例（新项目默认依赖启发式引擎，不强制配置）；
   - 新增 `schema_version: "1.0"` 作为首个正式版本标识；
2. **版本定义**：在 `project_config.py` 声明 `CURRENT_SCHEMA_VERSION = "1.0"`，并在 `QuenchStackConfig` 中增加 `schema_version` 字段；
3. **迁移逻辑实现（文本级补丁插入）**：编写 `migrate_config_if_needed`，读取文件原始文本，用正则（如 `"schema_version" not in raw_text`）检测缺失的顶层字段。对每个缺失字段，将预定义的默认文本块追加到文件末尾。**严禁使用 `yaml.dump()` 写回**——`yaml.safe_load()` 仅用于加载到内存供运行时使用，不参与写回；
4. **原子写回**：使用 `tempfile` + `os.replace` 原子替换 `quench_stack.yaml`，避免半截写损；
5. **模版同步**：确认 `init_project.py` 中的模板读取逻辑（L96-108）引用的是已清洗的 `templates/quench_stack.yaml`，无需额外代码修改；
6. **单元测试编写**：在 `test_config_migration.py` 中：
   - 构造 v0（无版本号、缺字段）YAML，验证加载后自动补齐并正确写盘，且已有的自定义字段完整保留；
   - **注释保留断言**：构造含行内注释的 YAML 文件，迁移后断言注释仍存在于文件中；
   - **模板中立性断言**：验证 `templates/quench_stack.yaml` 不包含 `JJW_MES`、`离线车间`、`双寄存器`、`ipc_client` 等私有关键词。

#### 【防御与边缘校验】

- **YAML 格式损坏防御**：若原文件语法有误（无法解析），立即抛出原有 `ValueError`，严禁用默认配置盲目覆写损坏的文件；
- **空文件防御**：空文件或仅含空白字符的文件视同 YAML 损坏，走 `ValueError` 路径；
- **高版本号不降级**：若现有文件的 `schema_version` 高于 `CURRENT_SCHEMA_VERSION`（如 `"2.0"`），不执行降级，仅输出 warning；
- **只读文件系统**：若由于权限限制写回失败，输出警告但不阻断配置在内存中的生效（降级运行）；
- **向后兼容**：所有老字段读取全部保持 `data.get(field, default)` 默认行为；
- **Windows BOM/GBK 编码容错**：读取 YAML 时统一使用 `encoding="utf-8"`，对 UTF-8 BOM（`\xef\xbb\xbf`）做静默剥离处理。

#### 【DoD 验证命令】

```bash
pytest plugins/quench-dev-tasks/server/tests/test_config_migration.py -v
pytest plugins/quench-dev-tasks/server/tests/test_project_config.py -v
```

---

### 任务 3 ✔️ 已完成 — 全局脚手架轻量化与环境自检优化 (Epic 1.3)

#### 【涉及文件】

```
[MODIFY] plugins/quench-dev-tasks/scripts/init_project.py
[NEW]    plugins/quench-dev-tasks/scripts/quench-init.ps1
[MODIFY] plugins/quench-dev-tasks/server/tests/test_init_project.py
```

#### 【缺陷根因与修改目标】

根因：当前接入新项目必须显式敲击一段冗长的命令（如 `python D:\Work\Quench\MCP\plugins\quench-dev-tasks\scripts\init_project.py ...`），且 `init_project.py` 缺乏项目环境自检，如果目标目录缺少 Git 或 Python 环境不兼容容易导致后续 MCP 静默失败。

目标：
1. 编写独立轻量的 PowerShell 脚本 `scripts/quench-init.ps1`，支持全局配置与无参数自动识别当前目录；
2. 在 `init_project.py` 中增加 `--check` 健康体检模式：自动检测 Git 仓库有效性、Python 虚拟环境与关键依赖（`fastmcp`, `yaml`, `filelock`），并在终端输出友好的自检报告；
3. 优化 `.agents/plugins.json` 写入，确保多次执行完全幂等且格式规范。

#### 【目标签名与类型契约】

```python
# === init_project.py ===
def diagnose_environment(project_root: str) -> dict:
    """全面诊断目标项目的治理环境就绪状态。
    返回结构: {
        "is_git_repo": bool,
        "has_quench_stack": bool,
        "has_plugins_json": bool,
        "python_valid": bool,
        "dependencies_ready": bool,
        "issues": list[str],
        "suggestions": list[str]
    }
    """
```

#### 【分步改造指引】

1. **环境诊断模块编写**：在 `init_project.py` 中实现 `diagnose_environment` 函数。`is_git_repo` 通过 `subprocess.run(["git", "rev-parse", "--is-inside-work-tree"])` 检测，若 `git` 不在 PATH 则在 `issues` 中输出友好提示而非抛异常；
2. **CLI 参数扩展**：新增 `--check` 参数，调用诊断函数并在控制台输出格式化的 ASCII / 颜色体检表；
3. **编写 `quench-init.ps1`**：包装调用逻辑，自动解析脚本所在目录作为插件源，支持直接将函数加载至用户 `$PROFILE`。脚本头部需包含 ExecutionPolicy 运行指引注释（提示用户使用 `powershell -ExecutionPolicy Bypass -File quench-init.ps1`），脚本本身不应调用 `Set-ExecutionPolicy` 以避免全局安全降级；
4. **扩充单元测试**：在 `test_init_project.py` 中测试 `--check` 诊断输出、幂等覆盖与非 Git 目录的友好提示。

#### 【防御与边缘校验】

- **无 Git 仓库初始化**：当在非 Git 目录初始化时，给出友好 Warning 并询问或提示先运行 `git init`，但不强阻断文件生成；
- **已存在配置防止被洗**：当目标已存在 `quench_stack.yaml` 时，除非显式指定 `--force`，否则默认跳过覆盖并建议运行迁移检查（任务 2 的 `migrate_config_if_needed`）；
- **Windows 下 `git` 不在 PATH**：`diagnose_environment` 捕获 `FileNotFoundError` 并在 `issues` 列表中输出 `"git 命令未找到，请安装 Git 或将其添加到系统 PATH"` 友好提示。

#### 【DoD 验证命令】

```bash
pytest plugins/quench-dev-tasks/server/tests/test_init_project.py -v
python plugins/quench-dev-tasks/scripts/init_project.py --check .
```
