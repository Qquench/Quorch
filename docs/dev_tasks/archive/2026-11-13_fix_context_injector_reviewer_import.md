# 2026-11-13_fix_context_injector_reviewer_import Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-13

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 修复 context_injector 中 ReviewerClient 幽灵模块导入导致外部 API 状态误判

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/hooks/context_injector.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py
```

#### 【缺陷根因与修改目标】
```
根因：plugins/quench-dev-tasks/server/hooks/context_injector.py 第 55 行仍写为 `from reviewer_client import ReviewerClient`，但服务端已重命名为 `reviewer_engine.py`，导致 `_is_external_api_available` 每次均静默捕获 `ModuleNotFoundError` 并返回 `False`。这会令 PreInvocation 与 Stop Hook 误判外部 Reviewer API 不可用，进而将配置了外部 API 的工作区强制判定为 `auto_fallback -> inverted` 模式，与 `dev_tasks_status` MCP 工具（从 `reviewer_engine` 导入 `ReviewerClient`）行为不一致。
目标：将 `context_injector._is_external_api_available` 中的导入路径修正为 `from reviewer_engine import ReviewerClient`（与 `server.py` 保持一致），并补充不依赖 mock `_resolve_harness_baton` 的回归单测，确保 `_is_external_api_available` 能正确识别已配置的外部引擎并返回 `True` / 未配置时返回 `False`。
```

#### 【目标签名与类型契约】
```python
def _is_external_api_available(workspace_root: str) -> bool:
    """Detect whether an external ReviewerClient endpoint is configured and reachable via key/local URL."""
```

#### 【分步改造指引】
1. 打开 `plugins/quench-dev-tasks/server/hooks/context_injector.py`，定位 `_is_external_api_available`（约第 52-61 行），将 `from reviewer_client import ReviewerClient` 修改为 `from reviewer_engine import ReviewerClient`；保持 `except Exception: return False` 的 Fail-Safe 行为与函数签名不变（需核对 `provider == "none"` 时 `client.is_available()` 与 `client.resolve_api_key()` 行为：若 `provider` 为 `"none"` 或未配置 key/本地地址，不得误返回 `True`，必要时可参考 `server._is_external_api_available` 或在未设置 `provider` 时显式拦截 `re_cfg.provider in ("none", "", None)`）。
2. 在 `plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py` 中新增两条回归测试：
   - 正常配置外部 API（如临时 `.agents/quench_stack.local.yaml` + `monkeypatch.setenv` 设置对应 API Key，或本地端点）时，`_is_external_api_available(str(ws))` 返回 `True`，且 `_resolve_harness_baton` 不会错误回落为 `inverted_main_reviewer`；
   - 未配置外部引擎（`provider: "none"` 且无可用本地端点/Key）时，`_is_external_api_available(str(ws))` 返回 `False`。

#### 【防御与边缘校验】
- 保持 Hook 5 秒超时与 stdout JSON-RPC 纯净契约：`_is_external_api_available` 禁止向 stdout 打印任何诊断信息，异常仅在 `QUENCH_HOOK_DEBUG` 时输出到 `stderr` 或静默返回 `False`。
- 当 `quench_stack.yaml` 中 `provider: "none"` 且不存在 `.agents/quench_stack.local.yaml` 覆盖时，即使系统环境中碰巧存在 `DEEPSEEK_API_KEY` 等环境变量，也不应误判为可用（需确保 `client.is_available()` / `provider` 校验严谨）。
- 测试需使用 `tmp_path` 与 `monkeypatch` 完全隔离环境变量与磁盘状态，不依赖本机真实 API Key 或注册表。

#### 【DoD 验证命令】
```bash
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; python -m pytest plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py -v
```

---
