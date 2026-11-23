import asyncio
import importlib
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agents import trip_workflow
from server.auth import require_identity
from server.models import ChatRequest
from trip_round_two_benchmark import CASES, NOW, drive, make_session, patch_clock_and_commute
from utils.trip_request import resolve_trip_turn


CHAT = importlib.import_module("server.routes.chat")
FULL = next(case for case in CASES if case["id"] == "full")
QUERY_COMMUTE = trip_workflow.query_commute


@pytest.fixture(autouse=True)
def fixed_providers_and_clock():
    with patch_clock_and_commute():
        yield


def decode_sse(body):
    events = []
    for frame in body.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in frame.splitlines() if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def mock_http(monkeypatch, *sessions, secure=False):
    by_user = {s.user_id: s for s in sessions}

    async def get(user_id, *args, **kwargs):
        return by_user[user_id]

    from fastapi import Request

    def identity(request: Request):
        return request.headers["test-identity"]

    monkeypatch.setattr(CHAT, "session_manager", SimpleNamespace(get_or_create=get))
    app = FastAPI()
    app.include_router(CHAT.router)
    app.dependency_overrides[require_identity] = identity
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="https://round-two.test" if secure else "http://round-two.test")


async def request(client, session, message):
    response = await client.post("/api/chat", json={"message": message}, headers={"test-identity": session.user_id})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return decode_sse(response.text)


def complete(events):
    terminals = [(name, data) for name, data in events if name in {"complete", "error", "clarification"}]
    assert len(terminals) == 1 and terminals[0][0] == "complete", terminals
    return terminals[0][1]


@pytest.mark.parametrize("answer", ["1", "１", "一"])
async def test_bare_passenger_answer_resumes_the_same_trip_without_intent_model(tmp_path, monkeypatch, answer):
    session, calls, _ = make_session(tmp_path, FULL, delay=0)
    async with mock_http(monkeypatch, session) as client:
        first = await request(client, session, "明天从北京去上海出差 3 天，往返预算 2000 元，请帮我规划。")
        assert first[-1][0] == "clarification"
        assert first[-1][1]["missing_info"] == ["出行人数"]
        draft = session.trip_request
        second = complete(await request(client, session, answer))
    trip = second["trip_plan"]["request"]
    assert (trip["origin"], trip["destination"], trip["passengers"]) == ("北京", "上海", 1)
    assert trip["depart_date"] == "2026-11-21" and trip["resolved_return_date"] == "2026-11-23"
    assert int(trip["budget"]["amount"]) == 2000
    assert session.trip_request.trip_id == draft.trip_id
    assert not any(":model" in call for call in calls)


def test_bare_number_is_only_used_for_an_unambiguous_passenger_question():
    text = "明天从北京去上海出差 3 天，往返预算 2000 元，请帮我规划。"
    draft = resolve_trip_turn(text, now=NOW).request
    assert resolve_trip_turn("1", now=NOW) is None
    assert resolve_trip_turn("1", draft.model_copy(update={"depart_date": None}), now=NOW) is None
    assert resolve_trip_turn("1", draft.model_copy(update={"passengers": 2}), now=NOW) is None
    invalid = resolve_trip_turn("51", draft, now=NOW)
    assert invalid.request.passengers is None and invalid.missing[0][0] == "passengers"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_fixed_trip_scenarios_use_real_chat_sse_and_grounded_routes(tmp_path, monkeypatch, case):
    session, calls, _ = make_session(tmp_path, case, delay=0)
    async with mock_http(monkeypatch, session) as client:
        turns = [await request(client, session, question) for question in case["turns"]]
    result = complete(turns[-1])
    rows = {row.get("node_id", row["agent_name"]): row for row in result["results"]}
    assert set(rows) == set(case["routes"])
    assert not any(":model" in call for call in calls)
    assert "_prepared_trip" not in json.dumps(turns)
    if case["id"] in {"weather", "one_way"}:
        assert len(calls) == 1
        assert session.trip_request is None
        return
    plan = result["trip_plan"]
    req = plan["request"]
    assert req["origin"] == "广州" and req["destination"] == "上海"
    assert plan["recommended"] is None  # Synthetic fixtures here omit other necessary costs.
    assert result["status"] == "partial_failure"
    assert not any(option["budget_status"] == "within" for option in plan["alternatives"])
    codes = {issue["code"] for issue in plan["issues"]}
    if case.get("budget"):
        assert int(req["budget"]["amount"]) == case["budget"]
    if case["id"] == "full":
        assert (req["depart_date"], req["resolved_return_date"], req["meeting_date"]) == ("2026-11-23", "2026-11-25", "2026-11-24")
        assert req["passengers"] == 1 and req["avoid_early"] is True
        assert plan["alternatives"][0]["commute"]["quality"] == "reference_estimate"
        assert plan["alternatives"][0]["cost_items"][-1]["amount"] is None
        assert rows["outbound"]["data"]["results"]["trains"][0]["train_no"] == "G100"
        assert rows["inbound"]["data"]["results"]["trains"][0]["train_no"] == "G200"
    elif case["id"] == "revision":
        old = complete(turns[0])["trip_plan"]["request"]
        assert {key for key in old if old[key] != req[key]} == {"budget", "revision"}
    elif case["id"] == "rail_down":
        assert {"outbound_missing", "inbound_missing"} <= codes
        assert rows["hotels"]["node_status"] == "success"
        assert not any(option["outbound"] or option["inbound"] for option in plan["alternatives"])
    elif case["id"] == "hotel_down":
        assert "hotel_missing" in codes and rows["commute"]["node_status"] == "skipped"
        assert rows["inbound"]["node_status"] == rows["outbound"]["node_status"] == "success"
    elif case["id"] == "over_budget":
        assert "total_budget_exceeded" in plan["excluded_reasons"] and not plan["alternatives"]
    elif case["id"] == "time_conflict":
        assert "meeting_arrival_conflict" in plan["excluded_reasons"] and not plan["alternatives"]
    elif case["id"] == "conversation":
        assert turns[0][-1][0] == turns[1][-1][0] == "clarification"
        assert req["passengers"] == 2 and req["meeting_place"] == "上海世博中心"
        assert req["return_period"] == "afternoon" and req["near_meeting"] is False
    if case["id"] in {"revision", "repeat"}:
        assert calls == ["outbound", "inbound", "hotel_search", "information_query"]
        assert all(rows[name]["cached"] for name in ("outbound", "inbound", "hotels", "weather", "commute"))


async def test_parallel_chat_sessions_do_not_share_constraints_or_cache(tmp_path, monkeypatch):
    first, left_calls, left_times = make_session(tmp_path, FULL, suffix="_a", delay=0.012)
    second, right_calls, right_times = make_session(tmp_path, FULL, suffix="_b", delay=0.012)
    async with mock_http(monkeypatch, first, second) as client:
        results = await asyncio.gather(
            request(client, first, FULL["turns"][0]),
            request(client, second, FULL["turns"][0].replace("3000", "3800").replace("1人", "2人")),
        )
        edited = await request(client, first, "预算改为2500元")
    a, b = [complete(e)["trip_plan"]["request"] for e in results]
    assert a["trip_id"] != b["trip_id"]
    assert (a["budget"]["amount"], b["budget"]["amount"], b["passengers"]) == ("3000", "3800", 2)
    assert complete(edited)["trip_plan"]["request"]["passengers"] == 1
    assert len(left_calls) == len(right_calls) == 4
    for times in (left_times, right_times):
        assert max(start for _, start, _ in times) < min(end for _, _, end in times)


async def test_partial_results_arrive_before_optional_weather_and_timeout(tmp_path, monkeypatch):
    session, _, _ = make_session(tmp_path, FULL, delay=0)
    original_graph = trip_workflow.build_graph
    monkeypatch.setattr(trip_workflow, "build_graph", lambda req: tuple(
        replace(node, timeout=0.2) if node.node_id == "weather" else node for node in original_graph(req)
    ))
    cancelled = asyncio.Event()

    async def slow_weather(_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    session.orchestrator.agent_registry["information_query"].reply = slow_weather
    events, _ = await drive(session, FULL["turns"][0])
    partial_nodes = [frame["node_id"] for kind, frame in events if kind == "agent_result"]
    assert partial_nodes.index("proposal") < partial_nodes.index("weather")
    final = complete(events)
    assert final["status"] == "partial_failure" and cancelled.is_set()
    assert {row["node_id"]: row["node_status"] for row in final["results"]} == {
        "outbound": "success", "inbound": "success", "hotels": "success",
        "weather": "timeout", "commute": "success", "proposal": "partial",
    }
    assert "weather_missing" in {issue["code"] for issue in final["trip_plan"]["issues"]}


async def test_trip_disconnect_cancels_all_active_reads_and_emits_no_false_complete(tmp_path, monkeypatch):
    session, _, _ = make_session(tmp_path, FULL, delay=0)
    disconnect = asyncio.Event()
    all_started = asyncio.Event()
    started = set()
    cancelled = set()

    async def pending(msg):
        from utils.as_compat import msg_json

        payload = msg_json(msg)
        name = payload.get("fast_train_ticket", {}).get("from") or payload["context"]["rewritten_query"]
        started.add(name)
        if len(started) == 4:
            all_started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.add(name)

    for agent in session.orchestrator.agent_registry.values():
        agent.reply = pending

    async def get(*args):
        return session

    monkeypatch.setattr(CHAT, "session_manager", SimpleNamespace(get_or_create=get))
    response = await CHAT.chat(ChatRequest(message=FULL["turns"][0]), session.user_id)
    sent = []

    async def receive():
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(frame):
        body = frame.get("body", b"")
        sent.append(body)
        if b"event: agent_start" in body:
            await all_started.wait()
            disconnect.set()
            await asyncio.Future()

    await asyncio.wait_for(response({"type": "http"}, receive, send), timeout=1.5)
    assert len(started) == 4 and cancelled == started
    assert session.orchestrator.result_queue is None and not session.chat_lock.locked()
    assert not any(b"event: complete" in frame for frame in sent)


async def test_global_concurrency_limit_applies_across_independent_workflows(tmp_path, monkeypatch):
    from utils.as_compat import mk_msg

    monkeypatch.setattr(trip_workflow, "GLOBAL_READ_LIMIT", 2)
    peak = active = 0

    async def reply(_):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.015)
        finally:
            active -= 1
        return mk_msg("Fixture", {"query_success": False, "results": {"message": "合成不可用"}})

    sessions = [make_session(tmp_path, FULL, suffix=f"_limited_{i}")[0] for i in range(3)]
    for session in sessions:
        for skill in session.orchestrator.agent_registry.values():
            skill.reply = reply
    async with mock_http(monkeypatch, *sessions) as client:
        streams = await asyncio.gather(*(request(client, s, FULL["turns"][0]) for s in sessions))
    assert peak == 2 and active == 0
    assert all(complete(stream)["status"] == "failed" for stream in streams)


async def test_complete_grounded_option_can_be_selected_and_cancelled_without_booking(tmp_path):
    session, _, _ = make_session(tmp_path, FULL, delay=0)
    message = FULL["turns"][0] + "其他必要费用200元"
    events, _ = await drive(session, message)
    result = complete(events)
    assert result["status"] == "completed"
    recommended = result["trip_plan"]["recommended"]
    assert recommended["known_subtotals"] == {"CNY": "2000"}
    assert recommended["budget_status"] == "within" and recommended["status"] == "validated"
    events, _ = await drive(session, "选择方案1")
    assert complete(events)["selected_proposal"] == recommended["id"]
    events, _ = await drive(session, "按这个方案重新规划")
    assert complete(events)["trip_plan"]["selected_proposal"] == recommended["id"]
    events, _ = await drive(session, "取消本次差旅规划")
    assert complete(events)["status"] == "cancelled"
    assert session.trip_request is None and session.trip_options == [] and session.trip_selection is None
    assert session.memory_manager.long_term.get_expenses() == []


async def test_hard_flight_requirement_does_not_substitute_rail_or_claim_budget_compliance(tmp_path):
    session, calls, _ = make_session(tmp_path, FULL, delay=0)
    events, _ = await drive(session, FULL["turns"][0] + "必须坐飞机")
    result = complete(events)
    assert result["trip_plan"]["recommended"] is None
    assert "flight_unavailable" in {issue["code"] for issue in result["trip_plan"]["issues"]}
    assert set(calls) == {"hotel_search", "information_query"}


@pytest.mark.parametrize("scenario,issue", [("wrong_seat", "seats_unverified"), ("expired", "quote_missing")])
async def test_unusable_seat_or_expired_quote_cannot_be_recommended(tmp_path, scenario, issue):
    from utils.as_compat import mk_msg, msg_json

    session, _, _ = make_session(tmp_path, FULL, delay=0)
    agent = session.orchestrator.agent_registry["train_ticket"]
    original = agent.reply

    async def edit_quote(msg):
        data = msg_json(await original(msg))
        row = data["results"]["trains"][0]
        if scenario == "wrong_seat":
            row["second_class"] = "无"
            row["first_class"] = "有"
        else:
            row["price_quote"]["valid_until"] = "2026-11-20T11:59:00+08:00"
        return mk_msg("Fixture", data)

    agent.reply = edit_quote
    events, _ = await drive(session, FULL["turns"][0] + "其他必要费用200元")
    plan = complete(events)["trip_plan"]
    assert plan["recommended"] is None
    assert issue in {row["code"] for row in plan["issues"]}


async def test_legacy_sse_does_not_publish_model_handoff_reasoning_or_reserved_fields(tmp_path, monkeypatch):
    case = {**FULL, "id": "synthetic_unstructured"}
    session, _, _ = make_session(tmp_path, case, delay=0)
    from utils.as_compat import mk_msg

    async def private_intent(_):
        return mk_msg("Fixture", {
            "intents": [{"type": "information_query", "description": "private-description", "reason": "private-reason"}],
            "reasoning": "private-analysis", "rewritten_query": "private-rewrite",
            "agent_schedule": [{"agent_name": "information_query", "priority": 1, "label": "private-label"}],
            "_prepared_trip": {"inadmissible": True},
        })

    monkeypatch.setattr(session.intention_agent, "reply", private_intent)
    async with mock_http(monkeypatch, session) as client:
        events = await request(client, session, "提供更多详细信息")
    assert complete(events)["results"][0]["agent_name"] == "information_query"
    serialized = json.dumps(events)
    assert "private-" not in serialized and "_prepared_trip" not in serialized


def test_ambiguous_budget_stays_pending_until_corrected_and_does_not_set_hard_soft_times():
    draft = resolve_trip_turn("11月23日从广州去上海出差，总预算3000元，周三下午回来，1人，最好不早于9点", now=NOW)
    assert draft.missing == ()
    assert draft.request.preferred_earliest_departure.hour == 9 and draft.request.earliest_departure is None
    assert draft.request.return_period == "afternoon"
    assert str(draft.request.budget.amount) == "3000"
    turn = resolve_trip_turn("预算改为2000～3000元", draft.request, now=NOW)
    assert turn.missing[0][0] == "budget"
    another = resolve_trip_turn("返程改到周三上午", turn.request, now=NOW)
    assert another.missing[0][0] == "budget"
    fixed = resolve_trip_turn("2500元", another.request, now=NOW)
    assert fixed.missing == () and str(fixed.request.budget.amount) == "2500"
    assert fixed.request.return_period == "morning"
    assert resolve_trip_turn("上海明天的天气怎么样？", fixed.request, now=NOW) is None
    identical = "明天从广州去上海出差，1人，三天出差"
    first = resolve_trip_turn(identical, now=NOW)
    assert first.missing == ()
    assert resolve_trip_turn(identical, first.request, now=NOW).request == first.request


def test_clearing_hotel_budget_never_removes_total_budget_and_unsupported_hard_constraint_asks():
    draft = resolve_trip_turn(FULL["turns"][0] + "酒店预算350元", now=NOW)
    assert str(draft.request.nightly_limit.amount) == "350"
    turn = resolve_trip_turn("取消住宿预算", draft.request, now=NOW)
    assert turn.missing == () and turn.request.nightly_limit is None and str(turn.request.budget.amount) == "3000"
    unsupported = resolve_trip_turn("住宿只允许服务式公寓，酒店必须提供无障碍浴室", turn.request, now=NOW)
    assert "unsupported_constraint" in dict(unsupported.missing)
    resolved = resolve_trip_turn("忽略未支持的硬性限制", unsupported.request, now=NOW)
    assert resolved.missing == ()


async def test_real_tool_adapters_cap_and_deduplicate_commute_and_reject_imprecise_geocode(monkeypatch):
    from config import AMAP_CONFIG

    req = resolve_trip_turn(FULL["turns"][0], now=NOW).request
    monkeypatch.setitem(AMAP_CONFIG, "api_key", "local-fixture-no-network")
    endpoints = []
    result_level = "兴趣点"

    async def response(url, params):
        endpoints.append(url)
        if url.endswith("/geo"):
            assert params["city"] == "上海" and params["address"] == "上海世博中心"
            return {"status": "1", "geocodes": [{"city": [], "province": "上海市", "level": result_level, "location": "121.51,31.21"}]}
        assert params["origin"] == "121.50,31.20"
        return {"status": "1", "route": {"paths": [{"distance": "700", "duration": "611"}]}}

    monkeypatch.setattr(trip_workflow, "amap_json", response)
    hotels = [{"id": name, "location": loc} for name, loc in (("a", "121.50,31.20"), ("b", "121.50,31.20"), ("x", "nonsense"))]
    walks = await QUERY_COMMUTE(req, hotels)
    assert len(endpoints) == 2 and set(walks) == {"a", "b"}
    assert walks["a"] == walks["b"] and walks["a"]["duration_min"] == 11
    result_level = "城市"
    assert await QUERY_COMMUTE(req, hotels) == {}
    assert len(endpoints) == 3


async def test_registered_skill_adapters_pass_actual_provider_payloads_to_workflow(tmp_path, monkeypatch):
    from config import AMAP_CONFIG
    from test_optimization_round_one import load_skill
    from utils.weather_range import resolve_weather_range

    rail, place, weather = (load_skill(name) for name in ("train-ticket", "place-search", "query-info"))
    session, unexpected, _ = make_session(tmp_path, FULL, delay=0)
    session.orchestrator.agent_registry.update({
        "train_ticket": rail.TrainTicketAgent(),
        "hotel_search": place.PlaceSearchAgent(),
        "information_query": weather.InformationQueryAgent(),
    })
    calls = []
    monkeypatch.setitem(AMAP_CONFIG, "api_key", "local-fixture-no-network")
    monkeypatch.setattr(weather, "resolve_weather_range", lambda q, **kw: resolve_weather_range(q, now=kw.get("now", NOW)))
    monkeypatch.setattr(weather, "shanghai_now", lambda: NOW)
    monkeypatch.setattr(rail, "_get_station_code", {"广州": "GZQ", "上海": "SHH"}.get)

    async def amap(url, params):
        calls.append((url.rsplit("/", 1)[-1], params))
        if url.endswith("/text"):
            return {"status": "1", "count": "1", "pois": [{"id": "poi-a", "name": "合成住宿", "location": "121.50,31.20",
                                                              "biz_ext": {"cost": "300", "rating": "4.5"}}]}
        return {"status": "1", "forecasts": [{"casts": [
            {"date": f"2026-11-{day}", "dayweather": "晴", "daytemp": "18", "nighttemp": "9"} for day in (21, 22, 23)
        ]}]}

    monkeypatch.setattr(weather, "amap_json", amap)
    monkeypatch.setattr(place, "amap_json", amap)

    class RailClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None):
            if not params:
                return httpx.Response(200, request=httpx.Request("GET", url))
            calls.append(("rail", params))
            start, end = (params[f"leftTicketDTO.{key}_station"] for key in ("from", "to"))
            row = [""] * 33
            row[3] = "G100" if start == "GZQ" else "G200"
            row[6:11] = [start, end, "09:00", "15:00", "06:00"] if start == "GZQ" else [start, end, "15:00", "21:00", "06:00"]
            row[30] = "有"
            return httpx.Response(200, json={"httpstatus": 200, "data": {
                "map": {"GZQ": "广州站", "SHH": "上海站"}, "result": ["|".join(row)],
            }}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", RailClient)
    events, _ = await drive(session, "明天从广州去上海出差，周一下午返回，1人，预算3000元，其他必要费用200元")
    result = complete(events)
    plan = result["trip_plan"]
    nodes = {row["node_id"]: row for row in result["results"]}
    assert not unexpected and nodes["weather"]["node_status"] == "success"
    assert {row["date_iso"] for row in nodes["weather"]["data"]["results"]["forecast"]} == {"2026-11-21", "2026-11-22", "2026-11-23"}
    assert [p["leftTicketDTO.train_date"] for name, p in calls if name == "rail"] == ["2026-11-21", "2026-11-23"]
    assert plan["alternatives"][0]["hotel"]["reference_cny"] == ["300", "300"]
    assert plan["alternatives"][0]["known_subtotals"] == {"CNY": "200"}
    assert plan["recommended"] is None and plan["alternatives"][0]["budget_status"] == "unverified"


async def test_personal_chat_saves_only_on_explicit_action_and_carries_the_pinned_version(tmp_path, monkeypatch):
    from server.personal.models import CandidateInput, ManualDraft, ManualInput, NewVersion, OperationCommit, OperationPreview
    from server.personal.profile import Profile
    from server.personal.repository import JsonTrips
    from server.personal.service import PersonalError, Trips

    user, calls, _ = make_session(tmp_path, FULL, delay=0)
    repo = JsonTrips(user.user_id, tmp_path)
    trips = Trips(repo)

    async def store(owner):
        return JsonTrips(owner, tmp_path)

    monkeypatch.setenv("ALIGO_PERSONAL_CENTER_ENABLED", "1")
    monkeypatch.setattr(CHAT, "trip_repository", store)

    mat = await trips.create(ManualInput(source="manual", draft=ManualDraft(title="已安排会议", schedule_items=[{
        "title": "仅本人可见的会议标题", "kind": "meeting", "city": "广州",
        "commitment": "fixed", "precision": "exact",
        "start_at": "2026-11-23T09:00:00+08:00", "end_at": "2026-11-23T11:00:00+08:00",
    }])), "prep-private-00001")
    preview = await trips.preview(mat["plan_id"], OperationPreview(action="schedule", draft_version=1, expected_revision=1))
    await trips.commit(mat["plan_id"], OperationCommit(operation_id=preview["operation_id"], confirmed=True), "auth-private-00001")

    async with mock_http(monkeypatch, user, secure=True) as client:
        declined = await request(client, user, "我喜欢坐高铁")
        assert "未保存" in declined[-1][1]["question"]
        assert not next(item for item in (await Profile(repo).preferences())["items"] if item["key"] == "transportation_preference")["value"]
        committed = complete(await request(client, user, "记住我喜欢坐高铁"))
        assert committed["agents_executed"] == 0
        assert not await Profile(repo).hints()
        generated = complete(await request(client, user, FULL["turns"][0]))
        assert generated.get("candidate_ref") and (await trips.overview())["counts"]["draft"] == 0
        assert any("existing_schedule_overlap" in option["issue_codes"] for option in generated["trip_plan"]["alternatives"])
        assert "仅本人可见的会议标题" not in json.dumps(generated["trip_plan"], ensure_ascii=False)
        source = CandidateInput(source="candidate", candidate_ref=generated["candidate_ref"], session_id=generated["candidate_session_id"])
        saved = await trips.create(source, "save-complete-00001")
        response = await client.post("/api/chat", json={
            "message": "预算改为2500元", "plan_ref": {"plan_id": saved["plan_id"], "version": 1},
        }, headers={"test-identity": user.user_id})
        revised = complete(decode_sse(response.text))
        assert revised["candidate_base_revision"] == 1 and revised["candidate_base"]["version"] == 1
        assert revised["trip_plan"]["request"]["budget"]["amount"] == "2500"
        assert (await trips.get(saved["plan_id"]))["draft"]["snapshot"]["budget"]["amount"] == "3000"
        await trips.rename(saved["plan_id"], "另一页已修改", 1)
        content = CandidateInput(source="candidate", candidate_ref=revised["candidate_ref"], session_id=revised["candidate_session_id"])
        with pytest.raises(PersonalError) as stale:
            await trips.add_version(saved["plan_id"], NewVersion(based_on_version=1, content=content), 2, "save-revised-00001")
        assert stale.value.code == "candidate_outdated"
    assert not any(":model" in call for call in calls)
