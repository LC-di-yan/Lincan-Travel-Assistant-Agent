"""结构化记忆的确定性查询与模型正文边界。"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Optional


PREFERENCE_NAMES = {
    "home_location": "常用出发地",
    "hotel_brands": "酒店品牌",
    "airlines": "航空公司",
    "budget": "预算偏好",
    "accommodation": "住宿偏好",
    "transportation": "交通偏好",
    "food": "餐饮偏好",
    "activity": "活动偏好",
    "other": "其他偏好",
    "seat_preference": "座位偏好",
    "transportation_preference": "交通偏好",
    "meal_preference": "餐饮偏好",
    "budget_level": "预算档次",
}
PREFERENCE_WORDS = {
    "home_location": ("常住", "住在哪", "家庭地址", "家在哪", "常用出发地"),
    "hotel_brands": ("酒店品牌",),
    "airlines": ("航空公司", "航司"),
    "budget": ("预算",),
    "accommodation": ("住宿", "酒店"),
    "transportation": ("交通", "出行方式"),
    "food": ("餐饮", "口味", "饮食", "吃", "餐食", "用餐"),
    "activity": ("活动", "景点"),
    "seat_preference": ("座位", "座席", "坐哪", "靠窗", "靠过道", "舱位"),
    "transportation_preference": ("交通", "出行方式"),
    "meal_preference": ("餐饮", "口味", "饮食", "吃", "餐食", "用餐"),
    "budget_level": ("预算", "档次"),
}
_SEMANTIC_QUERY = re.compile(
    r"分析|建议|推荐|推测|为什么|原因|比较|对比|适合|意味着|趋势|规律|变化|根据|"
    r"最常|最多|最少|频繁|平均|一共.*天|总共.*天"
)
_TRIP_QUERY = re.compile(r"差旅|出差|行程|旅行|旅游|出行|去过|上次去|之前去|以前去|历史记录|去.*(?:时候|时间|几次|哪)")
_CONVERSATION_QUERY = re.compile(r"对话|聊天|聊过|说过什么|问过|提过什么")
_PREFERENCE_QUERY = re.compile(r"偏好|喜好|喜欢|习惯|常住|家在哪|住在哪|家庭地址|常用出发地")
_OTHER_TASK = re.compile(r"天气|气温|下雨|汇率|换算|翻译|报销|帮我(?:规划|预订|购买|订)|(?:并|同时|然后|另外|顺便|还).*(?:帮我|查询|查一下|规划|预订)")
_TRIP_READ_SIGNAL = re.compile(r"记录|历史|去过|上次|之前|以前|第一次|最早|最新|最近一次|最后一次|几次|多少次|查(?:询|看|一下)?.*行程")
_PREFERENCE_READ_SIGNAL = re.compile(r"查|看|列出|告诉|什么|哪些|哪|是否|有没有|有无|吗|么|[？?]|偏好[。！!]?$|喜好[。！!]?$|习惯[。！!]?$")
# 早路由宁可放弃不确定的读取，也不能吞掉第二个请求或记忆写入。
# 因此带并列结构、多个分句的输入交给原编排，即使它可能只是多项记忆读取。
_MULTIPLE_REQUESTS = re.compile(r"和|与|以及|还有|并|同时|然后|另外|顺便|再(?:帮|查|看|记|问|算)|也(?:帮|查|看|记|问|算)|[，,；;。！？!?\n\r、+&]")
_READ_ACTION = re.compile(r"查询|查看|查一下|看一下|查查|看看|列出|告诉我")
_WRITE_OR_EXTERNAL_TASK = re.compile(
    r"更新|修改|删除|删掉|删去|新增|添加|清空|改为|改成|换成|设为|设成|设置|标记|记(?:一)?笔|记账|记下|记住|录入|"
    r"保存一下|保存偏好|保存我的|(?:保存|记录)(?:一下)?(?:我的|我|偏好|喜好|习惯)|记录(?:一|这)笔|记录打车|记录餐费|"
    r"导出|下载|截图|打印|发送|发邮件|迁移|帮我找|搜索|预订|购买|订(?:酒店|机票|车票|高铁|火车|房|票)|规划|报价|时刻表|导航|"
    r"美元|美金|人民币|日元|欧元|英镑|港币|USD|CNY|RMB|EUR|JPY|\d+(?:\.\d+)?\s*元",
    re.IGNORECASE,
)


def is_simple_memory_query(query: str) -> bool:
    """只识别无需模型的纯记忆读取；混合天气等请求交由上层编排。"""
    if not isinstance(query, str):
        return False
    # 只移除句尾标点，内部标点仍视为可能的新请求边界。
    statement = query.strip().rstrip("。！？?!")
    if (
        _MULTIPLE_REQUESTS.search(statement)
        or _WRITE_OR_EXTERNAL_TASK.search(statement)
        or len(_READ_ACTION.findall(statement)) > 1
    ):
        return False
    preferences = bool(_PREFERENCE_QUERY.search(query) and _PREFERENCE_READ_SIGNAL.search(query))
    trips = bool(_TRIP_QUERY.search(query) and _TRIP_READ_SIGNAL.search(query))
    return (
        not _SEMANTIC_QUERY.search(query)
        and not _OTHER_TASK.search(query)
        and not re.search(r"上周|下周|过去|近[一二三四五六七八九十\d]+(?:天|个月|年)", query)
        and (preferences != trips)
        and not needs_conversation_history(query)
    )


def _value_text(value: Any) -> str:
    """展开已保存字段，避免把列表、字典的原始表示塞进正文。"""
    if value is None or value == "":
        return "未记录"
    if isinstance(value, dict):
        return "；".join(f"{key}：{_value_text(item)}" for key, item in value.items()) or "未记录"
    if isinstance(value, (list, tuple)):
        return "、".join(_value_text(item) for item in value) or "未记录"
    return str(value)


def format_trip_history(trips: list[dict]) -> str:
    """只展示已存字段；记录时间不是出行日期，缺失用途不默认为旅游。"""
    lines = []
    for index, trip in enumerate(trips, 1):
        dates = f"{_value_text(trip.get('start_date'))} 至 {_value_text(trip.get('end_date'))}"
        lines.append(
            f"{index}. {_value_text(trip.get('origin'))} → {_value_text(trip.get('destination'))}"
            f"｜日期：{dates}｜用途：{_value_text(trip.get('purpose'))}"
        )
    return "\n".join(lines) if lines else "暂无已保存的行程记录。"


def format_preferences(preferences: dict) -> str:
    lines = [
        f"- {PREFERENCE_NAMES.get(key, key)}：{_value_text(value)}"
        for key, value in preferences.items()
        if value is not None and value != "" and value != [] and value != {}
    ]
    return "\n".join(lines) if lines else "暂无已保存的偏好记录。"


def needs_conversation_history(query: str) -> bool:
    """只有明确询问旧对话时读取原始片段，不额外生成模型摘要。"""
    return bool(_CONVERSATION_QUERY.search(query)) and not bool(_PREFERENCE_QUERY.search(query))


def _trip_sort_key(trip: dict) -> tuple[str, str]:
    # 起始日期缺失时不把记录写入时间当成出发日期。
    return str(trip.get("start_date") or ""), str(trip.get("timestamp") or "")


def _destination_in_query(query: str, trips: list[dict]) -> Optional[str]:
    candidates = {str(trip["destination"]) for trip in trips if trip.get("destination")}
    mentions = [city for city in candidates if city in query]
    if mentions:
        return max(mentions, key=len)
    # 已知目的地未命中时仍识别明确的去向，避免把别的城市记录当作答案。
    match = re.search(
        r"(?:去过|前往|去|到)([\u4e00-\u9fffA-Za-z·]{2,12}?)(?=出差|旅行|旅游|的|是|在|什么|哪|时候|时间|几|[？?，,]|$)",
        query,
    )
    city = match.group(1) if match else None
    return city if city and not re.match(r"哪些|哪里|哪儿|什么|过哪|过哪儿|了哪", city) else None


def direct_memory_answer(query: str, trips: list[dict], preferences: dict) -> Optional[str]:
    """返回可由结构化记忆回答的正文；需要语义理解时返回 None。"""
    if not is_simple_memory_query(query):
        return None

    wants_preferences = bool(_PREFERENCE_QUERY.search(query))
    wants_trips = bool(_TRIP_QUERY.search(query) and _TRIP_READ_SIGNAL.search(query))
    if wants_preferences:
        selected = {
            key: value
            for key, value in preferences.items()
            if any(word in query for word in PREFERENCE_WORDS.get(key, ()))
        }
        # 询问酒店时同时保留住宿要求与品牌，不凭空推断偏好。
        if "酒店" in query:
            selected = {key: value for key, value in preferences.items() if key in ("accommodation", "hotel_brands")}
        has_category = any(word in query for words in PREFERENCE_WORDS.values() for word in words)
        return "已保存的偏好：\n" + format_preferences(selected if has_category else preferences)

    if not wants_trips or needs_conversation_history(query):
        return None
    selected = list(trips)
    if "出差" in query:
        selected = [trip for trip in selected if re.search(r"出差|商务|公务", str(trip.get("purpose") or ""))]
    mentioned_destinations = {str(trip["destination"]) for trip in trips if trip.get("destination") and str(trip["destination"]) in query}
    destination = _destination_in_query(query, trips)
    if mentioned_destinations:
        selected = [trip for trip in selected if str(trip.get("destination") or "") in mentioned_destinations]
    elif destination:
        selected = [trip for trip in selected if str(trip.get("destination") or "") == destination]
    year = re.search(r"(20\d{2})年", query)
    month = re.search(r"(?:年|(?<!\d))(1[0-2]|0?[1-9])月", query)
    day = re.search(r"月(3[01]|[12]\d|0?[1-9])[日号]", query)
    exact_date = re.search(r"20\d{2}-\d{1,2}-\d{1,2}", query)
    selected_year = int(year.group(1)) if year else None
    selected_month = int(month.group(1)) if month else None
    if "今年" in query:
        selected_year = date.today().year
    elif "去年" in query:
        selected_year = date.today().year - 1
    if "本月" in query or "这个月" in query:
        selected_year, selected_month = date.today().year, date.today().month
    elif "上个月" in query:
        today = date.today()
        selected_year, selected_month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    if selected_year or selected_month or day or exact_date:
        def matches_date(trip):
            trip_date = str(trip.get("start_date") or "")
            parts = trip_date.split("-")
            return (not exact_date or trip_date == exact_date.group()) and (
                not selected_year or (parts and parts[0] == str(selected_year))
            ) and (
                not selected_month or (len(parts) > 1 and parts[1].isdigit() and int(parts[1]) == selected_month)
            ) and (
                not day or (len(parts) > 2 and parts[2].isdigit() and int(parts[2]) == int(day.group(1)))
            )
        selected = [trip for trip in selected if matches_date(trip)]
    if not selected:
        return "当前读取的结构化行程记录中没有符合条件的记录；不会将聊天中提到的计划当作行程事实。"

    selected.sort(key=_trip_sort_key, reverse=True)
    if re.search(r"上次|最近一次|最后一次|最新(?:一条|一次)?", query):
        # 没有起始日期的记录无法可靠判断哪一次实际出行更近。
        if any(not trip.get("start_date") for trip in selected):
            return "部分行程未记录出发日期，无法准确确定上次出行对应的已保存记录；记录不代表实际成行。\n" + format_trip_history(selected)
        selected = selected[:1]
    elif re.search(r"第一次|最早", query):
        if any(not trip.get("start_date") for trip in selected):
            return "部分行程未记录出发日期，无法准确确定首次出行对应的已保存记录；记录不代表实际成行。\n" + format_trip_history(selected)
        selected = selected[-1:]
    elif re.search(r"几次|多少次|多少条|几条", query):
        return f"当前读取的结构化记录中，符合条件的行程共 {len(selected)} 条（不代表实际成行次数）。"

    detail_fields = [
        (r"住宿|住过|住的|酒店", "住宿", ("hotel", "hotel_name", "accommodation")),
        (r"交通|怎么去|坐什么|航班|车次", "交通", ("transportation", "transport", "flight", "train")),
        (r"花了|费用|开销|预算", "费用", ("cost", "expenses", "budget")),
    ]
    for pattern, label, keys in detail_fields:
        if re.search(pattern, query):
            lines = []
            for trip in selected:
                values = [_value_text(trip[key]) for key in keys if trip.get(key) is not None]
                lines.append(f"- {_value_text(trip.get('destination'))}（{_value_text(trip.get('start_date'))}）：" + "；".join(values or [f"未记录{label}信息"]))
            return f"已保存行程中的{label}信息：\n" + "\n".join(lines)

    if re.search(r"哪些地方|哪些城市|去过哪|去过什么地方", query):
        destinations = list(dict.fromkeys(str(trip["destination"]) for trip in selected if trip.get("destination")))
        return "已保存行程中的目的地：" + "、".join(destinations) + "。（不能据此确认实际去过。）" if destinations else "行程记录未保存目的地。"
    return "已保存的行程记录（不代表实际成行）：\n" + format_trip_history(selected)


def extract_memory_answer(value: Any, depth: int = 0) -> str:
    """只接受自然语言字段；拒绝未知、损坏或嵌套过深的 JSON 外壳。"""
    if depth > 6:
        return ""
    if isinstance(value, dict):
        for key in ("answer", "response", "content", "result", "message"):
            if key in value:
                answer = extract_memory_answer(value[key], depth + 1)
                if answer:
                    return answer
        return ""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        # 模型在 JSON 外添加说明时，只提取其中完整的对象，绝不回显外壳。
        start, end = text.find("{"), text.rfind("}")
        if start >= 0:
            try:
                return extract_memory_answer(json.loads(text[start:end + 1]), depth + 1)
            except (json.JSONDecodeError, TypeError):
                return ""
        # 不透传数组、损坏代码块或键值形式的半截 JSON。
        if text.startswith(("[", '"')) or "```" in text or re.search(r'"(?:answer|content|result|status|query)"\s*:', text):
            return ""
        return text
    if isinstance(parsed, (dict, str)):
        return extract_memory_answer(parsed, depth + 1)
    return ""
