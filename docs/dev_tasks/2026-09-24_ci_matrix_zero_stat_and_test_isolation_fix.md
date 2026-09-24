# 2026-09-24_ci_matrix_zero_stat_and_test_isolation_fix Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-09-24

---

## Task List & Status / 任务清单与状态

### 任务 1.1 ✔️ 已完成 — 修复 gc_by_filename_order 的 TOCTOU 与零 stat 契约违反，消除测试全局 os.stat 毒化

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/log_naming.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_log_naming.py
[NEW] plugins/quench-dev-tasks/server/tests/test_no_global_os_stat_patch.py
[MODIFY] docs/ci_incident_tracker_and_compatibility_guide.md
```

#### 【缺陷根因与修改目标】
```
关联背景：本任务承接 Milestone v1.06 Task 1.5 新增的 log_naming 模块。
根因：gc_by_filename_order 使用 if os.path.exists(fpath): os.remove(fpath) 触发隐式 os.stat 调用，违背 zero-stat GC 契约并引入 TOCTOU；同时 test_gc_zero_stat_guarantee 全局 monkeypatch os.stat，在 POSIX 与 Windows-Python3.11 下污染 pytest 的 tmp_path 清理与 linecache，致使 CI 4-job 矩阵中 3-job 崩溃。
目标：以 try/except FileNotFoundError 幂等删除替代存在性检查，支持 Windows PermissionError 优雅降级；用定向白名单过滤与子进程隔离重构测试，并在 docs/ci_incident_tracker_and_compatibility_guide.md 中归档沉淀案例 6。
```

#### 【目标签名与类型契约】
```
def gc_by_filename_order(
    directory: str | os.PathLike[str],
    *,
    keep: int,
) -> list[str]:
    """Return basenames successfully removed.

    Syscall contract (zero-stat GC invariant):
        ALLOWED: os.listdir, os.remove
        FORBIDDEN: os.stat, os.lstat, os.path.exists, os.path.isfile,
                   os.path.isdir, os.path.getmtime, os.path.getsize
    Concurrency: idempotent against concurrent GC — FileNotFoundError
    is absorbed as a benign success. PermissionError (Windows handle lock,
    cf. ci_incident_tracker_and_compatibility_guide.md Case 4) is logged and skipped.
    """

def _guarded_stat(path: str | os.PathLike[str], *a, **kw) -> os.stat_result: ...
def _guarded_lstat(path: str | os.PathLike[str], *a, **kw) -> os.stat_result: ...
```

#### 【分步改造指引】
1. 生产修复：将 log_naming.py 中 gc_by_filename_order 内 if os.path.exists(fpath): os.remove(fpath) 替换为原子删除：try: os.remove(fpath); pruned.append(fname) except FileNotFoundError: pass except PermissionError: pass except OSError: pass；并对 .1.log 轮转文件同理执行原子删除。
2. 契约注释：在 gc_by_filename_order docstring 增补 Syscall Contract 白名单说明（ALLOWED: os.listdir, os.remove），更新模块级 zero-stat 说明。
3. 测试重构：将 test_log_naming.py 中的 test_gc_zero_stat_guarantee 改为定向路径白名单过滤（_guarded_stat 仅对匹配 _LOG_FILENAME_REGEX 的文件拦截，完全放行 pytest 内部路径）；新增 test_gc_zero_stat_guarantee_subprocess（子进程强隔离）与 test_gc_tolerates_permission_error（Windows 句柄锁容错）。
4. 静态门禁：新增 test_no_global_os_stat_patch.py，用 ast 扫描 tests/ 目录，禁止出现裸全局 monkeypatch.setattr(os, 'stat', ...)；并在 test_log_naming.py 中增加 test_gc_source_has_no_stat_calls 静态 AST 检查。
5. 文档沉淀：在 docs/ci_incident_tracker_and_compatibility_guide.md 中追加案例 6（全局 monkeypatch stdlib C 层函数导致 pytest session 级崩溃），并补充安全编码准则第 5 条。

#### 【防御与边缘校验】
- TOCTOU：并发 GC / 外部删除导致 FileNotFoundError 必须被吞并视为成功，不得上抛中断批次。
- Windows 句柄锁：PermissionError 必须降级跳过，不得中断 GC 批次（Case 4 句柄锁防护）。
- 测试隔离：任何 monkeypatch 严禁全局毒化 os.stat，必须带有路径白名单或限定被测模块。
- 跨平台与跨版本：在 Python 3.11 与 Python 3.12 双环境下全量测试通过。

#### 【DoD 验证命令】
```bash
uv run --python 3.11 pytest plugins/quench-dev-tasks/server/tests -q
python -m pytest plugins/quench-dev-tasks/server/tests -q
```

---

