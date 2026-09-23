# -*- coding: utf-8 -*-
"""Source-level vendor neutrality regression gate.

Ensures that core modules in plugins/quench-dev-tasks/server maintain absolute
vendor neutrality: no hardcoded vendor names, endpoints, or environment variable names,
except inside strictly audited sentinel blocks (# -- vendor-presets:start / end)
or single-line pragmas (# vendor-literal: allow).
"""
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Iterator

import pytest

# 规范契约常量
SERVER_DIR: Path = Path(__file__).resolve().parent.parent
SCAN_ROOT: Path = SERVER_DIR
SCAN_GLOB: str = "*.py"                       # 仅顶层，不递归
EXCLUDED_DIRS: tuple[str, ...] = ("tests", "adapters", "hooks", "__pycache__")

BANNED_VENDOR_TOKENS: tuple[str, ...] = (
    "deepseek", "claude", "gemini", "mistral", "qwen", "llama", "gpt-4", "gpt-3", "o1-",
)
BANNED_VENDOR_HOSTS: tuple[str, ...] = (
    "api.openai.com", "api.deepseek.com", "api.anthropic.com", "generativelanguage.googleapis.com",
)

PRESET_BLOCK_START: str = "# -- vendor-presets:start"
PRESET_BLOCK_END: str = "# -- vendor-presets:end"
LINE_PRAGMA: str = "# vendor-literal: allow"


@dataclass(frozen=True)
class VendorViolation:
    path: str
    lineno: int
    token: str
    snippet: str


def iter_scannable_lines(root: Path) -> Iterator[tuple[Path, int, str]]:
    """遍历目标根路径下的所有合规顶层 Python 源码行。"""
    root_path = Path(root)
    if root_path.is_file():
        candidate_files = [root_path]
    else:
        candidate_files = sorted(p for p in root_path.glob(SCAN_GLOB) if p.is_file())

    for p in candidate_files:
        # 排除指定目录与隐藏文件
        if any(part in EXCLUDED_DIRS for part in p.parts):
            continue
        if p.name.startswith(".") or not p.name.endswith(".py"):
            continue

        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                yield (p, lineno, line)


def find_vendor_violations(root: Path) -> list[VendorViolation]:
    """扫描 Python 文件中是否存在未豁免的厂商字面量。"""
    violations: list[VendorViolation] = []
    current_file: Path | None = None
    in_preset_block: bool = False

    for file_path, lineno, line in iter_scannable_lines(root):
        if file_path != current_file:
            if current_file is not None and in_preset_block:
                raise AssertionError(f"Unclosed preset block in {current_file}")
            current_file = file_path
            in_preset_block = False

        stripped = line.strip()
        if stripped.startswith(PRESET_BLOCK_START):
            if in_preset_block:
                raise AssertionError(f"Nested preset block start in {file_path}:{lineno}")
            in_preset_block = True
            continue

        if stripped.startswith(PRESET_BLOCK_END):
            if not in_preset_block:
                raise AssertionError(f"Unexpected preset block end without start in {file_path}:{lineno}")
            in_preset_block = False
            continue

        if in_preset_block:
            continue

        if LINE_PRAGMA in line:
            continue

        line_cf = line.casefold()
        for token in (*BANNED_VENDOR_TOKENS, *BANNED_VENDOR_HOSTS):
            if token in line_cf:
                violations.append(
                    VendorViolation(
                        path=str(file_path),
                        lineno=lineno,
                        token=token,
                        snippet=line.strip()[:120],
                    )
                )

    if current_file is not None and in_preset_block:
        raise AssertionError(f"Unclosed preset block in {current_file}")

    return violations


def test_core_modules_have_no_vendor_literals():
    """断言核心服务器模块（非 tests）100% 协议中立，不含未豁免的厂商字面量。"""
    t0 = time.perf_counter()
    violations = find_vendor_violations(SCAN_ROOT)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # 性能护栏：顶层扫描耗时必须 < 200 ms（超时即视为误设为全量递归）
    assert elapsed_ms < 200, f"Scanner took {elapsed_ms:.2f} ms (expected < 200 ms)"

    # 防自我命中与测试排除：断言扫描到的任何路径都不以 test_ 开头
    scanned_files = [p for p, _, _ in iter_scannable_lines(SCAN_ROOT)]
    scanned_filenames = {p.name for p in scanned_files}
    assert not any(name.startswith("test_") for name in scanned_filenames), (
        f"Test files must not be scanned: {scanned_filenames}"
    )

    # 核心模块必须 100% 纯净中立，无任何违规
    assert violations == [], f"Found vendor violations in core modules: {violations}"


def test_scanner_detects_planted_vendor_literal(tmp_path: Path):
    """自证断言：在 tmp_path 植入未经 pragma 豁免的 DeepSeekClient，断言扫描器必命中，防假绿。"""
    planted_file = tmp_path / "planted_module.py"
    planted_file.write_text(
        "class DeepSeekClient:\n    pass\n",
        encoding="utf-8",
    )
    violations = find_vendor_violations(tmp_path)
    assert len(violations) >= 1
    assert violations[0].token == "deepseek"
    assert violations[0].lineno == 1
    assert "DeepSeekClient" in violations[0].snippet


def test_pragma_suppresses_single_line_only(tmp_path: Path):
    """断言行级 pragma 仅豁免当前行，下一行违规仍被精准捕获。"""
    test_file = tmp_path / "pragma_test.py"
    test_file.write_text(
        '# Line 1: Allowed line\n'
        'DEFAULT_FALLBACK = "deepseek"  # vendor-literal: allow\n'
        'LEAKED_VENDOR = "deepseek"\n',
        encoding="utf-8",
    )
    violations = find_vendor_violations(tmp_path)
    assert len(violations) == 1
    assert violations[0].lineno == 3
    assert violations[0].token == "deepseek"


def test_unclosed_preset_block_fails(tmp_path: Path):
    """断言未闭合哨兵块、嵌套哨兵块以及孤立闭合块均触发 AssertionError。"""
    # 1. 未闭合哨兵块直接断言失败
    unclosed = tmp_path / "unclosed.py"
    unclosed.write_text(
        '# Header\n'
        '# -- vendor-presets:start\n'
        'PRESETS = {"deepseek": "url"}\n',
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match=r"(?i)unclosed"):
        find_vendor_violations(tmp_path)

    # 2. 嵌套哨兵块失败
    unclosed.unlink()
    nested = tmp_path / "nested.py"
    nested.write_text(
        '# -- vendor-presets:start\n'
        '# -- vendor-presets:start\n'
        '# -- vendor-presets:end\n',
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match=r"(?i)nested|already in"):
        find_vendor_violations(tmp_path)

    # 3. 孤立 end 哨兵块失败
    nested.unlink()
    orphan_end = tmp_path / "orphan_end.py"
    orphan_end.write_text(
        '# -- vendor-presets:end\n',
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match=r"(?i)without start|unexpected"):
        find_vendor_violations(tmp_path)


def test_preset_registry_is_only_exempted_region():
    """断言 project_config.py 仅在哨兵块内部定义厂商预设，其余区域 100% 协议中立。"""
    cfg_file = SCAN_ROOT / "project_config.py"
    assert cfg_file.exists(), f"Configuration file not found: {cfg_file}"

    content = cfg_file.read_text(encoding="utf-8")
    assert content.count(PRESET_BLOCK_START) == 1, "Must contain exactly one preset block start"
    assert content.count(PRESET_BLOCK_END) == 1, "Must contain exactly one preset block end"
    assert content.index(PRESET_BLOCK_START) < content.index(PRESET_BLOCK_END)

    # project_config.py 本身扫描必须 0 违规
    violations = find_vendor_violations(cfg_file)
    assert violations == [], f"Found unexpected violations in project_config.py: {violations}"
