"""Session-local, user-grounded inputs to the business-trip workflow."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from utils.train_intent import _CITY
from utils.weather_range import _number, resolve_weather_range, shanghai_now

_PAIR = re.compile(rf"(?P<origin>{_CITY})市?\s*(?:出发)?\s*(?:去|到|至|前往|飞往)\s*(?P<destination>{_CITY})市?")
_DATE = re.compile(
    r"(?<![\d:])(?:\d{4}[-/年])?\d{1,2}[-/月]\d{1,2}(?:日|号)?(?![\d:])|"
    r"(?<!\d)\d{1,2}(?:日|号)|大后天|后天|明天|明早|明晚|今天|今早|今晚|"
    r"(?:下下|下|本|这)?(?:周|星期)[一二三四五六日天末]?"
)
_AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?"
_CURRENCY = r"人民币|元|块|CNY|RMB|美元|USD|欧元|EUR|港币|HKD|日元|JPY"
_NUM = r"[\d零〇一二两三四五六七八九十百]+"
_BUSINESS = re.compile(r"差旅|出差|商旅|商务行程|商务旅行|拜访客户")
_PLAN = re.compile(r"规划|安排|设计.{0,6}行程|完整.{0,5}(?:方案|行程)")
_INDEPENDENT = re.compile(r"汇率|兑换|翻译|记(?:一|几|两)笔|记账|账本|报销政策|签证|历史记录|我去过")
_LOOKUP = re.compile(r"(?:查|搜|看看|查询).{0,32}(?:天气|高铁|火车|余票|机票|航班|酒店|餐厅|景点)|(?:余票|车票|车次|天气)(?:信息|如何|怎么样|多少钱|吗|么)?[?？。]?$")
_RETURN = re.compile(r"返程|返回|回程|回来|回去|回到")
_MEETING = re.compile(r"会议|开会|会面|会谈")
_CLOCK = r"\d{1,2}:\d{2}(?!\d)|\d{1,2}(?:点|时)(?:半|\d{1,2}分?)?"
_FIELD_EDIT = re.compile(
    r"^(?:(?:请|帮我|把|再把|现在|这次|请把)\s*)?(?:总预算|差旅预算|预算|人数|出发|去程|返程|返回|"
    r"出发地|目的地|会议|酒店|住宿|天数|交通|其他必要费用)|"
    r"(?:取消|不再|去掉|不用|不需要|不必|不要|改成|改为|改到|调整为|更换|添加|加上|只坐|改坐|优先坐|忽略未支持)"
)
_REPLAN = re.compile(r"^(?:按(?:这个|原|现有|刚才的)(?:方案|要求|条件))?(?:请)?(?:再规划一次|重新规划|给出方案|继续规划)$")
_CANCEL = re.compile(r"取消(?:本次|这次|这个|当前)(?:完整)?(?:差旅|行程|出差)(?:规划|任务)?[。！!]?$")
_CHOOSE = re.compile(r"(?:选择|采用|确认|选)\s*(?:第)?\s*([123一二三])\s*(?:个)?(?:号)?方案[。！!]?$|(?:选择|采用|确认|选)\s*方案\s*([123一二三])[。！!]?$")
_CITY_FIELDS = {"origin": "出发城市", "destination": "目的城市"}


class TripBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    amount: Decimal = Field(ge=0, le=100_000_000, decimal_places=2)
    currency: Literal["CNY", "USD", "EUR", "HKD", "JPY"] | None = None


class TripRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    trip_id: str = Field(min_length=6, max_length=48)
    revision: int = Field(default=1, ge=1)
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    origin: str | None = Field(default=None, min_length=2, max_length=24)
    destination: str | None = Field(default=None, min_length=2, max_length=24)
    depart_date: date | None = None
    return_date: date | None = None
    duration_days: int | None = Field(default=None, ge=1, le=30)
    passengers: int | None = Field(default=None, ge=1, le=50)
    rooms: int | None = Field(default=None, ge=1, le=50)
    one_way: bool = False
    lodging: bool = True
    budget: TripBudget | None = None
    nightly_limit: TripBudget | None = None
    other_cost: TripBudget | None = None
    depart_period: Literal["morning", "afternoon", "evening"] | None = None
    return_period: Literal["morning", "afternoon", "evening"] | None = None
    earliest_departure: time | None = None
    earliest_return: time | None = None
    latest_departure: time | None = None
    latest_return: time | None = None
    preferred_earliest_departure: time | None = None
    preferred_earliest_return: time | None = None
    transport_required: Literal["rail", "high_speed", "flight"] | None = None
    transport_preference: Literal["rail", "high_speed", "flight"] | None = None
    meeting_requested: bool = False
    meeting_place: str | None = Field(default=None, min_length=2, max_length=100)
    meeting_date: date | None = None
    meeting_start: time | None = None
    meeting_end: time | None = None
    near_meeting: bool = False
    near_meeting_required: bool = False
    max_commute_min: int | None = Field(default=None, ge=1, le=180)
    avoid_early: bool = False
    unresolved: dict[str, str] = Field(default_factory=dict, max_length=24)

    @property
    def effective_return(self) -> date | None:
        if self.one_way:
            return None
        if self.return_date is not None:
            return self.return_date
        if self.depart_date and self.duration_days:
            return self.depart_date + timedelta(days=self.duration_days - 1)
        return None

    @property
    def nights(self) -> int:
        if not self.lodging or not self.depart_date or not self.effective_return:
            return 0
        return max(0, (self.effective_return - self.depart_date).days)

    def public(self) -> dict:
        rendered = self.model_dump(mode="json", exclude={"unresolved"})
        rendered["resolved_return_date"] = self.effective_return.isoformat() if self.effective_return else None
        rendered["return_date_source"] = "explicit" if self.return_date else "duration" if self.effective_return else None
        rendered["hotel_nights"] = self.nights
        return rendered


@dataclass(frozen=True)
class TripTurn:
    request: TripRequest
    missing: tuple[tuple[str, str], ...]

    @property
    def question(self) -> str:
        return "请确认：" + "；".join(label for _, label in self.missing[:3]) + "？"


def _date(token: str, today: date, anchor: date | None = None) -> date | None:
    token = {"明早": "明天", "明晚": "明天", "今早": "今天", "今晚": "今天"}.get(token, token)
    if anchor and re.fullmatch(r"(?:周|星期)[一二三四五六日天]", token):
        offset = "一二三四五六日".index(token[-1].replace("天", "日"))
        result = anchor - timedelta(days=anchor.weekday()) + timedelta(days=offset)
        return result if result >= anchor else result + timedelta(days=7)
    result = resolve_weather_range(token, now=today)
    return result.start if result.explicit and not result.error and result.start == result.end else None


def _clock(raw: str, period: str | None = None) -> time:
    hours, _, minutes = re.sub(r"[点时]", ":", raw).rstrip("分").partition(":")
    hour = int(hours)
    if period in {"afternoon", "evening"} and hour < 12:
        hour += 12
    return time(hour, 30 if minutes == "半" else int(minutes or 0))


def _period(text: str) -> str | None:
    if re.search(r"下午|午后", text):
        return "afternoon"
    if re.search(r"晚上|晚间|傍晚|今晚|明晚", text):
        return "evening"
    if re.search(r"早上|上午|清晨|明早|今早", text):
        return "morning"
    return None


def _currency(raw: str | None):
    if raw is None:
        return None
    return {"元": "CNY", "块": "CNY", "人民币": "CNY", "RMB": "CNY", "美元": "USD", "欧元": "EUR",
            "港币": "HKD", "日元": "JPY"}.get(raw.upper(), raw.upper())


def _budget(clause: str, previous: TripBudget | None) -> TripBudget | None:
    marker = re.search(r"预算|总费用|总价上限|其他(?:必要|必需)?费用|房价|每晚|单晚", clause)
    amount_text = clause[marker.end():].strip() if marker else ""
    prefix = r"(?:(?:[:：=]|控制在|不超过|不高于|最高|上限|改为|改成|设为|是|为)\s*)*"
    match = re.match(rf"{prefix}({_AMOUNT})(?![\d.])\s*({_CURRENCY})?", amount_text, flags=re.I)
    if (not match or re.search(r"约|大概|左右|[~～－−$€£]|\d\s*[-至到]\s*\d|\d\s*(?:万|千|百)", amount_text)
            or re.search(r"^\s*(?:[年月日号]|[+-]|或|也可|以上|起步)", amount_text[match.end():])):
        return None
    currency = _currency(match[2]) if match[2] else previous.currency if previous else None
    return TripBudget(amount=Decimal(match[1].replace(",", "")), currency=currency)


def _missing(req: TripRequest, today: date) -> list[tuple[str, str]]:
    missing = [*req.unresolved.items(), *((key, label) for key, label in _CITY_FIELDS.items() if not getattr(req, key))]
    if req.origin and req.origin == req.destination:
        missing.append(("destination", "起终点相同，请确认目的城市"))
    if not req.depart_date or req.depart_date < today:
        missing.append(("depart_date", "出发日期（不能早于今天）"))
    end = req.effective_return
    if not req.one_way and (not end or (req.depart_date and end < req.depart_date)):
        missing.append(("return_date", "返程日期或出差天数"))
    if req.depart_date and end and (end - req.depart_date).days >= 30:
        missing.append(("return_date", "本次支持 30 天内行程，请确认返程日期"))
    if req.depart_date and req.return_date and req.duration_days and (req.return_date - req.depart_date).days + 1 != req.duration_days:
        missing.append(("duration_days", "出差天数和返程日期不一致，请明确修改其中一项"))
    if req.passengers is None:
        missing.append(("passengers", "出行人数"))
    if req.rooms and req.passengers and req.rooms > req.passengers:
        missing.append(("rooms", "房间数多于人数，请确认"))
    if req.meeting_requested:
        if not req.meeting_place:
            missing.append(("meeting_place", "会议地点的完整名称或地址"))
        if not (req.meeting_date and req.meeting_start and req.meeting_end):
            missing.append(("meeting_time", "会议日期和起止时间"))
        elif (req.meeting_end <= req.meeting_start or
              (req.depart_date and req.meeting_date < req.depart_date) or (end and req.meeting_date > end)):
            missing.append(("meeting_time", "会议日期必须在行程内，结束时间应晚于开始时间"))
    if req.near_meeting_required and req.max_commute_min is None:
        missing.append(("max_commute_min", "酒店到会场的最长可接受步行时间"))
    for low, high in ((req.earliest_departure, req.latest_departure), (req.earliest_return, req.latest_return)):
        if low and high and low > high:
            missing.append(("travel_time", "最早出发时间晚于最晚出发时间，请明确时段"))
    for key, label in (("budget", "总预算"), ("nightly_limit", "单晚预算"), ("other_cost", "其他必要费用")):
        if item := getattr(req, key):
            if not item.currency:
                missing.append((key, f"{label}币种"))
    fields = dict(req.unresolved)
    for name, label in missing:
        fields.setdefault(name, label)
    return list(fields.items())


def trip_requirements(req: TripRequest, today: date) -> tuple[tuple[str, str], ...]:
    return tuple(_missing(req, today))


def is_trip_cancellation(text: str) -> bool:
    return bool(_CANCEL.fullmatch(text.strip()))


def selected_option(text: str) -> int | None:
    found = _CHOOSE.fullmatch(text.strip())
    return _number(found[1] or found[2]) if found else None


def resolve_trip_turn(text: str, previous: TripRequest | None = None, *, now: datetime | None = None) -> TripTurn | None:
    """Recognize complete business-trip requests and explicit edits, not loose topic switches."""
    today = (now or shanghai_now()).date()
    text = unicodedata.normalize("NFKC", text).strip()
    clean = text.rstrip("。！!?？ ")
    if not text or _INDEPENDENT.search(text):
        return None  # preserve the existing mixed/specialized route
    pair = _PAIR.search(text)
    business = bool(_BUSINESS.search(text))
    new_trip = bool(business and (_PLAN.search(text) or pair or _DATE.search(text) or re.search(r"(?:我|要|想|去|次)出差", text)))
    if (_LOOKUP.search(text) or re.search(r"怎么样|有哪些|多少钱|如何|查一下|帮我查", clean)) and not _PLAN.search(text) and not _RETURN.search(text):
        return None
    replan = previous is not None and bool(_REPLAN.fullmatch(clean))
    pending = _missing(previous, today) if previous else []
    pending_fields = {field for field, _ in pending}
    bare_passengers = re.fullmatch(_NUM, clean) if pending_fields == {"passengers"} else None
    bare_city = re.fullmatch(_CITY, clean)
    answer_city = pending_fields & _CITY_FIELDS.keys()
    date_edit = bool(_DATE.search(clean) and (_RETURN.search(clean) or re.search(r"出发|开会|会议", clean)))
    people_edit = bool(re.match(rf"(?:一共|就)?{_NUM}(?:个)?(?:人|位)(?!民)", clean))
    commute_edit = "max_commute_min" in pending_fields and bool(re.fullmatch(r"\d{1,3}分钟", clean))
    currency_edit = bool(pending_fields & {"budget", "nightly_limit", "other_cost"} and re.fullmatch(_CURRENCY, clean, flags=re.I))
    pending_money = pending_fields & {"budget", "nightly_limit", "other_cost"}
    bare_amount = len(pending_money) == 1 and bool(re.fullmatch(rf"{_AMOUNT}\s*(?:{_CURRENCY})", clean, flags=re.I))
    edit = bool(previous and (_FIELD_EDIT.search(text) or replan or
                              date_edit or people_edit or bare_passengers or commute_edit or currency_edit or bare_amount or (len(answer_city) == 1 and bare_city) or
                              (pending_fields & {"depart_date", "return_date", "meeting_time"} and _DATE.fullmatch(clean)) or
                              ("passengers" in pending_fields and re.fullmatch(rf"(?:就|一共)?{_NUM}(?:个)?人", clean)) or
                              ("meeting_place" in pending_fields and re.fullmatch(r"[^，,。?？]{2,100}(?:中心|会议室|大厦|园区|酒店|会展馆)", clean))))
    if not (new_trip or edit):
        return None
    # Restating the same city pair without announcing a new trip keeps confirmed fields.
    if previous and new_trip:
        explicit_new = bool(re.search(r"另一次|另一趟|另一个|新的差旅|重新开始", text))
        changed_route = bool(pair and (pair["origin"], pair["destination"]) != (previous.origin, previous.destination))
        if explicit_new or changed_route and not re.search(r"改成|改为|改到|调整|更换", text):
            edit = False
        elif pair and not changed_route:
            edit = True
    base = previous if edit else TripRequest(trip_id=uuid4().hex[:16])
    if replan:
        return TripTurn(base, tuple(_missing(base, today)))
    patch: dict = {}
    invalid: list[tuple[str, str]] = []
    if bare_passengers:
        number = _number(bare_passengers[0])
        if 1 <= number <= 50:
            patch["passengers"] = number
        else:
            invalid.append(("passengers", "出行人数（1–50 人）"))

    if pair:
        patch.update(origin=pair["origin"], destination=pair["destination"])
    elif edit and len(answer_city) == 1 and bare_city:
        patch[next(iter(answer_city))] = bare_city[0]
    for field, label, prefix in (("origin", "出发城市", "出发地|起点"), ("destination", "目的城市", "目的地|终点")):
        if found := re.search(rf"(?:{prefix})\s*(?:是|为|改到|改成|改为|[:：])?\s*({_CITY})", text):
            patch[field] = found[1]
        elif field == "origin" and (found := re.search(rf"从({_CITY})市?出发", text)):
            patch[field] = found[1]
    for key, label, pattern, maxval in (
        ("duration_days", "出差天数（1–30 天）", rf"({_NUM})\s*(?:个)?天(?:的|出差|差旅|行程|$)|(?:出差|差旅|行程|天数改为)\s*({_NUM})\s*天", 30),
        ("passengers", "出行人数（1–50 人）", rf"({_NUM})\s*(?:个)?(?:人|位)(?!民)|人数\s*(?:为|是|改为|改成|:)\s*({_NUM})", 50),
        ("rooms", "房间数（1–50 间）", rf"({_NUM})\s*间(?:房|客房)|房间数\s*(?:为|是|改为|改成|:)\s*({_NUM})", 50),
    ):
        if found := re.search(pattern, clean):
            number = _number(found[1] or found[2])
            if 1 <= number <= maxval:
                patch[key] = number
            else:
                invalid.append((key, label))

    clauses = [part.strip() for part in re.split(r"[,，;；。！？\n]|(?<=元)\s*,", re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)) if part.strip()]
    # Outbound is resolved first so unqualified weekdays in the return and meeting
    # clauses refer to the explicitly chosen travel week, not the execution week.
    for clause in clauses:
        if _RETURN.search(clause) or _MEETING.search(clause):
            continue
        dates = _DATE.findall(clause)
        qualifies = bool(pair and _PAIR.search(clause) or re.search(r"出发|去程|出差|差旅", clause)
                         or "depart_date" in pending_fields and _DATE.fullmatch(clause))
        if qualifies and dates:
            if len(dates) == 1 and (value := _date(dates[0], today)) is not None:
                patch["depart_date"] = value
            else:
                invalid.append(("depart_date", "请明确一个出发日期"))
        if qualifies and (period := _period(clause)):
            patch["depart_period"] = period
    start = patch.get("depart_date", base.depart_date)
    for clause in clauses:
        dates = _DATE.findall(clause)
        if _RETURN.search(clause) or ("return_date" in pending_fields and "depart_date" not in pending_fields and _DATE.fullmatch(clause)):
            if dates:
                if len(dates) == 1 and (value := _date(dates[0], today, start)) is not None:
                    patch["return_date"] = value
                else:
                    invalid.append(("return_date", "请明确一个返程日期"))
            if period := _period(clause):
                patch["return_period"] = period
        if re.search(r"会议时间|会议(?:在|是|周|星期|明天|后天|下周|\d)|开会(?:时间|在)", clause) or "meeting_time" in pending_fields and re.search(_CLOCK, clause):
            patch["meeting_requested"] = True
            if len(dates) == 1 and (value := _date(dates[0], today, start)) is not None:
                patch["meeting_date"] = value
            elif dates:
                invalid.append(("meeting_time", "请明确一个会议日期"))
            if clocks := list(re.finditer(_CLOCK, clause)):
                try:
                    first_period = _period(clause[:clocks[0].start()])
                    patch["meeting_start"] = _clock(clocks[0][0], first_period)
                    if len(clocks) == 2:
                        second_period = _period(clause[clocks[0].end():clocks[1].start()]) or first_period
                        patch["meeting_end"] = _clock(clocks[1][0], second_period)
                    elif len(clocks) != 1:
                        invalid.append(("meeting_time", "请明确会议起止时间"))
                except ValueError:
                    invalid.append(("meeting_time", "会议时间无效，请提供有效的时分"))
        if location := re.match(r"(?:(?:把|请把)\s*)?(?:会议地点|开会地点|会面地点|会议地址)\s*(?:改为|改成|为|是|在|设在|:)\s*(.{2,100})", clause):
            value = location[1].strip()
            if len(value) >= 2 and not re.search(r"^(?:附近|靠近|酒店尽量|不确定|不知道|待定)", value):
                patch.update(meeting_place=value, meeting_requested=True)
        if threshold := re.search(rf"(?:不能|不得|不|最早)\s*(?:早于|早到|出发|不得早于)?\s*({_CLOCK})", clause):
            name = "earliest_return" if _RETURN.search(clause) else "earliest_departure"
            if re.search(r"最好|尽量|希望|偏好", clause):
                name = "preferred_" + name
            try:
                patch[name] = _clock(threshold[1], _period(clause))
            except ValueError:
                invalid.append((name, "最早出发时间无效，请提供有效的时分"))
        if threshold := re.search(rf"(?:不得晚于|不晚于|最晚|最迟)\s*({_CLOCK})|({_CLOCK})\s*(?:前出发|前发车|前返回)", clause):
            name = "latest_return" if _RETURN.search(clause) else "latest_departure"
            try:
                patch[name] = _clock(threshold[1] or threshold[2], _period(clause))
            except ValueError:
                invalid.append((name, "最晚发车时间无效，请提供有效的时分"))
        money_key = ("other_cost" if re.search(r"其他(?:必要|必需)?费用", clause)
                     else "nightly_limit" if re.search(r"每晚|单晚|酒店预算|住宿预算|房价", clause)
                     else "budget" if re.search(r"预算|总费用|总价上限", clause) else None)
        remove_money = re.search(r"(?:取消|去掉|不再限制|不限|不设)(?:.{0,10})(?:预算|房价|总费用|总价上限|其他(?:必要|必需)?费用)", clause)
        if money_key and remove_money:
            patch[money_key] = None
        elif money_key:
            try:
                value = _budget(clause, getattr(base, money_key))
            except ValidationError:
                value = None
            if value and (value.amount > 0 or money_key == "other_cost"):
                patch[money_key] = value
            elif value is None and re.search(r"[\d零一二两三四五六七八九十百千万]|预算改", clause):
                invalid.append((money_key, "金额无效或口径不清，请提供明确金额和币种"))
            elif value is not None:
                invalid.append((money_key, "总预算或单晚预算须大于零"))

    if "meeting_place" in pending_fields and "meeting_place" not in patch and re.fullmatch(r"[^，,。?？]{2,100}(?:中心|会议室|大厦|园区|酒店|会展馆)", clean):
        patch["meeting_place"] = clean
    if bare_amount:
        field = next(iter(pending_money))
        try:
            if (value := _budget("预算" + clean, getattr(base, field))) and (value.amount > 0 or field == "other_cost"):
                patch[field] = value
        except ValidationError:
            pass  # Keep the earlier clarification pending instead of reverting to a stale amount.
    for field in ("budget", "nightly_limit", "other_cost"):
        if field in pending_fields and getattr(base, field) and (cc := re.fullmatch(_CURRENCY, clean, flags=re.I)):
            patch[field] = TripBudget(amount=getattr(base, field).amount, currency=_currency(cc[0]))
    if re.search(r"(?:不订|不住|不用|不要|取消|不需要)(?:再)?(?:酒店|住宿)", text) and not re.search(r"靠近|附近", text):
        patch["lodging"] = False
    if re.search(r"(?:需要|加上|安排)(?:住宿|酒店)", text) and not re.search(r"不需要", text):
        patch["lodging"] = True
    if re.search(r"单程|无需返程|不安排返程", text):
        patch["one_way"] = True
    elif re.search(r"往返|需要返程|也查返程", text) or "return_date" in patch:
        patch["one_way"] = False
    if re.search(r"(?:靠近|离|附近).{0,5}会议|会议地点(?:附近|周边)", text):
        patch.update(near_meeting=True, meeting_requested=True)
    if re.search(r"(?:必须|务必|只能).{0,14}(?:靠近|附近|步行).{0,10}(?:会场|会议)|(?:必须|务必).{0,14}会议地点附近", text):
        patch.update(near_meeting=True, near_meeting_required=True, meeting_requested=True)
    if walk := re.search(r"(?:步行|走路|通勤).{0,10}?(\d{1,3})\s*分钟(?:以内|内|以下|封顶)", text) or (re.fullmatch(r"(\d{1,3})分钟", clean) if commute_edit else None):
        value = int(walk[1])
        if 1 <= value <= 180:
            patch.update(max_commute_min=value, near_meeting=True, near_meeting_required=True, meeting_requested=True)
        else:
            invalid.append(("max_commute_min", "步行上限须在 1–180 分钟之间"))
    if re.search(r"(?:取消|不再|不用|不必|去掉).{0,12}(?:靠近|会议地点附近)", text):
        patch.update(near_meeting=False, near_meeting_required=False, max_commute_min=None)
    if re.search(r"(?:不再有|取消了?|去掉)会议(?:$|[，,。；;])", text):
        patch.update(meeting_requested=False, meeting_place=None, meeting_date=None, meeting_start=None, meeting_end=None,
                     near_meeting=False, near_meeting_required=False, max_commute_min=None)
    if re.search(r"(?:不要|避免|不想|别)太早", text):
        patch["avoid_early"] = True
    if re.search(r"(?:取消|去掉).{0,12}(?:太早|早出发|早班)|早班也可以", text):
        patch["avoid_early"] = False
    if re.search(r"(?:取消|去掉).{0,8}最早出发", text):
        patch["earliest_departure"] = None
    mode_match = re.search(r"(必须|只坐|只能|仅限|优先|最好坐|希望坐|改坐)\s*(?:坐|乘坐|乘|搭乘)?\s*(高铁|动车|火车|铁路|飞机|航班)", text)
    if mode_match:
        mode = {"高铁": "high_speed", "动车": "high_speed", "火车": "rail", "铁路": "rail", "飞机": "flight", "航班": "flight"}[mode_match[2]]
        patch["transport_required" if mode_match[1] in {"必须", "只坐", "只能", "仅限", "改坐"} else "transport_preference"] = mode
    if re.search(r"(取消|去掉).{0,10}(?:交通方式|高铁|飞机).{0,6}(?:要求|限制)", text):
        patch.update(transport_required=None, transport_preference=None)
    if re.search(r"(?:改为|改成|调整为).{0,3}\d+天", text) and "duration_days" in patch and "return_date" not in patch:
        patch["return_date"] = None  # explicitly replacing the trip duration
    ignore_unsupported = bool(re.search(r"(?:忽略|去掉|取消)(?:未支持|未识别)的?(?:硬性)?(?:限制|要求|条件)", clean))
    # Unrecognized edits don't show a stale proposal as if the change had succeeded.
    if edit and not new_trip and not patch and not invalid and not ignore_unsupported:
        if re.search(r"预算|返程|会议|出发|人数|酒店|住宿|改为|改到|取消", text):
            invalid.append(("edit", "需要明确修改哪个条件及其新值"))
        else:
            return None
    resolved = set(patch)
    if {"meeting_start", "meeting_end", "meeting_date"} & resolved or patch.get("meeting_requested") is False:
        resolved.add("meeting_time")
    pending_invalid = {key: label for key, label in base.unresolved.items() if key not in resolved}
    if ignore_unsupported:
        pending_invalid.pop("unsupported_constraint", None)
    for clause in clauses:
        if (re.search(r"必须|务必|只能|仅限|不得|绝不能", clause)
                and not re.search(rf"预算|总价|费用|时间|最晚|最早|{_CLOCK}|(?:步行|通勤).{{0,6}}\d+分钟", clause)
                and not (re.search(r"高铁|动车|火车|铁路|飞机|航班", clause) and "transport_required" in patch)
                and not ("near_meeting_required" in patch and re.search(r"(?:靠近|附近|步行).{0,10}(?:会场|会议)|会议地点附近", clause))):
            invalid.append(("unsupported_constraint", "有暂不能核验的硬性要求，请改成可核验的条件，或确认忽略未支持的限制"))
    pending_invalid.update((key, label) for key, label in invalid if key != "edit")
    patch["unresolved"] = pending_invalid
    changed = {key: value for key, value in patch.items() if getattr(base, key) != value}
    req = TripRequest.model_validate({**base.model_dump(), **changed, "revision": base.revision + int(bool(changed) and bool(edit))})
    missing = dict([*_missing(req, today), *invalid])
    return TripTurn(req, tuple(missing.items()))
