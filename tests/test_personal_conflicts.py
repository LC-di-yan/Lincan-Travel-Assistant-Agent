import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from server.personal.conflicts import TravelEvidence, evaluate, project
from server.personal.candidates import CandidateCache, build_snapshot
from server.personal.models import (CandidateInput, Event, ManualDraft, ManualInput, NewVersion, OperationCommit,
                                    OperationPreview, Option, PlanSnapshot, RestoreInput)
from server.personal.repository import JsonTrips
from server.personal.service import PersonalError, Trips

NOW = datetime(2026, 12, 3, tzinfo=UTC)


def _event(title, city="上海", start="2027-01-12T10:00:00+08:00", end="2027-01-12T11:00:00+08:00", **kwargs):
    return Event(title=title, commitment="fixed", precision="exact", start_at=start, end_at=end,
                 city=city, **{"kind": "meeting", **kwargs})


def _snapshot(*events, **fields):
    return PlanSnapshot(title="会议", schedule_items=events, quality="manual", source_kind="manual", **fields)


def _report(first, *other, routes=()):
    plan = project(str(uuid4()), 1, "新安排", first)
    others = [project(str(uuid4()), 1, "旧安排", snap) for snap in other]
    return evaluate(plan, others, snapshot=first, now=NOW, calendar_revision=4, evidence=routes)


def test_fixed_cross_midnight_overlap_and_rail_preparation_buffer_block():
    train = _event("夜间铁路", start="2027-01-12T23:00:00+08:00", end="2027-01-13T06:00:00+08:00",
                   arrival_city="北京", kind="rail", before_minutes=60)
    earlier = _event("晚间会议", start="2027-01-12T22:20:00+08:00", end="2027-01-12T22:40:00+08:00")
    after = _event("次日早会", city="北京", start="2027-01-13T05:30:00+08:00", end="2027-01-13T07:00:00+08:00")
    result = _report(_snapshot(train), _snapshot(earlier), _snapshot(after))
    assert {issue["code"] for issue in result["issues"]} == {"required_buffer", "exact_overlap"}
    assert not result["can_commit"] and all(row["severity"] == "definite" for row in result["issues"])


def test_dates_and_hotel_checkpoints_do_not_create_hard_overlaps():
    hotel = Event(title="酒店退房", kind="check_out", precision="date_only", local_date="2027-01-12", city="上海")
    old = _snapshot(hotel, start_date="2027-01-11", end_date="2027-01-13", destination="上海")
    other_city = _snapshot(_event("杭州会议", "杭州"))
    result = _report(other_city, old)
    assert result["can_commit"]
    assert {row["severity"] for row in result["issues"]} == {"potential"}
    assert all("酒店" not in row["message"] for row in result["issues"])
    assert not _report(_snapshot(_event("上海会议")), old)["issues"]


def test_legacy_same_day_suggestions_produce_one_uncertainty_not_pairwise_conflicts():
    itinerary = {"title": "三日差旅", "daily_plans": [
        {"date": f"2027-01-{day}", "city": "上海", "activities": [
            {"time": hour, "activity": f"第 {day} 日的 {hour} 活动"} for hour in ("上午", "下午", "晚上")
        ]} for day in (12, 13, 14)
    ]}
    draft = build_snapshot({"results": [{"agent_name": "itinerary_planning", "status": "success",
                                       "data": {"itinerary": itinerary}}]})
    assert draft.source_kind == "legacy" and len(draft.schedule_items) == 9
    report = _report(draft)
    assert [(issue["code"], issue["other"], issue["severity"]) for issue in report["issues"]] == [
        ("legacy_time_unverified", None, "unknown")]
    assert report["can_commit"]

    # An actual cross-plan conflict stays blocking, even in a draft that also
    # contains suggestions without precise times.
    revised = draft.model_copy(update={"schedule_items": [*draft.schedule_items, _event("已知起止的会议")]})
    report = _report(revised, _snapshot(_event("已安排的旧会议")))
    conflicts = [issue for issue in report["issues"] if issue["code"] == "exact_overlap"]
    assert len(conflicts) == 1 and conflicts[0]["other"]["title"] == "旧安排"
    assert not report["can_commit"]
    internal = revised.model_copy(update={"schedule_items": [*revised.schedule_items, _event("同一行程另一场固定会议")]})
    assert any(issue["code"] == "exact_overlap" and issue["other"] is None for issue in _report(internal)["issues"])


def test_missing_and_estimated_transfer_remain_distinguishable():
    first = _event("上海会谈", place="上海办公点")
    second = _event("苏州会谈", "苏州", start="2027-01-12T11:30:00+08:00", end="2027-01-12T13:00:00+08:00", place="苏州办公点")
    missing = _report(_snapshot(second), _snapshot(first))
    assert missing["issues"][0]["severity"] == "unknown"
    estimated = TravelEvidence("上海办公点", "苏州办公点", 45, "route_estimate", NOW + timedelta(days=1))
    warning = _report(_snapshot(second), _snapshot(first), routes=(estimated,))
    assert warning["issues"][0]["severity"] == "potential" and warning["can_commit"]
    minimum = TravelEvidence("上海办公点", "苏州办公点", 45, "verified_minimum", NOW + timedelta(days=1))
    assert not _report(_snapshot(second), _snapshot(first), routes=(minimum,))["can_commit"]


def test_touching_events_at_same_place_are_valid_but_different_cities_are_impossible():
    a = _event("前一场", place="同一个会议室")
    b = _event("下一场", place="同一个会议室", start="2027-01-12T11:00:00+08:00", end="2027-01-12T12:00:00+08:00")
    assert not _report(_snapshot(a), _snapshot(b))["issues"]
    result = _report(_snapshot(a), _snapshot(b.model_copy(update={"city": "杭州"})))
    assert result["issues"][0]["code"] == "intercity_gap" and not result["can_commit"]


def test_unknown_required_time_blocks_unless_date_is_known():
    fixed = Event(title="时间未定", kind="meeting", commitment="fixed")
    blocked = _report(_snapshot(fixed, start_date="2027-01-12"))
    assert not blocked["can_commit"] and blocked["issues"][0]["code"] == "missing_fixed_time"
    tentative = fixed.model_copy(update={"precision": "date_only", "local_date": datetime(2027, 1, 12).date()})
    assert _report(_snapshot(tentative))["can_commit"]


def _create(title, city="上海", *, rough=False):
    item = (Event(title=f"{title}会议", kind="meeting", city=city, precision="date_only", local_date="2027-01-12")
            if rough else _event(f"{title}会议", city, place="主会场"))
    return ManualInput(source="manual", draft=ManualDraft(title=title, destination=city, start_date="2027-01-12", schedule_items=[item]))


async def _preview(trips, plan, action="schedule", refs=()):
    return await trips.preview(plan["plan_id"], OperationPreview(action=action, draft_version=plan["version"],
                                                               expected_revision=plan["revision"], replace_refs=refs))


def _commit(preview, acknowledged=()):
    return OperationCommit(operation_id=preview["operation_id"], confirmed=True, acknowledged_issue_ids=acknowledged)


async def check_schedule_contract(trips, same_owner, other):
    first = await trips.create(_create("项目甲"), "project-first-0001")
    second = await same_owner.create(_create("项目乙", "杭州"), "project-second-001")
    p1, p2 = await asyncio.gather(_preview(trips, first), _preview(same_owner, second))
    pair = await asyncio.gather(trips.commit(first["plan_id"], _commit(p1), "schedule-first-001"),
                                same_owner.commit(second["plan_id"], _commit(p2), "schedule-second-01"), return_exceptions=True)
    assert sum(isinstance(item, PersonalError) for item in pair) == 1
    outcome, blocked = ((first, second) if not isinstance(pair[0], PersonalError) else (second, first))
    failed = next(item for item in pair if isinstance(item, PersonalError))
    assert failed.code == "calendar_changed"
    checked = await _preview(trips, blocked)
    assert checked["operation_id"] is None and not checked["report"]["can_commit"]
    options = [issue["other"] for issue in checked["report"]["issues"] if issue["severity"] == "definite"]
    refs = [{key: options[0][key] for key in ("plan_id", "revision", "version")}]
    with pytest.raises(PersonalError) as invisible:
        await _preview(other, blocked, "replace", refs)
    assert invisible.value.status == 404
    prepare = await _preview(trips, blocked, "replace", refs)
    assert prepare["replacements"][0]["plan_id"] == outcome["plan_id"]
    result = await trips.commit(blocked["plan_id"], _commit(prepare), "replace-first-00001")
    assert result == await same_owner.commit(blocked["plan_id"], _commit(prepare), "replace-first-00001")
    assert (await trips.get(outcome["plan_id"]))["plan"]["lifecycle"] == "superseded"
    assert (await same_owner.get(blocked["plan_id"]))["scheduled"]["version"] == 1

    # Replaying the old draft as a fresh version must not overwrite the scheduled snapshot.
    appended = await trips.add_version(blocked["plan_id"], NewVersion(based_on_version=1, content=RestoreInput(source="saved_version")),
                                     result["revision"], "schedule-version02")
    assert appended["version"] == 2 and (await trips.get(blocked["plan_id"]))["scheduled"]["version"] == 1
    changed = await _preview(same_owner, appended, "reschedule")
    finished = await trips.commit(blocked["plan_id"], _commit(changed), "reschedule-first01")
    assert finished["version"] == 2 and (await trips.get(blocked["plan_id"]))["scheduled"]["version"] == 2


async def test_json_calendar_confirmation_and_replacement_are_atomic(tmp_path):
    await check_schedule_contract(Trips(JsonTrips("a", tmp_path)), Trips(JsonTrips("a", tmp_path)), Trips(JsonTrips("b", tmp_path)))


async def test_risk_acknowledgement_cannot_be_bypassed(tmp_path):
    trips = Trips(JsonTrips("a", tmp_path))
    a = await trips.create(_create("项目甲", rough=True), "warning-first-0001")
    b = await trips.create(_create("项目乙", "杭州"), "warning-second-001")
    a_preview = await _preview(trips, a)
    await trips.commit(a["plan_id"], _commit(a_preview), "warning-arrange-001")
    b_preview = await _preview(trips, b)
    risks = [item["id"] for item in b_preview["report"]["issues"] if item["requires_ack"]]
    assert risks
    with pytest.raises(PersonalError) as missing:
        await trips.commit(b["plan_id"], _commit(b_preview), "warning-confirm-001")
    assert missing.value.code == "review_required"
    assert (await trips.get(b["plan_id"]))["plan"]["lifecycle"] == "draft"
    assert (await trips.commit(b["plan_id"], _commit(b_preview, risks), "warning-confirm-002"))["lifecycle"] == "scheduled"


async def test_quote_expiring_between_preview_and_commit_preserves_the_existing_draft(tmp_path, monkeypatch):
    from server.personal import service

    moment = [NOW]
    monkeypatch.setattr(service, "_now", lambda: moment[0])
    cache = CandidateCache()
    snapshot = _snapshot(_event("确定的会议"), options=[Option(
        option_id="known_quote", status="validated", quotes=[
            {"price": {"amount": "125.00", "currency": "CNY"}, "unit": "seat", "source_url": "https://www.12306.cn/",
             "queried_at": NOW - timedelta(seconds=5), "valid_until": NOW + timedelta(seconds=5)},
        ],
    )], selected_option_id="known_quote")
    ref = cache.add("a", "quote_scope", snapshot)
    trips = Trips(JsonTrips("a", tmp_path), cache=cache)
    plan = await trips.create(CandidateInput(source="candidate", candidate_ref=ref, session_id="quote_scope"), "quotes-create-0001")
    check = await _preview(trips, plan)
    assert datetime.fromisoformat(check["expires_at"]) == NOW + timedelta(seconds=5)
    moment[0] += timedelta(seconds=6)
    with pytest.raises(PersonalError) as expired:
        await trips.commit(plan["plan_id"], _commit(check), "new-confirm-000001")
    assert expired.value.status == 410
    assert (await trips.get(plan["plan_id"]))["plan"]["lifecycle"] == "draft"
    assert any(item["code"] == "quote_expired" for item in (await _preview(trips, plan))["report"]["issues"])
