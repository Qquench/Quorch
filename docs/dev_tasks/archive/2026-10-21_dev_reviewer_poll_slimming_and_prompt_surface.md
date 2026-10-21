# 2026-10-21_dev_reviewer_poll_slimming_and_prompt_surface Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-21

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 物理移除 dev_reviewer_poll 的 raw_text 双投影并恢复单一结构化返回契约

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/server/reviewer_jobs.py
[MODIFY] dev_tasks_mcp_specification.md
[MODIFY] docs/architecture/README.md
[MODIFY] docs/configuration.md
[MODIFY] README.md
[MODIFY] README_zh.md
[MODIFY] docs/architecture/ide_tool_schemas.json
[MODIFY] CHANGELOG.md
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md
[MODIFY] plugins/quench-dev-tasks/rules/dev-tasks-discipline.md
[MODIFY] docs/ci_incident_tracker_and_compatibility_guide.md
[MODIFY] plugins/quench-dev-tasks/scripts/rules_exporter.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_rules_exporter.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_tools.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_spec_param_defaults_contract.py
```

#### 【缺陷根因与修改目标】
```
1. 缺陷根因：dev_reviewer_poll 中历史引入的 raw_text 参数使接口在 dict 与 str 之间产生双投影分叉；由于 IDE 在注入 System Prompt 时会剥离 default 属性，且此前函数缺少 Args: 块导致参数说明为空，大模型在阅读到 docstring 及 docs/configuration.md 中的 raw_text=True 示例后，极易主动传入 raw_text=True。而在现有独立审计日志（verdicts.jsonl、JobRecord、session log）已完备留存历史的背景下，raw_text 纯属表现层冗余。
2. 修改目标：物理移除 dev_reviewer_poll 中的 raw_text 形参及全部字符串投射分支，将返回值强类型彻底收敛为 dict[str, Any]；为函数补齐标准的 Google-style Args: 说明块；清理所有文档及示例中的 raw_text=True 残留，更新 CHANGELOG.md 与兼容性指南，为 rules_exporter.py 补充 --check 只读幂等校验并重新导出 ide_tool_schemas.json。
```

#### 【目标签名与类型契约】
```
async def dev_reviewer_poll(
    workspace_root: str,
    job_id: str,
    session_id: str,
    wait_max_s: int = 0,
) -> dict[str, Any]:
    """Poll status or result of a background Reviewer task.
    Enforces 1KB non-terminal snapshot contract.

    轮询 Reviewer 异步推演任务：强约束 1KB 极简白名单契约，恒定返回结构化字典。

    Args:
        workspace_root: Root path of the target workspace / 项目根目录绝对路径。
        job_id: Target job ID to poll / 待轮询的任务ID。
        session_id: Caller session ID for multi-session authorization / 会话隔离标识符。
        wait_max_s: Server-side long polling wait timeout in seconds (0-25) / 服务端长轮询最大挂起等待秒数。
    """
```

#### 【分步改造指引】
在 plugins/quench-dev-tasks/server/server.py 中删除 dev_reviewer_poll 的 raw_text 参数及内部所有 if raw_text 分支，返回类型注解改为 dict[str, Any]；为该函数补全完整的 Args: 块，明确说明各参数语义并声明恒定返回结构化字典。
在 plugins/quench-dev-tasks/server/reviewer_jobs.py 中重构 poll 与 project_poll_result 方法，移除 raw_text 形参及纯文本心跳/Markdown 直出分支，终态统一走 project_terminal（确认并锚定保留 MAX_FINDINGS_CHARS = 40000 截断逻辑），非终态统一走 project_nonterminal。
清理生产文档与规则：更新 dev_tasks_mcp_specification.md（移除 §4.1 默认值 JSON 中的 raw_text 项）、docs/architecture/README.md、docs/configuration.md（重写示例为从字典中提取 result.findings）、README.md、README_zh.md、SKILL.md、dev-tasks-discipline.md 与 docs/ci_incident_tracker_and_compatibility_guide.md；在 CHANGELOG.md 中记录 Breaking Change 与迁移说明；为 rules_exporter.py 增加 --check 只读幂等校验模式并在 test_rules_exporter.py 中补充测试，优先执行只读校验，严禁在【涉及文件】未覆盖产物的情况下触发脚本写盘（杜绝 ScopeViolationError）。
更新测试用例：在 test_server_tools.py 中新增对显式传入 raw_text=True 被拒绝抛出异常的物理断言；在 test_reviewer_jobs.py 中新增 40001 字符 findings 截断断言；在 test_reviewer_poll_progress.py、test_anti_roleplay_discipline_contract.py、test_spec_param_defaults_contract.py 中删除 raw_text 测试分支，保留所有 INV-3 / INV-4 核心断言。
运行 python scripts/export_ide_schemas.py --write 重新生成 docs/architecture/ide_tool_schemas.json，并执行 DoD 命令确保 100% 通过。

#### 【防御与边缘校验】
消除类型分叉：确保所有执行分支严禁返回 str，包括 COMPLETED 与 DEGRADED 终态，全量统一为严格按照 POLL_TERMINAL_FIELDS 或 POLL_NONTERMINAL_FIELDS 判别的 dict。
40k 预算防线强化断言：构造 len(findings) == 40001 的输入，断言 len(result["findings"]) == 40000 且 result["truncated"] is True；并追加多字节边界用例（在第 40000 字节处放置 CJK/emoji），断言截断结果可 utf-8 正常解码，不得产生半个码位或孤立代理项。
未知参数拒绝断言：未知参数拒绝断言必须锚定在 dev_reviewer_poll.fn 上（而非 FunctionTool 包装对象），并断言抛出 TypeError 且异常消息包含 "raw_text" / "unexpected keyword argument"；禁止以 "'FunctionTool' object is not callable" 形式的 TypeError 作为通过证据（杜绝 false-green）。
降级契约（INV-3）与纯净度（INV-4）：test_anti_roleplay_discipline_contract.py 仅删除与 raw_text 相关的用例，保留全部 INV-3（findings==""）和 INV-4（stdout 纯净度）断言并纳入 DoD。
快照守护：快照变更通过 scripts/export_ide_schemas.py 导出并核对 diff，更新 dev_tasks_mcp_specification.md §4.1 参数默认值 JSON，严禁未经 Reviewer 审查绕过 schema 快照闸门。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_server_tools.py -k "reviewer_poll" -q
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py -k "poll" -q
pytest plugins/quench-dev-tasks/server/tests/test_reviewer_poll_progress.py -q
pytest plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py -q
pytest plugins/quench-dev-tasks/server/tests/test_spec_param_defaults_contract.py -q
pytest plugins/quench-dev-tasks/server/tests/test_rules_exporter.py -q
pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q
python plugins/quench-dev-tasks/scripts/rules_exporter.py --check
python -c "import inspect; from typing import get_type_hints; import sys; sys.path.insert(0, 'plugins/quench-dev-tasks/server'); from server import dev_reviewer_poll as _t; fn = getattr(_t, 'fn', _t); sig = inspect.signature(fn); assert 'raw_text' not in sig.parameters, f'raw_text leaked: {sig}'; ret = get_type_hints(fn).get('return'); assert ret is dict or getattr(ret, '__origin__', None) is dict, f'return not dict: {ret!r}'; print('signature ok:', sig)"
python scripts/export_ide_schemas.py --check
pytest -m tier1_fast -q
```

---

### 任务 1.2 ✔️ 已完成 — 新增 Prompt-Surface 契约门禁（P1~P5），防止 docstring / 文档示例 / IDE schema 再次漂移

#### 【涉及文件】
```
[NEW] scripts/check_prompt_surface.py
[NEW] plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
[MODIFY] plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py
[MODIFY] dev_tasks_mcp_specification.md
[MODIFY] docs/architecture/README.md
[MODIFY] CHANGELOG.md
```

#### 【缺陷根因与修改目标】
```
1. 缺陷根因：现有门禁仅校验 Python 签名与规范默认值快照，未覆盖“模型引导面”——docstring 缺 Args 块、IDE 剥离 default 后参数描述为空、文档示例残留已删除关键字——三者均处于防线盲区。
2. 修改目标：新增纯 AST 静态门禁 check_prompt_surface.py（P1~P5），覆盖 docstring 完备性、派生快照描述完备性、活文档示例关键字残留、Markdown 代码块调用参数合法性、历史文档豁免合规性；以黑盒 subprocess 断言接入 git_pre_commit_guard.py（R3/R2/M4/D1~D3 决策已固化，杜绝门禁自锁与 false-green）。在 server.py 中补齐其余工具缺失的 Args: 块。
```

#### 【目标签名与类型契约】
```
# scripts/check_prompt_surface.py
from __future__ import annotations
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterable, Mapping, Sequence

EXIT_OK: Final[int] = 0
EXIT_VIOLATION: Final[int] = 1
EXIT_INTERNAL: Final[int] = 2

# 历史/审计文档白名单：新增条目须经 Reviewer 批准，并受单测锚定（R3）
HISTORICAL_ALLOWLIST: Final[frozenset[str]] = frozenset({
    "CHANGELOG.md",
    "docs/ci_incident_tracker_and_compatibility_guide.md",
})
# 任务单与归档目录一律排除，防止门禁自锁（R2）
EXCLUDED_PATH_PREFIXES: Final[tuple[str, ...]] = ("docs/dev_tasks/", "docs/archive/")
EXEMPTION_MARKER: Final[str] = "quench-prompt-surface:historical"
CALL_KEYWORD_RE: Final[re.Pattern[str]] = re.compile(r"\braw_text\s*=\s*(?:True|False)\b")
MIN_PARAM_DESC_CHARS: Final[int] = 8

@dataclass(frozen=True)
class LintFinding:
    rule: str
    file_path: str
    line_number: int
    message: str

def extract_server_signatures(server_py: Path) -> dict[str, frozenset[str]]: ...
def extract_mcp_tool_names(server_py: Path) -> frozenset[str]: ...
def check_docstring_args(server_py: Path, expected_tools: frozenset[str]) -> list[LintFinding]: ...
def check_schema_descriptions(snapshot: Path, expected_tools: frozenset[str]) -> list[LintFinding]: ...
def check_live_doc_call_keywords(doc_roots: Sequence[Path]) -> list[LintFinding]: ...
def check_example_call_keywords(doc_roots: Sequence[Path],
                                signatures: Mapping[str, frozenset[str]]) -> list[LintFinding]: ...
def check_historical_allowlist_discipline(doc_roots: Sequence[Path]) -> list[LintFinding]: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

#### 【分步改造指引】
新建 scripts/check_prompt_surface.py：实现 P1（AST 提取 @mcp.tool 装饰函数集合 + 形参集合，断言与 tool_surface_constants.TOOL_COUNT 一致，杜绝硬编码 16 造成的第二 SSOT；逐个校验 docstring 含 Google-style Args: 块且覆盖全部形参，忽略 ctx/self 注入参数）。
实现 P2：读取 ide_tool_schemas.json，先校验 envelope 的 version/tool_count 与 tool_surface_constants 一致（新鲜度前置，M2）；再逐个参数断言 description 非空且长度 >= MIN_PARAM_DESC_CHARS。
实现 P3 / P4 / P5 三个独立检查器：
- P3 作用于“活文档”白名单（README.md、README_zh.md、docs/configuration.md、dev_tasks_mcp_specification.md、docs/architecture/README.md、SKILL.md、rules/dev-tasks-discipline.md），在代码围栏内匹配 CALL_KEYWORD_RE，一律阻断（示例即引导面）。
- P4 作用于全部 Markdown 代码围栏但排除 EXCLUDED_PATH_PREFIXES 与 HISTORICAL_ALLOWLIST；仅做“未知关键字检测”（提供的关键字必须是该工具签名形参的子集），不校验必填完备性、不校验位置参数，遇到 *args/**kwargs 展开、非 Python 语言标注块直接跳过；围栏首行含 EXEMPTION_MARKER 时跳过该块。
- P5 断言 HISTORICAL_ALLOWLIST 内文件若出现 CALL_KEYWORD_RE，必须同行或上一行含 EXEMPTION_MARKER，否则阻断 —— 既保留审计事实，又不允许静默残留。
接入 plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py：以 check_prompt_surface.main(["--check"]) 形式调用，失败即阻断提交；门禁自身零 print，输出仅走 stderr，返回码严格 0/1/2（INV-4）。
新建 plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py：P1~P5 各至少 1 正例 + 1 反例；追加黑盒接线断言（C2）——在临时仓库预置违规 Markdown，subprocess 运行 git_pre_commit_guard.py，断言退出码非 0；追加 capsys 断言 checker 的 stdout 恒为空（INV-4）。更新 test_architecture_hygiene.py（断言门禁脚本存在且被 guard 引用）、dev_tasks_mcp_specification.md（新增 §4.2）、docs/architecture/README.md 与 CHANGELOG.md。在 server.py 中补齐其余工具缺失的 Args: 块。

#### 【防御与边缘校验】
纯 AST 零运行时依赖：检查脚本严禁 import server / fastmcp；仅允许标准库 + tool_surface_constants（零三方依赖）。
门禁自锁三重防护：P4 排除 docs/dev_tasks/** 与 docs/archive/**（R2）；P3 不扫历史白名单（R3）；围栏级 EXEMPTION_MARKER 提供最后的例外出口，且豁免常量受单测锚定。
历史文档不重写：CHANGELOG.md 与事故台账保留 raw_text=True 迁移/事故原文，仅要求带豁免标记（P5）。
SSOT 单一化：工具集合来自 tool_surface_constants + AST 交叉断言，任何一侧漂移即 fail-closed（M3）。
快照新鲜度前置：P2 在描述校验前先校验 envelope 与 tool_surface_constants 一致，拒绝在陈旧镜像上给出绿灯（M2）。
零误伤：P4 仅做未知关键字检测，绝不因“示例省略必填参数 / 使用位置参数 / 短横线伪代码”而误报。
协议纯净度（INV-4）：脚本零 print；stdout 仅保留给 JSON-RPC；CLI 输出定向 stderr；返回码 0/1/2。
性能与确定性：全量扫描 <= 2s；目录遍历排序稳定；错误信息输出相对路径与行号，禁止时间戳等非确定内容。
白名单变更治理：HISTORICAL_ALLOWLIST / EXCLUDED_PATH_PREFIXES 任一变更必须伴随单测更新，并在 PR 中显式说明。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py -q
pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q
python scripts/check_prompt_surface.py --check
python scripts/export_ide_schemas.py --check
python -c "import sys; sys.path.insert(0,'scripts'); import check_prompt_surface as m; sys.exit(m.main(['--check']))"
pytest -m tier1_fast -q
```

---

