import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.intention_agent import _fast_match
from agents.orchestration_agent import OrchestrationAgent
from utils.as_compat import mk_msg, msg_json
from utils.weather_intent import asks_about_clothing


def load_information_agent():
    path = Path(__file__).resolve().parents[1] / ".claude/skills/query-info/script/agent.py"
    spec = importlib.util.spec_from_file_location("composite_info_skill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.InformationQueryAgent


@pytest.mark.parametrize("query,place", [
    ("看看北京的住宿和现在穿什么衣服合适", "hotel_search"),
    ("北京酒店推荐，再看看气温", "hotel_search"),
    ("上海美食推荐和现在穿什么衣服合适", "restaurant_search"),
])
def test_place_request_also_schedules_weather(query, place):
    intention = _fast_match(query)
    assert intention is not None
    agents = [x["agent_name"] for x in intention["agent_schedule"]]
    assert set(agents) == {place, "information_query"}
    assert len(agents) == 2
    assert intention["rewritten_query"] == query


def test_expense_fast_route_cannot_swallow_weather():
    assert _fast_match("记一笔打车50元，同时查北京天气") is None


def test_hotel_only_does_not_trigger_weather():
    result = _fast_match("北京住宿推荐")
    assert [x["agent_name"] for x in result["agent_schedule"]] == ["hotel_search"]


def test_fashion_request_not_automatically_weather():
    assert not asks_about_clothing("婚礼穿什么衣服合适")


@pytest.mark.parametrize("temp,expected", [("0", "厚外套"), ("12", "毛衣"), ("20", "薄外套"), ("30", "轻薄"), ("?", "无法可靠判断"), ("nan", "无法可靠判断")])
def test_clothing_advice_uses_observed_temperature(temp, expected):
    assert expected in load_information_agent()._clothing_advice(temp, "5")


@pytest.mark.asyncio
async def test_composite_request_returns_stay_and_weather_clothing(monkeypatch):
    import config

    monkeypatch.setattr(config, "AMAP_CONFIG", {"api_key": "test-only"})

    async def fake_amap(url, params):
        if params["extensions"] == "base":
            data = {"status": "1", "lives": [{"temperature": "8", "weather": "晴", "reporttime": "2026-11-18 14:00:00"}]}
        else:
            data = {"status": "1", "forecasts": [{"casts": [{"date": "2026-11-18", "daytemp": "10", "nighttemp": "0", "dayweather": "晴", "nightweather": "晴"}]}]}
        return data

    weather = load_information_agent()()
    monkeypatch.setitem(weather._weather_query.__globals__, "amap_json", fake_amap)
    weather._web_search = AsyncMock(side_effect=AssertionError("Unexpected network search"))
    hotel = SimpleNamespace(reply=AsyncMock(return_value=mk_msg("hotel", {"hotels": [{"name": "测试酒店"}], "summary": "北京住宿结果"})))
    agent = OrchestrationAgent(agent_registry={"hotel_search": hotel, "information_query": weather})
    intention = _fast_match("看看北京的住宿和现在穿什么衣服合适")
    result = msg_json(await agent.reply(mk_msg("user", intention)))

    assert result["status"] == "completed"
    assert result["agents_executed"] == 2
    by_name = {x["agent_name"]: x for x in result["results"]}
    summary = by_name["information_query"]["data"]["results"]["summary"]
    assert "北京天气" in summary
    assert "穿衣建议" in summary and "毛衣" in summary
    hotel.reply.assert_awaited_once()
