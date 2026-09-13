from __future__ import annotations

import os
import sys
import warnings
from dataclasses import dataclass, field
import yaml


import fnmatch

DEFAULT_UNMANAGED_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".rst", ".adoc",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".drawio", ".puml", ".mermaid",
}

DEFAULT_UNMANAGED_DIRS = (
    "docs/", "doc/", "documentation/", "future_roadmap/",
    "roadmap/", "notes/", "manuals/", "sample_data/",
    "samples/", ".vscode/", ".idea/", ".github/",
)

CRITICAL_CODE_MANIFESTS = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "pom.xml", "build.gradle", "build.gradle.kts",
}


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


@dataclass
class QuenchStackConfig:
    workspace_root: str
    project_name: str
    dev_tasks_dir: str = "docs/dev_tasks"
    archive_dir: str = "docs/dev_tasks/archive"
    test_runner: str | None = None
    test_dir: str | None = "tests"
    changelog_path: str = "CHANGELOG.md"
    architecture_doc: str | None = None
    constraints: list[str] = field(default_factory=list)
    fast_track_rules: dict[str, Any] = field(default_factory=dict)
    governance_scope: dict[str, Any] = field(default_factory=dict)

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

    def is_path_governed(self, target_file: str) -> bool:
        """判断目标文件是否属于任务状态机强管控的生产代码/构建资产。

        采用【项目法定边界清单 (governance_scope) + 内核智能推断】双轨机制。
        返回 True 表示受管生产代码（触发任务状态机）；返回 False 表示非代码/文档资产（自由放行）。
        """
        norm_target = os.path.normpath(target_file).replace("\\", "/").lower()
        norm_root = os.path.normpath(self.workspace_root).replace("\\", "/").lower()
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
        # 核心构建与依赖清单（哪怕是 json/txt/yaml 也是高危生产清单）
        if basename in CRITICAL_CODE_MANIFESTS or basename.startswith("dockerfile"):
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


def load_project_config(workspace_root: str) -> QuenchStackConfig:
    """从 workspace_root/.agents/quench_stack.yaml 加载配置。

    若文件不存在，抛出明确的 FileNotFoundError 并提示运行初始化脚本。
    """
    root = os.path.abspath(workspace_root)
    yaml_path = os.path.join(root, ".agents", "quench_stack.yaml")

    if not os.path.isfile(yaml_path):
        raise FileNotFoundError(
            f"项目配置文件不存在: {yaml_path}\n"
            f"请先在项目根目录运行初始化: python D:\\Work\\Quench\\MCP\\plugins\\quench-dev-tasks\\scripts\\init_project.py \"{root}\""
        )

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"解析 {yaml_path} 失败（YAML 语法错误）: {e}") from e

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

    governance_scope_data = data.get("governance_scope")
    if not isinstance(governance_scope_data, dict):
        governance_scope_data = {}

    return QuenchStackConfig(
        workspace_root=root,
        project_name=project_name,
        dev_tasks_dir=data.get("dev_tasks_dir", "docs/dev_tasks"),
        archive_dir=data.get("archive_dir", "docs/dev_tasks/archive"),
        test_runner=data.get("test_runner"),
        test_dir=data.get("test_dir", "tests"),
        changelog_path=data.get("changelog_path", "CHANGELOG.md"),
        architecture_doc=data.get("architecture_doc"),
        constraints=data.get("constraints", []) or [],
        fast_track_rules=fast_track_data,
        governance_scope=governance_scope_data,
    )


def resolve_path(config: QuenchStackConfig, field_name: str) -> str:
    """辅助函数：解析绝对路径"""
    return config.resolve_path(field_name)
