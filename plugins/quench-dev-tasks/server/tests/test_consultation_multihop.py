# -*- coding: utf-8 -*-
"""Unit tests for multi-hop NEED-FILES guardrails in consultation.

Verifies:
1. should_enable_multi_hop integer cross-multiplication & exact boundary conditions;
2. strip_reasoning_from_history pure function semantics (immutability of input, assistant-only filtering);
3. HopBudget atomic consumption, non-negative clamping, and capacity boundaries;
4. evaluate_multi_hop_gate & telemetry reading (ENOENT, corrupted lines, tail-read limit, threshold check);
5. Audit latching with threading.Event preventing duplicate writes;
6. Native multi-turn loop and ReviewerBadRequestError (400/422) fallback to single-turn delivery.
"""
from pathlib import Path
from typing import Any, List, Optional
import json
import threading
import pytest

from consultation import (
    CodeSlice,
    ConsultRequest,
    HopBudget,
    MAX_TOTAL_INJECTION_CHARS,
    MIN_TELEMETRY_SAMPLES,
    MULTI_HOP_DEMAND_PERCENT,
    MULTI_HOP_DEMAND_THRESHOLD,
    _emit_consultation_audit,
    _read_telemetry_demand_sync,
    evaluate_multi_hop_gate,
    run_consultation,
    should_enable_multi_hop,
    strip_reasoning_from_history,
)
from project_config import QuenchStackConfig, ReviewerEngineConfig
from reviewer_engine import (
    ReviewerBadRequestError,
    StreamChunk,
    UsageSnapshot,
)


# ============================================================================
# 1. 门控断言与整数交叉相乘边界单测
# ============================================================================

def test_should_enable_multi_hop_sample_count_boundary():
    """断言样本数不足 MIN_TELEMETRY_SAMPLES (20) 时无论需求比例多高均拒绝开启。"""
    assert should_enable_multi_hop(demand_count=0, sample_count=0) is False
    assert should_enable_multi_hop(demand_count=1, sample_count=1) is False
    assert should_enable_multi_hop(demand_count=10, sample_count=10) is False
    assert should_enable_multi_hop(demand_count=19, sample_count=19) is False


def test_should_enable_multi_hop_exact_percentage_thresholds():
    """断言采用整数交叉相乘严格判定 demand_count * 100 > 30 * sample_count。"""
    # 当 sample_count == 20: 30% 刚好是 6
    # 6 * 100 > 30 * 20 -> 600 > 600 为 False（严格大于，临界值不包含）
    assert should_enable_multi_hop(demand_count=5, sample_count=20) is False
    assert should_enable_multi_hop(demand_count=6, sample_count=20) is False
    # 7 * 100 > 30 * 20 -> 700 > 600 为 True
    assert should_enable_multi_hop(demand_count=7, sample_count=20) is True

    # 当 sample_count == 100: 30% 刚好是 30
    assert should_enable_multi_hop(demand_count=29, sample_count=100) is False
    assert should_enable_multi_hop(demand_count=30, sample_count=100) is False
    assert should_enable_multi_hop(demand_count=31, sample_count=100) is True

    # 当 sample_count == 50: 30% 是 15
    assert should_enable_multi_hop(demand_count=15, sample_count=50) is False
    assert should_enable_multi_hop(demand_count=16, sample_count=50) is True


# ============================================================================
# 2. strip_reasoning_from_history 纯函数单测
# ============================================================================

def test_strip_reasoning_from_history_pure_function():
    """断言 strip_reasoning_from_history 绝不原地修改入参，且仅移除 assistant 的 reasoning 字段。"""
    input_history = [
        {
            "role": "system",
            "content": "You are a reviewer.",
            "thought": "system thoughts should stay intact",
        },
        {
            "role": "user",
            "content": "Review this function.",
            "reasoning": "user reasoning should stay intact",
        },
        {
            "role": "assistant",
            "content": "Here is my preliminary review.\n<<<NEED-FILES>>> a.py:1-10 <<<END>>>",
            "reasoning_content": "Deep reasoning stream...",
            "reasoning": "Deprecated reasoning format",
            "thought": "Anthropic thought field",
            "thoughts": ["list", "of", "thoughts"],
            "custom_metadata": "keep_this",
        },
    ]

    cleaned = strip_reasoning_from_history(input_history)

    # 1. 验证入参完全未被修改（纯函数保证）
    assert len(input_history) == 3
    assert "thought" in input_history[0]
    assert "reasoning" in input_history[1]
    assert "reasoning_content" in input_history[2]
    assert "thought" in input_history[2]

    # 2. 验证清洗后的新列表结构
    assert len(cleaned) == 3
    assert cleaned[0]["role"] == "system"
    assert cleaned[0]["thought"] == "system thoughts should stay intact"

    assert cleaned[1]["role"] == "user"
    assert cleaned[1]["reasoning"] == "user reasoning should stay intact"

    assert cleaned[2]["role"] == "assistant"
    assert cleaned[2]["content"] == "Here is my preliminary review.\n<<<NEED-FILES>>> a.py:1-10 <<<END>>>"
    assert cleaned[2]["custom_metadata"] == "keep_this"
    assert "reasoning_content" not in cleaned[2]
    assert "reasoning" not in cleaned[2]
    assert "thought" not in cleaned[2]
    assert "thoughts" not in cleaned[2]


# ============================================================================
# 3. HopBudget 跨跳累积预算池单测
# ============================================================================

def test_hop_budget_atomic_consumption():
    """断言 HopBudget 聚合扣减、原子性防溢出及非负钳制。"""
    budget = HopBudget(total=5000)
    assert budget.total == 5000
    assert budget.consumed == 0
    assert budget.remaining == 5000

    # 正常消耗 Hop 1 (2000 字符)
    assert budget.consume(2000) is True
    assert budget.consumed == 2000
    assert budget.remaining == 3000

    # Hop 2 尝试消耗 4000 字符（超过剩余的 3000）
    # 必须返回 False，且已消耗计数器严禁扣减（保持原子性）
    assert budget.consume(4000) is False
    assert budget.consumed == 2000
    assert budget.remaining == 3000

    # 消耗负数安全钳制为 0
    assert budget.consume(-100) is True
    assert budget.consumed == 2000
    assert budget.remaining == 3000

    # 消耗剩余全部 3000
    assert budget.consume(3000) is True
    assert budget.consumed == 5000
    assert budget.remaining == 0

    # 耗尽后再次尝试消耗任意正数均原子失败
    assert budget.consume(1) is False
    assert budget.consumed == 5000
    assert budget.remaining == 0


# ============================================================================
# 4. evaluate_multi_hop_gate 与遥测读取单测
# ============================================================================

def test_read_telemetry_demand_sync_missing_and_corrupt(tmp_path: Path):
    """断言遥测文件不存在或存在残缺损坏行时容错解析。"""
    missing_file = tmp_path / "non_existent.jsonl"
    d_count, s_count = _read_telemetry_demand_sync(missing_file)
    assert (d_count, s_count) == (0, 0)

    # 包含损坏行与正常行
    telemetry_file = tmp_path / "cache_telemetry.jsonl"
    lines = [
        json.dumps({"session_id": "s1", "demand": True}),
        "{truncated invalid json...",  # 损坏行
        "",  # 空行
        json.dumps({"session_id": "s2", "has_need_files": True}),
        json.dumps({"session_id": "s3", "demand": False}),
    ]
    telemetry_file.write_text("\n".join(lines), encoding="utf-8")

    d_count, s_count = _read_telemetry_demand_sync(telemetry_file)
    # 有效行共 3 条，其中 s1 (demand=True) 和 s2 (has_need_files=True) 为需求
    assert s_count == 3
    assert d_count == 2


def test_read_telemetry_demand_sync_tail_limit(tmp_path: Path):
    """断言最多读取最新 50 条遥测记录（有界 tail-read）。"""
    telemetry_file = tmp_path / "cache_telemetry.jsonl"
    # 写入 70 条记录，最前 20 条 demand=False，后 50 条 demand=True
    records = []
    for _ in range(20):
        records.append(json.dumps({"demand": False}))
    for _ in range(50):
        records.append(json.dumps({"demand": True}))

    telemetry_file.write_text("\n".join(records), encoding="utf-8")

    d_count, s_count = _read_telemetry_demand_sync(telemetry_file, max_samples=50)
    assert s_count == 50
    assert d_count == 50  # 倒序读取最新 50 条全部为 demand=True


@pytest.mark.anyio
async def test_evaluate_multi_hop_gate_flow(tmp_path: Path):
    """断言 evaluate_multi_hop_gate 异步工作线程评估及门控原因格式化。"""
    ws = tmp_path / "workspace"
    log_dir = ws / ".agents" / "logs" / "reviewer"
    log_dir.mkdir(parents=True)
    telemetry_file = log_dir / "cache_telemetry.jsonl"

    # 1. 样本数不足 20
    telemetry_file.write_text(
        "\n".join(json.dumps({"demand": True}) for _ in range(15)),
        encoding="utf-8",
    )
    enabled, reason = await evaluate_multi_hop_gate(str(ws))
    assert enabled is False
    assert reason is not None
    assert "insufficient_samples" in reason
    assert "samples=15 < 20" in reason

    # 2. 样本数达到 25，但 demand 只有 5 (20% <= 30%)
    records = [json.dumps({"demand": True}) for _ in range(5)] + [
        json.dumps({"demand": False}) for _ in range(20)
    ]
    telemetry_file.write_text("\n".join(records), encoding="utf-8")
    enabled, reason = await evaluate_multi_hop_gate(str(ws))
    assert enabled is False
    assert reason is not None
    assert "demand_threshold_not_met" in reason
    assert "demand=5/25" in reason

    # 3. 样本数达到 25，demand 有 10 (40% > 30%)
    records_pass = [json.dumps({"demand": True}) for _ in range(10)] + [
        json.dumps({"demand": False}) for _ in range(15)
    ]
    telemetry_file.write_text("\n".join(records_pass), encoding="utf-8")
    enabled, reason = await evaluate_multi_hop_gate(str(ws))
    assert enabled is True
    assert reason is None


# ============================================================================
# 5. 审计落盘闩锁单测 (threading.Event Latch)
# ============================================================================

@pytest.mark.anyio
async def test_emit_consultation_audit_idempotent_latch(tmp_path: Path):
    """断言 _emit_consultation_audit 在同一 Event 闩锁下多次调用仅落盘一次。"""
    log_dir = tmp_path / "reviewer_logs"
    latch = threading.Event()

    messages = [{"role": "user", "content": "hello"}]
    usage = {"prompt_tokens": 100, "prompt_cache_hit_tokens": 80}

    # 第一次调用
    await _emit_consultation_audit(
        latch=latch,
        log_dir=log_dir,
        session_id="test_sess_01",
        mode="critique",
        messages=messages,
        usage=usage,
        status="ok",
        has_need_files=False,
    )
    assert latch.is_set()

    # 第二次调用（模拟降级回退或重复调用）
    await _emit_consultation_audit(
        latch=latch,
        log_dir=log_dir,
        session_id="test_sess_01",
        mode="critique",
        messages=messages,
        usage=usage,
        status="fallback",
        has_need_files=True,
    )

    # 校验 cache_telemetry.jsonl 仅有 1 行
    t_file = log_dir / "cache_telemetry.jsonl"
    v_file = log_dir / "verdicts.jsonl"

    assert t_file.is_file()
    assert v_file.is_file()

    t_lines = [l for l in t_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    v_lines = [l for l in v_file.read_text(encoding="utf-8").splitlines() if l.strip()]

    assert len(t_lines) == 1
    assert len(v_lines) == 1
    t_record = json.loads(t_lines[0])
    assert t_record["session_id"] == "test_sess_01"
    assert t_record["mode"] == "critique"
    v_record = json.loads(v_lines[0])
    assert v_record["payload"]["status"] == "ok"  # 第一次写入的状态



# ============================================================================
# 6. 多跳原生多轮与 ReviewerBadRequestError (400/422) 幂等回退单测
# ============================================================================

class MultiHopFakeReviewerClient:
    """协议中立的假 Reviewer 客户端，支持多轮 stream_chat 与异常注入。"""

    def __init__(self, turns: list[list[StreamChunk] | Exception]):
        self._turns = list(turns)
        self.call_history: list[list[dict[str, Any]]] = []
        self.provider_label = "generic-mock"

    def is_available(self) -> bool:
        return True

    def resolve_api_key(self) -> str:
        return "mock-key"

    async def stream_chat(self, messages: Any, *, session_id: Optional[str] = None):
        self.call_history.append(list(messages))
        if not self._turns:
            yield StreamChunk(text="Default fallback content")
            return
        turn_item = self._turns.pop(0)
        if isinstance(turn_item, Exception):
            raise turn_item
        for chunk in turn_item:
            yield chunk


@pytest.mark.anyio
async def test_run_consultation_multihop_turn_and_bad_request_fallback(tmp_path: Path, monkeypatch):
    """断言多跳中 Turn 2 发生 ReviewerBadRequestError (400) 时优雅降级为 Turn 1 单轮交付且无多余落盘。"""
    ws = tmp_path / "workspace"
    ws.mkdir()
    code_file = ws / "target.py"
    code_file.write_text("print('hello target file')\n", encoding="utf-8")

    # 配置 25 条历史遥测保证门控开放 (>30%)
    log_dir = ws / ".agents" / "logs" / "reviewer"
    log_dir.mkdir(parents=True)
    t_file = log_dir / "cache_telemetry.jsonl"
    t_file.write_text(
        "\n".join(json.dumps({"demand": True}) for _ in range(25)) + "\n",
        encoding="utf-8",
    )

    # 准备响应序列：
    # Turn 1 响应含 <<<NEED-FILES>>> target.py:1-1 <<<END>>>，并携带 reasoning
    turn1_chunks = [
        StreamChunk(text="", reasoning="Thinking about dependencies..."),
        StreamChunk(
            text="Need more details:\n<<<NEED-FILES>>> target.py:1-1 <<<END>>>\nFirst impression looks okay.",
            reasoning="",
            usage=UsageSnapshot(prompt_tokens=150, completion_tokens=40, cached_tokens=100),
        ),
    ]
    # Turn 2 抛出 ReviewerBadRequestError (HTTP 400 非正文思维链回灌)
    turn2_err = ReviewerBadRequestError(
        "Upstream provider rejected reasoning history in multi-turn request"
    )

    fake_client = MultiHopFakeReviewerClient([turn1_chunks, turn2_err])
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    req = ConsultRequest(
        workspace_root=str(ws),
        query="Analyze the target code",
        mode="critique",
        session_id="sess_fallback_test",
        max_hops=2,
    )
    cfg = QuenchStackConfig(
        workspace_root=str(ws),
        project_name="test_proj",
        reviewer_engine=ReviewerEngineConfig(
            provider="mock-prov",
            model="mock-model",
            timeout_seconds=10,
        )
    )

    res = await run_consultation(req, config=cfg)

    # 断言降级逻辑生效：
    # 1. 状态为 ok，未崩溃上抛
    assert res.status == "ok"
    # 2. 返回内容保留了 Turn 1 的分析结果
    assert "First impression looks okay" in res.findings
    # 3. 客户端确实被调用了两次（Turn 1 + Turn 2）
    assert len(fake_client.call_history) == 2
    # 4. Turn 2 的 messages 中，Assistant 消息不含 reasoning 属性
    turn2_messages = fake_client.call_history[1]
    assistant_msgs = [m for m in turn2_messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) >= 1
    assert "reasoning_content" not in assistant_msgs[0]
    assert "thought" not in assistant_msgs[0]

    # 5. 验证审计日志仅有一条落盘（落盘闩锁保证单次落盘）
    t_lines = [l for l in t_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    # 原有 25 条预置记录 + 1 条本次咨询落盘
    assert len(t_lines) == 26
    last_record = json.loads(t_lines[-1])
    assert last_record["session_id"] == "sess_fallback_test"
    assert last_record["mode"] == "critique"
    v_lines = [l for l in (log_dir / "verdicts.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(v_lines) == 1
    v_last = json.loads(v_lines[-1])
    assert v_last["payload"]["status"] == "ok"



@pytest.mark.anyio
async def test_run_consultation_multihop_successful_two_turns(tmp_path: Path, monkeypatch):
    """断言两轮多跳成功交互，HopBudget 正确扣减并在第二轮注入增量代码切片。"""
    ws = tmp_path / "workspace"
    ws.mkdir()
    code_file = ws / "helper.py"
    code_file.write_text("def helper(): return 'done'\n", encoding="utf-8")

    # 配置 25 条历史遥测保证门控开放
    log_dir = ws / ".agents" / "logs" / "reviewer"
    log_dir.mkdir(parents=True)
    t_file = log_dir / "cache_telemetry.jsonl"
    t_file.write_text(
        "\n".join(json.dumps({"demand": True}) for _ in range(25)) + "\n",
        encoding="utf-8",
    )

    turn1_chunks = [
        StreamChunk(
            text="I need more code:\n<<<NEED-FILES>>> helper.py:1-1 <<<END>>>",
            usage=UsageSnapshot(prompt_tokens=100, completion_tokens=30, cached_tokens=50),
        )
    ]
    turn2_chunks = [
        StreamChunk(
            text="Analysis complete. Helper is safe.",
            usage=UsageSnapshot(prompt_tokens=140, completion_tokens=20, cached_tokens=100),
        )
    ]

    fake_client = MultiHopFakeReviewerClient([turn1_chunks, turn2_chunks])
    monkeypatch.setattr("consultation.create_reviewer_client", lambda cfg, sink=None: fake_client)

    req = ConsultRequest(
        workspace_root=str(ws),
        query="Check helper",
        mode="critique",
        session_id="sess_two_turns",
        max_hops=2,
    )
    cfg = QuenchStackConfig(
        workspace_root=str(ws),
        project_name="test_proj",
        reviewer_engine=ReviewerEngineConfig(
            provider="mock-prov",
            model="mock-model",
            timeout_seconds=10,
        )
    )

    res = await run_consultation(req, config=cfg)

    assert res.status == "ok"
    assert "Analysis complete. Helper is safe." in res.findings
    assert len(fake_client.call_history) == 2

    # 检查第二轮的消息结构：包含 Turn 1 Assistant 消息和 Turn 2 User 增量切片消息
    turn2_messages = fake_client.call_history[1]
    assert any("Additional Injected Code Context Slices" in str(m.get("content")) for m in turn2_messages)
    assert any("def helper(): return 'done'" in str(m.get("content")) for m in turn2_messages)
