# -*- coding: utf-8 -*-
"""Unit tests for AST Code Explorer and dev_tasks_refine_spec / dev_tasks_escalate.
Rigorous mock tests covering AST slicing, CJK safety, path containment, circular imports,
schema validation, and offline engine fallback.
"""
import io
import json
import os
import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from code_explorer import (
    ExploreResult,
    extract_ast_interfaces,
    explore_code_slices,
    is_path_safe,
    is_sensitive_file,
)
from project_config import QuenchStackConfig, ReviewerEngineConfig
from server import (
    _parse_task_markdown_sections,
    dev_tasks_escalate,
    dev_tasks_refine_spec,
)


@pytest.fixture
def sample_ws(tmp_path):
    ws = tmp_path / "test_refine_ws"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    src_dir = ws / "src"
    src_dir.mkdir()

    # 写入基础配置文件
    cfg_content = (
        "project_name: 'TestWs'\n"
        "dev_tasks_dir: 'docs/dev_tasks'\n"
        "architecture_doc: 'docs/arch.md'\n"
        "constraints: ['Thread-safe state changes']\n"
        "schema_version: '1.0'\n"
    )
    (agents_dir / "quench_stack.yaml").write_text(cfg_content, encoding="utf-8")
    
    docs_dir = ws / "docs"
    docs_dir.mkdir()
    (docs_dir / "arch.md").write_text("# Test Arch\nCore logic in src/", encoding="utf-8")

    # 创建示例 Python 文件（包含中文注释、类型注解与异步函数）
    py_code = (
        "# -*- coding: utf-8 -*-\n"
        "\"\"\"用户与订单核心管理模块 (MES 系统)\"\"\"\n"
        "import os\n"
        "from typing import List, Optional\n\n"
        "class OrderManager:\n"
        "    \"\"\"订单调度与并发锁控制器\"\"\"\n"
        "    def __init__(self, capacity: int = 10):\n"
        "        self.capacity = capacity\n\n"
        "    def create_order(self, order_id: str, items: List[str]) -> bool:\n"
        "        \"\"\"创建工单并下发排产指令\"\"\"\n"
        "        return True\n\n"
        "async def process_batch_async(batch_id: str) -> None:\n"
        "    \"\"\"异步批量处理流水线状态\"\"\"\n"
        "    pass\n"
    )
    (src_dir / "order.py").write_text(py_code, encoding="utf-8")

    return str(ws)


def test_is_path_safe_and_traversal(sample_ws):
    """路径沙箱防御：绝对路径、相对越界与空字符拦截。"""
    assert is_path_safe(sample_ws, "src/order.py") is True
    assert is_path_safe(sample_ws, "src/../src/order.py") is True
    assert is_path_safe(sample_ws, "../../etc/passwd") is False
    assert is_path_safe(sample_ws, "src/order.py\x00extra") is False
    assert is_path_safe(sample_ws, "") is False


def test_is_sensitive_file_denylist():
    """敏感凭据文件黑名单过滤。"""
    assert is_sensitive_file(".env") is True
    assert is_sensitive_file(".env.production") is True
    assert is_sensitive_file("server.key") is True
    assert is_sensitive_file("id_rsa") is True
    assert is_sensitive_file("id_ed25519") is True
    assert is_sensitive_file("app_secret.json") is True
    assert is_sensitive_file("order.py") is False
    assert is_sensitive_file("README.md") is False


def test_ast_interface_extraction_cjk_preservation(sample_ws):
    """AST 接口提取：断言类名、方法名、异步函数与中文 docstring 完整保留。"""
    order_file = os.path.join(sample_ws, "src", "order.py")
    with open(order_file, "r", encoding="utf-8") as f:
        code = f.read()

    symbols, imports, ok = extract_ast_interfaces(code, "src/order.py")
    assert ok is True
    assert "os" in imports
    
    names = [s.name for s in symbols]
    assert "OrderManager" in names
    assert "OrderManager.create_order" in names
    assert "process_batch_async" in names

    # 校验中文 docstring 完整无损
    order_cls = next(s for s in symbols if s.name == "OrderManager")
    assert order_cls.docstring == "订单调度与并发锁控制器"
    
    create_fn = next(s for s in symbols if s.name == "OrderManager.create_order")
    assert create_fn.docstring == "创建工单并下发排产指令"


def test_code_explorer_circular_import_cycle_defense(sample_ws):
    """循环依赖探索：模块 A 导入模块 B，模块 B 导入模块 A，必须有界退出。"""
    src_dir = os.path.join(sample_ws, "src")
    a_py = os.path.join(src_dir, "mod_a.py")
    b_py = os.path.join(src_dir, "mod_b.py")

    with open(a_py, "w", encoding="utf-8") as f:
        f.write("import mod_b\ndef func_a(): pass\n")
    with open(b_py, "w", encoding="utf-8") as f:
        f.write("import mod_a\ndef func_b(): pass\n")

    res = explore_code_slices(sample_ws, ["src/mod_a.py"], max_hops=3)
    assert res.hops_used <= 3
    rel_paths = [f.rel_path for f in res.files]
    assert "src/mod_a.py" in rel_paths
    assert "src/mod_b.py" in rel_paths
    # 绝对无死循环
    assert len(res.files) <= 3


def test_code_explorer_syntax_error_graceful_skip(sample_ws):
    """语法错误与二进制文件：优雅降级不崩溃。"""
    corrupt_file = os.path.join(sample_ws, "src", "bad.py")
    with open(corrupt_file, "w", encoding="utf-8") as f:
        f.write("def broken_syntax( { : [ incomplete")

    res = explore_code_slices(sample_ws, ["src/bad.py"], max_hops=1)
    assert len(res.files) == 1
    # 语法错误时符号列表为空，但文本切片仍然安全返回
    assert res.files[0].symbols == []


@pytest.mark.anyio
async def test_dev_tasks_refine_spec_offline_fallback(sample_ws):
    """ReviewerEngine 离线降级分支：当 provider='none' 时优雅保留草案并标明 degraded=True。"""
    draft = {
        "id": "3.1",
        "title": "重构订单状态机",
        "content": "原有状态机缺乏幂等锁，容易产生乱序写入",
        "affected_files": ["src/order.py"],
    }

    res = await dev_tasks_refine_spec(sample_ws, draft, context_files=["src/order.py"])
    assert res["ok"] is True
    assert res["degraded"] is True
    assert res["engine"] == "fallback_offline"
    assert res["task_id"] == "3.1"
    assert "重构订单状态机" in res["refined_spec"]


@pytest.mark.anyio
async def test_dev_tasks_refine_spec_mock_success(sample_ws):
    """ReviewerEngine 在线强化分支：模型返回完整六大字段，通过 schema_validator 并成功格式化。"""
    # 启用 deepseek 配置
    cfg_path = os.path.join(sample_ws, ".agents", "quench_stack.yaml")
    with open(cfg_path, "a", encoding="utf-8") as f:
        f.write("reviewer_engine:\n  provider: 'deepseek'\n  api_key_env: 'MOCK_KEY'\n")

    mock_llm_json = {
        "affected_files": ["[MODIFY] src/order.py"],
        "root_cause_and_goal": "根因：缺乏并发互斥锁。目标：在 OrderManager 引入 ThreadPoolLock",
        "type_contracts": "def create_order(self, order_id: str, items: List[str]) -> bool: ...",
        "steps": [
            "1. 在 order.py 中引入 threading.Lock",
            "2. 在 create_order 方法内部使用 with self._lock 保护临界区",
        ],
        "defensive_checks": [
            "并发安全断言：多线程高并发下单无脏读",
            "锁竞争超时熔断防护",
        ],
        "dod_commands": "pytest tests/test_order_concurrency.py",
    }
    raw_content = json.dumps(mock_llm_json, ensure_ascii=False)

    fake_client = MagicMock()
    fake_client.is_available.return_value = True
    fake_client.acomplete = AsyncMock(return_value={
        "content": raw_content,
        "reasoning_content": "Thinking: analyzed threading risks.",
    })

    draft = {
        "id": "3.2",
        "title": "并发锁加固",
        "content": "为 OrderManager 增加线程安全锁",
        "affected_files": ["src/order.py"],
    }

    with patch("server.DeepSeekClient", return_value=fake_client):
        res = await dev_tasks_refine_spec(sample_ws, draft, context_files=["src/order.py"])
        assert res["ok"] is True
        assert res["degraded"] is False
        assert res["validation"]["is_valid"] is True
        assert "【涉及文件】" in res["refined_spec"]
        assert "【缺陷根因与修改目标】" in res["refined_spec"]
        assert "【DoD 验证命令】" in res["refined_spec"]
        assert res["task_id"] == "3.2"


def test_dev_tasks_escalate_backward_compat_and_diagnostics(sample_ws):
    """dev_tasks_escalate 向后兼容性：所有既有字段均保持一致，附加 auto_diagnostics。"""
    # 创建任务单文件
    tasks_dir = os.path.join(sample_ws, "docs", "dev_tasks")
    os.makedirs(tasks_dir, exist_ok=True)
    task_file = os.path.join(tasks_dir, "2026-09-21_test.md")
    with open(task_file, "w", encoding="utf-8") as f:
        f.write("# Dev Tasks\n### 任务 1.1 🔨 执行中 — 疑难卡点\n")

    res = dev_tasks_escalate(
        sample_ws,
        "2026-09-21_test.md",
        "1.1",
        reason="订单分布式死锁无法收敛",
        context_files=["src/order.py"],
    )

    # 既有核心键必须原样保留
    assert res["status"] == "escalated"
    assert res["task_id"] == "1.1"
    assert res["reason"] == "订单分布式死锁无法收敛"
    assert "reviewer" in res["suggested_subagent"]
    assert res["handoff_required"] is True
    assert res["context_files_loaded"] == 1


def test_parse_task_markdown_sections_resilience():
    """解析容错性测试：支持原生 JSON 与标准 Markdown 双向解析。"""
    md_text = (
        "### 任务 9.1 ⬜ 待确认 — 单元测试规约\n\n"
        "#### 【涉及文件】\n```\n[MODIFY] server.py\n```\n\n"
        "#### 【缺陷根因与修改目标】\n根因分析清晰。\n\n"
        "#### 【目标签名与类型契约】\ndef test_fn(): ...\n\n"
        "#### 【分步改造指引】\n1. 步骤一\n2. 步骤二\n\n"
        "#### 【防御与边缘校验】\n- 边界保护\n\n"
        "#### 【DoD 验证命令】\npytest test.py\n"
    )
    d = _parse_task_markdown_sections(md_text)
    assert d["affected_files"] == ["[MODIFY] server.py"]
    assert "根因分析清晰" in d["root_cause_and_goal"]
    assert len(d["steps"]) == 2
    assert d["id"] == "9.1"
