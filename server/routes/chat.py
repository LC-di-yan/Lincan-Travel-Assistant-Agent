"""SSE 流式对话端点"""
import json
import logging
import asyncio
import time

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from anyio import CancelScope

from context.conversation_archive import redact_private_text
from server.models import ChatRequest
from server.auth import CurrentUser, owned_user
from server.personal.access import personal_enabled, secure_personal_site
from server.personal.candidates import build_snapshot, candidates
from server.personal.repository import trip_repository
from server.personal.profile import Profile
from server.personal.service import PersonalError, Trips
from server.session import session_manager
from server.utils.clarification import merge_clarification
from server.utils.conversation_transcript import PENDING_TTL_SEC, TERMINALS, Transcript, restore_checkpoint
from utils.circuit_breaker import CircuitOpenError
from utils.llm_resilience import retry_with_backoff
from utils.as_compat import mk_msg, msg_json
from utils.expense_commands import expense_execution, parse_expense_command
from utils.local_transport import is_transport_question_echo
from utils.preference_parser import explicitly_remembers_preference, parse_preference
from agents.orchestration_agent import normalized_schedule
from agents.trip_workflow import trip_intention
from agents.intention_agent import IntentionAgent, build_expense_intention
from utils.trip_request import is_trip_cancellation, selected_option
from agents.trip_decision import selection_is_current
from config import RESILIENCE_CONFIG

logger = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────────────────────
# 追问（clarification）合并的护栏
#   历史问题：只要 session.pending_intention 不为空，用户下一句话
#   就会被无条件当成「缺失字段的答案」。例如追问「出发地」时用户
#   问「北京有什么推荐酒店」，整句话被写成 origin，最终 12306 查询
#   变成 BJP→BJP，行程规划还拿它当需求，表现为「已读乱回」。
# ─────────────────────────────────────────────────────────────
_ORCHESTRATION_DONE = object()


class _ChatEventSourceResponse(EventSourceResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A disconnect can interrupt ASGI send while the generator is
            # suspended at yield, rather than interrupt its next iteration.
            with CancelScope(shield=True):
                await self.body_iterator.aclose()


@router.post("/api/chat")
async def chat(request: ChatRequest, current_user: CurrentUser, http_request: Request = None):
    request.user_id = owned_user(current_user, request.user_id)
    import time as _time
    _t_request_start = _time.monotonic()
    logger.info("[CHAT] request received")

    try:
        _t0 = _time.monotonic()
        session = await session_manager.get_or_create(request.user_id, request.session_id)
        _t_session = (_time.monotonic() - _t0) * 1000
        print(f"[TIMING] Session get/create took {_t_session:.0f}ms", flush=True)
    except Exception as e:
        from utils.llm_errors import describe, friendly

        logger.warning("[CHAT] session creation failed (%s)", describe(e))
        error_message = f"会话创建失败：{friendly(e)}"
        async def error_stream():
            yield _sse("error", {"message": error_message})
        return EventSourceResponse(error_stream())

    memory = session.memory_manager
    journal_enabled = not is_transport_question_echo(request.message)
    context_added = False
    user_text = redact_private_text(request.message)

    def add_user_context():
        nonlocal context_added
        if journal_enabled and not context_added:
            memory.short_term.add_message("user", user_text)
            context_added = True

    async def _stream():
        try:
            if is_transport_question_echo(request.message):
                yield _sse("clarification", {
                    "question": "这是我在请你补充路线信息，不用把问题发回来。直接告诉我出发地、目的地和时间即可。",
                    "missing_info": [],
                })
                return
            expense_command = parse_expense_command(request.message)
            expense_confirmation = expense_command and expense_command["kind"] == "confirm"
            ledger_intent = build_expense_intention(request.message)
            personal_available = http_request is not None and personal_enabled() and secure_personal_site(http_request)
            if personal_available and request.plan_ref is None and (pref := parse_preference(request.message)):
                if not explicitly_remembers_preference(request.message):
                    yield _sse("clarification", {"question": "这条偏好未保存。如果希望长期保存，请在个人中心设置，或明确说「记住我喜欢……」。"})
                    return
                names = await Profile(await trip_repository(current_user)).remember(pref["preferences"])
                if not names:
                    yield _sse("clarification", {"question": "暂未保存。可以在个人中心编辑城市和其他偏好，不要填写详细住址。"})
                    return
                answer = "已保存：" + "、".join(names) + "。是否用于自动规划可在个人中心单独设置。"
                result = {"status": "completed", "agents_executed": 0, "results": [
                    {"agent_name": "preference", "priority": 1, "status": "success", "data": {"answer": answer}},
                ]}
                yield _sse("complete", result)
                return
            previous_trip = getattr(session, "trip_request", None)
            based_on = getattr(session, "trip_plan_ref", None) if personal_available else None
            base_revision = getattr(session, "trip_plan_revision", None) if based_on else None
            carry_items = getattr(session, "trip_carry_items", ()) if based_on else ()
            if request.plan_ref is not None:
                if not personal_available:
                    yield _sse("error", {"message": "当前站点未开启行程引用。"})
                    return
                try:
                    previous_trip, base_revision, carry_items = await Trips(
                        await trip_repository(current_user),
                    ).open_trip_context(request.plan_ref)
                except PersonalError as exc:
                    yield _sse("error", {"message": exc.message})
                    return
                based_on = request.plan_ref
            if not request.plan_ref and previous_trip and is_trip_cancellation(request.message):
                session.trip_request = None
                session.trip_original = ""
                session.trip_options = []
                session.trip_selection = None
                session.trip_plan_ref = None
                session.trip_plan_revision = None
                session.trip_carry_items = []
                result = _trip_notice("本次差旅规划已取消，未执行预订或其他操作。", "cancelled")
                yield _sse("agent_result", result["results"][0])
                yield _sse("complete", result)
                return
            selection = selected_option(request.message) if previous_trip and not request.plan_ref else None
            if selection:
                options = getattr(session, "trip_options", [])
                chosen = options[selection - 1] if selection <= len(options) else None
                if chosen and selection_is_current(chosen):
                    session.trip_selection = chosen["id"]
                    result = _trip_notice(f"已保留方案 {selection} 的选择，未执行预订。", "completed")
                    result["selected_proposal"] = chosen["id"]
                    yield _sse("agent_result", result["results"][0])
                    yield _sse("complete", result)
                else:
                    yield _sse("clarification", {"question": "只能选择本轮已核验的方案；未核验的候选仍需补齐证据。"})
                return
            trip_turn = None if ledger_intent else IntentionAgent.prepare_trip(request.message, previous_trip)
            if request.plan_ref and (trip_turn is None or trip_turn.request.trip_id != previous_trip.trip_id):
                yield _sse("clarification", {"question": "请告诉我你想如何调整所引用的行程，例如「把去程改到明天上午」或「重新规划」。"})
                return
            if not trip_turn or not previous_trip or trip_turn.request.trip_id != previous_trip.trip_id:
                if based_on is not None:
                    session.trip_plan_ref = None
                    session.trip_plan_revision = None
                    session.trip_carry_items = []
                    if trip_turn is None:
                        session.trip_request = None
                based_on = None
                base_revision = None
                carry_items = ()
            personal_hints = {}
            if trip_turn is not None and personal_available:
                try:
                    async with asyncio.timeout(0.1):
                        personal_hints = await Profile(await trip_repository(current_user)).hints(
                            trip=trip_turn.request, exclude_plan=based_on.plan_id if based_on else None,
                        )
                except Exception as exc:
                    logger.debug("[CHAT] personal preference lookup skipped (%s)", type(exc).__name__)
            try:
                if ledger_intent is None and trip_turn is None:
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
                    yield _sse("complete", {
                        "status": "completed",
                        "intention": {"intents": [], "key_entities": {}},
                        "agents_executed": 1,
                        "results": [expand_payload],
                        "expanded": True,
                    })
                    return

            yield _sse("thinking", {"status": "analyzing_intent"})

            # 合并后的完整意图数据；非 None 时跳过 LLM 意图识别直接进入调度
            merged_intention_data = ledger_intent
            if trip_turn is not None:
                if previous_trip is None or trip_turn.request.trip_id != previous_trip.trip_id:
                    session.trip_original = request.message
                if request.plan_ref or previous_trip is None or previous_trip != trip_turn.request or trip_turn.missing:
                    session.trip_options = []
                    session.trip_selection = None
                session.trip_request = trip_turn.request
                if based_on is not None:
                    session.trip_plan_ref = based_on
                    session.trip_plan_revision = base_revision
                    session.trip_carry_items = list(carry_items)
                session.pending_intention = None
                merged_intention_data = trip_intention(trip_turn)

            # 只回填原任务的缺失信息；不得根据“凑齐两个城市”擅自生成行程。
            if ledger_intent is None and trip_turn is None and session.pending_intention is not None:
                age = time.monotonic() - getattr(session, "pending_since", 0.0)
                if age <= PENDING_TTL_SEC:
                    merged_intention_data = merge_clarification(session.pending_intention, request.message)
                session.pending_intention = None
                if merged_intention_data is not None:
                    logger.info("[CHAT] clarification merged; original schedule preserved")
                else:
                    logger.info("[CHAT] clarification expired or user changed topic")

            _t0 = _time.monotonic()
            recent_context = session.memory_manager.short_term.get_recent_context(n_turns=3) if merged_intention_data is None else []

            context_messages = []
            # 注入当前会话焦点提示（如焦点城市），帮助意图识别消解"附近"等指代
            focus_hint = session.focus_state.build_focus_hint()
            if focus_hint:
                context_messages.append(mk_msg("system", focus_hint, role="system"))

            for msg in recent_context:
                context_messages.append(mk_msg(msg["role"], msg["content"], role=msg["role"]))
            context_messages.append(mk_msg("user", request.message, role="user"))
            _t_context = (_time.monotonic() - _t0) * 1000
            print(f"[TIMING] Context preparation took {_t_context:.0f}ms", flush=True)

            # 注入用户长期偏好（帮助意图识别推断缺失信息如出发地）
            prefs = {} if personal_available else None
            try:
                lt = session.memory_manager.long_term
                if not personal_available and ledger_intent is None and trip_turn is None:
                    prefs = await session.memory_manager._maybe_await(lt.get_preference)
                if prefs:
                    pref_parts = []
                    if prefs.get("home_location"):
                        pref_parts.append(f"home_location: {prefs['home_location']}")
                    if pref_parts:
                        context_messages.insert(0, mk_msg("system",
                        "[用户偏好] " + "; ".join(pref_parts), role="system"))
            except Exception:
                pass

            if merged_intention_data is not None:
                # 追问合并后直接使用回填数据，跳过 LLM 意图识别
                intention_data = merged_intention_data
                intention_result = mk_msg("IntentionAgent", intention_data)
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

                intention_data = msg_json(
                    intention_result,
                    default={"intents": [], "error": "parse_failed"},
                )
            if not isinstance(intention_data, dict) or "error" in intention_data:
                yield _sse("error", {"message": "无法理解您的需求，请重新描述"})
                return

            intention_data = dict(intention_data, agent_schedule=normalized_schedule(intention_data))
            if personal_available and any(row.get("agent_name") == "preference" for row in intention_data["agent_schedule"]):
                # Free-form model output must never authorize a persistent preference write.
                intention_data["agent_schedule"] = [row for row in intention_data["agent_schedule"] if row.get("agent_name") != "preference"]
                if not intention_data["agent_schedule"]:
                    yield _sse("clarification", {"question": "还没有保存任何偏好。请在个人中心设置，或明确说「记住我喜欢坐高铁」。"})
                    return
            original_query = (merged_intention_data or {}).get("original_query") or request.message
            # Reserved transport fields are only added after publishing the intent.
            for reserved in ("preferences_snapshot", "_prepared_trip", "_personal_ranking_hints"):
                intention_data.pop(reserved, None)
            if trip_turn is None:
                intention_data.pop("trip_request", None)
            logger.info("[CHAT] sending intention event")
            yield _sse("intention", _public_intention(intention_data))

            # 更新会话焦点状态
            session.focus_state.update_from_intention(intention_data)

            # 关键实体缺失门控：暂停执行，反问用户
            if intention_data.get("needs_clarification"):
                question = intention_data.get("clarification_question", "请提供更多信息")
                if trip_turn and any(field == "origin" for field, _ in trip_turn.missing) and personal_hints.get("suggested_origin"):
                    question += f" 你常用的出发城市是{personal_hints['suggested_origin']}；如果本次也从那里出发，可以直接回复城市名。"
                fe_debug = intention_data.get("fast_event", {}) or {}
                mi_debug = fe_debug.get("missing_info", []) or []
                logger.info("[CHAT] clarification needed")
                if trip_turn is None:
                    intention_data["original_query"] = original_query
                    session.pending_intention = intention_data
                    session.pending_since = time.monotonic()  # 追问超时计时起点
                session.last_active = _time.monotonic()  # 防止session被LRU淘汰
                yield _sse("clarification", {
                    "question": question,
                    "missing_info": [label for _, label in trip_turn.missing] if trip_turn else mi_debug,
                    **({"trip_request": trip_turn.request.public(), "status": "needs_clarification"} if trip_turn else {}),
                })
                return  # 提前结束，不执行调度

            # 没有任何可执行 agent → 给一个明确回复，避免出现空白气泡
            if not intention_data.get("agent_schedule"):
                _fallback = (
                    "我可以帮你做这些：\n"
                "· 查天气、铁路余票和地图地点；票价与房价需另行核验\n"
                    "· 差旅标准、报销政策等知识库问答\n"
                    "· 行程规划、记账、汇率换算、翻译\n"
                    "直接说需求就行，比如「北京明天天气」「上海到北京的火车票」。"
                )
                logger.info("[CHAT] empty agent_schedule → capability fallback")
                yield _sse("clarification", {"question": _fallback, "missing_info": []})
                return

            yield _sse("dispatching", {"agents": _public_intention(intention_data)["agent_schedule"]})

            # 将焦点状态注入 intention_data，供编排器和 skill 使用
            intention_data["session_focus"] = {
                "focus_city": session.focus_state.focus_city,
                "last_search_city": session.focus_state.last_search_city,
                "current_trip_destination": session.focus_state.current_trip_destination,
            }
            history_query = "确认费用操作" if expense_confirmation else request.message
            intention_data["original_query"] = history_query if expense_confirmation else original_query
            if isinstance(prefs, dict):
                intention_data["preferences_snapshot"] = prefs
            if trip_turn is not None:
                intention_data["_prepared_trip"] = trip_turn.request.model_dump(mode="json")
                if personal_hints:
                    intention_data["_personal_ranking_hints"] = {k: v for k, v in personal_hints.items() if k != "suggested_origin"}
            intention_result = mk_msg("IntentionAgent", intention_data)

            add_user_context()

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
                    with expense_execution(request.message, session.session_id, request.request_id):
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
                finally:
                    # Producer is the only source of the terminal marker. A FIFO
                    # marker also wakes a waiting consumer when there are no results.
                    result_queue.put_nowait(_ORCHESTRATION_DONE)

            task = asyncio.create_task(run_orchestrator())

            try:
                while True:
                    result = await result_queue.get()
                    if result is _ORCHESTRATION_DONE:
                        break
                    event_type = result.get("type", "agent_result")
                    logger.info("[CHAT] real-time %s: %s", event_type, result.get("agent_name"))
                    yield _sse(event_type, result)
                await task
                logger.info("[CHAT] orchestrator task finished")
            finally:
                # 断开或取消时先收束任务，再让外层释放会话锁。
                if not task.done():
                    task.cancel()
                try:
                    with CancelScope(shield=True):
                        await task
                except asyncio.CancelledError:
                    pass
                finally:
                    session.orchestrator.result_queue = None

            if orchestration_error:
                from utils.llm_errors import describe, friendly

                logger.error(f"[CHAT] orchestrator error: {describe(orchestration_error)}")
                yield _sse("error", {"message": friendly(orchestration_error)})
                return

            result_data = msg_json(
                orchestration_result,
                default={"results": [], "error": "parse_failed"},
            )
            if not isinstance(result_data, dict) or result_data.get("error"):
                yield _sse("error", {"message": "无法读取本次任务结果，请稍后重试。"})
                return

            # 记住本轮的列表型结果（车票/酒店/餐厅/景点），供后续「列出来」展开
            from server.utils.list_expander import remember_list_result

            remember_list_result(session, result_data)
            if trip_turn is not None and isinstance(plan := result_data.get("trip_plan"), dict):
                session.trip_options = plan.get("alternatives") or []
                if session.trip_selection and not any(item["id"] == session.trip_selection and item["status"] == "validated"
                                                      for item in session.trip_options):
                    session.trip_selection = None
                plan["selected_proposal"] = session.trip_selection
                for row in result_data.get("results", []):
                    if row.get("node_id") == "proposal" and isinstance(row["data"].get("trip_plan"), dict):
                        row["data"]["trip_plan"]["selected_proposal"] = session.trip_selection
            public_intent = _public_intention(intention_data)
            if trip_turn is not None:
                result_data["intention"] = public_intent
            elif isinstance(result_data.get("intention"), dict):
                result_data["intention"] = {key: public_intent[key] for key in ("intents", "key_entities")}

            if personal_available:
                try:
                    snapshot = build_snapshot(result_data, trip_turn.request if trip_turn else None, based_on, carry_items)
                    if snapshot is not None:
                        snapshot = snapshot.model_copy(update={"base_revision": base_revision})
                        result_data["candidate_ref"] = str(candidates.add(current_user, session.session_id, snapshot))
                        result_data["candidate_session_id"] = session.session_id
                        if based_on:
                            result_data["candidate_base"] = based_on.model_dump(mode="json")
                            result_data["candidate_base_revision"] = base_revision
                        # Bound the optional hint: no providers or model calls,
                        # and a slow store must not hold back the final plan.
                        try:
                            async with asyncio.timeout(0.12):
                                advisory = await Trips(await trip_repository(current_user)).candidate_conflicts(snapshot)
                            result_data["personal_conflicts"] = advisory
                        except Exception as exc:
                            logger.debug("[CHAT] deferred personal calendar preview (%s)", type(exc).__name__)
                except Exception as exc:
                    # An invalid optional save projection must not hide a usable chat result.
                    logger.warning("[CHAT] personal candidate unavailable (%s)", type(exc).__name__)
            yield _sse("complete", result_data)

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
            transcript = Transcript()
            if journal_enabled:
                try:
                    restore_checkpoint(session, await memory.restore_conversation())
                    # Save the submitted message before any model or ledger operation,
                    # without including it twice when building the current prompt.
                    with CancelScope(shield=True):
                        await memory.add_message_async("user", user_text, include_short_term=False)
                    session.messages_since_summary += 1
                except Exception as exc:
                    logger.warning("[CHAT] user transcript not saved (%s)", type(exc).__name__)
                    yield _sse("error", {"message": "这条消息未能保存，本轮未执行，请稍后重试。",
                                         "history_warning": "不要关闭本页；这条消息只保留在当前页面。"})
                    return

            async def save_assistant():
                add_user_context()
                try:
                    text, presentation = transcript.assistant_message(session)
                    await memory.add_message_async("assistant", text, presentation=presentation,
                                                   include_short_term=presentation["status"] not in {"error", "interrupted"})
                    session.messages_since_summary += 1
                except Exception as exc:
                    logger.warning("[CHAT] assistant transcript not saved (%s)", type(exc).__name__)
                    return False
                return True

            stream = _stream()
            terminal_handled = False
            try:
                async for chunk in stream:
                    if journal_enabled:
                        transcript.observe(chunk)
                        if chunk.get("event") in TERMINALS:
                            terminal_handled = True
                            with CancelScope(shield=True):
                                saved = await save_assistant()
                            if not saved:
                                payload = json.loads(chunk["data"])
                                payload["history_warning"] = "本轮回复暂未写入历史，请留在本页查看。"
                                chunk = _sse(chunk["event"], payload)
                    yield chunk
            finally:
                # 客户端也可能在发送 yield 出去的事件时断开，必须主动关闭内层流，
                # 并屏蔽连接取消作用域，确保后台任务完全退出后才释放会话锁。
                with CancelScope(shield=True):
                    await stream.aclose()
                    if journal_enabled and not terminal_handled:
                        await save_assistant()

    return _ChatEventSourceResponse(event_stream(), ping=5, send_timeout=15)


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


def _public_intention(data: dict) -> dict:
    structured = bool(data.get("trip_request"))
    intents = [{**{key: row[key] for key in ("type", "confidence") if key in row},
                "description": "完整差旅规划" if data.get("trip_request") else "", "reason": ""}
               for row in (data.get("intents") or []) if isinstance(row, dict)]
    node_fields = ("agent_name", "priority", "node_id", "label", "depends_on") if structured else ("agent_name", "priority")
    nodes = [{**{key: row[key] for key in node_fields if key in row},
              "reason": "", "expected_output": ""}
             for row in data["agent_schedule"]]
    public = {"intents": intents, "key_entities": data.get("key_entities", {}), "agent_schedule": nodes,
              "reasoning": "", "rewritten_query": "",
              "needs_clarification": bool(data.get("needs_clarification"))}
    if data.get("trip_request"):
        public["trip_request"] = data["trip_request"]
    return public


def _trip_notice(answer: str, status: str) -> dict:
    result = {"agent_name": "itinerary_planning", "priority": 0, "status": "success", "data": {"answer": answer}}
    return {"status": status, "agents_executed": 0, "results": [result]}
