import json
import os
from pathlib import Path
import sys
import time
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config_sync import auto_heal_configs, render_plugin_configs


def test_auto_heal_noop_when_fresh(tmp_path):
    """当生成物存在且 mtime 新于模板时，auto_heal 保持静默返回 (False, [])"""
    p_dir = tmp_path / "plugin"
    p_dir.mkdir()
    (p_dir / "server").mkdir()
    (p_dir / "server" / "server.py").write_text("# server", encoding="utf-8")
    (p_dir / "server" / "hooks").mkdir()
    (p_dir / "server" / "hooks" / "file_scope_guard.py").write_text("# guard", encoding="utf-8")
    (p_dir / "server" / "hooks" / "context_injector.py").write_text("# injector", encoding="utf-8")

    mcp_tpl = p_dir / "mcp_config.json.template"
    mcp_tpl.write_text('{"mcpServers": {"test": {"command": "{{PYTHON_EXECUTABLE}}", "args": ["{{SERVER_SCRIPT_PATH}}"]}}}', encoding="utf-8")

    hooks_tpl = p_dir / "hooks.json.template"
    hooks_tpl.write_text('{"guard": "{{FILE_GUARD_SCRIPT_PATH}}", "injector": "{{CONTEXT_INJECTOR_SCRIPT_PATH}}"}', encoding="utf-8")

    # 首次执行自愈完成初次落地
    healed, affected = auto_heal_configs(plugin_dir=str(p_dir), python_exe="python")
    assert healed is True
    assert (p_dir / "mcp_config.json").exists()
    assert (p_dir / "hooks.json").exists()

    # 再次调用：应当无需重新生成
    healed, affected = auto_heal_configs(plugin_dir=str(p_dir), python_exe="python")
    assert healed is False
    assert affected == []


def test_auto_heal_regenerates_when_template_newer(tmp_path):
    """当模板文件的 mtime 晚于生成物时，auto_heal 自动执行重渲染并返回 (True, [...])"""
    p_dir = tmp_path / "plugin"
    p_dir.mkdir()
    (p_dir / "server").mkdir()
    (p_dir / "server" / "server.py").write_text("# server", encoding="utf-8")
    (p_dir / "server" / "hooks").mkdir()
    (p_dir / "server" / "hooks" / "file_scope_guard.py").write_text("# guard", encoding="utf-8")
    (p_dir / "server" / "hooks" / "context_injector.py").write_text("# injector", encoding="utf-8")

    mcp_tpl = p_dir / "mcp_config.json.template"
    mcp_tpl.write_text('{"mcpServers": {"test": {"command": "{{PYTHON_EXECUTABLE}}", "args": ["{{SERVER_SCRIPT_PATH}}"]}}}', encoding="utf-8")

    hooks_tpl = p_dir / "hooks.json.template"
    hooks_tpl.write_text('{"guard": "{{FILE_GUARD_SCRIPT_PATH}}", "injector": "{{CONTEXT_INJECTOR_SCRIPT_PATH}}"}', encoding="utf-8")

    auto_heal_configs(plugin_dir=str(p_dir), python_exe="python")

    # 模拟 git pull：将模板 mtime 推进未来
    now = time.time()
    os.utime(str(mcp_tpl), (now + 10, now + 10))

    healed, affected = auto_heal_configs(plugin_dir=str(p_dir), python_exe="python")
    assert healed is True
    assert any("mcp_config.json" in f for f in affected)


def test_auto_heal_workspace_hooks(tmp_path):
    """当工作区的 .agents/hooks.json 滞后于插件模板时，自动同步刷新工作区配置"""
    p_dir = tmp_path / "plugin"
    p_dir.mkdir()
    (p_dir / "server").mkdir()
    (p_dir / "server" / "server.py").write_text("# server", encoding="utf-8")
    (p_dir / "server" / "hooks").mkdir()
    (p_dir / "server" / "hooks" / "file_scope_guard.py").write_text("# guard", encoding="utf-8")
    (p_dir / "server" / "hooks" / "context_injector.py").write_text("# injector", encoding="utf-8")

    mcp_tpl = p_dir / "mcp_config.json.template"
    mcp_tpl.write_text('{"mcpServers": {}}', encoding="utf-8")

    hooks_tpl = p_dir / "hooks.json.template"
    hooks_tpl.write_text('{"guard": "{{FILE_GUARD_SCRIPT_PATH}}"}', encoding="utf-8")

    auto_heal_configs(plugin_dir=str(p_dir), python_exe="python")

    ws_dir = tmp_path / "workspace"
    ws_agents = ws_dir / ".agents"
    ws_agents.mkdir(parents=True)
    ws_hooks = ws_agents / "hooks.json"
    ws_hooks.write_text('{"old": true}', encoding="utf-8")

    # 模拟工作区 hooks.json 滞后
    past = time.time() - 100
    os.utime(str(ws_hooks), (past, past))

    healed, affected = auto_heal_configs(plugin_dir=str(p_dir), workspace_root=str(ws_dir), python_exe="python")
    assert healed is True
    assert any(str(ws_hooks) in f for f in affected)

    with open(ws_hooks, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "file_scope_guard.py" in data.get("guard", "")
