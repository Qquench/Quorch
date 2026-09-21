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
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

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
class SlicedFile:
    """安全切片后的单个文件结构化信息。"""
    rel_path: str
    language: str
    symbols: List[SymbolIface]
    slice_text: str
    truncated: bool = False
    size_bytes: int = 0


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


def is_path_safe(workspace_root: str, target_path: str) -> bool:
    """检查目标路径是否严格安全且限制在 workspace_root 内部。
    防御：空字符注入、符号链接逃逸、Windows 跨盘符崩溃。
    """
    if not target_path or "\x00" in target_path or "\x00" in workspace_root:
        return False

    try:
        # 转为绝对路径并解构符号链接
        root_real = os.path.realpath(os.path.abspath(workspace_root))
        if os.path.isabs(target_path):
            target_real = os.path.realpath(target_path)
        else:
            target_real = os.path.realpath(os.path.join(root_real, target_path))

        # Windows 大小写不敏感规整
        root_norm = os.path.normcase(root_real)
        target_norm = os.path.normcase(target_real)

        # 跨盘符防御：若盘符不一致，commonpath 会抛出 ValueError
        try:
            common = os.path.commonpath([root_norm, target_norm])
            return common == root_norm
        except ValueError:
            # 跨盘符直接判定为不安全逃逸
            return False
    except Exception:
        return False


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


def build_safe_slice(
    source_text: str,
    symbols: List[SymbolIface],
    max_lines: int = MAX_SLICE_LINES,
) -> Tuple[str, bool]:
    """根据提取的符号与源文本构建紧凑切片（最多 max_lines 行）。"""
    lines = source_text.splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines), False

    # 若超过上限，生成结构化摘要切片：导入头部 + 符号签名
    slice_lines: List[str] = []
    # 提取前 20 行（通常包含导入与模块常量）
    header_count = min(20, len(lines))
    slice_lines.extend(lines[:header_count])
    slice_lines.append(f"\n# ... [中间细节折叠，共 {len(lines)} 行，以下为核心接口声明] ...\n")

    for sym in symbols:
        if len(slice_lines) >= max_lines - 5:
            slice_lines.append("# ... [切片行数超限截断] ...")
            return "\n".join(slice_lines), True
        doc_snippet = f"  # {sym.docstring.splitlines()[0]}" if sym.docstring else ""
        slice_lines.append(f"{sym.signature}{doc_snippet}")

    return "\n".join(slice_lines[:max_lines]), True


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
    current_frontier: List[str] = list(seed_files)
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
                file_size = st.st_size
            except Exception as e:
                result.skipped.append(
                    SkippedFile(rel_path=rel_display, reason="stat_error", detail=str(e))
                )
                continue

            # 5. 读取与切片提取
            try:
                with open(target_abs, "rb") as f:
                    raw_bytes = f.read(MAX_FILE_BYTES + 1)
                
                # 检查空字节 (二进制文件检测)
                if b"\x00" in raw_bytes[:1024]:
                    result.skipped.append(
                        SkippedFile(rel_path=rel_display, reason="binary_file", detail="检测到二进制文件特征")
                    )
                    continue

                source_text = raw_bytes.decode("utf-8", errors="replace")
            except Exception as e:
                result.skipped.append(
                    SkippedFile(rel_path=rel_display, reason="read_error", detail=str(e))
                )
                continue

            # 6. Python 文件走 AST 结构化提取；其他文本文件走普通切片
            if rel_display.endswith(".py"):
                symbols, local_imports, parsed_ok = extract_ast_interfaces(source_text, rel_display)
                slice_str, is_trunc = build_safe_slice(source_text, symbols, MAX_SLICE_LINES)
                result.files.append(
                    SlicedFile(
                        rel_path=rel_display,
                        language="python",
                        symbols=symbols,
                        slice_text=slice_str,
                        truncated=is_trunc,
                        size_bytes=file_size,
                    )
                )

                # 若还有剩余 hop 预算，尝试将相对导入加入下一轮探索边界
                if hop_level < clamped_hops:
                    file_dir = os.path.dirname(target_abs)
                    for imp in local_imports:
                        # 尝试将模块名映射为本地 .py 文件
                        mod_as_path = imp.replace(".", os.sep) + ".py"
                        cand_local = os.path.join(file_dir, mod_as_path)
                        cand_root = os.path.join(root_real, mod_as_path)
                        if os.path.isfile(cand_local):
                            next_frontier.append(os.path.relpath(cand_local, root_real))
                        elif os.path.isfile(cand_root):
                            next_frontier.append(os.path.relpath(cand_root, root_real))
            else:
                # 针对 .yaml, .json, .md 等文件进行行级安全截断
                lines = source_text.splitlines()
                slice_str = "\n".join(lines[:MAX_SLICE_LINES])
                is_trunc = len(lines) > MAX_SLICE_LINES
                ext = os.path.splitext(rel_display)[-1].lstrip(".") or "text"
                result.files.append(
                    SlicedFile(
                        rel_path=rel_display,
                        language=ext,
                        symbols=[],
                        slice_text=slice_str,
                        truncated=is_trunc,
                        size_bytes=file_size,
                    )
                )

        current_frontier = next_frontier
        hop_level += 1
        result.hops_used = hop_level

    result.elapsed_ms = int((time.monotonic() - start_time) * 1000)
    return result
