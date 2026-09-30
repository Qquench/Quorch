# 2026-10-01_fix_reviewer_observability_mock_url Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-01

---

## Task List & Status / 任务清单与状态

### 任务 1 ✔️ 已完成 — 修复 test_reviewer_observability 模拟测试中的 base_url 与 dummy 模型名称

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py
```

#### 【缺陷根因与修改目标】
```
【根因分析】
在此前剥离硬编码模型供应商预设（1c3a033）后，ReviewerEngineConfig 不再具有默认的 base_url（回退为空字符串 ""）。test_reviewer_observability.py 中的两个模拟测试用例未显式传入 base_url，导致 _normalize_chat_endpoint 拼出裸路径 "/chat/completions"，引发 urllib.request.Request 抛出 ValueError: unknown url type: '/chat/completions'。同时，测试用例中仍残留具体供应商模型名称。

【修改目标】
为 test_reviewer_observability.py 中的 test_deepseek_client_streaming_and_soft_ceiling 与 test_deepseek_client_soft_ceiling_trigger 显式注入标准 Mock URL base_url="https://api.example.com/v1"，并将 model 改为中立的 "dummy-reasoning-model"。
```

#### 【目标签名与类型契约】
```
无类型契约变更，仅测试入参补全。
```

#### 【分步改造指引】
修改 test_reviewer_observability.py 中的 test_deepseek_client_streaming_and_soft_ceiling，在 ReviewerEngineConfig 中增加 base_url="https://api.example.com/v1"，并将 model 改为 "dummy-reasoning-model"
修改 test_reviewer_observability.py 中的 test_deepseek_client_soft_ceiling_trigger，在 ReviewerEngineConfig 中增加 base_url="https://api.example.com/v1"，并将 model 改为 "dummy-reasoning-model"

#### 【防御与边缘校验】
确保使用 RFC 2606 标准测试保留域名 https://api.example.com/v1，避免真实网络外发与解析异常
运行 test_reviewer_observability.py 确保软上限与流式测试 100% 绿灯通过
验证 python -m compileall -q 语法预检无误

#### 【DoD 验证命令】
```bash
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; pytest plugins/quench-dev-tasks/server/tests/test_reviewer_observability.py -v
python -m compileall -q plugins/quench-dev-tasks/server
```

---

