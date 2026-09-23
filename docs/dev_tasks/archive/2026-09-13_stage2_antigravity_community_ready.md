# 阶段二演进：Antigravity 社区通用开箱即用与开源准备

> **所属阶段**：Stage 2 — Antigravity Community Out-of-the-Box & Open Source Release  
> **基线规划**：`docs/roadmap/archive/v1.02_antigravity_community_ready.md`  
> **目标**：彻底消除代码库中任何本地绝对路径强绑定，提供跨平台自适应安装与 Pre-flight 预检脚手架，项目配置模板去特定化与逻辑角色模型解耦，并构建专业双语开源社区门面与规范资产。  
> **审查状态**：✅ 已确认（架构复核与决策修订完毕，已全量确认待执行）  
> **推荐执行顺序**：任务 1 → 任务 2 → 任务 3 → 任务 4

---

### 任务 1 ✔️ 已完成 — 消除本地绝对路径与配置模板化 (Epic 2.1)

#### 【涉及文件】

```
[NEW] plugins/quench-dev-tasks/mcp_config.json.template
[NEW] plugins/quench-dev-tasks/hooks.json.template
[MODIFY] .gitignore
[NEW] plugins/quench-dev-tasks/server/tests/test_templates.py
```

#### 【缺陷根因与修改目标】

根因：当前 `plugins/quench-dev-tasks/mcp_config.json` 与 `hooks.json` 强行硬编码了本机绝对路径（如 `D:\\Work\\Quench\\MCP\\venv\\Scripts\\python.exe` 与固定插件路径），导致外部开发者克隆仓库后无法直接使用，且推送到开源平台会暴露本机隐私路径并导致 IDE 报错崩溃。

目标：
1. 将配置提取为标准模板 `mcp_config.json.template` 与 `hooks.json.template`，使用 `{{PYTHON_EXECUTABLE}}`、`{{SERVER_SCRIPT_PATH}}`、`{{FILE_GUARD_SCRIPT_PATH}}`、`{{CONTEXT_INJECTOR_SCRIPT_PATH}}` 占位符；
2. 在 `.gitignore` 中追加过滤本地生成的 `plugins/quench-dev-tasks/mcp_config.json` 与 `plugins/quench-dev-tasks/hooks.json`，防止本地路径被误提交；
3. 编写 `test_templates.py` 严格测试模板文件的合法性（有效 JSON 结构、必要占位符存在性、以及模拟替换后的有效性）。

#### 【目标签名与类型契约】

```json
// plugins/quench-dev-tasks/mcp_config.json.template
{
  "mcpServers": {
    "quench-dev-tasks": {
      "command": "{{PYTHON_EXECUTABLE}}",
      "args": [
        "{{SERVER_SCRIPT_PATH}}"
      ]
    }
  }
}
```

```json
// plugins/quench-dev-tasks/hooks.json.template
{
  "quench-file-guard": {
    "PreToolUse": [
      {
        "matcher": "replace_file_content|multi_replace_file_content|write_to_file",
        "hooks": [
          {
            "type": "command",
            "command": "\"{{PYTHON_EXECUTABLE}}\" \"{{FILE_GUARD_SCRIPT_PATH}}\"",
            "timeout": 5
          }
        ]
      }
    ]
  },
  "quench-context-injector": {
    "PreInvocation": [
      {
        "type": "command",
        "command": "\"{{PYTHON_EXECUTABLE}}\" \"{{CONTEXT_INJECTOR_SCRIPT_PATH}}\"",
        "timeout": 5
      }
    ]
  }
}
```

#### 【分步改造指引】

1. 创建 `plugins/quench-dev-tasks/mcp_config.json.template`，声明 `{{PYTHON_EXECUTABLE}}` 和 `{{SERVER_SCRIPT_PATH}}`；
2. 创建 `plugins/quench-dev-tasks/hooks.json.template`，对包含占位符的命令加双引号包裹以安全支持带空格的安装路径；
3. 修改 `.gitignore`，追加 `plugins/quench-dev-tasks/mcp_config.json` 与 `plugins/quench-dev-tasks/hooks.json`；
4. 编写 `plugins/quench-dev-tasks/server/tests/test_templates.py`，验证模板文件存在、能正常反序列化为 JSON 骨架、包含所有必要占位符，且替换后生成合法的 JSON 配置字典；**必须包含 Windows 反斜杠安全性测试用例**：使用包含 `\Users`、`\Scripts`、`\test` 等 JSON 危险子串的模拟路径（如 `C:\Users\test\venv\Scripts\python.exe`）进行占位符替换，验证替换后仍为合法 JSON；
5. 运行单测确认全部通过。

#### 【防御与边缘校验】

- **路径空格防御**：Hook 执行命令中的解释器路径与脚本路径必须使用双引号包裹，防御路径包含空格（如 `C:\Program Files\...`）导致的命令解析断裂；
- **Windows 反斜杠转义防御**：在测试与渲染引擎中，替换 Windows 路径**必须使用 `json.dumps(path)[1:-1]`** 进行 JSON 安全转义，严禁直接 `str.replace()` 裸反斜杠（`\U`、`\t`、`\S` 等均为非法 JSON 转义序列，会导致生成的配置文件无法解析）；
- **本地会话连续性保障**：在生成模板和更新 `.gitignore` 期间，保留当前正在生效的本地配置文件，确保当前开发进程不失联。

#### 【DoD 验证命令】

```bash
# 请先激活虚拟环境（Windows: .venv\Scripts\activate | Unix: source .venv/bin/activate）
python -m pytest plugins/quench-dev-tasks/server/tests/test_templates.py -v
```

---

### 任务 2 ✔️ 已完成 — 跨平台自适应安装引导脚本与 Pre-flight 安全预检 (Epic 2.2)

#### 【涉及文件】

```
[NEW] scripts/install.py
[NEW] plugins/quench-dev-tasks/server/tests/test_install.py
```

#### 【缺陷根因与修改目标】

根因：从 GitHub 克隆插件的用户需要手动配置环境、解析 Python 路径并编辑 JSON 配置，门槛极高；此外在后续执行目录更名（从 `MCP` 更名为 `quorch`，即 **Qu**ench Dev **Orch**estrator 缩写，项目内部全称保持 `quench-dev-orchestrator`）或路径迁移时缺乏占用检查与配置快照备份，若有 IDE 或后台进程占用文件会导致操作半途崩溃且难以回滚。

目标：
1. 编写根目录 `scripts/install.py`，提供跨平台（Windows / Linux / macOS）一键安装能力；
2. 自动检测或创建 `.venv` 虚拟环境，自动判断平台 Python 可执行路径（Windows `Scripts/python.exe`，Unix `bin/python`）；
3. 检查并安装核心运行时依赖（`fastmcp>=2.0`, `filelock>=3.0`, `pyyaml>=6.0`, `pytest`）；
4. 读取 `.template` 模板文件，自动渲染生成合法的 `mcp_config.json` 与 `hooks.json`；
5. 实现 `--preflight` 预检机制：
   - **句柄占用检测**（主方案）：使用零依赖试探法 `os.rename(dir, dir)` 捕获 `PermissionError`；若运行时检测到 `psutil` 已安装则自动升级为进程级诊断，额外输出占用进程 PID 与名称（不强制依赖 `psutil`）；
   - **MAX_PATH 审计**：在 Windows 上统计路径总长度，>200 字符输出黄色警告，>250 字符输出红色阻断；
   - **备份快照写入**：将当前配置文件内容序列化至 `.agents/.quench_path_backup.json`，快照 Schema 见下方【防御与边缘校验】；
6. 实现 `--rollback` 机制：从 `.agents/.quench_path_backup.json` 读取快照，逐文件覆写恢复（仅恢复快照中记录的文件，不删除快照外的文件）；
7. 编写单元测试 `test_install.py` 覆盖各参数分支与边缘逻辑。

#### 【目标签名与类型契约】

```python
# scripts/install.py
def run_preflight(plugin_dir: str, backup_path: str) -> tuple[bool, list[str]]:
    """执行安装前 Pre-flight 检查：句柄占用、Windows MAX_PATH 长度审计、备份快照创建。"""

def rollback_configuration(plugin_dir: str, backup_path: str) -> bool:
    """从 .agents/.quench_path_backup.json 恢复旧配置文件。"""

def render_configs(plugin_dir: str, python_exe: str) -> tuple[str, str]:
    """根据模板渲染 mcp_config.json 和 hooks.json，返回生成的文件路径。"""

def check_and_install_dependencies(python_exe: str, auto_install: bool = False) -> bool:
    """检查必要依赖，若缺失且指定 auto_install 则通过 pip 安装。"""

def run_smoke_test(plugin_dir: str, python_exe: str) -> bool:
    """执行冒烟测试：尝试导入关键模块并验证环境。"""
```

#### 【分步改造指引】

1. 创建 `scripts/install.py`，实现 CLI 参数解析（`--preflight`, `--rollback`, `--global`, `--project`, `--no-deps`）；
2. 实现 Python 解释器与虚拟环境探测逻辑；
3. 实现 JSON-safe 路径转义替换与配置文件原子写入；
4. 实现 Pre-flight 检查器：
   - 句柄占用检测：主方案 `os.rename(dir, dir)` 试探法，可选 `psutil` 增强（输出占用进程信息）；
   - MAX_PATH 审计与备份快照写入（Schema 见防御校验节）；
5. 实现 Rollback 还原逻辑：解析快照 JSON → 逐文件校验 → 原子覆写恢复；
6. 编写 `plugins/quench-dev-tasks/server/tests/test_install.py` 覆盖各核心功能函数；
7. 运行单测并实际执行 `python scripts/install.py --preflight` 验证。

#### 【防御与边缘校验】

- **写入原子性**：渲染生成配置时先写入临时文件校验有效性后再替换目标文件，杜绝写出一半造成文件损坏；
- **路径反斜杠转义安全**：处理 Windows 路径（`\`）必须使用 `json.dumps(path)[1:-1]`，严禁直接字符串替换导致非法 JSON 转义字符；
- **Rollback 异常防护**：快照不存在或格式异常时输出明确指引，严禁在回滚失败时误删现有文件；
- **MAX_PATH 提前预警**：在 Windows 上当路径长度超过 200 字符时输出明确警告，避免后续操作因超过 260 限制静默失败；
- **Rollback 快照 Schema 规范**：
  ```json
  {
    "snapshot_version": "1.0",
    "created_at": "<ISO 8601 时间戳>",
    "python_executable": "<备份时探测到的 Python 路径>",
    "files": {
      "plugins/quench-dev-tasks/mcp_config.json": "<文件完整内容字符串>",
      "plugins/quench-dev-tasks/hooks.json": "<文件完整内容字符串>"
    }
  }
  ```

#### 【DoD 验证命令】

```bash
# 请先激活虚拟环境（Windows: .venv\Scripts\activate | Unix: source .venv/bin/activate）
python -m pytest plugins/quench-dev-tasks/server/tests/test_install.py -v
python scripts/install.py --preflight
```

#### 【人工联动步骤（任务 1 + 任务 2 全部完成后立即执行）】

> [!IMPORTANT]
> 以下步骤涉及物理文件系统更名与跨仓库操作，必须由用户在终端手动执行，不可由 AI 代理自动完成。
> 仓库文件夹使用简短名称 `quorch`（即 **Qu**ench Dev **Orch**estrator 缩写），便于命令行输入与 `git clone`；项目内部全称保持 `quench-dev-orchestrator` 不变。

0. **Pre-flight 预检**：
   ```powershell
   python scripts/install.py --preflight
   ```
   确认无进程占用、路径长度安全、旧配置已备份至 `.agents/.quench_path_backup.json`。
1. **关闭所有占用会话**：关闭所有打开了 `MCP` 目录的 IDE 窗口、终端会话与后台进程；
2. **执行仓库文件夹重命名**：
   ```powershell
   Rename-Item "D:\Work\Quench\MCP" "quorch"
   ```
3. **在新目录下执行自愈安装**：
   ```powershell
   cd D:\Work\Quench\quorch
   python scripts/install.py
   ```
4. **同步刷新外部下游业务项目插件路径**（防止插件失联）：
   ```powershell
   python plugins/quench-dev-tasks/scripts/init_project.py "<path_to_project>"
   ```
5. **验证 Git Remote**：若 GitHub/GitLab 仓库名同步更名为 `quorch`，需执行：
   ```powershell
   cd D:\Work\Quench\quorch
   git remote set-url origin <new-repo-url>
   ```
6. **验证恢复能力**：若更名后出现异常，可在新目录下执行 `python scripts/install.py --rollback` 恢复配置文件。

---

### 任务 3 ✔️ 已完成 — 项目配置模板去特定化与逻辑角色模型解耦 (Epic 2.3)

#### 【涉及文件】

```
[MODIFY] plugins/quench-dev-tasks/templates/quench_stack.yaml
[MODIFY] plugins/quench-dev-tasks/rules/dev-tasks.md
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md
[MODIFY] plugins/quench-dev-tasks/server/tests/test_config_migration.py
```

#### 【缺陷根因与修改目标】

根因：现有规则文档与模板依然将双模型体系与具体的商业模型代号（如绑定 Opus/Flash 专有名称）混为一谈，不利于不同算力条件或偏好不同模型的社区开发者；同时模板中缺少覆盖 Web 全栈、云原生微服务、CLI 运维工具等常见软件形态的规则参考。

目标：
1. 完善 `templates/quench_stack.yaml`：在注释中补充覆盖 Web 全栈、云原生微服务、CLI 工具、嵌入式 IoT 等典型技术栈的 `constraints` 与 `fast_track_rules` 参考范例；
2. 显式抽象解耦双模型角色：在 `rules/dev-tasks.md` 与 `skills/dev-tasks-review/SKILL.md` 中将模型定义为标准逻辑角色：
   - **Reviewer（架构审查师 / 深度推理模型）**：负责跨模块架构审查、系统性缺陷诊断、复杂冲突仲裁与阶段任务规划；
   - **Runner（日常执行器 / 敏捷模型）**：负责严格按【分步改造指引】开展内敛代码编写、单测补充与 DoD 闭环；
3. 更新 `test_config_migration.py`，确保模板调整后仍然保持项目中立与配置升级安全。

#### 【目标签名与类型契约】

```yaml
# templates/quench_stack.yaml 场景化参考规范
# 技术栈示例 A: Web 全栈 (FastAPI / Spring Boot + React / Vue)
# 技术栈示例 B: 云原生微服务 (Go / Rust / gRPC)
# 技术栈示例 C: CLI 工具与系统运维 (Python / Click / Cobra)
```

#### 【分步改造指引】

1. 修改 `plugins/quench-dev-tasks/templates/quench_stack.yaml`，补充场景化规范注释；
2. 修改 `plugins/quench-dev-tasks/rules/dev-tasks.md`，将具体商业模型名称抽象为通用逻辑角色（Reviewer 与 Runner），支持配置映射；
3. 修改 `plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`，明确审查者的职责边界与模型解耦原则；
4. 运行 `test_config_migration.py` 验证模板合规性。

#### 【防御与边缘校验】

- **YAML 格式安全**：新增的大段注释严禁影响 YAML 解析器正常加载，保持 `schema_version: "1.0"` 稳定；
- **向后兼容性**：不引入破损字段，老项目迁移无需被迫调整已有业务配置。

#### 【DoD 验证命令】

```bash
# 请先激活虚拟环境（Windows: .venv\Scripts\activate | Unix: source .venv/bin/activate）
python -m pytest plugins/quench-dev-tasks/server/tests/test_config_migration.py -v
```

---

### 任务 4 ✔️ 已完成 — 社区门面资产、双语文档与发布走查 (Epic 2.4)

#### 【涉及文件】

```
[MODIFY] README.md
[NEW] README_zh.md
[NEW] CONTRIBUTING.md
[NEW] docs/FAQ.md
[MODIFY] LICENSE
```

#### 【缺陷根因与修改目标】

根因：根目录 `README.md` 缺少面向开源社区的痛点陈述、直观架构图、快速上手引导与双语导航；缺少社区贡献指南 `CONTRIBUTING.md` 与常见环境问题排查清单 `docs/FAQ.md`；需要确认 MPL-2.0 开源许可协议的完整声明。

目标：
1. 重构根目录 `README.md`，采用 English-First 规范，顶部包含中英文切换链接，具备完整的痛点分析、双模型工作流 ASCII 图与快速上手引导；
2. 新增 `README_zh.md`，提供同步的中文完整指南；
3. 新增 `CONTRIBUTING.md`，规范本地环境准备、开发流程、测试验证与 PR 提交标准；
4. 新增 `docs/FAQ.md`，汇总常见问题（FastMCP 环境找不到、Windows 终端编码乱码、Hook 超时、路径超长等）；
5. 校验 `LICENSE` 文件并确认与 MPL-2.0 规范完全一致；
6. 执行全库敏感路径走查，确保零泄漏本机盘符与私有路径。

#### 【目标签名与类型契约】

```markdown
# README.md 顶部导航规范
[English](README.md) | [简体中文](README_zh.md)
```

#### 【分步改造指引】

1. 重写根目录 `README.md`，加入徽章、痛点与快速上手；
2. 编写 `README_zh.md`；
3. 编写 `CONTRIBUTING.md`；
4. 编写 `docs/FAQ.md`；
5. 审查并更新 `LICENSE`；
6. 运行全库全局路径扫描命令确认无任何遗留的硬编码路径。

#### 【防御与边缘校验】

- **链接有效性**：所有文档内的相对文件链接必须真实有效，严禁出现 404 坏链；
- **环境信息泄露防御**：严禁出现开发者本机的具体路径（如 `D:\Work\Quench\MCP`）。

#### 【DoD 验证命令】

```bash
# 全库敏感路径扫描（跨平台通用）
git grep -i "D:\\\\Work\\\\Quench" -- "*.md" || true
git grep -i "D:\\\\Work\\\\Quench" -- "*.py" || true
git grep -i "D:\\\\Work\\\\Quench" -- "*.json" || true

# 请先激活虚拟环境（Windows: .venv\Scripts\activate | Unix: source .venv/bin/activate）
# Windows (PowerShell)
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; python -m pytest plugins/quench-dev-tasks/server/tests -v
# Linux / macOS (bash)
# PYTHONPATH="plugins/quench-dev-tasks/server" python -m pytest plugins/quench-dev-tasks/server/tests -v
```
