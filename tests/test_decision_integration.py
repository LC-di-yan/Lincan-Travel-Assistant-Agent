"""决策层与 IntentionAgent 的接线测试（不联网、不需要真实 LLM）。

背景：项目 pin 的 agentscope==1.0.16 提供 AgentBase，而本机装的是 2.0.8（没有该类），
所以这里在导入 intention_agent 之前注入最小 stub，让接线逻辑可被单独验证。

覆盖：
    - assist：正则命中酒店，但决策层判为闲聊/非请求 → 否决 → 走 LLM
    - shadow：返回原 fast 结果不变，只落影子日志
    - primary：无正则命中且决策层高置信 → 直通，不调用 LLM
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

# ── agentscope stub（仅当真实版本缺 AgentBase 时）────────────────
try:
    from agentscope.agent import AgentBase as _AB  # noqa: F401
except Exception:  # noqa: BLE001
    _as = types.ModuleType("agentscope")
    _agent = types.ModuleType("agentscope.agent")
    _msg = types.ModuleType("agentscope.message")

    class AgentBase:  # noqa: D401
        def __init__(self, *a, **k):
            pass

    class Msg:
        def __init__(self, name="", content="", role="assistant", **k):
            self.name, self.content, self.role = name, content, role

    _agent.AgentBase = AgentBase
    _msg.Msg = Msg
    _as.agent, _as.message = _agent, _msg
    sys.modules.update({"agentscope": _as, "agentscope.agent": _agent, "agentscope.message": _msg})

from agents.intention_agent import IntentionAgent  # noqa: E402
from agentscope.message import Msg  # noqa: E402
from utils import decision_router as dr  # noqa: E402
from utils.decision_engine import DecisionEngine  # noqa: E402
from utils.decision_types import RouteDecision  # noqa: E402


class _Resp:
    def __init__(self, text: str):
        self.text = text


class FakeEngine(DecisionEngine):
    def __init__(self, mode: str, decision: RouteDecision | None = None):
        super().__init__(api_key="sk-test-000000", mode=mode)
        self._decision = decision
        self.logged = []

    async def route(self, query, history=None, entities=None):
        return self._decision

    def log(self, record):
        self.logged.append(record)


LLM_JSON = json.dumps({
    "reasoning": "LLM 兜底",
    "intents": [{"type": "information_query", "confidence": 0.6, "description": "查询", "reason": "llm"}],
    "key_entities": {},
    "fast_event": {},
    "rewritten_query": "x",
    "needs_clarification": False,
    "clarification_question": "",
    "agent_schedule": [{"agent_name": "information_query", "priority": 1,
                        "reason": "llm", "expected_output": "结果"}],
}, ensure_ascii=False)


def _user(text: str):
    return [Msg(name="user", content=text, role="user")]


@pytest.fixture(autouse=True)
def _clean():
    dr._pending.clear()
    yield
    dr._pending.clear()


async def test_assist_vetoes_hotel_hit_and_falls_back_to_llm(monkeypatch):
    decision = RouteDecision(intent="chitchat", p_intent=0.93,
                             intent_probs={"chitchat": 0.93, "hotel_search": 0.02},
                             is_request=False, p_is_request=0.2)
    engine = FakeEngine("assist", decision)
    monkeypatch.setattr(dr, "get_engine", lambda: engine)

    async def fake_model(messages, **kwargs):
        return _Resp(LLM_JSON)

    agent = IntentionAgent(model=fake_model)
    out = await agent.reply(_user("帮我推荐北京酒店"))

    payload = json.loads(out.content)
    assert payload["agent_schedule"][0]["agent_name"] == "information_query"   # 走了 LLM
    kinds = [r.kind for r in engine.logged]
    assert "decision" in kinds and "outcome" in kinds
    assert [r for r in engine.logged if r.kind == "outcome"][0].final_path == "llm"


async def test_shadow_mode_returns_fast_result_unchanged(monkeypatch):
    decision = RouteDecision(intent="chitchat", p_intent=0.9, is_request=False, p_is_request=0.2)
    engine = FakeEngine("shadow", decision)
    monkeypatch.setattr(dr, "get_engine", lambda: engine)

    called = {"llm": False}

    async def fake_model(messages, **kwargs):  # pragma: no cover - 不应被调用
        called["llm"] = True
        return _Resp(LLM_JSON)

    agent = IntentionAgent(model=fake_model)
    out = await agent.reply(_user("帮我推荐北京酒店"))

    payload = json.loads(out.content)
    assert payload["agent_schedule"][0]["agent_name"] == "hotel_search"
    assert called["llm"] is False
    await asyncio.sleep(0)      # 让 shadow 任务完成
    assert any(r.kind == "decision" for r in engine.logged)


async def test_primary_rescues_translation_without_calling_llm(monkeypatch):
    decision = RouteDecision(intent="translation", p_intent=0.95,
                             intent_probs={"translation": 0.95}, is_request=False, p_is_request=0.09)
    engine = FakeEngine("primary", decision)
    monkeypatch.setattr(dr, "get_engine", lambda: engine)
    # 固定成"正则不命中"的输入，专门验证直通路径
    import agents.intention_agent as ia
    monkeypatch.setattr(ia, "_fast_match", lambda q, dialogue_history=None: None)

    async def boom(messages, **kwargs):  # pragma: no cover
        raise AssertionError("primary 直通不应调用 LLM")

    agent = IntentionAgent(model=boom)
    out = await agent.reply(_user("把这句话翻译成俄语"))

    payload = json.loads(out.content)
    assert payload["agent_schedule"][0]["agent_name"] == "translation"
    assert payload["intents"][0]["confidence"] == pytest.approx(0.95)


async def test_off_mode_keeps_everything_untouched(monkeypatch):
    monkeypatch.setattr(dr, "get_engine", lambda: None)

    async def fake_model(messages, **kwargs):  # pragma: no cover
        raise AssertionError("off 模式不应改变行为")

    agent = IntentionAgent(model=fake_model)
    out = await agent.reply(_user("帮我推荐北京酒店"))
    assert json.loads(out.content)["agent_schedule"][0]["agent_name"] == "hotel_search"
