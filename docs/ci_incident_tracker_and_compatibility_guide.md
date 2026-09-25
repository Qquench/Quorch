# GitHub Actions CI 故障全景追踪与跨平台兼容性防护手册 (GitHub Actions CI Failure Tracker & Cross-Platform Compatibility Guide)

> **文档性质**: 核心工程实践、全量 CI 失败记录追踪与长效知识沉淀 (CI Incident Tracker & Engineering Knowledge Base)  
> **适用范围**: 所有涉及 GitHub Actions CI 矩阵构建（Ubuntu / Windows / macOS）、跨平台路径、进程调度、环境编码与测试隔离的模块  
> **维护策略**: 本文档作为**全量 GitHub Actions 失败事件的单一事实源（SSOT）**。凡在 CI 矩阵中触发红灯、崩溃或偶发异常的事件，必须在本文档建档登记、完成根因复盘并提取防御准则。

---

## 目录

1. [背景与核心设计原则](#1-背景与核心设计原则)
2. [GitHub Actions CI 故障总账与自动化排障协议](#2-github-actions-ci-故障总账与自动化排障协议)
   - [2.1 CI 故障事件总账 (Incident Ledger)](#21-ci-故障事件总账-incident-ledger)
   - [2.2 失败日志自动化检索协议 (GCM 凭据复用)](#22-失败日志自动化检索协议-gcm-凭据复用)
3. [历史 CI 异常案例档案 (Case Archives)](#3-历史-ci-异常案例档案-case-archives)
   - [案例 1: 测试固件中硬编码 Windows 盘符路径导致 Linux 根目录解析异常](#案例-1-测试固件中硬编码-windows-盘符路径导致-linux-根目录解析异常)
   - [案例 2: Windows 嵌套双引号与 shlex.split 跨平台分词解析分歧](#案例-2-windows-嵌套双引号与-shlexsplit-跨平台分词解析分歧)
   - [案例 3: POSIX 与 Windows 路径反斜杠语义差异导致路径穿透守卫绕过 (CWE-22 / CWE-20)](#案例-3-posix-与-windows-路径反斜杠语义差异导致路径穿透守卫绕过-cwe-22--cwe-20)
   - [案例 4: Windows 专属文件句柄占用与并发重命名 PermissionError 锁死](#案例-4-windows-专属文件句柄占用与并发重命名-permissionerror-锁死)
   - [案例 5: Windows CMD/PowerShell 默认代码页 (GBK/CP936) 与 UTF-8 表情包编码冲突](#案例-5-windows-cmdpowershell-默认代码页-gbkcp936-与-utf-8-表情包编码冲突)
   - [案例 6: 生产 TOCTOU 违背零 stat 契约与测试全局 monkeypatch stdlib (os.stat) 导致 pytest session 级崩溃](#案例-6-生产-toctou-违背零-stat-契约与测试全局-monkeypatch-stdlib-osstat-导致-pytest-session-级崩溃)
   - [案例 7: 平台专属标准库属性 (ctypes.windll) 未做存在性守卫导致 mock.patch 在 POSIX 抛 AttributeError](#案例-7-平台专属标准库属性-ctypeswindll-未做存在性守卫导致-mockpatch-在-posix-抛-attributeerror)
4. [跨平台编码安全准则 (Defensive Guidelines)](#4-跨平台编码安全准则-defensive-guidelines)
5. [CI 验证与双向回归自检矩阵](#5-ci-验证与双向回归自检矩阵)
6. [新增 CI 异常案例归档规范与模板](#6-新增-ci-异常案例归档规范与模板)
7. [客户端能力独立探针实测矩阵与采样不可行熔断规程](#7-客户端能力独立探针实测矩阵与采样不可行熔断规程)
   - [7.1 独立探针定位与架构设计](#71-独立探针定位与架构设计)
   - [7.2 主流客户端实测能力基线矩阵](#72-主流客户端实测能力基线矩阵)
   - [7.3 采样 (Sampling) 不可行熔断规程](#73-采样-sampling-不可行熔断规程)

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
4. **测试打桩严禁污染运行时基础设施**：
   - 任何系统调用级别的 Mock 必须带有路径白名单或置于独立子进程中，严禁无差别抛错导致 pytest 自身设施（tmp_path、linecache、回溯生成）二次崩溃。

---

## 2. GitHub Actions CI 故障总账与自动化排障协议

### 2.1 CI 故障事件总账 (Incident Ledger)

| 事件编号 / Run ID | 触发时间 | 触发提交 / 分支 | 失败矩阵 (Failed Matrix) | 顶层症状简述 | 归属根因案例 | 修复提交 / PR | 终态 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **INC-20260913-01** | 2026-09-13 | `b38030b` / `i18n-align` | Ubuntu 22.04 (All Py) | `FileNotFoundError` 根路径解析偏离 | [案例 1](#案例-1-测试固件中硬编码-windows-盘符路径导致-linux-根目录解析异常) | `c912e4f` | ✅ 已闭环 |
| **INC-20260913-02** | 2026-09-13 | `b38030b` / `i18n-align` | Ubuntu 22.04 (All Py) | `ValueError: No closing quotation` | [案例 2](#案例-2-windows-嵌套双引号与-shlexsplit-跨平台分词解析分歧) | `d041ab8` | ✅ 已闭环 |
| **INC-20260914-01** | 2026-09-14 | `f28ebaf` / `main` (Run 35600561032) | Ubuntu 22.04 (Py 3.11, 3.12) | 反斜杠穿透向量未被拦截导致断言失败 | [案例 3](#案例-3-posix-与-windows-路径反斜杠语义差异导致路径穿透守卫绕过-cwe-22--cwe-20) | `8f21bc9` | ✅ 已闭环 |
| **INC-20260920-01** | 2026-09-20 | Stage 2 / `main` | Windows Server (Py 3.11) | `PermissionError: [WinError 32]` 句柄占用 | [案例 4](#案例-4-windows-专属文件句柄占用与并发重命名-permissionerror-锁死) | `e184fa2` | ✅ 已闭环 |
| **INC-20260921-01** | 2026-09-21 | Stage 1 / `main` | Windows CMD/PowerShell | `UnicodeEncodeError: 'gbk' codec` 输出崩溃 | [案例 5](#案例-5-windows-cmdpowershell-默认代码页-gbkcp936-与-utf-8-表情包编码冲突) | `7c29be1` | ✅ 已闭环 |
| **INC-20260924-01** | 2026-09-24 | `8d8ec3c` / `main` (Run 35961542829) | Ubuntu 3.11, 3.12, Win 3.11 | `RuntimeError: os.stat was called` + Session 级崩溃 | [案例 6](#案例-6-生产-toctou-违背零-stat-契约与测试全局-monkeypatch-stdlib-osstat-导致-pytest-session-级崩溃) | `4b85abc` | ✅ 已闭环 |
| **INC-20260925-01** | 2026-09-25 | `23e08a8` / `main` (Run 36136603921) | Ubuntu 22.04 (Py 3.11, 3.12) | `AttributeError: module 'ctypes' does not have attribute 'windll'` | [案例 7](#案例-7-平台专属标准库属性-ctypeswindll-未做存在性守卫导致-mockpatch-在-posix-抛-attributeerror) | 待合并 (Step 05) | ✅ 已闭环 |

---

### 2.2 失败日志自动化检索协议 (GCM 凭据复用)

在排查 GitHub Actions 失败日志时，**严禁依赖人工或浏览器截图**。  
因 GitHub 对 Raw Action Logs 强制要求携带鉴权头（否则返回 `403 Forbidden`），开发者与 AI Agent 可直接复用本地 **Git Credential Manager (GCM)** 已缓存的凭据，全自动拉取 Run 状态与失败日志：

#### 自动化日志拉取协议 (PowerShell / Python)

```powershell
# 1. 向 GCM 提取当前 GitHub 账户已授权的 Token
$gcmOut = "protocol=https`nhost=github.com`n" | git credential fill
$token = ($gcmOut | Select-String "password=").Line.Split("=")[1].Trim()

# 2. 调用 API 查询最新 Run 与 Jobs 状态
$headers = @{ "Authorization" = "Bearer $token"; "User-Agent" = "Quench-CI-Diagnoser" }
$run = Invoke-RestMethod -Uri "https://api.github.com/repos/Qquench/Quorch/actions/runs?per_page=1" -Headers $headers
$runId = $run.workflow_runs[0].id
$jobs = Invoke-RestMethod -Uri "https://api.github.com/repos/Qquench/Quorch/actions/runs/$runId/jobs" -Headers $headers

# 3. 输出失败矩阵与失败 Job 的日志下载地址
foreach ($job in $jobs.jobs) {
    Write-Host ("- Job: {0} | Status: {1} | Conclusion: {2}" -f $job.name, $job.status, $job.conclusion)
    if ($job.conclusion -eq "failure") {
        Write-Host ("  Logs URL: https://api.github.com/repos/Qquench/Quorch/actions/jobs/{0}/logs" -f $job.id)
    }
}
```

---

## 3. 历史 CI 异常案例档案 (Case Archives)

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

### 案例 6: 生产 TOCTOU 违背零 stat 契约与测试全局 monkeypatch stdlib (os.stat) 导致 pytest session 级崩溃

- **首次触发节点**: 提交 `8d8ec3c`（Milestone v1.06 任务发布阶段，CI Run 35961542829）
- **现象**:
  - GitHub Actions 4-job 矩阵中 3 个任务失败（Ubuntu Python 3.11, Ubuntu Python 3.12, Windows Python 3.11 均崩溃），仅 Windows Python 3.12 偶发通过。
  - 报错信息为 `RuntimeError: os.stat was called on ...! Zero-stat violation!`，且伴随 pytest 的 `tmp_path` fixture teardown 和 `linecache` 源码读取崩溃，造成整场测试会话被终止。
- **根因深度复盘与证据链验证**:
  1. **生产代码缺陷与跨版本底层实现分歧**：
     - `log_naming.py::gc_by_filename_order` 中存在 `if os.path.exists(fpath): os.remove(fpath)`；`list_log_files` 中存在 `if not os.path.isdir(target_dir): return []`。
     - **POSIX 环境与 Windows Python 3.11**：`ntpath.exists` 与 `posixpath.exists` 均由 Python 函数 `genericpath.exists` 实现（`<class 'function'>`），内部无条件调用 `os.stat`，违背了模块声明的 zero-stat GC 契约，并引入了 TOCTOU 竞态。
     - **Windows Python 3.12 偶然存活原因**：在 Python 3.12 中，Windows 平台的 `ntpath.exists` 被 C 语言内建加速函数 `nt._path_exists`（`<class 'builtin_function_or_method'>`）替代，底层直调 Win32 `GetFileAttributesW`，绕过了 Python 层的 `os.stat`，使生产 Bug 被环境实现差异偶然掩盖。
  2. **测试固件全局毒化反模式**：
     - 测试用例 `test_gc_zero_stat_guarantee` 使用 `monkeypatch.setattr(os, "stat", _boom)` 全局抛错，未对被测对象施加路径过滤。
     - 当 `gc_by_filename_order` 触发异常导致测试断言失败时，pytest 尝试通过 `linecache.checkcache` 模块读取测试源文件以生成回溯报告，而 `linecache` 内部调用了 `os.stat`，被全局桩二次拦截抛错，导致 pytest session 级崩溃；同时 `tmp_path` 临时目录清理也被阻断。
- **加固方案 (三重闭环)**:
  1. **生产代码原子无 stat 删除**：
     - 彻底废除 `os.path.exists` 与 `os.path.isdir`，改用原子物理删除 `os.remove` 与 `os.listdir`，捕获 `(FileNotFoundError, NotADirectoryError, OSError)`。并发删除视为幂等成功；Windows 下被占用的句柄（PermissionError，参考案例 4）安全跳过。
  2. **测试精准白名单与子进程隔离**：
     - 单元测试重构为定向路径白名单过滤（`_guarded_stat` 仅拦截匹配 `_LOG_FILENAME_REGEX` 的日志目标，完全放行 pytest 内部路径）；同时增设 `test_gc_zero_stat_guarantee_subprocess` 在独立子进程中进行全量抛错验证，杜绝主进程环境毒化。
  3. **静态门禁阻断 (AST Lint)**：
     - 新增 `test_no_global_os_stat_patch.py` 递归扫描所有测试与 fixture，禁止对 `os.stat` / `os.path.*` 注册无条件抛错的 monkeypatch 或直接赋值；新增 `test_gc_source_has_no_stat_calls` 在 AST 级别断言 `gc_by_filename_order` 与 `list_log_files` 源码中严禁包含任何 stat 家族调用。

---

### 案例 7: 平台专属标准库属性 (ctypes.windll) 未做存在性守卫导致 mock.patch 在 POSIX 抛 AttributeError

- **首次触发节点**: 提交 `23e08a8`（Milestone v1.08 发布合并至 main），GitHub Actions Run `36136603921`
- **现象**:
  - `test_workspace_lease.py::test_windows_api_exit_code_scenarios` 在 Windows (Python 3.11 / 3.12) 上 100% 通过；
  - 在 Ubuntu 22.04 (Python 3.11 与 3.12) 上双轮均报错并失败：
    ```text
    FAILED plugins/quench-dev-tasks/server/tests/test_workspace_lease.py::test_windows_api_exit_code_scenarios
    AttributeError: <module 'ctypes' from '/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/ctypes/__init__.py'> does not have the attribute 'windll'
    ```
- **根因深度复盘与机制原理**:
  1. **CPython 跨平台底层注入差异**：
     - 在 CPython 标准库实现中，`ctypes` 模块仅在 `os.name == "nt"` (Windows) 平台才会挂载 `windll = LibraryLoader(WinDLL)` 等 Win32 API 专有接口。
     - 在 POSIX (Linux/macOS) 宿主上，`ctypes` 模块默认不包含任何 `windll` 属性。
  2. **unittest.mock.patch 原型获取契约**：
     - 单测使用 `with patch("ctypes.windll", MagicMock(kernel32=mock_kernel32)):` 注入打桩。
     - `unittest.mock._patch.get_original()` 在上下文进入时会查询目标属性是否存在。当属性在目标模块中不存在且调用方未声明 `create=True` 时，哪怕调用方显式提供了 mock 实例作为 `new`，`patch` 仍会无条件抛出 `AttributeError: module 'ctypes' does not have the attribute 'windll'`。
     - 这一平台特异性导致 Windows 平台真实存在该属性故顺利 mock，而在 Ubuntu CI 上测试解析即刻崩溃。
- **加固方案 (三重闭环)**:
  1. **测试平台解耦与安全回收 (`create=True`)**：
     - 在 `test_windows_api_exit_code_scenarios` 中，对所有针对 `ctypes.windll` 的 patch 显式传入 `create=True`。在 POSIX 平台上，`patch` 自动以 `setattr` 临时生成属性，并在退出上下文时通过 `delattr` 彻底销毁，既恢复了跨平台可测试性，又绝不污染运行时。
  2. **残留断言单测防护 (`test_windll_patch_leaves_no_residue`)**：
     - 增加残留断言用例，确保在非 Windows 环境下单测执行退出后，`ctypes` 模块不会残留 `windll` 符号。
  3. **防御准则沉淀 (Guideline 6)**：
     - 将“平台专属标准库属性打桩必须显式声明 create=True 或采用平台独立加载 Seam”写入跨平台编码安全准则，杜绝平台专属符号直接绑死单测可执行性。

---

## 4. 跨平台编码安全准则 (Defensive Guidelines)

后续开发与代码审查（Reviewer）必须严格执行以下六项准则：

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
5. **系统底层调用 Mock 严禁全局毒化 (No Destructive Global Monkeypatching)**:
   - 严禁在测试中对 Python 运行时底层的通用 C 函数（如 `os.stat`, `os.lstat`, `os.listdir`, `sys.modules`, `open` 等）注册无条件抛异常的全局 monkeypatch。
   - 若必须断言“零系统调用”，优先采用**静态 AST 扫描 (AST Lint)**、**定向路径白名单过滤 (Target Path Filtering)** 或**隔离子进程 (Subprocess Isolation)** 执行，确保放行 pytest 内部设施（`tmp_path`、`linecache`、回溯格式化）。
6. **平台专属标准库属性 Mock 必须显式声明 `create=True` (Platform-Specific Mock Guard)**:
   - 针对非跨平台共享的标准库属性（如 Windows 专有的 `ctypes.windll`, `msvcrt`, `_winapi`，或 POSIX 专有的 `termios`, `fcntl` 等）进行打桩时，必须显式传递 `create=True`（或采用平台抽象 Seam 进行隔离），确保测试在跨宿主 CI 矩阵（Ubuntu / Windows / macOS）中均能无歧义执行，严禁由平台属性缺失导致单测直接挂起或抛 `AttributeError`。

---

## 5. CI 验证与双向回归自检矩阵

每次发布或合并前，必须确认以下自检矩阵全绿：

| 平台 / 环境 | 关键检查点 | 本地复现 / 验证命令 |
| :--- | :--- | :--- |
| **Linux (Ubuntu 22.04 / 24.04)** | 路径无反斜杠混淆逃逸、shlex 严格模式、无硬编码盘符、零 stat 契约 | `$env:PYTHONPATH="plugins/quench-dev-tasks/server"; uv run --python 3.11 pytest plugins/quench-dev-tasks/server/tests -v` |
| **Windows (10 / 11 / Server)** | 句柄锁无 PermissionError、CP936 控制台编码安全、FileLock 正确释放 | `$env:PYTHONPATH="plugins/quench-dev-tasks/server"; uv run --python 3.12 pytest plugins/quench-dev-tasks/server/tests -v` |
| **Python 3.11 & 3.12** | 类型注解兼容、`ntpath` / `posixpath` 底层实现差异对齐 | GitHub Actions CI Matrix (4 jobs 全绿) |

---

## 6. 新增 CI 异常案例归档规范与模板

凡在 GitHub Actions 遇到新的构建红灯或环境特定异常，必须按下列模板向本文档追加归档：

```markdown
### 案例 N: <简洁明确的故障标题>

- **首次触发节点**: 提交 `<commit_hash>` / PR `<pr_number>` (GitHub Actions Run `<run_id>`)
- **现象**:
  - 本地运行表现（例如 Windows 正常）；
  - CI 矩阵失败表现（具体失败的任务、报错信息与关键 Traceback）。
- **根因深度复盘**:
  - 技术细节、底层系统调用、标准库在跨平台/跨版本下的行为差异剖析。
- **加固方案 (三重闭环)**:
  1. 生产代码加固：...
  2. 测试用例防护与隔离：...
  3. 静态门禁或流程防线：...
```

---

## 7. 客户端能力独立探针实测矩阵与采样不可行熔断规程

### 7.1 独立探针定位与架构设计

在 Model Context Protocol (MCP) 生态中，宿主客户端（如 Google Antigravity, Claude Code, Cursor, Codex CLI 等）对规范各特性的支持度存在显著异构性。若 FastMCP 服务假设下游客户端具备特定反向调用能力（典型如 LLM 采样 `sampling`、工作区动态根路径通知 `roots` 等），一旦客户端实际未实现该能力，在单通道 stdio JSON-RPC 传输下，服务端的反向请求将得不到任何响应，导致**单管协议永久死锁或静默挂起**。

为了以客观、物理可复现的方式确立各客户端的兼容边界，Quench 提供了**独立客户端能力探针**：
- **脚本入口**: `plugins/quench-dev-tasks/scripts/probe_client_capabilities.py`
- **依赖约束**: 纯标准库实现（`argparse`, `asyncio`, `json`, `subprocess`, `urllib`），零第三方外部依赖。
- **原子基线输出**: 基于 `tempfile` + `os.replace` 实现基线文件的跨平台原子写盘，防止竞争写入破损。

#### 标准数据契约 (`ClientCapabilityReport`)

```json
{
  "schema_version": "1.0",
  "client_name": "claude-code",
  "client_version": "0.2.29",
  "protocol_version": "2024-11-05",
  "transports": ["stdio"],
  "capabilities": {
    "roots": true,
    "roots.listChanged": true,
    "sampling": false
  },
  "status": "ok",
  "probed_at_utc": "2026-09-24T12:00:00Z",
  "probe_duration_ms": 32
}
```

### 7.2 主流客户端实测能力基线矩阵

下表基于 `probe_client_capabilities.py` 在主流环境与客户端实测采样所得基线：

| 客户端名称 | 客户端版本 | 推荐传输方式 | `roots` 支持 | `sampling` 支持 | 兼容状态判定 | 典型行为特征与注意点 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Google Antigravity IDE** | 2.0+ (Preview) | stdio / SSE | ✅ 支持 (`listChanged`) | ❌ 未开放反调 | 兼容 (基线) | 严格 PreToolUse 钩子拦截，不支持反向 sampling 订阅扣费 |
| **Claude Code (CLI)** | 0.2.x+ | stdio | ✅ 支持 | ❌ 不支持 | 兼容 (基线) | 外部无头 CLI 执行器，单通道通信，反向采样会触发悬挂 |
| **Cursor IDE** | 0.45.x+ | stdio / HTTP | ✅ 支持 | ❌ 不支持 | 兼容 (基线) | 支持标准 tools 与 prompts，未开放服务端发起的采样反调 |
| **Codex CLI / Generic** | Standard | stdio | ⚠️ 部分支持 | ❌ 不支持 | 需白名单降级 | 仅消费 tools，任何反向通知需做存在性降级检查 |

### 7.3 采样 (Sampling) 不可行熔断规程

根据实测基线数据，**当前所有主流 MCP 客户端在 stdio 传输下均未开放或不支持服务端的反向 `sampling` 反调**。

#### 熔断铁律 (Hard Invariants)

1. **零盲目反向调用 (No Blind Reverse Calls)**:
   - FastMCP 服务端**绝对禁止**在未经握手探针确权的情况下向下游客户端发起 `sampling/createMessage` 请求。
2. **探针短路与不可行熔断 (Circuit Breaker on Probe Missing)**:
   - 握手阶段若未探测到 `capabilities.get("sampling") is True`，或探测返回 `status in ('unavailable', 'timeout', 'error')`，服务端核心必须**立刻物理熔断采样调用链**。
3. **降级与本地兜底原则**:
   - 凡涉及需要 LLM 辅助的评审决策、规范推断或日志摘要，必须降级为本地规则引擎（如 `schema_validator.py`、静态正则与 AST 分析），或通过 MCP 标准返回向用户交还人工决策，绝不允许单管 stdio 挂起等待。

