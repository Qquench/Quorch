# -*- coding: utf-8 -*-
"""Quench Code Explorer: 轻量化 AST 接口提取与安全切片代码探索器.

专为规约强化 (dev_tasks_refine_spec) 与架构疑难升级 (dev_tasks_escalate) 提供精准代码上下文。
★ 核心防线与工业级纪律：
1. 路径沙箱与盘符防御：绝对隔离于 workspace_root 内，防跨盘符崩溃、防符号链接逃逸；
2. 绝对只读与无锁 (Lock-Free)：严禁写盘，严禁申请 FileLock，彻底避免与状态机死锁；
3. CJK 字符安全：统一采用 ast.get_source_segment 防御 Python col_offset 字节偏移错位；
4. 资源硬上限：max_hops <= 3，单文件 <= 512KB，切片行数 <= 100，总扫描文件 <= 30。
"""
from __future__ import annotations

import ast
import fnmatch
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# 敏感文件/凭据黑名单：坚决禁止将敏感密钥切片灌入 LLM Prompt
SENSITIVE_PATTERNS = [
    ".env*",
    "*.key",
    "*.pem",
    "*.pfx",
    "*.p12",
    "id_rsa*",
    "id_ed25519*",
    "*secret*",
    "*credential*",
    "*token*",
    "*.keystore",
]

MAX_HOPS_LIMIT = 3
MAX_FILE_BYTES = 512 * 1024  # 512 KiB
MAX_SLICE_LINES = 100
MAX_EXPLORE_FILES = 30
DEFAULT_DEADLINE_SECONDS = 3.0

RING1_MAX_LINES = 40          # 外环（非主工作区）单次读取硬上限（行）
RING1_MAX_BYTES = 64 * 1024   # 外环单次读取硬上限（字节，64 KiB）
MAX_LIST_ENTRIES = 200        # 单次目录列表最大条目数
MAX_GREP_HITS = 200           # grep 全局最大命中行数
MAX_GREP_HITS_PER_FILE = 20   # grep 单文件最大匹配行数（保证广度与深度均衡）
MAX_GREP_PATTERN_CHARS = 1024 # 正则表达式最大长度限制（防 ReDoS sanity 限制）
GREP_LINE_SCAN_CHARS = 4096   # 单行正则扫描窗口，截断后参与匹配


class CodeExplorerError(Exception):
    """代码探索器基础异常。"""
    pass


class UnsafePathError(CodeExplorerError):
    """路径越界或非法路径。"""
    pass


@dataclass(frozen=True)
class SymbolIface:
    """提取的类或函数接口签名。"""
    name: str
    kind: str  # "function" | "async_function" | "class"
    lineno: int
    end_lineno: int
    signature: str
    docstring: Optional[str] = None


@dataclass(frozen=True)
class LineWindow:
    text: str
    start_line: int            # 1-based 含；空页时恒为 total_lines + 1
    end_line: int              # 1-based 含；空页时恒为 total_lines
    total_lines: int
    next_offset: Optional[int] # 下一次调用的 offset；None 表示已到底
    byte_capped: bool          # True 当且仅当因字节预算而 withheld 了后续行


@dataclass(frozen=True)
class DirEntryInfo:
    name: str
    kind: str                  # "dir" | "file"
    size_bytes: int = 0        # 仅 file 填充


@dataclass(frozen=True)
class DirListing:
    rel_path: str
    origin: str                # "workspace" | "external"
    entries: List[DirEntryInfo]
    total_entries: int
    omitted: int               # == total_entries - len(entries)
    offset: int = 0
    next_offset: Optional[int] = None


@dataclass(frozen=True)
class GrepFileHit:
    rel_path: str
    count: int                 # 真实命中数，不受 per-file 行上限影响


@dataclass(frozen=True)
class GrepLineMatch:
    rel_path: str
    lineno: int                # 1-based
    text: str                  # 原始行（未截断原文返回，仅匹配时受扫描窗口约束）


@dataclass(frozen=True)
class GrepResult:
    pattern: str
    files_scanned: int
    histogram: List[GrepFileHit]   # (count desc, rel_path asc)
    matches: List[GrepLineMatch]   # (rel_path asc, lineno asc)，每文件 ≤ 5 行，全局 ≤ 200
    truncated: bool            # 全局上限 / deadline / max_files 任一触发
    elapsed_ms: int


@dataclass(frozen=True)
class SlicedFile:
    """安全切片后的单个文件结构化信息。"""
    rel_path: str
    language: str
    symbols: List[SymbolIface]
    slice_text: str
    truncated: bool = False
    size_bytes: int = 0
    start_line: int = 1
    end_line: int = 0
    total_lines: int = 0
    next_offset: Optional[int] = None
    origin: str = "workspace"
    hint: str = ""


@dataclass(frozen=True)
class SkippedFile:
    """跳过探测的文件及原因。"""
    rel_path: str
    reason: str
    detail: str = ""


@dataclass
class ExploreResult:
    """探索器整体结果集。"""
    files: List[SlicedFile] = field(default_factory=list)
    skipped: List[SkippedFile] = field(default_factory=list)
    hops_used: int = 0
    truncated: bool = False
    elapsed_ms: int = 0


_WIN_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$", re.IGNORECASE)


def resolve_within_roots(
    workspace_root: str,
    target_path: str,
    allowed_roots: Optional[Sequence[str]] = None,
) -> Optional[Tuple[str, str]]:
    """验证目标路径是否位于 workspace_root 或任一 allowed_roots 中。
    返回 (matched_root_real, target_real) 或 None。

    ★ 工业级安全防线：
    1. allowed_roots 必须由宿主注入，禁止透传模型入参；
    2. 空串、空字符 (\x00) 拒绝；
    3. 文件系统根 (/)、盘符根 (C:/, C:) 严格拒绝；
    4. UNC 路径 (//server/share) 与设备路径 (\\\\?\\C:\\) 严格拒绝；
    5. Windows 保留设备名 (CON, PRN, AUX, NUL, COM1-9, LPT1-9) 严格拒绝；
    6. 使用 os.path.realpath 解析符号链接，防御符号链接逃逸；
    7. 使用 os.path.normcase 规范化大小写，防御 Windows 大小写绕过；
    8. 跨盘符 commonpath 异常捕获并安全放行/返回 None。
    """
    if not target_path or not workspace_root or "\x00" in target_path or "\x00" in workspace_root:
        return None

    # 规范化与根拒绝
    norm = target_path.replace("\\", "/").strip()
    if norm in ("", "/"):
        return None
    if re.match(r"^[A-Za-z]:/?$", norm):
        return None
    if norm.startswith("//"):
        return None
    if target_path.startswith("\\\\?\\") or target_path.startswith("\\\\.\\"):
        return None

    segs = re.split(r"[\\/]+", norm)
    if any(_WIN_RESERVED.match(seg) for seg in segs if seg):
        return None

    valid_roots: List[str] = [workspace_root]
    if allowed_roots:
        for r in allowed_roots:
            if not r or "\x00" in r:
                continue
            r_norm = str(r).replace("\\", "/").strip()
            if r_norm in ("", "/") or re.match(r"^[A-Za-z]:/?$", r_norm) or r_norm.startswith("//"):
                continue
            valid_roots.append(r)

    try:
        if os.path.isabs(target_path):
            target_real = os.path.realpath(target_path)
        else:
            ws_real = os.path.realpath(os.path.abspath(workspace_root))
            target_real = os.path.realpath(os.path.join(ws_real, target_path))
    except (OSError, ValueError):
        return None

    target_norm = os.path.normcase(target_real)

    for root in valid_roots:
        try:
            root_real = os.path.realpath(os.path.abspath(root))
            root_norm = os.path.normcase(root_real)
            common = os.path.normcase(os.path.commonpath([root_norm, target_norm]))
            if common == root_norm:
                return root_real, target_real
        except (ValueError, OSError):
            continue

    return None


def is_path_safe(
    workspace_root: str,
    target_path: str,
    allowed_roots: Optional[Sequence[str]] = None,
) -> bool:
    """检查目标路径是否严格安全且限制在 workspace_root 或任一 allowed_roots 内部。
    保留既有函数签名，作为 resolve_within_roots 的薄封装。
    """
    return resolve_within_roots(workspace_root, target_path, allowed_roots) is not None


def is_sensitive_file(file_name: str) -> bool:
    """根据黑名单规则过滤敏感文件。"""
    name_lower = os.path.basename(file_name).lower()
    for pat in SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(name_lower, pat):
            return True
    return False


def extract_ast_interfaces(source_text: str, rel_path: str) -> Tuple[List[SymbolIface], List[str], bool]:
    """解析 Python 源码 AST，提取顶层与类层级接口签名、文档字符串及内部导入模块。
    使用 ast.get_source_segment 确保 CJK 多字节字符偏移量不被截断。
    """
    try:
        # 使用 raw_bytes 解析支持 PEP 263 编码声明
        tree = ast.parse(source_text.encode("utf-8"), filename=rel_path)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        # 语法错误、递归超限等降级处理，不中断流程
        return [], [], False

    symbols: List[SymbolIface] = []
    local_imports: List[str] = []

    lines = source_text.splitlines()

    for node in tree.body:
        # 1. 提取导入依赖（用于拓扑 Hop 发现）
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                local_imports.append(node.module)

        # 2. 提取函数与异步函数
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            sig_segment = ast.get_source_segment(source_text, node) or ""
            # 只取第一行或直到冒号的部分作为签名
            first_line = sig_segment.splitlines()[0] if sig_segment else f"def {node.name}(...):"
            doc = ast.get_docstring(node)
            symbols.append(
                SymbolIface(
                    name=node.name,
                    kind=kind,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", node.lineno),
                    signature=first_line.strip(),
                    docstring=doc.strip() if doc else None,
                )
            )

        # 3. 提取类及类内部公有方法
        elif isinstance(node, ast.ClassDef):
            sig_segment = ast.get_source_segment(source_text, node) or ""
            first_line = sig_segment.splitlines()[0] if sig_segment else f"class {node.name}:"
            class_doc = ast.get_docstring(node)
            symbols.append(
                SymbolIface(
                    name=node.name,
                    kind="class",
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", node.lineno),
                    signature=first_line.strip(),
                    docstring=class_doc.strip() if class_doc else None,
                )
            )
            # 提取类内方法
            for subnode in node.body:
                if isinstance(subnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sub_kind = "async_function" if isinstance(subnode, ast.AsyncFunctionDef) else "function"
                    sub_sig = ast.get_source_segment(source_text, subnode) or ""
                    sub_first = sub_sig.splitlines()[0] if sub_sig else f"def {subnode.name}(...):"
                    symbols.append(
                        SymbolIface(
                            name=f"{node.name}.{subnode.name}",
                            kind=sub_kind,
                            lineno=subnode.lineno,
                            end_lineno=getattr(subnode, "end_lineno", subnode.lineno),
                            signature=sub_first.strip(),
                            docstring=ast.get_docstring(subnode),
                        )
                    )

    return symbols, local_imports, True


def build_line_window(
    source_text: str,
    offset: int = 0,
    limit: int = MAX_SLICE_LINES,
    max_bytes: int = MAX_FILE_BYTES,
) -> LineWindow:
    """无 I/O 纯函数，计算行原子化切片与游标。
    行为契约：
    1. offset < 0 视作 0；limit <= 0 视作 1；
    2. source_text == "" 时 total_lines = 0，返回 text="", next_offset=None（对齐空文件契约）；
    3. 其余情况 total_lines = len(source_text.split("\n"))；offset >= total_lines 返回空页，不抛异常；
    4. 逐行累加，加入下一行将超过 max_bytes 即停，next_offset = offset + consumed_lines；
    5. 若当前单行本身超过 max_bytes：整行返回、置 byte_capped=True、next_offset = offset + 1，
       【绝不截断字符】（max_bytes 为软界，单行可过冲至文件硬顶 512KB）。
    注：行模型严格采用 split("\n")；分页重组须为 "\n".join(page.text for page in pages)。
    """
    offset = max(0, int(offset))
    limit = max(1, int(limit))
    max_bytes = max(1, int(max_bytes))

    if source_text == "":
        return LineWindow(
            text="",
            start_line=1,
            end_line=0,
            total_lines=0,
            next_offset=None,
            byte_capped=False,
        )

    lines = source_text.split("\n")
    total_lines = len(lines)

    if offset >= total_lines:
        return LineWindow(
            text="",
            start_line=total_lines + 1,
            end_line=total_lines,
            total_lines=total_lines,
            next_offset=None,
            byte_capped=False,
        )

    out: List[str] = []
    used_bytes = 0
    byte_capped = False

    end_idx = min(offset + limit, total_lines)
    for idx in range(offset, end_idx):
        line = lines[idx]
        cost = len(line.encode("utf-8")) + (1 if out else 0)
        if out and used_bytes + cost > max_bytes:
            byte_capped = True
            break
        out.append(line)
        used_bytes += cost
        if not byte_capped and len(out) == 1 and used_bytes > max_bytes:
            byte_capped = True

    n = len(out)
    next_offset: Optional[int] = offset + n
    if next_offset >= total_lines:
        next_offset = None
        byte_capped = False

    start_line = offset + 1
    end_line = offset + n
    return LineWindow(
        text="\n".join(out),
        start_line=start_line,
        end_line=end_line,
        total_lines=total_lines,
        next_offset=next_offset,
        byte_capped=byte_capped,
    )


def build_safe_slice(
    source_text: str,
    symbols: List[SymbolIface],
    max_lines: int = MAX_SLICE_LINES,
) -> Tuple[str, bool]:
    """签名兼容；底层替换为 build_line_window；symbols 参数兼容保留（不再拼入 slice_text，签名见 SlicedFile.symbols）。"""
    w = build_line_window(source_text, offset=0, limit=max_lines)
    return w.text, (w.next_offset is not None)


def list_dir(
    workspace_root: str,
    rel_path: str = ".",
    allowed_roots: Optional[Sequence[str]] = None,
    max_entries: int = MAX_LIST_ENTRIES,
    offset: int = 0,
) -> DirListing:
    """严格单层 scandir，过滤 .git / node_modules / __pycache__ 等。
    目录优先、名称字典序升序。支持游标分页（offset / next_offset）。超限返回 omitted 计数，不递归。
    """
    res = resolve_within_roots(workspace_root, rel_path, allowed_roots)
    if res is None:
        raise UnsafePathError(f"Path outside allowed roots: {rel_path}")

    matched_root, target_real = res
    if not os.path.exists(target_real):
        raise CodeExplorerError(f"Target path does not exist: {rel_path}")
    if not os.path.isdir(target_real):
        raise CodeExplorerError(f"Target is not a directory: {rel_path}")

    ws_real = os.path.realpath(os.path.abspath(workspace_root))
    origin = "workspace" if os.path.normcase(matched_root) == os.path.normcase(ws_real) else "external"

    raw_entries: List[DirEntryInfo] = []
    ignored_names = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv"}

    try:
        with os.scandir(target_real) as it:
            for entry in it:
                name = entry.name
                if name in ignored_names:
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    size = 0
                    if not is_dir:
                        try:
                            size = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            size = 0
                    raw_entries.append(
                        DirEntryInfo(
                            name=name,
                            kind="dir" if is_dir else "file",
                            size_bytes=size,
                        )
                    )
                except OSError:
                    continue
    except OSError as e:
        raise CodeExplorerError(f"Failed to scan directory: {e}") from e

    raw_entries.sort(key=lambda e: (e.kind != "dir", e.name.lower(), e.name))

    total_entries = len(raw_entries)
    effective_max = max(1, int(max_entries))
    effective_offset = max(0, int(offset))

    if effective_offset >= total_entries:
        clipped: List[DirEntryInfo] = []
        next_offset: Optional[int] = None
    else:
        clipped = raw_entries[effective_offset : effective_offset + effective_max]
        if effective_offset + len(clipped) < total_entries:
            next_offset = effective_offset + len(clipped)
        else:
            next_offset = None

    omitted = max(0, total_entries - len(clipped))

    rel_clean = rel_path.replace("\\", "/")
    return DirListing(
        rel_path=rel_clean,
        origin=origin,
        entries=clipped,
        total_entries=total_entries,
        omitted=omitted,
        offset=effective_offset,
        next_offset=next_offset,
    )


def grep(
    workspace_root: str,
    pattern: str,
    rel_path: str = ".",
    allowed_roots: Optional[Sequence[str]] = None,
    max_files: int = MAX_EXPLORE_FILES,
    deadline: float = DEFAULT_DEADLINE_SECONDS,
) -> GrepResult:
    """纯 Python 正则检索。
    1. pattern 校验长度 <= 1024，编译失败抛出 CodeExplorerError；
    2. deadline 为相对秒数，若 deadline <= 0 立即返回 files_scanned=0, truncated=True；
    3. 确定性遍历，目录与文件按字典序排序；
    4. 跳过 .git，跳过 >512KB 文件与 NUL 二进制文件；
    5. 每行仅对前 GREP_LINE_SCAN_CHARS (4096) 字符执行正则搜索；
    6. 每文件最多 20 条 matches（原始行），但 histogram 记录真实匹配次数；
    7. 全局最多 200 条 matches，超限置 truncated=True；
    8. 逐文件处理后检查 deadline，超时置 truncated=True 立即退出。
    """
    start_time = time.monotonic()

    if not pattern or len(pattern) > MAX_GREP_PATTERN_CHARS:
        raise CodeExplorerError(
            f"Pattern invalid or exceeds max length {MAX_GREP_PATTERN_CHARS} (len={len(pattern) if pattern else 0})"
        )
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise CodeExplorerError(f"Invalid regular expression '{pattern}': {e}") from e

    deadline_sec = float(deadline)
    if deadline_sec <= 0.0:
        return GrepResult(
            pattern=pattern,
            files_scanned=0,
            histogram=[],
            matches=[],
            truncated=True,
            elapsed_ms=0,
        )

    deadline_at = start_time + deadline_sec

    res = resolve_within_roots(workspace_root, rel_path, allowed_roots)
    if res is None:
        raise UnsafePathError(f"Path outside allowed roots: {rel_path}")

    matched_root, target_real = res
    if not os.path.exists(target_real):
        raise CodeExplorerError(f"Target path does not exist: {rel_path}")

    ignored_dirs = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv"}

    files_to_scan: List[str] = []
    if os.path.isfile(target_real):
        files_to_scan.append(target_real)
    else:
        for root_dir, dirs, files in os.walk(target_real):
            dirs[:] = sorted([d for d in dirs if d not in ignored_dirs])
            for f in sorted(files):
                files_to_scan.append(os.path.join(root_dir, f))

    files_scanned = 0
    histogram_map: Dict[str, int] = {}
    matches: List[GrepLineMatch] = []
    truncated = False

    max_files_limit = max(1, int(max_files))

    for file_path in files_to_scan:
        if files_scanned >= max_files_limit:
            truncated = True
            break

        rel_to_root = os.path.relpath(file_path, matched_root).replace("\\", "/")
        if is_sensitive_file(rel_to_root):
            continue

        try:
            st = os.stat(file_path)
            if st.st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue

        try:
            with open(file_path, "rb") as bf:
                raw = bf.read(MAX_FILE_BYTES + 1)
            if b"\x00" in raw[:4096]:
                continue
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            continue

        files_scanned += 1
        lines = text.split("\n")
        file_match_count = 0

        for line_idx, raw_line in enumerate(lines):
            line = raw_line.rstrip("\r")
            scan_chunk = line[:GREP_LINE_SCAN_CHARS]
            if regex.search(scan_chunk):
                file_match_count += 1
                if file_match_count <= MAX_GREP_HITS_PER_FILE and len(matches) < MAX_GREP_HITS:
                    matches.append(
                        GrepLineMatch(
                            rel_path=rel_to_root,
                            lineno=line_idx + 1,
                            text=line,
                        )
                    )

        if file_match_count > 0:
            histogram_map[rel_to_root] = file_match_count

        if len(matches) >= MAX_GREP_HITS:
            truncated = True
            break

        if time.monotonic() >= deadline_at:
            truncated = True
            break

    histogram = [
        GrepFileHit(rel_path=p, count=c)
        for p, c in sorted(histogram_map.items(), key=lambda item: (-item[1], item[0]))
    ]
    matches.sort(key=lambda m: (m.rel_path, m.lineno))

    elapsed_ms = max(0, int((time.monotonic() - start_time) * 1000))

    return GrepResult(
        pattern=pattern,
        files_scanned=files_scanned,
        histogram=histogram,
        matches=matches,
        truncated=truncated,
        elapsed_ms=elapsed_ms,
    )


def read_file_slice(
    workspace_root: str,
    rel_path: str,
    offset: int = 0,
    limit: Optional[int] = None,
    allowed_roots: Optional[Sequence[str]] = None,
) -> SlicedFile:
    """读取文件切片的唯一收敛入口。"""
    res = resolve_within_roots(workspace_root, rel_path, allowed_roots)
    if res is None:
        raise UnsafePathError(f"Path outside allowed roots: {rel_path}")

    matched_root, target_real = res
    if not os.path.exists(target_real):
        raise CodeExplorerError(f"File not found: {rel_path}")
    if not os.path.isfile(target_real):
        raise CodeExplorerError(f"Target is not a file: {rel_path}")

    ws_real = os.path.realpath(os.path.abspath(workspace_root))
    origin = "workspace" if os.path.normcase(matched_root) == os.path.normcase(ws_real) else "external"

    rel_display = os.path.relpath(target_real, matched_root).replace("\\", "/")
    if is_sensitive_file(rel_display):
        raise CodeExplorerError(f"Sensitive file access denied: {rel_display}")

    try:
        st = os.stat(target_real)
        if st.st_size > MAX_FILE_BYTES:
            raise CodeExplorerError(f"File size {st.st_size} exceeds maximum {MAX_FILE_BYTES}")
        file_size = st.st_size
    except OSError as e:
        raise CodeExplorerError(f"Failed to stat file: {e}") from e

    # 预算钳制 (Clarification C2: None -> MAX_SLICE_LINES)
    if origin == "workspace":
        req_limit = MAX_SLICE_LINES if limit is None else limit
        effective_limit = min(req_limit, MAX_SLICE_LINES)
        max_bytes = MAX_FILE_BYTES
        hint = ""
    else:
        req_limit = RING1_MAX_LINES if limit is None else limit
        effective_limit = min(req_limit, RING1_MAX_LINES)
        max_bytes = RING1_MAX_BYTES
        hint = "[EXTERNAL] 建议先使用 grep(pattern) 定位关键行"

    try:
        with open(target_real, "rb") as f:
            raw_bytes = f.read(MAX_FILE_BYTES + 1)
        if b"\x00" in raw_bytes[:1024]:
            raise CodeExplorerError(f"Binary file not supported: {rel_display}")
        source_text = raw_bytes.decode("utf-8", errors="replace")
    except OSError as e:
        raise CodeExplorerError(f"Failed to read file: {e}") from e

    window = build_line_window(
        source_text,
        offset=offset,
        limit=effective_limit,
        max_bytes=max_bytes,
    )

    symbols: List[SymbolIface] = []
    if rel_display.endswith(".py"):
        symbols, _, _ = extract_ast_interfaces(source_text, rel_display)
        lang = "python"
    else:
        lang = os.path.splitext(rel_display)[-1].lstrip(".") or "text"

    return SlicedFile(
        rel_path=rel_display,
        language=lang,
        symbols=symbols,
        slice_text=window.text,
        truncated=(window.next_offset is not None),
        size_bytes=file_size,
        start_line=window.start_line,
        end_line=window.end_line,
        total_lines=window.total_lines,
        next_offset=window.next_offset,
        origin=origin,
        hint=hint,
    )


def explore_code_slices(
    workspace_root: str,
    seed_files: List[str],
    max_hops: int = 1,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
) -> ExploreResult:
    """从种子文件开始，探索工作区代码切片与符号接口。
    
    ★ 严格遵循有界约束：
    - max_hops 钳制在 [0, 3] 之间；
    - 严格过滤敏感文件与越界路径；
    - 单文件大小上限 512KB；
    - 总扫描文件上限 30 个；
    - 运行超时熔断返回已搜集结果。
    """
    start_time = time.monotonic()
    deadline = start_time + deadline_seconds

    # 钳制探索跳数
    clamped_hops = max(0, min(int(max_hops), MAX_HOPS_LIMIT))

    result = ExploreResult(hops_used=0)
    visited_canonical: Set[str] = set()
    current_frontier: List[str] = sorted(list(dict.fromkeys(seed_files)), key=lambda p: str(p).replace("\\", "/"))
    root_real = os.path.realpath(os.path.abspath(workspace_root))

    hop_level = 0
    while current_frontier and hop_level <= clamped_hops:
        next_frontier: List[str] = []

        for rel_candidate in current_frontier:
            # 耗时熔断检查
            if time.monotonic() >= deadline:
                result.truncated = True
                break
            if len(result.files) >= MAX_EXPLORE_FILES:
                result.truncated = True
                break

            # 1. 路径安全性校验
            if not is_path_safe(root_real, rel_candidate):
                result.skipped.append(
                    SkippedFile(rel_path=rel_candidate, reason="unsafe_path", detail="路径越界或非法")
                )
                continue

            target_abs = os.path.normpath(
                rel_candidate if os.path.isabs(rel_candidate) else os.path.join(root_real, rel_candidate)
            )
            canonical_key = os.path.normcase(os.path.realpath(target_abs))
            if canonical_key in visited_canonical:
                continue
            visited_canonical.add(canonical_key)

            rel_display = os.path.relpath(target_abs, root_real).replace("\\", "/")

            # 2. 敏感文件过滤
            if is_sensitive_file(rel_display):
                result.skipped.append(
                    SkippedFile(rel_path=rel_display, reason="denylisted", detail="命中敏感文件黑名单")
                )
                continue

            # 3. 存在性与文件类型检查
            if not os.path.isfile(target_abs):
                result.skipped.append(
                    SkippedFile(rel_path=rel_display, reason="not_found", detail="目标文件不存在或为目录")
                )
                continue

            # 4. 体积上限检查 (512KB)
            try:
                st = os.stat(target_abs)
                if st.st_size > MAX_FILE_BYTES:
                    result.skipped.append(
                        SkippedFile(
                            rel_path=rel_display,
                            reason="too_large",
                            detail=f"文件体积 {st.st_size}B 超过上限 {MAX_FILE_BYTES}B",
                        )
                    )
                    continue
            except Exception as e:
                result.skipped.append(
                    SkippedFile(rel_path=rel_display, reason="stat_error", detail=str(e))
                )
                continue

            # 5. 读取与切片提取（统一走 read_file_slice）
            try:
                sliced = read_file_slice(
                    workspace_root=root_real,
                    rel_path=rel_display,
                    offset=0,
                    limit=MAX_SLICE_LINES,
                )
                clean_text = sliced.slice_text.replace("\r\n", "\n")
                if clean_text != sliced.slice_text:
                    sliced = SlicedFile(
                        rel_path=sliced.rel_path,
                        language=sliced.language,
                        symbols=sliced.symbols,
                        slice_text=clean_text,
                        truncated=sliced.truncated,
                        size_bytes=sliced.size_bytes,
                        start_line=sliced.start_line,
                        end_line=sliced.end_line,
                        total_lines=sliced.total_lines,
                        next_offset=sliced.next_offset,
                        origin=sliced.origin,
                        hint=sliced.hint,
                    )
                result.files.append(sliced)
            except CodeExplorerError as e:
                err_msg = str(e)
                if "Binary file" in err_msg:
                    result.skipped.append(SkippedFile(rel_path=rel_display, reason="binary_file", detail="检测到二进制文件特征"))
                elif "exceeds maximum" in err_msg:
                    result.skipped.append(SkippedFile(rel_path=rel_display, reason="too_large", detail=err_msg))
                elif "Sensitive file" in err_msg:
                    result.skipped.append(SkippedFile(rel_path=rel_display, reason="denylisted", detail="命中敏感文件黑名单"))
                else:
                    result.skipped.append(SkippedFile(rel_path=rel_display, reason="read_error", detail=err_msg))
                continue
            except Exception as e:
                result.skipped.append(SkippedFile(rel_path=rel_display, reason="read_error", detail=str(e)))
                continue

            # 6. Python 相对导入探索
            if rel_display.endswith(".py") and hop_level < clamped_hops:
                try:
                    with open(target_abs, "rb") as f:
                        raw_bytes = f.read(MAX_FILE_BYTES + 1)
                    src = raw_bytes.decode("utf-8", errors="replace")
                    _, local_imports, _ = extract_ast_interfaces(src, rel_display)
                    file_dir = os.path.dirname(target_abs)
                    for imp in sorted(local_imports):
                        mod_as_path = imp.replace(".", os.sep) + ".py"
                        cand_local = os.path.join(file_dir, mod_as_path)
                        cand_root = os.path.join(root_real, mod_as_path)
                        if os.path.isfile(cand_local):
                            next_frontier.append(os.path.relpath(cand_local, root_real))
                        elif os.path.isfile(cand_root):
                            next_frontier.append(os.path.relpath(cand_root, root_real))
                except Exception:
                    pass

        current_frontier = sorted(list(dict.fromkeys(next_frontier)), key=lambda p: str(p).replace("\\", "/"))
        hop_level += 1
        result.hops_used = hop_level

    # 规范化确定性排序：按 POSIX 相对路径字典序排序，保证跨环境与输入顺序的绝对一致
    result.files = sorted(result.files, key=lambda sf: sf.rel_path.replace("\\", "/"))
    result.skipped = sorted(result.skipped, key=lambda sk: (sk.rel_path.replace("\\", "/"), sk.reason))
    result.elapsed_ms = int((time.monotonic() - start_time) * 1000)
    return result
