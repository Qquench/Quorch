# 2026-10-01_ci_fix_reviewer_client_available Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-01

---

## Task List & Status / 任务清单与状态

### 任务 1 ✔️ 已完成 — 修复 CI 本地端点可用性断言与状态机临时文件范围核对隔离

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py
[MODIFY] plugins/quench-dev-tasks/server/state_machine.py
```

#### 【缺陷根因与修改目标】
```
【缺陷根因】
1. commit 1c3a033 依照 INV-5 供应商中立性原则清空了 PROVIDER_PRESETS 中的硬编码厂商预设端点，所有 ReviewerClient 均需声明式配置 base_url；
2. test_handoff_protocol.py::test_reviewer_client_is_available_ollama 在构造 ReviewerEngineConfig 时未显式配置 base_url，导致 base_url 为空；本地 Windows 环境因注册表穿透读取到了遗留 API Key 隐式掩盖了该缺陷，但在无 API Key 的 CI 环境（Ubuntu 与 Windows runner）中，_is_local_endpoint("") 为 False 且无 key，is_available() 返回 False 导致断言失败；
3. state_machine.py::_verify_scope_reconciliation 在任务文件位于外部临时目录（如 pytest tempfile）且 workspace_root 未传入时，退化为使用 os.getcwd() 触发工作区物理对账，与工作区遗留基线发生碰撞。

【修改目标】
1. 在 test_handoff_protocol.py 中为本地端点测试显式声明 base_url="http://localhost:11434/v1"，重命名为符合供应商中立性规范的 test_reviewer_client_is_available_local_endpoint（保留原名称兼容或指向同一逻辑），并增加 registry/env 隔离断言；
2. 在 state_machine.py 中增强防御校验：当任务文件位于工作区外部时跳过物理工作区对账，彻底隔离单元测试临时文件。
```

#### 【目标签名与类型契约】
```
def test_reviewer_client_is_available_ollama(monkeypatch): ...
def _verify_scope_reconciliation(filepath: str, task_id: str, workspace_root: Optional[str] = None) -> None: ...
```

#### 【分步改造指引】
1. 在 plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py 中，更新 test_reviewer_client_is_available_ollama 用例，显式指定 base_url='http://localhost:11434/v1'，并使用 patch 确保注册表与环境无 API Key 时仍稳定返回 True；
2. 在 plugins/quench-dev-tasks/server/state_machine.py 中，完善 _verify_scope_reconciliation 逻辑，若 filepath 不在 workspace_root 目录下则直接返回，避免单测临时文件污染；
3. 运行全量 DoD 测试确保 100% 绿灯。

#### 【防御与边缘校验】
1. 中立性守护（INV-5）：测试断言依赖声明式 base_url 而非内置硬编码厂商预设；
2. 环境封闭性：通过 patch 隔离 Windows 注册表与环境变量，确保在零 API Key 的纯净 CI runner 下可重复稳定通过；
3. 测试文件隔离：临时目录任务文件绝对不会误触发宿主工作区的物理对账。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py -v
pytest plugins/quench-dev-tasks/server/tests/test_state_machine.py -v
pytest plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py -v
```

---

