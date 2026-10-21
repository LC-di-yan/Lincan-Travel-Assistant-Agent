"""助手消息摘要生成

把编排结果 result_data 转成自然语言摘要，存入短期记忆。
意图识别 LLM 能从自然语言中提取上下文（城市/品牌/起终点），
而不是从原始 JSON 噪声中挣扎。

不调 LLM，纯结构化提取，零延迟。
"""
from typing import Any

# 智能体内部名 -> 中文名（写进记忆/朗读，避免出现 itinerary_planning 这种内部标识）
_AGENT_LABELS = {
    "itinerary_planning": "行程规划",
    "event_collection": "行程要素提取",
    "hotel_search": "酒店搜索",
    "restaurant_search": "餐厅搜索",
    "scenic_search": "景点搜索",
    "information_query": "信息查询",
    "train_ticket": "火车票查询",
    "expense_tracking": "费用记录",
    "expense_tracker": "费用记录",
    "translation": "翻译",
    "rag_knowledge": "知识库问答",
    "ask_question": "知识库问答",
    "preference": "偏好管理",
    "memory_query": "记忆查询",
    "currency_converter": "汇率换算",
    "currency_conversion": "汇率换算",
    "visa_info": "签证信息",
}


def _label(agent_name: str) -> str:
    return _AGENT_LABELS.get(agent_name, agent_name or "该步骤")


def _clean(text: Any, limit: int = 100) -> str:
    """压缩空白并截断，避免把上游 JSON 错误体整段塞进记忆。"""
    s = " ".join(str(text or "").split())
    return s[:limit] + ("…" if len(s) > limit else "")


def _safe_get(d: Any, *keys, default=None):
    """层层取键，任一层缺失返回 default。"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _summarize_itinerary(inner: dict) -> str:
    """行程规划摘要。"""
    it = inner.get("itinerary", inner) if isinstance(inner, dict) else {}
    title = it.get("title", "行程规划") if isinstance(it, dict) else "行程规划"
    duration = it.get("duration", "") if isinstance(it, dict) else ""
    plans = it.get("daily_plans", []) if isinstance(it, dict) else []
    days = len(plans) if isinstance(plans, list) else 0
    complete = inner.get("planning_complete", True)

    if not complete:
        err = _clean(inner.get("error", "请补充更多信息"))
        return f"行程规划未完成：{err}"

    # 提取关键城市/交通/地点信息
    cities = set()
    transports = []
    locations = []
    _LOCATION_MAX = 6
    for plan in plans if isinstance(plans, list) else []:
        if not isinstance(plan, dict):
            continue
        city = plan.get("city")
        if city:
            cities.add(city)
        for act in plan.get("activities", []) if isinstance(plan.get("activities"), list) else []:
            if isinstance(act, dict):
                t = act.get("transport", "")
                if t and t not in transports:
                    transports.append(t)
                loc = act.get("location") or act.get("name") or ""
                if loc and loc not in locations and len(locations) < _LOCATION_MAX:
                    locations.append(str(loc))
        meals = plan.get("meals", {}) if isinstance(plan.get("meals"), dict) else {}
        for meal_key in ("breakfast", "lunch", "dinner"):
            meal_val = meals.get(meal_key)
            if meal_val:
                mv = str(meal_val)
                if mv not in locations and len(locations) < _LOCATION_MAX:
                    locations.append(mv)

    duration_text = duration or f"{days}天"
    parts = [f"已规划{duration_text}行程：{title}"]
    if cities:
        parts.append(f"目的地：{'/'.join(cities)}")
    if locations:
        parts.append(f"关键地点：{'、'.join(locations)}")
    if transports:
        parts.append(f"交通：{'、'.join(transports[:3])}")
    return "，".join(parts) + "。"


def _summarize_search(agent_name: str, inner: dict) -> str:
    """酒店/餐厅/景点搜索摘要。"""
    summary = inner.get("summary") or inner.get("message") or ""
    count = inner.get("count", 0) or 0
    city = inner.get("city", "")

    label = {
        "hotel_search": "酒店",
        "restaurant_search": "餐厅",
        "scenic_search": "景点",
    }.get(agent_name, "结果")

    # 提取前几个结果的名字
    items_key = {
        "hotel_search": "hotels",
        "restaurant_search": "restaurants",
        "scenic_search": "attractions",
    }.get(agent_name)
    names = []
    if items_key:
        items = inner.get(items_key, []) or []
        if isinstance(items, list):
            for it in items[:3]:
                if isinstance(it, dict) and it.get("name"):
                    names.append(it["name"])

    parts = []
    if city:
        parts.append(f"在{city}")
    if count > 0:
        parts.append(f"找到{count}家{label}")
    else:
        parts.append(f"查询{label}")
    if names:
        parts.append(f"推荐：{'、'.join(names)}")
    if summary and not names:
        parts.append(str(summary)[:80])
    return "".join(parts) + "。"


def _summarize_information(inner: dict) -> str:
    """信息查询摘要（天气等）。"""
    results = inner.get("results", inner)
    summary = ""
    if isinstance(results, dict):
        summary = results.get("summary") or results.get("message") or ""
    if not summary:
        summary = inner.get("summary") or inner.get("answer") or inner.get("message") or ""
    return str(summary)[:150] if summary else "已查询信息。"


def _summarize_train(inner: dict) -> str:
    """火车票查询摘要。"""
    summary = inner.get("summary") or inner.get("message") or ""
    if summary:
        return str(summary)[:150]

    # 提取车次
    tickets = inner.get("tickets", []) or []
    if isinstance(tickets, list) and tickets:
        train_ids = []
        for t in tickets[:3]:
            if isinstance(t, dict):
                tid = t.get("train_id") or t.get("train") or ""
                if tid:
                    train_ids.append(str(tid))
        if train_ids:
            return f"查到车次：{'、'.join(train_ids)}。"
    return "已查询火车票。"


def _summarize_expense(inner: dict) -> str:
    """费用记录摘要。"""
    answer = inner.get("answer") or inner.get("message") or ""
    if answer:
        return str(answer)
    expense = inner.get("expense", {})
    if isinstance(expense, dict):
        category = expense.get("category", "其他")
        amount = expense.get("amount", "")
        return f"已记录{category} {amount} 元。"
    return "费用已记录。"


def _summarize_translation(inner: dict) -> str:
    """翻译摘要。"""
    text = (inner.get("translated_text") or inner.get("translation")
            or inner.get("result") or inner.get("answer") or "")
    return str(text)[:150] if text else "已完成翻译。"


def _summarize_rag(inner: dict) -> str:
    """RAG 知识库摘要。"""
    answer = (inner.get("answer") or inner.get("content")
              or inner.get("result") or inner.get("summary") or "")
    return str(answer)[:200] if answer else "已查询知识库。"


def _summarize_preference(inner: dict) -> str:
    """偏好管理摘要。"""
    answer = inner.get("answer") or inner.get("message") or ""
    return str(answer) if answer else "偏好已更新。"


def _summarize_memory(inner: dict) -> str:
    """记忆查询摘要。"""
    answer = (inner.get("answer") or inner.get("content")
              or inner.get("result") or inner.get("summary") or "")
    return str(answer)[:200] if answer else "已查询记忆。"


def _summarize_event_collection(inner: dict) -> str:
    """事项提取摘要。"""
    summary = inner.get("summary") or inner.get("message") or ""
    return str(summary) if summary else "已提取行程要素。"


def _summarize_one(result: dict) -> str:
    """单个 agent 结果 → 自然语言摘要。"""
    if not isinstance(result, dict):
        return ""

    status = result.get("status", "")
    if status == "error":
        err = _safe_get(result, "data", "error") or _safe_get(result, "data", "message") or ""
        agent = _label(result.get("agent_name", ""))
        err = _clean(err)
        return f"{agent}未完成：{err}" if err else f"{agent}未完成"

    agent = result.get("agent_name", "")
    data = result.get("data", {}) or {}
    inner = data.get("data", data) if isinstance(data, dict) else {}
    if not isinstance(inner, dict):
        inner = {}

    handlers = {
        "itinerary_planning": _summarize_itinerary,
        "hotel_search": _summarize_search,
        "restaurant_search": _summarize_search,
        "scenic_search": _summarize_search,
        "information_query": _summarize_information,
        "train_ticket": _summarize_train,
        "expense_tracking": _summarize_expense,
        "expense_tracker": _summarize_expense,
        "translation": _summarize_translation,
        "rag_knowledge": _summarize_rag,
        "ask_question": _summarize_rag,
        "preference": _summarize_preference,
        "memory_query": _summarize_memory,
        "event_collection": _summarize_event_collection,
        "currency_converter": _summarize_translation,
        "currency_conversion": _summarize_translation,
        "visa_info": _summarize_rag,
    }

    handler = handlers.get(agent)
    if handler:
        try:
            # search 类 handler 需要传 agent_name
            if agent in ("hotel_search", "restaurant_search", "scenic_search"):
                return handler(agent, inner)
            return handler(inner)
        except Exception:
            pass

    # 兜底：尝试常见字段
    for key in ("answer", "content", "result", "message", "summary", "description", "text"):
        v = inner.get(key)
        if isinstance(v, str) and v.strip():
            return v[:150]
    return f"已完成{agent}。"


def build_assistant_summary(result_data: Any) -> str:
    """编排结果 → 自然语言摘要（存入短期记忆）。

    多个 agent 结果用分号分隔，控制在 400 字内（够 LLM 理解上下文）。
    """
    if not isinstance(result_data, dict):
        return str(result_data)[:400] if result_data else ""

    results = result_data.get("results", [])
    if not isinstance(results, list) or not results:
        return "已完成处理。"

    parts = []
    for r in results:
        s = _summarize_one(r)
        if s:
            parts.append(s)

    summary = " ".join(parts)
    if len(summary) > 400:
        summary = summary[:397] + "..."
    return summary
