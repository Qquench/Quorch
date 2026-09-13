# 2026-09-13_fix_external_hooks_and_diagnostics 开发任务单

> **执行模型须知**
> - 严格按照每条任务的【分步改造指引】顺序执行
> - 不得修改任务未涉及的文件
> - 保留所有现有注释和文档字符串（除非明确要求修改）
> - **改逻辑必加单测断言**：在测试目录追加断言，杜绝回归
> - 每完成一条任务，更新其状态为 `🔨 执行中`，完成后更新为 `✔️ 已完成`

- **创建日期**：2026-09-13

---

## 任务清单与状态


### 任务 1.1 ✔️ 已完成 — 脚手架 hooks.json 自动生成、体检健康审计增强与 Windows 引号剥离修复

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/hooks.json.template
[MODIFY] plugins/quench-dev-tasks/scripts/init_project.py
[MODIFY] scripts/install.py
```

#### 【缺陷根因与修改目标】

根因：
1. **外部项目 Hook 注册穿透失效**：Antigravity IDE 仅从工作区根目录 (`<workspace>/.agents/hooks.json`) 加载生命周期 Hook，不会从 `plugins.json` 引用的外部插件目录穿透加载。而 `init_project.py` 从未生成目标项目的 `.agents/hooks.json`，导致外部业务项目（如 JJW_MES）无物理 Hook 文件，FileGuard 完全失效。
2. **体检诊断存在盲区**：`diagnose_environment()` 返回字典不含 `has_hooks_json` / `hooks_json_valid` 字段，在 Hook 完全缺失的情况下依然汇报"完全就绪"，形成假阳性体检报告。
3. **Windows cmd.exe /c 引号剥离（Quote Stripping）**：`hooks.json.template` 渲染后的命令格式为 `"\"<python>\" \"<script>\""` ——在 JSON 层面这是一个以 `"` 开头、以 `"` 结尾的字符串值。当 Antigravity 在 Windows 下通过 `cmd.exe /c <command>` 执行此字符串时，`cmd.exe` 会自动剥除整行首尾配对的双引号，导致参数解析崩溃（如 `python.exe" "script.py` → 闪退），Hook 静默失效。

目标：
1. 在 `hooks.json.template` 中预设 Windows 平台引号保护占位符，渲染器（`install.py` / `init_project.py`）在 Windows 平台输出最外层包裹保护引号的命令格式；
2. 在 `init_project.py` 的 `init_project()` 函数中增加基于模板的 `.agents/hooks.json` 动态渲染与写入能力，支持 `--force` 覆盖；
3. 在 `install.py --project` 流程中联动调用，确保新项目接入时闭环生成 `.agents/hooks.json`；
4. 升级 `diagnose_environment()` 返回字典，增加 `has_hooks_json` 和 `hooks_json_valid` 两个诊断维度。

#### 【目标签名与类型契约】

```python
# ── hooks.json.template 渲染后的命令字符串契约 ──
# 非 Windows 平台（Linux / macOS）：
#   "\"<python>\" \"<script>\""
# Windows 平台（cmd.exe /c 安全格式）：
#   "\"\"<python>\" \"<script>\"\""
# JSON 层面的原始值示例（Windows）：
#   "command": "\"\"D:\\venv\\Scripts\\python.exe\" \"D:\\plugins\\...\\file_scope_guard.py\"\""
# cmd.exe /c 接收后剥离最外层引号，剩余部分完整保留：
#   "D:\venv\Scripts\python.exe" "D:\plugins\...\file_scope_guard.py"

# ── diagnose_environment 返回字典新增字段 ──
def diagnose_environment(project_root: str) -> dict:
    """
    返回字典新增键:
        has_hooks_json: bool     # .agents/hooks.json 文件是否物理存在
        hooks_json_valid: bool   # True 当且仅当文件存在 + JSON 格式合法
                                 #   + 内部引用的 Python 和脚本路径均可达
    """

# ── init_project 函数签名保持不变，内部新增 hooks.json 生成逻辑 ──
def init_project(project_root: str, project_name: str | None = None, force: bool = False) -> None:
    """新增行为：在 .agents/ 下基于 hooks.json.template 动态渲染并写入 hooks.json。
    - force=False 且已存在时：跳过，输出提示信息；
    - force=True 且已存在时：覆盖并输出警告。
    渲染时自动探测 Python 可执行路径，并根据 sys.platform 决定是否施加 Windows 引号保护。
    """
```

#### 【分步改造指引】

1. **修改 `hooks.json.template`**：
   - 将两处 `command` 值中的占位符格式从 `\"{{PYTHON_EXECUTABLE}}\" \"{{...SCRIPT_PATH}}\"` 改为 `{{QUOTE_WRAP_OPEN}}\"{{PYTHON_EXECUTABLE}}\" \"{{...SCRIPT_PATH}}\"{{QUOTE_WRAP_CLOSE}}`，新增 `{{QUOTE_WRAP_OPEN}}` / `{{QUOTE_WRAP_CLOSE}}` 占位符对，由渲染器根据平台替换为 `\"` 或空字符串。

2. **修改 `scripts/install.py` 的 `render_configs()` 函数**：
   - 在渲染 hooks.json 模板时，根据 `sys.platform == "win32"` 判断：
     - Windows：`QUOTE_WRAP_OPEN` → `\"`（JSON 转义后为 `\\\"`），`QUOTE_WRAP_CLOSE` → `\"`；
     - 非 Windows：`QUOTE_WRAP_OPEN` / `QUOTE_WRAP_CLOSE` → 空字符串。
   - 确保渲染后仍通过 `json.loads()` 合法性校验。

3. **修改 `scripts/init_project.py`**：
   - 3a. 在文件头部新增 `_render_hooks_json(project_root: str, force: bool) -> None` 辅助函数：
     - 定位 `hooks.json.template`（与现有模板定位逻辑一致，位于 `plugin_dir/hooks.json.template`）；
     - 调用 `detect_python_executable()` 探测 Python 路径（复用 `install.py` 的同名函数逻辑或内联等价实现）；
     - 计算 `file_scope_guard.py` 和 `context_injector.py` 的绝对路径；
     - 执行模板占位符替换，包含平台感知的 `QUOTE_WRAP_OPEN/CLOSE` 逻辑；
     - 写入目标 `<project_root>/.agents/hooks.json`，遵循 `force` 语义。
   - 3b. 在 `init_project()` 函数的步骤 4（创建 quench_stack.yaml）之后调用 `_render_hooks_json()`。
   - 3c. 升级 `diagnose_environment()` 返回字典：
     - 新增 `has_hooks_json: bool`：检查 `<project_root>/.agents/hooks.json` 文件是否存在；
     - 新增 `hooks_json_valid: bool`：文件存在时尝试 `json.load()` 校验 JSON 合法性，然后提取 `command` 字段中的可执行路径（Python + 脚本），逐一检查 `os.path.isfile()` 可达性；
     - 文件缺失 / JSON 损坏 / 路径不可达时均向 `issues` 列表追加精准诊断消息。
   - 3d. 升级 `print_diagnostic_report()`：新增 hooks.json 体检行的格式化输出。
   - 3e. `--force` 参数的 `help` 文案更新，声明同时覆盖 `quench_stack.yaml` 和 `hooks.json`。

4. **适配 `scripts/install.py --project` 分支**：
   - 在 `main()` 函数的 `args.project` 分支中，将调用 `init_project.py` 的子进程命令追加 `--force` 标志（仅在主安装流程语境下默认强制刷新 hooks），确保一键接入时闭环生成最新的 `.agents/hooks.json`。

#### 【防御与边缘校验】

- **Windows cmd.exe 双引号剥离全防御**：最终渲染的 command 字符串在 Windows 下必须以 `""` 开头、`""` 结尾（JSON 层面为 `\"\"...\"\"`），无论路径是否包含空格均能通过 `cmd.exe /c` 正确执行。
- **JSON 格式合法性写入前校验**：`_render_hooks_json()` 写入前必须通过 `json.loads()` 验证，拒绝写入格式损坏的 hooks.json。
- **路径反斜杠安全转义**：所有 Windows 路径在 JSON 模板替换时必须通过 `json.dumps(path)[1:-1]`（即 `json_escape_path()`）转义，杜绝原始 `\` 破坏 JSON。
- **幂等安全**：非 `--force` 模式下检测到已存在的 `.agents/hooks.json` 必须跳过写入并输出提示，严禁静默覆盖；`--force` 模式下输出覆盖警告后再写入。
- **路径解析兼容性**：所有文件路径定位使用 `os.path.abspath()` + `os.path.normpath()` 转换为平台原生格式，杜绝相对路径歧义。
- **diagnose 分支完备性**：`hooks_json_valid` 的判定必须覆盖三个否定分支——文件不存在（`has_hooks_json=False`）、文件存在但 JSON 损坏、文件存在且 JSON 合法但内部引用路径不可达。

#### 【DoD 验证命令】
```bash
d:\Work\Quench\quorch\venv\Scripts\python plugins/quench-dev-tasks/scripts/init_project.py --check d:\Work\Quench\quorch
d:\Work\Quench\quorch\venv\Scripts\python scripts/install.py --check
```

---

### 任务 1.2 ✔️ 已完成 — 补齐脚手架与体检单元测试及同步文档变更

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_init_project.py
[MODIFY] plugins/quench-dev-tasks/scripts/quench-init.ps1
[MODIFY] CHANGELOG.md
```

#### 【缺陷根因与修改目标】

根因：现有 `test_init_project.py` 共 6 个测试用例，覆盖了 `init_project()` 的基础流程与 `diagnose_environment()` 的 Git / quench_stack / plugins_json 分支，但完全不涉及 hooks.json 自动生成行为和 Windows 引号防护逻辑的正确性校验。`quench-init.ps1` 的参数文档亦未体现 hooks.json 相关变更。

目标：
1. 在 `test_init_project.py` 中新增至少 5 个针对性测试用例，完整覆盖 hooks.json 生成、`--force` 覆盖、`diagnose_environment` 四分支诊断、以及 Windows 引号格式校验；
2. 更新 `quench-init.ps1` 的 `.DESCRIPTION` 文档段与参数提示，反映 hooks.json 自动生成能力；
3. 在 `CHANGELOG.md` 中记录本次修复条目。

#### 【目标签名与类型契约】

```python
# 新增测试函数签名清单（test_init_project.py）
def test_init_project_generates_hooks_json(tmp_path): ...
def test_init_project_hooks_json_idempotent_skip(tmp_path): ...
def test_init_project_hooks_json_force_overwrite(tmp_path): ...
def test_diagnose_hooks_json_branches(tmp_path): ...
def test_hooks_json_windows_quote_wrapping(tmp_path): ...
```

#### 【分步改造指引】

1. **在 `test_init_project.py` 中新增 hooks.json 生成测试**（`test_init_project_generates_hooks_json`）：
   - 调用 `init_project()` 后断言 `<project>/.agents/hooks.json` 存在；
   - 解析 JSON 并断言 `quench-file-guard` 和 `quench-context-injector` 键存在；
   - 断言 `command` 字段中包含有效的 Python 可执行路径子串。

2. **新增幂等跳过测试**（`test_init_project_hooks_json_idempotent_skip`）：
   - 先运行 `init_project()`，手动修改 hooks.json 内容（写入标记值）；
   - 再次运行 `init_project(force=False)`，断言标记值保留未被覆盖；
   - 断言 stdout 包含"跳过"提示。

3. **新增 `--force` 覆盖测试**（`test_init_project_hooks_json_force_overwrite`）：
   - 先运行 `init_project()`，再运行 `init_project(force=True)`；
   - 断言 hooks.json 被刷新（可通过文件修改时间或内容哈希对比）；
   - 断言 stdout 包含"覆盖"警告。

4. **新增 `diagnose_environment` 四分支覆盖测试**（`test_diagnose_hooks_json_branches`）：
   - 分支 A：hooks.json 不存在 → `has_hooks_json=False`, `hooks_json_valid=False`, issues 中包含缺失提示；
   - 分支 B：hooks.json 存在但内容为非法 JSON → `has_hooks_json=True`, `hooks_json_valid=False`, issues 中包含损坏提示；
   - 分支 C：hooks.json 合法但内部引用的 Python/脚本路径不存在 → `has_hooks_json=True`, `hooks_json_valid=False`, issues 中包含路径失效提示；
   - 分支 D：hooks.json 合法且路径均可达 → `has_hooks_json=True`, `hooks_json_valid=True`, 无 hooks 相关 issues。

5. **新增 Windows 引号格式校验测试**（`test_hooks_json_windows_quote_wrapping`）：
   - 使用 `unittest.mock.patch("sys.platform", "win32")` 模拟 Windows 环境；
   - 调用渲染逻辑后，断言 command 字符串以 `""` 开头、以 `""` 结尾（即 JSON 反序列化后首字符为 `"`、末字符为 `"`）；
   - 使用 `patch("sys.platform", "linux")` 时，断言不包含外层保护引号。

6. **更新 `quench-init.ps1`**：
   - 在 `.DESCRIPTION` 段追加 hooks.json 自动生成的说明；
   - 在 `$Force` 参数注释中声明同时覆盖 hooks.json。

7. **在 `CHANGELOG.md` 的 `[Unreleased]` 段中追加**：
   ```
   - YYYY-MM-DD fix(scaffolding): 修复外部项目 hooks.json 缺失导致 FileGuard 失效、体检假阳性、Windows cmd.exe /c 引号剥离导致 Hook 闪退
   ```

#### 【防御与边缘校验】

- 所有测试用例使用 `tmp_path` fixture 隔离文件系统环境，杜绝全局污染和跨用例干扰。
- `test_diagnose_hooks_json_branches` 覆盖正常、缺失、JSON 损坏、路径失效共 4 个分支，保证 `diagnose_environment()` 的诊断完备性。
- Windows 引号测试通过 `mock.patch` 模拟平台而非依赖实际运行系统，确保 CI 跨平台可执行。
- hooks.json 内容校验使用 `json.load()` 反序列化后逐字段断言，而非字符串匹配，避免空白差异导致的脆弱断言。

#### 【DoD 验证命令】
```bash
d:\Work\Quench\quorch\venv\Scripts\pytest plugins/quench-dev-tasks/server/tests/test_init_project.py -v
d:\Work\Quench\quorch\venv\Scripts\pytest plugins/quench-dev-tasks/server/tests -v
```

---
