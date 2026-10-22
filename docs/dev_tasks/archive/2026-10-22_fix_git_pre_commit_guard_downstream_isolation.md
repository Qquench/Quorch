# 2026-10-22_fix_git_pre_commit_guard_downstream_isolation Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-22

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 修复 git_pre_commit_guard 对下游业务工程的 Prompt Surface 误伤拦截（终审补丁版）

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py
[MODIFY] docs/architecture/README.md
```

#### 【缺陷根因与修改目标】
```
修正 evaluate_prompt_surface_check 对下游业务工程的误伤：下游工程缺少核心宿主 CI 脚本时，当前会 ModuleNotFoundError -> UNVERIFIABLE -> fail-closed 阻断一切 .md 提交。
终审补丁澄清宿主判定语义：
1. 采用 STRONG-ANCHOR 宿主分类（非插件分发单元），避免 vendored 插件路径被误判为 core；
2. 强锚点任一项存在 -> core；全部缺失 -> downstream（透明 SKIP）；
3. 明确记录强锚点模型下的“downstream fail-open”权衡与上游护栏（file_scope_guard + scope_reconciliation）阻断恶意删除强锚点的攻击面；
4. 补齐 core/downstream/half-core 三态黑盒矩阵与白盒矩阵单测；
5. 同步 docs/architecture/README.md §3.6 Host Boundary 精确表述。
```

#### 【目标签名与类型契约】
```
from __future__ import annotations
from typing import Final, Optional, Sequence, Union
from pathlib import Path

QUENCH_CORE_STRONG_ANCHORS: Final[tuple[str, ...]] = (
    "scripts/check_prompt_surface.py",
    "scripts/check_test_tiering_invariants.py",
    "scripts/check_test_duration_baselines.py",
    "docs/architecture/ide_tool_schemas.json",
)

def is_quorch_core_repo(repo_root: Union[Path, str]) -> bool:
    """Host classification via STRONG anchors (not vendor-distributed)."""

def evaluate_prompt_surface_check(
    changed_paths: Optional[Sequence[str]], *, repo_root: Path
) -> PromptSurfaceOutcome:
    """First line: short-circuit to SKIP if not is_quorch_core_repo(repo_root)."""
```

#### 【分步改造指引】
1. 在 plugins/quench-dev-tasks/scripts/git_pre_commit_guard.py 中定义 QUENCH_CORE_STRONG_ANCHORS 与 is_quorch_core_repo（仅强锚点；Path(repo_root) 不用 resolve()）。
2. 在 evaluate_prompt_surface_check 首行（changed_paths is None 判断之前）插入 if not is_quorch_core_repo(repo_root): return PromptSurfaceOutcome.SKIP，确保下游在 git 故障时也不 GUARD_ERROR。
3. 在 plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py 中：白盒矩阵断言 {空目录, 仅 vendored 插件路径, 单强锚点, 全强锚点} 分别为 False/False/True/True；边缘断言 changed_paths=None 下游仍 SKIP；三态黑盒集成测试覆盖 core (REPO_ROOT) -> PASS, downstream (tmp_path vendored) -> SKIP, half-core (1强锚点且桩脚本失败) -> VIOLATION。
4. 在 docs/architecture/README.md §3.6 增补 Host Boundary 段落，采用纯叙述文本（避免引入 python fence 与 MCP 工具调用示例，防止触发 P4），精确表述强锚点集合与 downstream 透明语义。
5. 执行 DoD 全量验证。

#### 【防御与边缘校验】
- P0-1 vendored 误判：强锚点为非分发单元，vendored 插件不触发分类翻转。
- P0-2 首行短路：宿主判定先于变更集判定；下游 changed_paths=None 仍 SKIP。
- P1-3 fail-closed 语义重述：强锚点缺失 -> downstream -> 透明 SKIP；安全由 §3.2 §3.5 上游护栏保障（见契约 docstring 的 (b) 项）；文档必须原样记录此权衡，禁止表述为“fail-closed to core”。
- 导入回退加固（非阻断建议）：checker_script.is_file() 为真时走 subprocess；仅在插件回退分支中，若 importlib.util.find_spec("check_prompt_surface") 的 origin 不在 repo_root 内，须返回 UNVERIFIABLE（不得 PASS）。
- 路径稳健性：Path(repo_root) 不使用 resolve()；跨平台斜杠安全。
- 零依赖：guard 保持仅标准库（enum, os, subprocess, sys, pathlib, typing）。
- 重入安全：is_quorch_core_repo 为纯读取、无锁、无状态、幂等。
- Tiering 不变量：新增测试不引入 Tier-1 fast gate 之外的重型并发；check_test_tiering_invariants.py 必须通过。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_prompt_surface_contract.py -q
pytest plugins/quench-dev-tasks/server/tests/test_pre_commit_guard.py -q
pytest plugins/quench-dev-tasks/server/tests/test_architecture_hygiene.py -q
python scripts/check_prompt_surface.py --check
python scripts/check_test_tiering_invariants.py
python scripts/check_test_duration_baselines.py
```

---

