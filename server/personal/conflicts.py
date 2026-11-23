"""确定性日程冲突规则。粗粒度输入从不当作全天硬占用。"""
from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from server.personal.models import Event, PlanSnapshot

RULE_VERSION = 2
_TZ = ZoneInfo("Asia/Shanghai")
_FIXED_TRANSIT = {"rail", "flight"}
_CHECKPOINTS = {"check_in", "check_out"}


@dataclass(frozen=True)
class Schedule:
    plan_id: str
    version: int
    title: str
    blocks: tuple[Event, ...]


@dataclass(frozen=True)
class TravelEvidence:
    from_place: str
    to_place: str
    minutes: int
    quality: Literal["verified_minimum", "route_estimate"]
    valid_until: datetime


def project(plan_id: str, version: int, title: str, snapshot: PlanSnapshot) -> Schedule:
    selected = next((entry for entry in snapshot.options if entry.option_id == snapshot.selected_option_id), None)
    events = [*snapshot.schedule_items, *(selected.schedule_items if selected else [])]
    if snapshot.start_date:
        events.append(Event(event_id=uuid5(UUID(plan_id), "date-scope"), kind="activity", title="行程日期范围",
                            precision="date_only", local_date=snapshot.start_date, end_date=snapshot.end_date,
                            city=snapshot.destination, commitment="soft"))
    return Schedule(plan_id, version, title, tuple({item.event_id: item for item in events}.values()))


def _bounds(event):
    if event.start_at and event.end_at:
        return (event.start_at.astimezone(UTC) - timedelta(minutes=event.before_minutes),
                event.end_at.astimezone(UTC) + timedelta(minutes=event.after_minutes))
    if event.local_date:
        try:
            return (datetime.combine(event.local_date, time.min, _TZ).astimezone(UTC),
                    datetime.combine((event.end_date or event.local_date) + timedelta(days=1), time.min, _TZ).astimezone(UTC))
        except (ValueError, OverflowError):
            return None
    return None


def _city(name):
    return name.strip().removesuffix("市").casefold() if name else None


def _loc(name):
    return name.strip().casefold() if name else None


def _is_scope(schedule, event):
    return uuid5(UUID(schedule.plan_id), "date-scope") == event.event_id


def _bounded_event(event):
    return event.kind not in _CHECKPOINTS or (event.precision in {"exact", "window"} and event.commitment == "fixed")


def _issue(code, severity, message, primary, event=None, against=None, conflicting=None, *, blocking=False):
    anchors = f"{primary.plan_id}:{primary.version}:{getattr(event, 'event_id', '')}"
    if against:
        anchors += f":{against.plan_id}:{against.version}:{getattr(conflicting, 'event_id', '')}"
    bounds = _bounds(event) if event else None
    return {
        "id": uuid5(NAMESPACE_URL, f"aligo:conflict:{RULE_VERSION}:{code}:{anchors}").hex,
        "code": code, "severity": severity, "message": message,
        "requires_ack": severity != "definite" and not blocking, "blocks_schedule": severity == "definite" or blocking,
        "event_ref": str(event.event_id) if event else None,
        "window": [item.isoformat() for item in bounds] if bounds else None,
        "other": {"plan_id": against.plan_id, "version": against.version, "title": against.title,
                  "event_ref": str(conflicting.event_id) if conflicting else None} if against and against.plan_id != primary.plan_id else None,
    }


def _label(plan, event, current):
    return f"「{plan.title}」的{event.title}" if plan.plan_id != current.plan_id else f"「{event.title}」"


def _compare(current, evidence, now, sa, ea, sb, eb):
    if sa.plan_id != current.plan_id:
        sa, ea, sb, eb = sb, eb, sa, ea
    if not _bounded_event(ea) or not _bounded_event(eb):
        return
    a, b = _bounds(ea), _bounds(eb)
    if a is None or b is None:
        return
    scope_a, scope_b = _is_scope(sa, ea), _is_scope(sb, eb)
    if sa.plan_id == sb.plan_id and (scope_a or scope_b):
        return
    city_a, city_b = _city(ea.city), _city(eb.city)
    known_cross_city = city_a is not None and city_b is not None and city_a != city_b
    if max(a[0], b[0]) < min(a[1], b[1]):
        if (scope_a or scope_b) and not known_cross_city:
            return
        labels = _label(sa, ea, current) + "与" + _label(sb, eb, current)
        both_exact = ea.precision == eb.precision == "exact" and ea.commitment == eb.commitment == "fixed"
        if both_exact:
            actual_overlap = max(ea.start_at, eb.start_at) < min(ea.end_at, eb.end_at)
            return _issue("exact_overlap" if actual_overlap else "required_buffer", "definite",
                          labels + ("的确定时段重叠。" if actual_overlap else "占用了必须预留的交通或准备时间。"), sa, ea, sb, eb)
        return _issue("window_overlap", "potential", labels + "的日期或估计时间窗重叠，请核对实际安排。", sa, ea, sb, eb)

    if scope_a or scope_b or ea.precision != "exact" or eb.precision != "exact":
        return
    if ea.commitment != "fixed" or eb.commitment != "fixed":
        return
    first, second = (ea, eb) if a[1] <= b[0] else (eb, ea)
    first_plan, second_plan = (sa, sb) if first is ea else (sb, sa)
    first_end = _bounds(first)[1]
    second_start = _bounds(second)[0]
    seconds = (second_start - first_end).total_seconds()
    if seconds > 18 * 3600:
        return
    first_city = _city(first.arrival_city if first.kind in _FIXED_TRANSIT else first.city)
    next_city = _city(second.city)
    left, right = _loc(first.arrival_place if first.kind in _FIXED_TRANSIT else first.place), _loc(second.place)
    if first_city and first_city == next_city and left and left == right:
        return
    labels = _label(first_plan, first, current) + "至" + _label(second_plan, second, current)
    path = next((item for item in evidence if left and right and _loc(item.from_place) == left
                 and _loc(item.to_place) == right and item.valid_until > now), None)
    if path:
        if path.minutes * 60 > seconds:
            severity = "definite" if path.quality == "verified_minimum" else "potential"
            return _issue("travel_buffer", severity, labels + "的剩余时间短于已有路线所需时间。", sa, ea, sb, eb)
        return
    if first_city and next_city and first_city != next_city:
        immediate = first.end_at == second.start_at
        return _issue("intercity_gap", "definite" if immediate else "unknown",
                      labels + ("没有可用于实际跨城转移的时间。" if immediate else "缺少可信的跨城交通时长，无法验证能否衔接。"),
                      sa, ea, sb, eb)
    if seconds < 2 * 3600 and (not first_city or not next_city or not left or not right or left != right):
        return _issue("local_transfer_unknown", "unknown", labels + "的地点或通勤时长未核验。", sa, ea, sb, eb)


def evaluate(candidate, others, *, snapshot: PlanSnapshot, now: datetime, calendar_revision: int, evidence=()):
    issues: dict = {}

    def append(item):
        if item:
            issues.setdefault(item["id"], item)

    blocks = candidate.blocks
    selected = next((entry for entry in snapshot.options if entry.option_id == snapshot.selected_option_id), None)
    if selected and selected.commute:
        route = selected.commute
        evidence = (*evidence, TravelEvidence(route.from_place, route.to_place, route.minutes,
                                             "route_estimate", route.queried_at + timedelta(days=1)))
    if not any(_bounds(item) for item in blocks):
        append(_issue("missing_date", "unknown", "没有确定的日期或可定位的活动时段，只能保存草稿。", candidate, blocking=True))
    for item in blocks:
        if item.commitment == "fixed" and item.kind not in _CHECKPOINTS and _bounds(item) is None:
            append(_issue("missing_fixed_time", "unknown",
                          f"「{item.title}」是必须参加或执行的活动，请补充日期或时间窗。", candidate, item, blocking=True))
        start_day = item.start_at.astimezone(_TZ).date() if item.start_at else item.local_date
        finish_day = item.end_at.astimezone(_TZ).date() if item.end_at else item.end_date or start_day
        if start_day and snapshot.start_date and (start_day < snapshot.start_date or
                                                  (snapshot.end_date and finish_day > snapshot.end_date)):
            append(_issue("activity_outside_trip", "potential", f"「{item.title}」超出当前行程日期，请核对是否需要改期。",
                          candidate, item))
    if snapshot.options and not snapshot.selected_option_id:
        append(_issue("unselected_transport", "potential", "尚未选择交通或住宿备选。安排只包含时间轴上的已知活动。", candidate))
    if snapshot.trip_request and snapshot.trip_request.unresolved:
        append(_issue("missing_requirements", "unknown", "规划中仍有未确认的要求，请核对后再决定是否安排。", candidate))
    legacy_suggestions = snapshot.source_kind == "legacy" and any(
        item.precision in {"date_only", "unknown"} and item.commitment == "soft"
        and not _is_scope(candidate, item) for item in blocks
    )
    if legacy_suggestions:
        append(_issue("legacy_time_unverified", "unknown",
                      "部分建议活动只有日期或未核验的时段。同一天不代表时间重叠；需要安排时请先核对起止时间。",
                      candidate))

    def mark_pair(first_plan, first, next_plan, second):
        append(_compare(candidate, evidence, now, first_plan, first, next_plan, second))

    relevant = _range(blocks)
    in_between = _between(blocks)
    for index, item in enumerate(blocks):
        for other in blocks[index + 1:]:
            # A legacy suggestion's date is a display anchor, not a reservation
            # of the whole day. Keep comparisons against scheduled plans below.
            if legacy_suggestions and any(event.precision in {"date_only", "unknown"} and event.commitment == "soft"
                                          for event in (item, other)):
                continue
            # Non-adjacent sessions may have an explicit transit leg in between.
            if in_between(item, other):
                continue
            mark_pair(candidate, item, candidate, other)
    for scheduled in others:
        historic = _range(scheduled.blocks)
        extension = timedelta(hours=18)
        if not relevant or not historic or relevant[0] - extension > historic[1] or historic[0] - extension > relevant[1]:
            continue
        between_calendar = _between((*blocks, *scheduled.blocks))
        for item in blocks:
            for other in scheduled.blocks:
                if between_calendar(item, other):
                    continue
                mark_pair(candidate, item, scheduled, other)
    priority = {"definite": 0, "potential": 1, "unknown": 2}
    rows = sorted(issues.values(), key=lambda row: (not row["blocks_schedule"], priority[row["severity"]], row["id"]))
    if len(rows) > 119:
        rows = rows[:118] + [_issue("too_many_conflicts", "unknown", "冲突项目过多。请先缩小行程或处理已列出的冲突，再重新检查。",
                                    candidate, blocking=True)]
    return {"rule_version": RULE_VERSION, "calendar_revision": calendar_revision, "issues": rows,
            "can_commit": not any(row["blocks_schedule"] for row in rows)}


def _range(events):
    dates = [period for event in events if (period := _bounds(event)) is not None]
    return (min(x[0] for x in dates), max(x[1] for x in dates)) if dates else None


def _between(blocks):
    bounds = {id(item): _bounds(item) for item in blocks}
    fixed = sorted((event for event in blocks if event.precision == "exact" and event.commitment == "fixed"),
                   key=lambda event: event.start_at)
    starts = [event.start_at for event in fixed]

    def contains(left, right):
        a, b = bounds[id(left)], bounds[id(right)]
        if a is None or b is None or left.precision != "exact" or right.precision != "exact" or max(a[0], b[0]) < min(a[1], b[1]):
            return False
        if a[1] > b[0]:
            a, b = b, a
        # A known transit leg or fixed event between two meetings makes that
        # pair non-adjacent; evaluate the closer transfers separately.
        if (b[0] - a[1]).total_seconds() > 18 * 3600:
            return False
        for index in range(bisect_left(starts, a[1]), bisect_left(starts, b[0])):
            item = fixed[index]
            if item is not left and item is not right and item.end_at <= b[0]:
                return True
        return False
    return contains


def quote_expiry(snapshot: PlanSnapshot, now):
    option = next((row for row in snapshot.options if row.option_id == snapshot.selected_option_id), None)
    if not option:
        return None, False
    expiries = [q.valid_until for q in option.quotes]
    return min((date for date in expiries if date > now), default=None), any(date <= now for date in expiries)
