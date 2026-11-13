# 2026-11-13_fix_context_injector_config_sync_import Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-13

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 消除 context_injector 中 config_sync 静态导入缺失报错

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/hooks/context_injector.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py
```

#### 【缺陷根因与修改目标】
```
根因：context_injector.py 在第 215 行和第 291 行直接使用了 from config_sync import ...，而 config_sync 位于 plugins/quench-dev-tasks/scripts/，不在 server 包的静态导入根路径中，导致 Pyrefly / IDE LSP 报 missing-import 诊断错误。同时，第 291 行仅为原子写入 stop_guard json，依赖外部脚本模块引入不必要的耦合。
目标：在 context_injector.py 中实现本地轻量 _atomic_write_json 辅助函数替代外部脚本导入，并将 auto_heal_configs 调用统一为与第 340 行及 server.py 一致的动态导入 __import__('config_sync')，彻底消除 LSP 导入缺失诊断，并补充单测确保 stop guard 原子写入与自愈调用行为一致。
```

#### 【目标签名与类型契约】
```
def _atomic_write_json(filepath: str, data: Any) -> None
```

#### 【分步改造指引】
1. 在 context_injector.py 中新增私有 _atomic_write_json 函数，采用 tempfile.mkstemp 与 os.replace 实现本地原子化写入，移除第 291 行对 config_sync.atomic_write_file 的静态导入。
2. 将第 215 行的 from config_sync import auto_heal_configs 改为与第 340 行一致的 try: __import__('config_sync').auto_heal_configs(workspace_root=workspace_root, quiet=True) 动态加载，避免静态导入器解析报错。
3. 在 test_context_injector_autopilot_harness.py 中补充单测，验证 _atomic_write_json 在正常和异常情况下的原子替换及清理逻辑，确保 stop guard 逻辑完整。

#### 【防御与边缘校验】
保持 Hook 纯净契约：零 stdout 输出，异常仅在调试模式输出至 stderr 或静默容错。
确保临时文件在写入失败时正确清理，避免残留垃圾文件。
单测使用 tmp_path 完全隔离测试文件与环境。

#### 【DoD 验证命令】
```bash
.venv/Scripts/python -m pytest plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py -v
```

---

