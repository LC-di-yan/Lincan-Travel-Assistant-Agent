"""Shared parsing and strict filtering for the two map-based hotel entries."""

import re
from decimal import Decimal

_NUMBER = r"(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d{1,2})?"
_SEPARATOR = r"[-–—~～到至]"
_PRICE = re.compile(rf"\s*[¥￥]?\s*({_NUMBER})(?:\s*元)?(?:\s*{_SEPARATOR}\s*[¥￥]?\s*({_NUMBER})(?:\s*元)?)?\s*")
_REFERENCE_NOTE = "高德地图价格仅供参考，未核验指定日期的房价、税费或房态。"
_NOT_CNY = r"美元|美金|港币|港元|澳元|欧元|日元|日币|新币|加元|台币|韩元|英镑|泰铢|法郎|卢布|比索|卢比|[$€£₹₩]|(?:USD|HKD|AUD|EUR|JPY|THB|SGD|GBP|KRW|CAD|TWD|CHF|INR|RUB)\b"


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", "").replace("，", ""))


def parse_hotel_budget(query: str) -> str | None:
    # POI costs cannot be compared to non-CNY or whole-trip / multi-night totals.
    if re.search(r"差旅总预算|总预算|总价|总共|合计", query):
        return "unverified"
    if re.search(_NOT_CNY, query, re.I) and re.search(r"预算|每晚|以内|以下|不超过|低于|左右|封顶", query):
        return "unverified"
    if match := re.search(rf"(?<![\d.-])({_NUMBER})\s*(?:元)?\s*{_SEPARATOR}\s*({_NUMBER})(?![\d.-])\s*元", query):
        return f"{_decimal(match[1])}-{_decimal(match[2])}"
    prefix = re.search(rf"(不超过|不能超过|不要超过|最多|至多|上限|最高|低于|小于|少于|小于等于)\s*[:：]?\s*[¥￥]?\s*({_NUMBER})(?![\d.万千百])", query)
    if prefix:
        return f"0-{_decimal(prefix[2])}" + ("!" if prefix[1] in {"低于", "小于", "少于"} else "")
    if match := re.search(rf"(?<![\d.-])({_NUMBER})\s*(?:元|块)?\s*(以内|以下|左右|封顶)", query):
        amount = _decimal(match[1])
        if match[2] != "左右":
            return f"0-{amount}"
        return f"{amount * Decimal('0.7')}-{amount * Decimal('1.3')}"
    if match := re.search(rf"(?:住宿|酒店|每晚|单晚)?预算\s*[:：为]?\s*[¥￥]?\s*({_NUMBER})(?![\d.万千百])\s*(?:元|块)?", query):
        return f"0-{_decimal(match[1])}"
    if re.search(r"预算|房价上限|每晚[^。]{0,12}(?:元|以内|以下|封顶)", query):
        return "unverified"
    return None


def reference_price_range(value):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    match = _PRICE.fullmatch(str(value))
    if not match:
        return None
    low, high = _decimal(match[1]), _decimal(match[2] or match[1])
    return (low, high) if 0 < low <= high else None


def filter_hotel_budget(pois: list[dict], price_range: str) -> list[dict]:
    exclusive = price_range.endswith("!")
    budget = _PRICE.fullmatch(price_range.removesuffix("!"))
    if not budget:
        return []
    floor, ceiling = _decimal(budget[1]), _decimal(budget[2] or budget[1])
    selected = []
    for poi in pois:
        value = reference_price_range((poi.get("biz_ext") or {}).get("cost"))
        if not value:
            continue
        low, high = value
        if low >= floor and (high < ceiling if exclusive else high <= ceiling):
            selected.append(poi)
    return selected


def label_hotel_prices(result: dict, budget: str | None, source_count: int) -> dict:
    results = result["results"]
    results.update(price_source="高德地图参考价", price_status="reference_only", source_count=source_count)
    if budget:
        count = len(results["hotels"])
        results.update(count=count, budget_status="reference_match" if count else "unverified" if budget == "unverified" else "no_match")
        if budget == "unverified":
            results["summary"] = "住宿预算的币种、口径或数值尚无法核验，未将任何酒店标为符合预算。请提供人民币每晚上限。"
        elif count:
            results["summary"] = f"本次候选中有 {count} 家的地图参考价落在预算范围内。{_REFERENCE_NOTE}"
        else:
            results["summary"] = f"本次候选中没有地图参考价符合预算的酒店。缺失或超预算的价格未计入。{_REFERENCE_NOTE}"
    return result
