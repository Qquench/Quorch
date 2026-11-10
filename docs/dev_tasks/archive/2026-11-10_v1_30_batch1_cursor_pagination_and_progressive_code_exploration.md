# 2026-11-10_v1_30_batch1_cursor_pagination_and_progressive_code_exploration Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-10

---

## Task List & Status / 任务清单与状态

### 任务 30.1 ✔️ 已完成 — 代码探索器游标分页、行原子化窗口与渐进式展开原语（Phases 1-5）

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/code_explorer.py
[NEW] plugins/quench-dev-tasks/server/tests/test_code_explorer_cursor_and_progressive.py
```

#### 【缺陷根因与修改目标】
```
根因：
1. build_safe_slice 静态折叠（插入 "[中间细节折叠]" / "[切片行数超限截断]"）无任何续读路径，属不可恢复的信息丢失；
2. is_path_safe 仅比对单一 workspace_root，跨兄弟目录只读访问被物理拒绝；
3. 缺少 list_dir / grep 渐进式展开原语，大目录与大文件只能盲读触发 SkippedFile。

目标：
1. 新增无 I/O 纯函数 build_line_window，实现行原子化的游标分页，满足 No Gap / No Overlap 拼接等价性；
2. 重写 build_safe_slice 复用 build_line_window，彻底移除折叠与截断标记；
3. 新增 resolve_within_roots 多根白名单解析（含盘符根/UNC/设备名/符号链接/大小写防御），is_path_safe 降为其薄封装；
4. 新增 list_dir 单层探查与 grep 直方图优先检索；
5. 新增统一入口 read_file_slice，按 origin 差异化钳制预算并回填游标字段；
6. 行原子性契约与 build_line_window docstring 必须语义一致（消除 B1 矛盾）：单行超 max_bytes 时整行返回、置 byte_capped=True、next_offset=offset+1，绝不截断任何字符（I3）。

[非目标 / Out of Scope]
- 本任务不接入 server.py 工具面，不将 allowed_roots 暴露为 MCP 模型可控入参；多根白名单装配由后续任务承载。
- allowed_roots 仅允许宿主/服务端注入（计划 §2.3），此约束在 resolve_within_roots docstring 中显式声明。
```

#### 【目标签名与类型契约】
```
RING1_MAX_LINES: int = 40
RING1_MAX_BYTES: int = 64 * 1024
MAX_LIST_ENTRIES: int = 200
MAX_GREP_HITS: int = 200
MAX_GREP_HITS_PER_FILE: int = 5
MAX_GREP_PATTERN_CHARS: int = 200
GREP_LINE_SCAN_CHARS: int = 4096

@dataclass(frozen=True)
class LineWindow:
    text: str
    start_line: int
    end_line: int
    total_lines: int
    next_offset: Optional[int]
    byte_capped: bool

@dataclass(frozen=True)
class DirEntryInfo:
    name: str
    kind: str
    size_bytes: int = 0

@dataclass(frozen=True)
class DirListing:
    rel_path: str
    origin: str
    entries: List[DirEntryInfo]
    total_entries: int
    omitted: int

@dataclass(frozen=True)
class GrepFileHit:
    rel_path: str
    count: int

@dataclass(frozen=True)
class GrepLineMatch:
    rel_path: str
    lineno: int
    text: str

@dataclass(frozen=True)
class GrepResult:
    pattern: str
    files_scanned: int
    histogram: List[GrepFileHit]
    matches: List[GrepLineMatch]
    truncated: bool
    elapsed_ms: int

def build_line_window(source_text: str, offset: int = 0, limit: int = MAX_SLICE_LINES, max_bytes: int = MAX_FILE_BYTES) -> LineWindow:
    """无 I/O 纯函数，计算行原子化切片与游标。
    行为契约：
    1. offset<0 视作 0；limit<=0 视作 1；
    2. source_text=="" 时 total_lines=0，返回 text=""、next_offset=None（对齐空文件契约）；
    3. 其余情况 total_lines = len(source_text.split("\n"))；offset>=total_lines 返回空页，不抛异常；
    4. 逐行累加，加入下一行将超过 max_bytes 即停，next_offset = offset + consumed_lines；
    5. 若当前单行本身超过 max_bytes：整行返回、置 byte_capped=True、next_offset = offset + 1，
       【绝不截断字符】（max_bytes 为软界，单行可过冲至文件硬顶 512KB）。
    注：行模型严格采用 split("\n")；分页重组须为 "\n".join(page.text for page in pages)。"""

def build_safe_slice(source_text: str, symbols: List[SymbolIface], max_lines: int = MAX_SLICE_LINES) -> Tuple[str, bool]:
    """签名兼容；底层替换为 build_line_window；symbols 参数兼容保留（不再拼入 slice_text，签名见 SlicedFile.symbols）。"""

def resolve_within_roots(workspace_root: str, target_path: str, allowed_roots: Optional[Sequence[str]] = None) -> Optional[Tuple[str, str]]:
    """allowed_roots 必须由宿主注入，禁止透传模型入参。"""

def is_path_safe(workspace_root: str, target_path: str, allowed_roots: Optional[Sequence[str]] = None) -> bool: ...
def list_dir(workspace_root: str, rel_path: str = ".", allowed_roots: Optional[Sequence[str]] = None, max_entries: int = MAX_LIST_ENTRIES) -> DirListing: ...
def grep(workspace_root: str, pattern: str, rel_path: str = ".", allowed_roots: Optional[Sequence[str]] = None, max_files: int = MAX_EXPLORE_FILES, deadline: float = DEFAULT_DEADLINE_SECONDS) -> GrepResult: ...
def read_file_slice(workspace_root: str, rel_path: str, offset: int = 0, limit: Optional[int] = None, allowed_roots: Optional[Sequence[str]] = None) -> SlicedFile: ...
```

#### 【分步改造指引】
1. 追加 7 常量（RING1_MAX_LINES=40, RING1_MAX_BYTES=64KB, MAX_LIST_ENTRIES=200, MAX_GREP_HITS=200, MAX_GREP_HITS_PER_FILE=5, MAX_GREP_PATTERN_CHARS=200, GREP_LINE_SCAN_CHARS=4096）。
2. 定义 LineWindow/DirEntryInfo/DirListing/GrepFileHit/GrepLineMatch/GrepResult；SlicedFile 追加 start_line=1, end_line=0, total_lines=0, next_offset=None, origin='workspace', hint=''。
3. 实现 build_line_window（严格遵守【目标签名】契约 1-5；空文件 total_lines=0；单行超 max_bytes 整行返回并置 byte_capped=True，绝不截断字符）。
4. 重写 build_safe_slice 复用 build_line_window；删除全部折叠/截断标记与 symbols 拼接；docstring 注明 symbols 兼容保留。
5. 实现 resolve_within_roots（空串/NUL/根/盘符根/UNC/设备名防御 + realpath + normcase）；is_path_safe 为薄封装。
6. 实现 list_dir（resolve->scandir->字典序排序->截取 max_entries->omitted 计数）。
7. 实现 grep（resolve->确定性 walk->跳过 .git 与 >512KB->NUL 检测->正则长度校验与 re.error 捕获->前 4096 字符匹配->每文件<=5、全局<=200->逐文件 deadline 熔断）。
8. 实现 read_file_slice（路径安全->敏感过滤->>512KB 抛错->origin 推导->差异化钳制->build_line_window->回填游标与 hint）。
9. 改造 explore_code_slices 内部装配改用 read_file_slice，SkippedFile 判定与返回结构保持不变。
10. 编写测试套件，落实 A-1~A-12 全部断言（零 sleep）。
【前置校验】：核实既有 test_ast_slice_cache_determinism.py / test_spec_refine.py 无折叠标记/签名内联断言（已排查确无断言，无需修改既有测试）。

#### 【防御与边缘校验】
A-1 续读权威性：250 行文件 page(0).next_offset==100，page(100).next_offset==200，page(200).next_offset is None。
A-2 拼接等价：pages=连续分页，断言 "\n".join(p.text for p in pages)==source_text（含结尾换行与不含结尾换行两例）。
A-3 行原子性：外环(64KB)下 100KB 单行 -> 整行返回、len(text)==行长、byte_capped is True、next_offset==offset+1、无字符丢失。
A-4 越界与空文件：offset>=total_lines -> text==""且 next_offset is None 不抛异常；source_text=="" -> total_lines==0。
A-5 首行永不拒：offset=0 首行超 max_bytes 仍返回整行。
A-6 根拒绝族："", "\x00", "/", "C:/", "C:", "\\\\?\\C:\\", "\\\\server\\share" -> resolve_within_roots 返回 None。
A-7 符号链接防御：root 内 symlink 指向外部 -> None。
A-8 (Windows) normcase 双端归一：大小写差异路径命中 root（POSIX 上用例 skip）。
A-9 外环预算：origin=="external" -> limit<=40、max_bytes<=64KB；单行过冲场景 page 字节<=512KB 硬顶。
A-10 正则卫生：len(pattern)>200 被拒；非法正则抛 CodeExplorerError；单行仅扫描前 4096 字符。
A-11 超时熔断：deadline<=0 -> 立即熔断返回，elapsed_ms>=0，不抛异常。
A-12 编码/二进制与确定性：非 UTF-8 用 errors="replace" 不抛异常；NUL 二进制跳过；histogram 按 (count desc, rel_path asc)、matches 按 (rel_path asc, lineno asc)，每文件<=5、全局<=200。
D-1 续读权威性：next_offset is not None 当且仅当仍有未返回内容。
D-2 拼接等价性：连续分页 "\n".join() 与 "\n".join(source_text.split("\n")) 逐字符相等。
D-3 行原子性：首行永不因 max_bytes 被拒；单行超预算时返回整行并置 byte_capped=True，next_offset = offset + 1，杜绝翻页死循环且不丢失任何字符。
D-4 越界安全：offset >= total_lines 返回空页而非异常。
D-5 根拒绝族：空串、\x00、/、C:/、C:、UNC、\\?\ 前缀一律 None。
D-6 符号链接防御：realpath 解析后落在根外一律 None。
D-7 Windows 大小写：normcase 双端归一，POSIX 上无副作用。
D-8 外环差异化预算：origin=="external" 时 limit <= 40、max_bytes <= 64KB。
D-9 正则卫生：<=200 字符仅为廉价 sanity 上限，不构成 ReDoS 证明；真实风险由 GREP_LINE_SCAN_CHARS=4096 单行窗口 + MAX_FILE_BYTES 文件剪枝共同封顶。
D-10 超时熔断：逐文件检查 monotonic deadline，deadline <= 0 立即熔断。
D-11 编码/二进制：errors="replace" + NUL 探测，非 UTF-8 与二进制文件不得抛异常。
D-12 确定性：目录/文件遍历与 histogram/matches 排序全部显式指定。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_code_explorer_cursor_and_progressive.py plugins/quench-dev-tasks/server/tests/test_ast_slice_cache_determinism.py plugins/quench-dev-tasks/server/tests/test_spec_refine.py -v -q
```

---

