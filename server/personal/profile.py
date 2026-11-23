"""明确授权的个人偏好和可核对的收藏引用。"""
import re
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from server.personal.models import Event, FavoriteInput, Money, PlanSnapshot
from server.personal.service import PersonalError, _now, _plan, _slug_payload, _version


PREFERENCE_FIELDS = {
    "home_city": "常用出发城市", "destination_preference": "常用目的地",
    "transportation_preference": "交通方式", "seat_preference": "座位类型",
    "hotel_brands": "住宿偏好", "nightly_budget": "每晚住宿预算",
    "departure_period": "偏好出发时段", "meal_preference": "饮食偏好", "trip_pace": "行程节奏",
}
_ACTIVE_FIELDS = {"home_city", "transportation_preference", "hotel_brands", "nightly_budget", "departure_period"}
_TRANSPORT = {"铁路": "rail", "高铁": "high_speed", "动车": "high_speed", "火车": "rail", "飞机": "flight"}
_PERIODS = {"早上": "morning", "上午": "morning", "下午": "afternoon", "晚上": "evening"}
_CITY = re.compile(r"^(?:[\u4e00-\u9fff·]{2,12}|[A-Za-z][A-Za-z .-]{1,26})$")
_TZ = ZoneInfo("Asia/Shanghai")


def _view_preferences(data):
    state = data.state.get("personalization", {})
    approved = set(state.get("approved_fields", []))
    fields = {key: data.preferences.get(key) for key in PREFERENCE_FIELDS}
    # The stale-check includes the underlying preference value: writing
    # through the legacy endpoint also invalidates an open edit form.
    version = _slug_payload(fields, state)
    return {"enabled": state.get("enabled") is True, "revision": version,
            "items": [{"key": key, "label": label, "value": fields[key], "use_for_planning": key in approved,
                       "supported_for_planning": key in _ACTIVE_FIELDS}
                      for key, label in PREFERENCE_FIELDS.items()]}


def _setting_value(key, value):
    if value is None:
        return None
    if key == "nightly_budget":
        if not isinstance(value, Money):
            raise PersonalError(422, "budget_value_required", "请填写金额和币种。")
        return value.model_dump(mode="json")
    if not isinstance(value, str):
        raise PersonalError(422, "text_value_required", "请填写一项文字偏好。")
    if key in {"home_city", "destination_preference"} and (not _CITY.fullmatch(value) or re.search(r"区|县|街|路|巷|小区|公寓|大厦|室", value)):
        raise PersonalError(422, "city_value_required", "这里只保存城市，例如「上海」，不要填写详细地址。")
    if key == "departure_period" and value not in _PERIODS:
        raise PersonalError(422, "departure_value_required", "请选择上午、下午或晚上。")
    return value


def _verify_revision(data, expected):
    if _view_preferences(data)["revision"] != expected:
        raise PersonalError(412, "preferences_changed", "偏好已更新，请刷新后重新保存。")


def _first_string(value):
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, str)), None)
    return value.strip() if isinstance(value, str) else None


class Profile:
    def __init__(self, repository):
        self.repository = repository

    async def preferences(self):
        return await self.repository.run(_view_preferences, profile=True)

    async def edit(self, key, update):
        value = _setting_value(key, update.value)
        if update.use_for_planning and (not value or key not in _ACTIVE_FIELDS):
            raise PersonalError(422, "unsupported_preference_use", "这一项暂不能用于自动规划。")

        def write(data):
            _verify_revision(data, update.expected_revision)
            config = data.state.setdefault("personalization", {})
            approved = set(config.get("approved_fields", []))
            if value is None:
                data.preferences.pop(key, None)
            else:
                data.preferences[key] = value
            if update.use_for_planning and value is not None:
                approved.add(key)
            else:
                approved.discard(key)
            config["approved_fields"] = sorted(approved)
            return _view_preferences(data)

        return await self.repository.run(write, write=True, profile=True)

    async def settings(self, update):
        def write(data):
            _verify_revision(data, update.expected_revision)
            data.state.setdefault("personalization", {})["enabled"] = update.enabled
            return _view_preferences(data)
        return await self.repository.run(write, write=True, profile=True)

    async def remember(self, preferences):
        def write(data):
            accepted = []
            config = data.state.setdefault("personalization", {})
            approved = set(config.get("approved_fields", []))
            for item in preferences:
                key = "home_city" if item.get("type") == "home_location" else item.get("type")
                if key not in PREFERENCE_FIELDS:
                    continue
                try:
                    value = _setting_value(key, item.get("value"))
                except PersonalError:
                    continue
                if not value:
                    continue
                if item.get("action") == "append" and key != "home_city":
                    old = data.preferences.get(key)
                    values = old if isinstance(old, list) else [old] if old else []
                    data.preferences[key] = list(dict.fromkeys([*(row for row in values if isinstance(row, str)), value]))
                else:
                    data.preferences[key] = value
                approved.discard(key)
                accepted.append(PREFERENCE_FIELDS[key])
            config["approved_fields"] = sorted(approved)
            return list(dict.fromkeys(accepted))
        return await self.repository.run(write, write=True, profile=True)

    async def hints(self, *, trip=None, exclude_plan=None):
        def read(data):
            windows = _busy_windows(data, trip, exclude_plan)
            config = data.state.get("personalization", {})
            if config.get("enabled") is not True:
                return {"busy_windows": windows} if windows else {}
            approved = set(config.get("approved_fields", [])) & _ACTIVE_FIELDS
            prefs = {key: data.preferences.get(key) for key in approved}
            hints = {key: value for key, value in {
                "transport": _TRANSPORT.get(_first_string(prefs.get("transportation_preference")) or ""),
                "departure": _PERIODS.get(_first_string(prefs.get("departure_period")) or ""),
                "hotel_brand": (_first_string(prefs.get("hotel_brands")) or "")[:48] or None,
            }.items() if value is not None}
            try:
                city = _setting_value("home_city", _first_string(prefs.get("home_city")))
                if city:
                    hints["suggested_origin"] = city
            except PersonalError:
                pass
            cap = prefs.get("nightly_budget")
            if isinstance(cap, dict):
                try:
                    hints["nightly_budget"] = Money.model_validate(cap).model_dump(mode="json")
                except ValueError:
                    pass
            if windows:
                hints["busy_windows"] = windows
            return hints
        return await self.repository.run(read, profile=True, schedule=bool(trip and trip.depart_date))


def _busy_windows(data, trip, exclude_plan):
    if not trip or not trip.depart_date:
        return []
    first = datetime.combine(trip.depart_date, time.min, _TZ).astimezone(UTC)
    end = trip.effective_return or trip.depart_date
    last = datetime.combine(end + timedelta(days=1), time.min, _TZ).astimezone(UTC)
    intervals = []
    for key, row in data.schedule.items():
        if key == str(exclude_plan) or data.plans.get(key, {}).get("lifecycle") != "scheduled":
            continue
        for payload in row["events"]:
            if payload.get("precision") != "exact" or payload.get("commitment") != "fixed":
                continue
            item = Event.model_validate(payload)
            start = item.start_at.astimezone(UTC) - timedelta(minutes=item.before_minutes)
            finish = item.end_at.astimezone(UTC) + timedelta(minutes=item.after_minutes)
            if max(first, start) < min(last, finish):
                intervals.append((start, finish))
    return [[start.isoformat(), finish.isoformat()] for start, finish in sorted(intervals)[:32]]


class Favorites:
    def __init__(self, repository):
        self.repository = repository

    async def list(self, *, limit=50, offset=0):
        def read(data):
            items = sorted(data.favorites.values(), key=lambda row: row["created_at"], reverse=True)
            return {"items": items[offset:offset + limit], "next_offset": offset + limit if len(items) > offset + limit else None}
        return await self.repository.run(read, favorites=True)

    async def create(self, request: FavoriteInput):
        key = str(request.ref.plan_id)

        def write(data):
            plan = _plan(data, key)
            snapshot = PlanSnapshot.model_validate(_version(data, key, request.ref.version)["snapshot"])
            label, facts, dedupe = plan["title"], {}, (key, request.ref.version)
            if request.kind != "plan":
                option = next((row for row in snapshot.options if row.option_id == request.option_id), None)
                if not option:
                    raise PersonalError(404, "favorite_source_not_found", "找不到这一版中的方案。")
                if request.kind == "rail":
                    origin, destination = snapshot.origin, snapshot.destination
                    if request.direction == "inbound":
                        origin, destination = destination, origin
                    route = next((item for item in option.schedule_items if item.kind == "rail" and origin and destination
                                  and item.city == origin and item.arrival_city == destination), None)
                    if not route:
                        raise PersonalError(422, "no_stable_service", "此方案没有可识别的铁路班次。")
                    label = route.title
                    train = next(iter(re.findall(r"[A-Z]\d{1,8}", label)), None)
                    if not train:
                        raise PersonalError(422, "no_stable_service", "此方案没有可识别的铁路班次。")
                    facts = {"origin": origin, "destination": destination, "departed_at": route.start_at.isoformat(),
                             "service": train, "provider": "12306", "source_url": "https://www.12306.cn/"}
                    dedupe = ("12306", train, origin, destination)
                else:
                    if not option.hotel_ref or not option.hotel:
                        raise PersonalError(422, "no_stable_place", "该住宿或地点没有可复用的供应商标识。")
                    label = option.hotel
                    facts = {"place_ref": option.hotel_ref, "city": snapshot.destination, "provider": "高德地图",
                             "source_url": "https://www.amap.com/"}
                    dedupe = ("amap", option.hotel_ref)
            dedupe_key = _slug_payload(*dedupe)
            existing = next((row for row in data.favorites.values() if row["kind"] == request.kind and row["dedupe_key"] == dedupe_key), None)
            if existing:
                return existing
            if len(data.favorites) >= 350:
                raise PersonalError(429, "favorite_limit", "收藏数量已达上限。")
            identifier = str(uuid4())
            result = {"favorite_id": identifier, "created_at": _now().isoformat(), "kind": request.kind,
                      "dedupe_key": dedupe_key, "title": label, "ref": request.ref.model_dump(mode="json"), "snapshot": facts,
                      "suggest_recheck": request.kind != "plan"}
            data.favorites[identifier] = result
            return result

        return await self.repository.run(write, write=True, version_ids=(key,), favorites=True)

    async def delete(self, favorite_id):
        key = str(favorite_id)

        def remove(data):
            if key not in data.favorites:
                raise PersonalError(404, "favorite_not_found", "找不到该收藏。")
            del data.favorites[key]
            return {"removed": True}
        return await self.repository.run(remove, write=True, favorites=True)
