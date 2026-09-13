# 修复 Windows Hook 命令过度引号包裹导致 Node.js 语法错误崩溃

> **执行模型须知**
> - 严格按照每条任务的【分步改造指引】顺序执行
> - 不得修改任务未涉及的文件
> - 保留所有现有注释和文档字符串（除非明确要求修改）
> - **改逻辑必加单测断言**：在测试目录追加断言，杜绝回归
> - 每完成一条任务，更新其状态为 `🔨 执行中`，完成后更新为 `✔️ 已完成`

- **创建日期**：2026-09-13

---

## 任务清单与状态


### 任务 1.1 ✔️ 已完成 — 移除 hooks.json 渲染中的多余双引号包裹并验证 Node.js 兼容性

#### 【涉及文件】
```
[MODIFY] scripts/install.py
[MODIFY] plugins/quench-dev-tasks/scripts/init_project.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_init_project.py
[MODIFY] CHANGELOG.md
```

#### 【缺陷根因与修改目标】
根因：
Antigravity IDE 基于 Electron/Node.js 架构，在 Windows 下执行 Hook 时底层使用 `child_process.exec(command)`。Node.js 在 Windows 上本身会自动包裹 `cmd.exe /d /s /c "<command>"`。
若在渲染 `hooks.json` 时额外将命令加上最外层双引号（即变成 `""<python>" "<script>""`），Node.js 再次包裹后会导致 `cmd.exe` 解析出首部空命令 `""`，引发 `文件、目录名或卷标语法不正确。` 报错退出代码 1。
由于 Antigravity IDE 采取 Fail-Open 容错机制，Hook 进程崩溃闪退后 IDE 静默放行工具调用，导致 PreToolUse 守卫完全失效。

目标：
1. 移除 `scripts/install.py` 与 `plugins/quench-dev-tasks/scripts/init_project.py` 中的 `_wrap_cmds` 多余双引号处理逻辑，保持标准 `"\"<python>\" \"<script>\""` 格式；
2. 保持 `init_project.py` 中 `diagnose_environment` 的容错解析逻辑；
3. 更新 `test_init_project.py` 单测断言；
4. 重新渲染本工作区与目标外部项目的 `.agents/hooks.json`；
5. 全量回归测试。

#### 【目标签名与类型契约】
```json
// hooks.json 渲染后的 command 属性契约（跨平台统一）
{
  "command": "\"D:\\path\\venv\\Scripts\\python.exe\" \"D:\\path\\plugins\\quench-dev-tasks\\server\\hooks\\file_scope_guard.py\""
}
```

#### 【分步改造指引】
1. 从 `scripts/install.py` 中移除 `_wrap_cmds` 递归函数及调用；
2. 从 `plugins/quench-dev-tasks/scripts/init_project.py` 中移除 `_wrap_cmds` 递归函数及调用；
3. 修改 `plugins/quench-dev-tasks/server/tests/test_init_project.py` 中的 `test_hooks_json_windows_quote_wrapping`，验证无论何种平台均生成标准的 `"python" "script"` 格式，且在 `shell=True` 下可成功执行；
4. 运行 `python scripts/install.py` 刷新本地 `.agents/hooks.json`；
5. 更新 `CHANGELOG.md`；
6. 运行全量 pytest 验证。

#### 【防御与边缘校验】
- **空格路径支持**：每个独立参数（解释器路径与脚本路径）依然被各自独立的双引号包裹，确保在包含空格的路径（如 `C:\Program Files\...`）下解析正常；
- **Node.js exec 兼容**：确保 Node.js `child_process.exec` 调用命令时不产生语法错误。

#### 【DoD 验证命令】
```powershell
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_init_project.py -v
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests -v
```
