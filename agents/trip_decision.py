"""Deterministic combination and validation of evidence returned by trip tools."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from itertools import product

from utils.hotel_budget import reference_price_range
from utils.trip_request import TripRequest
from utils.weather_range import SHANGHAI_TZ

RAIL_BUFFER_MINUTES = 60  # Conservative planning allowance, not a verified transfer ETA.
MAX_TOOL_CANDIDATES = 5

_ISSUES = {
    "outbound_missing": "去程没有可核验的铁路班次。",
    "inbound_missing": "返程没有可核验的铁路班次。",
    "hotel_missing": "没有取得可核验的住宿候选。",
    "commute_missing": "未取得可核验的住宿至会议地点的通勤估算。",
    "commute_limit_exceeded": "地图步行估算超过明确的通勤上限。",
    "weather_missing": "部分或全部日期暂无可靠天气预报。",
    "weather_pending": "天气仍在查询，最终结果将补充预报状态。",
    "meeting_arrival_conflict": "去程到达时间与会议冲突，或无法留出建议的换乘余量。",
    "meeting_return_conflict": "返程发车早于会议结束后的建议换乘窗口。",
    "existing_schedule_overlap": "本方案与个人中心中已有的确定安排重叠；需另选时段或明确调整旧安排。",
    "travel_window_conflict": "班次不满足明确的出发或返程时段，或往返时间重叠。",
    "transport_conflict": "班次不满足指定交通方式。",
    "seats_unverified": "未确认该班次有足够的可用席位。",
    "rooms_unverified": "未确认指定入住日期、房间数量与房态。",
    "nightly_limit_exceeded": "住宿报价高于明确的单晚限额。",
    "nightly_limit_unverified": "未取得同币种的真实房价，无法核验单晚限额。",
    "reference_over_budget": "地图参考价已超出预算可用空间；不是实时房价，不列作合规推荐。",
    "total_budget_exceeded": "已知同币种费用已超过总预算。",
    "quote_missing": "缺少真实票价、房价或明确的其他必要费用；不能判断总价是否合规。",
    "flight_unavailable": "本项目未接入核验航班及票价接口，无法满足必须乘飞机的要求。",
}
_HARD = {
    "meeting_arrival_conflict", "meeting_return_conflict", "travel_window_conflict", "transport_conflict",
    "nightly_limit_exceeded", "reference_over_budget", "total_budget_exceeded", "commute_limit_exceeded",
}
_SEAT_CLASSES = ("second_class", "first_class", "business", "hard_seat", "soft_sleeper", "hard_sleeper")


def _decimal(value) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and 0 <= result <= 100_000_000 else None
    except (ValueError, InvalidOperation):
        return None


def _timepoint(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _quote(value, now, *, unit: str, start: date, end: date | None = None) -> dict | None:
    """Only admit explicit, fresh, tax-inclusive quotes from an actual tool result."""
    if not isinstance(value, dict) or value.get("quality") != "verified_quote" or value.get("tax_included") is not True:
        return None
    issued, expires = _timepoint(value.get("queried_at")), _timepoint(value.get("valid_until"))
    if not issued or not expires or not issued <= now < expires or now - issued > timedelta(minutes=30):
        return None
    amount = _decimal(value.get("amount"))
    currency, source = value.get("currency"), value.get("source_url")
    if amount is None or currency not in {"CNY", "USD", "EUR", "HKD", "JPY"} or not isinstance(source, str) or not source.startswith("https://"):
        return None
    if unit == "room_night" and (value.get("unit") != unit or value.get("check_in") != start.isoformat()
                                or not end or value.get("check_out") != end.isoformat()):
        return None
    if unit == "seat":
        if value.get("unit") != unit or value.get("travel_date") != start.isoformat() or value.get("seat_class") not in _SEAT_CLASSES:
            return None
    return {"amount": amount, "currency": currency, "quality": "verified_quote", "source_url": source,
            "queried_at": issued.isoformat(), "valid_until": expires.isoformat()}


def _clock(raw):
    return time.fromisoformat(raw) if isinstance(raw, str) and re.fullmatch(r"\d{2}:\d{2}", raw) else None


def _rail_items(data: dict, day: date | None, now: datetime) -> list[dict]:
    if not day or data.get("query_success") is not True:
        return []
    body = data.get("results", {})
    if not isinstance(body, dict) or body.get("date") != day.isoformat():
        return []
    rows = body.get("trains")
    if not isinstance(rows, list):
        return []
    items = []
    for row in rows[:30]:
        if not isinstance(row, dict) or not (number := row.get("train_no")):
            continue
        try:
            depart_time, arrive_time = _clock(row.get("depart_time")), _clock(row.get("arrive_time"))
            if not depart_time or not arrive_time:
                continue
            depart = datetime.combine(day, depart_time, SHANGHAI_TZ)
            arrive = datetime.combine(day, arrive_time, SHANGHAI_TZ)
            minutes = row.get("duration")
            if isinstance(minutes, str) and re.fullmatch(r"\d{1,3}:\d{2}", minutes):
                hours, mins = map(int, minutes.split(":"))
                by_duration = depart + timedelta(hours=hours, minutes=mins)
                if by_duration.time() != arrive_time:
                    continue
                arrive = by_duration
            elif arrive < depart:
                arrive += timedelta(days=1)
            if arrive <= depart or arrive - depart > timedelta(days=7) or depart < now:
                continue
        except (ValueError, OverflowError):
            continue
        # Treat “有” as one seat, not a guarantee of enough seats for a whole party.
        seats_by_class = {}
        for seat_class in _SEAT_CLASSES:
            count = row.get(seat_class)
            seats_by_class[seat_class] = (int(count) if isinstance(count, (str, int)) and str(count).isascii()
                                         and str(count).isdigit() and len(str(count)) <= 4 else 1 if count == "有" else 0)
        raw_quote = row.get("price_quote")
        quote = _quote(raw_quote, now, unit="seat", start=day)
        seats = seats_by_class[raw_quote["seat_class"]] if quote else max(seats_by_class.values())
        items.append({
            "train_no": str(number)[:16], "from_station": row.get("from_station"), "to_station": row.get("to_station"),
            "departs": depart, "arrives": arrive, "seats_observed": seats,
            "source_url": "https://www.12306.cn/", "queried_at": body.get("queried_at"),
            "quote": {**quote, "seat_class": raw_quote["seat_class"]} if quote else None,
        })
    return items


def _hotel_items(data: dict, req: TripRequest, now: datetime) -> list[dict]:
    if data.get("query_success") is not True or req.nights == 0:
        return []
    body = _results(data)
    rows = body.get("hotels")
    if not isinstance(rows, list):
        return []
    items = []
    for row in rows[:MAX_TOOL_CANDIDATES]:
        if not isinstance(row, dict) or not row.get("id") or not row.get("name"):
            continue
        raw_quote = row.get("price_quote")
        quote = _quote(raw_quote, now, unit="room_night", start=req.depart_date, end=req.effective_return)
        reference = reference_price_range(row.get("cost"))
        items.append({"id": str(row["id"])[:100], "name": str(row["name"])[:120], "address": row.get("address"),
                      "reference_cny": [str(v) for v in reference] if reference else None,
                      "rooms_available": raw_quote.get("rooms_available") if quote else None, "quote": quote,
                      "source_url": "https://www.amap.com/", "queried_at": body.get("queried_at")})
    return items


def _matches_period(moment: time, period: str | None):
    return not period or (
        period == "morning" and moment.hour < 12 or period == "afternoon" and 12 <= moment.hour < 17
        or period == "evening" and moment.hour >= 17
    )


def _rail_issues(req: TripRequest, leg: dict, returning: bool) -> set[str]:
    issues = set()
    earliest = req.earliest_return if returning else req.earliest_departure
    latest = req.latest_return if returning else req.latest_departure
    period = req.return_period if returning else req.depart_period
    if not _matches_period(leg["departs"].time(), period) or earliest and leg["departs"].time() < earliest or latest and leg["departs"].time() > latest:
        issues.add("travel_window_conflict")
    if req.transport_required == "high_speed" and not leg["train_no"].startswith(("G", "D", "C")):
        issues.add("transport_conflict")
    if leg["seats_observed"] < (req.passengers or 1):
        issues.add("seats_unverified")
    if req.meeting_date and req.meeting_start and req.meeting_end:
        margin = timedelta(minutes=RAIL_BUFFER_MINUTES)
        if returning:
            if leg["departs"] < datetime.combine(req.meeting_date, req.meeting_end, SHANGHAI_TZ) + margin:
                issues.add("meeting_return_conflict")
        elif leg["arrives"] + margin > datetime.combine(req.meeting_date, req.meeting_start, SHANGHAI_TZ):
            issues.add("meeting_arrival_conflict")
    return issues


def _candidate(req, outbound, inbound, hotel, commute, ranking_hints=None):
    issues = set()
    for label, leg in (("outbound", outbound), ("inbound", inbound)):
        if leg:
            issues |= _rail_issues(req, leg, returning=label == "inbound")
        elif label == "outbound" or not req.one_way:
            issues.add(f"{label}_missing")
    if outbound and inbound and inbound["departs"] <= outbound["arrives"]:
        issues.add("travel_window_conflict")
    rooms = req.rooms or (1 if req.passengers == 1 else None)
    if req.nights and not hotel:
        issues.add("hotel_missing")
    if hotel:
        available = hotel["rooms_available"]
        if not rooms or type(available) is not int or available < rooms:
            issues.add("rooms_unverified")
    if hotel and req.meeting_place and not commute:
        issues.add("commute_missing")
    if hotel and commute and req.max_commute_min and commute["duration_min"] > req.max_commute_min:
        issues.add("commute_limit_exceeded")
    if req.nightly_limit and req.nights:
        quote = hotel.get("quote") if hotel else None
        if not quote or quote["currency"] != req.nightly_limit.currency:
            issues.add("nightly_limit_unverified")
            if hotel and hotel["reference_cny"] and req.nightly_limit.currency == "CNY":
                if Decimal(hotel["reference_cny"][0]) > req.nightly_limit.amount:
                    issues.add("reference_over_budget")
        elif quote["amount"] > req.nightly_limit.amount:
            issues.add("nightly_limit_exceeded")
    items = []
    subtotals: dict[str, Decimal] = {}

    def add(name, quote=None, units=None):
        if quote is None or units is None:
            items.append({"kind": name, "amount": None, "quality": "unknown"})
            return
        amount = quote["amount"] * units
        currency = quote["currency"]
        subtotals[currency] = subtotals.get(currency, Decimal(0)) + amount
        items.append({**quote, "kind": name, "amount": str(amount), "unit_amount": str(quote["amount"]), "units": units})

    add("outbound", outbound["quote"] if outbound else None, req.passengers)
    if not req.one_way:
        add("inbound", inbound["quote"] if inbound else None, req.passengers)
    if req.nights:
        add("hotel", hotel["quote"] if hotel else None, req.nights * rooms if rooms else None)
    add("other", {"amount": req.other_cost.amount, "currency": req.other_cost.currency, "quality": "user_budget"} if req.other_cost else None, 1)
    complete_cost = all(item["amount"] is not None for item in items)
    if not complete_cost:
        issues.add("quote_missing")
    requested_currency = req.budget.currency if req.budget else None
    in_budget_currency = subtotals.get(requested_currency, Decimal(0))
    cost_verified_for_budget = complete_cost and all(item.get("currency") == requested_currency for item in items)
    budget_status = "not_set"
    if req.budget:
        if in_budget_currency > req.budget.amount:
            issues.add("total_budget_exceeded")
            budget_status = "exceeds"
        else:
            budget_status = "within" if cost_verified_for_budget else "unverified"
            if not cost_verified_for_budget:
                issues.add("quote_missing")
                if hotel and not hotel["quote"] and hotel["reference_cny"] and requested_currency == "CNY":
                    reference_min = Decimal(hotel["reference_cny"][0]) * req.nights * (rooms or 1)
                    if in_budget_currency + reference_min > req.budget.amount:
                        issues.add("reference_over_budget")
    hints = ranking_hints or {}
    commitments = [(leg["departs"] - timedelta(minutes=RAIL_BUFFER_MINUTES), leg["arrives"])
                   for leg in (outbound, inbound) if leg]
    if req.meeting_date and req.meeting_start and req.meeting_end:
        commitments.append((datetime.combine(req.meeting_date, req.meeting_start, SHANGHAI_TZ),
                            datetime.combine(req.meeting_date, req.meeting_end, SHANGHAI_TZ)))
    if any(start and finish and max(start, added_start) < min(finish, added_finish)
           for start, finish in hints.get("busy_windows", []) for added_start, added_finish in commitments):
        issues.add("existing_schedule_overlap")
    hard = bool(issues & _HARD)
    total_minutes = sum(int((leg["arrives"] - leg["departs"]).total_seconds() / 60) for leg in (outbound, inbound) if leg)
    walk_minutes = int(commute["duration_min"]) if commute else 0
    unliked = 45 if req.avoid_early and outbound and outbound["departs"].hour < 9 else 0
    for leg, preferred in ((outbound, req.preferred_earliest_departure), (inbound, req.preferred_earliest_return)):
        if leg and preferred and leg["departs"].time() < preferred:
            unliked += 45
    if req.transport_preference == "high_speed" and outbound and not outbound["train_no"].startswith(("G", "D", "C")):
        unliked += 45
    score = total_minutes + walk_minutes * (4 if req.near_meeting else 1) + unliked
    score += int(in_budget_currency / 25) if requested_currency == "CNY" else 0
    reasons = [f"铁路车程 {total_minutes} 分钟"] if total_minutes else []
    explicit_departure = req.depart_period or req.earliest_departure or req.latest_departure or req.preferred_earliest_departure
    if outbound and not explicit_departure and hints.get("departure") and _matches_period(outbound["departs"].time(), hints["departure"]):
        score -= 30
        reasons.append("符合已授权的常用出发时段")
    if not req.transport_required and not req.transport_preference and hints.get("transport") == "high_speed" and outbound:
        if outbound["train_no"].startswith(("G", "D", "C")):
            score -= 25
            reasons.append("符合已授权的高铁偏好")
    if hotel and isinstance(hints.get("hotel_brand"), str) and hints["hotel_brand"].casefold() in hotel["name"].casefold():
        score -= 25
        reasons.append("符合已授权的住宿偏好")
    soft_limit = hints.get("nightly_budget")
    if hotel and isinstance(soft_limit, dict) and not req.nightly_limit:
        room = hotel.get("quote")
        if room and room["currency"] == soft_limit.get("currency") and (limit := _decimal(soft_limit.get("amount"))) is not None:
            if room["amount"] <= limit:
                score -= 20
                reasons.append("核验报价符合已授权的每晚预算偏好")
    if commute:
        reasons.append(f"酒店至会场步行约 {walk_minutes} 分钟（地图估算）")
    if budget_status == "within":
        reasons.append("已知报价和用户给定的其他费用额度合计未超过总预算")
    if req.avoid_early and outbound and outbound["departs"].hour >= 9:
        reasons.append("去程不早于 09:00，符合出发偏好")
    return {"outbound": _public_leg(outbound), "inbound": _public_leg(inbound), "hotel": _public_hotel(hotel),
            "commute": commute, "cost_items": items, "known_subtotals": {k: str(v) for k, v in subtotals.items()},
            "budget_status": budget_status, "status": "excluded" if hard else "provisional" if issues else "validated",
            "issue_codes": sorted(issues), "issues": [_ISSUES[key] for key in sorted(issues)], "score": score, "reasons": reasons}


def _public_leg(leg):
    return {**leg, "departs": leg["departs"].isoformat(), "arrives": leg["arrives"].isoformat(),
            "quote": _public_quote(leg["quote"])} if leg else None


def _public_hotel(hotel):
    return {**hotel, "quote": _public_quote(hotel["quote"])} if hotel else None


def _public_quote(quote):
    return {**quote, "amount": str(quote["amount"])} if quote else None


def selection_is_current(option: dict) -> bool:
    from agents.trip_workflow import shanghai_now

    now = shanghai_now()
    outbound = _timepoint((option.get("outbound") or {}).get("departs"))
    if option.get("status") != "validated" or not outbound or outbound <= now:
        return False
    for cost in option.get("cost_items", []):
        if cost.get("quality") == "verified_quote":
            expires = _timepoint(cost.get("valid_until"))
            if not expires or expires <= now:
                return False
    return True


def _results(data: dict) -> dict:
    body = data.get("results")
    return body if isinstance(body, dict) else {}


def evaluate_trip(req: TripRequest, tool_data: dict[str, dict], now: datetime, *, ranking_hints=None) -> dict:
    outbound = _rail_items(tool_data.get("outbound", {}), req.depart_date, now)
    inbound = _rail_items(tool_data.get("inbound", {}), req.effective_return, now)
    hotels = _hotel_items(tool_data.get("hotels", {}), req, now)
    weather = _results(tool_data.get("weather", {})).get("forecast", [])
    weather_days = {row.get("date_iso") for row in weather if isinstance(row, dict)} if isinstance(weather, list) else set()
    end = req.effective_return or req.depart_date
    dates = {(req.depart_date + timedelta(days=i)).isoformat() for i in range((end - req.depart_date).days + 1)}
    commute = tool_data.get("commute", {}).get("routes", {})
    hints = dict(ranking_hints or {})
    hints["busy_windows"] = [tuple(map(_timepoint, item)) for item in hints.get("busy_windows", [])
                             if isinstance(item, list) and len(item) == 2] if isinstance(hints.get("busy_windows"), list) else []

    def shortlist(items, returning):
        return sorted(items, key=lambda item: (bool(_rail_issues(req, item, returning) & _HARD),
                                               item["seats_observed"] < (req.passengers or 1),
                                               item["departs"]))[:MAX_TOOL_CANDIDATES]

    ranking, excluded = [], []
    codes = set()
    for out, back, hotel in product(shortlist(outbound, False) or [None], shortlist(inbound, True) or [None], hotels or [None]):
        walk = commute.get(hotel["id"]) if hotel else None
        item = _candidate(req, out, back, hotel, walk, hints)
        if not any((out, back, hotel)):
            codes.update(item["issue_codes"])
            continue
        (excluded if item["status"] == "excluded" else ranking).append(item)
    ranking.sort(key=lambda item: (item["status"] != "validated", len(item["issue_codes"]), item["score"]))
    excluded.sort(key=lambda item: (len(item["issue_codes"]), item["score"]))
    alternatives = ranking[:3]
    for item in alternatives:
        identity = [
            [(item.get(direction) or {}).get(field) for field in ("train_no", "departs", "arrives")] for direction in ("outbound", "inbound")
        ]
        identity.extend([(item.get("hotel") or {}).get("id"), item["known_subtotals"]])
        signature = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
        item["id"] = f"{req.trip_id}-{req.revision}-{signature}"
    recommended = next((item for item in alternatives if item["status"] == "validated"), None)
    codes.update(item for result in ([recommended] if recommended else alternatives or excluded[:3]) for item in result["issue_codes"])
    if "weather" not in tool_data:
        codes.add("weather_pending")
    elif not dates <= weather_days:
        codes.add("weather_missing")
    if req.transport_required == "flight":
        codes.add("flight_unavailable")
    partial = bool(codes or not recommended)
    return {"request": req.public(), "status": "partial" if partial else "success",
            "recommended": recommended, "alternatives": alternatives,
            "excluded_count": len(excluded), "excluded_reasons": sorted({code for item in excluded for code in item["issue_codes"] if code in _HARD}),
            "issues": [{"code": code, "message": _ISSUES[code]} for code in sorted(codes)],
            "validation": {"station_buffer_minutes": RAIL_BUFFER_MINUTES,
                           "note": "铁路站点接驳预留并非实测门到门时间；报价和席位须在购买前重查，未执行预订。"}}
