"""Offline full-pipeline checks for requests that must not call a language model."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import time

import pytest

from agents.intention_agent import IntentionAgent, _fast_match, _extract_currency
from agents.orchestration_agent import OrchestrationAgent
from context.memory_manager import MemoryManager
from utils.as_compat import mk_msg, msg_json
from utils.currency_parser import parse_currency
from utils.preference_parser import parse_preference

ROOT = Path(__file__).resolve().parents[1]


def skill(name):
    spec = importlib.util.spec_from_file_location("deterministic_" + name.replace("-", "_"), ROOT / ".claude/skills" / name / "script/agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("query,src,dst,amount", [
    ("换算100美元为人民币", "USD", "CNY", 100),
    ("请将100美元兑换为人民币", "USD", "CNY", 100),
    ("100美元多少人民币", "USD", "CNY", 100),
    ("请帮我换算100美元兑换人民币", "USD", "CNY", 100),
    ("1,000.50 USD换算成CNY", "USD", "CNY", 1000.5),
    ("50港币等于多少人民币", "HKD", "CNY", 50),
    ("100人民币换人民币", "CNY", "CNY", 100),
    ("0.5美元是多少人民币", "USD", "CNY", .5),
    ("美元兑人民币汇率是多少", "USD", "CNY", 1),
    ("日元汇率", "JPY", "CNY", 1),
    ("usd/cny", "USD", "CNY", 1),
    ("请把100美元换成人民币", "USD", "CNY", 100),
    (".5美元多少人民币", "USD", "CNY", .5),
    (".25美元兑人民币", "USD", "CNY", .25),
    ("100美元能换多少人民币", "USD", "CNY", 100),
])
def test_currency_parser_shared_with_routing(query, src, dst, amount):
    assert parse_currency(query) == _extract_currency(query) == {"from_currency": src, "to_currency": dst, "amount": amount}
    assert _fast_match(query)["fast_currency"] == parse_currency(query)


@pytest.mark.parametrize("query", [
    "换算100美元为人民币，再给我推荐酒店", "100美元为人民币预算",
    "100元换酒店", "100美元多少人民币，另外查北京天气", "100美元兑人民币和欧元",
    "-100美元多少人民币", "1,00美元换人民币", "100美元在北京住什么酒店", "人民币跌了",
])
def test_currency_parser_never_accepts_nonconversion_or_mixed_requests(query):
    assert parse_currency(query) is None


@pytest.mark.parametrize("query,kind,value,action", [
    ("我住酒店喜欢汉庭", "hotel_brands", "汉庭", "replace"),
    ("我喜欢住汉庭酒店", "hotel_brands", "汉庭", "replace"),
    ("我还喜欢如家", "hotel_brands", "如家", "append"),
    ("把我的酒店偏好改成全季", "hotel_brands", "全季", "replace"),
    ("我常坐东航", "airlines", "东航", "replace"),
    ("我喜欢靠窗座位", "seat_preference", "靠窗", "replace"),
    ("我搬家到上海了", "home_location", "上海", "replace"),
    ("我出行喜欢地铁", "transportation_preference", "地铁", "replace"),
])
def test_preference_rules_preserve_type_value_and_write_semantics(query, kind, value, action):
    assert parse_preference(query)["preferences"] == [{"type": kind, "value": value, "action": action}]
    assert _fast_match(query)["agent_schedule"][0]["agent_name"] == "preference"


@pytest.mark.parametrize("query", ["我不喜欢汉庭", "我喜欢汉庭吗", "我喜欢汉庭，顺便查天气", "我喜欢住哪里", "帮我推荐汉庭酒店", "删除酒店偏好", "我喜欢汉庭和如家", "我住在上海想查天气", "我住在上海想订酒店", "我家在北京但是要去上海出差"])
def test_preference_rules_do_not_mutate_uncertain_statements(query):
    assert parse_preference(query) is None


@pytest.mark.parametrize("query", ["北京未来3天天气", "北京未来三天的天气", "查看出差记录", "查看我的行程历史", "查看我的交通偏好"])
def test_duration_and_trip_words_do_not_force_simple_reads_through_model(query):
    assert _fast_match(query) is not None


def test_future_followup_preserves_city_and_time_range():
    result = _fast_match("未来3天的天气", ["用户: 查一下北京天气", "助手: 北京天气晴"])
    assert result["key_entities"]["destination"] == "北京"
    assert "未来3天" in result["rewritten_query"]


@pytest.mark.parametrize("query", ["查询差旅记录，100美元多少人民币", "查询差旅记录和北京的酒店", "查询出差记录并记一笔打车50元"])
def test_mixed_requests_are_not_swallowed_by_memory_early_route(query):
    result = _fast_match(query)
    assert result is None or len(result["agent_schedule"]) > 1


@pytest.mark.asyncio
async def test_full_pipeline_currency_memory_and_preferences_make_zero_model_calls(monkeypatch, tmp_path):
    import agents.intention_agent as intention_module
    from contextlib import asynccontextmanager

    model = AsyncMock(side_effect=AssertionError("确定性操作不得调用模型"))
    decision = AsyncMock(side_effect=AssertionError("确定性操作不得等待二级分类器"))
    monkeypatch.setattr(intention_module, "maybe_use_decision", decision)
    memory = MemoryManager("local_fast_test", "session1", storage_path=str(tmp_path), llm_model=model)
    memory.long_term.save_trip_history({"origin": "测试甲城", "destination": "测试乙城", "start_date": "2026-11-19", "end_date": "2026-11-21", "purpose": "出差"})
    currency = skill("currency-converter")
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"date": "2026-11-18", "rates": {"CNY": 7.1}})
    fetch = AsyncMock(return_value=response)

    @asynccontextmanager
    async def fake_client(*args, **kwargs):
        yield SimpleNamespace(get=fetch)

    monkeypatch.setattr(currency, "provider_client", fake_client)
    registry = {
        "currency_conversion": currency.CurrencyConverterAgent(model=model),
        "preference": skill("preference").PreferenceAgent(model=model, memory_manager=memory),
        "memory_query": skill("memory-query").MemoryQueryAgent(model=model, memory_manager=memory),
    }
    orchestrator = OrchestrationAgent(agent_registry=registry, memory_manager=memory)
    intent = IntentionAgent(model=model)
    elapsed = []
    for query in ["100美元多少人民币", "200美元多少人民币", "我住酒店喜欢汉庭", "我还喜欢如家", "查询差旅记录", "查看我的偏好"]:
        start = time.monotonic()
        routed = await intent.reply(mk_msg("user", query, role="user"))
        result = msg_json(await orchestrator.reply(routed))
        elapsed.append(time.monotonic() - start)
        assert result["status"] == "completed"
        assert result["results"][0]["status"] == "success"
        if "美元" in query:
            assert result["results"][0]["data"]["result"] == (710 if query.startswith("100") else 1420)
        if query == "查询差旅记录":
            assert result["results"][0]["data"]["memory_sources"]["used_model"] is False
    assert memory.long_term.get_preference("hotel_brands") == ["汉庭", "如家"]
    model.assert_not_awaited()
    decision.assert_not_awaited()
    assert fetch.call_count == 1
    assert max(elapsed) < 2  # Network is mocked: only actual routing, skills and temporary-file persistence remain.


@pytest.mark.asyncio
async def test_multiple_preference_values_in_one_request_are_not_overwritten(tmp_path):
    memory = MemoryManager("multi_pref_test", "s1", storage_path=str(tmp_path))
    parsed = parse_preference("我喜欢汉庭，我喜欢全季")
    agent = OrchestrationAgent(memory_manager=memory)
    await agent._update_memory({}, [{"agent_name": "preference", "result": {"data": parsed}}])
    assert memory.long_term.get_preference("hotel_brands") == ["汉庭", "全季"]
    assert parse_preference("我喜欢汉庭，把我的酒店偏好改成全季")["preferences"][-1]["action"] == "replace"


async def test_currency_pair_cache_expires_and_identity_conversion_is_offline(monkeypatch):
    from contextlib import asynccontextmanager

    module = skill("currency-converter")
    agent = module.CurrencyConverterAgent()
    clock = [100.0]
    monkeypatch.setattr(module._time, "monotonic", lambda: clock[0])
    fetch = AsyncMock(return_value=SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"date": "2026-11-18", "rates": {"CNY": "7.12345"}}))

    @asynccontextmanager
    async def fake_client(*args, **kwargs):
        yield SimpleNamespace(get=fetch)

    monkeypatch.setattr(module, "provider_client", fake_client)
    assert (await agent._fetch_rate("CNY", "CNY", 0.5))["result"] == .5
    assert (await agent._fetch_rate("CNY", "CNY", 1234567))["answer"].startswith("1234567 人民币 = 1234567.00")
    fetch.assert_not_called()
    assert (await agent._fetch_rate("USD", "CNY", 100))["result"] == 712.35
    assert (await agent._fetch_rate("USD", "CNY", 200))["rate_cached"] is True
    assert fetch.call_count == 1
    clock[0] += module._RATE_TTL + 1
    assert (await agent._fetch_rate("USD", "CNY", 200))["rate_cached"] is False
    assert fetch.call_count == 2
