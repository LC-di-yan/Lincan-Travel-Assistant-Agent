"""SSE 流式对话端点"""
import json
import logging
import asyncio
import re
import time

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from server.models import ChatRequest
from server.session import session_manager
from context.session_focus_state import SessionFocusState
from utils.circuit_breaker import CircuitOpenError
from utils.llm_resilience import retry_with_backoff
from utils.json_parser import robust_json_parse
from config import RESILIENCE_CONFIG
from agentscope.message import Msg

logger = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────────────────────
# 追问（clarification）合并的护栏
#   历史问题：只要 session.pending_intention 不为空，用户下一句话
#   就会被无条件当成「缺失字段的答案」。例如追问「出发地」时用户
#   问「北京有什么推荐酒店」，整句话被写成 origin，最终 12306 查询
#   变成 BJP→BJP，行程规划还拿它当需求，表现为「已读乱回」。
# ─────────────────────────────────────────────────────────────
PENDING_TTL_SEC = 300.0  # 追问超过 5 分钟自动失效

# 出现这些词，说明用户在开新话题，而不是在回答「出发地/目的地」
_TOPIC_SWITCH_HINTS = (
    "酒店", "住宿", "民宿", "房源", "天气", "景点", "美食", "餐厅", "小吃",
    "推荐", "攻略", "门票", "机票", "火车票", "高铁", "行程", "规划",
    "怎么", "如何", "什么", "哪些", "为什么", "吗", "呢", "?", "？",
    "帮我", "我想", "我要", "能不能", "可以", "介绍", "对比",
)

_PLACE_PREFIXES = ("从", "去", "到", "自")
_PLACE_SUFFIXES = ("出发", "起飞", "走")


def _normalize_place(text: str) -> str:
    """把「从上海出发」这类回答收敛成「上海」"""
    t = (text or "").strip().strip("。，,！!、 ")
    for suf in _PLACE_SUFFIXES:
        if t.endswith(suf):
            t = t[: -len(suf)]
    for pre in _PLACE_PREFIXES:
        if t.startswith(pre):
            t = t[len(pre):]
            break
    return t.strip("。，,！!、 ")


def _looks_like_place(text: str) -> bool:
    """判断这句话更像一个地名，而不是一个完整问题"""
    t = (text or "").strip()
    if not t or len(t) > 12:
        return False
    if any(h in t for h in _TOPIC_SWITCH_HINTS):
        return False
    return True


def _is_answer_to_missing(text: str, missing: list) -> bool:
    """用户这句话是否真的在回答追问的缺失字段"""
    if not missing:
        return False
    t = (text or "").strip()
    for m in missing:
        if m in ("出发地", "目的地"):
            if not _looks_like_place(t):
                return False
        elif m in ("出发日期", "天数"):
            if not re.search(r"\d", t):
                return False
        else:
            if len(t) > 30:
                return False
    return True


@router.post("/api/chat")
async def chat(request: ChatRequest):
    import time as _time
    _t_request_start = _time.monotonic()
    logger.info(f"[CHAT] user={request.user_id}, msg={request.message[:50]}")

    try:
        _t0 = _time.monotonic()
        session = await session_manager.get_or_create(request.user_id, request.session_id)
        _t_session = (_time.monotonic() - _t0) * 1000
        print(f"[TIMING] Session get/create took {_t_session:.0f}ms", flush=True)
    except Exception as e:
        logger.exception("[CHAT] session creation failed")
        async def error_stream():
            from utils.llm_errors import friendly

            yield _sse("error", {"message": f"会话创建失败：{friendly(e)}"})
        return EventSourceResponse(error_stream())

    async def _stream():
        try:
            try:
                session.circuit_breaker.raise_if_open()
            except CircuitOpenError:
                yield _sse("error", {"message": "服务暂时不可用，请稍后再试"})
                return

            rc = RESILIENCE_CONFIG
            max_retries = rc.get("max_retries", 2)

            # ── 「列出来 / 全部 / 展开」：展开上一轮的列表结果，不调模型、不联网 ──
            from server.utils.list_expander import build_expand_payload, is_expand_request

            if session.focus_state.last_list_result and is_expand_request(request.message):
                expand_payload = build_expand_payload(session.focus_state.last_list_result)
                if expand_payload:
                    logger.info("[CHAT] expand last list result: %s", expand_payload.get("agent_name"))
                    yield _sse("thinking", {"status": "analyzing_intent"})
                    yield _sse("agent_result", expand_payload)
                    _expand_text = (expand_payload.get("data") or {}).get("answer", "")
                    yield _sse("complete", {
                        "status": "completed",
                        "intention": {"intents": [], "key_entities": {}},
                        "agents_executed": 1,
                        "results": [expand_payload],
                        "expanded": True,
                    })
                    await session.memory_manager.add_message_async("assistant", _expand_text[:500])
                    session.messages_since_summary += 1
                    return

            yield _sse("thinking", {"status": "analyzing_intent"})

            # 诊断日志
            print(f"[DEBUG] sid={session.session_id}, pending={'set' if session.pending_intention else 'None'}, msg={request.message[:60]}", flush=True)

            # 合并后的完整意图数据；非 None 时跳过 LLM 意图识别直接进入调度
            merged_intention_data = None

            # 检查是否为对追问的响应：合并原始意图上下文 + 回填 fast_event
            # ── 护栏：追问超时、或用户明显在换话题 → 丢弃 pending，走正常意图识别 ──
            if session.pending_intention is not None:
                _fe = session.pending_intention.get("fast_event", {}) or {}
                _missing = list(_fe.get("missing_info", []) or [])
                if not _missing and _fe:
                    if not _fe.get("origin") and _fe.get("destination"):
                        _missing.append("出发地")
                    elif not _fe.get("destination"):
                        _missing.append("目的地")
                _age = time.monotonic() - getattr(session, "pending_since", 0.0)
                if _age > PENDING_TTL_SEC or not _is_answer_to_missing(request.message, _missing):
                    _reason = "expired" if _age > PENDING_TTL_SEC else "new_topic"
                    print(f"[DEBUG] pending dropped ({_reason}): msg={request.message[:40]!r}, missing={_missing}, age={_age:.0f}s", flush=True)
                    logger.info(f"[CHAT] clarification dropped ({_reason}), treat as new topic: {request.message[:40]}")
                    session.pending_intention = None

            if session.pending_intention is not None:
                pending = session.pending_intention
                original = pending.get("rewritten_query", request.message)
                fe = pending.get("fast_event", {})
                if not isinstance(fe, dict):
                    fe = {}
                missing = fe.get("missing_info", []) or []

                print(f"[DEBUG] merge start: missing_info={missing}, fe.keys={list(fe.keys())[:6] if fe else 'empty'}", flush=True)

                # 兜底：如果 missing_info 为空，自动从 fast_event 检测缺失实体
                if not missing and fe:
                    if not fe.get("origin") and fe.get("destination"):
                        missing.append("出发地")
                    elif not fe.get("destination"):
                        missing.append("目的地")
                    if missing:
                        print(f"[DEBUG] auto-detected missing: {missing}", flush=True)

                # 回填 fast_event：将用户回复写入缺失字段
                _ans = _normalize_place(request.message) or request.message
                patched_fe = dict(fe)
                patched_fe.pop("missing_info", None)
                for m in missing:
                    if m == "出发地":
                        patched_fe["origin"] = _ans
                    elif m == "目的地":
                        patched_fe["destination"] = _ans
                    elif m == "出发日期":
                        patched_fe["start_date"] = request.message
                    elif m == "行程目的":
                        patched_fe["trip_purpose"] = request.message
                    elif m == "天数":
                        try:
                            days = int(re.search(r'\d+', request.message).group())
                            patched_fe["duration_days"] = days
                        except Exception:
                            pass

                # 根据缺失信息类型，将用户回复自然转换为上下文
                missing_map = {
                    "出发地": f"从{_ans}出发",
                    "出发日期": f"{request.message}出发",
                    "目的地": f"去{_ans}",
                    "行程目的": f"目的是{request.message}",
                    "天数": f"行程{request.message}天",
                }
                clues = []
                for m in missing:
                    if m in missing_map:
                        clues.append(missing_map[m])
                if fe.get("destination") and "目的地" not in missing:
                    clues.append(f"去{fe['destination']}")
                if fe.get("origin") and "出发地" not in missing:
                    clues.append(f"从{fe['origin']}出发")
                if fe.get("start_date") and "出发日期" not in missing:
                    clues.append(f"{fe['start_date']}出发")

                known_parts = []
                if fe.get("destination"): known_parts.append(f"目的地是{fe['destination']}")
                if fe.get("start_date"): known_parts.append(f"出发日期{fe['start_date']}")
                if fe.get("duration_days"): known_parts.append(f"行程{fe['duration_days']}天")

                if clues:
                    request.message = "。".join(clues)
                elif known_parts:
                    request.message = f"原始需求: {original}。用户补充: {request.message}"
                else:
                    request.message = f"原始需求: {original}。用户补充: {request.message}"

                # ── 构建合并后的意图数据（跳过 LLM 意图识别）──
                agent_schedule = []
                intents_list = []
                if patched_fe.get("origin") and patched_fe.get("destination"):
                    agent_schedule.append({"agent_name": "train_ticket", "priority": 1, "reason": "查询交通方式", "expected_output": "车次列表"})
                    agent_schedule.append({"agent_name": "itinerary_planning", "priority": 2, "reason": "规划行程", "expected_output": "行程计划"})
                    intents_list.append({"type": "itinerary_planning", "confidence": 0.95, "description": "差旅规划", "reason": "出发地和目的地已明确"})
                elif patched_fe.get("destination"):
                    agent_schedule.append({"agent_name": "information_query", "priority": 1, "reason": "查询目的地信息", "expected_output": "目的地信息"})
                    intents_list.append({"type": "information_query", "confidence": 0.9, "description": "信息查询", "reason": "查询目的地相关信息"})

                merged_intention_data = {
                    "reasoning": f"补全缺失信息{missing}后直接调度",
                    "intents": intents_list,
                    "key_entities": {"origin": patched_fe.get("origin"), "destination": patched_fe.get("destination")},
                    "fast_event": patched_fe,
                    "rewritten_query": request.message,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "agent_schedule": agent_schedule,
                }

                session.pending_intention = None
                print(f"[DEBUG] merged: {request.message[:100]}, fe={json.dumps(patched_fe, ensure_ascii=False)[:200]}", flush=True)
                logger.info(f"[CHAT] merged clarification: {request.message[:100]}")

            # 长期记忆总结：累积 ≥10 条消息后才触发，后台并行执行不阻塞
            from agents.intention_agent import _fast_match
            _is_fast = _fast_match(request.message) is not None
            if not _is_fast and session.messages_since_summary >= 10:
                async def _refresh_summary():
                    try:
                        _t0 = _time.monotonic()
                        new_summary = await session.memory_manager.get_long_term_summary_async()
                        _dt = (_time.monotonic() - _t0) * 1000
                        print(f"[TIMING] Long-term summary (bg) took {_dt:.0f}ms", flush=True)
                        if new_summary:
                            session.long_term_summary = new_summary
                        session.messages_since_summary = 0
                    except Exception as e:
                        logger.warning(f"[CHAT] background summary failed: {e}")
                asyncio.create_task(_refresh_summary())

            _t0 = _time.monotonic()
            recent_context = session.memory_manager.short_term.get_recent_context(n_turns=3)

            context_messages = []
            if session.long_term_summary:
                context_messages.append(Msg(name="system", content=session.long_term_summary, role="system"))

            # 注入当前会话焦点提示（如焦点城市），帮助意图识别消解"附近"等指代
            focus_hint = session.focus_state.build_focus_hint()
            if focus_hint:
                context_messages.append(Msg(name="system", content=focus_hint, role="system"))

            for msg in recent_context:
                context_messages.append(Msg(name=msg["role"], content=msg["content"], role=msg["role"]))
            context_messages.append(Msg(name="user", content=request.message, role="user"))
            _t_context = (_time.monotonic() - _t0) * 1000
            print(f"[TIMING] Context preparation took {_t_context:.0f}ms", flush=True)

            # 注入用户长期偏好（帮助意图识别推断缺失信息如出发地）
            try:
                lt = session.memory_manager.long_term
                prefs = lt.get_preference()
                if prefs:
                    pref_parts = []
                    if prefs.get("home_location"):
                        pref_parts.append(f"home_location: {prefs['home_location']}")
                    if pref_parts:
                        context_messages.insert(0, Msg(name="system",
                            content="[用户偏好] " + "; ".join(pref_parts), role="system"))
            except Exception:
                pass

            if merged_intention_data is not None:
                # 追问合并后直接使用回填数据，跳过 LLM 意图识别
                intention_data = merged_intention_data
                intention_result = Msg(name="IntentionAgent", content=json.dumps(intention_data, ensure_ascii=False), role="assistant")
                print(f"[TIMING] Intention agent SKIPPED (merged data), schedule={[a['agent_name'] for a in merged_intention_data.get('agent_schedule', [])]}", flush=True)
            else:
                try:
                    _t_intention_start = _time.monotonic()
                    intention_result = await retry_with_backoff(
                        lambda: session.intention_agent.reply(context_messages),
                        max_retries=max_retries,
                        base_delay_sec=rc.get("retry_base_delay_sec", 0.5),
                        max_delay_sec=rc.get("retry_max_delay_sec", 8.0),
                    )
                    _t_intention = (_time.monotonic() - _t_intention_start) * 1000
                    session.circuit_breaker.record_success()
                    _msg = f"[TIMING] Intention agent done in {_t_intention:.0f}ms"
                    logger.info(_msg)
                    print(_msg, flush=True)
                except Exception as e:
                    session.circuit_breaker.record_failure()
                    from utils.llm_errors import describe, friendly

                    logger.error("[CHAT] intention agent failed: %s", describe(e))
                    yield _sse("error", {"message": f"意图识别失败：{friendly(e)}"})
                    return

                intention_data = robust_json_parse(
                    getattr(intention_result, "content", ""),
                    fallback={"intents": [], "error": "parse_failed"},
                )
            if "error" in intention_data:
                yield _sse("error", {"message": "无法理解您的需求，请重新描述"})
                return

            logger.info("[CHAT] sending intention event")
            yield _sse("intention", intention_data)

            # 更新会话焦点状态
            session.focus_state.update_from_intention(intention_data)

            # 关键实体缺失门控：暂停执行，反问用户
            if intention_data.get("needs_clarification"):
                question = intention_data.get("clarification_question", "请提供更多信息")
                fe_debug = intention_data.get("fast_event", {}) or {}
                mi_debug = fe_debug.get("missing_info", []) or []
                print(f"[DEBUG] clarification gating: question={question}, missing_info={mi_debug}, fe={list(fe_debug.keys())[:8] if fe_debug else 'empty'}", flush=True)
                logger.info(f"[CHAT] clarification needed: {question}")
                session.pending_intention = intention_data
                session.pending_since = time.monotonic()  # 追问超时计时起点
                session.last_active = _time.monotonic()  # 防止session被LRU淘汰
                yield _sse("clarification", {
                    "question": question,
                    "missing_info": mi_debug,
                })
                await session.memory_manager.add_message_async("user", request.message)
                await session.memory_manager.add_message_async("assistant", question)
                session.messages_since_summary += 2
                return  # 提前结束，不执行调度

            # 没有任何可执行 agent → 给一个明确回复，避免出现空白气泡
            if not intention_data.get("agent_schedule"):
                _fallback = (
                    "我可以帮你做这些：\n"
                    "· 查天气、火车票/机票、酒店、景点、美食\n"
                    "· 差旅标准、报销政策等知识库问答\n"
                    "· 行程规划、记账、汇率换算、翻译\n"
                    "直接说需求就行，比如「北京明天天气」「上海到北京的火车票」。"
                )
                logger.info("[CHAT] empty agent_schedule → capability fallback")
                yield _sse("clarification", {"question": _fallback, "missing_info": []})
                await session.memory_manager.add_message_async("user", request.message)
                await session.memory_manager.add_message_async("assistant", _fallback)
                session.messages_since_summary += 2
                return

            yield _sse("dispatching", {"agents": intention_data.get("agent_schedule", [])})

            # 将焦点状态注入 intention_data，供编排器和 skill 使用
            intention_data["session_focus"] = {
                "focus_city": session.focus_state.focus_city,
                "last_search_city": session.focus_state.last_search_city,
                "current_trip_destination": session.focus_state.current_trip_destination,
            }
            intention_result = Msg(
                name="IntentionAgent",
                content=json.dumps(intention_data, ensure_ascii=False),
                role="assistant",
            )

            await session.memory_manager.add_message_async("user", request.message)
            session.messages_since_summary += 1

            # ---- 编排阶段：Task + 实时结果推送 ----
            yield _sse("thinking", {"status": "executing_agents"})
            logger.info("[CHAT] starting orchestrator task")

            orchestration_result = None
            orchestration_error = None

            result_queue: asyncio.Queue = asyncio.Queue()
            session.orchestrator.result_queue = result_queue

            async def run_orchestrator():
                nonlocal orchestration_result
                try:
                    _t_orch_start = _time.monotonic()
                    orchestration_result = await retry_with_backoff(
                        lambda: session.orchestrator.reply(intention_result),
                        max_retries=max_retries,
                        base_delay_sec=rc.get("retry_base_delay_sec", 0.5),
                        max_delay_sec=rc.get("retry_max_delay_sec", 8.0),
                    )
                    _t_orch = (_time.monotonic() - _t_orch_start) * 1000
                    _msg = f"[TIMING] Orchestrator done in {_t_orch:.0f}ms"
                    logger.info(_msg)
                    print(_msg, flush=True)
                    session.circuit_breaker.record_success()
                except Exception as e:
                    nonlocal orchestration_error
                    orchestration_error = e
                    session.circuit_breaker.record_failure()

            task = asyncio.create_task(run_orchestrator())

            # 从队列实时读取子 Agent 结果并推送
            while not task.done():
                try:
                    result = await asyncio.wait_for(result_queue.get(), timeout=5.0)
                    event_type = result.get("type", "agent_result")
                    agent_name = result.get("agent_name")
                    logger.info(f"[CHAT] real-time {event_type}: {agent_name}")
                    yield _sse(event_type, result)
                except asyncio.TimeoutError:
                    yield {"comment": "keepalive"}

            await task
            logger.info("[CHAT] orchestrator task finished")

            # 排空队列中剩余结果
            while not result_queue.empty():
                result = await result_queue.get()
                event_type = result.get("type", "agent_result")
                logger.info(f"[CHAT] drain remaining {event_type}: {result.get('agent_name')}")
                yield _sse(event_type, result)

            if orchestration_error:
                from utils.llm_errors import describe, friendly

                logger.error(f"[CHAT] orchestrator error: {describe(orchestration_error)}")
                yield _sse("error", {"message": friendly(orchestration_error)})
                return

            result_data = robust_json_parse(
                getattr(orchestration_result, "content", ""),
                fallback={"results": [], "error": "parse_failed"},
            )

            # 记住本轮的列表型结果（车票/酒店/餐厅/景点），供后续「列出来」展开
            from server.utils.list_expander import remember_list_result

            remember_list_result(session, result_data)

            yield _sse("complete", result_data)

            # 助手消息存自然语言摘要（非原始 JSON），便于追问时意图识别 LLM 提取上下文
            from server.utils.assistant_summary import build_assistant_summary
            assistant_summary = build_assistant_summary(result_data)
            await session.memory_manager.add_message_async("assistant", assistant_summary)
            session.messages_since_summary += 1
            _t_total = (_time.monotonic() - _t_request_start) * 1000
            _msg = f"[TIMING] Total request done in {_t_total:.0f}ms"
            logger.info(_msg)
            print(_msg, flush=True)

        except Exception as e:
            from utils.llm_errors import describe, friendly

            logger.error("[CHAT] SSE stream error: %s", describe(e))
            yield _sse("error", {"message": friendly(e)})

    async def event_stream():
        # 同一会话串行：session.orchestrator.result_queue / pending_intention 是
        # 会话级共享状态，两个并发请求会互相覆盖，导致其中一条静默返回空结果
        # （2026-10-20 全量测试：并发「酒店 + 天气」，酒店那条 0 个 agent_result）。
        async with session.chat_lock:
            async for chunk in _stream():
                yield chunk

    return EventSourceResponse(event_stream())


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}
