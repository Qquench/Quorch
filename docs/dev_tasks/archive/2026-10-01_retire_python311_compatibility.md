# 2026-10-01_retire_python311_compatibility Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-01

---

## Task List & Status / 任务清单与状态

### 任务 1 ✔️ 已完成 — 提升 Python 最低支持基线至 3.12 并退役 3.11 语法守卫

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/pyproject.toml
[MODIFY] .github/workflows/ci.yml
[DELETE] plugins/quench-dev-tasks/server/tests/test_python_version_compat.py
[NEW] plugins/quench-dev-tasks/server/tests/test_python_floor_discipline.py
[MODIFY] README.md
[MODIFY] docs/ci_incident_tracker_and_compatibility_guide.md
[MODIFY] CHANGELOG.md
```

#### 【缺陷根因与修改目标】
```
【根因分析】
Quorch 此前将最低兼容基线设为 Python 3.11，但 Python 3.11 的 C 解析器不支持 PEP 701（f-string 表达式内反斜杠等现代语法），导致现代 LLM 与开发者在 3.12+ 环境下编写合法代码后，推送到 3.11 CI 矩阵时频繁遭遇 SyntaxError 编译期崩溃（如 INC-20260930-01），引发多次不必要的提单与返工。为此此前引入了 test_python_version_compat.py 等 AST 扫描守卫和绕行写法（如 chr(92)），带来了持续的语法约束税与双轴 CI 维护开销。

【修改目标】
1. 将项目最低支持基线正式提升至 Python >= 3.12，并在 pyproject.toml 中声明 requires-python = ">=3.12"；
2. 调整 .github/workflows/ci.yml，移除 3.11 测试轴，保留 3.12 并在 Windows 与 Ubuntu 双平台运行；
3. 物理退役并删除 3.11 专属反斜杠守卫 test_python_version_compat.py；
4. 新增 test_python_floor_discipline.py 版本下限纪律元测试，断言 pyproject.toml 与 CI 矩阵不得回退至 < 3.12，且旧守卫保持退役；
5. 同步更新 README.md、docs/ci_incident_tracker_and_compatibility_guide.md 与 CHANGELOG.md 文档。
```

#### 【目标签名与类型契约】
```
# plugins/quench-dev-tasks/server/tests/test_python_floor_discipline.py

from typing import Final, List, Tuple

MINIMUM_PYTHON: Final[Tuple[int, int]] = (3, 12)

def test_pyproject_floor_is_at_least_312() -> None: ...
def test_ci_matrix_has_no_axis_below_floor() -> None: ...
def test_legacy_fstring_backslash_guard_is_retired() -> None: ...
```

#### 【分步改造指引】
修改 plugins/quench-dev-tasks/server/pyproject.toml，将 requires-python 从 '>=3.11' 更新为 '>=3.12'
修改 .github/workflows/ci.yml，将 matrix.python-version 从 ['3.11', '3.12'] 更新为 ['3.12']，保留 ubuntu 和 windows 双 OS
物理删除旧版本语法守卫 plugins/quench-dev-tasks/server/tests/test_python_version_compat.py
新增 plugins/quench-dev-tasks/server/tests/test_python_floor_discipline.py，包含 pyproject 下限、CI 矩阵下限及旧守卫退役断言
更新 README.md、docs/ci_incident_tracker_and_compatibility_guide.md 与 CHANGELOG.md，同步记录基线提升至 Python 3.12+

#### 【防御与边缘校验】
LF-1 守卫孤儿防范：test_python_floor_discipline.py 元测试对旧守卫文件存在性做负向断言，确保旧 AST 守卫已被物理移除且不再复活
LF-2 宿主环境校验：确认本地 Python 为 3.12.10，hook 运行在 >=3.12 环境且为 fail-closed
LF-3 保留类型前向注解：明确禁止误删各模块中的 from __future__ import annotations
LF-4 元数据漂移防范：元测试同时校验 pyproject.toml 的 requires-python 与 .github/workflows/ci.yml 的 matrix.python-version，保证下限一致 >= 3.12
LF-5 阶段解耦：本任务不引入激进语法重构，仅做版本下限提升与守卫物理退役，保证回滚面完全清洁

#### 【DoD 验证命令】
```bash
python -c "import pathlib, tomllib; f = tomllib.loads(pathlib.Path('plugins/quench-dev-tasks/server/pyproject.toml').read_text(encoding='utf-8')); assert f['project']['requires-python'] == '>=3.12', f['project']['requires-python']; print('pyproject floor ok')"
python -c "import pathlib; txt = pathlib.Path('.github/workflows/ci.yml').read_text(encoding='utf-8'); assert '3.11' not in txt, '3.11 still in CI matrix'; assert '3.12' in txt, '3.12 missing in CI matrix'; print('ci matrix ok')"
python -c "import pathlib; assert not pathlib.Path('plugins/quench-dev-tasks/server/tests/test_python_version_compat.py').exists(), 'legacy guard still exists'; print('legacy guard retired ok')"
pytest plugins/quench-dev-tasks/server/tests/test_python_floor_discipline.py -v
python -m compileall -q plugins/quench-dev-tasks/server
pytest plugins/quench-dev-tasks/server/tests -v -rA --tb=short
```

---

