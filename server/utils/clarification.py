"""Merge slot answers without changing the task the user actually requested."""
from copy import deepcopy
import re

from utils.train_intent import build_train_intention, parse_train_date

_QUESTIONS = {
    "出发地": "请问你从哪个城市出发？",
    "目的地": "请问你要前往哪个城市？",
    "出发日期": "你计划哪天出发？可以说“明天”或具体日期。",
    "天数": "你打算出行几天？",
    "行程目的": "这次出行的目的是什么？",
}
_ENTITY_FIELDS = {"出发地": "origin", "目的地": "destination", "出发日期": "start_date", "天数": "duration_days", "行程目的": "trip_purpose"}
_NEW_TOPIC = re.compile(r"天气|酒店|住宿|景点|美食|餐厅|汇率|换算|翻译|记账|记一笔|记录|美元|人民币|机票|查询|查票|火车票|高铁|车次|规划|攻略|行程|取消|算了|不用了|不查了|帮我|推荐|什么|哪些|为什么|如何")
_UNSURE = re.compile(r"^(?:我)?(?:还|暂时)?(?:待定|不确定|没定|不知道|不清楚|没想好|随便|都行|无所谓)$")
_DATE_TEXT = re.compile(
    r"(?<!\d)(?:\d{4}(?:年|[-/]))?\d{1,2}(?:月|[-/])\d{1,2}(?:日|号)?(?!\d)|"
    r"(?<!\d)\d{1,2}(?:日|号)(?!\d)|大后天|后天|后早|后晚|明天|明日|明早|明晚|今天|今日|今早|今晚|昨天|昨日|"
    r"(?:下下|下|本|这)?(?:周|星期)[一二三四五六日天]"
)


def normalize_place(text: str) -> str:
    value = (text or "").strip().strip("。，,！!、 ")
    value = re.sub(r"^(?:我(?:想|要)?(?:是)?|出发地是|目的地是)?(?:从|自|去|到)?", "", value)
    return re.sub(r"(?:出发|起飞|走)$", "", value).strip()


def _place_answer(text: str) -> str:
    if _NEW_TOPIC.search(text) or _UNSURE.fullmatch(text.strip()) or re.search(r"[?？]|不知|随便|都行|无所谓|记得|日期|明天|后天|今天|出差|旅游|开会|商务|度假|和|或|以及|[一二三四五六七八九十两\d]+天", text):
        return ""
    value = normalize_place(text)
    if re.fullmatch(r"[\u4e00-\u9fffA-Za-z· -]{2,16}", value):
        return value
    return ""


def _canonical_pending(pending: dict) -> dict:
    result = deepcopy(pending)
    entities = result.get("key_entities")
    entities = entities if isinstance(entities, dict) else {}
    event = result.get("fast_event")
    event = event if isinstance(event, dict) else {}
    ticket = result.get("fast_train_ticket")
    ticket = ticket if isinstance(ticket, dict) else {}
    original = result.get("original_query") or result.get("rewritten_query") or ""
    # Recover intended work even from the legacy clarification protocol (schedule=[]).
    simple_ticket = build_train_intention(original)
    if simple_ticket:
        # Keep original task attributes, but an explicitly pure ticket request never authorises planning.
        result["intents"] = [intent for intent in result.get("intents", []) if intent.get("type") == "train_ticket"] or simple_ticket["intents"]
        result["agent_schedule"] = [task for task in result.get("agent_schedule", []) if task.get("agent_name") == "train_ticket"] or simple_ticket["agent_schedule"]
    if not result.get("agent_schedule"):
        allowed = {
            "train_ticket", "itinerary_planning", "hotel_search", "restaurant_search", "scenic_search",
            "information_query", "preference", "memory_query", "rag_knowledge", "expense_tracking",
            "currency_conversion", "translation", "visa_info",
        }
        result["agent_schedule"] = [
            {"agent_name": intent["type"], "priority": 2 if intent["type"] == "itinerary_planning" else 1,
             "reason": "继续原始请求", "expected_output": "原任务结果"}
            for intent in result.get("intents", []) if isinstance(intent, dict) and intent.get("type") in allowed
        ]
    for field, alias in (("origin", "from"), ("destination", "to"), ("start_date", "date")):
        value = ticket.get(alias) or entities.get(field) or (entities.get("date") if field == "start_date" else "") or event.get(field)
        if not value and simple_ticket:
            value = simple_ticket["fast_train_ticket"].get(alias)
        if field == "start_date" and value:
            value = parse_train_date(str(value))
            # Invalid/past dates in an old pending record still require clarification.
            if not value:
                event[field] = entities["date"] = ticket[alias] = ""
        if value:
            event[field] = value
            entities["date" if field == "start_date" else field] = value
            ticket[alias] = value
    if simple_ticket:
        for key, value in simple_ticket["fast_train_ticket"].items():
            ticket.setdefault(key, value)
    result.update({"original_query": original, "key_entities": entities, "fast_event": event})
    if any(task.get("agent_name") == "train_ticket" for task in result["agent_schedule"]):
        result["fast_train_ticket"] = ticket
    return result


def missing_slots(pending: dict) -> list[str]:
    result = _canonical_pending(pending)
    event = result["fast_event"]
    explicit = event.get("missing_info") or []
    explicit = explicit if isinstance(explicit, list) else []
    fields = [field for field in explicit if field in _ENTITY_FIELDS and not event.get(_ENTITY_FIELDS[field])]
    schedule = {task.get("agent_name") for task in result.get("agent_schedule", [])}
    required = ["出发地", "目的地", "出发日期"] if "train_ticket" in schedule else ["出发地", "目的地"] if "itinerary_planning" in schedule else []
    for field in required:
        if not event.get(_ENTITY_FIELDS[field]) and field not in fields:
            fields.append(field)
    return fields


def merge_clarification(pending: dict, answer: str) -> dict | None:
    """Return the same task with filled slots; None means a genuine new topic/unsupported answer."""
    result = _canonical_pending(pending)
    missing = missing_slots(result)
    if not missing:
        return None
    # Only a short slot response is accepted here. A new task must be recognised afresh.
    if _NEW_TOPIC.search(answer) or len(answer) > 80:
        return None
    event = result["fast_event"]
    values = {}
    if _UNSURE.fullmatch(answer.strip()):
        result["needs_clarification"] = True
        result["clarification_question"] = "确定后告诉我就能继续查票。" + _QUESTIONS.get(missing[0], "请补充缺失信息。")
        return result
    date = parse_train_date(answer)
    if "出发日期" in missing and date:
        values["出发日期"] = date
    if "天数" in missing:
        days = re.fullmatch(r"\s*(\d{1,2})\s*(?:天)?\s*[。！!]?", answer)
        if days and 1 <= int(days[1]) <= 30:
            values["天数"] = int(days[1])
    location_fields = [field for field in missing if field in ("出发地", "目的地")]
    if location_fields:
        target = result.get("clarification_field")
        if target not in location_fields:
            target = location_fields[0]
        # A date word must never be accepted as a city. Handle “上海，明天” safely.
        parts = re.split(r"[，,；;]+", answer.strip())
        route_text = _DATE_TEXT.sub("", answer.strip()) if date else answer.strip()
        route_text = re.sub(r"上午|早上|下午|午后|晚上|傍晚", "", route_text).strip("，,；; ")
        locations = [_place_answer(_DATE_TEXT.sub("", part).strip()) for part in parts]
        locations = [value for value in locations if value]
        match = re.fullmatch(r"(?:从)?(.{2,12}?)(?:到|去|至)(.{2,12}?)(?:出发)?", route_text)
        if match and _place_answer(match[1]) and _place_answer(match[2]):
            values.update({"出发地": _place_answer(match[1]), "目的地": _place_answer(match[2])})
        if not any(field in values for field in location_fields) and len(locations) == 1:
            values[target] = locations[0]
    if "行程目的" in missing and not values and re.fullmatch(r"出差|旅游|探亲|开会|商务|度假", answer.strip()):
        values["行程目的"] = answer.strip()
    if not values:
        if "出发日期" in missing and (_DATE_TEXT.search(answer) or re.fullmatch(r"\d{1,2}(?:日|号)?", answer.strip())):
            result["needs_clarification"] = True
            result["clarification_question"] = "暂不能使用这个日期，请提供有效且未过去的出发日期。"
            return result
        return None
    for slot, value in values.items():
        event[_ENTITY_FIELDS[slot]] = value
    entities = result["key_entities"]
    for key in ("origin", "destination"):
        if event.get(key):
            entities[key] = event[key]
    if event.get("start_date"):
        entities["date"] = event["start_date"]
    if result.get("fast_train_ticket") is not None:
        ticket = result["fast_train_ticket"]
        ticket.update({"from": event.get("origin", ""), "to": event.get("destination", ""), "date": event.get("start_date", "")})
        if re.search(r"明早|今早|上午|早上", answer):
            ticket["period"] = "morning"
        elif re.search(r"今晚|明晚|晚上|傍晚", answer):
            ticket["period"] = "evening"
        elif re.search(r"下午|午后", answer):
            ticket["period"] = "afternoon"
    event["missing_info"] = missing
    remaining = missing_slots(result)
    event["missing_info"] = remaining
    result["needs_clarification"] = bool(remaining)
    result["clarification_field"] = remaining[0] if remaining else ""
    route = "到".join(str(event.get(field) or "待补充") for field in ("origin", "destination"))
    question = _QUESTIONS.get(remaining[0], "请补充缺失信息。") if remaining else ""
    result["clarification_question"] = f"{route}，{question}" if remaining == ["出发日期"] else question
    # Preserve every constraint in the original request; structured parameters carry the filled slots.
    result["rewritten_query"] = result["original_query"] + "。已补充：" + "；".join(
        f"{slot}={event[_ENTITY_FIELDS[slot]]}" for slot in _ENTITY_FIELDS if event.get(_ENTITY_FIELDS[slot])
    )
    result["reasoning"] = "补齐原任务所需信息，保留原调度"
    return result
