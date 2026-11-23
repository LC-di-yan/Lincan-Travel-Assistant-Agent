"""费用金额、币种、日期解析与按原币种汇总。"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

_CURRENCIES = {
    "人民币": "CNY", "美元": "USD", "美金": "USD", "欧元": "EUR", "英镑": "GBP",
    "日元": "JPY", "日币": "JPY", "韩元": "KRW", "港币": "HKD", "港元": "HKD",
    "新台币": "TWD", "台币": "TWD", "新加坡元": "SGD", "新币": "SGD", "泰铢": "THB",
    "澳元": "AUD", "加元": "CAD", "元": "CNY", "块": "CNY",
    "瑞士法郎": "CHF", "瑞郎": "CHF", "俄罗斯卢布": "RUB", "卢布": "RUB",
    "越南盾": "VND", "印尼盾": "IDR", "印度卢比": "INR", "林吉特": "MYR", "马币": "MYR",
    "RMB": "CNY",
}
_ISO_CODES = set(_CURRENCIES.values())
_CURRENCY_PATTERN = re.compile("|".join(sorted(_CURRENCIES, key=len, reverse=True)) + r"|(?<![A-Za-z])(?:" + "|".join(sorted(_ISO_CODES)) + r")(?![A-Za-z])", re.I)


def is_single_expense_statement(query: str, amount_token: str) -> bool:
    """只有明确的一笔支出才可直接写入；其余请求交回完整意图解析。"""
    if re.search(r"[?？€£¥￥$]|吗|是否|多少|有没|查|统计|汇总|合计|删|撤|取消|修改|改成|改为|更正|纠正|别记|不.{0,3}记|预算|预计|如果|假如|准备|计划|退款|退回", query):
        return False
    without_dates = re.sub(r"(?:(?:\d{4}[-年])?\d{1,2}[-月]\d{1,2})(?:日|号)?", " ", query)
    if re.search(r"[-−负]\s*\d|\d\s*[十百千万亿折%％]|[,.，．]\d{3}(?!\d)", without_dates):
        return False
    return re.findall(r"\d+(?:\.\d+)?", without_dates) == [amount_token]


def expense_fields(query: str, today: date | None = None) -> dict | None:
    """只快解析明确日期和币种，无法确定时回退模型而非擅自记为今天人民币。"""
    today = today or date.today()
    codes = {_CURRENCIES.get(word, _CURRENCIES.get(word.upper(), word.upper())) for word in _CURRENCY_PATTERN.findall(query)}
    # 数字与币种代码通常紧挨着，不能使用单词边界；未知外币也不能默认为人民币。
    explicit_codes = re.findall(r"\d\s*([A-Za-z]{3})(?![A-Za-z])", query)
    if any(code.upper() not in _ISO_CODES | {"RMB"} for code in explicit_codes):
        return None
    if re.search(r"比索|马克|克朗|法郎|里亚尔|第纳尔|迪拉姆|卢比", _CURRENCY_PATTERN.sub("", query)):
        return None
    if len(codes) > 1 or "$" in query:
        return None
    currency = next(iter(codes), "CNY")
    dates = []
    for word, offset in (("前天", -2), ("昨天", -1), ("今天", 0)):
        if word in query:
            dates.append(today + timedelta(days=offset))
    explicit = re.findall(r"(?:(\d{4})[-年])?(\d{1,2})[-月](\d{1,2})(?:日|号)?", query)
    try:
        for year, month, day in explicit:
            dates.append(date(int(year) if year else today.year, int(month), int(day)))
    except ValueError:
        return None
    if len(set(dates)) > 1:
        return None
    if not dates and re.search(r"上周|上星期|上个月|去年|明天|后天|前几天|月底|月初|\d+[天周月年]前|(?:周|星期)[一二三四五六日天]|\d{1,2}/\d{1,2}", query):
        return None
    return {"currency": currency, "date": (dates[0] if dates else today).isoformat()}


def money(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("金额必须是有效数字")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or abs(amount) > Decimal("9999999999.99"):
            raise ValueError("金额超出有效范围")
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("金额必须是有效数字") from exc


def currency_code(value) -> str:
    code = str(value or "CNY").upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValueError("请提供三位币种代码")
    return code


def format_money(amount, currency="CNY") -> str:
    prefix = "¥" if currency == "CNY" else f"{currency} "
    return f"{prefix}{money(amount):.2f}"


def summarize_expenses(expenses: list[dict]) -> dict:
    totals, categories = {}, {}
    for item in expenses:
        code = currency_code(item.get("currency"))
        amount = money(item.get("amount", 0))
        totals[code] = totals.get(code, Decimal(0)) + amount
        group = categories.setdefault(code, {})
        category = item.get("category") or "其他"
        group[category] = group.get(category, Decimal(0)) + amount
    code = next(iter(totals)) if len(totals) == 1 else ("CNY" if not totals else None)
    totals = {key: float(value) for key, value in totals.items()}
    categories = {key: {cat: float(amount) for cat, amount in group.items()} for key, group in categories.items()}
    return {"total": totals.get(code, 0) if code else None, "currency": code,
            "totals_by_currency": totals, "by_category_by_currency": categories,
            "by_category": categories.get(code, {}) if code else {},
            "count": len(expenses), "items": expenses[-10:]}
