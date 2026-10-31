import json
import os
from pathlib import Path
import sys
import time
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config_sync import auto_heal_configs, is_workspace_plugin_mounted, render_plugin_configs


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


def test_auto_heal_workspace_mcp_config(tmp_path):
    """当工作区的 .agents/mcp_config.json 缺失或滞后于插件模板时，自动同步刷新工作区配置并保留第三方 server。"""
    p_dir = tmp_path / "plugin"
    p_dir.mkdir()
    (p_dir / "server").mkdir()
    (p_dir / "server" / "server.py").write_text("# server", encoding="utf-8")
    (p_dir / "server" / "hooks").mkdir()
    (p_dir / "server" / "hooks" / "file_scope_guard.py").write_text("# guard", encoding="utf-8")
    (p_dir / "server" / "hooks" / "context_injector.py").write_text("# injector", encoding="utf-8")

    mcp_tpl = p_dir / "mcp_config.json.template"
    mcp_tpl.write_text('{"mcpServers": {"quench-dev-tasks": {"command": "{{PYTHON_EXECUTABLE}}", "args": ["{{SERVER_SCRIPT_PATH}}"]}}}', encoding="utf-8")

    hooks_tpl = p_dir / "hooks.json.template"
    hooks_tpl.write_text('{"guard": "{{FILE_GUARD_SCRIPT_PATH}}"}', encoding="utf-8")

    auto_heal_configs(plugin_dir=str(p_dir), python_exe="python")

    ws_dir = tmp_path / "workspace"
    ws_agents = ws_dir / ".agents"
    ws_agents.mkdir(parents=True)
    ws_hooks = ws_agents / "hooks.json"
    ws_hooks.write_text('{"guard": "file_scope_guard.py"}', encoding="utf-8")
    # 让 hooks.json 最新，避免混入 hooks 自愈
    now = time.time()
    os.utime(str(ws_hooks), (now + 10, now + 10))

    ws_mcp = ws_agents / "mcp_config.json"
    # 模拟已有第三方 server 的旧配置
    ws_mcp.write_text(json.dumps({
        "mcpServers": {
            "third-party": {"command": "node", "args": ["app.js"]}
        }
    }), encoding="utf-8")
    past = time.time() - 100
    os.utime(str(ws_mcp), (past, past))

    healed, affected = auto_heal_configs(plugin_dir=str(p_dir), workspace_root=str(ws_dir), python_exe="python")
    assert healed is True
    assert any(str(ws_mcp) in f for f in affected)

    with open(ws_mcp, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "quench-dev-tasks" in data["mcpServers"]
    assert "third-party" in data["mcpServers"]


def test_is_workspace_plugin_mounted_detection(tmp_path):
    """断言 is_workspace_plugin_mounted 支持直接路径、父级路径及 enabled 字段过滤。"""
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    p_dir = ws_dir / "plugins" / "quench-dev-tasks"
    p_dir.mkdir(parents=True)

    # 1. 缺失 plugins.json -> False
    assert is_workspace_plugin_mounted(str(ws_dir), str(p_dir)) is False

    # 2. 空 entries -> False
    agents_dir = ws_dir / ".agents"
    agents_dir.mkdir()
    plugins_json = agents_dir / "plugins.json"
    plugins_json.write_text('{"entries": []}', encoding="utf-8")
    assert is_workspace_plugin_mounted(str(ws_dir), str(p_dir)) is False

    # 3. disabled -> False
    plugins_json.write_text(json.dumps({
        "entries": [{"path": "plugins", "enabled": False}]
    }), encoding="utf-8")
    assert is_workspace_plugin_mounted(str(ws_dir), str(p_dir)) is False

    # 4. parent directory mount -> True
    plugins_json.write_text(json.dumps({
        "entries": [{"path": "plugins"}]
    }), encoding="utf-8")
    assert is_workspace_plugin_mounted(str(ws_dir), str(p_dir)) is True

    # 5. exact plugin directory mount -> True
    plugins_json.write_text(json.dumps({
        "entries": [{"path": "plugins/quench-dev-tasks"}]
    }), encoding="utf-8")
    assert is_workspace_plugin_mounted(str(ws_dir), str(p_dir)) is True


def test_auto_heal_strips_redundant_configs_when_plugin_mounted(tmp_path):
    """当工作区已挂载插件时，auto_heal 清理孤立冗余配置并 unlink 空文件。"""
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    p_dir = ws_dir / "plugins" / "quench-dev-tasks"
    p_dir.mkdir(parents=True)
    (p_dir / "server").mkdir()
    (p_dir / "server" / "server.py").write_text("# server", encoding="utf-8")
    (p_dir / "server" / "hooks").mkdir()
    (p_dir / "server" / "hooks" / "file_scope_guard.py").write_text("# guard", encoding="utf-8")
    (p_dir / "server" / "hooks" / "context_injector.py").write_text("# injector", encoding="utf-8")

    mcp_tpl = p_dir / "mcp_config.json.template"
    mcp_tpl.write_text('{"mcpServers": {"quench-dev-tasks": {"command": "{{PYTHON_EXECUTABLE}}", "args": ["{{SERVER_SCRIPT_PATH}}"]}}}', encoding="utf-8")

    hooks_tpl = p_dir / "hooks.json.template"
    hooks_tpl.write_text('{"quench-file-guard": {}, "quench-context-injector": {}}', encoding="utf-8")

    # 首次落地插件级配置
    auto_heal_configs(plugin_dir=str(p_dir), python_exe="python")

    # 挂载插件
    agents_dir = ws_dir / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plugins_json = agents_dir / "plugins.json"
    plugins_json.write_text(json.dumps({"entries": [{"path": "plugins"}]}), encoding="utf-8")

    # 模拟工作区遗留纯 quench 冗余配置
    ws_hooks = agents_dir / "hooks.json"
    ws_hooks.write_text(json.dumps({
        "quench-file-guard": {"PreToolUse": []},
        "quench-context-injector": {"PreInvocation": []}
    }), encoding="utf-8")

    ws_mcp = agents_dir / "mcp_config.json"
    ws_mcp.write_text(json.dumps({
        "mcpServers": {
            "quench-dev-tasks": {"command": "python", "args": ["server.py"]}
        }
    }), encoding="utf-8")

    healed, affected = auto_heal_configs(plugin_dir=str(p_dir), workspace_root=str(ws_dir), python_exe="python")
    assert healed is True
    assert str(ws_hooks) in affected
    assert str(ws_mcp) in affected

    # 因为剥离后为空，文件应当被直接删除 unlink
    assert not ws_hooks.exists()
    assert not ws_mcp.exists()


def test_auto_heal_preserves_third_party_when_plugin_mounted(tmp_path):
    """当工作区已挂载插件且包含第三方配置时，auto_heal 仅剥离 quench 键并保留文件与第三方条目。"""
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    p_dir = ws_dir / "plugins" / "quench-dev-tasks"
    p_dir.mkdir(parents=True)
    (p_dir / "server").mkdir()
    (p_dir / "server" / "server.py").write_text("# server", encoding="utf-8")
    (p_dir / "server" / "hooks").mkdir()
    (p_dir / "server" / "hooks" / "file_scope_guard.py").write_text("# guard", encoding="utf-8")
    (p_dir / "server" / "hooks" / "context_injector.py").write_text("# injector", encoding="utf-8")

    mcp_tpl = p_dir / "mcp_config.json.template"
    mcp_tpl.write_text('{"mcpServers": {"quench-dev-tasks": {"command": "{{PYTHON_EXECUTABLE}}", "args": ["{{SERVER_SCRIPT_PATH}}"]}}}', encoding="utf-8")
    hooks_tpl = p_dir / "hooks.json.template"
    hooks_tpl.write_text('{"quench-file-guard": {}}', encoding="utf-8")

    auto_heal_configs(plugin_dir=str(p_dir), python_exe="python")

    agents_dir = ws_dir / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plugins_json = agents_dir / "plugins.json"
    plugins_json.write_text(json.dumps({"entries": [{"path": "plugins"}]}), encoding="utf-8")

    # 包含第三方条目
    ws_hooks = agents_dir / "hooks.json"
    ws_hooks.write_text(json.dumps({
        "quench-file-guard": {},
        "third-party-hook": {"type": "command"}
    }), encoding="utf-8")

    ws_mcp = agents_dir / "mcp_config.json"
    ws_mcp.write_text(json.dumps({
        "mcpServers": {
            "quench-dev-tasks": {"command": "python"},
            "third-party-server": {"command": "node", "args": ["srv.js"]}
        }
    }), encoding="utf-8")

    healed, affected = auto_heal_configs(plugin_dir=str(p_dir), workspace_root=str(ws_dir), python_exe="python")
    assert healed is True
    assert str(ws_hooks) in affected
    assert str(ws_mcp) in affected

    # 文件保留
    assert ws_hooks.exists()
    assert ws_mcp.exists()

    with open(ws_hooks, "r", encoding="utf-8") as f:
        h_data = json.load(f)
    assert "quench-file-guard" not in h_data
    assert "third-party-hook" in h_data

    with open(ws_mcp, "r", encoding="utf-8") as f:
        m_data = json.load(f)
    assert "quench-dev-tasks" not in m_data["mcpServers"]
    assert "third-party-server" in m_data["mcpServers"]


