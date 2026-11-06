"""决策层与 IntentionAgent 的接线（唯一改动点）。

职责边界：
    - 本文件负责"要不要用、怎么用、记什么"，**不负责** HTTP（那是 decision_engine）
      也不负责意图识别本身的兜底（那是 intention_agent）。
    - 任何异常都在这里吞掉：决策层是增强项，不允许它让主链路失败。

四种模式（ALIGO_DECISION_MODE）：
    off     完全不调用（默认）
    shadow  异步旁路，只写 data/decision_shadow/*.jsonl，返回原结果
    assist  同步复核：只在"正则命中高风险分支"时允许否决（veto），不改其他行为
    primary assist + 对 RESCUEABLE_INTENTS 高置信直通（省掉一次 LLM 调用）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from utils.decision_engine import DecisionEngine, get_engine
from utils.decision_schema import (
    GATE_TO_INTENT,
    INTENT_TO_AGENT,
    RESCUEABLE_INTENTS,
    RISKY_AGENTS,
    intention_from_decision,
)
from utils.decision_thresholds import load_thresholds
from utils.decision_types import RouteDecision, ShadowRecord

logger = logging.getLogger(__name__)

# 防止 create_task 的协程被 GC 掉
_pending: set = set()


def _agents_of(intention: Optional[dict]) -> List[str]:
    if not intention:
        return []
    return [x.get("agent_name", "") for x in intention.get("agent_schedule", []) or []]


def _intents_of(intention: Optional[dict]) -> List[str]:
    if not intention:
        return []
    return [x.get("type", "") for x in intention.get("intents", []) or []]


class DecisionHook:
    """一次请求的决策接线结果。"""

    __slots__ = ("fast", "decision", "trace_id", "source", "engine", "query")

    def __init__(self, fast: Optional[dict], decision: Optional[RouteDecision],
                 trace_id: str, source: str, engine: Optional[DecisionEngine], query: str):
        self.fast = fast
        self.decision = decision
        self.trace_id = trace_id
        self.source = source          # "fast" | "decision" | "veto" | "off"
        self.engine = engine
        self.query = query

    def log_outcome(self, path: str, intention: Optional[dict]) -> None:
        """记录最终走了哪条路（供 replay_shadow 算一致率）。"""
        if self.engine is None or not self.trace_id:
            return
        try:
            self.engine.log(ShadowRecord(
                kind="outcome",
                query=self.query[:200],
                trace_id=self.trace_id,
                mode=self.engine.mode,
                final_path=path,
                final_agents=_agents_of(intention),
                final_intents=_intents_of(intention),
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("decision outcome log failed: %s", exc)


async def _shadow(engine: DecisionEngine, query: str, history: List[str],
                  regex_result: Optional[dict], trace_id: str) -> None:
    try:
        decision = await engine.route(query, history)
        if decision is None:
            return
        engine.log(ShadowRecord(
            kind="decision",
            query=query[:200],
            trace_id=trace_id,
            mode=engine.mode,
            decision=decision.to_dict(),
            regex_agents=_agents_of(regex_result),
            regex_intents=_intents_of(regex_result),
            latency_ms=decision.latency_ms,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("shadow decision failed: %s", exc)


def _should_veto(decision: RouteDecision, fast: Optional[dict], th: Dict[str, Any]) -> bool:
    """正则命中高风险分支，但决策层强烈反对 → 撤销，交给 LLM。"""
    if not fast:
        return False
    agents = set(_agents_of(fast))
    if not (agents & RISKY_AGENTS):
        return False

    veto = th.get("veto") or {}
    p_req_below = float(veto.get("p_is_request_below", 0.35))
    p_chat_above = float(veto.get("p_chitchat_above", 0.60))
    p_confident = float(veto.get("min_confident_intent", 0.60))
    margin = float(veto.get("min_agree_margin", 0.15))

    # 1) 判为闲聊且够自信
    if decision.intent == "chitchat" and decision.p_intent >= p_chat_above:
        return True
    # 2) 模型认为"不像请求"，且自己也没有别的把握 → 宁可交给 LLM
    #    （实测 is_request 对祈使句偏低：翻译/记账会被打成 0.1–0.35，
    #      所以必须要求"低置信"才否决，避免误杀正常搜索）
    if decision.p_is_request < p_req_below and decision.p_intent < p_confident:
        return True
    # 3) 决策层指向另一个意图且很自信，同时正则那个分支概率极低
    regex_intents = [i for i in _intents_of(fast) if i]
    if regex_intents and decision.intent not in regex_intents:
        p_regex = float(decision.intent_probs.get(regex_intents[0], 0.0))
        if decision.p_intent >= 0.85 and p_regex <= max(0.05, decision.p_intent - margin * 2):
            return True
    return False


def _should_rescue(decision: RouteDecision, fast: Optional[dict], th: Dict[str, Any]) -> bool:
    """正则没命中，但决策层高置信指向"不需要实体抽取"的意图 → 直接调度。"""
    # 注意：不用 is_request 做前置条件——实测祈使句（翻译/记账）会被打成 0.1–0.35，
    # 用它当门槛会让这些意图永远无法直通。
    if fast or decision.intent == "chitchat":
        return False
    if decision.intent not in RESCUEABLE_INTENTS:
        return False
    if decision.p_intent < float(th.get("p_intent", 0.90)):
        return False
    if decision.intent not in INTENT_TO_AGENT or INTENT_TO_AGENT[decision.intent] is None:
        return False
    # 有冲突说明模型自相矛盾，宁可走 LLM
    if decision.conflicts:
        return False
    return True


async def maybe_use_decision(
    query: str,
    history: Optional[List[str]] = None,
    fast: Optional[dict] = None,
) -> DecisionHook:
    """在 IntentionAgent.reply() 的 fast-route 之后调用。"""
    import uuid

    engine = get_engine()
    if engine is None or not engine.enabled:
        return DecisionHook(fast, None, "", "off", None, query)

    trace_id = uuid.uuid4().hex[:12]
    history = history or []

    # assist 模式只做"否决"：正则没命中时没有必要多付一次 500ms
    if fast is None and engine.mode == "assist":
        return DecisionHook(None, None, trace_id, "off", engine, query)

    # ── shadow：异步旁路，不阻塞 ──
    if engine.mode == "shadow":
        try:
            task = asyncio.create_task(_shadow(engine, query, history, fast, trace_id))
            _pending.add(task)
            task.add_done_callback(_pending.discard)
        except RuntimeError:  # 没有事件循环（同步脚本）
            logger.debug("no running loop, skip shadow decision")
        return DecisionHook(fast, None, trace_id, "fast" if fast else "off", engine, query)

    # ── assist / primary：同步等一次结果 ──
    try:
        decision = await engine.route(query, history)
    except Exception as exc:  # noqa: BLE001
        logger.debug("decision route failed: %s", exc)
        return DecisionHook(fast, None, trace_id, "fast" if fast else "off", engine, query)

    if decision is None:
        return DecisionHook(fast, None, trace_id, "fast" if fast else "off", engine, query)

    th = load_thresholds()
    engine.log(ShadowRecord(
        kind="decision",
        query=query[:200],
        trace_id=trace_id,
        mode=engine.mode,
        decision=decision.to_dict(),
        regex_agents=_agents_of(fast),
        regex_intents=_intents_of(fast),
        latency_ms=decision.latency_ms,
    ))

    # 1) 否决：撤销错误的正则命中
    if _should_veto(decision, fast, th):
        logger.info("[decision] veto fast-route %s -> LLM (intent=%s p=%.2f)",
                    _agents_of(fast), decision.intent, decision.p_intent)
        return DecisionHook(None, decision, trace_id, "veto", engine, query)

    # 2) 直通：正则没命中且决策层很确定
    if engine.mode == "primary" and _should_rescue(decision, fast, th):
        rescue = intention_from_decision(decision.intent, decision.p_intent, query)
        if rescue is not None:
            logger.info("[decision] rescue -> %s (p=%.2f, %sms)",
                        decision.intent, decision.p_intent, decision.latency_ms)
            return DecisionHook(rescue, decision, trace_id, "decision", engine, query)

    return DecisionHook(fast, decision, trace_id, "fast" if fast else "off", engine, query)


def decision_status() -> Dict[str, Any]:
    """健康检查用。"""
    engine = get_engine()
    if engine is None:
        return {"enabled": False, "mode": "off"}
    return engine.status()
