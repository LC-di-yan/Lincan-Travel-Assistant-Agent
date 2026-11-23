"""Conservative local parsing and routing for explicit preference statements."""
import re


_BRANDS = r"汉庭|如家|全季|亚朵|桔子|锦江之星|维也纳|希尔顿|万豪|喜来登|洲际|香格里拉|凯悦|华住|七天|7天"
_AIRLINES = r"东航|南航|国航|海航|厦航|深航|春秋航空|吉祥航空|东方航空|南方航空|中国国际航空"
_TRANSPORT = r"公共交通|公交车|出租车|网约车|地铁|公交|高铁|动车|火车|飞机|打车|步行|自驾|骑行|骑车"
_SEATS = r"靠窗|靠过道|过道"
_MEALS = r"清淡|素食|清真|低盐|低油|低糖|无糖|微辣|中辣|重辣|辣|素"

_LEAD = r"(?:(?:另外|此外|同时))?(?:我)?(?:现在|平时)?"
_STATE = r"(?:现在)?(?:还|也)?(?:更|比较)?(?:喜欢|偏好|习惯|倾向|偏向)(?:于)?"
_TIME = r"(?:时|的时候|方面|上)?"
_BUSINESS = r"(?:出差(?:时|的时候)?)?"
_SETTING_LEAD = r"(?:我)?(?:把)?(?:我的)?"
_SETTING = r"(?:偏好|喜好|习惯)(?:是|为|改成|改为|换成|设为|设置为|调整为|更新为|增加|追加|新增|加上)"
_REPLACE = re.compile(r"改成|改为|换成|设为|设置为|调整为|更新为|搬家|迁居|搬到|搬去")
_APPEND = re.compile(r"^(?:另外|此外)|(?:还|也)(?=(?:更|比较)?(?:喜欢|偏好|习惯|倾向|偏向|常坐|经常))|增加|追加|新增|加上")
_SAVE_PREFIX = re.compile(r"^(?:请)?(?:帮我|替我)?(?:记住|记一下|保存一下)[，,:： ]*")
# A full-clause match is required as well: these guards never make a partial
# preference safe to save when another task or an uncertain statement follows.
_UNSAFE = re.compile(
    r"不|别|讨厌|取消|删除|排除|除外|[?？]|吗|呢|么|是否|能否|可否|有没有|有无|是不是|还是|"
    r"什么|哪|如何|怎么|怎样|多少|几|为何|"
    r"查|搜|天气|气温|推荐|建议|订|预定|买|行程|规划|攻略|"
    r"翻译|换算|汇率|记账|记(?:一)?笔|报销|但是|不过|然后|顺便|想|打算|计划|准备|要|"
    r"帮|替我|麻烦|请|告诉|如果|假如|可能|也许|大概|应该|似乎|据说|听说"
)
_UNCERTAIN = re.compile(
    r"暂时|临时|暂住|短住|短期|暂定|待定|未定|未知|未确认|未明确|待确认|待明确|不详|"
    r"无固定|无法|无从|尚未|还没|没有|没想好|没确定|没确认|忘了|"
    r"或许|估计|差不多|大约|左右|随便|随机|无所谓|也行|都行"
)
# Unknown descriptions are additionally constrained below; this cross-domain
# guard rejects attached actions rather than trying to classify their task.
_EXTRA_ACTION = re.compile(
    r"给我|为我|替我|(?:讲|说|听|唱|放|念|读)(?:个|段|首|篇|一|下)|笑话|故事|音乐|歌曲|视频|电影|新闻|"
    r"打开|关闭|播放|暂停|停止|启动|运行|执行|安装|卸载|下载|上传|导出|导入|复制|粘贴|截图|"
    r"发送|发(?:消息|邮件|短信|给)|联系|拨打|呼叫|通知|提醒|闹钟|创建|生成|制作|编辑|修改|"
    r"设置(?!为)|切换|整理|总结|解释|讲解|回答|计算|算一下|修复|付款|转账|支付|下单|叫车|导航|定位|打电话"
)
_CLAUSE_SPLIT = re.compile(
    r"[，,；;。\n\r]+|(?:并且|而且|以及|同时|并|和)(?=(?:我)?(?:现在|平时)?(?:还|也)?"
    r"(?:更|比较)?(?:喜欢|偏好|习惯|倾向|偏向|常坐|经常|出差|出行|交通|住宿|住酒店|乘机|座位|饮食|餐饮))"
)
_HOME_HEAD = r"(?:我的家在|我家在|我常住(?:在)?|我住在|我搬家到|(?:我)?迁居(?:到)?|我搬到|我搬去)"
# Bare locations need a known geographic name. Detailed addresses require a
# known root followed only by administrative, street, building and unit parts.
# Arbitrary Chinese text must never become an address just because it follows 在.
_HOME_CITIES = r"北京|上海|天津|重庆|广州|深圳|杭州|南京|成都|武汉|西安|苏州|厦门|青岛|大连|宁波|无锡|长沙|郑州|济南|哈尔滨|沈阳|昆明|合肥|福州|石家庄|南昌|贵阳|太原|南宁|拉萨|乌鲁木齐|呼和浩特|银川|西宁|兰州|海口|三亚|珠海|嘉兴|丽江|大理|桂林|洛阳|威海|烟台|温州|绍兴|徐州|香港|澳门|台北|高雄|东京|大阪|首尔|新加坡|曼谷|伦敦|巴黎|纽约|悉尼"
_HOME_PROVINCE = r"(?:河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾)(?:省)?|(?:内蒙古|西藏)(?:自治区)?|广西(?:壮族)?(?:自治区)?|宁夏(?:回族)?(?:自治区)?|新疆(?:维吾尔)?(?:自治区)?"
_ADDRESS_TAIL = (
    r"(?:[\u4e00-\u9fff]{2,8}(?:自治县|新区|区|县|旗|镇|乡|村|街道)){0,4}"
    r"(?:[\u4e00-\u9fffA-Za-z0-9·-]{2,12}(?:大道|路|街|巷)){0,2}"
    r"(?:[\u4e00-\u9fffA-Za-z0-9·-]{2,12}(?:小区|社区|花园|公寓|大厦|园|苑)){0,2}"
    r"(?:[0-9A-Za-z一二三四五六七八九十百-]{1,8}(?:号|弄|栋|幢|单元|室|楼|座)){0,5}"
)
_ADDRESS_ROOT = rf"(?:(?:{_HOME_PROVINCE}))?(?:{_HOME_CITIES})(?:市)?"
_HOME = re.compile(rf"{_HOME_HEAD}(?P<value>{_ADDRESS_ROOT}{_ADDRESS_TAIL})(?:了)?")
_HOME_CANDIDATE = re.compile(rf"{_HOME_HEAD}(?P<value>[\u4e00-\u9fffA-Za-z0-9·-]{{2,80}}?)(?:了)?")
_UNKNOWN_ADDRESS = re.compile(rf"(?:(?:{_HOME_PROVINCE}))?[\u4e00-\u9fff]{{2,8}}(?:市|自治州|州|县|区){_ADDRESS_TAIL}")
_ADDRESS_OTHER = re.compile(
    r"喜欢|偏好|习惯|倾向|偏向|去|坐|乘|出差|出行|酒店|入住|用餐|吃饭|喝茶|并|同时|另外|以及|以后|之后|下次|"
    r"打车|叫车|下单|写(?:信|邮件|一|封)|邮件|开会|会议|游玩|旅游|今天|明天|后天|接着|随后|接下来|顺带|排序"
)

# type, values, context before the predicate, optional context after it,
# choice verb, value suffix, field name in explicit update statements.
_FAMILIES = (
    ("hotel_brands", _BRANDS, rf"{_BUSINESS}(?:住酒店|入住酒店|住宿|酒店(?:品牌)?)|出差", r"住宿|住酒店", r"住|入住|选择", r"(?:酒店)?(?:住宿|入住)?", rf"{_BUSINESS}(?:酒店|住宿)(?:品牌)?"),
    ("airlines", _AIRLINES, rf"{_BUSINESS}(?:坐飞机|乘坐飞机|乘飞机|乘机|出行|航空公司|航司)|出差", r"乘机|坐飞机|乘坐飞机", r"坐|乘坐|乘|搭乘|选择", r"(?:的?(?:航班|飞机))?(?:出行)?", rf"{_BUSINESS}(?:航空公司|航司|航空)"),
    ("seat_preference", _SEATS, rf"{_BUSINESS}(?:坐飞机|乘坐飞机|乘飞机|乘机|坐高铁|乘坐高铁|坐火车|乘车|座位|座席)|出差", r"乘机|坐飞机|乘坐飞机|坐高铁|乘车", r"坐|选择|选", r"(?:的?(?:座位|位置|座))?", rf"{_BUSINESS}(?:座位|座席|座位位置)"),
    ("transportation_preference", _TRANSPORT, rf"{_BUSINESS}(?:出行|交通|出行方式|交通方式)|出差", r"出行|交通", r"坐|乘坐|乘|搭乘|选择", r"(?:出行|通勤|出门)?", rf"{_BUSINESS}(?:出行|交通)(?:方式)?"),
    ("meal_preference", _MEALS, rf"{_BUSINESS}(?:饮食|餐饮|餐食|口味|吃饭|用餐)|出差", r"饮食|用餐", r"吃|选择|选", r"(?:的?(?:口味|饮食|餐食|饭菜|食物))?", rf"{_BUSINESS}(?:饮食|餐饮|餐食|口味|用餐)"),
)


def _family_patterns(values, context, after, choice, suffix, domain, *, require_context=False):
    value = rf"(?P<value>{values})"
    before = rf"(?:(?:{context}){_TIME})" + ("" if require_context else "?")
    tail = rf"(?:(?:{after}){_TIME})?(?:{choice})?{value}{suffix}"
    field = rf"(?:{domain})" + ("" if require_context else "?")
    return (
        re.compile(rf"{_LEAD}{before}{_STATE}{tail}"),
        re.compile(rf"(?:{context}){_TIME}我(?:平时)?{_STATE}{tail}"),
        re.compile(rf"{_SETTING_LEAD}{field}{_SETTING}(?:{choice})?{value}{suffix}"),
    )


_PATTERNS = tuple(
    (kind, pattern)
    for kind, values, *grammar in _FAMILIES
    for pattern in _family_patterns(values, *grammar)
) + (("airlines", re.compile(rf"{_LEAD}(?:出差{_TIME})?(?:还|也)?(?:常坐|常乘坐|经常坐|经常乘坐|经常搭乘)(?P<value>{_AIRLINES})(?:的?航班)?")),)

# Unknown values must themselves have a descriptive or domain-noun structure.
# Accepting arbitrary characters after 偏好 would swallow attached non-travel
# actions even when a blacklist does not happen to know that action's wording.
_HOTEL_FEATURE = r"安静|干净|整洁|卫生|舒适|宽敞|明亮|隔音好|经济型|商务型|连锁|(?:有|带)?独立卫生间|(?:靠近|临近)(?:地铁站?|车站|机场|市中心|高铁站)|(?:带|有)(?:早餐|健身房|停车场|浴缸)"
_HOTEL_DESCRIPTION = rf"(?:{_HOTEL_FEATURE})(?:(?:且|又|和|以及|、)?(?:{_HOTEL_FEATURE}))*(?:的)?(?:酒店|客房|房间|住宿)?"
_HOTEL_NAME = r"[\u4e00-\u9fffA-Za-z0-9·-]{2,20}(?:酒店|旅馆|宾馆|民宿|客栈)"
_MEAL_FEATURE = r"少油|少盐|少糖|低盐|低油|低糖|清淡|素食|清真|高蛋白|无糖|无乳糖|无麸质|无花生"
_ROUTE_VALUES = {
    "hotel_brands": rf"{_HOTEL_DESCRIPTION}|{_HOTEL_NAME}",
    "airlines": r"[\u4e00-\u9fffA-Za-z0-9·-]{2,20}(?:航空公司|航空|航司)",
    "seat_preference": r"商务舱|经济舱|头等舱|(?:前排|后排|过道边|窗边|腿部空间大)(?:的)?(?:座位|位置)?",
    "transportation_preference": r"机场接送服务|接送机服务|(?:打|使用)(?:网约车|出租车)(?:出行|通勤|出门)?",
    "meal_preference": rf"(?:{_MEAL_FEATURE})(?:(?:且|和|及|、)?(?:{_MEAL_FEATURE}))*(?:的)?(?:饮食|餐食|饭菜|食物)?",
}
_ROUTE_PATTERNS = tuple(
    pattern
    for kind, values, *grammar in _FAMILIES
    for pattern in (
        *_family_patterns(_ROUTE_VALUES[kind], *grammar, require_context=True),
        *_family_patterns(rf"(?:{values})(?:(?:和|与|及|以及|、)(?:{values}))+", *grammar),
    )
) + (re.compile(rf"{_LEAD}{_STATE}(?:住|入住)(?P<value>{_HOTEL_NAME})"),)
_ROUTE_OTHER = re.compile(
    r"去|到|在|前往|抵达|今天|明天|后天|今晚|这次|本次|临时|下周|下月|下次|再|给|安排|记录|办理|支付|"
    r"比较|对比|找|看看|考虑|还是|或者|或是|能|可以|并|而且|同时|接着|随后|接下来|顺带|排序|"
    r"今年|本周|本月|周末|上午|下午|晚上|早上|明早|今早|(?:周|星期|礼拜)[一二三四五六七日天]|"
    r"[0-9零〇一二三四五六七八九十百两]+(?:年|月|日|号|点|天|周|晚|夜)|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
)


def _statement_parts(query):
    q = query.strip().strip("。.!！ ")
    q = _SAVE_PREFIX.sub("", q)
    q = re.sub(r"(另外|此外|同时)[，,:： ]+(?=我)", r"\1", q)
    if not q or _UNSAFE.search(q) or _UNCERTAIN.search(q) or _EXTRA_ACTION.search(q):
        return None
    parts = [part.strip() for part in _CLAUSE_SPLIT.split(q)]
    return parts if all(parts) else None


def parse_preference(query: str):
    """Extract only closed-vocabulary positive statements, never partial tasks."""
    parts = _statement_parts(query)
    if not parts:
        return None
    preferences = []
    for part in parts:
        action = "replace" if _REPLACE.search(part) else "append" if _APPEND.search(part) else "replace"
        for pref_type, pattern in _PATTERNS + (("home_location", _HOME),):
            match = pattern.fullmatch(part)
            if not match:
                continue
            value = match.group("value")
            if pref_type == "home_location" and _ADDRESS_OTHER.search(value):
                return None
            if pref_type == "home_location":
                action = "replace"
            if pref_type == "meal_preference" and value == "素":
                value = "素食"
            if any(item["type"] == pref_type for item in preferences) and not _REPLACE.search(part):
                action = "append"
            preferences.append({"type": pref_type, "value": value, "action": action})
            break
        else:
            return None
    return {"has_preferences": True, "preferences": preferences, "answer": "偏好已更新", "proactive_question": "", "execution_path": "local_rules"}


def explicitly_remembers_preference(query: str) -> bool:
    return bool(_SAVE_PREFIX.match(query.strip()))


def can_route_preference_statement(query: str) -> bool:
    """Route clear preference-only statements without claiming extracted values.

    True does not authorize a memory write: callers must still execute the
    preference skill, which either uses parse_preference or its own model.
    """
    if parse_preference(query):
        return True
    parts = _statement_parts(query)
    if not parts:
        return False
    for part in parts:
        if parse_preference(part):
            continue
        if home := _HOME_CANDIDATE.fullmatch(part):
            value = home.group("value")
            if _ADDRESS_OTHER.search(value) or not _UNKNOWN_ADDRESS.fullmatch(value):
                return False
            if sum(city in value for city in _HOME_CITIES.split("|")) > 1:
                return False
            continue
        if _ROUTE_OTHER.search(part) or not any(pattern.fullmatch(part) for pattern in _ROUTE_PATTERNS):
            return False
    return True
