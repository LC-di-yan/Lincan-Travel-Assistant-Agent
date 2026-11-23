"""Slot completion must preserve the user's task across the actual SSE chat pipeline."""
import asyncio
from copy import deepcopy
import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.intention_agent import IntentionAgent, _fast_match
from agents.orchestration_agent import OrchestrationAgent
from context.memory_manager import MemoryManager
from context.session_focus_state import SessionFocusState
from server.models import ChatRequest
from server.utils.clarification import merge_clarification, missing_slots
from utils.as_compat import mk_msg, msg_json
from utils.circuit_breaker import CircuitBreaker
from utils.local_transport import TRANSPORT_ROUTE_QUESTION
from utils.train_intent import build_train_intention, parse_train_date


@pytest.fixture(autouse=True)
def fixed_ticket_clock(monkeypatch):
    import utils.train_intent as ticket_module

    monkeypatch.setattr(ticket_module, "shanghai_now", lambda: datetime(2026, 11, 18, 16, tzinfo=timezone(timedelta(hours=8))))


def test_missing_origin_then_date_never_adds_planning():
    pending = build_train_intention("查去北京的火车票")
    before = deepcopy(pending)
    filled_origin = merge_clarification(pending, "上海")
    assert pending == before
    assert filled_origin["needs_clarification"] is True
    assert filled_origin["fast_train_ticket"] == {"from": "上海", "to": "北京", "date": ""}
    assert filled_origin["fast_event"]["missing_info"] == ["出发日期"]
    assert "上海到北京" in filled_origin["clarification_question"]
    completed = merge_clarification(filled_origin, "明天")
    assert completed["needs_clarification"] is False
    assert [task["agent_name"] for task in completed["agent_schedule"]] == ["train_ticket"]
    assert completed["fast_train_ticket"]["date"] == parse_train_date("明天")
    assert completed["fast_event"]["duration_days"] == 1  # No invented three-day trip.


@pytest.mark.parametrize("answer", ["上海", "从上海出发", "我从上海出发", "上海，明早", "明早从上海出发"])
def test_preserves_route_date_and_filters_while_filling_origin(answer):
    pending = build_train_intention("查明早去北京的高铁")
    completed = merge_clarification(pending, answer)
    assert completed["fast_train_ticket"] == {"from": "上海", "to": "北京", "date": parse_train_date("明早"), "period": "morning", "train_types": ["G"]}
    assert completed["needs_clarification"] is False


def test_legacy_pending_without_fast_event_recovers_ticket_task_only():
    pending = {"intents": [{"type": "train_ticket"}], "key_entities": {"destination": "北京", "date": "2026-11-20"}, "agent_schedule": [], "rewritten_query": "查去北京的火车票", "needs_clarification": True}
    completed = merge_clarification(pending, "上海")
    assert completed["fast_train_ticket"] == {"from": "上海", "to": "北京", "date": "2026-11-20"}
    assert [task["agent_name"] for task in completed["agent_schedule"]] == ["train_ticket"]


def test_legacy_ticket_parameters_are_used_when_missing_info_is_empty():
    pending = {"intents": [{"type": "train_ticket"}], "fast_train_ticket": {"to": "北京", "date": "2026-11-20", "period": "evening"}, "agent_schedule": [], "rewritten_query": "查去北京的火车票"}
    assert missing_slots(pending) == ["出发地"]
    result = merge_clarification(pending, "上海")
    assert result["fast_train_ticket"] == {"from": "上海", "to": "北京", "date": "2026-11-20", "period": "evening"}


def test_date_answer_does_not_fill_city_and_one_city_does_not_fill_both_ends():
    pending = build_train_intention("查火车票")
    with_date = merge_clarification(pending, "明天")
    assert with_date["fast_train_ticket"]["from"] == ""
    assert with_date["fast_train_ticket"]["to"] == ""
    with_city = merge_clarification(with_date, "北京")
    assert with_city["fast_train_ticket"]["to"] == "北京"
    assert with_city["fast_train_ticket"]["from"] == ""


def test_explicit_route_answer_can_fill_two_location_slots():
    result = merge_clarification(build_train_intention("查明天火车票"), "从上海到北京")
    assert result["fast_train_ticket"]["from"] == "上海"
    assert result["fast_train_ticket"]["to"] == "北京"
    assert not result["needs_clarification"]


@pytest.mark.parametrize("answer", ["北京天气怎么样", "推荐上海酒店", "帮我规划北京行程", "明天，记一笔打车50元", "算了", "你还记得我家在哪吗", "上海和杭州", "三天"])
def test_new_topic_or_nonanswer_does_not_pollute_pending_slots(answer):
    assert merge_clarification(build_train_intention("查去北京的火车票"), answer) is None


def test_explicit_itinerary_request_remains_itinerary_without_unasked_train_task():
    pending = {"intents": [{"type": "itinerary_planning"}], "key_entities": {"destination": "北京"}, "fast_event": {"destination": "北京", "duration_days": 2, "missing_info": ["出发地"]}, "agent_schedule": [], "rewritten_query": "帮我规划去北京的两天行程"}
    result = merge_clarification(pending, "上海")
    assert [task["agent_name"] for task in result["agent_schedule"]] == ["itinerary_planning"]
    assert result["fast_event"]["duration_days"] == 2


def test_original_ticket_schedule_attributes_are_preserved():
    pending = build_train_intention("查去北京的火车票")
    pending["agent_schedule"][0].update({"priority": 5, "reason": "原始原因", "expected_output": "指定格式", "custom": True})
    assert merge_clarification(pending, "上海")["agent_schedule"] == pending["agent_schedule"]


def test_explicit_pair_is_not_written_as_a_single_city():
    result = merge_clarification(build_train_intention("查去北京的火车票"), "上海到北京")
    assert result["fast_train_ticket"]["from"] == "上海"
    assert result["fast_train_ticket"]["to"] == "北京"


@pytest.mark.parametrize("answer", ["待定", "不确定", "还没定", "我不知道"])
def test_uncertain_answer_keeps_question_without_polluting_city(answer):
    result = merge_clarification(build_train_intention("查去北京的火车票"), answer)
    assert result["needs_clarification"] is True
    assert not result["fast_train_ticket"]["from"]


def test_invalid_date_from_legacy_pending_is_not_executed():
    pending = {"intents": [{"type": "train_ticket"}], "key_entities": {"destination": "北京", "date": "2026-02-30"}, "agent_schedule": [], "rewritten_query": "查去北京的火车票"}
    result = merge_clarification(pending, "上海")
    assert result["needs_clarification"] is True
    assert result["fast_train_ticket"]["date"] == ""
    assert "出发日期" in result["fast_event"]["missing_info"]


def test_invalid_date_answer_reasks_without_model_or_city_mutation():
    pending = merge_clarification(build_train_intention("查去北京的火车票"), "上海")
    result = merge_clarification(pending, "2月30日")
    assert result["needs_clarification"] is True
    assert result["fast_train_ticket"] == pending["fast_train_ticket"]


@pytest.mark.asyncio
@pytest.mark.parametrize("initial", ["查去北京的火车票", "查去北京的火车票，我想少换乘"])
async def test_actual_chat_three_turns_preserves_ticket_parameters_with_zero_model_calls(tmp_path, monkeypatch, initial):
    import server.routes.chat as routes
    import agents.intention_agent as intention_module

    model = AsyncMock(side_effect=AssertionError("明确查票及补槽不应调用模型"))
    monkeypatch.setattr(intention_module, "maybe_use_decision", AsyncMock(side_effect=AssertionError("不应等待额外分类器")))
    captured = []

    class FakeTicket:
        async def reply(self, message):
            data = msg_json(message)
            captured.append(data)
            assert data["context"]["original_query"] == initial
            assert data["fast_train_ticket"] == {"from": "上海", "to": "北京", "date": parse_train_date("明天")}
            return mk_msg("train", {"query_success": True, "query_type": "余票查询", "answer": "测试车票结果", "results": {"trains": [{"train_no": "TEST"}]}})

    memory = MemoryManager("clarify_pipeline_test", "s1", storage_path=str(tmp_path), llm_model=model)
    orchestrator = OrchestrationAgent(agent_registry={"train_ticket": FakeTicket()}, memory_manager=memory)
    session = SimpleNamespace(
        session_id="s1", circuit_breaker=CircuitBreaker(), focus_state=SessionFocusState(),
        memory_manager=memory, intention_agent=IntentionAgent(model=model), orchestrator=orchestrator,
        chat_lock=asyncio.Lock(), pending_intention=None, pending_since=0,
        long_term_summary="", messages_since_summary=0,
    )
    monkeypatch.setattr(routes, "session_manager", SimpleNamespace(get_or_create=AsyncMock(return_value=session)))

    async def chat(message):
        response = await routes.chat(ChatRequest(user_id="clarify_pipeline_test", session_id="s1", message=message), current_user="clarify_pipeline_test")
        return [(event["event"], json.loads(event["data"])) async for event in response.body_iterator]

    first = await asyncio.wait_for(chat(initial), 2)
    assert any(kind == "clarification" and "出发" in data["question"] for kind, data in first)
    assert not captured
    pending = session.pending_intention
    echo = await chat(TRANSPORT_ROUTE_QUESTION)
    assert [kind for kind, _ in echo] == ["clarification"]
    assert "不用把问题发回来" in echo[0][1]["question"]
    assert session.pending_intention is pending
    second = await asyncio.wait_for(chat("上海"), 2)
    assert any(kind == "clarification" and "哪天" in data["question"] for kind, data in second)
    assert not captured
    third = await asyncio.wait_for(chat("明天"), 2)
    assert len(captured) == 1
    final = next(data for kind, data in third if kind == "complete")
    assert [result["agent_name"] for result in final["results"]] == ["train_ticket"]
    assert all("itinerary_planning" not in json.dumps(data) for _, data in first + second + third)
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_pending_does_not_reuse_old_route(monkeypatch, tmp_path):
    import server.routes.chat as routes

    model_result = {"intents": [{"type": "information_query"}], "agent_schedule": [], "key_entities": {}}
    intent = SimpleNamespace(reply=AsyncMock(return_value=mk_msg("intent", model_result)))
    session = SimpleNamespace(
        session_id="expired", circuit_breaker=CircuitBreaker(), focus_state=SessionFocusState(),
        memory_manager=MemoryManager("expired_test", "expired", storage_path=str(tmp_path)),
        intention_agent=intent, orchestrator=SimpleNamespace(), chat_lock=asyncio.Lock(),
        pending_intention=build_train_intention("查明天去北京的火车票"), pending_since=-1e12,
        long_term_summary="", messages_since_summary=0,
    )
    monkeypatch.setattr(routes, "session_manager", SimpleNamespace(get_or_create=AsyncMock(return_value=session)))
    response = await routes.chat(ChatRequest(user_id="expired_test", message="上海"), current_user="expired_test")
    _ = [event async for event in response.body_iterator]
    assert session.pending_intention is None
    intent.reply.assert_awaited_once()
