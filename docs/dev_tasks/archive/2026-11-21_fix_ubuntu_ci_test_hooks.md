# 2026-11-21_fix_ubuntu_ci_test_hooks Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-21

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 修复 Ubuntu CI 中 test_hooks.py 跨平台外部路径硬编码导致的断言失败

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_hooks.py
```

#### 【缺陷根因与修改目标】
```
Ubuntu CI (`9146dd4` / `4603c3d`) failed in `test_file_scope_guard_agent_brain_artifact_exempt_with_and_without_active_task` because the test hardcoded Windows drive-letter paths (`C:/Users/user/...`). On POSIX (Linux/Ubuntu), `os.path.isabs('C:/...')` is `False`, so `file_scope_guard.py` and `project_config.py` resolve it as a relative path inside `workspace_root` (`<tmp_path>/C:/Users/user/other_repo/README.md`), where `is_path_governed` exempts `.md` files via `DEFAULT_UNMANAGED_EXTENSIONS` and returns `allow` instead of `force_ask`. Fix the test to use OS-agnostic external paths (`ws = tmp_path / 'ws'`, `external_base = tmp_path / 'external'`) across all platforms, plus an `os.name == 'nt'` cross-drive check.
```

#### 【目标签名与类型契约】
```
test_file_scope_guard_agent_brain_artifact_exempt_with_and_without_active_task(tmp_path: Path) -> None
```

#### 【分步改造指引】
1. Update `test_file_scope_guard_agent_brain_artifact_exempt_with_and_without_active_task` in `plugins/quench-dev-tasks/server/tests/test_hooks.py` to separate `ws = tmp_path / 'ws'` from `external_base = tmp_path / 'external'`.
2. Replace hardcoded `C:/Users/user/...` brain, non-brain external `README.md`, and `..` traversal escape paths with OS-agnostic paths under `external_base` (preserving unnormalized `..` segments via `os.path.join` for the traversal escape test).
3. Add a Windows-only (`if os.name == 'nt':`) cross-drive assertion block covering both external brain `allow` and external non-brain `force_ask` using a drive letter distinct from `ws`.
4. Run `pytest plugins/quench-dev-tasks/server/tests/test_hooks.py -v` and `ruff check plugins/quench-dev-tasks/server/tests/test_hooks.py` to confirm all tests and lint checks pass.

#### 【防御与边缘校验】
- Ensure workspace root (`tmp_path / 'ws'`) and external root (`tmp_path / 'external'`) are physically separate directories on both POSIX (Ubuntu) and Windows, without writing outside `tmp_path`
- Ensure traversal escape path preserves unnormalized `..` segments in input so `file_scope_guard.py` exercises `resolve_physical_path` normalization rather than pre-normalizing in test setup
- Keep Windows cross-drive verification guarded by `if os.name == 'nt':` using an alternate drive letter different from `tmp_path`'s drive
- Verify full `pytest` suite and `ruff check` on modified test file pass with zero regressions

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_hooks.py -v
pytest plugins/quench-dev-tasks/server/tests -q
```

---

