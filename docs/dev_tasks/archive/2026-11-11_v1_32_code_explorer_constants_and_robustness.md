# 2026-11-11_v1_32_code_explorer_constants_and_robustness Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-11

---

## Task List & Status / 任务清单与状态

### 任务 32.1 ✔️ 已完成 — Code Explorer Constants Evolution & list_dir Cursor Pagination

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/code_explorer.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_code_explorer_cursor_and_progressive.py
```

#### 【缺陷根因与修改目标】
```
根据外部 Reviewer (Job: job_1794315890_9bf81dfa) 审计结论：
1. MAX_GREP_HITS_PER_FILE=5 在特征密集型文件中造成广度对深度的严重压制，掐断关键集中定义处的排查；
2. MAX_GREP_PATTERN_CHARS=200 存在对合法联合长正则/状态机枚举的虚假拦截误伤；
3. list_dir 缺乏 offset / next_offset 分页游标机制，在超大目录中超出 max_entries 的条目物理不可达；
4. grep 匹配截断与 histogram 统计耦合，需确保全局分布图统计真实完整。
目标：将 MAX_GREP_HITS_PER_FILE 扩容至 20；MAX_GREP_PATTERN_CHARS 扩容至 1024；为 list_dir 和 DirListing 引入 offset 与 next_offset 游标分页；解耦 grep 命中截断与直方图统计，并补充单测断言。
```

#### 【目标签名与类型契约】
```
MAX_GREP_HITS_PER_FILE: int = 20
MAX_GREP_PATTERN_CHARS: int = 1024

@dataclass(frozen=True)
class DirListing:
    rel_path: str
    origin: str
    entries: List[DirEntryInfo]
    total_entries: int
    omitted: int
    offset: int = 0
    next_offset: Optional[int] = None

def list_dir(
    workspace_root: str,
    rel_path: str = ".",
    allowed_roots: Optional[Sequence[str]] = None,
    max_entries: int = MAX_LIST_ENTRIES,
    offset: int = 0,
) -> DirListing: ...
```

#### 【分步改造指引】
1. 修改 plugins/quench-dev-tasks/server/code_explorer.py 常量：MAX_GREP_HITS_PER_FILE 调整为 20，MAX_GREP_PATTERN_CHARS 调整为 1024。
2. 扩充 DirListing 数据类字段：增加 offset: int = 0 与 next_offset: Optional[int] = None。
3. 改造 list_dir 函数：支持入参 offset: int = 0，做下限截断（max(0, int(offset))），切片 raw_entries[effective_offset : effective_offset + effective_max]，并计算 next_offset。
4. 优化 grep 统计逻辑：确保 histogram 统计反映文件内实际总匹配数，matches 列表受 MAX_GREP_HITS_PER_FILE (20) 与全局 MAX_GREP_HITS 截断。
5. 在 plugins/quench-dev-tasks/server/tests/test_code_explorer_cursor_and_progressive.py 中补充 A-13、A-14、A-15 单测断言覆盖常量扩容、分页遍历全集等价性与直方图解耦。

#### 【防御与边缘校验】
- offset 防御：offset < 0 自动钳位至 0；offset >= total_entries 返回空 entries 且 next_offset 为 None；omitted 准确反映未返回条目数。
- 向后兼容：DirListing 新增 offset 与 next_offset 字段附带默认值，旧调用方不传参行为完全兼容。
- 正则防御：保持 re.error 异常捕获并封装为 CodeExplorerError，防非法语法穿透；长正则上限放宽至 1024 字符。
- 回滚锚点：git checkout plugins/quench-dev-tasks/server/code_explorer.py plugins/quench-dev-tasks/server/tests/test_code_explorer_cursor_and_progressive.py

#### 【DoD 验证命令】
```bash
python -m pytest plugins/quench-dev-tasks/server/tests/test_code_explorer_cursor_and_progressive.py -v
```

---

