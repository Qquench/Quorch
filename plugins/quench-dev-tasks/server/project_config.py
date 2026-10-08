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
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple, Literal, TypedDict, Final
import math
import unicodedata
import urllib.parse
import yaml
from pydantic import BaseModel, model_validator

CURRENT_SCHEMA_VERSION = "1.0"
CURRENT_CONFIG_VERSION: Final[int] = 1


class ConfigFault(str, Enum):
    UNKNOWN_KEY          = "unknown_key"                 # 可降级（进返回列表）
    NFD_MISMATCH         = "nfd_mismatch"                # 可降级（carve-out 反馈）
    INVALID_SAFETY_VALUE = "invalid_safety_value"        # fail-closed（raise ConfigError）
    VERSION_UNSUPPORTED  = "config_version_unsupported"  # fail-closed（raise ConfigError）
    SAFETY_DOWNGRADE_DENIED = "safety_downgrade_denied"   # fail-closed（raise ConfigError）


class ConfigError(ValueError):
    """配置校验失败异常（如误填入明文密钥或非法凭据配置）。"""
    pass


def _calculate_shannon_entropy(s: str) -> float:
    """计算字符串香农熵，用于高熵随机密钥探测。"""
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for c in s:
        counts[c] = counts.get(c, 0) + 1
    length = len(s)
    return -sum((cnt / length) * math.log2(cnt / length) for cnt in counts.values())


def _looks_like_plaintext_secret(val: str) -> bool:
    """检测是否为明文 API 密钥（如 sk- 开头或高熵密钥）而非合法环境变量名。"""
    if not isinstance(val, str):
        return False
    s = val.strip()
    if not s:
        return False

    s_lower = s.lower()
    # 1. 显式常见 API 密钥特征前缀
    if s_lower.startswith(("sk-", "key-", "secret-", "ghp_", "gho_", "glpat-", "xoxb-", "xoxp-")):
        return True

    # 包含 Bearer 凭据或内嵌典型密钥格式 (如 sk- 开头且含 8 位以上内容)
    if "bearer " in s_lower:
        return True
    if re.search(r"sk-[a-zA-Z0-9_-]{8,}", s):
        return True

    # 2. 合法环境变量名规范 (大/小写字母、数字、下划线且首字符为字母或下划线)
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s):
        # 32 位及以上纯十六进制且无下划线，大概率为原始 API 密钥/哈希
        if len(s) >= 32 and "_" not in s and re.match(r"^[0-9a-fA-F]+$", s):
            return True
        # 合法环境变量名
        return False

    # 3. 包含连字符、符号等非环境变量合法字符的字符串检测
    parsed = urllib.parse.urlparse(s)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        # 如果是 URL，递归检查 query 参数是否携带密钥
        query = parsed.query
        if query:
            for param in query.split("&"):
                if "=" in param:
                    _, param_val = param.split("=", 1)
                    if _looks_like_plaintext_secret(param_val):
                        return True
        return False

    # 4. 非 URL 的特殊长字符高熵检测
    if len(s) >= 16 and _calculate_shannon_entropy(s) >= 3.5:
        return True

    return False


def _reject_inline_credentials(url: str) -> None:
    """校验 URL 中是否含有 user:pass@ 明文鉴权串，若存在抛出 ConfigError。"""
    if not url or not isinstance(url, str):
        return
    try:
        parsed = urllib.parse.urlparse(url)
        if "@" in parsed.netloc or parsed.username is not None or parsed.password is not None:
            raise ConfigError(
                f"URL must not contain plaintext credentials (user:pass@): '{url}' / "
                f"URL 不得包含明文鉴权凭据 (user:pass@): '{url}'"
            )
    except ConfigError:
        raise
    except Exception:
        if "@" in url and "://" in url:
            raise ConfigError(
                f"URL must not contain plaintext credentials: '{url}' / "
                f"URL 不得包含明文鉴权凭据: '{url}'"
            )


def _validate_credentials_security(target_dict: dict[str, Any]) -> None:
    """静态防御校验，仅限定扫描凭据承载字段（api_key_env、base_url、headers、api_key，
    排除 model、provider 等非凭据字段以防误伤）；当发现明文密钥模式时抛出 ConfigError 阻断异常。
    """
    if not isinstance(target_dict, dict):
        return

    # 1. 扫描 api_key 字段（严禁明文凭据入库）
    if "api_key" in target_dict:
        val = target_dict.get("api_key")
        if val is not None and str(val).strip():
            raise ConfigError(
                "Plaintext 'api_key' is strictly prohibited in configuration; use 'api_key_env' to reference an environment variable instead / "
                "配置文件中严禁出现 'api_key' 明文凭据字段，请使用 'api_key_env' 引用环境变量。"
            )

    # 2. 扫描 api_key_env 字段
    if "api_key_env" in target_dict:
        val = target_dict.get("api_key_env")
        if isinstance(val, str) and val.strip():
            if _looks_like_plaintext_secret(val):
                raise ConfigError(
                    f"api_key_env must not contain a plaintext API key; provide an environment variable name instead (e.g. 'API_KEY_ENV'): '{val}' / "
                    f"api_key_env 字段不得填入明文 API 密钥，必须填写环境变量名 (如 'API_KEY_ENV'): '{val}'"
                )

    # 3. 扫描 base_url 字段
    if "base_url" in target_dict:
        val = target_dict.get("base_url")
        if isinstance(val, str) and val.strip():
            _reject_inline_credentials(val)
            if _looks_like_plaintext_secret(val):
                raise ConfigError(
                    f"base_url must not contain a plaintext API key or credential: '{val}' / "
                    f"base_url 字段不得包含明文 API 密钥或凭据: '{val}'"
                )

    # 4. 扫描 headers 字段
    if "headers" in target_dict:
        headers = target_dict.get("headers")
        if isinstance(headers, dict):
            for h_key, h_val in headers.items():
                if _looks_like_plaintext_secret(str(h_val)) or _looks_like_plaintext_secret(str(h_key)):
                    raise ConfigError(
                        f"headers must not contain a plaintext API key or credential: '{h_key}: {h_val}' / "
                        f"headers 中不得包含明文 API 密钥或凭据: '{h_key}: {h_val}'"
                    )
        elif isinstance(headers, str) and _looks_like_plaintext_secret(headers):
            raise ConfigError(
                f"headers must not contain plaintext credentials: '{headers}' / "
                f"headers 字段不得包含明文凭据: '{headers}'"
            )


def _deep_merge_dict(base: dict, overlay: dict) -> dict:
    """递归合并两个字典，overlay 覆盖 base。"""
    result = base.copy()
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_dict(result[k], v)
        else:
            result[k] = v
    return result


_DEFAULT_SCHEMA_VERSION_PATCH = 'schema_version: "1.0"\n'
_DEFAULT_CONFIG_VERSION_PATCH = "config_version: 1\n"
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


@dataclass
class RunnerProfile:
    provider: str = "unknown"
    model: str = "unknown"


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str
    api_key_env: str | None
    requires_thinking_flag: bool = False


# -- vendor-presets:start
PROVIDER_PRESETS: Mapping[str, ProviderPreset | None] = MappingProxyType({})
PROVIDER_ALIASES: Mapping[str, str] = MappingProxyType({})


def normalize_model_identity(provider: str, model: str) -> tuple[str, str]:
    """归一化 (provider, model) 用于同模型比对。"""
    p = (provider or "").strip().lower()
    m = (model or "").strip().lower()
    return p, m


def check_self_verification_warning(
    runner: RunnerProfile | None,
    reviewer_provider: str,
    reviewer_model: str,
) -> Optional[str]:
    """检测 Runner 与 Reviewer 是否配置为相同模型。
    若任一方为 unknown 或 reviewer.provider 为 none，则不告警。
    若归一化后 provider 与 model 均相同，则返回预警信息。
    """
    if not runner:
        return None
    r_prov = (runner.provider or "").strip().lower()
    r_model = (runner.model or "").strip().lower()
    if r_prov in ("unknown", "", "none") or r_model in ("unknown", ""):
        return None

    rev_prov = (reviewer_provider or "").strip().lower()
    if rev_prov in ("none", "", "unknown"):
        return None

    norm_r_prov, norm_r_model = normalize_model_identity(r_prov, r_model)
    norm_rev_prov, norm_rev_model = normalize_model_identity(rev_prov, reviewer_model)

    if norm_r_prov == norm_rev_prov and norm_r_model == norm_rev_model:
        return (
            f"Advisory: Runner profile and Reviewer profile resolve to the same model identity "
            f"('{norm_r_prov}/{norm_r_model}'). Beware of homogeneous bias (S1 self-verification trap)."
        )
    return None
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
                f"Unknown Reviewer provider='{config.provider}' with empty base_url. "
                f"Please configure a valid base_url in quench_stack.yaml / "
                f"未知 Reviewer provider='{config.provider}' 且未显式指定 base_url。请在 quench_stack.yaml 中配置有效的 base_url。"
            )

    if not base_url:
        raise ReviewerNotConfiguredError(
            f"Reviewer engine base_url is empty (provider='{prov}') / Reviewer 引擎 base_url 为空 (provider='{prov}')"
        )

    # URL 校验
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise ReviewerNotConfiguredError(
            f"base_url must use http or https protocol: '{base_url}' / base_url 必须为 http 或 https 协议: '{base_url}'"
        )
    if not parsed.hostname:
        raise ReviewerNotConfiguredError(
            f"base_url must contain a valid host: '{base_url}' / base_url 必须包含有效的 host: '{base_url}'"
        )
    if "@" in parsed.netloc:
        raise ReviewerNotConfiguredError(
            f"base_url must not contain userinfo credentials (@): '{base_url}' / base_url 不得包含 userinfo 凭据 (@): '{base_url}'"
        )

    is_local = (parsed.hostname or "").lower() in ("127.0.0.1", "localhost", "::1", "0.0.0.0")
    if not is_local and not api_key_env:
        raise ReviewerNotConfiguredError(
            f"Remote Reviewer endpoint ('{base_url}') requires api_key_env for authentication / "
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


def canonical_artifact_ref(workspace_root: str, task_file: str, task_id: str) -> str:
    """SSOT 复合键：f"{posix_relpath(workspace_root, task_file)}#{task_id}"。
    task_id 必须复用 TaskItem.id，禁止在此二次派生或归一化。"""
    ws = os.path.abspath(workspace_root)
    if not os.path.isabs(task_file):
        abs_task_file = os.path.abspath(os.path.join(ws, task_file))
    else:
        abs_task_file = os.path.abspath(task_file)
    rel = os.path.relpath(abs_task_file, ws)
    rel_posix = rel.replace(os.sep, "/").replace("\\", "/")
    while rel_posix.startswith("./"):
        rel_posix = rel_posix[2:]
    return f"{rel_posix}#{str(task_id).strip()}"


AuditGateReason = Literal[
    "disabled", "not_managed_scope", "session_bypass_active", "matched",
    "no_matching_record", "record_stale", "record_timestamp_invalid", "record_degraded",
    "tail_window_exhausted", "log_missing", "log_unparsable", "precondition_changed", "internal_error",
]


class AuditGatePolicy(BaseModel):
    enabled: bool = False
    scope: Literal["managed_paths"] = "managed_paths"
    audit_log_path: Optional[str] = None
    bind_artifact: bool = True
    max_age_minutes: int = 1440
    max_tail_bytes: int = 1048576
    on_missing_record: Literal["block", "warn", "allow"] = "block"
    on_degraded: Literal["block", "warn", "allow"] = "block"
    on_internal_error: Literal["allow", "warn"] = "allow"
    require_undegraded_record: bool = True
    clock_skew_tolerance_seconds: int = 2
    tail_window_exhausted_policy: Optional[Literal["block", "warn", "allow"]] = None  # DEPRECATED alias

    @model_validator(mode="after")
    def validate_audit_gate_policy(self) -> "AuditGatePolicy":
        if self.enabled and not self.bind_artifact:
            raise ValueError("bind_artifact must be True when audit gate is enabled")
        if "tail_window_exhausted_policy" in self.model_fields_set:
            warnings.warn(
                "'tail_window_exhausted_policy' is deprecated and aliased to 'on_degraded' (most-restrictive-wins). "
                "Please migrate to 'on_degraded' in .agents/quench_stack.yaml / "
                "'tail_window_exhausted_policy' 已弃用并别名化至 'on_degraded'（最严优先），请在配置中直接使用 'on_degraded'。",
                DeprecationWarning,
                stacklevel=2,
            )
        return self


def most_restrictive_policy(
    primary: Literal["block", "warn", "allow"],
    secondary: Optional[Literal["block", "warn", "allow"]] = None,
) -> Literal["block", "warn", "allow"]:
    """最严优先纯函数 (most-restrictive-wins):
    优先级: block > warn > allow; secondary is None 时返回 primary。
    """
    if secondary is None:
        return primary
    if primary == "block" or secondary == "block":
        return "block"
    if primary == "warn" or secondary == "warn":
        return "warn"
    return "allow"


def _derive_safety_key_domains() -> Mapping[str, frozenset[str]]:
    import typing

    def _extract_literals(tp: Any) -> list[str]:
        origin = typing.get_origin(tp)
        if origin is Literal:
            return [str(arg) for arg in typing.get_args(tp)]
        res: list[str] = []
        for arg in typing.get_args(tp):
            if arg is not type(None) and arg is not None:
                res.extend(_extract_literals(arg))
        return res

    domains: dict[str, frozenset[str]] = {}
    for key in (
        "on_missing_record",
        "on_degraded",
        "tail_window_exhausted_policy",
        "on_internal_error",
    ):
        field_info = AuditGatePolicy.model_fields.get(key)
        if field_info is not None:
            domains[f"audit_gate.{key}"] = frozenset(_extract_literals(field_info.annotation))
    return MappingProxyType(domains)


# 单一 SSOT：域由 audit_gate 策略字面量派生，并覆盖现网实值 block/warn/allow
SAFETY_KEY_DOMAINS: Final[Mapping[str, frozenset[str]]] = _derive_safety_key_domains()


class AuditGateResult(TypedDict):
    allowed: bool
    reason: AuditGateReason
    artifact_ref: Optional[str]
    audit_ref: Optional[str]
    parse_skipped_lines: int


@dataclass
class ObservabilityConfig:
    verdict_path: str = ".agents/logs/reviewer/verdicts.jsonl"
    max_record_bytes: int = 16384
    stream_in_subagent: bool = False


@dataclass
class QuenchStackConfig:
    workspace_root: str
    project_name: str
    schema_version: str = "1.0"
    config_version: int = CURRENT_CONFIG_VERSION
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
    runner_profile: RunnerProfile = field(default_factory=RunnerProfile)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    audit_gate: AuditGatePolicy = field(default_factory=AuditGatePolicy)
    local_override_loaded: bool = False
    local_override_path: str | None = None

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


KNOWN_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset({
    "config_version",
    "project_name",
    "schema_version",
    "dev_tasks_dir",
    "archive_dir",
    "test_runner",
    "test_dir",
    "changelog_path",
    "architecture_doc",
    "constraints",
    "fast_track_rules",
    "governance_scope",
    "reviewer_engine",
    "reaper_policy",
    "governance",
    "runner_profile",
    "observability",
    "audit_gate",
    "workspace_root",
    "api_key",
})

PROTECTED_CONFIG_NAMES: Final[frozenset[str]] = frozenset({"quench_stack.yaml", "quench_stack.local.yaml"})


def is_protected_config_path(path: str, faults: list[ConfigFault] | None = None) -> bool:
    """carve-out：受保护配置「词法 ∪ realpath」双错时返回 True（fail-closed）；非 NFC 输入经 ConfigFault.NFD_MISMATCH 上报。"""
    try:
        path_str = str(path)
        if not unicodedata.is_normalized("NFC", path_str):
            if faults is not None:
                faults.append(ConfigFault.NFD_MISMATCH)
            return True

        # Canonicalize Windows ADS (Alternate Data Streams) and trailing dots/spaces
        prefix, rest = ("", path_str)
        if len(rest) >= 2 and rest[1] == ":" and rest[0].isalpha():
            prefix, rest = rest[:2], rest[2:]
        if ":" in rest:
            rest = rest.split(":", 1)[0]
        cleaned = prefix + rest.rstrip(". ")
        lexical_match = os.path.basename(cleaned).lower() in PROTECTED_CONFIG_NAMES
        real_match = os.path.basename(os.path.realpath(cleaned)).lower() in PROTECTED_CONFIG_NAMES
        return lexical_match or real_match
    except Exception:
        return True  # 词法 ∪ realpath 双错 fail-closed


def _build_quench_stack_config(
    data: Mapping[str, Any],
    workspace_root: str = ".",
    config_version: int = CURRENT_CONFIG_VERSION,
) -> QuenchStackConfig:
    root = os.path.abspath(workspace_root)
    project_name = str(data.get("project_name") or "default").strip()

    fast_track_data = data.get("fast_track_rules")
    if not isinstance(fast_track_data, dict):
        fast_track_data = {}

    re_data = data.get("reviewer_engine")
    if isinstance(re_data, dict):
        provider_val = str(re_data.get("provider", "none")).lower().strip()
        raw_mode = str(re_data.get("mode", "auto")).lower().strip()
        if raw_mode not in ("auto", "subagent", "engine", "manual"):
            raw_mode = "auto"

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

        if provider_val == "none" and "manual" not in strategy_order:
            strategy_order.append("manual")

        base_url_val = str(re_data.get("base_url", "")).strip() if re_data.get("base_url") is not None else ""
        api_key_env_val = str(re_data.get("api_key_env")).strip() if re_data.get("api_key_env") is not None else None
        model_val = str(re_data.get("model", "default")).strip()

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

    rp_raw = data.get("runner_profile")
    if isinstance(rp_raw, dict):
        rp_provider = str(rp_raw.get("provider", "unknown")).strip() or "unknown"
        rp_model = str(rp_raw.get("model", "unknown")).strip() or "unknown"
        runner_profile = RunnerProfile(provider=rp_provider, model=rp_model)
    else:
        runner_profile = RunnerProfile()

    obs_raw = data.get("observability")
    if isinstance(obs_raw, dict):
        observability = ObservabilityConfig(
            verdict_path=str(obs_raw.get("verdict_path", ".agents/logs/reviewer/verdicts.jsonl")).strip(),
            max_record_bytes=_coerce_positive_int(obs_raw.get("max_record_bytes"), default=16384, lo=1024, hi=1048576),
            stream_in_subagent=bool(obs_raw.get("stream_in_subagent", False)),
        )
    else:
        observability = ObservabilityConfig()

    ag_raw = data.get("audit_gate")
    if isinstance(ag_raw, dict):
        ag_dict = dict(ag_raw)
        if ag_dict.get("audit_log_path") is None:
            ag_dict["audit_log_path"] = observability.verdict_path
        audit_gate = AuditGatePolicy(**ag_dict)
    else:
        audit_gate = AuditGatePolicy()

    return QuenchStackConfig(
        workspace_root=root,
        project_name=project_name,
        schema_version=str(data.get("schema_version", CURRENT_SCHEMA_VERSION)),
        config_version=config_version,
        dev_tasks_dir=str(data.get("dev_tasks_dir", "docs/dev_tasks")),
        archive_dir=str(data.get("archive_dir", "docs/dev_tasks/archive")),
        test_runner=data.get("test_runner"),
        test_dir=data.get("test_dir", "tests"),
        changelog_path=str(data.get("changelog_path", "CHANGELOG.md")),
        architecture_doc=data.get("architecture_doc"),
        constraints=data.get("constraints", []) or [],
        fast_track_rules=fast_track_data,
        governance_scope=governance_scope_data,
        reviewer_engine=reviewer_engine,
        reaper_policy=reaper_policy,
        runner_profile=runner_profile,
        observability=observability,
        audit_gate=audit_gate,
    )


def migrate_and_validate(raw: Mapping[str, Any]) -> tuple[QuenchStackConfig, list[ConfigFault]]:
    """未知键 -> 收集为 UNKNOWN_KEY warn 并降级；
    安全键非法值 / 未来版本 -> raise ConfigError（fail-closed，物理不可忽略）。
    缺失 config_version 视作 v1 触发迁移（幂等无副作用）。"""
    if not isinstance(raw, Mapping):
        raise ConfigError(f"Expected a mapping for configuration, got {type(raw).__name__}")

    faults: list[ConfigFault] = []

    # 1. 检查非 NFC 字符 (拒绝静默归一)
    for k in raw.keys():
        if isinstance(k, str) and not unicodedata.is_normalized("NFC", k):
            faults.append(ConfigFault.NFD_MISMATCH)

    # 2. 版本门禁 (Version Gate)
    raw_ver = raw.get("config_version")
    if raw_ver is None:
        effective_ver = CURRENT_CONFIG_VERSION
    else:
        try:
            effective_ver = int(raw_ver)
        except (ValueError, TypeError):
            raise ConfigError(
                f"Invalid config_version format: '{raw_ver}'. Expected integer / "
                f"config_version 格式非法: '{raw_ver}'，必须为整数。"
            )
        if effective_ver > CURRENT_CONFIG_VERSION:
            raise ConfigError(
                f"Unsupported config_version {effective_ver} > {CURRENT_CONFIG_VERSION} "
                f"[{ConfigFault.VERSION_UNSUPPORTED.value}] / "
                f"配置版本 {effective_ver} 高于当前系统支持版本 {CURRENT_CONFIG_VERSION}"
            )

    # 3. 安全键非法值物理门禁 (Safety Key Domains Fail-Closed)
    for full_key, allowed_domain in SAFETY_KEY_DOMAINS.items():
        parts = full_key.split(".")
        curr: Any = raw
        found = True
        for p in parts:
            if isinstance(curr, Mapping) and p in curr:
                curr = curr[p]
            else:
                found = False
                break
        if found and curr is not None:
            val = str(curr).lower().strip()
            if val not in allowed_domain:
                raise ConfigError(
                    f"Invalid safety configuration value for '{full_key}': '{curr}'. "
                    f"Must be one of {sorted(allowed_domain)} [{ConfigFault.INVALID_SAFETY_VALUE.value}] / "
                    f"安全配置项 '{full_key}' 存在非法取值: '{curr}'，必须属于 {sorted(allowed_domain)}"
                )

    # 4. 未知顶层键收集与降级 (Unknown Keys Degradation)
    for k in raw.keys():
        if k not in KNOWN_TOP_LEVEL_KEYS:
            faults.append(ConfigFault.UNKNOWN_KEY)
            warnings.warn(
                f"Unknown configuration key '{k}' will be safely ignored / 未知配置键 '{k}' 将被安全忽略降级。",
                UserWarning,
                stacklevel=2,
            )

    ws_root = str(raw.get("workspace_root") or ".")
    cfg = _build_quench_stack_config(raw, workspace_root=ws_root, config_version=effective_ver)
    return cfg, faults


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

    cfg_ver = data.get("config_version")
    if cfg_ver is not None:
        try:
            if int(cfg_ver) > CURRENT_CONFIG_VERSION:
                raise ConfigError(
                    f"Configuration version '{cfg_ver}' is higher than current supported version '{CURRENT_CONFIG_VERSION}' / "
                    f"配置版本 '{cfg_ver}' 高于当前系统支持版本 '{CURRENT_CONFIG_VERSION}'"
                )
        except (ValueError, TypeError) as e:
            if isinstance(e, ConfigError):
                raise

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
            f"Project configuration file not found: {yaml_path}\n"
            f"Please run initialization in project root: python \"{init_script}\" \"{root}\" / "
            f"项目配置文件不存在: {yaml_path}\n"
            f"请先在项目根目录运行初始化: python \"{init_script}\" \"{root}\""
        )

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    except Exception as e:
        raise ValueError(f"Failed to read {yaml_path}: {e} / 读取 {yaml_path} 失败: {e}") from e

    # 剥离 UTF-8 BOM
    raw_content = raw_content.lstrip("\ufeff")
    if not raw_content.strip():
        raise ValueError(f"Configuration file is empty: {yaml_path} / 配置文件为空或仅包含空白字符: {yaml_path}")

    try:
        data = yaml.safe_load(raw_content) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse {yaml_path} (YAML syntax error): {e} / 解析 {yaml_path} 失败（YAML 语法错误）: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Invalid configuration format (expected a YAML dictionary): {yaml_path} / 配置文件格式无效（应为 YAML 字典键值对）: {yaml_path}")

    # 执行向后兼容自动升级迁移
    data, _ = migrate_config_if_needed(yaml_path, data)

    # 检查本地私有覆盖配置 .agents/quench_stack.local.yaml (已在 .gitignore 中忽略)
    def _merge_local_override(base: dict, overlay: dict) -> dict:
        """对安全与治理字段执行单调收紧硬门禁与基线锁定；其余字段走深合并。"""
        audit_order = {"block": 2, "warn": 1, "allow": 0}
        base_ag = base.get("audit_gate") if isinstance(base.get("audit_gate"), dict) else {}
        over_ag = overlay.get("audit_gate") if isinstance(overlay.get("audit_gate"), dict) else {}
        if base_ag.get("enabled") is True and over_ag.get("enabled") is False:
            raise ConfigError(
                f"Local override cannot disable audit_gate when enabled in baseline ({ConfigFault.SAFETY_DOWNGRADE_DENIED.value}) / "
                "本地覆盖不得在基线已启用的情况下关闭 audit_gate"
            )

        for policy in ("on_missing_record", "on_degraded", "on_internal_error"):
            if policy in over_ag:
                base_val = str(base_ag.get(policy, "block" if policy != "on_internal_error" else "allow")).strip().lower()
                over_val = str(over_ag.get(policy)).strip().lower()
                base_rank = audit_order.get(base_val, 0)
                over_rank = audit_order.get(over_val, 0)
                if over_rank < base_rank:
                    raise ConfigError(
                        f"Local override cannot loosen audit_gate.{policy} from '{base_val}' to '{over_val}' ({ConfigFault.SAFETY_DOWNGRADE_DENIED.value}) / "
                        f"本地覆盖不得将 audit_gate.{policy} 从 '{base_val}' 放宽至 '{over_val}'"
                    )

        base_scope = base.get("governance_scope") if isinstance(base.get("governance_scope"), dict) else {}
        over_scope = overlay.get("governance_scope") if isinstance(overlay.get("governance_scope"), dict) else {}
        if "managed_paths" in over_scope and "managed_paths" in base_scope:
            base_managed = set(base_scope["managed_paths"])
            over_managed = set(over_scope["managed_paths"])
            if not base_managed.issubset(over_managed):
                missing = base_managed - over_managed
                raise ConfigError(
                    f"Local override cannot narrow governance_scope.managed_paths (missing {missing}) ({ConfigFault.SAFETY_DOWNGRADE_DENIED.value}) / "
                    "本地覆盖不得收窄基线受管路径"
                )

        if "unmanaged_paths" in over_scope and "unmanaged_paths" in base_scope:
            base_unmanaged = set(base_scope["unmanaged_paths"])
            over_unmanaged = set(over_scope["unmanaged_paths"])
            if not over_unmanaged.issubset(base_unmanaged):
                added = over_unmanaged - base_unmanaged
                raise ConfigError(
                    f"Local override cannot widen governance_scope.unmanaged_paths (added {added}) ({ConfigFault.SAFETY_DOWNGRADE_DENIED.value}) / "
                    "本地覆盖不得放宽基线非受管路径"
                )

        base_gov = base.get("governance") if isinstance(base.get("governance"), dict) else {}
        over_gov = overlay.get("governance") if isinstance(overlay.get("governance"), dict) else {}
        if "manifest_path" in over_gov and base_gov.get("manifest_path") != over_gov.get("manifest_path"):
            raise ConfigError(
                f"Local override cannot redirect governance.manifest_path ({ConfigFault.SAFETY_DOWNGRADE_DENIED.value}) / "
                "本地覆盖不得重定向 manifest_path"
            )

        return _deep_merge_dict(base, overlay)

    local_yaml_path = os.path.join(root, ".agents", "quench_stack.local.yaml")
    local_override_loaded = False
    if os.path.isfile(local_yaml_path):
        try:
            with open(local_yaml_path, "r", encoding="utf-8") as f:
                raw_local = f.read().lstrip("\ufeff")
            if raw_local.strip():
                local_data = yaml.safe_load(raw_local)
                if isinstance(local_data, dict):
                    data = _merge_local_override(data, local_data)
                    local_override_loaded = True
        except (yaml.YAMLError, ConfigError):
            raise
        except Exception as e:
            raise ValueError(f"Failed to read local override config {local_yaml_path}: {e} / 读取本地覆盖配置 {local_yaml_path} 失败: {e}") from e

    # 静态安全防御校验：严禁明文密钥或凭据落盘
    if "api_key" in data and data.get("api_key"):
        raise ConfigError(
            "Plaintext 'api_key' is strictly prohibited in configuration; use 'api_key_env' to reference an environment variable instead / "
            "配置文件中严禁出现 'api_key' 明文凭据字段，请使用 'api_key_env' 引用环境变量。"
        )

    re_data_check = data.get("reviewer_engine")
    if isinstance(re_data_check, dict):
        _validate_credentials_security(re_data_check)

    # 必填项校验
    project_name = data.get("project_name")
    if not project_name:
        raise ValueError(f"Missing required field 'project_name' in {yaml_path} / 配置文件缺少必填项 'project_name': {yaml_path}")

    # 路径检查：如果是绝对路径发出可移植性警告
    for p_field in ["dev_tasks_dir", "archive_dir", "changelog_path", "architecture_doc", "test_dir"]:
        val = data.get(p_field)
        if val and os.path.isabs(val):
            warnings.warn(
                f"Field '{p_field}' uses an absolute path '{val}'; use a relative path for portability / "
                f"字段 '{p_field}' 配置了绝对路径 '{val}'，建议使用相对路径以提高跨平台与多机可移植性。",
                stacklevel=2,
            )

    data["workspace_root"] = root
    cfg, _ = migrate_and_validate(data)
    cfg.local_override_loaded = local_override_loaded
    cfg.local_override_path = local_yaml_path if local_override_loaded else None
    return cfg


def resolve_path(config: QuenchStackConfig, field_name: str) -> str:
    """辅助函数：解析绝对路径"""
    return config.resolve_path(field_name)


def resolve_reviewer_log_dir(workspace_root: str | os.PathLike[str]) -> str:
    """唯一解析 reviewer 日志目录的 SSOT 辅助函数。"""
    return os.path.abspath(os.path.join(str(workspace_root), ".agents", "logs", "reviewer"))


