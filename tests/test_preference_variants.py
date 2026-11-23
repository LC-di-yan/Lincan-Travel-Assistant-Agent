"""Offline regression coverage for explicit preference word order and safety."""
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock
import time

import pytest

from agents.intention_agent import IntentionAgent
from agents.orchestration_agent import OrchestrationAgent
from context.memory_manager import MemoryManager
from utils.as_compat import mk_msg, msg_json
from utils.preference_parser import can_route_preference_statement, parse_preference


@pytest.mark.parametrize("query,value", [
    ("我偏好打车出行", "打车"),
    ("我喜欢打车出行", "打车"),
    ("我习惯打车出行", "打车"),
    ("我出行偏好打车", "打车"),
    ("我出行时习惯打车", "打车"),
    ("出行时我偏好打车", "打车"),
    ("我平时出行喜欢打车", "打车"),
    ("我偏好出行时打车", "打车"),
    ("我偏好乘坐地铁出行", "地铁"),
    ("我习惯坐公交车出行", "公交车"),
    ("我习惯坐出租车出门", "出租车"),
    ("我偏好网约车通勤", "网约车"),
    ("我出差喜欢坐高铁", "高铁"),
    ("我出差时偏好坐高铁", "高铁"),
    ("出差时我习惯坐高铁", "高铁"),
    ("我出差出行习惯坐地铁", "地铁"),
    ("我倾向于打车出行", "打车"),
    ("我偏向打车出行", "打车"),
    ("我交通方式偏好高铁", "高铁"),
    ("我喜欢步行出行", "步行"),
    ("我的出行偏好是自驾", "自驾"),
    ("我的交通方式偏好为网约车", "网约车"),
    ("请帮我记住，我偏好打车出行。", "打车"),
])
def test_transportation_word_order_is_parsed_locally(query, value):
    assert parse_preference(query)["preferences"] == [
        {"type": "transportation_preference", "value": value, "action": "replace"}
    ]
    assert can_route_preference_statement(query)


@pytest.mark.parametrize("value", ["打车", "出租车", "网约车", "地铁", "公交车"])
@pytest.mark.parametrize("predicate", ["喜欢", "偏好", "习惯", "倾向于", "偏向"])
@pytest.mark.parametrize("suffix", ["出行", "通勤", "出门"])
def test_transport_aliases_and_suffixes_share_preference_grammar(value, predicate, suffix):
    choice = "" if value == "打车" else "坐"
    query = f"我{predicate}{choice}{value}{suffix}"
    assert parse_preference(query)["preferences"] == [
        {"type": "transportation_preference", "value": value, "action": "replace"}
    ]
    assert can_route_preference_statement(query)


@pytest.mark.parametrize("query,kind,value", [
    ("我住宿偏好汉庭", "hotel_brands", "汉庭"),
    ("我住宿时喜欢住全季酒店", "hotel_brands", "全季"),
    ("住宿时我习惯入住亚朵", "hotel_brands", "亚朵"),
    ("我偏好入住如家酒店", "hotel_brands", "如家"),
    ("我习惯住希尔顿", "hotel_brands", "希尔顿"),
    ("我的酒店品牌偏好是万豪酒店", "hotel_brands", "万豪"),
    ("我偏好全季住宿", "hotel_brands", "全季"),
    ("我出差住宿偏好汉庭", "hotel_brands", "汉庭"),
    ("我出差时住宿偏好汉庭", "hotel_brands", "汉庭"),
    ("我出差喜欢住全季酒店", "hotel_brands", "全季"),
    ("我的出差住宿偏好是汉庭", "hotel_brands", "汉庭"),
    ("我习惯乘坐东航", "airlines", "东航"),
    ("我喜欢乘坐南航的航班", "airlines", "南航"),
    ("我出行习惯乘坐南航", "airlines", "南航"),
    ("我喜欢乘坐东航出行", "airlines", "东航"),
    ("我乘机偏好国航", "airlines", "国航"),
    ("我出差乘机偏好国航", "airlines", "国航"),
    ("乘机时我习惯坐厦航", "airlines", "厦航"),
    ("我经常乘坐东方航空", "airlines", "东方航空"),
    ("我出差常坐东航", "airlines", "东航"),
    ("我的航空公司偏好为吉祥航空", "airlines", "吉祥航空"),
    ("我乘坐飞机时喜欢坐靠窗座位", "seat_preference", "靠窗"),
    ("我习惯坐靠过道的位置", "seat_preference", "靠过道"),
    ("我出差喜欢坐靠过道", "seat_preference", "靠过道"),
    ("乘机时我偏好靠窗", "seat_preference", "靠窗"),
    ("我的座位偏好是靠过道座位", "seat_preference", "靠过道"),
    ("我喜欢吃清淡的饭菜", "meal_preference", "清淡"),
    ("我饮食偏好清淡", "meal_preference", "清淡"),
    ("我出差饮食偏好清淡", "meal_preference", "清淡"),
    ("用餐时我习惯吃素食", "meal_preference", "素食"),
    ("我习惯吃素", "meal_preference", "素食"),
    ("我的餐食偏好为清真", "meal_preference", "清真"),
    ("我喜欢低盐饮食", "meal_preference", "低盐"),
    ("我偏好无糖饮食", "meal_preference", "无糖"),
])
def test_travel_preference_families_share_explicit_statement_grammar(query, kind, value):
    assert parse_preference(query)["preferences"] == [
        {"type": kind, "value": value, "action": "replace"}
    ]
    assert can_route_preference_statement(query)


@pytest.mark.parametrize("query,kind,value,action", [
    ("我还喜欢打车出行", "transportation_preference", "打车", "append"),
    ("我出行也习惯乘坐地铁", "transportation_preference", "地铁", "append"),
    ("我也倾向于坐出租车出门", "transportation_preference", "出租车", "append"),
    ("我出差也偏向打车出行", "transportation_preference", "打车", "append"),
    ("另外我偏好全季住宿", "hotel_brands", "全季", "append"),
    ("另外，我偏好全季住宿", "hotel_brands", "全季", "append"),
    ("此外我喜欢国航", "airlines", "国航", "append"),
    ("我也经常乘坐南航", "airlines", "南航", "append"),
    ("我出差也常坐南航", "airlines", "南航", "append"),
    ("我的酒店偏好增加如家", "hotel_brands", "如家", "append"),
    ("我的交通偏好追加打车", "transportation_preference", "打车", "append"),
    ("我的交通偏好追加出租车", "transportation_preference", "出租车", "append"),
    ("我的交通偏好改成网约车通勤", "transportation_preference", "网约车", "replace"),
    ("把我的出行偏好改成打车出行", "transportation_preference", "打车", "replace"),
    ("我把交通方式偏好换成地铁", "transportation_preference", "地铁", "replace"),
    ("我的住宿品牌偏好设为全季酒店", "hotel_brands", "全季", "replace"),
    ("我的航司偏好更新为南航", "airlines", "南航", "replace"),
    ("把我的座位偏好调整为靠窗", "seat_preference", "靠窗", "replace"),
    ("我的饮食偏好改为素食", "meal_preference", "素食", "replace"),
])
def test_preference_update_and_append_actions_are_preserved(query, kind, value, action):
    assert parse_preference(query)["preferences"] == [
        {"type": kind, "value": value, "action": action}
    ]


@pytest.mark.parametrize("separator", ["，", "；", "。", "\n", "并且", "而且", "同时"])
def test_multiple_explicit_preferences_are_all_extracted(separator):
    query = separator.join(["我偏好打车出行", "我住宿喜欢汉庭", "我习惯乘坐东航", "我偏好靠窗座位", "我饮食喜欢清淡"])
    assert parse_preference(query)["preferences"] == [
        {"type": "transportation_preference", "value": "打车", "action": "replace"},
        {"type": "hotel_brands", "value": "汉庭", "action": "replace"},
        {"type": "airlines", "value": "东航", "action": "replace"},
        {"type": "seat_preference", "value": "靠窗", "action": "replace"},
        {"type": "meal_preference", "value": "清淡", "action": "replace"},
    ]


def test_repeated_fields_append_unless_user_explicitly_replaces_them():
    parsed = parse_preference("我喜欢汉庭，我喜欢全季，我的酒店偏好改为如家，我还喜欢亚朵")
    assert [(p["value"], p["action"]) for p in parsed["preferences"]] == [
        ("汉庭", "replace"), ("全季", "append"), ("如家", "replace"), ("亚朵", "append")
    ]


@pytest.mark.parametrize("query", [
    "我不偏好打车出行", "我不喜欢汉庭", "我不是习惯坐东航", "我讨厌靠窗座位",
    "我喜欢打车出行吗", "我偏好打车还是地铁", "我的酒店偏好是什么", "我喜欢住哪里",
    "我是否偏好打车出行", "我可能喜欢住汉庭", "如果我喜欢汉庭", "他说我喜欢汉庭",
    "我住宿偏好哪家", "我的饮食偏好是怎样", "我的交通偏好是打车呢",
    "你喜欢汉庭", "我想打车出行", "我准备坐东航", "我今天坐东航", "我住汉庭酒店",
    "请推荐打车出行方案", "帮我推荐汉庭酒店", "删除交通偏好", "取消座位偏好",
    "我偏好打车出行，顺便查北京天气", "我喜欢汉庭并查询上海天气",
    "我偏好打车出行，同时订一张机票", "我住宿喜欢安静并比较当地价格",
    "我住宿偏好安静并记一笔打车50元", "我住宿偏好安静同时找找车票",
    "我喜欢全季，100美元多少人民币", "我饮食偏好清淡，安排明天的午餐",
    "我偏好打车出行，帮我去机场", "我偏好打车出行但不要保存",
    "我住在北京喜欢汉庭", "我住在北京坐地铁",
    "我住在北京打车去机场", "我家在上海写封邮件", "我住在上海开会",
    "我住在上海想订酒店", "我家在北京但是要去上海出差",
    "我家在北京出差", "我明天出差喜欢坐高铁", "我在上海出差喜欢坐高铁",
    "我出差喜欢坐高铁去上海", "我出差住宿偏好汉庭，明天订一晚",
    "我出差喜欢坐高铁，查一下明天的车票", "我出差住宿喜欢2026年11月19日入住汉庭",
    "我出差住宿喜欢十一月十九日入住汉庭", "我倾向于明天打车出行",
    "我出差喜欢周五坐高铁", "我出差喜欢星期五坐高铁", "我出差喜欢2026-11-19坐高铁",
    "我出差住宿喜欢汉庭订一晚", "我出差喜欢在上海住汉庭", "我出差住宿偏好汉庭一晚",
    "我偏向打车去上海", "我临时偏好网约车通勤", "我出差喜欢汉庭，订票去杭州",
    "我喜欢打车出行，未知内容", "我的习惯是早起", "我喜欢旅行", "",
])
def test_uncertain_negative_nonpreference_and_mixed_statements_never_fast_route(query):
    assert parse_preference(query) is None
    assert can_route_preference_statement(query) is False


@pytest.mark.parametrize("prefix", [
    "我家在北京", "我住在上海", "我常住呼和浩特", "我出行偏好打车",
    "我住宿偏好安静", "我乘机偏好东航", "我的饮食偏好是少油少盐",
])
@pytest.mark.parametrize("action", [
    "给我讲个笑话", "播放音乐", "打开浏览器", "发送邮件", "创建提醒",
    "算一下123加456", "折纸鹤", "遛小狗", "背诗词", "校对作业",
])
def test_attached_actions_are_never_absorbed_into_addresses_or_preferences(prefix, action):
    query = prefix + action
    assert parse_preference(query) is None
    assert can_route_preference_statement(query) is False


@pytest.mark.parametrize("query", [
    "我家在暂时未知", "我家在未知市", "我家在暂时未知区", "我住在北京临时路",
    "我家在无法确定市", "我家在随便市", "我家在未确认区", "我家在没确定市",
    "我家在上海左右", "我家在上海附近", "我家在北京或上海", "我家在北京和上海市",
    "我暂住北京", "我住在北京三天", "我住在北京一周", "我住在上海短期小区",
    "我家在北京给我讲个笑话路", "我住在上海播放音乐花园", "我住在无法确定小区",
])
def test_uncertain_temporary_and_nonaddress_locations_never_route_for_writing(query):
    assert parse_preference(query) is None
    assert can_route_preference_statement(query) is False


@pytest.mark.parametrize("query", [
    "我喜欢汉庭和如家", "我偏好打车和地铁出行", "我住宿偏好安静且靠近地铁的酒店",
    "我的饮食偏好是少油少盐", "我乘机喜欢坐商务舱", "我出行偏好机场接送服务",
    "我喜欢汉庭，我的住宿偏好是安静的酒店",
    "我住宿偏好莫兰迪酒店", "我喜欢住莫兰迪酒店", "我航司偏好阿联酋航空",
])
def test_clear_complex_preferences_route_without_fabricating_local_values(query):
    assert parse_preference(query) is None
    assert can_route_preference_statement(query) is True


@pytest.mark.parametrize("query,value", [
    ("我家在上海", "上海"), ("我搬家到苏州了", "苏州"),
    ("我住在上海浦东新区", "上海浦东新区"), ("我常住呼和浩特", "呼和浩特"),
    ("我迁居苏州", "苏州"), ("迁居苏州了", "苏州"), ("我常住在苏州", "苏州"),
    ("我家在浙江省杭州市滨江区", "浙江省杭州市滨江区"),
    ("我住在内蒙古自治区呼和浩特市赛罕区", "内蒙古自治区呼和浩特市赛罕区"),
    ("我住在上海浦东新区世纪大道100号2栋301室", "上海浦东新区世纪大道100号2栋301室"),
])
def test_home_location_remains_a_complete_standalone_statement(query, value):
    assert parse_preference(query)["preferences"] == [
        {"type": "home_location", "value": value, "action": "replace"}
    ]


def test_unknown_but_structured_address_is_model_extracted_not_locally_saved():
    query = "我家在云栖市新月区星河路18号"
    assert parse_preference(query) is None
    assert can_route_preference_statement(query) is True


def test_home_and_other_explicit_preferences_are_not_greedily_merged():
    assert parse_preference("我住在上海并且喜欢汉庭")["preferences"] == [
        {"type": "home_location", "value": "上海", "action": "replace"},
        {"type": "hotel_brands", "value": "汉庭", "action": "replace"},
    ]


def _preference_skill():
    path = Path(__file__).resolve().parents[1] / ".claude/skills/preference/script/agent.py"
    spec = importlib.util.spec_from_file_location("preference_variants_skill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_common_preference_variants_complete_without_model_calls(monkeypatch, tmp_path):
    import agents.intention_agent as intention_module

    model = AsyncMock(side_effect=AssertionError("明确常见偏好不得调用模型"))
    decision = AsyncMock(side_effect=AssertionError("明确常见偏好不得调用二级意图模型"))
    monkeypatch.setattr(intention_module, "maybe_use_decision", decision)
    memory = MemoryManager("preference_variants", "s1", storage_path=str(tmp_path), llm_model=model)
    preference = _preference_skill().PreferenceAgent(model=model, memory_manager=memory)
    orchestrator = OrchestrationAgent(agent_registry={"preference": preference}, memory_manager=memory)
    intention = IntentionAgent(model=model)
    queries = [
        "我偏好打车出行", "我还喜欢坐地铁出行", "我住宿习惯住汉庭酒店",
        "我习惯乘坐东航", "我乘机喜欢靠窗座位", "我饮食偏好清淡",
        "我出差喜欢坐高铁", "我出差住宿偏好汉庭", "我习惯坐出租车出门",
        "我偏好网约车通勤", "我倾向于打车出行", "我偏向打车出行",
        "把我的出行偏好改成自驾", "我还习惯乘坐高铁出行",
    ]
    elapsed = []
    for query in queries:
        start = time.monotonic()
        routed = await intention.reply(mk_msg("user", query, role="user"))
        result = msg_json(await orchestrator.reply(routed))
        elapsed.append(time.monotonic() - start)
        assert result["status"] == "completed"
        assert result["results"][0]["data"]["execution_path"] == "local_rules"
    assert memory.long_term.get_preference("transportation_preference") == ["自驾", "高铁"]
    assert memory.long_term.get_preference("hotel_brands") == "汉庭"
    assert memory.long_term.get_preference("airlines") == "东航"
    assert memory.long_term.get_preference("seat_preference") == "靠窗"
    assert memory.long_term.get_preference("meal_preference") == "清淡"
    model.assert_not_awaited()
    decision.assert_not_awaited()
    assert max(elapsed) < 2

@pytest.mark.parametrize("query", ["我的交通偏好设置为打车", "我的酒店偏好设置为汉庭"])
def test_explicit_preference_setting_is_not_mistaken_for_an_external_settings_task(query):
    assert parse_preference(query)
    assert can_route_preference_statement(query)
