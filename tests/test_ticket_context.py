"""火车票上下文回填与余票请求回归测试；全部使用本地替身，不访问 12306。"""
import asyncio
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from utils.as_compat import mk_msg, msg_text


_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "train_ticket_context_agent", _ROOT / ".claude" / "skills" / "train-ticket" / "script" / "agent.py"
)
agent_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(agent_mod)


@pytest.fixture(autouse=True)
def forbid_live_requests(monkeypatch):
    """未显式替换的网络调用直接失败，防止回归测试误连真实接口。"""
    monkeypatch.setattr(httpx, "get", Mock(side_effect=AssertionError("禁止真实网络请求")))
    monkeypatch.setattr(httpx, "AsyncClient", Mock(side_effect=AssertionError("禁止真实网络请求")))
    monkeypatch.setattr(agent_mod, "_get_station_code", Mock(side_effect=AssertionError("必须替换站点查询")))
    agent_mod._query_cache.clear()
    yield
    agent_mod._query_cache.clear()


def _train_row(train_no="G102", depart_time="09:00"):
    parts = [""] * 33
    for index, value in {
        3: train_no, 6: "AOH", 7: "VNP", 8: depart_time, 9: "14:30", 10: "05:30", 30: "有", 31: "2"
    }.items():
        parts[index] = value
    return "|".join(parts)


def _payload():
    return {
        "httpstatus": 200,
        "data": {"map": {"AOH": "上海虹桥", "VNP": "北京南"}, "result": [_train_row()]},
    }


@pytest.fixture
def ticket_transport(monkeypatch):
    calls = []
    response_payload = _payload()

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return response_payload

    class FakeClient:
        def __init__(self, **kwargs):
            self.options = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse()

    station_lookup = Mock(side_effect=lambda city: {"上海": "SHH", "北京": "BJP"}.get(city))
    monkeypatch.setattr(agent_mod, "_get_station_code", station_lookup)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    return calls, response_payload, station_lookup


@pytest.mark.parametrize(
    "data",
    [
        {"context": {"rewritten_query": "从上海出发。去北京", "key_entities": {
            "origin": "上海", "destination": "北京", "date": "2026-11-20"}}},
        {"context": {"rewritten_query": "上海", "fast_train_ticket": {
            "from": "上海", "to": "北京", "date": "2026-11-20"}}},
        {"fast_train_ticket": {"from": "上海"}, "context": {"rewritten_query": "上海", "key_entities": {
            "origin": "广州", "destination": "北京", "start_date": "2026-11-20"}}},
    ],
)
async def test_reply_uses_explicit_context_without_model(data, ticket_transport):
    model = AsyncMock(side_effect=AssertionError("余票查询不能调用模型"))
    agent = agent_mod.TrainTicketAgent(model=model)
    result = json.loads(msg_text(await agent.reply(mk_msg("user", data))))

    calls, _, station_lookup = ticket_transport
    assert result["query_success"] is True
    assert result["results"]["from"] == "上海"
    assert result["results"]["to"] == "北京"
    assert result["results"]["date"] == "2026-11-20"
    assert result["results"]["trains"][0]["train_no"] == "G102"
    station_lookup.assert_any_call("上海")
    station_lookup.assert_any_call("北京")
    assert len(calls) == 2
    assert calls[1][1]["params"] == {
        "leftTicketDTO.train_date": "2026-11-20",
        "leftTicketDTO.from_station": "SHH",
        "leftTicketDTO.to_station": "BJP",
        "purpose_codes": "ADULT",
    }
    model.assert_not_called()


async def test_partial_fast_params_fall_back_to_query(ticket_transport):
    result = await agent_mod.TrainTicketAgent()._query_tickets(
        "2026-11-20 上海到北京火车票", {"from": "上海"}
    )
    assert result["query_success"] is True
    assert result["results"]["to"] == "北京"


@pytest.mark.parametrize("rewritten", [
    "用户更在意省钱还是少换乘？已补充：出发地=上海；目的地=北京；出发日期=2026-11-20",
    "上海到北京，请提供中转方案",  # A rewrite must not override an actual preference for direct trains.
])
async def test_transfer_preference_uses_the_confirmed_direct_ticket_lookup(rewritten, ticket_transport):
    data = {"context": {"original_query": "查去北京的火车票，我想少换乘", "rewritten_query": rewritten,
                        "fast_train_ticket": {"from": "上海", "to": "北京", "date": "2026-11-20"}}}
    result = json.loads(msg_text(await agent_mod.TrainTicketAgent().reply(mk_msg("user", data))))
    assert result["query_type"] == "余票查询"
    assert result["query_success"] is True
    assert result["results"]["trains"][0]["train_no"] == "G102"


async def test_explicit_transfer_consumes_structured_slots_without_reasking_or_inventing_trains(monkeypatch):
    agent = agent_mod.TrainTicketAgent()
    monkeypatch.setattr(agent, "_extract_travel_params", Mock(side_effect=AssertionError("完整槽位不应重解析")))
    payload = {"context": {"original_query": "去北京怎么换乘", "rewritten_query": "明天",
                           "fast_train_ticket": {"from": "上海", "to": "北京", "date": "2026-11-20"}}}
    result = json.loads(msg_text(await agent.reply(mk_msg("user", payload))))
    assert result["availability_status"] == "unavailable"
    assert result["query_success"] is False
    assert result["query_type"] == "中转换乘"
    assert [result["results"][key] for key in ("from", "to", "date")] == ["上海", "北京", "2026-11-20"]
    assert "暂未获取" in result["results"]["message"]
    assert "trains" not in result["results"]


async def test_complete_fast_params_do_not_reparse_query(monkeypatch, ticket_transport):
    agent = agent_mod.TrainTicketAgent()
    monkeypatch.setattr(agent, "_extract_travel_params", Mock(side_effect=AssertionError("已有实体不重解析")))
    result = await agent._query_tickets("上海", {"from": "上海", "to": "北京", "date": "2026-11-20"})
    assert result["query_success"] is True


async def test_missing_date_asks_before_station_or_network_lookup():
    agent = agent_mod.TrainTicketAgent()
    result = await agent._query_tickets("从上海出发。去北京", {"from": "上海", "to": "北京"})
    assert result["query_success"] is False
    assert result["needs_clarification"] is True
    assert result["missing_info"] == ["出发日期"]
    assert result["results"]["from"] == "上海"
    assert result["results"]["to"] == "北京"
    assert "日期" in result["answer"]


async def test_missing_origin_preserves_destination_and_date():
    result = await agent_mod.TrainTicketAgent()._query_tickets(
        "去北京的火车票", {"to": "北京", "date": "2026-11-20"}
    )
    assert result["missing_info"] == ["出发地"]
    assert result["results"]["to"] == "北京"
    assert result["results"]["date"] == "2026-11-20"


@pytest.mark.parametrize("date", ["2026-02-30", "2026-13-01", "下次", "2026-00-10"])
async def test_invalid_date_does_not_default_to_today(date):
    result = await agent_mod.TrainTicketAgent()._query_tickets(
        "上海到北京火车票", {"from": "上海", "to": "北京", "date": date}
    )
    assert result["query_success"] is False
    assert result["missing_info"] == ["出发日期"]


@pytest.mark.parametrize("word,offset", [("今天", 0), ("明早", 1), ("后天", 2)])
async def test_explicit_relative_date_is_sent_to_api(word, offset, ticket_transport):
    result = await agent_mod.TrainTicketAgent()._query_tickets(
        "上海到北京火车票", {"from": "上海", "to": "北京", "date": word}
    )
    expected = (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")
    assert result["results"]["date"] == expected
    assert ticket_transport[0][1][1]["params"]["leftTicketDTO.train_date"] == expected


def test_single_digit_iso_date_is_normalized():
    assert agent_mod._normalize_date_str("2026-1-2") == "2026-01-02"


async def test_32_column_row_is_skipped_without_discarding_valid_train(ticket_transport):
    ticket_transport[1]["data"]["result"].insert(0, "|".join([""] * 32))
    result = await agent_mod.TrainTicketAgent()._query_tickets(
        "上海", {"from": "上海", "to": "北京", "date": "2026-11-20"}
    )
    assert result["query_success"] is True
    assert result["results"]["total"] == 1


async def test_upstream_error_is_not_reported_as_no_tickets(monkeypatch, ticket_transport):
    ticket_transport[1].clear()
    result = await agent_mod.TrainTicketAgent()._query_tickets(
        "上海", {"from": "上海", "to": "北京", "date": "2026-11-20"}
    )
    assert result["query_success"] is False
    assert "暂无余票" not in result["answer"]
    assert "trains" not in result["results"]


async def test_cookie_and_ticket_requests_share_total_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(agent_mod, "TICKET_REQUEST_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(agent_mod, "_get_station_code", lambda city: "SHH" if city == "上海" else "BJP")

    class SlowClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            calls.append(url)
            await asyncio.sleep(1)

    monkeypatch.setattr(httpx, "AsyncClient", SlowClient)
    result = await asyncio.wait_for(agent_mod.TrainTicketAgent()._query_tickets(
        "上海", {"from": "上海", "to": "北京", "date": "2026-11-20"}
    ), timeout=0.5)
    assert result["query_success"] is False
    assert "12306" in result["answer"]
    assert len(calls) == 1, "超时后不能重试或继续发起余票请求"


async def test_station_lookup_is_bounded(monkeypatch):
    async def slow_lookup(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(agent_mod, "STATION_LOOKUP_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(agent_mod.asyncio, "to_thread", slow_lookup)
    result = await asyncio.wait_for(agent_mod.TrainTicketAgent()._query_tickets(
        "上海", {"from": "上海", "to": "北京", "date": "2026-11-20"}
    ), timeout=0.5)
    assert result["query_success"] is False
    assert "车站信息查询超时" in result["answer"]


@pytest.mark.parametrize("query,method", [
    ("G1票价多少钱", "_query_price"),
    ("查北京站", "_search_station"),
    ("G1经过哪些站", "_query_route_stations"),
    ("上海到北京怎么换乘", "_query_transfer"),
])
async def test_non_ticket_query_types_keep_their_handlers(monkeypatch, query, method):
    agent = agent_mod.TrainTicketAgent()
    handler = AsyncMock(return_value={"query_success": True})
    monkeypatch.setattr(agent, method, handler)
    await agent.reply(mk_msg("user", query))
    handler.assert_awaited_once_with(query)


def test_context_train_types_are_preserved_and_normalized():
    params = agent_mod.TrainTicketAgent._context_travel_params(
        {"fast_train_ticket": {"from": "上海", "train_types": ["g", "D", "g", None, "invalid"]}},
        {"key_entities": {"destination": "北京", "train_types": ["C"], "period": "afternoon"}},
    )
    assert params == {"from": "上海", "to": "北京", "train_types": ["G", "D"], "period": "afternoon"}


async def test_reply_filters_train_types_and_period_from_context(ticket_transport):
    ticket_transport[1]["data"]["result"] = [
        _train_row("D111", "11:59"), _train_row("G120", "12:00"), _train_row("D169", "16:59"),
        _train_row("C140", "14:00"), _train_row("G170", "17:00"),
    ]
    message = mk_msg("user", {
        "fast_train_ticket": {"from": "上海"},
        "context": {"rewritten_query": "上海", "key_entities": {
            "destination": "北京", "date": "2026-11-20", "train_types": ["G", "D"], "period": "afternoon",
        }},
    })
    result = json.loads(msg_text(await agent_mod.TrainTicketAgent().reply(message)))
    assert [t["train_no"] for t in result["results"]["trains"]] == ["G120", "D169"]
    assert result["results"]["train_types"] == ["D", "G"]
    assert result["results"]["period"] == "afternoon"
    assert "下午" in result["answer"]


@pytest.mark.parametrize("period,expected", [
    ("morning", ["G111"]),
    ("afternoon", ["G120", "G169"]),
    ("evening", ["G170"]),
])
async def test_period_boundaries(period, expected, ticket_transport):
    ticket_transport[1]["data"]["result"] = [
        _train_row("G111", "11:59"), _train_row("G120", "12:00"),
        _train_row("G169", "16:59"), _train_row("G170", "17:00"),
    ]
    result = await agent_mod.TrainTicketAgent()._query_tickets(
        "上海", {"from": "上海", "to": "北京", "date": "2026-11-20", "period": period}
    )
    assert [t["train_no"] for t in result["results"]["trains"]] == expected


@pytest.mark.parametrize("filters", [{"train_types": ["D"]}, {"period": "afternoon"}])
async def test_unmatched_filters_are_not_reported_as_all_sold_out(filters, ticket_transport):
    result = await agent_mod.TrainTicketAgent()._query_tickets(
        "上海", {"from": "上海", "to": "北京", "date": "2026-11-20", **filters}
    )
    assert result["query_success"] is True
    assert result["results"]["trains"] == []
    assert result["results"]["unfiltered_total"] == 1
    assert result["results"]["matched_total"] == 0
    assert "未找到符合" in result["answer"]
    assert "暂无余票" not in result["answer"]
    assert "不代表其他车次无余票" in result["answer"]


async def test_train_type_filter_runs_before_display_limit(ticket_transport):
    ticket_transport[1]["data"]["result"] = [
        *[_train_row(f"K{i}") for i in range(1, 17)], _train_row("G102"),
    ]
    result = await agent_mod.TrainTicketAgent()._query_tickets(
        "上海", {"from": "上海", "to": "北京", "date": "2026-11-20", "train_types": ["G"]}
    )
    assert [t["train_no"] for t in result["results"]["trains"]] == ["G102"]
    assert result["results"]["unfiltered_total"] == 17


async def test_train_type_filters_have_distinct_cache_keys(ticket_transport):
    ticket_transport[1]["data"]["result"] = [_train_row("G102"), _train_row("D102")]
    agent = agent_mod.TrainTicketAgent()
    base = {"from": "上海", "to": "北京", "date": "2026-11-20"}
    high_speed = await agent._query_tickets("上海", {**base, "train_types": ["G"]})
    bullet = await agent._query_tickets("上海", {**base, "train_types": ["D"]})
    high_speed_again = await agent._query_tickets("上海", {**base, "train_types": ["G"]})
    assert [t["train_no"] for t in high_speed["results"]["trains"]] == ["G102"]
    assert [t["train_no"] for t in bullet["results"]["trains"]] == ["D102"]
    assert high_speed_again == high_speed
    assert len(ticket_transport[0]) == 4, "相同筛选复用成功缓存，不同车型不得串缓存"


async def test_reply_does_not_cache_clarification():
    agent = agent_mod.TrainTicketAgent()
    layer = Mock(enabled=True, get_json=AsyncMock(), set_json=AsyncMock())
    agent._cache_layer = layer
    message = mk_msg("user", {"fast_train_ticket": {"from": "上海", "to": "北京"}})
    for _ in range(2):
        result = json.loads(msg_text(await agent.reply(message)))
        assert result["needs_clarification"] is True
    layer.get_json.assert_not_awaited()
    layer.set_json.assert_not_awaited()
    assert agent_mod._query_cache == {}


async def test_relative_dates_are_renormalized_before_cache_lookup(monkeypatch, ticket_transport):
    class FrozenDateTime(datetime):
        current = datetime(2026, 11, 18, 12, 0)

        @classmethod
        def now(cls):
            return cls.current

    monkeypatch.setattr(agent_mod, "datetime", FrozenDateTime)
    agent = agent_mod.TrainTicketAgent()
    message = mk_msg("user", {"fast_train_ticket": {"from": "上海", "to": "北京", "date": "明天"}})
    first = json.loads(msg_text(await agent.reply(message)))
    FrozenDateTime.current = datetime(2026, 11, 19, 12, 0)
    second = json.loads(msg_text(await agent.reply(message)))
    assert first["results"]["date"] == "2026-11-19"
    assert second["results"]["date"] == "2026-11-20"
    assert len(ticket_transport[0]) == 4


async def test_missing_date_is_not_created_by_route_extraction():
    agent = agent_mod.TrainTicketAgent()
    assert agent._extract_travel_params("上海到北京火车票") == ("上海", "北京", "")
    result = await agent._query_tickets("上海到北京火车票")
    assert result["needs_clarification"] is True
    assert result["missing_info"] == ["出发日期"]
