"""Deterministic currency parsing shared by routing and conversion."""
import re
from decimal import Decimal, InvalidOperation


CURRENCY_MAP = {
    "人民币": "CNY", "元": "CNY", "块": "CNY", "美元": "USD", "美金": "USD", "刀": "USD",
    "欧元": "EUR", "英镑": "GBP", "日元": "JPY", "日币": "JPY", "韩元": "KRW",
    "港币": "HKD", "港元": "HKD", "新台币": "TWD", "台币": "TWD",
    "新加坡元": "SGD", "新币": "SGD", "泰铢": "THB", "澳元": "AUD", "加元": "CAD",
}
_CODES = set(CURRENCY_MAP.values())
_TOKEN = "(?:" + "|".join(sorted(CURRENCY_MAP, key=len, reverse=True)) + "|" + "|".join(sorted(_CODES)) + ")"
_AMOUNT = r"(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
_PREFIX = r"(?:(?:请|麻烦)?(?:帮我|给我)?(?:算一下|换算一下|换算|计算|查一下|查询|查查|看看)?)?(?:把|将)?"
_CONVERT = re.compile(
    rf"{_PREFIX}(?P<amount>{_AMOUNT})\s*(?P<src>{_TOKEN})\s*"
    rf"(?:大约|大概|约)?(?:可以|能)?(?:兑换[成为]?|换算[成为]?|转换[成为]?|换成?|兑|等于|相当于|折合|合|是|转[成为]?|多少)\s*"
    rf"(?:多少|几)?\s*(?P<dst>{_TOKEN})(?:是多少|多少钱|多少)?", re.I,
)
_COMMAND_CONVERT = re.compile(
    rf"(?:(?:请|麻烦)?(?:帮我|给我)?)?(?:换算|转换|兑换)(?:一下)?\s*(?P<amount>{_AMOUNT})\s*(?P<src>{_TOKEN})\s*[成为到]\s*(?P<dst>{_TOKEN})", re.I,
)
_RATE = re.compile(rf"{_PREFIX}(?P<src>{_TOKEN})(?:的)?\s*(?:兑|兑换|换|对|/|到)\s*(?P<dst>{_TOKEN})(?:的)?(?:汇率)?(?:是多少|多少|怎么样)?", re.I)
_SINGLE = re.compile(rf"{_PREFIX}(?P<src>{_TOKEN})(?:的)?汇率(?:是多少|多少|怎么样)?", re.I)


def parse_currency(query: str):
    """Accept a complete, single conversion request, never a matching substring."""
    # 只删除句尾标点；前导小数点是金额的一部分（.5 不能变成 5）。
    q = query.strip().rstrip("。.!！?？ ")
    match = _CONVERT.fullmatch(q) or _COMMAND_CONVERT.fullmatch(q) or _RATE.fullmatch(q) or _SINGLE.fullmatch(q)
    if not match:
        return None
    groups = match.groupdict()
    src = CURRENCY_MAP.get(groups["src"], groups["src"].upper())
    dst_word = groups.get("dst") or "人民币"
    dst = CURRENCY_MAP.get(dst_word, dst_word.upper())
    try:
        amount = Decimal((groups.get("amount") or "1").replace(",", ""))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0 or amount > Decimal("1e15"):
        return None
    return {"from_currency": src, "to_currency": dst, "amount": float(amount)}
