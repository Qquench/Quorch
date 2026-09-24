# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

from project_config import (
    QuenchStackConfig,
    load_project_config,
    DEFAULT_UNMANAGED_EXTENSIONS,
    CRITICAL_CODE_MANIFEST_PATTERNS,
    ConfigError,
    _looks_like_plaintext_secret,
    _reject_inline_credentials,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_unmanaged_extensions_and_critical_manifests():
    """验证扩充后的未受管后缀与高危清单 Glob 规则"""
    assert ".sample" in DEFAULT_UNMANAGED_EXTENSIONS
    assert ".example" in DEFAULT_UNMANAGED_EXTENSIONS
    assert ".bak" in DEFAULT_UNMANAGED_EXTENSIONS
    assert ".log" in DEFAULT_UNMANAGED_EXTENSIONS
    assert ".csv" in DEFAULT_UNMANAGED_EXTENSIONS
    assert ".tsv" in DEFAULT_UNMANAGED_EXTENSIONS
    assert ".parquet" in DEFAULT_UNMANAGED_EXTENSIONS
    assert ".lock" in DEFAULT_UNMANAGED_EXTENSIONS

    # 验证 Glob 模式存在
    assert "dockerfile*" in CRITICAL_CODE_MANIFEST_PATTERNS
    assert "docker-compose*.yml" in CRITICAL_CODE_MANIFEST_PATTERNS
    assert "tsconfig*.json" in CRITICAL_CODE_MANIFEST_PATTERNS
    assert ".env" in CRITICAL_CODE_MANIFEST_PATTERNS


def test_is_path_governed_heuristics_manifest_variants(temp_workspace):
    """测试构建清单变体及 glob 模式识别"""
    cfg = QuenchStackConfig(workspace_root=str(temp_workspace), project_name="test_proj")

    # 构建清单变体受管
    assert cfg.is_path_governed("docker-compose.override.yml") is True
    assert cfg.is_path_governed("docker-compose.prod.yaml") is True
    assert cfg.is_path_governed("Dockerfile.dev") is True
    assert cfg.is_path_governed("tsconfig.build.json") is True
    assert cfg.is_path_governed("tsconfig.node.json") is True
    assert cfg.is_path_governed("package.json") is True
    assert cfg.is_path_governed("yarn.lock") is True
    assert cfg.is_path_governed("Cargo.lock") is True
    assert cfg.is_path_governed(".env") is True

    # 未受管后缀放行
    assert cfg.is_path_governed(".env.example") is False
    assert cfg.is_path_governed("config.sample") is False
    assert cfg.is_path_governed("output.log") is False
    assert cfg.is_path_governed("data/dataset.csv") is False
    assert cfg.is_path_governed("data/features.parquet") is False
    assert cfg.is_path_governed("backup.bak") is False
    # 非已知 manifest 的普通 lock 文件放行
    assert cfg.is_path_governed("process.lock") is False


def test_is_path_governed_multi_language_false_positive_rate(temp_workspace):
    """验证多语言典型工程结构判定准确率，确保文档资产假阳性率（误报为代码）<= 5%"""
    cfg = QuenchStackConfig(workspace_root=str(temp_workspace), project_name="multi_lang")

    test_cases = [
        # Python Web
        ("src/app/main.py", True),
        ("src/app/models.py", True),
        ("requirements.txt", True),
        ("pyproject.toml", True),
        ("docs/index.md", False),
        ("docs/architecture.drawio", False),
        ("docs/api.txt", False),
        (".github/workflows/ci.yml", False),
        # Vue / React
        ("src/components/Button.tsx", True),
        ("src/views/Home.vue", True),
        ("package.json", True),
        ("pnpm-lock.yaml", True),
        ("tsconfig.json", True),
        ("tsconfig.app.json", True),
        ("public/favicon.ico", False),
        ("README.md", False),
        ("notes/meeting.txt", False),
        # Go
        ("cmd/server/main.go", True),
        ("pkg/router/router.go", True),
        ("go.mod", True),
        ("go.sum", True),
        ("doc/guide.md", False),
        ("sample_data/users.json", False),  # 命中 sample_data/ 目录
        # Rust
        ("src/main.rs", True),
        ("src/lib.rs", True),
        ("Cargo.toml", True),
        ("Cargo.lock", True),
        ("manuals/setup.rst", False),
        ("samples/demo.rs", False),  # 命中 samples/ 目录
        # Java Maven
        ("src/main/java/com/example/App.java", True),
        ("src/main/resources/application.properties", True),
        ("pom.xml", True),
        ("roadmap/v2.md", False),
        ("future_roadmap/plan.adoc", False),
    ]

    total_doc_assets = 0
    misclassified_doc_assets = 0

    for path, expected_governed in test_cases:
        actual_governed = cfg.is_path_governed(path)
        assert actual_governed == expected_governed, f"判定不符: {path} 预期 {expected_governed}, 实际 {actual_governed}"
        if not expected_governed:
            total_doc_assets += 1
            if actual_governed:
                misclassified_doc_assets += 1

    false_positive_rate = misclassified_doc_assets / total_doc_assets if total_doc_assets > 0 else 0
    assert false_positive_rate <= 0.05, f"假阳性率超过 5%: {false_positive_rate:.2%}"


def test_is_path_governed_path_escape_defense(temp_workspace):
    """验证路径越界逃逸防御"""
    cfg = QuenchStackConfig(workspace_root=str(temp_workspace), project_name="escape_test")

    # 向上逃逸出工作区目录，必须判定为受管（被拦截）
    assert cfg.is_path_governed("../../etc/passwd") is True
    assert cfg.is_path_governed("../outside_project/evil.py") is True
    assert cfg.is_path_governed(temp_workspace.parent / "escape.py") is True


def test_is_path_governed_symlink_defense(temp_workspace):
    """验证符号链接穿透防御：指向生产代码的 symlink 必须判定为受管"""
    code_dir = temp_workspace / "src"
    code_dir.mkdir(parents=True, exist_ok=True)
    real_code_file = code_dir / "target.py"
    real_code_file.write_text("print('hello')", encoding="utf-8")

    docs_dir = temp_workspace / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    symlink_file = docs_dir / "link_to_code.py"

    try:
        symlink_file.symlink_to(real_code_file)
        symlink_created = True
    except (OSError, NotImplementedError):
        symlink_created = False

    cfg = QuenchStackConfig(workspace_root=str(temp_workspace), project_name="symlink_test")

    if symlink_created:
        # 即使 symlink 位于 docs/ 目录下，由于指向 src/target.py，必须穿透解析并判定为受管
        assert cfg.is_path_governed(str(symlink_file)) is True
    else:
        # Windows 权限限制若无法创建真实 symlink，使用 mock 测试 realpath 解析效果
        with patch("os.path.realpath") as mock_realpath:
            mock_realpath.side_effect = lambda p: str(real_code_file) if "link_to_code.py" in str(p) else str(p)
            assert cfg.is_path_governed(str(symlink_file)) is True


def test_load_project_config_dynamic_script_path(temp_workspace):
    """验证缺少 quench_stack.yaml 时异常信息动态计算 init_project.py 路径而非硬编码"""
    import project_config

    mock_file_path = os.path.normpath("/custom/virtual/path/plugins/quench-dev-tasks/server/project_config.py")
    expected_script = os.path.normpath("/custom/virtual/path/plugins/quench-dev-tasks/scripts/init_project.py")

    with patch.object(project_config, "__file__", mock_file_path):
        with pytest.raises(FileNotFoundError) as exc_info:
            load_project_config(str(temp_workspace))

    msg = str(exc_info.value)
    assert expected_script in msg
    assert "D:\\Work\\Quench\\MCP" not in msg


def test_looks_like_plaintext_secret():
    """验证明文密钥探测函数：精准识别密钥模式且不误判合法环境变量名"""
    # 正例（明文密钥/高危模式）
    assert _looks_like_plaintext_secret("sk-1234567890abcdef") is True
    assert _looks_like_plaintext_secret("sk-proj-abc123xyz456") is True
    assert _looks_like_plaintext_secret("Bearer sk-ant-api03-xxxx") is True
    assert _looks_like_plaintext_secret("key-9876543210abcdef") is True
    assert _looks_like_plaintext_secret("ghp_1234567890abcdef1234567890abcdef") is True
    assert _looks_like_plaintext_secret("e4d909c290d0fb1ca068ffaddf22cbd0") is True  # 32位纯hex
    assert _looks_like_plaintext_secret("https://api.example.com/v1?api_key=sk-1234567890") is True

    # 负例（合法环境变量名、普通字符串或URL）
    assert _looks_like_plaintext_secret("OPENAI_API_KEY") is False
    assert _looks_like_plaintext_secret("DEEPSEEK_API_KEY_Quench") is False
    assert _looks_like_plaintext_secret("MY_API_KEY") is False
    assert _looks_like_plaintext_secret("CUSTOM_TOKEN_ENV") is False
    assert _looks_like_plaintext_secret("https://api.example.com/v1") is False
    assert _looks_like_plaintext_secret("http://127.0.0.1:11434/v1") is False


def test_reject_inline_credentials():
    """验证 URL 明文鉴权串探测（user:pass@）防御"""
    with pytest.raises(ConfigError) as exc_info:
        _reject_inline_credentials("https://user:password@api.example.com/v1")
    assert "不得包含明文鉴权凭据" in str(exc_info.value)

    # 正常无凭据 URL 不抛异常
    _reject_inline_credentials("https://api.example.com/v1")
    _reject_inline_credentials("http://127.0.0.1:8000/v1")


def test_config_credentials_security_rejections(temp_workspace):
    """验证配置加载时的凭据防御拦截（抛出 ConfigError 且不误判 model/provider）"""
    import yaml

    agents_dir = temp_workspace / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    yaml_file = agents_dir / "quench_stack.yaml"

    # 1. 尝试在 api_key_env 中直接填入明文 sk- 密钥
    base_data = {
        "project_name": "test_sec",
        "reviewer_engine": {
            "provider": "custom",
            "model": "gpt-4o",  # 连字符模型名不应被误判
            "api_key_env": "sk-proj-1234567890abcdef123456",
            "base_url": "https://api.example.com/v1",
        }
    }
    yaml_file.write_text(yaml.dump(base_data), encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(str(temp_workspace))
    assert "api_key_env 字段不得填入明文 API 密钥" in str(exc_info.value)

    # 2. 尝试在 base_url 中夹带 user:pass@
    base_data["reviewer_engine"]["api_key_env"] = "VALID_KEY_ENV"
    base_data["reviewer_engine"]["base_url"] = "https://user:pass@api.example.com/v1"
    yaml_file.write_text(yaml.dump(base_data), encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(str(temp_workspace))
    assert "不得包含明文鉴权凭据" in str(exc_info.value)

    # 3. 尝试在配置中写入 api_key 字段
    base_data["reviewer_engine"]["base_url"] = "https://api.example.com/v1"
    base_data["reviewer_engine"]["api_key"] = "any-key-here"
    yaml_file.write_text(yaml.dump(base_data), encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(str(temp_workspace))
    assert "严禁出现 'api_key' 明文凭据字段" in str(exc_info.value)

    # 4. 尝试在 headers 中夹带明文 Bearer sk-
    del base_data["reviewer_engine"]["api_key"]
    base_data["reviewer_engine"]["headers"] = {"Authorization": "Bearer sk-1234567890abcdef"}
    yaml_file.write_text(yaml.dump(base_data), encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        load_project_config(str(temp_workspace))
    assert "headers 中不得包含明文 API 密钥" in str(exc_info.value)


def test_quench_stack_local_yaml_overlay(temp_workspace):
    """验证 .agents/quench_stack.local.yaml 本地私有覆盖机制"""
    import yaml

    agents_dir = temp_workspace / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    yaml_file = agents_dir / "quench_stack.yaml"
    local_yaml_file = agents_dir / "quench_stack.local.yaml"

    base_data = {
        "project_name": "base_project",
        "reviewer_engine": {
            "provider": "none",
            "model": "default",
            "timeout_seconds": 120,
        }
    }
    yaml_file.write_text(yaml.dump(base_data), encoding="utf-8")

    # 未提供 local 时加载 base
    cfg = load_project_config(str(temp_workspace))
    assert cfg.reviewer_engine.provider == "none"
    assert cfg.reviewer_engine.timeout_seconds == 120

    # 提供 local 时，覆盖相应字段且保留其余字段
    local_data = {
        "reviewer_engine": {
            "provider": "ollama",
            "model": "qwen2.5-coder",
            "base_url": "http://127.0.0.1:11434/v1",
        }
    }
    local_yaml_file.write_text(yaml.dump(local_data), encoding="utf-8")

    cfg_overridden = load_project_config(str(temp_workspace))
    assert cfg_overridden.reviewer_engine.provider == "ollama"
    assert cfg_overridden.reviewer_engine.model == "qwen2.5-coder"
    assert cfg_overridden.reviewer_engine.base_url == "http://127.0.0.1:11434/v1"
    # timeout_seconds 依然保留基础配置
    assert cfg_overridden.reviewer_engine.timeout_seconds == 120


