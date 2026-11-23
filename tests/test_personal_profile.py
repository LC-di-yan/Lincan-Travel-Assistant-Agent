from inspect import isawaitable
from uuid import uuid4

import pytest

from context.long_term_memory import LongTermMemory
from server.personal.candidates import CandidateCache, build_snapshot
from server.personal.models import CandidateInput, FavoriteInput, PlanRef, PreferenceEdit, PreferenceSettings
from server.personal.profile import Favorites, Profile
from server.personal.repository import JsonTrips
from server.personal.service import PersonalError, Trips
from utils.trip_request import TripRequest


def _options():
    req = TripRequest(trip_id="profile-test", origin="上海", destination="北京", depart_date="2027-01-11",
                      return_date="2027-01-12", passengers=1)
    return build_snapshot({"trip_plan": {"status": "partial", "alternatives": [{
        "id": "profile-variant", "status": "provisional",
        "outbound": {"train_no": "G101", "from_station": "上海虹桥", "to_station": "北京南",
                     "departs": "2027-01-11T10:00:00+08:00", "arrives": "2027-01-11T15:00:00+08:00"},
        "hotel": {"name": "供应商测试住宿", "id": "stable-fixture-id"},
    }]}}, req)


async def check_profile_contract(repo, memory, other):
    profile = Profile(repo)
    start = await profile.preferences()
    assert not start["enabled"] and not await profile.hints()
    result = memory.save_preference("home_location", "上海市浦东新区旧测试路1号")
    if isawaitable(result):
        await result
    with pytest.raises(PersonalError) as address:
        await profile.edit("home_city", PreferenceEdit(expected_revision=start["revision"], value="上海市浦东新区", use_for_planning=True))
    assert address.value.status == 422
    result = await profile.edit("home_city", PreferenceEdit(expected_revision=start["revision"], value="上海", use_for_planning=True))
    assert not await profile.hints()
    with pytest.raises(PersonalError) as stale:
        await profile.settings(PreferenceSettings(enabled=True, expected_revision=start["revision"]))
    assert stale.value.status == 412
    active = await profile.settings(PreferenceSettings(enabled=True, expected_revision=result["revision"]))
    assert await profile.hints() == {"suggested_origin": "上海"}
    assert not await Profile(other).hints()
    assert await profile.remember([{"type": "home_location", "value": "杭州"}, {"type": "home_location", "value": "广州市天河区"}]) == ["常用出发城市"]
    view = await profile.preferences()
    assert view["revision"] != active["revision"] and view["enabled"]
    assert not await profile.hints()
    blank = await profile.edit("home_city", PreferenceEdit(expected_revision=view["revision"], value=None, use_for_planning=False))
    assert next(row for row in blank["items"] if row["key"] == "home_city")["value"] is None
    raw = memory.get_preference("home_location")
    if isawaitable(raw):
        raw = await raw
    assert raw == "上海市浦东新区旧测试路1号"  # Do not erase legacy data when editing this field.

    cache = CandidateCache()
    candidate = cache.add(repo.user_id, "test_session", _options())
    trips = Trips(repo, cache=cache)
    created = await trips.create(CandidateInput(source="candidate", candidate_ref=candidate,
                                                session_id="test_session"), "favorites-00000001")
    ref = PlanRef(plan_id=created["plan_id"], version=1)
    fav = Favorites(repo)
    rail = FavoriteInput(kind="rail", ref=ref, option_id="profile-variant", direction="outbound")
    first = await fav.create(rail)
    assert first == await fav.create(rail)
    assert first["snapshot"]["service"] == "G101" and first["suggest_recheck"]
    place = await fav.create(FavoriteInput(kind="place", ref=ref, option_id="profile-variant"))
    assert place["snapshot"]["place_ref"] == "stable-fixture-id"
    with pytest.raises(PersonalError) as hidden:
        await Favorites(other).create(rail)
    assert hidden.value.status == 404
    assert not (await Favorites(other).list())["items"]
    await fav.delete(first["favorite_id"])
    assert (await trips.version(ref.plan_id, ref.version))["snapshot"]["options"]


async def test_preferences_require_permission_for_planning_and_favorites_use_original_snapshot(tmp_path):
    repo = JsonTrips("a", tmp_path)
    await check_profile_contract(repo, LongTermMemory("a", tmp_path), JsonTrips("b", tmp_path))
