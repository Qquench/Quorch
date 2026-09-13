# Quench DevTasks MCP — 双模型开发任务治理套件 (Quench DevTasks Orchestrator)

> 本目录为 **Quench 标的体系** 下专用于双模型开发任务治理、代码越界拦截与流程自动化的 MCP 服务与 Antigravity IDE Plugin 根目录（插件标识：`quench-dev-tasks`）。独立于 Quench 体系后续可能衍生的其他领域 MCP（如工业 PLC 通信、CAD 数据等）。

---

## 一、 核心文档

- 📄 **[dev_tasks_mcp_specification.md](file:///D:/Work/Quench/MCP/dev_tasks_mcp_specification.md)**:
  架构设计与详细规范说明书（设计参考，非直接执行文件）
- 📋 **[docs/dev_tasks/](file:///D:/Work/Quench/MCP/docs/dev_tasks/)**:
  开发任务单目录（Opus → Flash 工作流）
- 📝 **[CHANGELOG.md](file:///D:/Work/Quench/MCP/CHANGELOG.md)**:
  版本更新日志与已完成架构演进历史归档
- 🌐 **[OPEN_SOURCE_RELEASE_GUIDE.md](file:///D:/Work/Quench/MCP/OPEN_SOURCE_RELEASE_GUIDE.md)**:
  开源发布备忘录与微调指南（实战跑通后对外发布到 GitHub 时的参考操作手册）
- 🚀 **[future_roadmap/](file:///D:/Work/Quench/MCP/future_roadmap/)**:
  未来演进路线与架构方案收纳（含基于独立 API 的全自动 Subagent 委派与代码库动态探查规划）

---

## 二、 目录结构

```
D:\Work\Quench\MCP\
├── README.md                              # [当前文件] 项目导航
├── CHANGELOG.md                           # ★ 版本更新日志与历史归档
├── OPEN_SOURCE_RELEASE_GUIDE.md           # ★ 开源发布备忘录与微调指南（待实战跑通后使用）
├── future_roadmap\                        # ★ 未来演进路线与架构方案收纳
├── dev_tasks_mcp_specification.md         # 架构设计规范（参考文档）
├── docs\dev_tasks\                        # 开发任务管理（双模型工作流）
│   ├── README.md                          # 任务管理规则
│   ├── archive\                           # ★ 已闭环任务单归档目录
│   └── YYYY-MM-DD_<desc>.md              # 活跃任务单
│
└── plugins\
    └── quench-dev-tasks\                  # ★ Antigravity IDE Plugin 本体
        ├── plugin.json                    # Plugin 清单
        ├── mcp_config.json                # MCP Server 启动配置
        ├── hooks.json                     # 生命周期拦截钩子
        ├── rules\                         # 常驻行为约束（注入 system prompt）
        │   └── dev-tasks-discipline.md
        ├── skills\                        # 按需工作流指南
        │   ├── dev-tasks-workflow\SKILL.md
        │   └── dev-tasks-review\SKILL.md
        ├── agents\                        # Subagent 定义
        │   └── opus_reviewer\agent.md
        ├── scripts\                       # 辅助脚本
        │   └── init_project.py            # 新项目初始化
        ├── templates\                     # 配置模板
        │   └── quench_stack.yaml          # 项目配置模板
        └── server\                        # MCP Server 实现
            ├── server.py                  # FastMCP 入口（7 个 Tool）
            ├── state_machine.py           # 任务状态机引擎
            ├── schema_validator.py        # 六大字段 Schema 校验
            ├── project_config.py          # 项目配置加载器
            ├── changelog_writer.py        # CHANGELOG 增量写入
            ├── hooks\                     # Hook 脚本
            │   ├── file_scope_guard.py    # PreToolUse: 文件修改范围守卫
            │   └── context_injector.py    # PreInvocation: 任务状态注入
            ├── tests\                     # 单元测试
            ├── requirements.txt
            └── pyproject.toml
```

---

## 三、 接入方式

### 对 Quench 项目的接入

每个 Quench 项目只需在根目录创建两个文件：

```
<project_root>\.agents\
├── plugins.json          # 指向本 Plugin（固定 3 行）
└── quench_stack.yaml     # 项目特定配置
```

或使用初始化脚本一键生成：
```powershell
python D:\Work\Quench\MCP\plugins\quench-dev-tasks\scripts\init_project.py <project_root>
```

### 隔离性

本 Plugin **不安装在全局 `~/.gemini/config/`**，仅通过各 Quench 项目的 `.agents/plugins.json` 显式注册，非 Quench 项目完全不受影响。

---

## 四、 ⚠️ 关键环境排错与 MCP 解释器约束 (Prerequisites)

在引入或迁移本插件前，必须确保 Antigravity IDE 能正常通过具备 `fastmcp>=2.0` 的 Python 解释器拉起 MCP 服务：
1. **解释器绝对路径**：`plugins/quench-dev-tasks/mcp_config.json` 中的 `command` 必须显式指向已安装依赖的虚拟环境 Python（如 `D:\Work\Quench\MCP\venv\Scripts\python.exe`），严禁使用系统全局未安装依赖的裸 `python` 命令，否则 IDE Language Server 启动子进程时将因 `ModuleNotFoundError` 静默失败导致治理工具失联；
2. **环境验证命令**：
   ```powershell
   D:\Work\Quench\MCP\venv\Scripts\python.exe -c "import fastmcp, filelock, yaml; print('MCP Environment OK!')"
   ```
3. **状态守卫防线**：`file_scope_guard.py` 已内置任务单状态物理拦截，任何 Agent 尝试将状态修改为已确认均必须经过用户弹窗明确确认，新生成任务强制从【待确认】开始。
