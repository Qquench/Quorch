# 常见问题排查与技术问答 (FAQ)

[English](FAQ.md) | [简体中文](FAQ_zh.md)

本文档汇集在安装、配置与使用 **Quench Dev-Orchestrator (`quorch`)** 过程中的常见问题与排错指南。

---

## 目录
1. [MCP 解释器与运行环境问题](#1-mcp-解释器与运行环境问题)
2. [Windows 控制台与乱码问题 (GBK / UTF-8)](#2-windows-控制台与乱码问题-gbk--utf-8)
3. [PreToolUse 拦截弹窗与 Hook 超时](#3-pretooluse-拦截弹窗与-hook-超时)
4. [目录更名与句柄锁定 (PermissionError)](#4-目录更名与句柄锁定-permissionerror)
5. [Windows MAX_PATH 路径长度警告](#5-windows-max_path-路径长度警告)
6. [双模型角色与实际大模型映射](#6-双模型角色与实际大模型映射)
7. [审查引擎 API 接入、企业代理与一键体检](#7-审查引擎-api-接入企业代理与一键体检)
8. [Draft 任务草案态与物理可行性 Lint 门禁](#8-draft-任务草案态与物理可行性-lint-门禁)

---

### 1. MCP 解释器与运行环境问题

#### Q: IDE 报错找不到 FastMCP 或 MCP Server 启动失败？
- **原因**：Antigravity IDE 或 Cursor 启动 MCP Server 时使用的是全局系统 Python，而非配置了 `fastmcp>=2.0` 的虚拟环境。
- **排查与解决**：
  1. 在 `quorch` 根目录执行安装引导脚手架：
     ```bash
     python scripts/install.py
     ```
     脚手架会自动探测当前激活的虚拟环境或根目录 `.venv`，并将准确的解释器路径填入各 IDE 配置。
  2. 运行体检命令验证环境完整性：
     ```bash
     quench check
     # 或
     python scripts/install.py --check
     ```

---

### 2. Windows 控制台与乱码问题 (GBK / UTF-8)

#### Q: Windows PowerShell / CMD 下终端输出出现中文乱码或 `UnicodeDecodeError`？
- **原因**：Windows 默认代码页为 CP936（GBK），当 Python 脚本输出包含 UTF-8 特殊字符（如 Emoji 或复杂中文）时，控制台缓冲区可能发生解码冲突。
- **排查与解决**：
  1. 插件内部所有脚本均已预置 `sys.stdout.reconfigure(encoding="utf-8")` 容错；
  2. 在 PowerShell 中，可临时切换控制台至 UTF-8 代码页：
     ```powershell
     chcp 65001
     $OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
     ```

---

### 3. PreToolUse 拦截弹窗与 Hook 超时

#### Q: 模型在编辑文件时，IDE 突然弹出确认授权弹窗？
- **这是正常安全机制**：说明当前修改的文件**不属于当前正在执行任务的【涉及文件】白名单**。
- **处理建议**：
  - 若该修改是合理且必要的：点击【允许 (Allow)】单次放行，或由模型调用 `dev_tasks_set_bypass` 申请临时会话旁路；
  - 若该修改属于模型的幻觉或无意越界：点击【拒绝 (Deny)】，守卫将阻断修改并提示模型聚焦于本任务。

#### Q: Hook 报告超时（Timeout > 5s）？
- **原因**：Hook 执行被杀毒软件或高负载进程阻塞。
- **解决**：Quench Hook 经过极致轻量化设计，正常响应在 20ms 以内。若被安全软件拦截，请将 Python 虚拟环境添加至防病毒白名单。

---

### 4. 目录更名与句柄锁定 (PermissionError)

#### Q: 执行仓库重命名或安装时提示 `[目录句柄锁定] PermissionError`？
- **原因**：当前有终端窗口、VS Code / Antigravity IDE 实例或正在运行的 Python 进程正持有该目录下的打开文件句柄。
- **排查与解决**：
  1. 运行 Pre-flight 预检确认占用状态：
     ```bash
     python scripts/install.py --preflight
     ```
  2. 关闭所有停留在该目录下的命令行终端与 IDE 编辑器窗口；
  3. 确认无后台残留的 `python.exe` 进程后，重试更名或安装。

---

### 5. Windows MAX_PATH 路径长度警告

#### Q: Pre-flight 提示 `[MAX_PATH 警告] 当前安装路径长度为 ... 字符`？
- **原因**：Windows 经典文件系统有 260 字符的 `MAX_PATH` 限制。当代码仓库放在极深的嵌套目录中时，嵌套测试文件可能超限。
- **解决**：
  - 建议将仓库克隆至较浅的路径（如 `D:\Work\quorch`）；
  - 或在 Windows 注册表中开启长路径支持：
    `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`。

---

### 6. 双模型角色与通用解耦设计

#### Q: 如何理解 Reviewer（架构审查）与 执行 Agent（日常执行）的解耦架构？是否必须绑定特定厂商模型？
- **完全不需要绑定任何特定模型**：Quench 采用纯粹的**逻辑角色解耦架构**：
  - **Reviewer（架构审查者）**：任何具备强逻辑推理、擅长系统架构与大局观的高阶模型皆可充当（可灵活接入外部 Thinking 推理 API、本地 Ollama 离线部署模型或宿主 IDE 内置子代理）；
  - **执行 Agent（日常执行者 / Runner）**：任何遵循度高、响应敏捷且成本低廉的日常执行模型皆可充当。
- 两者通过 MCP 状态机与六大字段任务契约实现标准协议交互，开发者可根据工程场景和算力预算自由配置。

---

### 7. 审查引擎 API 接入、企业代理与一键体检

#### Q: 如何接入外部 API 推理模型（如 DeepSeek、OpenAI、本地 Ollama）充当 Reviewer？
- **配置方式**：编辑 `.agents/quench_stack.yaml` 中的 `reviewer_engine` 块，配置 `provider: "deepseek"`, `api_key_env: "DEEPSEEK_API_KEY"`，并在操作系统或终端中导出对应的环境变量。
- **企业内网代理**：引擎原生支持并尊重 `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` 环境变量，内置 SSL 上下文自适应与连接超时熔断。
- **一键测试连通性**：通过 Quench CLI 提供的专用诊断工具：
  ```bash
  quench check --reviewer
  ```
  该命令将安全检测上游 API 连通性、密钥有效性与往返延迟，绝不产生多余的文件变更。
- **思考流日志在哪里查看？**：思维链实时分块落盘至 `.agents/logs/reviewer/thinking.log`，内置 1024KB 安全硬轮转与凭据正则脱敏。

---

### 8. Draft 任务草案态与物理可行性 Lint 门禁

#### Q: 什么是 `📝 Draft`（`📝 草案`）状态？它如何防止模型空转与误伤代码？
- **核心定位**：在构思高风险重构或复杂特性时，可通过 `is_draft=True` 提交草案任务。Draft 状态任务与待执行队列严格隔离，Runner 模型绝不会越级领单。
- **物理可行性 Lint 门禁**：在调用 `dev_tasks_promote_draft` 晋升任务前，系统硬性核验：
  1. 【涉及文件】是否存在路径穿越（`../`）漏洞；
  2. 声明的文件在磁盘上是否真实物理存在；
  3. 目标覆盖冲突安全检测；
  4. 静态语法 dry-run（如 `pytest --collect-only`），在允许开工前提前排查文件语法崩溃。

