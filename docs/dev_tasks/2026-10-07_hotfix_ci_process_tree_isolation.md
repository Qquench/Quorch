# 2026-10-07_hotfix_ci_process_tree_isolation Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-07

---

## Task List & Status / 任务清单与状态

### 任务 1 ✔️ 已完成 — CI 进程树回收跨平台隔离加固与 canary 防自杀 + 隔离性正向断言

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/tests/test_server_daemon_launch_canary.py
[MODIFY] .github/workflows/ci.yml
```

#### 【缺陷根因与修改目标】
```
Root Cause:
_terminate_process_tree 在 POSIX 下调用 os.killpg(os.getpgid(proc.pid), signal.SIGKILL)，但 subprocess.Popen 未指定
start_new_session=True，子进程继承 pytest 与 GHA runner worker 的进程组，导致 killpg 向整组投递 SIGKILL，
误杀 runner worker 祖先进程，Ubuntu CI 失去回传通道并挂起至超时判死（46 分钟）；Windows 走 taskkill /T /F /PID
仅命中子进程树，故正常通过。
Target:
1) 两个 Popen 站点启用 start_new_session=True，使被测守护进程独立成会话/进程组，使进程组清理仅作用于目标树；
2) 在 _terminate_process_tree 加入防自杀保护：目标 pgid 不得等于 os.getpgrp()，命中则降级为 proc.kill()；
3) 清理时安全关闭 stdin/stdout/stderr 管道句柄；
4) CI 增加作业级 timeout-minutes 上界兜底；
5) 补强 DoD：新增"进程组隔离"正向断言与"防自杀降级"负路径断言，使回归可被证伪。
```

#### 【目标签名与类型契约】
```
无新增公共 API。内部测试辅助函数行为契约变更：
  _terminate_process_tree(proc: subprocess.Popen) -> None
  - 前置：proc 为存活/已退出 Popen 实例；函数幂等（proc.poll() is not None 时立即返回）。
  - 后置：返回时 proc.poll() is not None（直接子进程已回收）。
  - 不变式（POSIX）：绝不对 os.getpgrp() 所在进程组投递任何信号。
```

#### 【分步改造指引】
1. 在两个 Popen 站点（test_server_daemon_launch_canary_and_lock_isolation、test_grandchild_pipe_fd_isolation_timeout_recovery）均注入 start_new_session=True。
   （参数跨平台可传；行为仅 POSIX 生效，Windows 忽略并继续走 taskkill /T /F /PID。）
2. 重写 _terminate_process_tree 的 POSIX 分支：在 try 内取 pgid = os.getpgid(proc.pid)；
   若 pgid == os.getpgrp() 则 proc.kill()，否则 os.killpg(pgid, signal.SIGKILL)；
   ProcessLookupError 及其他异常一律降级 proc.kill()。
3. 【GAP-1】在首测进程存活期间新增正向断言：POSIX 下 assert os.getpgid(proc.pid) != os.getpgrp()，直接证明会话隔离生效。
4. 【GAP-2】新增负路径用例：构造未启用 start_new_session 的短命子进程，调用 _terminate_process_tree，断言当前 pytest 进程仍然存活（未自杀）且目标子进程已被终止。
5. 【GAP-3】强化第二用例：令 helper 将孙进程 PID 写入 stdout/变量并在清理后断言孤儿子进程已回收。
6. 在清理路径于 kill 之后安全关闭 proc.stdin/stdout/stderr（判空与异常安全保护）。
7. 在 .github/workflows/ci.yml 的 test 作业增加 timeout-minutes: 15 兜底。
8. 运行定向与全量 pytest 验证。

#### 【防御与边缘校验】
- 防自杀保护：POSIX 下严禁向 os.getpgrp() 所在进程组投递信号；命中即降级 proc.kill()。
- 竞态降级：os.getpgid 可能因进程已退出抛 ProcessLookupError，必须在 try 内捕获并降级。
- 跨平台：start_new_session 参数跨平台可传，行为仅 POSIX 生效；Windows 维持 taskkill /T /F /PID。
- 管道释放：close 前判空；close 异常不得中断清理流程。
- 爆炸半径：本变更不触碰生产代码，风险限定于测试夹具与 CI 配置。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_server_daemon_launch_canary.py -v -rA --tb=short
pytest plugins/quench-dev-tasks/server/tests -v -rA --tb=short
```

---

