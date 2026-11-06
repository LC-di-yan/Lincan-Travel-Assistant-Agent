"""决策层：题面与状态模板（NeoHorse-Jev-4B 专用）。

为什么单独一个文件：
    - 意图枚举、门控措辞、state 模板是**调优对象**，会被反复改；
      与 HTTP 客户端（decision_engine.py）分开，改提示词不用碰网络层。
    - tools/bench_decision.py 与线上链路共用同一份题面，保证"评测的"就是"上线的"。

模型能力边界（实测，见 docs/decision-layer-dev-plan.md 第 2 节）：
    - choice 头比独立 noul 头准（84% vs 68%）→ 主意图用 choice，门控只做辅助；
    - 同一次请求内 choice 与 noul 可能自相矛盾 → 由 decision_engine 做冲突消解；
    - state 里给"场景 + 最近对话"比裸 query 明显更稳。
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ── 13 类意图（与 agents/intention_agent.py 的 prompt 枚举一致）──────────
INTENT_CRITERIA: Dict[str, str] = {
    "itinerary_planning": "规划多天行程、安排出差或旅行日程",
    "train_ticket": "查询火车票、高铁车次",
    "hotel_search": "查找酒店、民宿等住宿",
    "restaurant_search": "查找餐厅、美食、小吃",
    "scenic_search": "查找景点、公园、游玩地点",
    "information_query": "查询天气等实时信息",
    "memory_query": "回忆历史对话、过往行程或个人偏好",
    "preference": "记录或修改用户偏好",
    "expense_tracking": "记账、报销、费用登记",
    "currency_conversion": "汇率换算",
    "translation": "翻译文本",
    "rag_knowledge": "查询知识库、差旅政策、公司规定",
    "chitchat": "闲聊、寒暄、陈述日常经历",
}

# 意图 → OrchestrationAgent 里注册的 agent 名（chitchat 不调度）
INTENT_TO_AGENT: Dict[str, Optional[str]] = {
    "itinerary_planning": "itinerary_planning",
    "train_ticket": "train_ticket",
    "hotel_search": "hotel_search",
    "restaurant_search": "restaurant_search",
    "scenic_search": "scenic_search",
    "information_query": "information_query",
    "memory_query": "memory_query",
    "preference": "preference",
    "expense_tracking": "expense_tracking",
    "currency_conversion": "currency_conversion",
    "translation": "translation",
    "rag_knowledge": "rag_knowledge",
    "chitchat": None,
}

# 期望输出（写进 agent_schedule，供编排层展示）
INTENT_EXPECTED: Dict[str, str] = {
    "itinerary_planning": "行程计划",
    "train_ticket": "车次列表",
    "hotel_search": "酒店列表",
    "restaurant_search": "餐厅列表",
    "scenic_search": "景点列表",
    "information_query": "查询结果",
    "memory_query": "历史记忆",
    "preference": "偏好确认",
    "expense_tracking": "记账结果",
    "currency_conversion": "汇率换算结果",
    "translation": "译文",
    "rag_knowledge": "知识库答案",
    "chitchat": "",
}

# ── 6 个能力门控（noul）────────────────────────────────────────────
# 措辞原则：问"是否明确提出请求"，而不是"是否提到相关词"——
# 后者会把"我住在北京朝阳区"判成想找酒店（KB-001）。
GATES: Dict[str, str] = {
    "want_trip": "用户是否明确要求规划多天行程、出差或旅行安排？",
    "want_hotel": "用户是否明确要求查找或推荐酒店、民宿等住宿？",
    "want_restaurant": "用户是否明确要求查找或推荐餐厅、美食？",
    "want_scenic": "用户是否明确要求查找或推荐景点、游玩地点？",
    "want_info": "用户是否明确要求查询天气等实时信息？",
    "want_memory": "用户是否在询问自己过去去过哪里、做过什么？",
}

# 门控 → 对应意图（冲突消解 & 多意图扩展用）
GATE_TO_INTENT: Dict[str, str] = {
    "want_trip": "itinerary_planning",
    "want_hotel": "hotel_search",
    "want_restaurant": "restaurant_search",
    "want_scenic": "scenic_search",
    "want_info": "information_query",
    "want_memory": "memory_query",
}

# 只有这些意图允许"决策层直接接管"（不需要实体抽取）。
# 酒店/餐厅/景点/天气/火车票/行程都依赖城市和日期抽取，接管会丢参数 → 永远走 LLM。
RESCUEABLE_INTENTS = frozenset({
    "rag_knowledge",
    "preference",
    "expense_tracking",
    "currency_conversion",
    "translation",
})

# 已知容易被正则误判的 fast-route 分支 → 需要决策层复核（veto）
RISKY_AGENTS = frozenset({
    "hotel_search",
    "restaurant_search",
    "scenic_search",
    "memory_query",
})

STATE_TEMPLATE = (
    "【场景】旅行与差旅智能助手。用户可能提出查询请求，也可能只是闲聊、陈述经历或回忆。\n"
    "【用户本轮输入】{query}\n"
    "【最近对话】{history}\n"
    "【已知实体】{entities}"
)


def build_state(
    query: str,
    history: Optional[List[str]] = None,
    entities: Optional[Dict[str, str]] = None,
) -> str:
    """拼 state。history 取最近 2 轮（实测更长没有额外收益，反而拖慢）。"""
    hist = ""
    if history:
        tail = [h.strip() for h in history[-2:] if h and h.strip()]
        hist = " / ".join(h[-120:] for h in tail) or "无"
    else:
        hist = "无"

    if entities:
        ent = "，".join(f"{k}={v}" for k, v in entities.items() if v)
    else:
        ent = "无"

    return STATE_TEMPLATE.format(query=query.strip(), history=hist or "无", entities=ent or "无")


def build_questions() -> Dict[str, dict]:
    """一次请求 ≤16 题：1 前置门控 + 1 主意图 + 1 反问 + 6 能力门控 = 9 题。"""
    questions: Dict[str, dict] = {
        "is_request": {
            "type": "noul",
            "instructions": "用户这一句是在向助手提出查询或请求吗？闲聊、陈述经历、自言自语算否。",
        },
        "intent": {
            "type": "choice",
            "instructions": "用户最主要的意图是什么？",
            "criteria": INTENT_CRITERIA,
        },
        "need_clarify": {
            "type": "noul",
            "instructions": "是否缺少出发地、目的地或日期等关键信息，需要先反问用户？",
        },
    }
    for name, text in GATES.items():
        questions[name] = {"type": "noul", "instructions": text}
    return questions


def intention_from_decision(intent: str, confidence: float, query: str) -> Optional[dict]:
    """把决策结果转成 IntentionAgent 的对外契约（疑似 JSON 结构）。

    仅用于 RESCUEABLE_INTENTS：这些技能只吃 query，不需要 key_entities / fast_event。
    其余意图返回 None，调用方应继续走 LLM。
    """
    if intent not in RESCUEABLE_INTENTS:
        return None
    agent = INTENT_TO_AGENT.get(intent)
    if not agent:
        return None
    return {
        "reasoning": f"决策层直通: {intent} p={confidence:.2f}",
        "intents": [{
            "type": intent,
            "confidence": round(float(confidence), 3),
            "description": INTENT_CRITERIA.get(intent, intent),
            "reason": "NeoHorse-Jev-4B 决策层高置信直通",
        }],
        "key_entities": {},
        "fast_event": {},
        "rewritten_query": query,
        "needs_clarification": False,
        "clarification_question": "",
        "agent_schedule": [{
            "agent_name": agent,
            "priority": 2 if intent == "itinerary_planning" else 1,
            "reason": INTENT_CRITERIA.get(intent, ""),
            "expected_output": INTENT_EXPECTED.get(intent, ""),
        }],
    }
