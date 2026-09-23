# 2026-09-23_cross_platform_path_guard Development Tasks / 跨平台路径穿透防御与路径沙箱规范化任务单

> **路线图与根因来源**: Reviewer 深度代码审计与 Ubuntu CI 失败复盘 (`scratch/reviewer_ubuntu_ci_analysis.md`) 及跨平台异常手册 (`docs/cross_platform_ci_anomalies.md`)
> **批次划分**: Batch 1（单一批次：统一跨平台路径穿透防御与单一事实源抽象，任务 1.1）
> **串行约束**: 严格遵守单核串行施工原则，单任务闭环交付。
> **语言约定**: 本任务单采用中文正文与中文六字段标题，执行时严禁翻译或改写为英文标题（镜像契约）。
> **回归基线**: 确保 `plugins/quench-dev-tasks/server/tests` 全量测试套件与新增跨平台双引擎测试 100% 通过，且核心无任何厂商字面量。

---

## 批次 1 (Batch 1): 统一跨平台路径穿透防御与单一事实源抽象

### 任务 1.1 ✔️ 已完成 — 统一跨平台路径穿透防御与路径沙箱规范化 (Unified Cross-Platform Path Guard & Workspace Confinement)

#### 【涉及文件】
```
[NEW] plugins/quench-dev-tasks/server/path_guard.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/consultation.py
[MODIFY] plugins/quench-dev-tasks/server/schema_validator.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py
[NEW] plugins/quench-dev-tasks/server/tests/test_path_guard.py
```

#### 【缺陷根因与修改目标】
**根因**：
1. `server.py::_resolve_handoff_envelope`、`consultation.py::resolve_context_files` 与 `schema_validator.py::lint_task_physical_feasibility` 中独立实现了基于 `os.path.normpath` 和 `os.path.commonpath` 的路径防御逻辑。
2. 宿主系统的分隔符表随平台而异：在 Windows (`ntpath`) 下，`\` 是 `os.sep`，`..\..\windows\system32\cmd.exe` 会被识别为目录层级跳转并成功被 `commonpath` 拦截；而在 POSIX (Ubuntu Linux / macOS) 下，`/` 是唯一的分隔符，`\` 是普通文件名字符，`os.path.join(ws, cf)` 会将反斜杠视作当前工作区内的一个带反斜杠的文件名，`commonpath` 判定仍在工作区内放行。
3. 随后 `server.py` 对放行路径执行 `.replace("\\", "/")`，瞬间将文件名还原为包含目录穿越向量的 `"../../windows/system32/cmd.exe"` 并追加至安全上下文文件列表，导致 Ubuntu CI `assert not f.startswith("..")` 产生 `AssertionError`。
4. 存在多处路径防御实现漂移（D2）及对软链接、URL 编码绕过、NUL 截断等边缘测试向量缺少统一防御。

**目标**：
1. 建立单一事实源（SSOT）模块 `path_guard.py`，提供宿主无关的组件级路径规范化与工作区沙箱限制函数 `sanitize_workspace_path`。
2. 遵循 Fail-Closed 准则：发现任何路径越界、盘符、UNC、NUL 截断或恶意编码时，统一抛出 `PathTraversalError`，杜绝静默篡改。
3. 重构 `server.py`、`consultation.py` 与 `schema_validator.py`，消除重复实现与语义漂移。
4. 引入 `ntpath` 与 `posixpath` 双引擎模拟测试，确保在任何单平台运行即可验证所有跨平台测试向量。

#### 【目标签名与类型契约】
```python
# plugins/quench-dev-tasks/server/path_guard.py

class PathTraversalError(ValueError):
    """Raised when a candidate path violates workspace confinement or contains traversal vectors. / 当候选路径违反工作区沙箱约束或包含逃逸向量时抛出。"""
    pass

def sanitize_workspace_path(
    workspace_root: str,
    candidate: str,
    *,
    must_exist: bool = False,
    allow_workspace_root: bool = False,
) -> str:
    """Sanitize and confine a candidate path within workspace_root, returning a canonical absolute realpath.

    Raises:
        PathTraversalError: If candidate is None, empty, contains NUL, drive, UNC, escapes workspace, or fails existence check.
    """
    ...

def to_workspace_relative_path(
    workspace_root: str,
    candidate: str,
    *,
    must_exist: bool = False,
    allow_workspace_root: bool = False,
) -> str:
    """Sanitize and return a relative path formatted with forward slashes ('/')."""
    ...
```

#### 【分步改造指引】
1. **新建 `path_guard.py`**：
   - 实现 `PathTraversalError` 异常类。
   - 实现 `sanitize_workspace_path`：
     - 空指针与空串防御（`None` 或 `strip() == ""`）。
     - `\x00` NUL 字节截断检测。
     - URL 百分号编码探针（若 `unquote` 产生 `..` 或敏感字符则拦截）。
     - 分隔符前置归一：统一 `replace("\\", "/")`。
     - 结构检查：拦截绝对路径（以 `/` 开头）、UNC 路径（以 `//` 开头）、Windows 盘符（如 `^[a-zA-Z]:`）。
     - 恶意分量与 Win32 别名防御：拦截包含 3 个及以上连续点（如 `....`）、以点或空格结尾的非法分量（如 `"a. "`）、Windows 预留设备名（CON, PRN, AUX, NUL, COM*, LPT*）。
     - 物理路径解析：`real_ws = os.path.realpath(os.path.abspath(workspace_root))`。
     - 路径拼接与软链接解析：`joined = os.path.realpath(os.path.abspath(os.path.join(real_ws, *parts)))`。
     - 沙箱包含性断言：通过 `os.path.commonpath([real_ws, joined]) == real_ws`，防范跨盘符（捕获 `ValueError` 并抛出 `PathTraversalError`）与父级逃逸。
     - 相对路径前缀校验：`rel = os.path.relpath(joined, real_ws)`，校验不以 `..` 开头；若不允许工作区根目录且 `joined == real_ws` 则拦截。
     - 可选存在性校验（`must_exist`）：校验 `os.path.exists(joined)`。
   - 实现 `to_workspace_relative_path`：在 `sanitize_workspace_path` 基础上返回 `os.path.relpath(abs_p, real_ws).replace("\\", "/")`。
2. **重构调用点**：
   - `server.py::_resolve_handoff_envelope`：
     - `task_path` 使用 `to_workspace_relative_path`，若抛出 `PathTraversalError` 则安全回退至空或降级标记，绝不放行逃逸路径。
     - `context_files`：使用 `to_workspace_relative_path(ws_root, cf, must_exist=False)` 逐项校验并添加到 `safe_context_files`，捕获 `PathTraversalError` 并安全跳过。
   - `consultation.py::resolve_context_files`：
     - 将原本局部的 `splitdrive` 与 `commonpath` 替换为调用 `sanitize_workspace_path(ws_root, p_str, must_exist=True)`。
   - `schema_validator.py::lint_task_physical_feasibility`：
     - 将原本第 328-344 行的路径穿越检验替换为调用 `sanitize_workspace_path(ws_root, rel)`，捕获 `PathTraversalError` 并生成 `LintIssue("error", "affected_files", ...)`。
3. **编写单元测试**：
   - 新建 `plugins/quench-dev-tasks/server/tests/test_path_guard.py`，参数化验证 11+ 类跨平台穿透测试向量、双引擎（`ntpath` / `posixpath`）兼容性与边缘用例。
   - 更新 `test_handoff_protocol.py::test_path_traversal_defense`，强化断言，确保 Ubuntu 和 Windows 双向安全。

#### 【防御与边缘校验】
- **分隔符归一前置**：必须在任何 `os.path` 操作前完成 `replace("\\", "/")`，严禁在校验之后再执行二次语义替换。
- **跨盘符安全**：Windows 下跨盘符调用 `os.path.commonpath` 会引发 `ValueError`，必须显式捕获并转化为 `PathTraversalError`。
- **软链接逃逸防御**：必须使用 `os.path.realpath` 计算物理真实路径后再做 `commonpath`。
- **Win32 别名与尾随点/空格防御**：拦截 `a. `、`con.txt` 等在 Windows 下会发生文件系统别名重定向的路径。
- **代码中立性**：`path_guard.py` 作为核心基础模块，严禁包含任何厂商字面量。

#### 【DoD 验证命令】
```bash
# 1. 运行 path_guard 专项测试（含 11+ 跨平台向量）
pytest plugins/quench-dev-tasks/server/tests/test_path_guard.py -q -o pythonpath=plugins/quench-dev-tasks/server

# 2. 运行 handoff 协议测试（验证历史 CI 失败用例）
pytest plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py -q -o pythonpath=plugins/quench-dev-tasks/server

# 3. 运行核心模块厂商中立性扫描门禁
pytest plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py -q -o pythonpath=plugins/quench-dev-tasks/server

# 4. 运行全量测试套件（回归基线，要求 100% 通过）
pytest plugins/quench-dev-tasks/server/tests/ -q -o pythonpath=plugins/quench-dev-tasks/server
```
