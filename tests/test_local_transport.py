import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agents.intention_agent import _fast_match
from utils.as_compat import mk_msg, msg_json
from utils.local_transport import local_transport_advice, needs_transport_advice


@pytest.fixture
def information_agent():
    path = Path(__file__).resolve().parents[1] / ".claude/skills/query-info/script/agent.py"
    spec = importlib.util.spec_from_file_location("transport_info", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    agent = module.InformationQueryAgent()
    agent._web_search = AsyncMock(side_effect=AssertionError("Unexpected web search"))
    return agent


@pytest.mark.parametrize("city,local_feature", [("北京", "大兴"), ("上海", "浦东"), ("重庆", "高差"), ("杭州", "西湖"), ("深圳", "跨度"), ("成都", "郊区")])
def test_city_specific_guidance(city, local_feature):
    data = local_transport_advice(city, f"{city}交通推荐")
    assert local_feature in data["summary"]
    assert "未查询实时拥堵" in data["summary"]
    assert data["sources"]


def test_transport_adapts_to_observed_cold_and_wind():
    result = local_transport_advice("北京", "北京天气和交通", {"temp": "7", "wind": "西风 5级", "weather": "晴"})
    assert "当前气温约7℃" in result["summary"]
    assert "当前风力偏大" in result["summary"]
    assert "谨慎选择骑行" in result["summary"]


def test_unknown_city_does_not_assert_metro_exists():
    text = local_transport_advice("丽江", "丽江市内交通")["summary"]
    assert "若起终点有便利轨道或公交衔接" in text
    assert "未查询实时拥堵" in text


def test_unknown_weather_does_not_fabricate_cold_or_wind():
    text = local_transport_advice("北京", "北京交通")["summary"]
    assert "当前气温" not in text and "当前风力" not in text


def test_existing_route_endpoints_are_not_requested_again():
    text = local_transport_advice("北京", "从北京南站到国贸交通推荐")["summary"]
    assert "尚未计算" in text
    assert "请告诉我起点" not in text


def test_transport_expense_is_not_mobility_advice():
    assert not needs_transport_advice("交通费报销标准是多少")


def test_hotel_plus_transport_covers_both_needs():
    result = _fast_match("看看北京住宿和市内交通推荐")
    assert {x["agent_name"] for x in result["agent_schedule"]} == {"hotel_search", "information_query"}


@pytest.mark.asyncio
async def test_weather_and_transport_both_answered(information_agent):
    query = "请帮我查一下北京的天气和交通"
    weather = information_agent._build_weather_result("北京", {"temperature": "7", "weather": "晴", "winddirection": "西", "windpower": "5"}, [], query=query)
    information_agent._weather_query = AsyncMock(return_value=weather)
    result = msg_json(await information_agent.reply(mk_msg("user", {"context": {"rewritten_query": query}})))
    summary = result["results"]["summary"]
    assert "北京天气" in summary and "北京交通推荐" in summary
    assert "当前风力偏大" in summary
    assert "交通方式和住宿" not in result["proactive_question"]
    assert "具体起点和终点" in result["proactive_question"]
    assert result["results"]["transport_advice"]["scope"] == "city_guidance"
    from server.utils.assistant_summary import _summarize_information
    assert "交通建议" in _summarize_information(result)


@pytest.mark.asyncio
async def test_transport_only_does_not_require_weather_api(information_agent):
    information_agent._weather_query = AsyncMock(side_effect=AssertionError("Unexpected weather API"))
    result = msg_json(await information_agent.reply(mk_msg("user", "重庆交通推荐")))
    assert "高差" in result["results"]["summary"]
    information_agent._weather_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_city_asks_for_city(information_agent):
    result = msg_json(await information_agent.reply(mk_msg("user", "交通推荐")))
    assert result["query_success"] is False
    assert "请补充" in result["results"]["message"]


@pytest.mark.asyncio
async def test_cross_city_query_is_not_assumed_to_be_first_city(information_agent):
    result = msg_json(await information_agent.reply(mk_msg("user", "从北京到上海交通推荐")))
    text = result["results"]["summary"]
    assert "多个城市" in text
    assert "未计算城际路线" in text
