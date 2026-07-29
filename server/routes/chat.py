"""SSE 流式对话端点"""
import json
import logging
import asyncio

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from server.models import ChatRequest
from server.session import session_manager
from utils.circuit_breaker import CircuitOpenError
from utils.llm_resilience import retry_with_backoff
from utils.json_parser import robust_json_parse
from config import RESILIENCE_CONFIG
from agentscope.message import Msg

logger = logging.getLogger(__name__)
router = APIRouter()


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
            yield _sse("error", {"message": f"会话创建失败: {str(e)}"})
        return EventSourceResponse(error_stream())

    async def event_stream():
        try:
            try:
                session.circuit_breaker.raise_if_open()
            except CircuitOpenError:
                yield _sse("error", {"message": "服务暂时不可用，请稍后再试"})
                return

            rc = RESILIENCE_CONFIG
            max_retries = rc.get("max_retries", 2)

            yield _sse("thinking", {"status": "analyzing_intent"})

            # 长期记忆总结：仅在有足够历史数据时触发，避免简单查询阻塞
            from agents.intention_agent import _fast_match
            _is_fast = _fast_match(request.message) is not None
            if not _is_fast and (session.messages_since_summary == 0 or session.messages_since_summary >= 10):
                try:
                    _t0 = _time.monotonic()
                    session.long_term_summary = await session.memory_manager.get_long_term_summary_async()
                    _t_summary = (_time.monotonic() - _t0) * 1000
                    print(f"[TIMING] Long-term summary took {_t_summary:.0f}ms", flush=True)
                    session.messages_since_summary = 0
                except Exception as e:
                    logger.warning(f"[CHAT] long_term_summary failed: {e}")
                    session.long_term_summary = ""

            _t0 = _time.monotonic()
            recent_context = session.memory_manager.short_term.get_recent_context(n_turns=3)

            context_messages = []
            if session.long_term_summary:
                context_messages.append(Msg(name="system", content=session.long_term_summary, role="system"))
            for msg in recent_context:
                context_messages.append(Msg(name=msg["role"], content=msg["content"], role=msg["role"]))
            context_messages.append(Msg(name="user", content=request.message, role="user"))
            _t_context = (_time.monotonic() - _t0) * 1000
            print(f"[TIMING] Context preparation took {_t_context:.0f}ms", flush=True)

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
                logger.exception("[CHAT] intention agent failed")
                yield _sse("error", {"message": f"意图识别失败: {str(e)}"})
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
            yield _sse("dispatching", {"agents": intention_data.get("agent_schedule", [])})

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
                logger.error(f"[CHAT] orchestrator error: {orchestration_error}")
                yield _sse("error", {"message": f"执行失败: {str(orchestration_error)}"})
                return

            result_data = robust_json_parse(
                getattr(orchestration_result, "content", ""),
                fallback={"results": [], "error": "parse_failed"},
            )

            yield _sse("complete", result_data)

            await session.memory_manager.add_message_async("assistant", json.dumps(result_data, ensure_ascii=False))
            session.messages_since_summary += 1
            _t_total = (_time.monotonic() - _t_request_start) * 1000
            _msg = f"[TIMING] Total request done in {_t_total:.0f}ms"
            logger.info(_msg)
            print(_msg, flush=True)

        except Exception as e:
            logger.exception("[CHAT] SSE stream error")
            yield _sse("error", {"message": str(e)})

    return EventSourceResponse(event_stream())


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}
