# 2026-11-21_fix_real_pyright_type_issues Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-21

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 修复 probe_client_capabilities、project_config 与 manifest 中的真实类型窄化与流守卫问题

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/scripts/probe_client_capabilities.py
[MODIFY] plugins/quench-dev-tasks/server/project_config.py
[MODIFY] plugins/quench-dev-tasks/server/manifest.py
```

#### 【缺陷根因与修改目标】
```
Fix real static type-narrowing and stream attribute guard issues in probe_client_capabilities.py (2 TextIO.reconfigure errors), project_config.py (22 double-.get() dict narrowing errors in rp_data and _merge_local_override), and manifest.py (1 mutate_manifest_under_lock TypeVar return narrowing error).
```

#### 【目标签名与类型契约】
```
_as_dict(mapping: Mapping[str, Any], key: str) -> dict[str, Any]; mutate_manifest_under_lock(...) -> T
```

#### 【分步改造指引】
1. In `plugins/quench-dev-tasks/scripts/probe_client_capabilities.py`, import `io` and guard `sys.stdout`/`sys.stderr` `.reconfigure(...)` with `isinstance(_stream, io.TextIOWrapper)` (matching the pattern used in server/hooks).
2. In `plugins/quench-dev-tasks/server/project_config.py`, avoid calling `.get(...)` twice after `isinstance(..., dict)` checks at lines 1079-1080 (`gov_rp = gov_data.get("reaper_policy")`) and inside `_merge_local_override` (lines 1370-1424, e.g. via a local `_as_dict(mapping, key)` helper or single-lookup temporary variables) so `dict` type narrowing holds cleanly.
3. In `plugins/quench-dev-tasks/server/manifest.py` around lines 314-317, compute `should_persist = (new_manifest is not initial_manifest) or (result is not False)` (or equivalent non-narrowing boolean) so Pyright preserves `result: T` without widening to `T | object | Literal[False]`.

#### 【防御与边缘校验】
- Preserve utf-8 stream reconfiguration behavior on Windows/POSIX when sys.stdout/stderr is io.TextIOWrapper without crashing on mock/StringIO streams
- Preserve identical ConfigError messages, safety_downgrade checks, and fallback defaults in project_config.py
- Preserve exact mutate_manifest_under_lock CAS and dirty-write semantics (`new_manifest is not initial_manifest or result is not False`) without changing runtime return values

#### 【DoD 验证命令】
```bash
uvx pyright --pythonpath .\.venv\Scripts\python.exe plugins/quench-dev-tasks/scripts/probe_client_capabilities.py plugins/quench-dev-tasks/server/project_config.py plugins/quench-dev-tasks/server/manifest.py
uvx pyrefly check --python-interpreter-path .\.venv\Scripts\python.exe --min-severity=warn --output-format min-text .
.\.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_probe_client_capabilities.py plugins/quench-dev-tasks/server/tests/test_project_config.py plugins/quench-dev-tasks/server/tests/test_project_config_migration.py plugins/quench-dev-tasks/server/tests/test_manifest_lease.py plugins/quench-dev-tasks/server/tests/test_manifest_bounds.py -q
```

---

### 任务 1.2 ✔️ 已完成 — 修复 reviewer_jobs、reviewer_engine 与 server 中的属性守卫及 TypedDict 安全索引问题

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/reviewer_jobs.py
[MODIFY] plugins/quench-dev-tasks/server/reviewer_engine.py
[MODIFY] plugins/quench-dev-tasks/server/server.py
```

#### 【缺陷根因与修改目标】
```
Fix real attribute-guard and NotRequired TypedDict access issues in reviewer_jobs.py (2 Mapping.phase attribute errors), reviewer_engine.py (1 ProgressSink.close attribute error), and server.py (2 ReviewerHandoff['legacy_card_markdown'] NotRequired indexing errors).
```

#### 【目标签名与类型契约】
```
ReviewerHandoff.get('legacy_card_markdown', '') -> str
```

#### 【分步改造指引】
1. In `plugins/quench-dev-tasks/server/reviewer_jobs.py` lines 185-190, narrow `self.progress` with `isinstance(self.progress, JobProgress)` before accessing `.phase`, keeping the `Mapping` fallback branch for dict payloads.
2. In `plugins/quench-dev-tasks/server/reviewer_engine.py` lines 1904-1909, replace `if hasattr(s, "close"): s.close()` with `close_fn = getattr(s, "close", None)` and `if callable(close_fn): close_fn()`.
3. In `plugins/quench-dev-tasks/server/server.py` lines 2310 and 3263, replace `envelope["legacy_card_markdown"]` with `envelope.get("legacy_card_markdown", "")`.

#### 【防御与边缘校验】
- Preserve JobProgress vs Mapping[str, Any] phase extraction precedence in ReviewerJobRecord/PollSnapshot.__post_init__
- Guard sink close with callable check (`close_fn = getattr(s, 'close', None); if callable(close_fn): close_fn()`) so non-callable attributes cannot raise TypeError
- Keep ReviewerHandoff TypedDict total=False contract intact while safely reading `envelope.get('legacy_card_markdown', '')` in server.py

#### 【DoD 验证命令】
```bash
uvx pyright --pythonpath .\.venv\Scripts\python.exe plugins/quench-dev-tasks/server/reviewer_jobs.py plugins/quench-dev-tasks/server/reviewer_engine.py plugins/quench-dev-tasks/server/server.py
uvx pyrefly check --python-interpreter-path .\.venv\Scripts\python.exe --min-severity=warn --output-format min-text .
.\.venv\Scripts\python.exe -m pytest plugins/quench-dev-tasks/server/tests/test_reviewer_jobs.py plugins/quench-dev-tasks/server/tests/test_reviewer_engine.py plugins/quench-dev-tasks/server/tests/test_handoff_protocol.py plugins/quench-dev-tasks/server/tests/test_server_tools.py -q
```

---

