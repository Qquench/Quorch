# -*- coding: utf-8 -*-
"""Unified ArchitectureHygieneScanner implementation for server modules."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

from _hygiene.rules import (
    MERGED_EXPANSION_ALLOWLIST,
    RULE_IDS,
    RULE_SCOPE,
    SCAN_ROOTS,
)

PRESET_BLOCK_START: Final[str] = "# -- vendor-presets:start"
PRESET_BLOCK_END: Final[str] = "# -- vendor-presets:end"
LINE_PRAGMA: Final[str] = "# vendor-literal: allow"

ALLOWED_PROVIDER_EGRESS_FILES: Final[frozenset[str]] = frozenset(
    {
        "server/reviewer_engine.py",
        "server/project_config.py",
    }
)


class HygieneScanError(RuntimeError):
    """携带 file_path / lineno；禁止静默跳过。"""

    def __init__(self, file_path: str, lineno: int, detail: str) -> None:
        super().__init__(f"HygieneScanError at {file_path}:{lineno}: {detail}")
        self.file_path = file_path
        self.lineno = lineno
        self.detail = detail


@dataclass(frozen=True)
class HygieneFinding:
    rule_id: str
    file_path: str               # plugin 根相对 POSIX 路径（server/...）
    lineno: int
    symbol_or_token: str
    message: str


def finding_sort_key(f: HygieneFinding) -> tuple[str, str, int, str]:
    """[E3] 升维去重排序键：(rule_id, file_path, lineno, symbol_or_token)，彻底杜绝同一物理行多违规符号折叠。"""
    return (f.rule_id, f.file_path, f.lineno, f.symbol_or_token)


class ArchitectureHygieneScanner:
    """单次 AST 解析、多门禁规则归并的架构卫生扫描器。"""

    def __init__(self, server_dir: Path) -> None:
        self.server_dir = Path(server_dir).resolve()
        self.plugin_root = self.server_dir.parent
        self._cached_findings: list[HygieneFinding] | None = None

    def rel_posix(self, path: Path) -> str:
        """转换为 plugin 根相对 POSIX 路径（server/...）。"""
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(self.plugin_root).as_posix()
        except ValueError:
            try:
                rel = resolved.relative_to(self.server_dir).as_posix()
                return f"server/{rel}"
            except ValueError:
                return resolved.name

    def get_core_module_paths(self) -> list[Path]:
        """获取所有核心 server Python 模块（排除 tests, adapters, hooks, __pycache__ 等）。"""
        paths: list[Path] = []
        for p in sorted(self.server_dir.glob("*.py")):
            if p.is_file() and not p.name.startswith("."):
                paths.append(p)
        return paths

    def _applies_rule_to_path(self, rule_id: str, rel_path: str, is_isolated_file_scan: bool) -> bool:
        """判断某规则是否适用于给定的相对文件路径。"""
        if is_isolated_file_scan:
            return True
        spec = SCAN_ROOTS.get(rule_id, ())
        if spec == ("server",):
            return rel_path.startswith("server/") and "/" not in rel_path[len("server/"):]
        return rel_path in spec

    def scan_file(self, file_path: Path, is_isolated_file_scan: bool = True) -> list[HygieneFinding]:
        """扫描单个 Python 文件，应用适用规则，单次 ast.parse 跨规则共享语法树。"""
        resolved_path = Path(file_path).resolve()
        rel_path = self.rel_posix(resolved_path)

        try:
            source = resolved_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = resolved_path.read_text(encoding="utf-8-sig", errors="replace")

        try:
            tree = ast.parse(source, filename=str(resolved_path))
        except SyntaxError as e:
            raise HygieneScanError(
                file_path=rel_path,
                lineno=getattr(e, "lineno", 1) or 1,
                detail=str(e),
            ) from e

        source_lines = source.splitlines()
        findings: list[HygieneFinding] = []

        # 规则 1: lease_symbol_removal
        if self._applies_rule_to_path("lease_symbol_removal", rel_path, is_isolated_file_scan):
            forbidden_lease = set(RULE_SCOPE["lease_symbol_removal"])
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in forbidden_lease:
                    findings.append(
                        HygieneFinding(
                            rule_id="lease_symbol_removal",
                            file_path=rel_path,
                            lineno=getattr(node, "lineno", 1),
                            symbol_or_token=node.id,
                            message=f"Forbidden lease symbol '{node.id}' in Name",
                        )
                    )
                elif isinstance(node, ast.Attribute) and node.attr in forbidden_lease:
                    findings.append(
                        HygieneFinding(
                            rule_id="lease_symbol_removal",
                            file_path=rel_path,
                            lineno=getattr(node, "lineno", 1),
                            symbol_or_token=node.attr,
                            message=f"Forbidden lease symbol '{node.attr}' in Attribute",
                        )
                    )
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden_lease:
                    findings.append(
                        HygieneFinding(
                            rule_id="lease_symbol_removal",
                            file_path=rel_path,
                            lineno=getattr(node, "lineno", 1),
                            symbol_or_token=node.name,
                            message=f"Forbidden lease symbol '{node.name}' in FunctionDef",
                        )
                    )
                elif isinstance(node, ast.ClassDef) and node.name in forbidden_lease:
                    findings.append(
                        HygieneFinding(
                            rule_id="lease_symbol_removal",
                            file_path=rel_path,
                            lineno=getattr(node, "lineno", 1),
                            symbol_or_token=node.name,
                            message=f"Forbidden lease symbol '{node.name}' in ClassDef",
                        )
                    )

        # 规则 2: touch_outcome_truthiness
        if self._applies_rule_to_path("touch_outcome_truthiness", rel_path, is_isolated_file_scan):
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    test = node.test
                    # 直接调用: if <expr>.touch():
                    if (
                        isinstance(test, ast.Call)
                        and isinstance(test.func, ast.Attribute)
                        and test.func.attr == "touch"
                    ):
                        findings.append(
                            HygieneFinding(
                                rule_id="touch_outcome_truthiness",
                                file_path=rel_path,
                                lineno=getattr(node, "lineno", 1),
                                symbol_or_token="touch",
                                message="Implicit truthiness check on touch() call",
                            )
                        )
                    # 一元非: if not <expr>.touch():
                    elif (
                        isinstance(test, ast.UnaryOp)
                        and isinstance(test.op, ast.Not)
                        and isinstance(test.operand, ast.Call)
                        and isinstance(test.operand.func, ast.Attribute)
                        and test.operand.func.attr == "touch"
                    ):
                        findings.append(
                            HygieneFinding(
                                rule_id="touch_outcome_truthiness",
                                file_path=rel_path,
                                lineno=getattr(node, "lineno", 1),
                                symbol_or_token="touch",
                                message="Implicit truthiness check on 'not touch()' call",
                            )
                        )

        # 规则 3: vendor_literal_in_core
        if self._applies_rule_to_path("vendor_literal_in_core", rel_path, is_isolated_file_scan):
            in_preset_block = False
            banned_vendors = set(RULE_SCOPE["vendor_literal_in_core"])

            for lineno, line in enumerate(source_lines, 1):
                stripped = line.strip()
                if stripped.startswith(PRESET_BLOCK_START):
                    if in_preset_block:
                        raise HygieneScanError(
                            file_path=rel_path,
                            lineno=lineno,
                            detail="Nested preset block start",
                        )
                    in_preset_block = True
                    continue

                if stripped.startswith(PRESET_BLOCK_END):
                    if not in_preset_block:
                        raise HygieneScanError(
                            file_path=rel_path,
                            lineno=lineno,
                            detail="Unexpected preset block end without start",
                        )
                    in_preset_block = False
                    continue

                if in_preset_block or LINE_PRAGMA in line:
                    continue

                line_cf = line.casefold()
                for token in banned_vendors:
                    if token in line_cf:
                        findings.append(
                            HygieneFinding(
                                rule_id="vendor_literal_in_core",
                                file_path=rel_path,
                                lineno=lineno,
                                symbol_or_token=token,
                                message=f"Unexempted vendor literal '{token}' in source line",
                            )
                        )

            if in_preset_block:
                raise HygieneScanError(
                    file_path=rel_path,
                    lineno=len(source_lines),
                    detail="Unclosed preset block at EOF",
                )

        # 规则 4: api_bypass
        if self._applies_rule_to_path("api_bypass", rel_path, is_isolated_file_scan):
            banned_modules = {
                "openai",
                "anthropic",
                "google.generativeai",
                "google.genai",
                "mistralai",
                "cohere",
            }
            banned_endpoints = {
                "api.deepseek.com",
                "api.openai.com",
                "api.anthropic.com",
                "generativelanguage.googleapis.com",
            }
            banned_env_vars = {
                "DEEPSEEK_API_KEY",
                "DEEPSEEK_API_KEY_QUENCH",
                "OPENAI_API_KEY",
                "ANTHROPIC_API_KEY",
                "GEMINI_API_KEY",
            }

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_mod = alias.name.split(".")[0]
                        if alias.name in banned_modules or top_mod in banned_modules:
                            if rel_path not in ALLOWED_PROVIDER_EGRESS_FILES:
                                findings.append(
                                    HygieneFinding(
                                        rule_id="api_bypass",
                                        file_path=rel_path,
                                        lineno=getattr(node, "lineno", 1),
                                        symbol_or_token=alias.name,
                                        message=f"Direct import of provider SDK '{alias.name}' is prohibited",
                                    )
                                )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top_mod = node.module.split(".")[0]
                        if node.module in banned_modules or top_mod in banned_modules:
                            if rel_path not in ALLOWED_PROVIDER_EGRESS_FILES:
                                findings.append(
                                    HygieneFinding(
                                        rule_id="api_bypass",
                                        file_path=rel_path,
                                        lineno=getattr(node, "lineno", 1),
                                        symbol_or_token=node.module,
                                        message=f"Direct import from provider SDK '{node.module}' is prohibited",
                                    )
                                )
                        if "DeepSeekClient" in [a.name for a in node.names]:
                            if rel_path != "server/reviewer_engine.py":
                                findings.append(
                                    HygieneFinding(
                                        rule_id="api_bypass",
                                        file_path=rel_path,
                                        lineno=getattr(node, "lineno", 1),
                                        symbol_or_token="DeepSeekClient",
                                        message="Direct import of provider client 'DeepSeekClient' is prohibited",
                                    )
                                )
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    val_lower = node.value.lower()
                    for ep in banned_endpoints:
                        if ep in val_lower:
                            if rel_path not in ALLOWED_PROVIDER_EGRESS_FILES:
                                findings.append(
                                    HygieneFinding(
                                        rule_id="api_bypass",
                                        file_path=rel_path,
                                        lineno=getattr(node, "lineno", 1),
                                        symbol_or_token=ep,
                                        message=f"Hard-coded provider endpoint '{ep}' found",
                                    )
                                )
                elif isinstance(node, ast.Call):
                    fn_name = ""
                    if isinstance(node.func, ast.Attribute):
                        fn_name = node.func.attr
                    elif isinstance(node.func, ast.Name):
                        fn_name = node.func.id
                    if fn_name in ("get", "getenv") and node.args:
                        first_arg = node.args[0]
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            up_val = first_arg.value.upper()
                            if up_val in banned_env_vars:
                                if rel_path not in ALLOWED_PROVIDER_EGRESS_FILES:
                                    findings.append(
                                        HygieneFinding(
                                            rule_id="api_bypass",
                                            file_path=rel_path,
                                            lineno=getattr(node, "lineno", 1),
                                            symbol_or_token=up_val,
                                            message=f"Direct access to provider API key '{up_val}' is prohibited",
                                        )
                                    )
                elif isinstance(node, ast.Subscript):
                    if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                        up_val = node.slice.value.upper()
                        if up_val in banned_env_vars:
                            if rel_path not in ALLOWED_PROVIDER_EGRESS_FILES:
                                findings.append(
                                    HygieneFinding(
                                        rule_id="api_bypass",
                                        file_path=rel_path,
                                        lineno=getattr(node, "lineno", 1),
                                        symbol_or_token=up_val,
                                        message=f"Direct subscript access to provider API key '{up_val}' is prohibited",
                                    )
                                )

        # 按 finding_sort_key 升维去重排序
        seen_keys = set()
        deduped: list[HygieneFinding] = []
        for f in sorted(findings, key=finding_sort_key):
            k = finding_sort_key(f)
            if k not in seen_keys:
                seen_keys.add(k)
                deduped.append(f)

        return deduped

    def scan_all_core_modules(self) -> list[HygieneFinding]:
        """单次遍历 server 核心模块，单次 ast.parse，集中执行全部规则。"""
        all_findings: list[HygieneFinding] = []
        for file_path in self.get_core_module_paths():
            file_findings = self.scan_file(file_path, is_isolated_file_scan=False)
            all_findings.extend(file_findings)

        seen_keys = set()
        deduped: list[HygieneFinding] = []
        for f in sorted(all_findings, key=finding_sort_key):
            k = finding_sort_key(f)
            if k not in seen_keys:
                seen_keys.add(k)
                deduped.append(f)

        self._cached_findings = deduped
        return deduped

    def findings_for(self, rule_id: str) -> list[HygieneFinding]:
        """返回指定 rule_id 的违规项列表（未知 rule_id 抛 KeyError）。"""
        if rule_id not in RULE_IDS:
            raise KeyError(f"Unknown rule_id: '{rule_id}' (valid: {RULE_IDS})")

        if self._cached_findings is None:
            self.scan_all_core_modules()

        assert self._cached_findings is not None
        rule_findings = [f for f in self._cached_findings if f.rule_id == rule_id]
        return sorted(rule_findings, key=finding_sort_key)

    def inspected_tokens(self, rule_id: str) -> frozenset[tuple[str, str]]:
        """返回指定 rule_id 实际检查的 (rel_posix_path, symbol_or_token) 二元组集合。"""
        if rule_id not in RULE_IDS:
            raise KeyError(f"Unknown rule_id: '{rule_id}' (valid: {RULE_IDS})")

        spec = SCAN_ROOTS[rule_id]
        if spec == ("server",):
            target_paths = [self.rel_posix(p) for p in self.get_core_module_paths()]
        else:
            target_paths = list(spec)

        tokens = RULE_SCOPE[rule_id]
        pairs = {(path_str, token) for path_str in target_paths for token in tokens}
        return frozenset(pairs)

    def scope_report(self) -> frozenset[tuple[str, str, str]]:
        """由实际遍历派生的全量检查范围三元组集合 (rule_id, rel_posix_path, symbol_or_token)。"""
        triples = set()
        for r in RULE_IDS:
            for path_str, token in self.inspected_tokens(r):
                triples.add((r, path_str, token))
        return frozenset(triples)
