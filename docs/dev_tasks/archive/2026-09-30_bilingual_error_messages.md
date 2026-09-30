# 2026-09-30_bilingual_error_messages Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-09-30

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 升级 project_config.py 中的错误与告警信息为双语/英文版

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
```

#### 【缺陷根因与修改目标】
```
【缺陷根因】\nproject_config.py 中的安全防御异常与配置解析告警信息此前均为纯中文，纯英语开发者与英语 LLM 在排查错误或解析异常时存在理解障碍。\n\n【修改目标】\n1. 将 project_config.py 内的异常与告警信息升级为英文在前、中文对照在后的国际化双语规范，提升英语友好度；\n2. 确保全部现有单测套件 100% 保持通过，做到零破坏性兼容。
```

#### 【目标签名与类型契约】
```
# project_config.py: 保持所有异常类型与调用签名不变，仅丰富异常消息文本为英文首位格式
```

#### 【分步改造指引】
1. 在 plugins/quench-dev-tasks/server/project_config.py 中更新 _reject_inline_credentials 和 _validate_credentials_security 的 ConfigError 描述为英中文双语；\n2. 更新 create_reviewer_client 中的 ReviewerNotConfiguredError 描述为英中文双语；\n3. 更新 load_project_config 中的 FileNotFoundError、ValueError、ConfigError 与 warnings.warn 为英中文双语；\n4. 运行 pytest 单测套件验证全部通过。

#### 【防御与边缘校验】
- 异常语义保持：所有异常类型（ConfigError、ReviewerNotConfiguredError、ValueError、FileNotFoundError）完全保持不变\n- 单测向下兼容：采用英文在前、中文对照在后的双语模式，既满足英语环境需要，又保证现有单测断言 100% 绿灯通过\n- 边界与安全校验：明文凭据拦截与 base_url 格式校验逻辑零劣化

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_project_config.py -v\npytest plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py -v
```

---

