# Quench DevTasks Plugin 全量开发任务单

> **执行模型须知**
> - 本任务单涵盖一个完整的 Antigravity IDE Plugin 从零构建
> - **设计参考文档**：执行前必须先阅读 [dev_tasks_mcp_specification.md](file:///D:/Work/Quench/MCP/dev_tasks_mcp_specification.md) 建立设计上下文
> - **Plugin 规范参考**：Antigravity Plugin 的目录结构、hooks.json 契约、mcp_config.json 格式见 [agy-customizations SKILL](file:///C:/Users/asus/.gemini/antigravity-ide/builtin/skills/agy-customizations/SKILL.md) 及其 `docs/` 子目录
> - 严格按照每条任务的【分步改造指引】顺序执行
> - 不得修改任务未涉及的文件
> - 每完成一条任务，在其状态标记处更新为 `🔨 执行中`，完成后更新为 `✔️ 已完成`
> - 遇到指引不明确的情况，停止并说明问题，不要猜测

**Plugin 根路径**：`D:\Work\Quench\MCP\plugins\quench-dev-tasks\`
（下文以 `$PLUGIN` 指代此路径）

---

## Phase 1: 基础骨架（模块间无依赖，可按顺序执行）

---

### 任务 1.1 ✔️ 已完成 — Plugin 目录骨架与构建配置

#### 【涉及文件】

```
[NEW] $PLUGIN\plugin.json
[NEW] $PLUGIN\mcp_config.json
[NEW] $PLUGIN\server\pyproject.toml
[NEW] $PLUGIN\server\requirements.txt
```

#### 【缺陷根因与修改目标】

根因：Plugin 项目尚未创建，Antigravity IDE 无法发现和加载工具。
目标：建立符合 Antigravity Plugin 规范的目录结构与构建配置，使 IDE 可通过 `plugins.json` 注册后自动加载。

#### 【目标签名与类型契约】

无接口变更，纯配置文件创建。

#### 【分步改造指引】

1. 创建 Plugin 完整目录树：`server/`、`server/hooks/`、`server/tests/`、`rules/`、`skills/dev-tasks-workflow/`、`skills/dev-tasks-review/`、`agents/opus_reviewer/`、`scripts/`、`templates/`

2. 创建 `plugin.json`：name=`"quench-dev-tasks"`，version=`"0.1.0"`，description 写明"双模型开发任务治理工具"

3. 创建 `mcp_config.json`：
   ```json
   {"mcpServers": {"quench-dev-tasks": {
     "command": "python",
     "args": ["$PLUGIN\\server\\server.py"]}}}
   ```
   注意：`args` 中必须使用**实际绝对路径**，不要写 `$PLUGIN`

4. 创建 `server/pyproject.toml`：声明 `requires-python = ">=3.11"`，依赖 `fastmcp>=2.0`、`pyyaml>=6.0`、`filelock>=3.0`

5. 创建 `server/requirements.txt` 与 pyproject.toml 依赖保持一致

#### 【防御与边缘校验】

- `mcp_config.json` 中 `args` 路径必须是反斜杠转义的 Windows 绝对路径
- `plugin.json` 中 `name` 字段必须是小写+连字符格式

#### 【DoD 验证命令】

```bash
python -c "import json; json.load(open(r'D:\Work\Quench\MCP\plugins\quench-dev-tasks\plugin.json'))"
python -c "import json; json.load(open(r'D:\Work\Quench\MCP\plugins\quench-dev-tasks\mcp_config.json'))"
```

---

### 任务 1.2 ✔️ 已完成 — 项目配置加载器与配置模板

#### 【涉及文件】

```
[NEW] $PLUGIN\server\project_config.py
[NEW] $PLUGIN\templates\quench_stack.yaml
```

#### 【缺陷根因与修改目标】

根因：MCP 工具需要知道各 Quench 项目的特定路径（任务目录、测试器、CHANGELOG 位置等），否则工具只能硬编码路径。
目标：从各项目根目录的 `.agents/quench_stack.yaml` 加载项目特定配置，支持跨项目复用。

#### 【目标签名与类型契约】

```python
@dataclass
class QuenchStackConfig:
    project_name: str
    dev_tasks_dir: str       # 相对于 workspace root
    archive_dir: str
    test_runner: str | None
    test_dir: str | None
    changelog_path: str
    architecture_doc: str | None
    constraints: list[str]   # 项目边界约束文本

def load_project_config(workspace_root: str) -> QuenchStackConfig:
    """从 workspace_root/.agents/quench_stack.yaml 加载配置。"""
```

#### 【分步改造指引】

1. 定义 `QuenchStackConfig` dataclass，所有路径字段存储**相对路径**

2. 实现 `load_project_config(workspace_root)`：
   # yaml_path = workspace_root / ".agents" / "quench_stack.yaml"
   # if not exists → raise FileNotFoundError with clear message
   # parse yaml → validate required fields → return QuenchStackConfig

3. 添加 `resolve_path(config, field_name)` 辅助函数，将相对路径拼接为绝对路径

4. 创建 `templates/quench_stack.yaml` 模板文件，包含所有字段及注释说明。以示例工程为实例值填写

#### 【防御与边缘校验】

- `.agents/quench_stack.yaml` 不存在：抛出明确异常，提示运行 `init_project.py`
- YAML 解析失败（格式错误）：捕获 `yaml.YAMLError`，返回行号级别的错误信息
- 必填字段缺失（如 `project_name`、`dev_tasks_dir`）：逐字段校验并列出缺失项
- 路径字段含绝对路径时：发出警告但不拒绝（用户可能有特殊需求）

#### 【DoD 验证命令】

```bash
cd $PLUGIN\server
python -c "from project_config import load_project_config; c = load_project_config(r'D:\path\to\target_project'); print(c)"
# 前置条件：需先在目标项目创建 .agents/quench_stack.yaml（从 templates/ 复制并填写）
```

---

### 任务 1.3 ✔️ 已完成 — Markdown 任务文件解析器与状态机引擎

#### 【涉及文件】

```
[NEW] $PLUGIN\server\state_machine.py
```

#### 【缺陷根因与修改目标】

根因：任务状态（⬜/✅/🔨/✔️/⏭️/🔄）存储在 Markdown 文件的标题行中，需要可靠的解析和原子化状态转换。
目标：实现 Markdown 任务文件的解析、状态查询与状态转换，带文件锁防止并发损坏。

#### 【目标签名与类型契约】

```python
@dataclass
class TaskItem:
    id: str              # 如 "1.1"
    title: str           # 标题文本
    status: str          # "✅ 已确认" | "✅ 已确认" | ...
    line_number: int     # 在文件中的行号（用于原地更新）

def parse_task_file(filepath: str) -> list[TaskItem]:
    """解析 Markdown 任务文件，提取所有任务条目及其状态。"""

def transition_task(filepath: str, task_id: str, new_status: str) -> TaskItem:
    """原子化状态转换：读取→校验合法性→写回。带 filelock。"""

def get_status_summary(filepath: str) -> dict[str, int]:
    """返回各状态计数，如 {"✅ 已确认": 3, "✅ 已确认": 2, ...}。"""
```

#### 【分步改造指引】

1. 定义状态常量和合法转换映射表：
   ```python
   VALID_TRANSITIONS = {
       "✅ 已确认": ["✅ 已确认", "⏭️ 跳过"],
       "✅ 已确认": ["🔨 执行中", "✅ 已确认"],
       # ...完整映射
   }
   ```

2. 实现 `parse_task_file`：用正则匹配 `### 任务 X.X <emoji> <status> — <title>` 格式的标题行，提取 id、状态、标题、行号

3. 实现 `transition_task`：使用 `filelock.FileLock(filepath + ".lock")` 获取排他锁 → 读文件 → 校验当前状态是否允许转换 → 替换行 → 写回文件

4. 实现 `get_status_summary`：调用 `parse_task_file` 后按状态分组计数

#### 【防御与边缘校验】

- 非法状态转换（如 ⬜ 直接到 🔨）：抛出 `InvalidTransitionError` 并列出合法路径
- 任务 ID 不存在：抛出 `TaskNotFoundError`
- 文件被外部删除或重命名（锁获取后文件消失）：检测并抛出明确异常
- Markdown 格式不符合预期（标题行解析失败）：跳过无法解析的行，在返回中附加 warning
- 文件锁超时（其他进程长期持有）：设置 5 秒超时，超时后抛出异常

#### 【DoD 验证命令】

```bash
cd $PLUGIN\server
python -m pytest tests/test_state_machine.py -v
```

需新增测试文件 `tests/test_state_machine.py`，覆盖：
- 解析包含多种状态的示例 Markdown 文件
- 合法转换成功
- 非法转换被拒绝
- 文件锁互斥测试

---

### 任务 1.4 ✔️ 已完成 — 六大字段 Schema 校验器

#### 【涉及文件】

```
[NEW] $PLUGIN\server\schema_validator.py
```

#### 【缺陷根因与修改目标】

根因：Opus 生成的任务指引可能遗漏必填字段或违反粒度规则，需要在 `dev_tasks_propose` 工具中进行结构化校验。
目标：实现六大字段的完整性校验、粒度检查和内容质量预警。

#### 【目标签名与类型契约】

```python
@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]     # 硬性错误（必须修正）
    warnings: list[str]   # 软性警告（建议优化）

def validate_task_schema(task: dict) -> ValidationResult:
    """校验单条任务的六大字段完整性与内容质量。"""
```

#### 【分步改造指引】

1. 定义六大字段的 key 名与必填性：
   `affected_files`（必填）、`root_cause_and_goal`（必填）、`type_contracts`（必填，可为"无"）、`steps`（必填）、`defensive_checks`（必填，可为"无"）、`dod_commands`（必填）

2. 实现字段存在性检查：缺失必填字段 → error

3. 实现粒度检查：`affected_files` 中 `[MODIFY]` 类型超过 3 个 → warning（`TaskGranularityWarning`）

4. 实现内容质量检查：`steps` 中连续代码行超过 15 行 → warning（建议浓缩为伪代码）

#### 【防御与边缘校验】

- `affected_files` 为空数组 vs 缺失字段：区分处理，空数组也视为 error
- `steps` 不是数组而是纯字符串：尝试按换行分割，附加 warning
- 无特殊边缘条件的字段（如 `type_contracts` 内容为"无"）：不做深度校验，通过

#### 【DoD 验证命令】

```bash
cd $PLUGIN\server
python -m pytest tests/test_schema_validator.py -v
```

需新增测试文件，覆盖：完整合法输入通过、缺失必填字段被拒、粒度超限触发 warning

---

## Phase 2: MCP Tool 实现（依赖 Phase 1 的三个核心模块）

---

### 任务 2.1 ✔️ 已完成 — MCP Server 入口 + `dev_tasks_status` + `dev_tasks_propose`

#### 【涉及文件】

```
[NEW] $PLUGIN\server\server.py
```

#### 【缺陷根因与修改目标】

根因：MCP 工具尚未实现，模型无法通过工具接口管理开发任务。
目标：创建 FastMCP Server 入口，实现最核心的两个工具——状态查询与任务提议。

#### 【目标签名与类型契约】

```python
@mcp.tool()
def dev_tasks_status(workspace_root: str) -> dict:
    """返回 {files: [{name, path, summary: {status: count}}], active_task: {...} | None}"""

@mcp.tool()
def dev_tasks_propose(workspace_root: str, task_file_name: str,
                      tasks: list[dict]) -> dict:
    """创建/追加任务单。tasks 中每项必须符合六大字段 Schema。
    返回 {file_path, created_count, warnings: [...]}"""
```

#### 【分步改造指引】

1. 创建 `server.py`，初始化 `FastMCP("quench-dev-tasks")`

2. 实现 `dev_tasks_status`：
   # load_project_config → 获取 dev_tasks_dir
   # glob 所有 .md（排除 README.md 和 archive/）
   # 对每个文件调用 parse_task_file → 汇总状态
   # 识别 🔨 执行中 的任务作为 active_task

3. 实现 `dev_tasks_propose`：
   # load_project_config → 获取 dev_tasks_dir
   # 对每条 task 调用 validate_task_schema → 收集 errors/warnings
   # 有 error → 拒绝并返回错误列表
   # 全部通过 → 生成/追加 Markdown 文件（调用内部 _render_task_markdown）

4. 实现 `_render_task_markdown(task: dict) -> str`：将六大字段 dict 渲染为符合格式的 Markdown 文本段

5. 底部添加 `if __name__ == "__main__": mcp.run()`

#### 【防御与边缘校验】

- `workspace_root` 不存在或不是目录：返回明确错误
- `dev_tasks_dir` 目录不存在：自动创建（`os.makedirs(exist_ok=True)`）
- `task_file_name` 不符合 `YYYY-MM-DD_<desc>.md` 格式：返回命名规范提示
- 目标文件已存在：追加模式（append），不覆盖

#### 【DoD 验证命令】

```bash
cd $PLUGIN\server
pip install -r requirements.txt
python server.py
# 在另一个终端测试 MCP 连接（或通过 Antigravity IDE 调用 dev_tasks_status）
```

---

### 任务 2.2 ✔️ 已完成 — `dev_tasks_confirm` + `dev_tasks_checkout`

#### 【涉及文件】

```
[MODIFY] $PLUGIN\server\server.py
```

#### 【缺陷根因与修改目标】

根因：业主确认和 Flash 检出任务的流程尚未工具化，状态推进依赖手动编辑。
目标：实现 confirm（推进确认/跳过/撤回）和 checkout（检出下一个已确认任务）两个工具。

#### 【目标签名与类型契约】

```python
@mcp.tool()
def dev_tasks_confirm(workspace_root: str, task_file: str,
                      task_ids: list[str], action: str) -> dict:
    """action: 'confirm' | 'skip' | 'revoke'
    返回 {updated: [{id, old_status, new_status}], errors: [...]}"""

@mcp.tool()
def dev_tasks_checkout(workspace_root: str) -> dict:
    """返回 {task_id, task_file, title, affected_files, steps,
             defensive_checks, dod_commands} | {error: "无可用任务"}"""
```

#### 【分步改造指引】

1. 实现 `dev_tasks_confirm`：
   # action → 映射目标状态：confirm→✅, skip→⏭️, revoke→⬜
   # 遍历 task_ids → 逐个调用 transition_task
   # 收集成功/失败结果

2. 实现 `dev_tasks_checkout`：
   # 扫描所有任务文件 → 找第一个 ✅ 已确认 的任务
   # 调用 transition_task 将其标记为 🔨 执行中
   # 解析该任务的完整六大字段内容并返回

3. `dev_tasks_checkout` 需要实现 `_extract_task_detail(filepath, task_id) -> dict`：从 Markdown 中提取指定任务的六大字段详细内容（非仅标题行，而是完整段落）

#### 【防御与边缘校验】

- `confirm` 批量操作中部分失败：返回成功列表和失败列表，不因单条失败中断全部
- `checkout` 找不到 ✅ 任务：返回 error 消息而非抛出异常
- `checkout` 时已有 🔨 执行中的任务：返回 warning 提示存在未完成任务，但仍允许检出新任务
- `revoke` 操作仅允许从 ✅ 回退到 ⬜：其他状态的撤回被拒绝

#### 【DoD 验证命令】

```bash
cd $PLUGIN\server
python -m pytest tests/test_server_confirm_checkout.py -v
```

测试覆盖：confirm 批量成功、confirm 非法状态被拒、checkout 返回正确任务、checkout 空队列返回 error

---

### 任务 2.3 ✔️ 已完成 — `dev_tasks_complete`（含 git diff 单测审计）

#### 【涉及文件】

```
[MODIFY] $PLUGIN\server\server.py
```

#### 【缺陷根因与修改目标】

根因：Flash 完成任务后需要提交完成报告，且必须校验是否真正添加了单测断言（Mandatory Assertion Rule）。
目标：实现 complete 工具，含 git diff 审计和 DoD 证据验收。

#### 【目标签名与类型契约】

```python
@mcp.tool()
def dev_tasks_complete(workspace_root: str, task_file: str,
                       task_id: str, dod_output: str,
                       test_evidence: str) -> dict:
    """返回 {status: 'completed' | 'rejected',
             reason: str, audit: {test_files_changed: [...], assertions_found: bool}}"""
```

#### 【分步改造指引】

1. 实现 `_audit_test_changes(workspace_root, config)` 辅助函数：
   # 执行 subprocess: git diff --name-only HEAD
   # 过滤出 config.test_dir 下的文件变更
   # 在变更文件内容中用正则搜索 assert / def test_ 关键字

2. 实现 `dev_tasks_complete` 主逻辑：
   # 解析目标任务 → 检查当前状态是否为 🔨
   # 调用 _audit_test_changes → 判断是否涉及业务逻辑变更
   # 涉及业务逻辑且无测试变更 → 返回 rejected
   # 通过 → 调用 transition_task 标记为 ✔️

3. 业务逻辑判断标准：任务的 `affected_files` 中含 `[MODIFY]` 且不全是配置文件/文档文件

#### 【防御与边缘校验】

- 项目不在 git 仓库中（`git diff` 失败）：降级为不审计，附加 warning
- `test_evidence` 为空字符串：如果审计通过可接受；如果审计未通过则 rejected
- 任务纯粹是文档/配置修改（无业务逻辑）：跳过单测审计
- `git diff` 输出为空（未提交改动）：提示 Flash 先 `git add` 变更文件

#### 【DoD 验证命令】

```bash
cd $PLUGIN\server
python -m pytest tests/test_server_complete.py -v
```

测试覆盖：有测试变更时通过、无测试变更时拒绝、非 git 仓库降级处理

---

### 任务 2.4 ✔️ 已完成 — `dev_tasks_escalate` + `dev_tasks_archive` + CHANGELOG 写入

#### 【涉及文件】

```
[MODIFY] $PLUGIN\server\server.py
[NEW]    $PLUGIN\server\changelog_writer.py
```

#### 【缺陷根因与修改目标】

根因：Flash 需要上报复杂问题给 Opus，且完成的任务单需要归档并同步 CHANGELOG。
目标：实现 escalate（标记升级审查）和 archive（归档 + CHANGELOG 写入）两个工具。

#### 【目标签名与类型契约】

```python
# server.py
@mcp.tool()
def dev_tasks_escalate(workspace_root: str, task_file: str,
                       task_id: str, reason: str,
                       context_files: list[str]) -> dict:
    """返回 {status: 'escalated', suggested_context: [...], prompt_hint: str}"""

@mcp.tool()
def dev_tasks_archive(workspace_root: str, task_file: str) -> dict:
    """返回 {archived_to: str, changelog_updated: bool, summary: str}"""

# changelog_writer.py
def append_changelog_entry(changelog_path: str, task_file: str,
                           completed_tasks: list[TaskItem]) -> None:
    """在 CHANGELOG.md 顶部插入本次任务单的摘要。"""
```

#### 【分步改造指引】

1. 实现 `dev_tasks_escalate`：
   # 不做状态转换（保持 🔨），仅返回建议的 subagent 调用上下文
   # context_files 列表裁剪：每个文件只取前 200 行
   # 返回 prompt_hint 供模型构造 subagent 调用参数

2. 实现 `changelog_writer.py` 的 `append_changelog_entry`：
   # 读取现有 CHANGELOG.md → 在第一个 `## ` 标题前插入新条目
   # 格式：`## [YYYY-MM-DD] <task_file_name>`，下列已完成任务标题

3. 实现 `dev_tasks_archive`：
   # 校验前置条件：所有任务均为 ✔️ 或 ⏭️
   # 调用 append_changelog_entry
   # 移动文件到 archive/ 目录

#### 【防御与边缘校验】

- `archive` 时仍有未闭环任务：拒绝归档，列出未完成的任务
- `CHANGELOG.md` 不存在：自动创建，写入标准头部
- `archive/` 目录不存在：自动创建
- `escalate` 时 `context_files` 中包含不存在的文件：跳过并 warning
- 移动文件时目标路径已存在同名文件：追加时间戳后缀避免覆盖

#### 【DoD 验证命令】

```bash
cd $PLUGIN\server
python -m pytest tests/test_server_escalate_archive.py tests/test_changelog_writer.py -v
```

---

## Phase 3: 执行纪律层（依赖 Phase 2 的状态机查询能力）

---

### 任务 3.1 ✔️ 已完成 — Hooks 拦截层（文件范围守卫 + 上下文注入）

#### 【涉及文件】

```
[NEW] $PLUGIN\hooks.json
[NEW] $PLUGIN\server\hooks\file_scope_guard.py
[NEW] $PLUGIN\server\hooks\context_injector.py
```

#### 【缺陷根因与修改目标】

根因：模型可能修改任务范围外的文件、或忘记查看当前任务状态，纯 system prompt 约束不够可靠。
目标：通过 Hooks 机制实现真正的物理拦截（PreToolUse）和自动上下文注入（PreInvocation）。

#### 【目标签名与类型契约】

无 Python 接口变更。Hook 脚本遵循 Antigravity Hooks I/O 契约：
- `file_scope_guard.py`：stdin 接收 `{toolCall: {name, args}, workspacePaths, ...}`，stdout 输出 `{decision, reason}`
- `context_injector.py`：stdin 接收 `{invocationNum, workspacePaths, ...}`，stdout 输出 `{injectSteps: [{ephemeralMessage}]}`

#### 【分步改造指引】

1. 创建 `hooks.json`，注册两个 Hook：
   # file_scope_guard: PreToolUse, matcher = "replace_file_content|multi_replace_file_content|write_to_file"
   # context_injector: PreInvocation（无 matcher，全局触发）
   # command 指向对应 Python 脚本的绝对路径

2. 实现 `file_scope_guard.py`：
   # 读 stdin JSON → 提取 TargetFile
   # 从 workspacePaths[0] 加载当前 🔨 任务的 affected_files
   # 不在范围内 → 输出 {"decision": "ask", "reason": "..."}
   # 在范围内 或 无活跃任务 → 输出 {"decision": "allow"}

3. 实现 `context_injector.py`：
   # 读 stdin JSON → 从 workspacePaths[0] 获取任务状态摘要
   # 有活跃任务 → 输出 ephemeralMessage 包含当前任务 ID 和标题
   # 无任务 → 输出空 {}

#### 【防御与边缘校验】

- Hook 脚本异常时必须输出合法 JSON（`{"decision": "allow"}`），否则 IDE 会阻塞
- `workspacePaths` 为空数组：直接 allow，不做任何检查
- 项目无 `.agents/quench_stack.yaml`（非 Quench 项目）：静默 allow，不干预
- Hook 超时（hooks.json 中设置 5 秒）：脚本内部不做耗时操作

#### 【DoD 验证命令】

```bash
# 验证 hooks.json JSON 语法
python -c "import json; json.load(open(r'$PLUGIN\hooks.json'))"

# 模拟 file_scope_guard 输入
echo '{"toolCall":{"name":"replace_file_content","args":{"TargetFile":"D:\\\\path\\\\to\\\\target_project\\\\backend\\\\main.py"}},"workspacePaths":["D:\\\\path\\\\to\\\\target_project"]}' | python $PLUGIN\server\hooks\file_scope_guard.py
```

---

### 任务 3.2 ✔️ 已完成 — Rules（常驻行为约束）+ Skills（工作流指南）

#### 【涉及文件】

```
[NEW] $PLUGIN\rules\dev-tasks-discipline.md
[NEW] $PLUGIN\skills\dev-tasks-workflow\SKILL.md
[NEW] $PLUGIN\skills\dev-tasks-review\SKILL.md
```

#### 【缺陷根因与修改目标】

根因：模型行为约束不能完全依赖 MCP 工具拦截，需要 system prompt 级别的常驻纪律注入和按需加载的工作流指南。
目标：编写 Rules（始终注入 system prompt）和 Skills（按需激活的详细工作流手册）。

#### 【目标签名与类型契约】

无代码接口。纯 Markdown 文件，遵循 Antigravity Rules/Skills 格式规范。

#### 【分步改造指引】

1. 创建 `rules/dev-tasks-discipline.md`——常驻规则，内容覆盖：
   # 审查阶段纪律：不修改源码、先读文档、区分问题与偏好、尊重项目定位
   # 执行阶段纪律：按指引顺序、不越界修改、改逻辑必加单测
   # 状态机纪律：必须通过 MCP Tool 推进状态，不手动编辑任务文件

2. 创建 `skills/dev-tasks-workflow/SKILL.md`——frontmatter `name: dev-tasks-workflow`，description 说明触发场景。内容覆盖：
   # 会话启动协议（调用 dev_tasks_status → 判断状态 → 决定动作）
   # 任务六大字段编写规范（每个字段的格式要求和示例）
   # 任务粒度原则

3. 创建 `skills/dev-tasks-review/SKILL.md`——frontmatter `name: dev-tasks-review`。内容覆盖：
   # 审查行为规则（原 README §7 的完整展开）
   # 质量弹性分级（类型定义放宽、实现逻辑 ≤5 行、防御校验不限）
   # 任务交付格式示例

#### 【防御与边缘校验】

- Skills 的 SKILL.md 必须有正确的 YAML frontmatter（`name` + `description` 字段），否则不会被 IDE 发现
- Rules 文件不需要 frontmatter，直接写 Markdown 内容
- 内容中引用的 MCP Tool 名称必须与 server.py 中注册的名称完全一致

#### 【DoD 验证命令】

人工检查清单：
1. 在 Antigravity IDE 中打开 Quench 项目，确认 `dev-tasks-workflow` 和 `dev-tasks-review` 出现在 Skills 列表中
2. 确认 Rules 内容被注入到模型上下文（在对话中让模型复述当前生效的规则）

---

### 任务 3.3 ✔️ 已完成 — Opus 审查 Subagent + 项目初始化脚本

#### 【涉及文件】

```
[NEW] $PLUGIN\agents\opus_reviewer\agent.md
[NEW] $PLUGIN\scripts\init_project.py
```

#### 【缺陷根因与修改目标】

根因：Flash 遇到复杂架构问题时需要委托 Opus 深度审查（通过 subagent 机制），且新项目接入需要手动创建多个配置文件。
目标：定义 Opus 审查 subagent，并提供一键初始化脚本简化新项目接入。

#### 【目标签名与类型契约】

```python
# init_project.py
def init_project(project_root: str, project_name: str | None = None) -> None:
    """在 project_root 创建 .agents/plugins.json 和 .agents/quench_stack.yaml 模板。"""
```

#### 【分步改造指引】

1. 创建 `agents/opus_reviewer/agent.md`，定义 subagent 角色：
   # 职责：接收上下文后进行深度架构分析，通过 dev_tasks_propose 生成任务单
   # 约束：只产出任务单，不修改源码；遇多方案列选项供业主选择
   # 工作完成后立即结束

2. 实现 `init_project.py` 主函数：
   # 参数解析：project_root（必填）、project_name（可选，默认用目录名）
   # 创建 .agents/ 目录
   # 写入 plugins.json（指向 D:\Work\Quench\MCP\plugins）
   # 从 templates/quench_stack.yaml 复制模板到 .agents/quench_stack.yaml
   # 替换模板中的 project_name 占位符
   # 创建 docs/dev_tasks/ 和 docs/dev_tasks/archive/ 目录

3. 添加 `if __name__ == "__main__"` 入口，支持命令行调用：
   `python init_project.py <project_root> [--name <project_name>]`

#### 【防御与边缘校验】

- `.agents/` 目录已存在：不覆盖，仅补充缺失文件，已存在的文件跳过并提示
- `plugins.json` 已存在且已包含 quench-dev-tasks 路径：跳过，打印"已配置"
- `project_root` 不存在：报错退出，不自动创建项目根目录
- 模板文件 `templates/quench_stack.yaml` 不存在：报错并提示 Plugin 安装不完整

#### 【DoD 验证命令】

```bash
# 测试初始化（使用临时目录）
python $PLUGIN\scripts\init_project.py D:\Work\Quench\test_project --name "TestProject"
dir D:\Work\Quench\test_project\.agents\
type D:\Work\Quench\test_project\.agents\plugins.json
type D:\Work\Quench\test_project\.agents\quench_stack.yaml
# 验证后清理测试目录
rmdir /s /q D:\Work\Quench\test_project
```

---

## 依赖关系与执行顺序

```
Phase 1（基础骨架）：
  1.1 目录骨架 ──┐
  1.2 配置加载器 ─┼──→ Phase 2 全部依赖这三个模块
  1.3 状态机引擎 ─┤
  1.4 Schema 校验 ─┘

Phase 2（MCP Tools）：
  2.1 status + propose ──→ 2.2 confirm + checkout ──→ 2.3 complete ──→ 2.4 escalate + archive

Phase 3（执行纪律层）：
  3.1 Hooks ──┐
  3.2 Rules  ─┼── 可并行，但建议在 Phase 2 基本可用后再做
  3.3 Subagent ┘
```
