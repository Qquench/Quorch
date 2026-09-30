# 2026-09-30_remove_vendor_presets Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-09-30

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 移除 project_config.py 中的厂商预注册表、默认模型与别名映射，实现纯声明式配置

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py
```

#### 【缺陷根因与修改目标】
```
【缺陷根因】\nproject_config.py 中第 253 ~ 293 行维护了硬编码的厂商预设表 (PROVIDER_PRESETS)、厂商别名 (PROVIDER_ALIASES)、默认模型 (DEFAULT_MODEL_BY_PROVIDER) 以及模型别名 (MODEL_ALIASES)。这些内容在 AI 模型快速迭代背景下容易过时且违背了底层中立设计原则。\n\n【修改目标】\n1. 清理 project_config.py 中过时的硬编码厂商映射表（DEFAULT_MODEL_BY_PROVIDER、MODEL_ALIASES、PROVIDER_ALIASES、PROVIDER_PRESETS 清空或移除），使模型和端点完全由用户在 quench_stack.yaml 中声明式指定；\n2. 简化 normalize_model_identity 为纯基础清洗（大小写规范化与去空格），不再进行预设模型和别名替换；\n3. 保留 ProviderPreset 和 resolve_preset 签名（返回 None/空）以保障核心功能与老接口调用兼容；\n4. 同步更新工厂中立测试与模型标识测试，确保测试套件 100% 通过。
```

#### 【目标签名与类型契约】
```
# project_config.py\nPROVIDER_PRESETS: Mapping[str, ProviderPreset | None] = MappingProxyType({})\nPROVIDER_ALIASES: Mapping[str, str] = MappingProxyType({})\n\ndef normalize_model_identity(provider: str, model: str) -> tuple[str, str]: ...\ndef resolve_preset(provider: str) -> ProviderPreset | None: ...
```

#### 【分步改造指引】
1. 在 plugins/quench-dev-tasks/server/project_config.py 中将 PROVIDER_PRESETS 与 PROVIDER_ALIASES 设为空 MappingProxyType({})，移除 DEFAULT_MODEL_BY_PROVIDER 与 MODEL_ALIASES；\n2. 改造 normalize_model_identity 函数，仅执行 strip() 与 lower() 归一化，移除对别名表与默认模型表的依赖；\n3. 更新 create_reviewer_client 中提示文案，去除预设列表残留依赖；\n4. 适配 test_reviewer_factory_neutrality.py 与 test_consultation_runner_profile.py 中针对别名映射与内置预设的断言；\n5. 运行 pytest 验证全量测试绿灯。

#### 【防御与边缘校验】
- 核心功能零破坏：用户显式配置 base_url 时 ReviewerClient 正常创建，未配置时明确报 ReviewerNotConfiguredError\n- 接口兼容性：保留 ProviderPreset 与 resolve_preset 符号导出，避免第三方或旧模块出现 ImportError\n- 同模型预警仍生效：runner 与 reviewer 指定相同模型字符串时，check_self_verification_warning 仍正常触发\n- 代码中立性提升：彻底消除核心文件中的硬编码厂商模型字面量

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_factory_neutrality.py -v\npytest plugins/quench-dev-tasks/server/tests/test_consultation_runner_profile.py -v\npytest plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py -v
```

---

