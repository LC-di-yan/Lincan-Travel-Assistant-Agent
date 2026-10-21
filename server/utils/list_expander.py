"""「列出来 / 全部 / 展开」这类追问的处理。

背景（2026-10-21）：
    用户先问「明早从北京去上海的高铁票有哪些」，卡片只给了前 3 趟；
    接着说「列出来」，系统把它当成新查询又跑了一遍，仍然只有 3 趟。

做法：
    把上一次成功的「列表型」结果记在会话焦点状态里（车票/酒店/餐厅/景点），
    当用户说「列出来/全部/详细/展开」时，直接用上次的结果拼出完整清单，
    不再调用模型、也不再联网查一次。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

LIST_AGENTS = ("train_ticket", "hotel_search", "restaurant_search", "scenic_search")
LIST_RESULT_TTL = 1800  # 30 分钟内有效

# 仅仅表示「把刚才的结果展开」的说法（整句匹配，避免误伤正常提问）
_EXPAND_EXACT = {
    "列出来", "列一下", "全部列出来", "都列出来", "全部", "所有", "所有车次", "全部车次",
    "详细", "详细点", "具体", "具体点", "展开", "展开看看", "展开全部", "都列出来看看",
    "还有哪些", "还有哪些车次", "都有哪些", "完整的", "全部显示", "显示全部",
}
_EXPAND_PREFIX = ("列出来", "列一下", "全部列", "都列", "展开", "显示全部")


def is_expand_request(message: str) -> bool:
    t = (message or "").strip().strip("。！？，,.!?～~ \t")
    if not t:
        return False
    if t in _EXPAND_EXACT:
        return True
    # 允许「列出来吧」「全部列一下」这类少量追加
    return len(t) <= 10 and any(t.startswith(p) for p in _EXPAND_PREFIX)


def remember_list_result(session: Any, result_data: Dict[str, Any]) -> None:
    """把本轮成功的列表型结果存进会话焦点，供后续「列出来」使用。"""
    try:
        results = (result_data or {}).get("results") or []
    except AttributeError:
        return
    for r in reversed(results):
        if not isinstance(r, dict):
            continue
        agent = r.get("agent_name")
        if agent in LIST_AGENTS and r.get("status") == "success":
            data = r.get("data") or {}
            session.focus_state.last_list_result = {
                "agent": agent,
                "data": data,
                "ts": time.time(),
            }
            return


def _format_trains(data: Dict[str, Any]) -> str:
    res = data.get("results") or {}
    trains = res.get("trains") or []
    if not trains:
        return res.get("summary") or "没有查到车次，可以换个日期试试。"
    head = f"{res.get('from', '')}→{res.get('to', '')}（{res.get('date', '')}）共 {len(trains)} 趟："
    lines = [head, ""]  # 空行 + 有序列表，Markdown 才会逐条换行
    for i, t in enumerate(trains, 1):
        seats = []
        for label, key in (("二等座", "second_class"), ("一等座", "first_class"), ("商务座", "business")):
            v = (t.get(key) or "").strip()
            if v and v != "无":
                seats.append(f"{label} {v}")
        seat_text = "｜".join(seats) if seats else "余票紧张"
        lines.append(
            f"{i}. {t.get('train_no', '')} {t.get('depart_time', '')}→{t.get('arrive_time', '')} "
            f"{t.get('duration', '')}｜{seat_text}"
        )
    return "\n".join(lines)


def _format_places(agent: str, data: Dict[str, Any]) -> str:
    res = data.get("results") or data
    key = {
        "hotel_search": "hotels",
        "restaurant_search": "restaurants",
        "scenic_search": "attractions",
    }.get(agent, "")
    items = res.get(key) or []
    if not items:
        return res.get("summary") or "没有更多结果了。"
    label = {"hotel_search": "酒店", "restaurant_search": "餐厅", "scenic_search": "景点"}.get(agent, "结果")
    lines = [f"共 {len(items)} 个{label}：", ""]
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            continue
        name = it.get("name") or ""
        rating = it.get("rating") or ""
        addr = it.get("address") or it.get("location") or ""
        extra = " ".join(x for x in (f"★{rating}" if rating else "", str(addr)) if x)
        lines.append(f"{i}. {name}" + (f"　{extra}" if extra else ""))
    return "\n".join(lines)


def build_expand_payload(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """把「上次的列表结果」拼成一个 agent_result 事件；过期或没有则返回 None。"""
    if not item:
        return None
    if time.time() - float(item.get("ts") or 0) > LIST_RESULT_TTL:
        return None

    agent = item.get("agent") or ""
    data = item.get("data") or {}
    if agent == "train_ticket":
        text = _format_trains(data)
    else:
        text = _format_places(agent, data)
    if not text:
        return None

    # 保留原始结构（卡片要渲染列表），只把摘要换成完整清单
    merged: Dict[str, Any] = dict(data)
    res = dict((data.get("results") or {}))
    res["summary"] = text
    res["expanded"] = True
    merged["results"] = res
    merged["answer"] = text
    merged["expanded"] = True

    return {
        "type": "agent_result",
        "agent_name": agent,
        "priority": 1,
        "status": "success",
        "data": merged,
    }
