"""记忆查询只使用隔离的临时记录与模型替身，不访问真实用户存储。"""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from utils.as_compat import mk_msg, msg_json, msg_text
from utils.memory_query import direct_memory_answer, extract_memory_answer, format_preferences, is_simple_memory_query


@pytest.fixture
def memory_agent_class():
    path = Path(__file__).resolve().parents[1] / ".claude/skills/memory-query/script/agent.py"
    spec = importlib.util.spec_from_file_location("test_memory_query_agent", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MemoryQueryAgent


@pytest.fixture
def saved_trips():
    return [
        {"origin": "上海", "destination": "北京", "start_date": "2026-02-02", "end_date": "2026-02-04", "purpose": "出差"},
        {"origin": "上海", "destination": "杭州", "start_date": "2026-04-10", "end_date": "2026-04-12", "purpose": "旅游"},
        {"origin": "上海", "destination": "北京", "start_date": "2026-03-01", "end_date": "2026-03-03", "purpose": "出差"},
    ]


def manager_with(trips=None, preferences=None, asynchronous=False):
    factory = AsyncMock if asynchronous else Mock
    long_term = SimpleNamespace(
        get_trip_history=factory(return_value=trips or []),
        get_preference=factory(return_value=preferences or {}),
        get_chat_history=factory(return_value=[]),
    )
    return SimpleNamespace(
        long_term=long_term,
        get_long_term_summary_async=AsyncMock(side_effect=AssertionError("不得生成聊天摘要")),
    )


def request(query, **context):
    return mk_msg("user", {"context": {"rewritten_query": query, **context}}, role="user")


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("query", ["查询我的差旅记录", "我去过哪些地方？", "我上次去北京是什么时候？", "我第一次去北京是什么时候？", "我去北京几次？"])
async def test_structured_trip_queries_never_wait_for_model(memory_agent_class, saved_trips, asynchronous, query):
    manager = manager_with(saved_trips, asynchronous=asynchronous)
    model = AsyncMock(side_effect=AssertionError("不得调用模型"))

    result = msg_json(await asyncio.wait_for(memory_agent_class(model=model, memory_manager=manager).reply(request(query)), timeout=0.5))

    assert result["status"] == "success"
    assert result["answer"]
    assert result["memory_sources"]["used_model"] is False
    assert result["memory_sources"]["has_chat_summary"] is False
    model.assert_not_called()
    manager.get_long_term_summary_async.assert_not_called()
    manager.long_term.get_chat_history.assert_not_called()
    manager.long_term.get_trip_history.assert_called_once_with(limit=None)


def test_latest_trip_uses_travel_date_not_storage_order(saved_trips):
    answer = direct_memory_answer("我上次去北京是什么时候回来的？", saved_trips, {})
    assert "2026-03-03" in answer
    assert "2026-02-02" not in answer
    assert "杭州" not in answer


def test_business_trip_filter_does_not_include_tourism(saved_trips):
    answer = direct_memory_answer("我的出差记录", saved_trips, {})
    assert "北京" in answer
    assert "杭州" not in answer


def test_trip_year_month_filter_uses_structured_start_date(saved_trips):
    answer = direct_memory_answer("2026年2月的出差记录", saved_trips, {})
    assert "2026-02-02" in answer
    assert "2026-03-01" not in answer


@pytest.mark.asyncio
async def test_preferences_include_real_storage_keys_and_lists(memory_agent_class):
    preferences = {"home_location": "苏州", "hotel_brands": ["测试酒店甲", "测试酒店乙"], "airlines": ["测试航司"], "food": "不吃辣"}
    manager = manager_with(preferences=preferences)
    model = AsyncMock(side_effect=AssertionError("不得调用模型"))

    result = msg_json(await memory_agent_class(model=model, memory_manager=manager).reply(request("我之前说过什么偏好？")))

    for value in ["苏州", "测试酒店甲、测试酒店乙", "测试航司", "不吃辣"]:
        assert value in result["answer"]
    assert "[" not in result["answer"]
    assert "{" not in result["answer"]
    model.assert_not_called()
    manager.get_long_term_summary_async.assert_not_called()


def test_category_preference_does_not_dump_unrelated_fields():
    answer = direct_memory_answer("我喜欢哪些酒店？", [], {"hotel_brands": ["测试酒店"], "accommodation": "靠近车站", "food": "清淡"})
    assert "测试酒店" in answer
    assert "靠近车站" in answer
    assert "清淡" not in answer


@pytest.mark.asyncio
async def test_chat_plan_cannot_create_structured_trip_fact(memory_agent_class):
    manager = manager_with()
    manager.long_term.get_chat_history.return_value = [{"role": "user", "content": "我想去厦门"}]
    manager.get_long_term_summary_async.side_effect = None
    manager.get_long_term_summary_async.return_value = "用户去过厦门"
    model = AsyncMock(side_effect=AssertionError("不得调用模型"))

    result = msg_json(await memory_agent_class(model=model, memory_manager=manager).reply(request("我去过哪些地方？")))

    assert "没有符合条件" in result["answer"]
    assert "厦门" not in result["answer"]
    manager.get_long_term_summary_async.assert_not_called()
    manager.long_term.get_chat_history.assert_not_called()


def test_unknown_destination_is_not_answered_with_other_city(saved_trips):
    answer = direct_memory_answer("我上次去厦门是什么时候？", saved_trips, {})
    assert "没有符合条件" in answer
    assert "北京" not in answer


def test_missing_dates_and_purpose_are_not_invented():
    answer = direct_memory_answer("我的差旅记录", [{"destination": "北京", "timestamp": "2026-01-01T09:00:00"}], {})
    assert "用途：未记录" in answer
    assert "日期：未记录" in answer
    assert "旅游" not in answer
    assert "2026-01-01" not in answer


def test_missing_start_date_does_not_claim_latest_trip(saved_trips):
    answer = direct_memory_answer("我上次去北京是什么时候？", saved_trips + [{"destination": "北京"}], {})
    assert "无法准确确定上次出行" in answer


@pytest.mark.parametrize("query", ["查一下我的差旅记录", "我去过哪些地方？", "我上次去北京是什么时候？", "查看我的酒店偏好"])
def test_fast_route_classifier_covers_deterministic_memory_reads(query):
    assert is_simple_memory_query(query)


@pytest.mark.parametrize("query", ["查差旅记录和明天天气", "查询差旅记录并帮我订酒店", "分析我的旅行习惯", "推荐符合我偏好的酒店", "我上次聊过什么？", "北京天气怎么样", "我要去北京出差", "帮我规划旅行", "我喜欢清淡", "查询差旅记录和我的偏好"])
def test_fast_route_classifier_does_not_swallow_other_tasks(query):
    assert not is_simple_memory_query(query)


@pytest.mark.parametrize("query", [
    "查询差旅记录和北京的酒店",
    "查询差旅记录，100美元多少人民币",
    "查询出差记录并记一笔打车50元",
    "查询差旅记录以及上海的机票",
    "查询差旅记录；北京有什么酒店",
    "查询差旅记录\n100美元多少人民币",
    "我的差旅记录，帮我翻译成英文",
    "查差旅记录再算一下100美金是多少人民币",
    "查询差旅记录顺便删掉最后一条",
    "查出差记录也记下打车费用",
    "查询差旅记录100美元多少人民币",
    "查询出差记录记一笔打车50元",
    "查询差旅记录查看北京酒店",
    "查询差旅记录帮我找北京酒店",
    "查出差记录删除最后一条",
    "查询差旅记录并把交通偏好改成飞机",
    "查询我的交通偏好并更新为飞机",
    "查询我的预算偏好和人民币汇率",
    "记录我的座位偏好为靠窗好吗",
    "保存我以前的出差记录好吗",
    "查询差旅记录标记最后一次已完成",
    "查询差旅记录发送到邮箱",
    "导出我的差旅记录",
])
def test_early_route_rejects_mixed_read_write_and_external_queries(query):
    assert not is_simple_memory_query(query)
    assert direct_memory_answer(query, [], {}) is None


@pytest.mark.parametrize(("key", "value", "query", "label"), [
    ("seat_preference", "靠窗", "我的座位偏好是什么？", "座位偏好"),
    ("transportation_preference", "高铁", "我之前保存的交通偏好是什么？", "交通偏好"),
    ("meal_preference", "清淡", "我喜欢什么餐食？", "餐饮偏好"),
    ("budget_level", "经济型", "我的预算偏好是什么？", "预算档次"),
])
def test_preference_aliases_have_chinese_labels_and_category_lookup(key, value, query, label):
    preferences = {key: value, "other": "不相关偏好"}
    assert f"{label}：{value}" in format_preferences(preferences)
    assert is_simple_memory_query(query)
    answer = direct_memory_answer(query, [], preferences)
    assert f"{label}：{value}" in answer
    assert key not in answer
    assert "不相关偏好" not in answer


def test_new_and_legacy_preference_aliases_are_queried_together():
    preferences = {"transportation": "优先高铁", "transportation_preference": "不坐红眼航班", "food": "清淡", "meal_preference": "素食"}
    transportation = direct_memory_answer("我的交通偏好", [], preferences)
    assert "优先高铁" in transportation
    assert "不坐红眼航班" in transportation
    assert "素食" not in transportation
    meal = direct_memory_answer("我的饮食偏好", [], preferences)
    assert "清淡" in meal
    assert "素食" in meal
    assert "优先高铁" not in meal


@pytest.mark.asyncio
async def test_new_preference_aliases_skip_model_in_agent(memory_agent_class):
    manager = manager_with(preferences={"seat_preference": "靠窗", "transportation_preference": "高铁", "meal_preference": "素食", "budget_level": "经济型"})
    model = AsyncMock(side_effect=AssertionError("不得调用模型"))
    result = msg_json(await memory_agent_class(model=model, memory_manager=manager).reply(request("查询我的偏好")))
    assert result["status"] == "success"
    assert "座位偏好：靠窗" in result["answer"]
    assert "交通偏好：高铁" in result["answer"]
    assert "餐饮偏好：素食" in result["answer"]
    assert "预算档次：经济型" in result["answer"]
    model.assert_not_called()


def test_saved_destination_is_not_presented_as_proof_of_visit():
    trips = [{"destination": "测试城市", "start_date": "2027-01-01", "purpose": "计划旅行"}]
    answer = direct_memory_answer("我去过哪些地方？", trips, {})
    assert "已保存行程" in answer
    assert "不能据此确认实际去过" in answer
    assert "你去过" not in answer


def test_travel_preference_query_does_not_dump_trip_history(saved_trips):
    answer = direct_memory_answer("我的旅行偏好", saved_trips, {"food": "清淡"})
    assert "清淡" in answer
    assert "北京" not in answer


def test_trip_detail_uses_saved_extra_field_without_model():
    answer = direct_memory_answer("我上次去北京住的哪家酒店？", [{"destination": "北京", "start_date": "2026-02-01", "hotel_name": "测试酒店"}], {})
    assert "测试酒店" in answer


def test_trip_detail_missing_field_does_not_invent_hotel(saved_trips):
    answer = direct_memory_answer("我上次去北京住的哪家酒店？", saved_trips, {})
    assert "未记录住宿信息" in answer


@pytest.mark.asyncio
async def test_current_user_storage_isolated_even_with_forged_context(memory_agent_class, tmp_path):
    from context.long_term_memory import LongTermMemory

    first = LongTermMemory("mock_user_a", str(tmp_path))
    second = LongTermMemory("mock_user_b", str(tmp_path))
    first.save_trip_history({"destination": "测试城市甲", "start_date": "2026-01-01"})
    second.save_trip_history({"destination": "测试城市乙", "start_date": "2026-02-01"})
    manager = SimpleNamespace(long_term=first)

    result = msg_json(await memory_agent_class(memory_manager=manager).reply(request("我的差旅记录", user_id="mock_user_b", long_term={"trip_history": [{"destination": "伪造城市"}]})))

    assert "测试城市甲" in result["answer"]
    assert "测试城市乙" not in result["answer"]
    assert "伪造城市" not in result["answer"]
    # 另一实例写入后，查询仍读取当前用户最新落盘值，而不是过期缓存。
    LongTermMemory("mock_user_a", str(tmp_path)).save_trip_history({"destination": "测试城市丙"})
    updated = msg_json(await memory_agent_class(memory_manager=manager).reply(request("我的差旅记录")))
    assert "测试城市丙" in updated["answer"]


@pytest.mark.asyncio
async def test_direct_queries_include_records_older_than_fifty(memory_agent_class, tmp_path):
    from context.long_term_memory import LongTermMemory

    memory = LongTermMemory("mock_history", str(tmp_path))
    memory.save_trip_history({"destination": "测试旧目的地", "start_date": "2020-01-01"})
    for index in range(51):
        memory.save_trip_history({"destination": "测试新目的地", "start_date": f"2026-02-{index % 28 + 1:02d}"})
    result = msg_json(await memory_agent_class(memory_manager=SimpleNamespace(long_term=memory)).reply(request("我去过哪些地方？")))
    assert "测试旧目的地" in result["answer"]
    assert result["memory_sources"]["trip_count"] == 52
    assert result["memory_sources"]["trip_history_complete"] is True


@pytest.mark.asyncio
async def test_postgres_reads_all_current_user_trips_with_null_limit(memory_agent_class):
    from context.long_term_memory import PostgresLongTermMemory

    pool = SimpleNamespace(execute=AsyncMock(), fetch=AsyncMock(return_value=[]))
    memory = PostgresLongTermMemory("mock_pg_user", pool)
    result = msg_json(await memory_agent_class(memory_manager=SimpleNamespace(long_term=memory)).reply(request("我的差旅记录")))
    assert result["status"] == "success"
    trip_call = next(call for call in pool.fetch.await_args_list if "FROM trip_history" in call.args[0])
    assert "WHERE user_id=$1" in trip_call.args[0]
    assert trip_call.args[1:] == ("mock_pg_user", None)


@pytest.mark.asyncio
async def test_complex_query_uses_one_model_without_generated_summary(memory_agent_class, saved_trips):
    manager = manager_with(saved_trips)
    model = AsyncMock(return_value=SimpleNamespace(text='```json\n{"answer": "记录中有两次北京行程，无法据此推断全部偏好。", "proactive_question": ""}\n```'))

    result = msg_json(await memory_agent_class(model=model, memory_manager=manager).reply(request("分析我的旅行规律")))

    assert result["status"] == "success"
    assert result["answer"] == "记录中有两次北京行程，无法据此推断全部偏好。"
    model.assert_awaited_once()
    manager.get_long_term_summary_async.assert_not_called()
    manager.long_term.get_chat_history.assert_not_called()
    messages = model.await_args.args[0]
    prompt = "\n".join(msg_text(message) if not isinstance(message, dict) else message["content"] for message in messages)
    assert "行程事实仅来自 trip_history" in prompt
    assert "不得声称用户已实际成行" in prompt


@pytest.mark.asyncio
async def test_explicit_conversation_query_reads_raw_excerpts_only(memory_agent_class):
    manager = manager_with()
    manager.long_term.get_chat_history.return_value = [{"role": "user", "content": "测试聊天片段"}]
    model = AsyncMock(return_value=SimpleNamespace(text='{"answer": "你之前提过测试聊天片段。"}'))

    result = msg_json(await memory_agent_class(model=model, memory_manager=manager).reply(request("我上次聊过什么？")))

    manager.long_term.get_chat_history.assert_called_once_with(limit=30)
    manager.get_long_term_summary_async.assert_not_called()
    assert result["memory_sources"]["has_chat_history"] is True


@pytest.mark.parametrize("response", [
    '{"answer": "查询正文", "proactive_question": "不应泄漏"}',
    '```json\n{"answer": "查询正文"}\n```',
    '{"answer": {"content": "查询正文"}}',
    json.dumps({"answer": json.dumps({"response": "查询正文"}, ensure_ascii=False)}, ensure_ascii=False),
    '说明：\n{"result": {"message": "查询正文"}}',
    '查询正文',
])
def test_answer_parser_returns_only_natural_language(response):
    assert extract_memory_answer(response) == "查询正文"


@pytest.mark.parametrize("response", [
    '{"status": "success", "memory_sources": {"trip_count": 1}}',
    '{"answer": "未闭合',
    '[{"answer": "不能当作正文"}]',
    '```json\n{"unknown": "原始结构"}\n```',
    '{"answer": ["不支持的数组"]}',
    '',
])
@pytest.mark.asyncio
async def test_invalid_model_payload_never_reaches_answer(memory_agent_class, response):
    model = AsyncMock(return_value=SimpleNamespace(text=response))
    result = msg_json(await memory_agent_class(model=model, memory_manager=manager_with()).reply(request("分析我的旅行规律")))
    assert result["status"] == "error"
    assert result["error_code"] == "invalid_memory_answer"
    assert "answer" not in result
    assert response not in result["message"] if response else True


@pytest.mark.asyncio
async def test_storage_error_is_safe_and_does_not_trigger_model(memory_agent_class):
    manager = manager_with()
    manager.long_term.get_trip_history.side_effect = OSError("模拟存储错误")
    model = AsyncMock()
    result = msg_json(await memory_agent_class(model=model, memory_manager=manager).reply(request("我的差旅记录")))
    assert result["status"] == "error"
    assert "模拟存储错误" not in result["message"]
    model.assert_not_called()
