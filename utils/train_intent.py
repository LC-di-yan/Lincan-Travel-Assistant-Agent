"""Conservative, model-free routing for a single train availability request."""
from __future__ import annotations

from datetime import date, datetime
import re

from utils.local_transport import needs_transport_advice
from utils.weather_intent import needs_weather
from utils.weather_range import resolve_weather_range, shanghai_now


# Keep this independent from agents.intention_agent: importing that module loads
# the model stack. Only city names, not districts or station abbreviations, belong
# here; an unrecognised place must go through the complete intent recogniser.
_CITIES = frozenset("""
北京 上海 广州 深圳 杭州 南京 成都 武汉 西安 苏州 天津 重庆 厦门 青岛 大连
宁波 无锡 长沙 郑州 济南 哈尔滨 沈阳 昆明 合肥 福州 石家庄 南昌 贵阳 太原
南宁 拉萨 乌鲁木齐 呼和浩特 银川 西宁 兰州 海口 三亚 珠海 嘉兴 丽江 大理
桂林 洛阳 威海 烟台 温州 绍兴 徐州 佛山 东莞 惠州 中山 江门 肇庆 潮州 揭阳
汕头 汕尾 梅州 常州 南通 镇江 泰州 盐城 淮安 连云港 宿迁 湖州 金华 衢州 舟山
台州 丽水 芜湖 潍坊 临沂 淄博 济宁 泰安 泉州 漳州 龙岩 三明 莆田 宁德 南平
宜昌 襄阳 荆州 绵阳 德阳 宜宾 南充 泸州 遵义 曲靖 玉溪 长春 吉林 鞍山 锦州
咸阳 宝鸡 榆林 柳州 北海 防城港 儋州 琼海 包头 鄂尔多斯 赤峰 九江 景德镇
岳阳 延安 秦皇岛 承德 张家界 黄山 敦煌
""".split())
_CITY = "(?:" + "|".join(sorted(_CITIES, key=lambda city: (-len(city), city))) + ")"
_CITY_RE = re.compile(_CITY + r"市?")
_PAIR_RE = re.compile(
    rf"(?P<origin>{_CITY})市?(?:出发)?(?:前往|到|至|去|往)(?P<destination>{_CITY})市?"
)
_ORIGIN_RES = (
    re.compile(rf"(?:从|出发地(?:是|为|[：:])|起点(?:是|为|[：:]))(?P<city>{_CITY})市?"),
    re.compile(rf"(?P<city>{_CITY})市?出发"),
)
_DESTINATION_RES = (
    re.compile(rf"(?:前往|去|到|往|至|目的地(?:是|为|[：:])|终点(?:是|为|[：:]))(?P<city>{_CITY})市?"),
)
_TRAIN_RE = re.compile(r"火车|高铁|动车|列车|车次|12306|城际")
_TRANSFER_PREFERENCE = re.compile(r"(?:尽量|优先)?\s*(?:少|不想|不愿|不用|不需要|无需|不要|避免)\s*(?:再)?\s*(?:换乘|中转|转车)")
_SPECIAL_RE = re.compile(
    r"票价|价格|多少钱|费用|经停|停靠|站点|车站|换乘|中转|转车|时刻表|"
    r"退票|改签|候补|抢票|订票|买票|购票|预订|开售|起售|放票|取票|检票|"
    r"报销|政策|标准|规定|学生票|儿童票|几折|折扣|优惠|晚点|准点|正点"
)
_OTHER_TASK_RE = re.compile(
    r"酒店|民宿|宾馆|住宿|旅馆|客栈|青旅|旅店|住哪|落脚|下榻|"
    r"天气|气温|温度|带伞|穿衣|餐厅|饭店|吃饭|美食|小吃|景点|景区|"
    r"公园|好玩|游玩|攻略|规划|行程|安排|旅游|机票|飞机|航班|汽车票|大巴|"
    r"汇率|换算|兑换|翻译|记账|记一笔|偏好|历史|记录|签证|地图|导航|"
    r"为什么|为何|怎么|如何|安全|意思|区别|介绍|取消|不查|别查|不用查"
)
_UNSUPPORTED_DATE_RE = re.compile(
    r"月底|月初|下个?月|下下个?月|元旦|春节|清明|劳动节|端午|中秋|国庆|圣诞|"
    r"未来|接下来|明后|今明|[零一二两三四五六七八九十]+[月日号]"
)
_DATE_RE = re.compile(
    r"(?<!\d)(?:\d{4}(?:年|[-/]))?\d{1,2}(?:月|[-/])\d{1,2}(?:日|号)?(?!\d)|"
    r"(?<!\d)\d{1,2}(?:日|号)(?!\d)|"
    r"大后天|后天|后早|明天|明日|明早|明晚|今天|今日|今早|今晚|昨天|昨日|"
    r"(?:下下|下|本|这)?(?:周|星期)[一二三四五六日天末]?"
)
_PERIODS = (
    ("morning", ("凌晨", "清晨", "早上", "早晨", "明早", "今早", "后早", "上午", "早班")),
    ("afternoon", ("下午", "午后")),
    ("evening", ("晚上", "今晚", "明晚", "傍晚", "晚班")),
)
# A residue check is intentionally stricter than a keyword detector. Unknown
# clauses must not disappear behind an early, single-agent return.
_REQUEST_WORDS = sorted((
    "请帮我", "麻烦帮我", "麻烦", "帮我", "替我", "查一下", "查询", "查查", "查",
    "搜一下", "搜索", "搜", "看一下", "看看", "查看", "看", "请", "我想", "我要",
    "想", "要", "一下", "火车票", "高铁票", "动车票", "列车票", "火车", "高铁",
    "动车", "列车", "城际", "12306", "车票", "车次", "班次", "余票", "有票",
    "没票", "还有票", "有没有票", "有哪些", "有什么", "是否", "有没有", "还有",
    "有", "的", "吗", "呢", "啊", "吧", "呀", "只", "仅", "就", "需要", "出差",
    "前往", "出发地", "目的地", "起点", "终点", "出发", "从", "到", "至", "去",
    "往", "是", "为", "和", "或", "以及", "还有哪些", "能查到", "能否查到",
    "凌晨", "清晨", "早上", "早晨", "上午", "早班", "下午", "午后", "晚上", "傍晚", "晚班",
), key=len, reverse=True)
_REQUEST_RE = re.compile("|".join(map(re.escape, _REQUEST_WORDS)))


def without_transfer_preferences(text: str) -> str:
    """Remove preferences that a direct train already satisfies, not requests for connections."""
    return _TRANSFER_PREFERENCE.sub("", text)


def _extract_route(query: str) -> tuple[str, str] | None:
    cities = {match.group(0).removesuffix("市") for match in _CITY_RE.finditer(query)}
    if len(cities) > 2:
        return None
    pairs = {(match["origin"], match["destination"]) for match in _PAIR_RE.finditer(query)}
    if len(pairs) > 1:
        return None
    origins = {match["city"] for pattern in _ORIGIN_RES for match in pattern.finditer(query)}
    destinations = {match["city"] for pattern in _DESTINATION_RES for match in pattern.finditer(query)}
    if pairs:
        origin, destination = next(iter(pairs))
        origins.add(origin)
        destinations.add(destination)
    if len(origins) > 1 or len(destinations) > 1:
        return None
    origin = next(iter(origins), "")
    destination = next(iter(destinations), "")
    # A bare city mention has no reliable role; do not silently assign it.
    if cities - {origin, destination}:
        return None
    return origin, destination


def parse_train_date(text: str, now: date | datetime | None = None) -> str:
    """Resolve one explicitly supplied travel day in Beijing time, never today by default."""
    q = re.sub(r"\s+", "", text or "")
    if _UNSUPPORTED_DATE_RE.search(q):
        return ""
    for source, target in (("明早", "明天"), ("明晚", "明天"), ("今早", "今天"), ("今晚", "今天"), ("后早", "后天")):
        q = q.replace(source, target)
    dates = resolve_weather_range(q, now=shanghai_now() if now is None else now)
    if not dates.explicit or dates.error or dates.start != dates.end or dates.start < dates.today:
        return ""
    return dates.start.isoformat()


def build_train_intention(query: str) -> dict | None:
    """Return a complete intent only for a high-confidence, single ticket lookup.

    This function never reads conversation history or defaults an omitted date to
    today. Clarification asks for the route first, then the date, preserving all
    known values and filters in ``fast_train_ticket`` throughout that exchange.
    """
    q = re.sub(r"\s+", "", without_transfer_preferences(query or ""))
    if not _TRAIN_RE.search(q):
        return None
    if (_SPECIAL_RE.search(q) or _OTHER_TASK_RE.search(q)
            or needs_weather(q) or needs_transport_advice(q)):
        return None
    if _UNSUPPORTED_DATE_RE.search(q):
        return None
    route = _extract_route(q)
    if route is None:
        return None
    origin, destination = route
    if not origin and not destination and not re.search(r"查|搜|看|票|车次|班次", q):
        return None

    date_str = parse_train_date(q)
    if not date_str and _DATE_RE.search(q):
        return None

    residue = _CITY_RE.sub("", q)
    residue = _DATE_RE.sub("", residue)
    residue = _REQUEST_RE.sub("", residue)
    if re.sub(r"[，,。.!！?？、；;：:()（）\-—~～/]+", "", residue):
        return None

    fast_params = {"from": origin, "to": destination, "date": date_str}
    periods = [period for period, words in _PERIODS if any(word in q for word in words)]
    if len(periods) > 1:
        return None
    if periods:
        fast_params["period"] = periods[0]
    train_types = [kind for word, kind in (("高铁", "G"), ("动车", "D"), ("城际", "C")) if word in q]
    if train_types:
        fast_params["train_types"] = train_types

    # Keep every pending field while asking only the highest-priority question.
    # The chat layer must gate execution while needs_clarification is true; keep
    # the intended schedule here so a one-word answer cannot lose the task.
    missing = [name for name, value in (("目的地", destination), ("出发地", origin), ("出发日期", date_str)) if not value]
    question = ""
    if "目的地" in missing:
        question = "你想从哪里出发，前往哪里？" if "出发地" in missing else "你想去哪里？"
    elif "出发地" in missing:
        question = "你准备从哪里出发？"
    elif "出发日期" in missing:
        question = "你计划哪天出发？"
    return {
        "reasoning": "确定性本地解析",
        "intents": [{"type": "train_ticket", "confidence": 1.0, "description": "火车票余票或班次查询", "reason": "完整单任务规则匹配"}],
        "key_entities": {"origin": origin, "destination": destination, "date": date_str},
        "fast_event": {
            "origin": origin, "destination": destination, "start_date": date_str,
            "end_date": "", "duration_days": 1, "trip_purpose": "", "missing_info": missing,
        },
        "rewritten_query": (query or "").strip(),
        "needs_clarification": bool(missing),
        "clarification_field": missing[0] if missing else "",
        "clarification_question": question,
        "agent_schedule": [{"agent_name": "train_ticket", "priority": 1, "reason": "查询火车票", "expected_output": "车次列表"}],
        "fast_train_ticket": fast_params,
    }
