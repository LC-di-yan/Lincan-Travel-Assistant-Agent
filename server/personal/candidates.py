"""从服务器的最终规划结果生成限期引用，不信任客户端回传的结果卡。"""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import Lock
import time
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from server.personal.models import Event, Observation, Option, PlanRef, PlanSnapshot, Quote, RecordedRoute
from utils.trip_request import TripRequest

_TZ = ZoneInfo("Asia/Shanghai")


def _text(value, limit=120):
    return (value.strip()[:limit].strip() or None) if isinstance(value, str) else None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _event_id(trip_id, kind):
    return uuid5(NAMESPACE_URL, f"aligo:{trip_id}:{kind}")


def _option(req: TripRequest, row: dict) -> Option:
    items, quotes, observations = [], [], []

    def observed(kind, source, raw):
        try:
            return Observation(kind=kind, source_url=source, observed_at=raw)
        except ValidationError:
            return Observation(kind=kind, source_url=source)
    for direction, origin, destination in (
        ("outbound", req.origin, req.destination), ("inbound", req.destination, req.origin),
    ):
        leg = _mapping(row.get(direction))
        if not leg:
            continue
        try:
            items.append(Event(
                event_id=_event_id(req.trip_id, direction), kind="rail", title=f"铁路 {leg['train_no']}",
                commitment="fixed", precision="exact", start_at=leg["departs"], end_at=leg["arrives"],
                city=origin, arrival_city=destination, place=_text(leg.get("from_station")),
                arrival_place=_text(leg.get("to_station")), before_minutes=60,
            ))
        except (KeyError, ValidationError):
            continue
        if leg.get("quote"):
            quotes.append(("seat", leg["quote"]))
        observations.append(observed(f"{direction}_rail", "https://www.12306.cn/", leg.get("queried_at")))

    hotel = _mapping(row.get("hotel"))
    if hotel:
        observations.append(observed("hotel_place", "https://www.amap.com/", hotel.get("queried_at")))
    if hotel.get("quote"):
        quotes.append(("room_night", hotel["quote"]))
    if hotel and req.depart_date and req.effective_return and req.nights:
        for kind, day, display in (("check_in", req.depart_date, "入住"), ("check_out", req.effective_return, "退房")):
            items.append(Event(event_id=_event_id(req.trip_id, kind), title=display, kind=kind, city=req.destination,
                               place=_text(hotel.get("name")), precision="date_only", local_date=day))
    valid_quotes = []
    for unit, item in quotes:
        quote = _mapping(item)
        if quote.get("quality") != "verified_quote":
            continue
        try:
            valid_quotes.append(Quote(price={"amount": quote["amount"], "currency": quote["currency"]}, unit=unit,
                                     source_url=quote["source_url"], queried_at=quote["queried_at"],
                                     valid_until=quote["valid_until"]))
        except (KeyError, ValidationError):
            continue
    commute = None
    route = _mapping(row.get("commute"))
    if route.get("quality") == "reference_estimate" and req.meeting_place and hotel.get("name"):
        try:
            commute = RecordedRoute(from_place=_text(hotel["name"]), to_place=req.meeting_place,
                                    minutes=route["duration_min"], queried_at=route["queried_at"], source_url=route["source_url"])
        except (KeyError, ValidationError):
            pass
    return Option(
        option_id=row.get("id"), status=row.get("status"), schedule_items=items,
        hotel=_text(hotel.get("name")), hotel_ref=_text(hotel.get("id")), quotes=valid_quotes, observations=observations, commute=commute,
        hotel_reference_cny=hotel.get("reference_cny") or [],
        known_subtotals=row.get("known_subtotals", {}),
        reasons=[note for value in (row.get("reasons") or [])[:12] if (note := _text(value, 600))],
    )


def _typed(result: dict, req: TripRequest, based_on: PlanRef | None, carry_items=()):
    plan = _mapping(result.get("trip_plan"))
    if not plan or not req.origin or not req.destination or not req.depart_date:
        return None
    items = []
    if req.meeting_requested:
        start = datetime.combine(req.meeting_date, req.meeting_start, _TZ) if req.meeting_date and req.meeting_start else None
        end = datetime.combine(req.meeting_date, req.meeting_end, _TZ) if req.meeting_date and req.meeting_end else None
        precise = bool(start and end and start < end)
        items.append(Event(
            event_id=_event_id(req.trip_id, "meeting"), title="会议", kind="meeting",
            commitment="fixed", city=req.destination, place=req.meeting_place,
            precision="exact" if precise else "date_only" if req.meeting_date else "unknown",
            start_at=start if precise else None, end_at=end if precise else None,
            local_date=req.meeting_date if not precise else None,
        ))
    items.extend(carry_items[:120 - len(items)])
    options = []
    for row in (plan.get("alternatives") or [])[:3]:
        try:
            options.append(_option(req, _mapping(row)))
        except ValidationError:
            continue
    valid_ids = {item.option_id for item in options}
    selected = plan.get("selected_proposal")
    default_option = selected if selected in valid_ids else None
    issues = [note for row in (plan.get("issues") or [])[:40] if (note := _text(_mapping(row).get("message"), 600))]
    if not options:
        issues = ["没有可核验的交通或住宿候选，仅保存已提供的要求。", *issues[:39]]
    budget = req.budget.model_dump() if req.budget and req.budget.currency else None
    return PlanSnapshot(
        source_kind="typed", quality="structured" if plan.get("status") == "success" and options else "partial",
        title=f"{req.origin} → {req.destination}差旅", origin=req.origin, destination=req.destination,
        start_date=req.depart_date, end_date=req.effective_return or req.depart_date, schedule_items=items,
        trip_request=req, issues=issues, options=options, selected_option_id=default_option, budget=budget, based_on=based_on,
    )


def _calendar_day(value):
    try:
        result = date.fromisoformat(str(value)) if value else None
        return result if result and 1900 <= result.year <= 2200 else None
    except ValueError:
        return None


def from_summary(row: dict) -> PlanSnapshot:
    start, end = _calendar_day(row.get("start_date")), _calendar_day(row.get("end_date"))
    if not start or end and not timedelta(0) <= end - start <= timedelta(days=30):
        end = None
    origin, destination = (_text(row.get(field), 32) for field in ("origin", "destination"))
    origin = origin if origin and len(origin) >= 2 else None
    destination = destination if destination and len(destination) >= 2 else None
    title = f"{origin} → {destination}差旅" if origin and destination else f"{destination or origin or '旧'}行程摘要"
    return PlanSnapshot(title=title, origin=origin, destination=destination, start_date=start, end_date=end,
                        source_kind="imported_summary", quality="partial", notes=_text(row.get("purpose"), 600) or "",
                        issues=["旧记录只有摘要，请补齐后再安排。"])


def _legacy(result: dict, based_on: PlanRef | None):
    for row in result.get("results") or []:
        if row.get("agent_name") not in {"itinerary_planning", "plan-trip"} or row.get("status") != "success":
            continue
        data = _mapping(row.get("data"))
        inner = _mapping(data.get("itinerary") or data.get("data") or data)
        itinerary = _mapping(inner.get("itinerary") or inner)
        days = itinerary.get("daily_plans")
        if not isinstance(days, list) or not days or itinerary.get("planning_complete") is False or data.get("planning_complete") is False:
            continue
        items, dates = [], []
        for day in map(_mapping, days[:31]):
            event_day = _calendar_day(day.get("date"))
            if event_day:
                dates.append(event_day)
            city = _text(day.get("city"), 32)
            for activity in map(_mapping, (day.get("activities") or [])[:20]):
                title = _text(activity.get("activity") or activity.get("location"))
                if not title:
                    continue
                items.append(Event(title=title, kind="activity", precision="date_only" if event_day else "unknown",
                                   local_date=event_day, city=city if city and len(city) >= 2 else None,
                                   place=_text(activity.get("location")),
                                   notes="；".join(filter(None, (_text(activity.get("time")), _text(activity.get("description"), 400))))[:600]))
                if len(items) == 120:
                    break
            if len(items) == 120:
                break
        if items:
            return PlanSnapshot(
                title=_text(itinerary.get("title")) or "差旅行程", schedule_items=items,
                start_date=min(dates) if dates else None,
                end_date=max(dates) if dates and (max(dates) - min(dates)).days <= 30 else None,
                source_kind="legacy", quality="partial", based_on=based_on,
                raw_estimate=_text(itinerary.get("estimated_budget"), 600),
                issues=["旧式行程中的活动时间、交通与报价是待核对的建议。"],
            )
    return None


def build_snapshot(result: dict, trip: TripRequest | None = None, based_on: PlanRef | None = None, carry_items=()):
    if trip is not None:
        return _typed(result, trip, based_on, carry_items)
    return _legacy(result, based_on)


@dataclass(frozen=True)
class Candidate:
    user_id: str
    session_id: str
    snapshot: PlanSnapshot
    expires_at: float


class CandidateCache:
    def __init__(self, *, capacity=180, per_user=8, ttl=1800):
        self.capacity, self.per_user, self.ttl = capacity, per_user, ttl
        self._entries: OrderedDict[UUID, Candidate] = OrderedDict()
        self._lock = Lock()

    def add(self, user_id: str, session_id: str, snapshot: PlanSnapshot) -> UUID:
        now = time.monotonic()
        with self._lock:
            for key in [key for key, item in self._entries.items() if item.expires_at <= now]:
                del self._entries[key]
            owned = [key for key, item in self._entries.items() if item.user_id == user_id]
            for key in owned[:max(0, len(owned) + 1 - self.per_user)]:
                del self._entries[key]
            while len(self._entries) >= self.capacity:
                self._entries.popitem(last=False)
            ref = uuid4()
            self._entries[ref] = Candidate(user_id, session_id, snapshot, now + self.ttl)
            return ref

    def get(self, user_id, session_id, ref):
        with self._lock:
            item = self._entries.get(ref)
            if item and item.user_id == user_id and item.session_id == session_id and item.expires_at > time.monotonic():
                return item.snapshot
            return None


candidates = CandidateCache()
