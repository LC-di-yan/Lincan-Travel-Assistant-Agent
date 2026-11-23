"""行程快照、时间精度及个人中心写入协议。"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from utils.trip_request import TripRequest

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)]
City = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=32)]
OptionId = Annotated[str, StringConstraints(min_length=1, max_length=96, pattern=r"^[\w-]+$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
DomesticZone = Literal["Asia/Shanghai"]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Money(DTO):
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: Currency


class Event(DTO):
    event_id: UUID = Field(default_factory=uuid4)
    title: Label
    kind: Literal["rail", "flight", "meeting", "check_in", "check_out", "activity", "buffer"]
    commitment: Literal["fixed", "soft"] = "soft"
    precision: Literal["exact", "window", "date_only", "unknown"] = "unknown"
    timezone: DomesticZone = "Asia/Shanghai"
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    local_date: date | None = None
    end_date: date | None = None
    city: City | None = None
    arrival_city: City | None = None
    place: Label | None = None
    arrival_place: Label | None = None
    notes: Note = ""
    before_minutes: int = Field(default=0, ge=0, le=720)
    after_minutes: int = Field(default=0, ge=0, le=720)

    @model_validator(mode="after")
    def check_time(self):
        for value in (self.start_at, self.end_at, self.local_date, self.end_date):
            if value is not None and not 1900 <= value.year <= 2200:
                raise ValueError("日期超出支持范围")
        if self.precision in {"exact", "window"}:
            if not self.start_at or not self.end_at or self.local_date or self.end_date:
                raise ValueError("精确时刻或时间窗需要完整的起止时刻")
            try:
                tz = ZoneInfo(self.timezone)
                start, end = self.start_at.astimezone(UTC), self.end_at.astimezone(UTC)
                start.astimezone(tz)
                end.astimezone(tz)
            except (ValueError, OverflowError, ZoneInfoNotFoundError):
                raise ValueError("时刻或时区无效") from None
            if not timedelta(0) < end - start <= timedelta(days=31):
                raise ValueError("起止时刻必须有效，跨度不超过 31 天")
        elif self.start_at or self.end_at:
            raise ValueError("不确定的时刻不能被标作精确时间")
        elif self.precision == "date_only":
            if not self.local_date or self.end_date and not timedelta(0) <= self.end_date - self.local_date <= timedelta(days=30):
                raise ValueError("日期范围无效或超过 31 天")
        elif self.local_date or self.end_date:
            raise ValueError("已有日期的事件请设置日期精度")
        return self


class Quote(DTO):
    price: Money
    unit: Literal["seat", "room_night"]
    source_url: Literal["https://www.12306.cn/", "https://www.amap.com/"]
    queried_at: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def check_expiry(self):
        if self.valid_until <= self.queried_at:
            raise ValueError("报价失效时间必须晚于查询时间")
        return self


class Observation(DTO):
    kind: Literal["outbound_rail", "inbound_rail", "hotel_place"]
    source_url: Literal["https://www.12306.cn/", "https://www.amap.com/"]
    observed_at: AwareDatetime | None = None


class RecordedRoute(DTO):
    from_place: Label
    to_place: Label
    minutes: int = Field(ge=0, le=1440)
    source_url: Literal["https://www.amap.com/"]
    queried_at: AwareDatetime


class Option(DTO):
    option_id: OptionId
    status: Literal["validated", "provisional"]
    schedule_items: list[Event] = Field(default_factory=list, max_length=10)
    hotel: Label | None = None
    hotel_ref: Label | None = None
    hotel_reference_cny: list[Decimal] = Field(default_factory=list, max_length=2)
    quotes: list[Quote] = Field(default_factory=list, max_length=3)
    observations: list[Observation] = Field(default_factory=list, max_length=3)
    commute: RecordedRoute | None = None
    known_subtotals: dict[Currency, Decimal] = Field(default_factory=dict, max_length=8)
    reasons: list[Note] = Field(default_factory=list, max_length=12)


class ManualDraft(DTO):
    title: Label
    origin: City | None = None
    destination: City | None = None
    start_date: date | None = None
    end_date: date | None = None
    schedule_items: list[Event] = Field(default_factory=list, max_length=120)
    notes: Note = ""
    budget: Money | None = None

    @model_validator(mode="after")
    def check_range(self):
        if any(value and not 1900 <= value.year <= 2200 for value in (self.start_date, self.end_date)):
            raise ValueError("行程日期超出支持范围")
        if self.end_date and (not self.start_date or not timedelta(0) <= self.end_date - self.start_date <= timedelta(days=30)):
            raise ValueError("行程日期范围无效或超过 31 天")
        if len({event.event_id for event in self.schedule_items}) != len(self.schedule_items):
            raise ValueError("同一时间轴中不能重复使用事件编号")
        return self


class PlanRef(DTO):
    plan_id: UUID
    version: int = Field(ge=1, le=1_000_000)


class PlanSnapshot(ManualDraft):
    schema_version: Literal[1] = 1
    source_kind: Literal["typed", "legacy", "manual", "imported_summary"]
    quality: Literal["structured", "partial", "manual"]
    trip_request: TripRequest | None = None
    issues: list[Note] = Field(default_factory=list, max_length=40)
    options: list[Option] = Field(default_factory=list, max_length=3)
    selected_option_id: OptionId | None = None
    raw_estimate: Note | None = None
    based_on: PlanRef | None = None
    base_revision: int | None = Field(default=None, ge=1)


class CandidateInput(DTO):
    source: Literal["candidate"]
    candidate_ref: UUID
    session_id: Annotated[str, StringConstraints(pattern=r"^[\w-]{1,32}$")]
    option_id: OptionId | None = None
    title: Label | None = None


class ManualInput(DTO):
    source: Literal["manual"]
    draft: ManualDraft


class RestoreInput(DTO):
    source: Literal["saved_version"]


class SelectSavedOption(DTO):
    source: Literal["saved_option"]
    option_id: OptionId


class SummaryInput(DTO):
    source: Literal["historical_summary"]
    trip_id: Annotated[str, StringConstraints(min_length=1, max_length=48)]


class CopyInput(DTO):
    source: Literal["copy"]
    ref: PlanRef
    title: Label | None = None


CreateTrip = Annotated[CandidateInput | ManualInput | SummaryInput | CopyInput, Field(discriminator="source")]


class NewVersion(DTO):
    based_on_version: int = Field(ge=1, le=1_000_000)
    content: Annotated[CandidateInput | ManualInput | RestoreInput | SelectSavedOption, Field(discriminator="source")]


class RenameTrip(DTO):
    title: Label


class Replacement(PlanRef):
    revision: int = Field(ge=1, le=1_000_000)


class OperationPreview(DTO):
    action: Literal["schedule", "reschedule", "replace", "cancel", "archive", "complete"]
    draft_version: int = Field(ge=1, le=1_000_000)
    expected_revision: int = Field(ge=1, le=1_000_000)
    replace_refs: list[Replacement] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def check_replacements(self):
        if ((self.action == "replace") != bool(self.replace_refs)
                or len({row.plan_id for row in self.replace_refs}) != len(self.replace_refs)):
            raise ValueError("替换操作必须明确指定不同的旧行程和版本")
        return self


class OperationCommit(DTO):
    operation_id: UUID
    confirmed: Literal[True]
    acknowledged_issue_ids: list[Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]] = Field(default_factory=list, max_length=120)


class AssignmentPreview(DTO):
    plan_id: UUID | None
    expected_entry_revision: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class AssignmentCommit(DTO):
    operation_id: UUID
    confirmed: Literal[True]


PreferenceKey = Literal["home_city", "destination_preference", "transportation_preference", "seat_preference",
                        "hotel_brands", "nightly_budget", "departure_period", "meal_preference", "trip_pace"]
RevisionHash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class PreferenceEdit(DTO):
    expected_revision: RevisionHash
    value: Label | Money | None
    use_for_planning: bool


class PreferenceSettings(DTO):
    expected_revision: RevisionHash
    enabled: bool


class FavoriteInput(DTO):
    kind: Literal["plan", "rail", "hotel", "place"]
    ref: PlanRef
    option_id: OptionId | None = None
    direction: Literal["outbound", "inbound"] | None = None

    @model_validator(mode="after")
    def check_reference(self):
        if (self.kind != "plan") != bool(self.option_id) or (self.kind == "rail") != bool(self.direction):
            raise ValueError("请指定对应行程版本、备选和交通方向")
        return self
