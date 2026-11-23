"""Offline regressions for date-scoped forecasts and their downstream advice."""
from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils.as_compat import mk_msg, msg_json
from utils.weather_range import SHANGHAI_TZ, resolve_weather_range


TODAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 14, 0, tzinfo=SHANGHAI_TZ)


@pytest.mark.parametrize("query,start,end,current", [
    ("北京天气", "2026-11-18", "2026-11-21", True),
    ("北京今天天气", "2026-11-18", "2026-11-18", True),
    ("北京明天天气", "2026-11-19", "2026-11-19", False),
    ("北京后天天气", "2026-11-20", "2026-11-20", False),
    ("北京大后天天气", "2026-11-21", "2026-11-21", False),
    ("北京未来3天天气", "2026-11-19", "2026-11-21", False),
    ("北京未来三天天气", "2026-11-19", "2026-11-21", False),
    ("北京接下来两天天气", "2026-11-19", "2026-11-20", False),
    ("北京未来一周天气", "2026-11-19", "2026-11-25", False),
    ("北京从明天开始三天天气", "2026-11-19", "2026-11-21", False),
    ("北京从今天起未来3天天气", "2026-11-18", "2026-11-20", True),
    ("北京今明两天天气", "2026-11-18", "2026-11-19", True),
    ("北京下周天气", "2026-11-23", "2026-11-29", False),
    ("北京下周一天气", "2026-11-23", "2026-11-23", False),
    ("北京周五天气", "2026-11-20", "2026-11-20", False),
    ("北京周末天气", "2026-11-21", "2026-11-22", False),
    ("北京下个月天气", "2026-12-01", "2026-12-31", False),
    ("北京2026-11-20天气", "2026-11-20", "2026-11-20", False),
    ("北京2026/11/20天气", "2026-11-20", "2026-11-20", False),
    ("北京2026年11月20日天气", "2026-11-20", "2026-11-20", False),
    ("北京11月20日至22日天气", "2026-11-20", "2026-11-22", False),
    ("北京11月20日到11月22日天气", "2026-11-20", "2026-11-22", False),
    ("北京12月31日至1月2日天气", "2026-12-31", "2027-01-02", False),
    ("北京20号天气", "2026-11-20", "2026-11-20", False),
    ("北京2号天气", "2026-12-02", "2026-12-02", False),
    ("北京未来3日天气", "2026-11-19", "2026-11-21", False),
    ("北京接下来的一周天气", "2026-11-19", "2026-11-25", False),
])
def test_weather_range_resolves_requested_calendar_dates(query, start, end, current):
    requested = resolve_weather_range(query, now=NOW)
    assert requested.start.isoformat() == start
    assert requested.end.isoformat() == end
    assert requested.include_current is current
    assert not requested.error


def test_relative_dates_use_shanghai_instead_of_utc_date():
    utc_now = datetime(2026, 11, 18, 16, 30, tzinfo=timezone.utc)
    requested = resolve_weather_range("北京未来3天天气", now=utc_now)
    assert requested.today == date(2026, 11, 19)
    assert requested.start == date(2026, 11, 20)
    assert requested.end == date(2026, 11, 22)


@pytest.mark.parametrize("query", ["北京2026年2月30日天气", "北京未来0天天气", "北京未来999999天天气", "北京2026-11-22到2026-11-20天气"])
def test_invalid_date_request_never_silently_selects_current_weather(query):
    requested = resolve_weather_range(query, now=NOW)
    assert requested.error
    assert not requested.include_current


@pytest.fixture
def weather_agent(monkeypatch):
    import utils.weather_range as range_module

    monkeypatch.setattr(range_module, "shanghai_now", lambda: NOW)
    path = Path(__file__).resolve().parents[1] / ".claude/skills/query-info/script/agent.py"
    spec = importlib.util.spec_from_file_location("date_scoped_info_skill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "shanghai_now", lambda: NOW)
    agent = module.InformationQueryAgent()
    agent._web_search = AsyncMock(side_effect=AssertionError("Unexpected network search"))
    return agent


@pytest.fixture
def weather_data():
    current = {"temperature": "39", "weather": "今日独有实况", "humidity": "1", "winddirection": "西", "windpower": "8"}
    casts = []
    for offset, (high, low, weather) in enumerate([("39", "35", "今日独有预报"), ("12", "3", "小雨"), ("19", "13", "多云"), ("25", "20", "晴")]):
        casts.append({"date": (TODAY + timedelta(days=offset)).isoformat(), "daytemp": high, "nighttemp": low, "dayweather": weather, "nightweather": weather})
    return current, casts


def test_future_three_days_exclude_today_from_summary_and_structured_data(weather_agent, weather_data):
    current, casts = weather_data
    result = weather_agent._build_weather_result("北京", current, casts, "北京未来3天天气")
    data = result["results"]
    assert result["query_success"] is True
    assert [day["date_iso"] for day in data["forecast"]] == ["2026-11-19", "2026-11-20", "2026-11-21"]
    assert "current" not in data
    assert "今日独有" not in data["summary"]
    assert "当前实况" not in data["summary"] and "今日全天预报" not in data["summary"]
    assert "39℃" not in data["summary"]
    assert "3~12℃" in data["summary"]


@pytest.mark.parametrize("query,expected", [("北京明天天气", "2026-11-19"), ("北京后天天气", "2026-11-20"), ("北京11月21日天气", "2026-11-21")])
def test_one_day_request_only_returns_that_actual_date(weather_agent, weather_data, query, expected):
    current, casts = weather_data
    result = weather_agent._build_weather_result("北京", current, list(reversed(casts)), query)
    assert [day["date_iso"] for day in result["results"]["forecast"]] == [expected]
    assert "current" not in result["results"]


def test_future_seven_days_returns_only_available_three_and_explains_limit(weather_agent, weather_data):
    result = weather_agent._build_weather_result("北京", *weather_data, "北京未来7天天气")
    data = result["results"]
    assert len(data["forecast"]) == 3
    assert data["partial"] is True
    assert "4 日预报" in data["summary"] and "超出可用范围" in data["summary"]
    assert "今日独有" not in data["summary"]
    assert data["requested_range"]["end_date"] == "2026-11-25"
    assert data["forecast_limit"]["end_date"] == "2026-11-21"


def test_out_of_range_date_returns_no_fabricated_current_or_forecast(weather_agent, weather_data):
    result = weather_agent._build_weather_result("北京", *weather_data, "北京11月25日天气和穿衣建议")
    data = result["results"]
    assert result["query_success"] is False
    assert data["forecast"] == [] and "current" not in data
    assert "超出可用范围" in data["summary"]
    assert "暂不能可靠判断衣物厚度" in data["summary"]
    assert "今日独有" not in data["summary"] and "39℃" not in data["summary"]


def test_missing_day_is_not_replaced_or_renamed_by_response_position(weather_agent, weather_data):
    current, casts = weather_data
    casts = [casts[0], casts[2], {**casts[1], "date": "not-a-date"}, {**casts[1], "date": "2026-11-17"}]
    result = weather_agent._build_weather_result("北京", current, casts, "北京明天天气")
    assert result["query_success"] is False
    assert result["results"]["forecast"] == []
    assert "缺失日期" in result["results"]["summary"]


def test_forecast_clothing_uses_requested_day_not_current_heat(weather_agent, weather_data):
    result = weather_agent._build_weather_result("北京", *weather_data, "北京明天天气和穿衣建议")
    summary = result["results"]["summary"]
    assert "毛衣" in summary and "基于预报" in summary
    assert "轻薄透气" not in summary and "防暑" not in summary


def test_forecast_transport_never_uses_current_cold_wind_or_weather(weather_agent, weather_data):
    current, casts = weather_data
    current.update(temperature="-30", weather="暴雪")
    query = "北京明天天气、穿衣建议和交通推荐"
    result = weather_agent._build_weather_result("北京", current, casts, query)
    weather_agent._append_transport_advice(result, query)
    summary = result["results"]["summary"]
    assert "北京交通推荐" in summary and "结合所查日期预报" in summary
    assert "当前气温" not in summary and "当前风力偏大" not in summary
    assert "暴雪" not in summary and "-30" not in summary


def test_today_only_retains_current_but_does_not_include_other_dates(weather_agent, weather_data):
    result = weather_agent._build_weather_result("北京", *weather_data, "北京今天天气")
    assert result["results"]["current"]["temp"] == "39"
    assert [day["date_iso"] for day in result["results"]["forecast"]] == ["2026-11-18"]
    assert "当前实况" in result["results"]["summary"]


@pytest.mark.asyncio
async def test_future_weather_fetches_forecast_only_without_current_dependency(weather_agent, weather_data, monkeypatch):
    monkeypatch.setitem(sys.modules, "config", SimpleNamespace(AMAP_CONFIG={"api_key": "offline-test"}))
    calls = []

    async def fake_amap(url, params):
        calls.append(url)
        assert params["extensions"] == "all"
        return {"status": "1", "forecasts": [{"casts": weather_data[1]}]}

    monkeypatch.setitem(weather_agent._weather_query.__globals__, "amap_json", fake_amap)
    result = await weather_agent._weather_query("北京未来3天天气")
    assert len(calls) == 1
    assert len(result["results"]["forecast"]) == 3
    assert "current" not in result["results"]


@pytest.mark.asyncio
async def test_wholly_unavailable_date_does_not_call_weather_api(weather_agent, monkeypatch):
    async def unexpected_amap(*args, **kwargs):
        raise AssertionError("An unavailable forecast must not need a network request")

    monkeypatch.setitem(weather_agent._weather_query.__globals__, "amap_json", unexpected_amap)
    result = await weather_agent._weather_query("北京11月25日天气")
    assert result["query_success"] is False
    assert "超出可用范围" in result["results"]["summary"]


@pytest.mark.asyncio
async def test_future_api_failure_does_not_fall_back_to_undated_weather_search(weather_agent):
    weather_agent._weather_query = AsyncMock(side_effect=ValueError("offline failure"))
    result = msg_json(await weather_agent.reply(mk_msg("user", "北京未来3天天气和交通推荐")))
    assert result["query_success"] is False
    assert "可靠预报" in result["results"]["summary"]
    assert "北京交通推荐" in result["results"]["summary"]
    assert result["results"]["forecast"] == []
    weather_agent._web_search.assert_not_awaited()


@pytest.mark.parametrize("query", ["未来3天的天气", "请帮我查一下未来三天的天气", "给我推荐一下未来三天的天气", "麻烦查询未来3天天气", "明天的天气怎么样", "后天穿什么衣服", "下周的天气", "当地未来3天天气", "这里的天气"])
def test_time_and_location_pronouns_are_not_misidentified_as_city(weather_agent, query):
    assert weather_agent._extract_city_from_query(query) == ""


@pytest.mark.parametrize("query,city", [("丽江未来三天天气", "丽江"), ("请问丽江天气", "丽江"), ("三亚未来3天的天气", "三亚"), ("乌鲁木齐后天穿什么", "乌鲁木齐")])
def test_explicit_city_extraction_retains_known_and_geocoded_city_support(weather_agent, query, city):
    assert weather_agent._extract_city_from_query(query) == city


@pytest.mark.parametrize("context", [
    {"key_entities": {"destination": "北京"}},
    {"session_focus": {"focus_city": "北京"}},
    {"session_focus": {"last_search_city": "北京"}},
    {"session_focus": {"current_trip_destination": "北京"}},
    {"key_entities": {"destination": "北京"}, "session_focus": {"focus_city": "上海"}},
])
@pytest.mark.asyncio
async def test_followup_weather_uses_supplied_entity_or_session_city(weather_agent, weather_data, context):
    def fake_weather(query):
        return weather_agent._build_weather_result("北京", *weather_data, query)

    weather_agent._weather_query = AsyncMock(side_effect=fake_weather)
    context["rewritten_query"] = "未来3天的天气"
    result = msg_json(await weather_agent.reply(mk_msg("user", {"context": context})))
    query = weather_agent._weather_query.await_args.args[0]
    assert "北京" in query and "未来3天" in query
    assert result["results"]["city"] == "北京"
    assert [day["date_iso"] for day in result["results"]["forecast"]] == ["2026-11-19", "2026-11-20", "2026-11-21"]
    assert "current" not in result["results"]


@pytest.mark.asyncio
async def test_explicit_weather_city_overrides_stale_session_focus(weather_agent, weather_data):
    weather_agent._weather_query = AsyncMock(return_value=weather_agent._build_weather_result("上海", *weather_data, "上海未来3天天气"))
    await weather_agent.reply(mk_msg("user", {"context": {"rewritten_query": "上海未来3天天气", "key_entities": {"destination": "北京"}, "session_focus": {"focus_city": "北京"}}}))
    assert weather_agent._weather_query.await_args.args[0] == "上海未来3天天气"


@pytest.mark.asyncio
async def test_followup_without_any_city_asks_instead_of_defaulting_or_geocoding_time(weather_agent, monkeypatch):
    async def unexpected_amap(*args, **kwargs):
        raise AssertionError("A missing city must be clarified without network requests")

    monkeypatch.setitem(weather_agent._weather_query.__globals__, "amap_json", unexpected_amap)
    result = msg_json(await weather_agent.reply(mk_msg("user", "未来3天的天气")))
    assert result["query_success"] is False
    assert result["results"]["needs_clarification"] is True
    assert "哪座城市" in result["results"]["summary"]
    assert "北京" not in result["results"]["summary"]
    assert result["results"]["forecast"] == []
    weather_agent._web_search.assert_not_awaited()
