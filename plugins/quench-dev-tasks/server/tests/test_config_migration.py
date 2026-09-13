# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import tempfile
import warnings
import pytest
from pathlib import Path

from project_config import (
    CURRENT_SCHEMA_VERSION,
    QuenchStackConfig,
    load_project_config,
    migrate_config_if_needed,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        agents_dir = root / ".agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        yield root


def test_template_neutrality():
    """验证 templates/quench_stack.yaml 已经过项目中立化清洗"""
    template_path = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "templates",
            "quench_stack.yaml",
        )
    )
    assert os.path.isfile(template_path), f"模板文件不存在: {template_path}"

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 严禁残留 JJW_MES 工控项目私有内容
    forbidden_keywords = [
        "JJW_MES",
        "离线车间",
        "双寄存器",
        "ipc_client",
        "SQLite WAL",
        "Standby=0",
    ]
    for kw in forbidden_keywords:
        assert kw not in content, f"模板中仍然残留私有工控关键词: '{kw}'"

    # 必须包含占位符与规范版本标识
    assert '__PROJECT_NAME__' in content
    assert 'schema_version: "1.0"' in content


def test_template_multi_stack_guidance():
    """验证 templates/quench_stack.yaml 包含多技术栈场景注释范例且可正常被 YAML 解析"""
    import yaml
    template_path = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "templates",
            "quench_stack.yaml",
        )
    )
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 验证多技术栈示例存在
    assert "Web 全栈开发" in content
    assert "云原生微服务" in content
    assert "CLI 命令行工具" in content

    # 验证解析后的 YAML 结构完好
    data = yaml.safe_load(content.replace("__PROJECT_NAME__", "TestApp"))
    assert data["project_name"] == "TestApp"
    assert data["schema_version"] == "1.0"
    assert isinstance(data["constraints"], list)
    assert len(data["constraints"]) >= 3


def test_migrate_config_v0_to_v1(temp_workspace):
    """验证旧版 v0 配置文件在 load_project_config 时自动平滑升级为 v1.0"""
    yaml_path = temp_workspace / ".agents" / "quench_stack.yaml"
    legacy_content = (
        "# 这是一个旧版配置\n"
        "project_name: 'LegacyProject'\n"
        "dev_tasks_dir: 'docs/dev_tasks'\n"
        "changelog_path: 'CHANGELOG.md'\n"
    )
    yaml_path.write_text(legacy_content, encoding="utf-8")

    # 加载配置触发自动迁移
    cfg = load_project_config(str(temp_workspace))

    assert cfg.schema_version == CURRENT_SCHEMA_VERSION
    assert cfg.project_name == "LegacyProject"
    assert cfg.fast_track_rules == {"allow_untracked_patterns": []}

    # 检查磁盘文件是否已原子追加升级补丁
    disk_content = yaml_path.read_text(encoding="utf-8")
    assert 'schema_version: "1.0"' in disk_content
    assert "fast_track_rules:" in disk_content
    # 原有内容依然保留
    assert "project_name: 'LegacyProject'" in disk_content


def test_migrate_config_preserves_comments_and_custom_fields(temp_workspace):
    """验证文本级迁移零破坏：保留所有既有注释与用户自定义扩展字段"""
    yaml_path = temp_workspace / ".agents" / "quench_stack.yaml"
    content_with_comments = (
        "# ==========================================\n"
        "# 核心架构自定义配置\n"
        "# ==========================================\n"
        "project_name: 'CustomProject' # 行内注释不可丢失\n"
        "custom_domain_field: 'financial_ledger'\n"
        "custom_retry_limit: 5\n"
    )
    yaml_path.write_text(content_with_comments, encoding="utf-8")

    cfg = load_project_config(str(temp_workspace))
    assert cfg.project_name == "CustomProject"

    # 重新读取原文本断言注释完整留存
    updated_raw = yaml_path.read_text(encoding="utf-8")
    assert "# 核心架构自定义配置" in updated_raw
    assert "# 行内注释不可丢失" in updated_raw
    assert "custom_domain_field: 'financial_ledger'" in updated_raw
    assert "custom_retry_limit: 5" in updated_raw
    assert 'schema_version: "1.0"' in updated_raw


def test_empty_or_corrupted_config_raises_error(temp_workspace):
    """验证空文件或格式损坏文件抛出明确 ValueError，不被盲目覆写"""
    yaml_path = temp_workspace / ".agents" / "quench_stack.yaml"

    # 1. 空白文件
    yaml_path.write_text("   \n\n  \t", encoding="utf-8")
    with pytest.raises(ValueError, match="配置文件为空或仅包含空白字符"):
        load_project_config(str(temp_workspace))

    # 2. 语法损坏文件
    yaml_path.write_text("project_name: [unclosed list", encoding="utf-8")
    with pytest.raises(ValueError, match="YAML 语法错误"):
        load_project_config(str(temp_workspace))

    # 3. 非字典文件
    yaml_path.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="配置文件格式无效"):
        load_project_config(str(temp_workspace))


def test_higher_schema_version_no_downgrade(temp_workspace):
    """验证若遇到高版本 schema_version（如 2.0），不执行降级，发出警告"""
    yaml_path = temp_workspace / ".agents" / "quench_stack.yaml"
    future_content = (
        "schema_version: '2.0'\n"
        "project_name: 'FutureProject'\n"
    )
    yaml_path.write_text(future_content, encoding="utf-8")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cfg = load_project_config(str(temp_workspace))
        assert cfg.schema_version == "2.0"
        assert any("高于当前系统支持版本" in str(item.message) for item in w)

    # 磁盘文件内容保持 2.0，不被降级
    disk_content = yaml_path.read_text(encoding="utf-8")
    assert "schema_version: '2.0'" in disk_content
