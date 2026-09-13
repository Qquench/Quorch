# 升级 AntigravityAdapter 决策契约为 force_ask

> **执行模型须知**
> - 严格按照每条任务的【分步改造指引】顺序执行
> - 不得修改任务未涉及的文件
> - 保留所有现有注释和文档字符串（除非明确要求修改）
> - **改逻辑必加单测断言**：在测试目录追加断言，杜绝回归
> - 每完成一条任务，更新其状态为 `🔨 执行中`，完成后更新为 `✔️ 已完成`

- **创建日期**：2026-09-13

---

## 任务清单与状态


### 任务 1.1 ✔️ 已完成 — 升级 AntigravityAdapter 决策契约为 force_ask 并同步单测

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/adapters/antigravity_adapter.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_adapters.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_hooks.py
[MODIFY] CHANGELOG.md
```

#### 【缺陷根因与修改目标】
根因：
Antigravity IDE 官方 PreToolUse 规范中定义：
- `"ask"`：向用户请求权限，但尊重“始终允许 / Always Allow”缓存。若用户或工作区对 `replace_file_content` / `write_to_file` 等基础工具已开启信任，返回 `"ask"` 会直接命中缓存而静默放行，导致拦截弹窗被绕过；
- `"force_ask"`：无条件强制唤起交互确认弹窗，忽略任何已缓存的权限信任。

目标：
1. 改造 `plugins/quench-dev-tasks/server/adapters/antigravity_adapter.py`：在 `AntigravityAdapter.format_decision` 中将内部状态机给出的 `ask` 决策统一转换为 `force_ask`；
2. 同步更新单测：更新 `test_adapters.py` 与 `test_hooks.py` 中对 Antigravity 适配器返回 `decision` 的断言为 `force_ask`；
3. 更新 `CHANGELOG.md` 记录加固内容。

#### 【目标签名与类型契约】
```python
# plugins/quench-dev-tasks/server/adapters/antigravity_adapter.py
def format_decision(self, decision: str, reason: str = "") -> dict:
    """格式化为 Antigravity 专有 JSON 报文对象与弹窗契约。"""
    d = decision.strip().lower()
    if d == "allow":
        return {"decision": "allow"}

    # 核心加固：Antigravity IDE 中必须使用 force_ask 才能穿透 Always Allow 缓存强制弹窗
    if d == "ask":
        d = "force_ask"

    out = {"decision": d}
    if reason:
        out["reason"] = reason
    return out
```

#### 【分步改造指引】
1. 修改 `plugins/quench-dev-tasks/server/adapters/antigravity_adapter.py` 中的 `format_decision` 方法，将 `ask` 映射为 `force_ask`；
2. 更新 `plugins/quench-dev-tasks/server/tests/test_adapters.py`：
   - 验证 `AntigravityAdapter.format_decision("ask", ...)` 返回 `{"decision": "force_ask", ...}`；
   - 验证 GenericCliAdapter 与 CursorAdapter 行为不受影响（解耦隔离）；
3. 更新 `plugins/quench-dev-tasks/server/tests/test_hooks.py`：
   - 将所有针对 `file_scope_guard.py` 在未纳管状态下预期的 `res["decision"] == "ask"` 断言升级为 `res["decision"] == "force_ask"`；
4. 更新 `CHANGELOG.md`；
5. 运行 pytest 验证全量通过。

#### 【防御与边缘校验】
- **跨宿主适配器隔离**：`force_ask` 是 Antigravity 特有的契约，严禁污染 `base_adapter.py`、`generic_cli_adapter.py` 或 `cursor_adapter.py`；
- **状态机与日志纯洁性**：状态机内部与 `file_scope_guard.py` 的事件日志依旧使用 `ask` / `ASK_MODAL`，仅在与宿主环境通信的 Adapter 出口处转换为 `force_ask`。

#### 【DoD 验证命令】
```powershell
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_adapters.py plugins/quench-dev-tasks/server/tests/test_hooks.py -v
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests -v
```
