"""Simple clothing/weather questions must use the same deterministic routing as weather wording."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.intention_agent import IntentionAgent, _fast_match
from agents.orchestration_agent import OrchestrationAgent
from utils.as_compat import mk_msg, msg_json
from utils.weather_range import resolve_weather_range


@pytest.mark.asyncio
async def test_clear_but_complex_preference_skips_intent_model_and_uses_one_extraction_model(monkeypatch):
    import agents.intention_agent as intention_module

    model = AsyncMock(return_value=SimpleNamespace(text='{"has_preferences":true,"preferences":[{"type":"accommodation","value":"安静且靠近地铁","action":"replace"}]}'))
    monkeypatch.setattr(intention_module, "maybe_use_decision", AsyncMock(side_effect=AssertionError("不应多付一次分类")))
    query = "我住宿偏好安静且靠近地铁的酒店"
    intent = IntentionAgent(model=model)
    routed = await intent.reply(mk_msg("user", query, role="user"))
    model.assert_not_awaited()
    path = Path(__file__).resolve().parents[1] / ".claude/skills/preference/script/agent.py"
    spec = importlib.util.spec_from_file_location("complex_preference_skill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    preference = module.PreferenceAgent(model=model)
    result = msg_json(await OrchestrationAgent(agent_registry={"preference": preference}).reply(routed))
    assert result["status"] == "completed"
    model.assert_awaited_once()


@pytest.mark.parametrize("query", [
    "北京现在穿什么衣服合适", "北京穿衣建议", "北京冷不冷", "北京现在多少度",
    "北京冷吗", "北京要不要穿羽绒服", "北京的交通怎么选", "看看北京的天气和交通",
    "请问北京现在穿什么衣服合适", "我想知道北京现在穿什么衣服合适",
    "能不能帮我查一下北京现在多少度", "麻烦你看看北京天气",
])
def test_common_information_expressions_have_no_model_routing_gap(query):
    result = _fast_match(query)
    assert result is not None
    assert result["reasoning"] == "确定性本地解析"
    assert [task["agent_name"] for task in result["agent_schedule"]] == ["information_query"]
    assert result["key_entities"]["destination"] == "北京"


@pytest.mark.parametrize("query", [
    "北京天气和100美元多少人民币", "北京穿衣建议，顺便查去上海的火车票",
    "看看北京天气并翻译hello", "看看北京天气，再记一笔打车50元",
    "我偏好晴天在北京步行", "北京天气和上海的酒店", "查北京天气并写一封邮件",
    "不查北京天气，只查北京酒店", "北京天气怎么样，不需要酒店",
    "北京穿什么衣服，帮我订明天的出租车", "北京天气怎么样，顺便给我讲个笑话",
    "北京天气怎么样，播放一首音乐", "北京天气，帮我打开电脑",
])
def test_information_fast_path_does_not_swallow_other_tasks(query):
    result = _fast_match(query)
    assert result is None or len(result["agent_schedule"]) > 1


def test_clothing_followup_uses_context_without_losing_current_time_scope():
    result = _fast_match("现在穿什么衣服合适", ["用户: 北京天气怎么样", "助手: 北京天气晴"])
    assert result["key_entities"]["destination"] == "北京"
    assert "现在穿什么" in result["rewritten_query"]


def test_clothing_without_city_asks_instead_of_waiting_for_model():
    result = _fast_match("现在穿什么衣服合适")
    assert result["needs_clarification"]
    assert result["fast_event"]["missing_info"] == ["目的地"]


def test_simple_weather_and_nearby_hotel_still_keeps_both_tasks():
    result = _fast_match("我想看看北京天气和附近酒店")
    assert {task["agent_name"] for task in result["agent_schedule"]} == {"information_query", "hotel_search"}


@pytest.mark.parametrize("query", ["北京现在穿什么衣服合适", "北京穿衣建议", "北京当前气温", "北京实时天气"])
def test_current_or_clothing_question_does_not_proactively_include_other_days(query):
    requested = resolve_weather_range(query)
    assert requested.start == requested.today == requested.end


def test_relative_weather_label_does_not_repeat_synonyms():
    assert resolve_weather_range("北京今天天气").label == "今天"
    assert resolve_weather_range("北京明日天气").label == "明天"


@pytest.mark.asyncio
async def test_full_pipeline_for_exact_clothing_question_never_calls_model(monkeypatch):
    import agents.intention_agent as intention_module

    now = datetime(2026, 11, 18, 17, 28, tzinfo=timezone(timedelta(hours=8)))
    path = Path(__file__).resolve().parents[1] / ".claude/skills/query-info/script/agent.py"
    spec = importlib.util.spec_from_file_location("current_clothing_skill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "shanghai_now", lambda: now)
    model = AsyncMock(side_effect=AssertionError("简单穿衣问题不得调用模型"))
    monkeypatch.setattr(intention_module, "maybe_use_decision", AsyncMock(side_effect=AssertionError("不应等辅助分类器")))
    info = module.InformationQueryAgent(model=model)
    current = {"temperature": "6", "weather": "晴", "humidity": "22", "winddirection": "西", "windpower": "5", "reporttime": "2026-11-18 17:00:00"}
    casts = [{"date": (now.date() + timedelta(days=i)).isoformat(), "dayweather": "晴", "nightweather": "多云", "daytemp": "7", "nighttemp": "-2"} for i in range(4)]
    async def fetched(query):
        return info._build_weather_result("北京", current, casts, query)
    info._weather_query = AsyncMock(side_effect=fetched)
    intent = IntentionAgent(model=model)
    routed = await intent.reply(mk_msg("user", "北京现在穿什么衣服合适", role="user"))
    result = msg_json(await OrchestrationAgent(agent_registry={"information_query": info}).reply(routed))
    data = result["results"][0]["data"]["results"]
    assert result["status"] == "completed"
    assert len(data["forecast"]) == len(data["advice"]) == 1
    assert data["advice"][0]["date_iso"] == "2026-11-18"
    assert "外套" in data["advice"][0]["clothing_advice"]
    assert data["presentation_version"] == 2
    assert data["current"]["observed_at"] == "2026-11-18 17:00:00"
    assert "明天" not in data["summary"] and "后天" not in data["summary"]
    model.assert_not_awaited()
