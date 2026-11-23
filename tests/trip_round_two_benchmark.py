"""Run a fixed, offline chat/agent benchmark against this or an earlier PYTHONPATH."""
import asyncio
import importlib
import json
import statistics
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents.intention_agent import IntentionAgent
from agents.orchestration_agent import OrchestrationAgent
from context.memory_manager import MemoryManager
from server.models import ChatRequest
from server.session import UserSession
from utils.as_compat import mk_msg, msg_json
from utils.circuit_breaker import CircuitBreaker
from utils.weather_range import SHANGHAI_TZ

CASES = json.loads((Path(__file__).parent / "fixtures" / "trip_round_two.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 20, 12, tzinfo=SHANGHAI_TZ)
STAMP = "2026-11-20T12:00:00+08:00"
EXPIRES = "2026-11-20T12:30:00+08:00"


def quote(amount):
    return {"amount": amount, "currency": "CNY", "quality": "verified_quote", "tax_included": True,
            "queried_at": STAMP, "valid_until": EXPIRES, "source_url": "https://example.org/fixture"}


def make_session(tmp, case, *, delay=0.035, suffix=""):
    calls, times = [], []
    q = case["turns"][0]
    plan = case["id"] not in {"weather", "one_way"}
    fault = case.get("fault")

    async def intent_model(*args, **kwargs):
        calls.append("intent:model")
        await asyncio.sleep(delay)
        names = ["train_ticket", "hotel_search", "information_query", "itinerary_planning"] if plan else case["routes"]
        payload = {"reasoning": "fixture internal", "rewritten_query": q,
                   "fast_event": {"origin": "广州", "destination": "上海", "start_date": "2026-11-23", "end_date": "2026-11-25",
                                  "duration_days": 3, "trip_purpose": "出差", "missing_info": []} if plan else {},
                   "intents": [{"type": "itinerary_planning" if plan else names[0], "confidence": 1, "description": "fixture", "reason": ""}],
                   "key_entities": {"origin": "广州", "destination": "上海"} if plan else {},
                   "agent_schedule": [{"agent_name": x, "priority": 2 if x == "itinerary_planning" else 1,
                                       "reason": "fixture", "expected_output": ""} for x in names]}
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))

    def skill(name):
        async def reply(msg):
            data = msg_json(msg)
            context = data["context"]
            train = data.get("fast_train_ticket", {})
            inbound = train.get("from") == "上海"
            label = ("inbound" if inbound else "outbound") if name == "train_ticket" else name
            if name == "itinerary_planning":
                label = "plan:model"
            calls.append(label)
            start = time.perf_counter()
            await asyncio.sleep(delay)
            times.append((label, start, time.perf_counter()))
            if name == "train_ticket":
                day = train.get("date") or "2026-11-23"
                result = {"train_no": "G200" if inbound else "G100", "train_type": "高铁",
                          "from_station": train.get("from", "广州") + "站", "to_station": train.get("to", "上海") + "站",
                          "depart_time": "15:00" if inbound else "09:00", "arrive_time": "21:00" if inbound else "15:00",
                          "duration": "06:00", "second_class": "有", "first_class": "有",
                          "price_quote": {**quote(500), "seat_class": "second_class", "unit": "seat", "travel_date": day}}
                answer = {"query_success": fault != "rail", "availability_status": "failure" if fault == "rail" else "success",
                          "results": {"date": day, "queried_at": STAMP,
                                      "trains": [] if fault == "rail" else [result], "summary": "合成铁路结果"}}
            elif name == "hotel_search":
                rates = [1900, 2300] if fault == "budget" else [400, 530]
                answer = {"query_success": fault != "hotel", "results": {"summary": "合成地点结果", "queried_at": STAMP,
                          "hotels": [] if fault == "hotel" else [
                            {"id": f"poi-{i}", "name": f"合成住宿{i}", "location": f"121.50{i},31.20{i}",
                             "cost": str(rate), "rating": "4.5",
                             "price_quote": {**quote(rate), "unit": "room_night", "rooms_available": 3,
                                             "check_in": "2026-11-23", "check_out": "2026-11-25"}} for i, rate in enumerate(rates)]}}
            elif name == "information_query":
                answer = {"query_success": True, "results": {"summary": "合成天气结果",
                          "city": context.get("key_entities", {}).get("destination", "上海"),
                          "forecast": [{"date_iso": f"2026-11-{day}", "weather": "晴"} for day in (23, 24, 25)]}}
            else:
                answer = {"itinerary": {"title": "合成旧路径行程", "daily_plans": []}, "planning_complete": True}
            return mk_msg(name, answer)
        return SimpleNamespace(reply=reply)

    uid = "round2_bench" + suffix
    memory = MemoryManager(uid, "bench", str(tmp))
    registry = {name: skill(name) for name in ("information_query", "train_ticket", "hotel_search", "itinerary_planning")}
    session = UserSession(user_id=uid, session_id="bench", memory_manager=memory,
                          intention_agent=IntentionAgent(model=intent_model),
                          orchestrator=OrchestrationAgent(agent_registry=registry, memory_manager=memory),
                          circuit_breaker=CircuitBreaker(), model=intent_model)
    return session, calls, times


async def fake_commute(request, hotels):
    await asyncio.sleep(0.02)
    return {h["id"]: {"distance_m": 800 + i * 220, "duration_min": 12 + i * 4, "quality": "reference_estimate",
                      "source_url": "https://example.org/fixture", "queried_at": STAMP} for i, h in enumerate(hotels)}


async def drive(session, message):
    route = importlib.import_module("server.routes.chat")

    async def get(*args, **kwargs):
        return session

    with patch.object(route, "session_manager", SimpleNamespace(get_or_create=get)):
        events, elapsed, _, _ = await time_stream(route, session, message)
        return events, elapsed


async def time_stream(route, session, message):
    start = time.perf_counter()
    response = await route.chat(ChatRequest(message=message), session.user_id)
    events = []
    first_sse = first_content = None
    async for chunk in response.body_iterator:
        if "event" not in chunk:
            continue
        name = chunk["event"]
        elapsed = (time.perf_counter() - start) * 1000
        if first_sse is None:
            first_sse = elapsed
        if first_content is None and name in {"agent_result", "clarification", "error", "complete"}:
            first_content = elapsed
        events.append((name, json.loads(chunk["data"])))
    return events, (time.perf_counter() - start) * 1000, first_sse, first_content


def patch_clock_and_commute():
    from contextlib import ExitStack

    stack = ExitStack()
    for name, attr, value in (("utils.trip_request", "shanghai_now", lambda: NOW),
                              ("agents.trip_workflow", "shanghai_now", lambda: NOW),
                              ("agents.trip_workflow", "query_commute", fake_commute)):
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
        else:
            stack.enter_context(patch.object(mod, attr, value))
    return stack


def assess(case, events, calls, ms, times):
    last = events[-1][1]
    routes = sorted({row.get("node_id", row.get("agent_name")) for row in last.get("results", [])})
    plan = last.get("trip_plan") or {}
    request = plan.get("request") or last.get("trip_request") or {}
    budget = request.get("budget") or {}
    proposal = plan.get("recommended")
    if plan:
        intent_ok = request.get("origin") == "广州" and request.get("destination") == "上海"
        if case.get("budget"):
            intent_ok &= float(budget.get("amount") or 0) == case["budget"]
    else:
        intent_ok = routes == case["routes"] if case["id"] in {"weather", "one_way"} else False
    return {
        "routes": routes, "route_exact": routes == sorted(case["routes"]), "intent_grounded": intent_ok,
        "status": last.get("status", events[-1][0]), "model_calls": sum(":model" in call for call in calls),
        "calls": calls[:], "task_ms": round(ms, 2),
        "tool_and_planning_calls": len(times),
        "tool_execution_ms": round(1000 * sum(b - a for _, a, b in times), 2),
        "tool_wall_ms": round(1000 * (max(b for _, _, b in times) - min(a for _, a, _ in times)), 2) if times else None,
        "trip_budget": budget.get("amount"), "origin": request.get("origin"), "destination": request.get("destination"),
        "has_recommendation": bool(proposal), "issues": plan.get("issues", []),
    }


async def benchmark():
    route = importlib.import_module("server.routes.chat")
    with patch_clock_and_commute(), tempfile.TemporaryDirectory() as temp:
        for case in CASES:
            samples = []
            all_times = []
            for i in range(3):
                session, calls, times = make_session(temp, case, suffix=f"_{case['id']}_{i}")
                ms = 0
                first_events, first_content = [], []

                async def get(*args, **kwargs):
                    return session

                with patch.object(route, "session_manager", SimpleNamespace(get_or_create=get)):
                    for turn in case["turns"]:
                        result, elapsed, first, content = await time_stream(route, session, turn)
                        ms += elapsed
                        first_events.append(first)
                        first_content.append(content)
                sample = assess(case, result, calls, ms, times)
                sample["first_sse_ms"] = first_events[0]
                sample["first_content_ms"] = first_content[0]
                samples.append(sample)
                all_times.append(ms)
            report = samples[-1]
            report["median_task_ms"] = round(statistics.median(all_times), 2)
            for key in ("first_sse_ms", "first_content_ms"):
                report[f"median_{key}"] = round(statistics.median(row[key] for row in samples), 2)
            print("ROUND2", case["id"], json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(benchmark())
