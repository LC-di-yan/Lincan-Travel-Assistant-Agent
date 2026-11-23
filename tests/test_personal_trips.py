import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from context.long_term_memory import LongTermMemory
from server.personal.candidates import CandidateCache, build_snapshot
from server.personal.models import CandidateInput, CopyInput, ManualDraft, ManualInput, NewVersion, PlanRef
from server.personal.repository import JsonTrips, PostgresTrips
from server.personal.service import PersonalError, Trips
from utils.trip_request import TripRequest


def _manual(title="上海会议"):
    return ManualInput(source="manual", draft=ManualDraft(
        title=title, origin="广州", destination="上海", start_date="2027-01-11", end_date="2027-01-13",
        budget={"amount": "1234.56", "currency": "CNY"},
        schedule_items=[{"title": "会议", "kind": "meeting", "commitment": "fixed", "precision": "exact", "city": "上海",
                         "start_at": "2027-01-12T11:00:00+08:00", "end_at": "2027-01-12T12:00:00+08:00"}],
    ))


async def _repository_contract(owner, reload_owner, other):
    first, retry = await asyncio.gather(
        owner.create(_manual(), "manual-0000000001"), reload_owner.create(_manual(), "manual-0000000001"),
    )
    # Server-generated event IDs are not part of a retried client payload.
    assert retry == first
    plan_id = first["plan_id"]
    with pytest.raises(PersonalError) as missing:
        await other.get(plan_id)
    assert missing.value.status == 404
    assert (await reload_owner.get(plan_id))["draft"]["snapshot"]["budget"]["amount"] == "1234.56"
    snapshot = (await owner.get(plan_id))["draft"]["snapshot"]
    with pytest.raises(PersonalError) as mismatch:
        await owner.create(_manual("另一个行程"), "manual-0000000001")
    assert mismatch.value.code == "idempotency_mismatch"
    append = NewVersion(based_on_version=1, content=_manual("变更后的行程"))
    await owner.add_version(plan_id, append, 1, "revision-00000001")
    assert (await owner.version(plan_id, 1))["snapshot"] == snapshot
    with pytest.raises(PersonalError) as stale:
        await reload_owner.add_version(plan_id, append, 1, "revision-00000002")
    assert stale.value.status == 412
    duplicate = await owner.create(CopyInput(source="copy", ref=PlanRef(plan_id=plan_id, version=1)), "copy-000000000001")
    copy = await owner.get(duplicate["plan_id"])
    assert copy["draft"]["snapshot"]["schedule_items"][0]["event_id"] != snapshot["schedule_items"][0]["event_id"]
    assert duplicate["plan_id"] != plan_id and copy["scheduled"] is None
    assert (await owner.versions(plan_id))["items"][0]["version"] == 2
    assert (await owner.overview())["counts"] == {"scheduled": 0, "draft": 2}


async def test_json_trips_survive_repository_recreation_without_replacing_legacy_data(tmp_path):
    memory = LongTermMemory("a", tmp_path)
    memory.save_preference("hotel", "此前保存的住宿偏好")
    await _repository_contract(Trips(JsonTrips("a", tmp_path)), Trips(JsonTrips("a", tmp_path)), Trips(JsonTrips("b", tmp_path)))
    assert LongTermMemory("a", tmp_path).get_preference("hotel") == "此前保存的住宿偏好"


@pytest.mark.integration
async def test_pg_trips_use_the_same_version_and_idempotency_contract():
    dsn = os.environ.get("ALIGO_TEST_PERSONAL_PG_DSN")
    if not dsn:
        pytest.skip("需要独立本机 aligo_personal_dev_test 数据库")
    parts = urlsplit(dsn)
    assert parts.hostname in {"127.0.0.1", "::1"} and parts.path == "/aligo_personal_dev_test"
    import asyncpg
    from db.connection import _init_connection

    async with asyncpg.create_pool(dsn, min_size=1, max_size=4, init=_init_connection) as pool:
        root = Path(__file__).resolve().parents[1]
        migrations = sorted((root / "db" / "migrations").glob("*.sql"))
        for relative in [root / "db/schema.sql", *migrations, *migrations]:
            await pool.execute((root / relative).read_text(encoding="utf-8"))
        key = f"test_{uuid4().hex}"
        await _repository_contract(Trips(PostgresTrips(key, pool)), Trips(PostgresTrips(key, pool)),
                                   Trips(PostgresTrips(f"{key}_other", pool)))
        from test_personal_conflicts import check_schedule_contract

        await check_schedule_contract(Trips(PostgresTrips(key, pool)), Trips(PostgresTrips(key, pool)),
                                      Trips(PostgresTrips(f"{key}_other", pool)))
        from context.long_term_memory import PostgresLongTermMemory
        from test_personal_finance import check_finance_contract

        ledger_owner = f"{key}_ledger"
        await check_finance_contract(PostgresTrips(ledger_owner, pool), PostgresLongTermMemory(ledger_owner, pool),
                                     PostgresTrips(f"{key}_other", pool))
        from test_personal_profile import check_profile_contract

        prefs_owner = f"{key}_prefs"
        await check_profile_contract(PostgresTrips(prefs_owner, pool), PostgresLongTermMemory(prefs_owner, pool),
                                     PostgresTrips(f"{key}_other", pool))


async def test_only_server_candidate_is_saved_and_it_is_owner_and_session_scoped(tmp_path):
    req = TripRequest(trip_id="abcdefg", origin="上海", destination="北京", depart_date="2027-01-11",
                      return_date="2027-01-12", passengers=1, unresolved={"meeting": "需要确认"})
    snap = build_snapshot({"trip_plan": {"status": "partial", "alternatives": [
        {"id": "sample-direct-rail", "status": "provisional", "outbound": {
            "train_no": "G101", "from_station": "上海虹桥", "to_station": "北京南",
            "departs": "2027-01-11T08:00:00+08:00", "arrives": "2027-01-11T13:00:00+08:00",
        }},
    ]}}, req)
    assert snap.options[0].schedule_items[0].kind == "rail" and snap.options[0].quotes == []
    cache = CandidateCache()
    ref = cache.add("a", "source_session", snap)
    payload = CandidateInput(source="candidate", candidate_ref=ref, session_id="source_session", option_id="sample-direct-rail")
    for user, candidate in [("b", payload), ("a", payload.model_copy(update={"session_id": "wrong"}))]:
        with pytest.raises(PersonalError) as missing:
            await Trips(JsonTrips(user, tmp_path), cache=cache).create(candidate, "candidate-0000001")
        assert missing.value.status == 404
    trips = Trips(JsonTrips("a", tmp_path), cache=cache)
    saved = await trips.create(payload, "candidate-0000001")
    context = await trips.trip_context(PlanRef(plan_id=saved["plan_id"], version=1))
    assert (context.origin, context.destination, context.unresolved) == ("上海", "北京", {"meeting": "需要确认"})
    broken = NewVersion(based_on_version=1, content=payload)
    with pytest.raises(PersonalError, match="基于你选择"):
        await trips.add_version(saved["plan_id"], broken, 1, "candidate-0000002")


async def test_personal_api_requires_identity_origin_and_csrf(tmp_path, monkeypatch):
    from server.app import app
    from server.auth import signing_key
    from server.routes import personal

    monkeypatch.setenv("ALIGO_PERSONAL_CENTER_ENABLED", "1")
    monkeypatch.setenv("ALIGO_SESSION_SECRET", "x" * 32)
    signing_key.cache_clear()

    async def use_test_repo(owner):
        return JsonTrips(owner, tmp_path)

    monkeypatch.setattr(personal, "trip_repository", use_test_repo)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://travel.test") as a, AsyncClient(
            transport=ASGITransport(app=app), base_url="https://travel.test",
        ) as b:
            assert (await a.get("/api/personal/trips")).status_code == 401
            await a.post("/api/identity")
            await b.post("/api/identity")
            cap = await a.get("/api/personal/capabilities")
            token = cap.json()["csrf_token"]
            assert cap.headers["cache-control"] == "private, no-store"
            create = "/api/personal/trips"
            body = _manual().model_dump(mode="json")
            headers = {"origin": "https://travel.test", "x-aligo-csrf": token, "idempotency-key": "test-create-000001"}
            for removed in ("origin", "x-aligo-csrf"):
                assert (await a.post(create, json=body, headers={k: v for k, v in headers.items() if k != removed})).status_code == 403
            assert (await b.post(create, json=body, headers=headers)).status_code == 403
            saved_response = await a.post(create, json=body, headers=headers)
            assert saved_response.status_code == 201, saved_response.text
            saved = f'{create}/{saved_response.json()["plan_id"]}'
            assert (await b.get(saved)).status_code == 404
            assert (await a.get(saved)).headers["etag"] == '"1"'
            await a.post(create, json={**body, "draft": {**body["draft"], "title": "第二次"}}, headers={
                **headers, "idempotency-key": "test-create-000002",
            })
            page = (await a.get(create, params={"limit": 1})).json()
            assert page["next_cursor"]
            older = (await a.get(create, params={"cursor": page["next_cursor"], "limit": 1})).json()
            assert len(older["items"]) == 1 and older["items"][0]["title"] == "上海会议"
    finally:
        signing_key.cache_clear()
