# Quench 配置与清单说明手册 (`quench_stack.yaml`)

[English](configuration.md) | [简体中文](configuration_zh.md)

本文档为在项目中使用 **Quench Dev-Orchestrator (`quorch`)** 治理框架时的配置参考手册，详细解读 `.agents/quench_stack.yaml` 各字段含义与最佳实践。

---

## 1. 架构总览与定位

被 Quench 治理的任何技术栈代码库，均通过根目录下的 `.agents/quench_stack.yaml` 声明边界约束、单测入口与审查模型调度。  
该设计使得治理引擎自身与被治理项目的业务逻辑与编程语言完全解耦。

```text
<目标项目根目录>/
├── .agents/
│   ├── plugins.json            # 注册 quench-dev-tasks 插件
│   ├── quench_stack.yaml       # 项目治理清单 (Single Source of Truth)
│   └── logs/reviewer/          # 审查大脑实时思考流落盘目录 (自动生成)
│       └── thinking.log
└── docs/dev_tasks/             # 任务单流转工作区
    └── archive/                # 已完成任务归档区
```

---

## 2. 核心元数据配置

| 字段名 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `schema_version` | `string` | `"1.0"` | 配置文件架构版本（由配置迁移引擎自动维护，勿随意手工修改）。 |
| `project_name` | `string` | **必填** | 项目或服务的唯一标识名称。 |
| `dev_tasks_dir` | `string` | `"docs/dev_tasks"` | 活跃开发任务 Markdown 文档存放的相对路径。 |
| `archive_dir` | `string` | `"docs/dev_tasks/archive"` | 已闭环任务单归档的相对路径。 |
| `changelog_path` | `string` | `"CHANGELOG.md"` | 项目版本变更日志文件路径。 |
| `test_runner` | `string` | `null` | 默认自动化单测执行命令（例如 `pytest tests/ -v` 或 `npm test`），用于 DoD 门禁校验。 |
| `test_dir` | `string` | `"tests"` | 主要测试套件目录。 |
| `architecture_doc`| `string` | `null` | 可选系统架构规格说明书路径（如 `docs/architecture.md`）。 |

---

## 3. 工程规范与边界约束 (`constraints`)

`constraints` 列表用于向 AI Agent 的系统提示词中注入强领域规则，在任务提单、规约生成及代码审查全周期持续生效：

```yaml
constraints:
  - "所有核心业务逻辑与算法变更必须包含自动化单元测试"
  - "公共 API 与数据结构变更必须保持向后兼容或提供平滑迁移方案"
  - "严禁在代码中硬编码任何生产密码、私钥或 API 密钥"
```

---

## 4. 治理边界与三层快速通道

Quench 采用**三层纵深防御体系**防范越界修改：

```yaml
# 第一层：静态白名单 (匹配该 Glob 模式的文件免除任务状态机管控)
fast_track_rules:
  allow_untracked_patterns:
    - "docs/**"
    - "*.md"
    - "notes/**"

# 可选：显式声明代码受管边界
governance_scope:
  # 🔴 生产受管范围 (严格执行单核状态机与【涉及文件】白名单拦截)
  managed_paths:
    - "src/**"
    - "plugins/**"
    - "package.json"
  # 🟢 免管放行范围 (文档与非代码资产自由放行)
  unmanaged_paths:
    - "docs/**"
    - "*.md"
```

- **第一层（静态白名单）**：`allow_untracked_patterns` 中声明的文件天然豁免 PreToolUse 拦截。保持空单起步，按需沉淀。
- **第二层（会话级临时旁路）**：模型可主动申请 `dev_tasks_set_bypass`，用于极轻量修补（如修复单点样式、文档排版）。附带严格会话锁与 4 小时硬性过期。
- **第三层（交互决策弹窗）**：当模型尝试触碰未经授权的代码文件时，IDE 触发弹窗并显示修改理由，由开发者人工裁决是否允许。

---

## 5. 审查模型与外置大脑调度 (`reviewer_engine`)

`reviewer_engine` 模块实现了“高阶战略审查 (Reviewer)”与“日常敏捷编码 (Runner)”的彻底解耦。支持多厂商 API 直连、企业代理兼容与流式思维链审计。

```yaml
reviewer_engine:
  # 调度模式: "auto" | "subagent" | "engine" | "manual"
  mode: "auto"

  # 瀑布回退顺序（当前置策略不可用时自动向下回退）
  strategy_order:
    - "subagent"
    - "engine"
    - "manual"

  # 上游 API 厂商: "deepseek" | "openai" | "ollama" | "custom" | "none"
  provider: "deepseek"

  # 模型标识
  model: "deepseek-flash"

  # 存放 API 密钥的环境变量名称（严禁在此硬编码明文密钥！）
  api_key_env: "DEEPSEEK_API_KEY"

  # API 服务端点
  base_url: "https://api.deepseek.com"

  # 是否开启思维链思考流 (reasoning_content) 实时输出
  thinking: true

  # 推理算力预算: "low" | "medium" | "high"
  reasoning_effort: "high"

  # 单次网络请求超时时间（秒）
  timeout_seconds: 60

  # 遇到瞬态网络抖动最大重试次数
  max_retries: 2

  # 智能规约生成时最大工具调用轮数
  max_tool_hops: 3
```

### 厂商支持矩阵

| Provider | 典型模型 | Base URL | 核心特性 |
| :--- | :--- | :--- | :--- |
| **`deepseek`** | `deepseek-chat`, `deepseek-reasoner`, `deepseek-flash` | `https://api.deepseek.com` | 原生提取 `reasoning_content` 思维链；自动解析 Prompt Cache 命中率与计费 Token。 |
| **`openai`** | `gpt-4o`, `gpt-4o-mini`, `o1`, `o3-mini` | `https://api.openai.com/v1` | 标准 OpenAI 接口兼容。 |
| **`ollama`** | `deepseek-r1:14b`, `qwen2.5-coder:14b` | `http://localhost:11434/v1` | 100% 离线私有化部署，本地显卡推理，零外部 API 依赖。 |
| **`subagent`** | 宿主 IDE 内置子代理 (`reviewer`) | N/A | 依托 IDE 自带订阅额度（如 Antigravity Pro），无需额外 API 支出。 |
| **`manual`** | 人工架构师手动评审 | N/A | 优雅回退，输出结构化的人机协作审查交接卡。 |

---

## 6. 实时思考流落盘与可观测性

当高阶推理模型流式输出思维链时，Quench 内置引擎自动保障：
1. 实时流式分块写入 `.agents/logs/reviewer/thinking.log`；
2. **1024KB 硬封顶安全轮转**（单文件轮转备份 `thinking.log.1`，杜绝磁盘暴涨）；
3. 跨分块正则流式敏感信息脱敏（对 API 密钥、私钥凭据自动打码）；
4. 维持约 1.0s 低频进度心跳，100% 保持 MCP `sys.stdout` JSON-RPC 通信纯净无污染。

---

## 7. 终端体检与健康诊断

开发者可通过命令行随时核验配置与网络连通性：

```bash
# 检查基础运行环境与 quench_stack.yaml 语法
quench check

# 专项体检 Reviewer 引擎 API 连通性、密钥有效性与网络延迟
quench check --reviewer
```
