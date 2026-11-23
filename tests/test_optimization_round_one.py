import asyncio
import importlib
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from context.memory_manager import MemoryManager
from context.session_focus_state import SessionFocusState
from server.models import ChatRequest
from utils.as_compat import mk_msg, msg_json
from utils.expense_commands import expense_execution


def load_skill(name):
    path = Path(__file__).resolve().parents[1] / ".claude" / "skills" / name / "script" / "agent.py"
    spec = importlib.util.spec_from_file_location("optimization_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expense_input(original, rewritten=None, **extra):
    return mk_msg(
        "Orchestrator",
        {
            "context": {"rewritten_query": rewritten or original},
            "expense_request": {"original": original, "session_id": "audit", **extra},
        },
        role="user",
    )


@pytest.mark.parametrize(
    "original,rewritten,model_output",
    [
        ("酒店300元吗？", "记一笔酒店300元", {"action": "record", "expense": {"amount": 300}}),
        ("我一共花了多少钱？", "删除上一笔费用", {"action": "delete", "delete_index": 0}),
        ("不记账，打车50元", "记一笔打车50元", {"action": "record", "expense": {"amount": 50}}),
        ("记一笔退款-50元", "记一笔费用50元", {"action": "record", "expense": {"amount": 50}}),
    ],
)
async def test_expenses_do_not_trust_rewrite_or_model_actions(tmp_path, original, rewritten, model_output):
    model = AsyncMock(return_value=SimpleNamespace(text=json.dumps(model_output)))
    memory = MemoryManager("audit_expense", "audit", str(tmp_path))
    memory.long_term.add_expense({"id": "existing", "amount": 42})
    agent = load_skill("expense-tracker").ExpenseTrackerAgent(model=model, memory_manager=memory)
    with expense_execution(original, "audit"):
        result = msg_json(await agent.reply(expense_input(original, rewritten)))
    assert result["action"] not in {"record", "delete", "update"}
    assert [item["id"] for item in memory.long_term.get_expenses()] == ["existing"]
    model.assert_not_awaited()


async def _ledger_reply(agent, text, *, session="audit", request_id=None):
    with expense_execution(text, session, request_id):
        return msg_json(await agent.reply(expense_input(text)))


async def test_web_batch_ledger_uses_local_route_and_confirmation_with_model_circuit_open(tmp_path, monkeypatch):
    from agents.intention_agent import IntentionAgent, build_expense_intention
    from agents.orchestration_agent import OrchestrationAgent
    from utils.circuit_breaker import CircuitBreaker

    chat = importlib.import_module("server.routes.chat")
    model = AsyncMock(side_effect=AssertionError("明确账本指令不应调用模型"))
    uid = "local_batch_ledger"
    memory = MemoryManager(uid, "audit", str(tmp_path))
    agent = load_skill("expense-tracker").ExpenseTrackerAgent(model=model, memory_manager=memory)
    circuit = CircuitBreaker(failure_threshold=1)
    circuit.record_failure()
    session = SimpleNamespace(
        session_id="audit", memory_manager=memory, circuit_breaker=circuit, focus_state=SessionFocusState(),
        pending_intention=None, chat_lock=asyncio.Lock(), messages_since_summary=0,
        intention_agent=IntentionAgent(model=model),
        orchestrator=OrchestrationAgent(agent_registry={"expense_tracking": agent}, memory_manager=memory),
    )
    monkeypatch.setattr(chat, "session_manager", SimpleNamespace(get_or_create=AsyncMock(return_value=session)))

    async def send(message):
        response = await chat.chat(ChatRequest(message=message), uid)
        events = [item async for item in response.body_iterator]
        complete = [json.loads(item["data"]) for item in events if item["event"] == "complete"]
        assert len(complete) == 1
        return complete[0]["results"][0]["data"]

    request = "记一笔打车30元、午餐50美元"
    assert build_expense_intention("查北京天气，以及我的账单") is None
    assert build_expense_intention("记一笔打车30元，顺便查上海明天的天气") is None
    preview = await send(request)
    assert preview["action"] == "preview" and not memory.long_term.get_expenses()
    receipt = await send(preview["confirmation_command"])
    assert receipt["action"] == "record"
    assert [(row["amount"], row["currency"]) for row in memory.long_term.get_expenses()] == [(30, "CNY"), (50, "USD")]
    model.assert_not_awaited()


async def test_ledger_confirmation_is_persistent_atomic_and_idempotent(tmp_path):
    cls = load_skill("expense-tracker").ExpenseTrackerAgent
    memory = MemoryManager("ledger_owner", "audit", str(tmp_path))
    a = cls(memory_manager=memory)
    b = cls(memory_manager=MemoryManager("ledger_owner", "audit", str(tmp_path)))
    original = "记一笔打车30元、午餐50美元"
    request_id = "explicit_request_baseline_01"
    p1, p2 = await asyncio.gather(*(_ledger_reply(agent, original, request_id=request_id) for agent in (a, b)))
    assert p1 == p2 and p1["action"] == "preview"
    assert [(it["amount"], it["currency"]) for it in p1["expenses"]] == [(30, "CNY"), (50, "USD")]
    assert memory.long_term.get_expenses() == []
    assert (await _ledger_reply(a, "记一笔打车31元", request_id=request_id))["action"] == "error"
    code = p1["confirmation_command"]
    other = cls(memory_manager=MemoryManager("ledger_other", "audit", str(tmp_path)))
    assert (await _ledger_reply(other, code))["action"] == "error"
    assert (await _ledger_reply(a, code, session="other"))["action"] == "error"
    # Transport envelopes aren't an authority; only the request-scoped original can confirm.
    assert msg_json(await a.reply(expense_input(code)))["action"] == "error"
    r1, r2 = await asyncio.gather(*(_ledger_reply(agent, code) for agent in (a, b)))
    assert r1 == r2 and r1["action"] == "record"
    assert len(memory.long_term.get_expenses()) == 2
    assert await _ledger_reply(b, original, request_id=request_id) == r1


async def test_ledger_update_and_delete_require_confirmation_and_reject_stale_previews(tmp_path):
    memory = MemoryManager("ledger_owner", "audit", str(tmp_path))
    memory.long_term.add_expense({"id": "exp_old", "amount": 12, "currency": "USD", "description": "打车"})
    agent = load_skill("expense-tracker").ExpenseTrackerAgent(memory_manager=memory)
    delete = await _ledger_reply(agent, "删除费用 exp_old")
    edit = await _ledger_reply(agent, "修改费用 exp_old 为 20")
    assert delete["action"] == edit["action"] == "preview"
    assert memory.long_term.get_expenses()[0]["amount"] == 12
    assert (await _ledger_reply(agent, edit["confirmation_command"]))["action"] == "update"
    assert (await _ledger_reply(agent, delete["confirmation_command"]))["action"] == "error"
    assert (memory.long_term.get_expenses()[0]["amount"], memory.long_term.get_expenses()[0]["currency"]) == (20, "USD")
    new = await _ledger_reply(agent, "删除打车")
    r1 = await _ledger_reply(agent, new["confirmation_command"])
    r2 = await _ledger_reply(agent, new["confirmation_command"])
    assert r1 == r2 and r1["deleted_id"] == "exp_old"
    assert memory.long_term.get_expenses() == []


async def test_ledger_rejected_or_failed_batch_never_changes_ledger(tmp_path, monkeypatch):
    memory = MemoryManager("ledger_owner", "audit", str(tmp_path))
    agent = load_skill("expense-tracker").ExpenseTrackerAgent(memory_manager=memory)
    for text in ("记一笔打车30元、午餐-50元", "记一笔午餐－50元", "记一笔午餐€50", "记一笔打车30元、晚餐多少钱", "记一笔30.001元", "记一笔30元或50元"):
        assert (await _ledger_reply(agent, text))["action"] == "error"
    preview = await _ledger_reply(agent, "记一笔打车30元、午餐50元")
    real_save = memory.long_term._save

    def failing_save():
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr(memory.long_term, "_save", failing_save)
    result = await _ledger_reply(agent, preview["confirmation_command"])
    assert result["action"] == "error"
    assert memory.long_term.get_expenses() == []
    monkeypatch.setattr(memory.long_term, "_save", real_save)
    assert (await _ledger_reply(agent, preview["confirmation_command"]))["action"] == "record"
    assert len(memory.long_term.get_expenses()) == 2


async def test_ledger_expired_preview_cannot_be_committed(tmp_path, monkeypatch):
    memory = MemoryManager("ledger_owner", "audit", str(tmp_path))
    agent = load_skill("expense-tracker").ExpenseTrackerAgent(memory_manager=memory)
    preview = await _ledger_reply(agent, "记一笔打车30元")
    import utils.expense_commands as commands
    now = time.time()
    monkeypatch.setattr(commands, "time", SimpleNamespace(time=lambda: now + commands.PROPOSAL_TTL + 5))
    assert "过期" in (await _ledger_reply(agent, preview["confirmation_command"]))["answer"]
    assert memory.long_term.get_expenses() == []


async def test_mixed_request_can_preview_an_explicit_separate_expense_clause(tmp_path):
    memory = MemoryManager("ledger_owner", "audit", str(tmp_path))
    agent = load_skill("expense-tracker").ExpenseTrackerAgent(memory_manager=memory)
    preview = await _ledger_reply(agent, "下周去成都规划行程，顺便记一笔打车50元")
    assert preview["action"] == "preview" and preview["expense"]["amount"] == 50
    assert (await _ledger_reply(agent, "不要记账，查差旅记录，顺便记一笔打车50元"))["action"] == "error"
    assert memory.long_term.get_expenses() == []


@pytest.mark.parametrize("name,cls", [("place-search", "PlaceSearchAgent"), ("hotel-search", "HotelSearchAgent")])
def test_hotel_budget_does_not_relax_and_handles_range_boundary(name, cls):
    agent = getattr(load_skill(name), cls)()
    options = [{"biz_ext": {"cost": value}} for value in ("300", "200-300", "200-301", "900", "")]
    assert agent._filter_by_price(options, "0-300") == options[:2]
    assert agent._filter_by_price(options[2:], "0-300") == []


@pytest.mark.parametrize(
    "method,query",
    [("_query_price", "G1次车票多少钱"), ("_query_route_stations", "G1次有哪些经停站"), ("_query_transfer", "广州到北京怎么中转")],
)
async def test_unimplemented_train_information_is_not_success(method, query):
    agent = load_skill("train-ticket").TrainTicketAgent()
    result = await getattr(agent, method)(query)
    assert not result["query_success"]
    assert result["availability_status"] == "unavailable"


async def test_rail_availability_and_price_report_partial_without_mutating_cached_data():
    agent = load_skill("train-ticket").TrainTicketAgent()
    snapshot = {"query_success": True, "availability_status": "success", "price_status": "unavailable",
                "answer": "有车次", "results": {"trains": [{"train_no": "G1", "second_class": "有"}]}}
    agent._query_tickets = AsyncMock(return_value=snapshot)
    raw = mk_msg("user", {"context": {"rewritten_query": "广州到北京的高铁余票和票价",
                                     "key_entities": {"origin": "广州", "destination": "北京", "start_date": "2026-11-23"}}})
    partial = msg_json(await agent.reply(raw))
    assert partial["availability_status"] == "partial" and partial["price_status"] == "unavailable"
    assert partial["results"]["trains"] and partial["query_success"]
    assert snapshot["answer"] == "有车次" and snapshot["availability_status"] == "success"
    agent._query_tickets.return_value = {"query_success": False, "results": {"message": "暂不可用"}}
    assert msg_json(await agent.reply(raw))["availability_status"] == "failure"


@pytest.mark.parametrize("payload", [{"map": {}}, {"result": ["bad row"], "map": {}}])
async def test_malformed_rail_response_is_failure_not_empty_stock(monkeypatch, payload):
    from datetime import date, timedelta
    import httpx

    module = load_skill("train-ticket")
    monkeypatch.setattr(module, "_get_station_code", lambda city: {"北京": "BJP", "上海": "SHH"}[city])
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"httpstatus": 200, "data": payload}),
    ))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    day = (date.today() + timedelta(days=1)).isoformat()
    result = await module.TrainTicketAgent()._query_tickets(
        "北京到上海的火车票", {"from": "北京", "to": "上海", "date": day},
    )
    assert result["query_success"] is False
    assert result["availability_status"] == "failure"
    assert "暂无余票" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize("query,budget_expected", [
    ("北京2026-11-23住一晚", None),
    ("广州酒店预算不超过1,200元", "0-1200"),
    ("上海酒店 200.50 到 300.25 元", "200.50-300.25"),
    ("上海酒店低于300元", "0-300!"),
    ("住宿两晚总预算600元", "unverified"),
])
def test_hotel_budget_preserves_currency_precision_and_scope(query, budget_expected):
    from utils.hotel_budget import parse_hotel_budget

    assert parse_hotel_budget(query) == budget_expected


async def test_hotel_keeps_original_hard_budget_when_rewrite_drops_it(monkeypatch):
    import config

    module = load_skill("place-search")
    monkeypatch.setattr(config, "AMAP_CONFIG", {"api_key": "audit-placeholder"})
    mock = AsyncMock(return_value={"status": "1", "count": "99", "pois": [
        {"name": "偏贵", "biz_ext": {"cost": "900"}}, {"name": "没价格", "biz_ext": {}},
    ]})
    monkeypatch.setattr(module, "amap_json", mock)
    data = msg_json(await module.PlaceSearchAgent().reply(mk_msg("user", {"context": {
        "agent_name": "hotel_search", "rewritten_query": "北京酒店", "original_query": "北京酒店每晚不超过300元",
    }})))
    assert data["query_success"] is True
    assert data["results"]["count"] == 0 and data["results"]["hotels"] == []
    assert data["results"]["budget_status"] == "no_match" and data["results"]["price_status"] == "reference_only"
    assert "没有地图参考价符合预算" in data["results"]["summary"]
    mock.assert_awaited_once()


def _stub_chat(monkeypatch, execute):
    chat = importlib.import_module("server.routes.chat")
    orch = SimpleNamespace(result_queue=None)

    async def reply(msg):
        return await execute(orch.result_queue)

    orch.reply = reply
    memory = SimpleNamespace(
        short_term=SimpleNamespace(get_recent_context=lambda **kwargs: [], add_message=MagicMock()),
        long_term=SimpleNamespace(get_preference=lambda: {}),
        _maybe_await=AsyncMock(return_value={}),
        add_message_async=AsyncMock(),
        restore_conversation=AsyncMock(),
    )
    intent = SimpleNamespace(reply=AsyncMock(return_value=mk_msg(
        "IntentionAgent", {"agent_schedule": [{"agent_name": "information_query"}]},
    )))
    session = SimpleNamespace(
        circuit_breaker=MagicMock(), focus_state=SessionFocusState(), pending_intention=None,
        messages_since_summary=0, memory_manager=memory, long_term_summary="", session_id="audit",
        intention_agent=intent, orchestrator=orch, chat_lock=asyncio.Lock(),
    )
    monkeypatch.setattr(chat, "session_manager", SimpleNamespace(get_or_create=AsyncMock(return_value=session)))
    return chat, session


async def test_sse_completion_after_last_result_does_not_wait_for_heartbeat(monkeypatch):
    async def execute(queue):
        await queue.put({"agent_name": "information_query"})
        await asyncio.sleep(0.03)
        return mk_msg("Orchestrator", {"status": "completed", "results": []})

    chat, session = _stub_chat(monkeypatch, execute)
    response = await chat.chat(ChatRequest(message="合成测试"), "audit")
    marks = {}
    async for event in response.body_iterator:
        if "event" in event:
            marks[event["event"]] = time.perf_counter()
    closed = time.perf_counter()
    print(f"SSE result → complete: {(marks['complete'] - marks['agent_result'])*1000:.1f} ms; "
          f"result → close: {(closed - marks['agent_result'])*1000:.1f} ms")
    assert 0 < closed - marks["agent_result"] < 0.25
    assert session.orchestrator.result_queue is None and not session.chat_lock.locked()


async def test_sse_error_follows_buffered_results_once_and_closes(monkeypatch):
    async def execute(queue):
        await queue.put({"agent_name": "information_query", "type": "agent_start"})
        await queue.put({"agent_name": "information_query", "type": "agent_result"})
        raise ValueError("synthetic orchestration failure")

    chat, session = _stub_chat(monkeypatch, execute)
    response = await chat.chat(ChatRequest(message="合成测试"), "audit")
    events = [event["event"] async for event in response.body_iterator if "event" in event]
    assert events[-3:] == ["agent_start", "agent_result", "error"]
    assert events.count("error") == 1 and "complete" not in events
    assert session.orchestrator.result_queue is None and not session.chat_lock.locked()


async def test_sse_disconnect_while_sending_cancels_worker_releases_lock(monkeypatch):
    producer_cancelled = asyncio.Event()
    disconnect = asyncio.Event()

    async def execute(queue):
        try:
            await queue.put({"agent_name": "information_query"})
            await asyncio.Future()
        finally:
            producer_cancelled.set()

    chat, session = _stub_chat(monkeypatch, execute)
    response = await chat.chat(ChatRequest(message="合成测试"), "audit")

    async def receive():
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if b"event: agent_result" in message.get("body", b""):
            disconnect.set()
            await asyncio.Future()  # client disconnects exactly while transport is sending

    await asyncio.wait_for(response({"type": "http", "method": "POST", "path": "/api/chat", "headers": []}, receive, send), timeout=1)
    assert producer_cancelled.is_set()
    assert session.orchestrator.result_queue is None and not session.chat_lock.locked()


async def test_sse_transcript_failure_is_not_second_terminal_event(monkeypatch):
    async def execute(queue):
        return mk_msg("Orchestrator", {"status": "completed", "results": []})

    chat, session = _stub_chat(monkeypatch, execute)
    session.memory_manager.add_message_async.side_effect = [None, OSError("write interrupted")]
    response = await chat.chat(ChatRequest(message="合成测试"), "audit")
    events = [event["event"] async for event in response.body_iterator if "event" in event]
    assert events[-1] == "complete"
    assert "error" not in events


async def test_search_does_not_block_other_coroutines(monkeypatch):
    module = load_skill("query-info")

    class SlowSearch:
        def __init__(self, **kwargs):
            pass

        def text(self, *args, **kwargs):
            time.sleep(0.12)
            return [{"href": "https://example.org/source", "title": "Example", "body": "Text"}]

    monkeypatch.setattr(module, "DDGS", SlowSearch)
    monkeypatch.setattr(module, "DDGS_AVAILABLE", True)
    agent = module.InformationQueryAgent()
    agent._summarize_search_results = AsyncMock(return_value="合成结果")
    start = time.perf_counter()

    async def heartbeat():
        await asyncio.sleep(0.02)
        return (time.perf_counter() - start) * 1000

    tick, *results = await asyncio.gather(heartbeat(), *(agent._web_search("合成") for _ in range(3)))
    print(f"DDGS 3 × 120 ms: heartbeat {tick:.1f} ms; total {(time.perf_counter()-start)*1000:.1f} ms")
    assert tick < 100
    assert all(item["query_success"] for item in results)


async def test_timed_out_search_keeps_slot_until_actual_worker_exits():
    from threading import Event
    from utils.search_executor import SearchBusy, SearchExecutor

    pool = SearchExecutor(max_workers=1)
    started, release = Event(), Event()

    def blocked_search():
        started.set()
        release.wait(timeout=1)

    try:
        with pytest.raises(TimeoutError):
            await pool.run(blocked_search, timeout=0.05)
        assert started.is_set()
        with pytest.raises(SearchBusy):
            await pool.run(lambda: "unexpected", timeout=1)
    finally:
        release.set()
        pool.close()


async def test_provider_http_reuses_clients_in_lifespan_and_releases_sockets():
    from utils.as_compat import build_chat_model
    from utils.provider_http import provider_client, provider_resources, shared_client

    async with provider_resources():
        async with provider_client("amap") as first:
            async with provider_client("translation") as separate, provider_client("amap") as second:
                assert first is second and separate is not first
        assert not first.is_closed
        cfg = {"base_url": "https://example.org/v1", "api_key": "test-only", "model_name": "fixture"}
        a, b = build_chat_model(cfg), build_chat_model(cfg)
        assert a is not b and a.client._client is b.client._client
        pooled = shared_client("openai:https://example.org/v1")
        assert pooled is a.client._client
    assert first.is_closed and separate.is_closed and pooled.is_closed


async def test_planning_does_not_repeat_already_complete_event_extraction():
    from agents.orchestration_agent import OrchestrationAgent

    fields = {"origin": "广州", "destination": "上海", "start_date": "2026-11-23",
              "end_date": "2026-11-25", "duration_days": 3, "trip_purpose": "出差", "missing_info": []}
    event_model = AsyncMock(return_value=SimpleNamespace(text=json.dumps(fields, ensure_ascii=False)))
    event = load_skill("event-collection").EventCollectionAgent(model=event_model)
    plan_model = AsyncMock(return_value=SimpleNamespace(text=json.dumps({"itinerary": {"title": "上海差旅", "daily_plans": []}})))
    plan = load_skill("plan-trip").ItineraryPlanningAgent(model=plan_model)
    orchestrator = OrchestrationAgent(agent_registry={"event_collection": event, "itinerary_planning": plan})
    intention = {"rewritten_query": "广州到上海出差三天", "fast_event": fields,
                 "intents": [{"type": "itinerary_planning"}],
                 "agent_schedule": [{"agent_name": "event_collection", "priority": 1},
                                    {"agent_name": "itinerary_planning", "priority": 2}]}
    start = time.perf_counter()
    result = msg_json(await orchestrator.reply(mk_msg("IntentionAgent", intention)))
    print(f"Complete event fixture: event LLM={event_model.await_count}; planning LLM={plan_model.await_count}; "
          f"total={(time.perf_counter() - start)*1000:.1f} ms")
    assert event_model.await_count == 0 and plan_model.await_count == 1
    assert result["status"] == "completed"
    assert result["results"][-1]["data"]["itinerary"]["title"] == "上海差旅"
