# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import os
import sys
import fnmatch
import re
import tempfile
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple, Literal
import urllib.parse
import yaml

CURRENT_SCHEMA_VERSION = "1.0"

_DEFAULT_SCHEMA_VERSION_PATCH = 'schema_version: "1.0"\n'
_DEFAULT_FAST_TRACK_PATCH = """fast_track_rules:
  allow_untracked_patterns: []
"""
_SEEN_DEPRECATED_PROVIDERS: set[str] = set()


DEFAULT_UNMANAGED_EXTENSIONS = {
    # 文档类
    ".md", ".markdown", ".txt", ".rst", ".adoc",
    # 图片与素材类
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    # 设计图类
    ".drawio", ".puml", ".mermaid",
    # 模板与示例类（新增）
    ".sample", ".example", ".bak",
    # 数据与日志类（新增）
    ".log", ".csv", ".tsv", ".parquet",
    # 锁文件（新增，非代码产物；构建清单在下方精确受管）
    ".lock",
}

DEFAULT_UNMANAGED_DIRS = (
    "docs/", "doc/", "documentation/", "future_roadmap/",
    "roadmap/", "notes/", "manuals/", "sample_data/",
    "samples/", ".vscode/", ".idea/", ".github/",
    ".agents/.quorch/", ".agents/logs/",
)

CRITICAL_CODE_MANIFEST_PATTERNS: list[str] = [
    # 精确匹配
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum",
    "pom.xml", "build.gradle", "build.gradle.kts",
    # Glob 模式匹配（支持容器、配置与环境变体）
    "dockerfile*",
    "docker-compose*.yml", "docker-compose*.yaml",
    "tsconfig*.json",
    ".env",  # .env 本身是高危凭据文件
]

CRITICAL_CODE_MANIFESTS = set(CRITICAL_CODE_MANIFEST_PATTERNS)


def _match_glob(target_rel: str, pattern: str) -> bool:
    norm_pattern = pattern.replace("\\", "/").lower().strip()
    target_rel = target_rel.replace("\\", "/").lower().strip("/")
    basename = os.path.basename(target_rel)

    if "/" not in norm_pattern:
        if fnmatch.fnmatch(basename, norm_pattern):
            return True
        if fnmatch.fnmatch(target_rel, norm_pattern):
            return True

    if fnmatch.fnmatch(target_rel, norm_pattern):
        return True

    if norm_pattern.endswith("/**"):
        prefix = norm_pattern[:-3].strip("/")
        if target_rel.startswith(prefix + "/") or target_rel == prefix:
            return True
        if f"/{prefix}/" in f"/{target_rel}/":
            return True

    if norm_pattern.endswith("/*"):
        prefix = norm_pattern[:-2].strip("/")
        if target_rel.startswith(prefix + "/"):
            return True

    return False


DispatchStrategy = Literal["subagent", "engine", "manual"]


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str
    api_key_env: str | None
    requires_thinking_flag: bool = False


# -- vendor-presets:start
PROVIDER_PRESETS: Mapping[str, ProviderPreset | None] = MappingProxyType({
    "openai": ProviderPreset("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "deepseek": ProviderPreset("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "ollama": ProviderPreset("http://127.0.0.1:11434/v1", None),
    "vllm": ProviderPreset("http://127.0.0.1:8000/v1", None),
    "custom": ProviderPreset("", None),
    "none": None,
})
PROVIDER_ALIASES: Mapping[str, str] = MappingProxyType({
    "deepseek-compatible": "deepseek",
    "openai-compatible": "openai",
})
# -- vendor-presets:end


def resolve_preset(provider: str) -> ProviderPreset | None:
    """解析 provider 对应的预设端点与环境变量（支持别名映射）。"""
    if not provider:
        return None
    key = str(provider).lower().strip()
    if key in PROVIDER_ALIASES:
        key = PROVIDER_ALIASES[key]
    return PROVIDER_PRESETS.get(key)


DEFAULT_MAX_TOTAL_INJECTION_CHARS: int = 40000
DEFAULT_WINDOW_LINES: int = 200
MAX_LINES_PER_SLICE: int = 600
MIN_TOTAL_INJECTION_CHARS: int = 512
MAX_TOTAL_INJECTION_CHARS_UPPER: int = 200_000


def _coerce_positive_int(raw: object, *, default: int, lo: int, hi: int) -> int:
    """Coerce YAML scalar to a clamped int; never raises on malformed input. Excludes bool."""
    if isinstance(raw, bool) or raw is None:
        return default
    try:
        val = int(raw)
        return max(lo, min(hi, val))
    except (ValueError, TypeError):
        return default


@dataclass
class ReviewerEngineConfig:
    mode: str = "auto"  # "auto" | "subagent" | "engine" | "manual"
    strategy_order: list[str] = field(
        default_factory=lambda: ["subagent", "engine", "manual"]
    )
    provider: str = "none"                       # 不再默认任何厂商
    model: str = "default"                       # 通用占位，不再默认厂商模型名
    api_key_env: str | None = None               # 不再默认厂商 Key 变量名
    base_url: str = ""                           # 空 -> 由 preset 推导；preset 亦缺失 -> 判定未配置
    thinking: bool = True
    reasoning_effort: str = "high"
    timeout_seconds: int = 60
    max_retries: int = 2
    max_tool_hops: int = 3
    max_total_injection_chars: int = DEFAULT_MAX_TOTAL_INJECTION_CHARS
    default_window_lines: int = DEFAULT_WINDOW_LINES
    max_lines_per_slice: int = MAX_LINES_PER_SLICE

    def __post_init__(self) -> None:
        self.max_total_injection_chars = _coerce_positive_int(
            self.max_total_injection_chars,
            default=DEFAULT_MAX_TOTAL_INJECTION_CHARS,
            lo=MIN_TOTAL_INJECTION_CHARS,
            hi=MAX_TOTAL_INJECTION_CHARS_UPPER,
        )
        self.max_lines_per_slice = _coerce_positive_int(
            self.max_lines_per_slice,
            default=MAX_LINES_PER_SLICE,
            lo=30,
            hi=5000,
        )
        self.default_window_lines = _coerce_positive_int(
            self.default_window_lines,
            default=DEFAULT_WINDOW_LINES,
            lo=30,
            hi=self.max_lines_per_slice,
        )
        if self.default_window_lines > self.max_lines_per_slice:
            self.default_window_lines = self.max_lines_per_slice


def create_reviewer_client(
    config: ReviewerEngineConfig,
    *,
    sink: Any = None,
) -> Any:
    """工厂函数：根据声明式配置创建厂商中立 ReviewerClient。
    返回 None 表示引擎未配置（调用方必须走降级卡，严禁自行扮演 Reviewer）。
    """
    from reviewer_engine import ReviewerClient, ReviewerNotConfiguredError

    if not config or config.provider in ("none", "", None):
        return None

    prov = str(config.provider).lower().strip()
    preset = resolve_preset(prov)

    base_url = (config.base_url or "").strip()
    api_key_env = config.api_key_env

    if preset is not None:
        if not base_url:
            base_url = preset.base_url
        if api_key_env is None:
            api_key_env = preset.api_key_env
    else:
        # 未在注册表中
        if not base_url:
            raise ReviewerNotConfiguredError(
                f"未知 Reviewer provider='{config.provider}' 且未显式指定 base_url。"
                f"请在 quench_stack.yaml 中配置有效的 base_url 或使用已知预设: {list(PROVIDER_PRESETS.keys())}"
            )

    if not base_url:
        raise ReviewerNotConfiguredError(f"Reviewer 引擎 base_url 为空 (provider='{prov}')")

    # URL 校验
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise ReviewerNotConfiguredError(f"base_url 必须为 http 或 https 协议: '{base_url}'")
    if not parsed.hostname:
        raise ReviewerNotConfiguredError(f"base_url 必须包含有效的 host: '{base_url}'")
    if "@" in parsed.netloc:
        raise ReviewerNotConfiguredError(f"base_url 不得包含 userinfo 凭据 (@): '{base_url}'")

    is_local = (parsed.hostname or "").lower() in ("127.0.0.1", "localhost", "::1", "0.0.0.0")
    if not is_local and not api_key_env:
        raise ReviewerNotConfiguredError(
            f"远端 Reviewer 端点 ('{base_url}') 必须配置 api_key_env 环境变量名以进行鉴权"
        )

    return ReviewerClient(
        base_url=base_url,
        model=config.model,
        api_key_env=api_key_env,
        provider_label=prov,
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
        thinking=config.thinking,
        reasoning_effort=config.reasoning_effort,
        sink=sink,
    )


DEFAULT_HEARTBEAT_SILENCE_THRESHOLD_SECONDS: int = 900
DEFAULT_AFFECTED_FILES_MTIME_THRESHOLD_SECONDS: int = 600


@dataclass
class ReaperPolicyConfig:
    heartbeat_silence_threshold_seconds: int = DEFAULT_HEARTBEAT_SILENCE_THRESHOLD_SECONDS
    affected_files_mtime_threshold_seconds: int = DEFAULT_AFFECTED_FILES_MTIME_THRESHOLD_SECONDS

    def __post_init__(self) -> None:
        self.heartbeat_silence_threshold_seconds = _coerce_positive_int(
            self.heartbeat_silence_threshold_seconds,
            default=DEFAULT_HEARTBEAT_SILENCE_THRESHOLD_SECONDS,
            lo=10,
            hi=86400,
        )
        self.affected_files_mtime_threshold_seconds = _coerce_positive_int(
            self.affected_files_mtime_threshold_seconds,
            default=DEFAULT_AFFECTED_FILES_MTIME_THRESHOLD_SECONDS,
            lo=10,
            hi=86400,
        )


@dataclass
class QuenchStackConfig:
    workspace_root: str
    project_name: str
    schema_version: str = "1.0"
    dev_tasks_dir: str = "docs/dev_tasks"
    archive_dir: str = "docs/dev_tasks/archive"
    test_runner: str | None = None
    test_dir: str | None = "tests"
    changelog_path: str = "CHANGELOG.md"
    architecture_doc: str | None = None
    constraints: list[str] = field(default_factory=list)
    fast_track_rules: dict[str, Any] = field(default_factory=dict)
    governance_scope: dict[str, Any] = field(default_factory=dict)
    reviewer_engine: ReviewerEngineConfig = field(default_factory=ReviewerEngineConfig)
    reaper_policy: ReaperPolicyConfig = field(default_factory=ReaperPolicyConfig)

    def resolve_path(self, field_name: str) -> str:
        """将相对路径属性解析为基于 workspace_root 的绝对路径"""
        val = getattr(self, field_name, None)
        if not val:
            return ""
        if os.path.isabs(val):
            return os.path.normpath(val)
        return os.path.normpath(os.path.join(self.workspace_root, val))

    def get_fast_track_patterns(self) -> list[str]:
        """获取配置文件中声明的快速通道免管控白名单匹配模式列表（默认为空）"""
        if not isinstance(self.fast_track_rules, dict):
            return []
        patterns = self.fast_track_rules.get("allow_untracked_patterns", [])
        if isinstance(patterns, list):
            return [str(p).strip() for p in patterns if str(p).strip()]
        return []

    def is_path_governed(self, target_file: str | Path, workspace_root: Optional[str | Path] = None) -> bool:
        """判断目标文件是否属于任务状态机强管控的生产代码/构建资产。

        采用【项目法定边界清单 (governance_scope) + 内核智能推断】双轨机制。
        0. symlink 解析 + 路径越界防御
        1. 显式清单优先 (Explicit Governance Scope)
        2. 核心构建清单与 Glob 特征匹配
        3. 扩展名与常用非代码目录推断兜底
        返回 True 表示受管生产代码（触发任务状态机）；返回 False 表示非代码/文档资产（自由放行）。
        """
        ws_root = str(workspace_root or self.workspace_root)
        try:
            real_root = os.path.realpath(os.path.abspath(ws_root))
            target_str = str(target_file)
            if not os.path.isabs(target_str):
                abs_target = os.path.join(real_root, target_str)
            else:
                abs_target = target_str
            real_target = os.path.realpath(abs_target)

            # 路径越界穿越防御
            try:
                common = os.path.commonpath([real_target, real_root])
            except ValueError:
                # 跨驱动器（Windows 下跨盘符逃逸），判定为受管（拦截）
                return True

            if os.path.normcase(common) != os.path.normcase(real_root):
                # 路径逃逸出工作区根目录，判定为受管（拦截）
                return True
        except Exception:
            # 路径解析失败兜底为受管
            return True

        norm_target = real_target.replace("\\", "/").lower()
        norm_root = real_root.replace("\\", "/").lower()
        if norm_target.startswith(norm_root):
            rel_path = norm_target[len(norm_root):].lstrip("/")
        else:
            rel_path = norm_target

        basename = os.path.basename(norm_target)
        _, ext = os.path.splitext(norm_target)

        # 1. 项目显式清单优先 (Explicit Governance Scope)
        if isinstance(self.governance_scope, dict):
            unmanaged = self.governance_scope.get("unmanaged_paths", [])
            if isinstance(unmanaged, list):
                for pat in unmanaged:
                    if _match_glob(rel_path, str(pat)):
                        return False

            managed = self.governance_scope.get("managed_paths", [])
            if isinstance(managed, list) and managed:
                for pat in managed:
                    if _match_glob(rel_path, str(pat)):
                        return True
                # 若显式配置了 managed_paths 且未命中，则判定为非受管资产
                return False

        # 2. 内核智能语义推断兜底 (Smart Heuristics Fallback)
        # 核心构建与依赖清单（支持 Glob 变体匹配，优先级高于普通后缀推断）
        for pat in CRITICAL_CODE_MANIFEST_PATTERNS:
            if fnmatch.fnmatch(basename, pat.lower()):
                return True

        # 智能识别文档/设计素材扩展名
        if ext in DEFAULT_UNMANAGED_EXTENSIONS:
            return False

        # 智能识别常用文档/规划/素材目录
        for u_dir in DEFAULT_UNMANAGED_DIRS:
            if rel_path.startswith(u_dir) or f"/{u_dir}" in f"/{rel_path}":
                return False

        # 默认为生产代码/核心配置
        return True


def migrate_config_if_needed(yaml_path: str, data: dict) -> Tuple[dict, bool]:
    """纯文本级追加缺失字段，零注释破坏。

    读取文件原文本，用正则检测缺失的顶层字段，在文件末尾追加补丁文本块。
    使用 tempfile + os.replace 原子写回。
    返回: (migrated_data, has_changes)
    """
    if not os.path.isfile(yaml_path):
        return data, False

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
    except Exception:
        return data, False

    # 剥离 UTF-8 BOM
    clean_text = raw_text.lstrip("\ufeff")
    if not clean_text.strip():
        raise ValueError(f"配置文件为空或仅包含空白字符: {yaml_path}")

    current_ver = str(data.get("schema_version", "")).strip()
    if current_ver:
        try:
            # 若配置版本高于当前支持版本，不降级，仅发出警告
            if float(current_ver) > float(CURRENT_SCHEMA_VERSION):
                warnings.warn(
                    f"配置文件版本 '{current_ver}' 高于当前系统支持版本 '{CURRENT_SCHEMA_VERSION}'，跳过自动降级迁移。",
                    stacklevel=2,
                )
                return data, False
        except (ValueError, TypeError):
            pass

    has_changes = False
    patch_blocks: list[str] = []

    # 1. 检查 schema_version
    if not re.search(r"^\s*schema_version\s*:", clean_text, flags=re.MULTILINE):
        patch_blocks.append(_DEFAULT_SCHEMA_VERSION_PATCH.strip("\n"))
        data["schema_version"] = CURRENT_SCHEMA_VERSION
        has_changes = True

    # 2. 检查 fast_track_rules
    if not re.search(r"^\s*fast_track_rules\s*:", clean_text, flags=re.MULTILINE):
        patch_blocks.append(_DEFAULT_FAST_TRACK_PATCH.strip("\n"))
        data["fast_track_rules"] = {"allow_untracked_patterns": []}
        has_changes = True

    if not has_changes:
        return data, False

    updated_text = clean_text
    if not updated_text.endswith("\n"):
        updated_text += "\n"
    for pb in patch_blocks:
        updated_text += "\n" + pb + "\n"

    # 原子写回（使用 tempfile + os.replace）
    yaml_dir = os.path.dirname(os.path.abspath(yaml_path))
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=yaml_dir, delete=False, encoding="utf-8") as tf:
            temp_file = tf.name
            tf.write(updated_text)
        os.replace(temp_file, yaml_path)
    except OSError as e:
        warnings.warn(f"自动升级配置文件写回失败（可能是只读文件系统）: {e}，将在内存中维持升级状态。", stacklevel=2)
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
        return data, False

    # 重新从更新文本解析 data 保持完全一致
    try:
        reloaded = yaml.safe_load(updated_text)
        if isinstance(reloaded, dict):
            data = reloaded
    except Exception:
        pass

    return data, True


def load_project_config(workspace_root: str) -> QuenchStackConfig:
    """从 workspace_root/.agents/quench_stack.yaml 加载配置。

    若文件不存在，抛出明确的 FileNotFoundError 并提示运行初始化脚本。
    """
    root = os.path.abspath(workspace_root)
    yaml_path = os.path.join(root, ".agents", "quench_stack.yaml")

    if not os.path.isfile(yaml_path):
        init_script = os.path.normpath(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "init_project.py")
        )
        raise FileNotFoundError(
            f"项目配置文件不存在: {yaml_path}\n"
            f"请先在项目根目录运行初始化: python \"{init_script}\" \"{root}\""
        )

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    except Exception as e:
        raise ValueError(f"读取 {yaml_path} 失败: {e}") from e

    # 剥离 UTF-8 BOM
    raw_content = raw_content.lstrip("\ufeff")
    if not raw_content.strip():
        raise ValueError(f"配置文件为空或仅包含空白字符: {yaml_path}")

    try:
        data = yaml.safe_load(raw_content) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"解析 {yaml_path} 失败（YAML 语法错误）: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"配置文件格式无效（应为 YAML 字典键值对）: {yaml_path}")

    # 执行向后兼容自动升级迁移
    data, _ = migrate_config_if_needed(yaml_path, data)

    # 必填项校验
    project_name = data.get("project_name")
    if not project_name:
        raise ValueError(f"配置文件缺少必填项 'project_name': {yaml_path}")

    # 路径检查：如果是绝对路径发出可移植性警告
    for p_field in ["dev_tasks_dir", "archive_dir", "changelog_path", "architecture_doc", "test_dir"]:
        val = data.get(p_field)
        if val and os.path.isabs(val):
            warnings.warn(
                f"字段 '{p_field}' 配置了绝对路径 '{val}'，建议使用相对路径以提高跨平台与多机可移植性。",
                stacklevel=2,
            )

    fast_track_data = data.get("fast_track_rules")
    if not isinstance(fast_track_data, dict):
        fast_track_data = {}

    re_data = data.get("reviewer_engine")
    if isinstance(re_data, dict):
        provider_val = str(re_data.get("provider", "none")).lower().strip()
        raw_mode = str(re_data.get("mode", "auto")).lower().strip()
        if raw_mode not in ("auto", "subagent", "engine", "manual"):
            raw_mode = "auto"

        # 平滑迁移旧版配置：若未显式指定 mode，根据 provider 判断
        if "mode" not in re_data:
            if provider_val == "none":
                effective_mode = "manual"
            else:
                effective_mode = "auto"
        else:
            effective_mode = raw_mode

        order_val = re_data.get("strategy_order")
        if isinstance(order_val, list) and order_val:
            parsed_order = [str(s).lower().strip() for s in order_val if str(s).lower().strip() in ("subagent", "engine", "manual")]
            strategy_order = parsed_order if parsed_order else ["subagent", "engine", "manual"]
        else:
            strategy_order = ["subagent", "engine", "manual"]

        # 确保 provider="none" 时 strategy_order 兜底包含 manual
        if provider_val == "none" and "manual" not in strategy_order:
            strategy_order.append("manual")

        base_url_val = str(re_data.get("base_url", "")).strip() if re_data.get("base_url") is not None else ""
        api_key_env_val = str(re_data.get("api_key_env")).strip() if re_data.get("api_key_env") is not None else None
        model_val = str(re_data.get("model", "default")).strip()

        # 迁移兼容（只读补全内存配置，绝不改写用户 YAML 落盘）
        if provider_val in ("deepseek", "deepseek-compatible"):  # vendor-literal: allow
            if not base_url_val:
                preset = resolve_preset(provider_val)
                if preset:
                    base_url_val = preset.base_url
                    if api_key_env_val is None:
                        api_key_env_val = preset.api_key_env
                    if provider_val not in _SEEN_DEPRECATED_PROVIDERS:
                        _SEEN_DEPRECATED_PROVIDERS.add(provider_val)
                        warnings.warn(  # vendor-literal: allow
                            f"检测到旧版配置 provider='{provider_val}' 且未显式声明 base_url，已按预设自动补全，建议在 quench_stack.yaml 中显式声明。",  # vendor-literal: allow
                            DeprecationWarning,  # vendor-literal: allow
                            stacklevel=2,  # vendor-literal: allow
                        )  # vendor-literal: allow

        reviewer_engine = ReviewerEngineConfig(
            mode=effective_mode,
            strategy_order=strategy_order,
            provider=provider_val,
            model=model_val,
            api_key_env=api_key_env_val,
            base_url=base_url_val,
            thinking=bool(re_data.get("thinking", True)),
            reasoning_effort=str(re_data.get("reasoning_effort", "high")).strip(),
            timeout_seconds=_coerce_positive_int(re_data.get("timeout_seconds"), default=60, lo=5, hi=600),
            max_retries=_coerce_positive_int(re_data.get("max_retries"), default=2, lo=0, hi=10),
            max_tool_hops=_coerce_positive_int(re_data.get("max_tool_hops"), default=3, lo=0, hi=10),
            max_total_injection_chars=_coerce_positive_int(re_data.get("max_total_injection_chars"), default=DEFAULT_MAX_TOTAL_INJECTION_CHARS, lo=MIN_TOTAL_INJECTION_CHARS, hi=MAX_TOTAL_INJECTION_CHARS_UPPER),
            default_window_lines=_coerce_positive_int(re_data.get("default_window_lines"), default=DEFAULT_WINDOW_LINES, lo=30, hi=2000),
            max_lines_per_slice=_coerce_positive_int(re_data.get("max_lines_per_slice"), default=MAX_LINES_PER_SLICE, lo=30, hi=5000),
        )
    else:
        reviewer_engine = ReviewerEngineConfig(mode="manual", provider="none")

    governance_scope_data = data.get("governance_scope")
    if not isinstance(governance_scope_data, dict):
        governance_scope_data = {}

    rp_data = data.get("reaper_policy")
    if not isinstance(rp_data, dict):
        gov_data = data.get("governance")
        if isinstance(gov_data, dict) and isinstance(gov_data.get("reaper_policy"), dict):
            rp_data = gov_data.get("reaper_policy")
        else:
            rp_data = {}

    reaper_policy = ReaperPolicyConfig(
        heartbeat_silence_threshold_seconds=_coerce_positive_int(
            rp_data.get("heartbeat_silence_threshold_seconds"),
            default=DEFAULT_HEARTBEAT_SILENCE_THRESHOLD_SECONDS,
            lo=10,
            hi=86400,
        ),
        affected_files_mtime_threshold_seconds=_coerce_positive_int(
            rp_data.get("affected_files_mtime_threshold_seconds"),
            default=DEFAULT_AFFECTED_FILES_MTIME_THRESHOLD_SECONDS,
            lo=10,
            hi=86400,
        ),
    )

    return QuenchStackConfig(
        workspace_root=root,
        project_name=project_name,
        schema_version=data.get("schema_version", CURRENT_SCHEMA_VERSION),
        dev_tasks_dir=data.get("dev_tasks_dir", "docs/dev_tasks"),
        archive_dir=data.get("archive_dir", "docs/dev_tasks/archive"),
        test_runner=data.get("test_runner"),
        test_dir=data.get("test_dir", "tests"),
        changelog_path=data.get("changelog_path", "CHANGELOG.md"),
        architecture_doc=data.get("architecture_doc"),
        constraints=data.get("constraints", []) or [],
        fast_track_rules=fast_track_data,
        governance_scope=governance_scope_data,
        reviewer_engine=reviewer_engine,
        reaper_policy=reaper_policy,
    )


def resolve_path(config: QuenchStackConfig, field_name: str) -> str:
    """辅助函数：解析绝对路径"""
    return config.resolve_path(field_name)

