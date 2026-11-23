"""Offline checks for deterministic, single-task train intent parsing."""
from datetime import datetime, timezone

import pytest

from utils import train_intent


@pytest.fixture(autouse=True)
def fixed_beijing_clock(monkeypatch):
    monkeypatch.setattr(train_intent, "shanghai_now", lambda: datetime(2026, 11, 18, 16, 30, tzinfo=timezone.utc))


def test_destination_only_asks_origin_without_guessing_date():
    result = train_intent.build_train_intention("查去北京的火车票")
    assert result["needs_clarification"] is True
    assert result["fast_event"]["missing_info"] == ["出发地", "出发日期"]
    assert result["clarification_field"] == "出发地"
    assert result["fast_train_ticket"] == {"from": "", "to": "北京", "date": ""}
    assert [task["agent_name"] for task in result["agent_schedule"]] == ["train_ticket"]
    assert result["fast_event"]["start_date"] == ""


def test_clarification_preserves_date_period_and_train_type():
    result = train_intent.build_train_intention("帮我查明早去北京的高铁票")
    assert result["fast_event"]["missing_info"] == ["出发地"]
    assert result["fast_train_ticket"] == {
        "from": "", "to": "北京", "date": "2026-11-20", "period": "morning", "train_types": ["G"],
    }
    assert result["rewritten_query"] == "帮我查明早去北京的高铁票"


@pytest.mark.parametrize("query,origin,destination,date_str", [
    ("查明天从上海去北京的火车票", "上海", "北京", "2026-11-20"),
    ("查一下2026-12-01北京到上海的高铁", "北京", "上海", "2026-12-01"),
    ("查广州到揭阳11月20日的火车票", "广州", "揭阳", "2026-11-20"),
    ("查下周一广州到深圳的动车", "广州", "深圳", "2026-11-23"),
    ("目的地：北京，出发地：上海，明天的火车票", "上海", "北京", "2026-11-20"),
    ("明天出差从北京去上海，只查火车票", "北京", "上海", "2026-11-20"),
])
def test_complete_route_only_schedules_ticket_lookup(query, origin, destination, date_str):
    result = train_intent.build_train_intention(query)
    assert result is not None
    assert result["needs_clarification"] is False
    assert result["fast_event"]["missing_info"] == []
    assert result["fast_train_ticket"]["from"] == origin
    assert result["fast_train_ticket"]["to"] == destination
    assert result["fast_train_ticket"]["date"] == date_str
    assert [task["agent_name"] for task in result["agent_schedule"]] == ["train_ticket"]


def test_known_route_without_date_asks_instead_of_assuming_today():
    result = train_intent.build_train_intention("查广州到揭阳的高铁")
    assert result["needs_clarification"] is True
    assert result["fast_event"]["missing_info"] == ["出发日期"]
    assert result["clarification_field"] == "出发日期"
    assert result["fast_train_ticket"]["date"] == ""
    assert [task["agent_name"] for task in result["agent_schedule"]] == ["train_ticket"]


def test_relative_dates_use_beijing_day_not_utc_day():
    result = train_intent.build_train_intention("查今天北京到上海的火车票")
    assert result["fast_train_ticket"]["date"] == "2026-11-19"


@pytest.mark.parametrize("query", [
    "查明天北京到上海的高铁和天气",
    "查明天北京到上海的高铁，顺便找酒店",
    "查明天北京到上海的高铁，再规划三天行程",
    "查明天北京到上海的高铁，推荐景点",
    "查明天北京到上海的高铁以及当地交通",
    "查明天北京到上海的高铁，穿什么衣服",
    "查明天北京到上海的高铁，100美元多少人民币",
    "查明天北京到上海的高铁，同时翻译hello",
    "查明天北京到上海的高铁并记一笔打车50元",
    "查明天北京到上海的高铁以及我的出差历史",
    "明天北京到上海的高铁，另外提醒我开会",
    "查明天北京到上海的高铁和广州到揭阳的火车票",
])
def test_mixed_requests_defer_to_full_intent_recognition(query):
    assert train_intent.build_train_intention(query) is None


@pytest.mark.parametrize("query", [
    "查北京到上海的高铁票价", "G123经停哪些站", "北京到上海怎么换乘火车",
    "北京有哪些火车站", "查明天北京到上海的高铁多少钱", "订明天北京到上海的火车票",
    "查明天北京到上海的火车票并改签", "查北京到上海火车票什么时候开售",
    "高铁", "12306", "我想高铁", "高铁安全吗", "火车票怎么买", "不查去北京的火车票", "查去北京的机票",
    "查明天北京南到上海虹桥的高铁", "查明天南京路到北京的火车票",
    "查明天从公司去北京的火车票", "查北京的火车票", "查明天北京上海的火车票",
    "查明天北京到上海早上和晚上的高铁", "查明天北京到上海10点的高铁",
])
def test_uncertain_roles_special_operations_and_unparsed_filters_are_not_intercepted(query):
    assert train_intent.build_train_intention(query) is None


@pytest.mark.parametrize("query", [
    "查2026-02-30北京到上海的火车票", "查昨天北京到上海的火车票",
    "查明天或后天北京到上海的火车票", "查下周北京到上海的火车票",
    "查国庆北京到上海的火车票", "查下个月20号北京到上海的火车票",
    "查十一月二十日北京到上海的火车票",
])
def test_invalid_ambiguous_and_unsupported_dates_are_not_changed_to_today(query):
    assert train_intent.build_train_intention(query) is None


def test_ticket_request_without_route_preserves_pending_endpoints():
    result = train_intent.build_train_intention("帮我查火车票")
    assert result["needs_clarification"] is True
    assert result["fast_event"]["missing_info"] == ["目的地", "出发地", "出发日期"]
    assert result["fast_train_ticket"] == {"from": "", "to": "", "date": ""}


@pytest.mark.parametrize("text,expected", [
    ("", ""), ("上海", ""), ("明天", "2026-11-20"), ("明早", "2026-11-20"),
    ("后天", "2026-11-21"), ("11月20日", "2026-11-20"), ("2026-11-20", "2026-11-20"),
    ("2026-02-30", ""), ("明天或后天", ""), ("国庆", ""),
])
def test_shared_train_date_parser_never_guesses_an_omitted_day(text, expected):
    assert train_intent.parse_train_date(text) == expected


def test_shared_train_date_parser_accepts_explicit_clock():
    now = datetime(2026, 12, 31, 16, 30, tzinfo=timezone.utc)
    assert train_intent.parse_train_date("明天", now=now) == "2027-01-02"
