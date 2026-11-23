"""Resolve weather dates independently of the host timezone or API response order."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from utils.weather_intent import asks_about_clothing


try:
    SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    # Windows installations do not always ship the IANA timezone database.
    SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI_TZ)


@dataclass(frozen=True)
class WeatherRange:
    today: date
    start: date
    end: date
    label: str
    explicit: bool = False
    error: str = ""

    @property
    def include_current(self) -> bool:
        return not self.error and self.start <= self.today <= self.end

    def contains(self, day: date) -> bool:
        return not self.error and self.start <= day <= self.end

    def as_dict(self) -> dict:
        return {
            "start_date": self.start.isoformat(),
            "end_date": self.end.isoformat(),
            "include_current": self.include_current,
            "label": self.label,
        }


_NUMBER = r"[0-9零〇一二两三四五六七八九十百]+"
_DIGITS = {c: i for i, c in enumerate("零一二三四五六七八九")}
_DIGITS.update({"〇": 0, "两": 2})
_DATE = re.compile(
    r"(?<!\d)(?:(?P<year>\d{4})\s*(?:年|[-/]))?"
    r"(?P<month>\d{1,2})\s*(?:月|[-/])\s*(?P<day>\d{1,2})(?:日|号)?(?!\d)"
)


def _number(text: str) -> int:
    if text.isdigit():
        return int(text)
    total, digit = 0, 0
    for character in text:
        if character in _DIGITS:
            digit = _DIGITS[character]
        elif character in ("十", "百"):
            total += (digit or 1) * (10 if character == "十" else 100)
            digit = 0
    return total + digit


def resolve_weather_range(query: str, now: date | datetime | None = None) -> WeatherRange:
    """Unqualified weather includes today; future/next N days start tomorrow."""
    if now is None:
        today = shanghai_now().date()
    elif isinstance(now, datetime):
        today = (now.replace(tzinfo=SHANGHAI_TZ) if now.tzinfo is None else now.astimezone(SHANGHAI_TZ)).date()
    else:
        today = now
    text = re.sub(r"\s+", "", query or "")

    def result(start: date, end: date, label: str, error: str = "") -> WeatherRange:
        return WeatherRange(today, start, end, label, explicit=True, error=error)

    # Explicit calendar dates take priority over loose words in a longer request.
    matches = list(_DATE.finditer(text))
    if matches:
        dates = []
        try:
            for match in matches:
                year = int(match["year"]) if match["year"] else today.year
                day = date(year, int(match["month"]), int(match["day"]))
                if not match["year"] and day < today:
                    day = day.replace(year=year + 1)
                dates.append(day)
        except ValueError:
            return result(today, today, "指定日期", "日期无效，请提供有效的年月日。")
        start, end = dates[0], dates[-1]
        if end < start:
            if not matches[-1]["year"]:
                try:
                    end = end.replace(year=start.year + 1)
                except ValueError:
                    return result(start, start, "指定日期", "日期无效，请提供有效的年月日。")
            else:
                return result(start, end, "指定日期", "结束日期早于开始日期，请确认查询范围。")
        # Support the common abbreviated range: 11月20日至22日.
        abbreviated = re.match(r"(?:到|至|[-~～])(?P<day>\d{1,2})(?:日|号)", text[matches[0].end():]) if len(matches) == 1 else None
        if abbreviated:
            try:
                end = start.replace(day=int(abbreviated["day"]))
            except ValueError:
                return result(start, start, "指定日期", "日期无效，请提供有效的年月日。")
            if end < start:
                return result(start, end, "指定日期", "结束日期早于开始日期，请确认查询范围。")
        label = start.isoformat() if start == end else f"{start.isoformat()} 至 {end.isoformat()}"
        return result(start, end, label)

    count_match = re.search(rf"(?:未来|接下来|往后|今后|随后)(?:的)?({_NUMBER})(?:个)?(天|日|周|星期)", text)
    start_match = re.search(r"(?:从)?(今天|今日|明天|明日|后天|大后天)(?:起|开始)", text)
    if count_match or start_match:
        count = _number(count_match[1]) if count_match else 1
        if count_match and count_match[2] in ("周", "星期"):
            count *= 7
        if not count_match:
            following = re.search(rf"(?:起|开始)(?:的)?({_NUMBER})(?:个)?(?:天|日)", text)
            if following:
                count = _number(following[1])
        offset = {"今天": 0, "今日": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3}.get(start_match[1], 1) if start_match else 1
        if count < 1 or count > 3660:
            return result(today, today, "指定天数", "查询天数无效或范围过大，请提供合理的日期范围。")
        start = today + timedelta(days=offset)
        return result(start, start + timedelta(days=count - 1), f"未来 {count} 天" if offset == 1 else f"{start_match[1]}起 {count} 天")

    day_match = re.search(r"(?<!\d)(\d{1,2})(?:日|号)", text)
    if day_match:
        try:
            start = today.replace(day=int(day_match[1]))
            if start < today:
                next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
                start = next_month.replace(day=int(day_match[1]))
        except ValueError:
            return result(today, today, "指定日期", "日期无效，请提供有效的年月日。")
        return result(start, start, start.isoformat())

    relative = [("大后天", 3), ("后天", 2), ("明天", 1), ("明日", 1), ("今天", 0), ("今日", 0), ("昨天", -1), ("昨日", -1)]
    offsets = []
    remaining = text
    for word, offset in relative:
        if word in remaining:
            offsets.append(offset)
            remaining = remaining.replace(word, "")
    if "今明" in text:
        offsets.extend([0, 1])
    if offsets:
        start, end = today + timedelta(days=min(offsets)), today + timedelta(days=max(offsets))
        labels = {-1: "昨天", 0: "今天", 1: "明天", 2: "后天", 3: "大后天"}
        return result(start, end, "、".join(labels[offset] for offset in sorted(set(offsets))))

    # “下周天气”的“天”属于“天气”，不是“星期天”。
    week_match = re.search(r"(下下|下|本|这)?(?:周|星期)([一二三四五六日末]|天(?!气))?", text)
    if week_match:
        shift = {"下下": 2, "下": 1}.get(week_match[1], 0)
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=shift)
        weekday = week_match[2]
        if weekday:
            number = 5 if weekday == "末" else "一二三四五六日天".index(weekday)
            number = min(number, 6)
            start = monday + timedelta(days=number)
            if not week_match[1] and start < today:
                start += timedelta(weeks=1)
            end = start + timedelta(days=1) if weekday == "末" else start
        else:
            start = monday if shift else today
            end = monday + timedelta(days=6)
        return result(start, end, week_match[0])

    if re.search(r"下个?月", text):
        start = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = ((start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))
        return result(start, end, "下个月")
    if re.search(r"未来|接下来|以后|之后|后面", text):
        return result(today + timedelta(days=1), today + timedelta(days=3), "未来 3 天")
    if re.search(r"现在|当前|此刻|实时|多少度|冷不冷|热不热|冷吗|热吗|气温|温度", text) or asks_about_clothing(text):
        return result(today, today, "今天")
    return WeatherRange(today, today, today + timedelta(days=3), "今天及未来 3 天")
