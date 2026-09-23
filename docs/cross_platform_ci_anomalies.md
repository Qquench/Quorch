# 跨平台 CI 异常记录与兼容性防护手册 (Cross-Platform CI Anomalies & Compatibility Guide)

> **文档性质**: 核心工程实践与长效知识沉淀 (Engineering Knowledge Base)  
> **适用范围**: 所有涉及跨平台（Windows / Linux / macOS）路径、进程调度、编码与 CI 构建的模块  
> **维护策略**: 遇到新的跨平台或 CI 边界缺陷时持续追加，作为后续大版本演进与回归测试设计的强制检查清单。

---

## 目录

1. [背景与核心设计原则](#1-背景与核心设计原则)
2. [历史 CI 异常案例档案 (Case Archives)](#2-历史-ci-异常案例档案-case-archives)
   - [案例 1: 测试固件中硬编码 Windows 盘符路径导致 Linux 根目录解析异常](#案例-1-测试固件中硬编码-windows-盘符路径导致-linux-根目录解析异常)
   - [案例 2: Windows 嵌套双引号与 shlex.split 跨平台分词解析分歧](#案例-2-windows-嵌套双引号与-shlexsplit-跨平台分词解析分歧)
   - [案例 3: POSIX 与 Windows 路径反斜杠语义差异导致路径穿透守卫绕过 (CWE-22 / CWE-20)](#案例-3-posix-与-windows-路径反斜杠语义差异导致路径穿透守卫绕过-cwe-22--cwe-20)
   - [案例 4: Windows 专属文件句柄占用与并发重命名 PermissionError 锁死](#案例-4-windows-专属文件句柄占用与并发重命名-permissionerror-锁死)
   - [案例 5: Windows CMD/PowerShell 默认代码页 (GBK/CP936) 与 UTF-8 表情包编码冲突](#案例-5-windows-cmdpowershell-默认代码页-gbkcp936-与-utf-8-表情包编码冲突)
3. [跨平台编码安全准则 (Defensive Guidelines)](#3-跨平台编码安全准则-defensive-guidelines)
4. [CI 验证与双向回归自检矩阵](#4-ci-验证与双向回归自检矩阵)

---

## 1. 背景与核心设计原则

Quench Dev-Orchestrator 是在 **Windows (Google Antigravity IDE)** 环境中孵化并首发验证的，但其作为标准的 FastMCP 服务与开源规范套件，必须能在 **Ubuntu (GitHub Actions CI)**、**macOS** 与各类云原生容器中 100% 保持确定性一致。

### 核心铁律 (Iron Rules)

1. **绝对禁止依赖宿主 OS 隐式决定安全语义**：
   - 路径处理、文件权限、分隔符归一化必须在逻辑层显式前置完成，绝不能假设“所有系统都把 `\` 当作目录分隔符”。
2. **测试固件必须 100% 平台无关**：
   - 单元测试严禁出现任何硬编码盘符（如 `C:/`、`D:/`）或绝对路径（如 `/tmp/`、`/etc/`），必须统一依赖 pytest 的 `tmp_path` fixture。
3. **断言必须具备宿主无关性 (Host-Invariant Assertions)**：
   - 如果测试是在 Linux CI 上运行，针对 Windows 语境（如反斜杠穿透）的守卫逻辑，必须通过组件级归一化或双引擎（`ntpath` / `posixpath`）注入进行无差别验证。

---

## 2. 历史 CI 异常案例档案 (Case Archives)

### 案例 1: 测试固件中硬编码 Windows 盘符路径导致 Linux 根目录解析异常

- **首次触发节点**: 提交 `b38030b`（PR i18n 多语言对齐阶段）
- **现象**:
  - `test_init_project.py::test_init_project_nonexistent_root` 在 Windows 本地全绿。
  - GitHub Actions Ubuntu CI 报 `FileNotFoundError` 或路径解析行为异常。
- **根因分析**:
  - 测试用例中硬编码传入了 `D:/NonExistentPath_XYZ_123` 和 `D:/Path/That/Definitely/Does/Not/Exist_123.py` 作为“不存在路径”的测试桩。
  - 在 Windows 下，`D:/...` 是合法的绝对路径格式。
  - 在 Linux/POSIX 下，系统没有盘符概念，`D:/...` 被解析为当前工作目录下的相对路径，导致断言目标与环境行为产生非预期漂移。
- **加固方案**:
  - 彻底清理所有测试中的硬编码绝对路径，全部改用 `tmp_path / "non_existent_path"`。

---

### 案例 2: Windows 嵌套双引号与 shlex.split 跨平台分词解析分歧

- **首次触发节点**: 提交 `b38030b`（`diagnose_environment` Hook 命令审计阶段）
- **现象**:
  - Windows 环境下注册的 Hook 命令常带双引号保护（如 `""python" "script.py""`），在 Windows 下通过 `subprocess` 正常运行。
  - 在 Ubuntu CI 执行 `diagnose_environment` 时，`shlex.split` 抛出 `ValueError: No closing quotation`，或者把嵌套引号解析为碎裂的参数碎片。
- **根因分析**:
  - 标准库 `shlex.split` 默认在 POSIX 系统上采用 `posix=True` 严格解析反斜杠转义与单双引号；而在 Windows CMD 机制下，双引号通常成对闭合且允许两端双写以防止空格截断。
- **加固方案**:
  - 在进入 `shlex.split` 前，先通过正则 `re.findall(r'"([^"]+)"', clean_cmd)` 剥离清洗外层冗余嵌套引号，并采用 `posix=False` 容错回退机制。

---

### 案例 3: POSIX 与 Windows 路径反斜杠语义差异导致路径穿透守卫绕过 (CWE-22 / CWE-20)

- **首次触发节点**: 提交 `f28ebaf`（Release `v0.2.0`），GitHub Actions Run `35600561032`
- **现象**:
  - `test_handoff_protocol.py::test_path_traversal_defense` 在 Windows 100% 通过。
  - 在 Ubuntu 22.04 / Python 3.11 与 3.12 双轮 CI 中均报 `AssertionError`:
    ```text
    AssertionError: assert not True
    where True = '../../windows/system32/cmd.exe'.startswith('..')
    ```
- **根因深度复盘**:
  - 在 `server.py::_resolve_handoff_envelope` 中：
    ```python
    cf_abs = os.path.normpath(os.path.join(ws_root, cf_clean))
    if os.path.commonpath([ws_root, cf_abs]) == ws_root:
        rel_cf = os.path.relpath(cf_abs, ws_root).replace("\\", "/")
        safe_context_files.append(rel_cf)
    ```
  - 当输入测试向量为 `..\..\windows\system32\cmd.exe` 时：
    - **Windows 环境**: `\` 是 `os.sep`，`normpath` 解析父级目录跳转并越出工作区，`commonpath` 判定不匹配，**成功拦截**。
    - **POSIX (Ubuntu/macOS) 环境**: `/` 是唯一的分隔符，`\` 是合法的文件名字符！`os.path.join` 将其当作工作区根目录下的**单个带反斜杠的文件名**。`commonpath` 认为其未离开工作区而放行！
    - 随后代码执行 `rel_cf.replace("\\", "/")`，在校验通过后反向将反斜杠替换回斜杠，瞬间还原为穿透向量 `"../../windows/system32/cmd.exe"`！
- **加固方案 (SSOT 架构)**:
  - 引入单一事实源 `path_guard.py::sanitize_workspace_path`：**前置强行归一**（`candidate.replace("\\", "/")` 必须先于任何 `os.path` 操作），结合 `realpath` 阻断软链接逃逸，严禁在校验之后再执行二次语义变形。

---

### 案例 4: Windows 专属文件句柄占用与并发重命名 PermissionError 锁死

- **首次触发节点**: Stage 2 / Stage 3 开发阶段
- **现象**:
  - 在 Linux/macOS 上，打开一个文件句柄后重命名或删除该文件（通过 inode 解除引用）是合法的。
  - 在 Windows 上，若任何文件流（如 `open()` 未闭合、日志句柄未 flush/close、FastMCP 长连接未释放）未解除句柄，执行 `os.rename` 或 `os.replace` 将引发 `PermissionError: [WinError 32] 另一个程序正在使用此文件，进程无法访问`。
- **加固方案**:
  - 涉及状态机文件写操作时，必须基于上下文管理器（`with open(...)`）确保严格闭合；
  - 涉及日志切分或覆盖时，必须显式触发 `sink.close()`；
  - 采用 `FileLock` 配合指数退避重试（带 `random.uniform(0.05, 0.15)`），避免 Windows 文件锁竞态毛刺。

---

### 案例 5: Windows CMD/PowerShell 默认代码页 (GBK/CP936) 与 UTF-8 表情包编码冲突

- **首次触发节点**: Stage 1 / Stage 2 终端输出阶段
- **现象**:
  - 终端输出状态机 Emoji（如 `🔨`、`✔️`、`✅`、`📝`）或双语中文日志时，在 Windows PowerShell 偶发 `UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'`。
- **根因分析**:
  - Windows 控制台标准输出流默认绑定为系统本地代码页（如 CP936/GBK）。当 Python 使用默认缓冲区输出超出 GBK 编码范围的 Unicode 符号时崩溃。
- **加固方案**:
  - 所有入口 CLI、Hook 脚本及日志输出模块顶部必须声明：
    ```python
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ```

---

## 3. 跨平台编码安全准则 (Defensive Guidelines)

后续开发与代码审查（Reviewer）必须严格执行以下四项准则：

1. **路径分隔符归一化 (Separator Normalization)**:
   - 任何从外部参数、配置文件、任务单或网络载荷中获取的文件路径字符串，**进入任何处理前**一律执行：
     ```python
     clean_path = raw_path.strip().replace("\\", "/")
     ```
2. **禁止依赖 `os.sep` 进行跨平台安全过滤**:
   - 安全校验必须同时拒绝以 `/` 和 `\` 开头、拒绝含 `:` 盘符、拒绝以 `//` 开头。
3. **真实物理路径包含性检测 (`commonpath + realpath`)**:
   - 比较前必须获取真实的绝对物理路径：
     ```python
     real_ws = os.path.realpath(os.path.abspath(workspace_root))
     real_target = os.path.realpath(os.path.abspath(target_path))
     if os.path.commonpath([real_ws, real_target]) != real_ws:
         raise PathTraversalError(...)
     ```
4. **测试断言双引擎守护**:
   - 涉及路径防逃逸的单元测试，必须在用例内显式对 POSIX 和 Windows 风格同时测试，确保在单平台运行就能提前暴露出跨平台隐患。

---

## 4. CI 验证与双向回归自检矩阵

每次发布或合并前，必须确认以下自检矩阵全绿：

| 平台 / 环境 | 关键检查点 | 典型验证命令 |
| :--- | :--- | :--- |
| **Linux (Ubuntu 22.04 / 24.04)** | 路径无反斜杠混淆逃逸、shlex 严格模式、无硬编码盘符 | `pytest plugins/quench-dev-tasks/server/tests -v` |
| **Windows (10 / 11 / Server)** | 句柄锁无 PermissionError、CP936 控制台编码安全、FileLock 正确释放 | `pytest plugins/quench-dev-tasks/server/tests -v` |
| **Python 3.11 & 3.12** | 类型注解兼容、`datetime.UTC` / `timezone.utc` 语义一致 | GitHub Actions CI Matrix (4 jobs) |
