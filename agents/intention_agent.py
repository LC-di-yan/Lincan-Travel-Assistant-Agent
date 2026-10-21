"""
意图识别智能体 IntentionRecognitionAgent
职责：准确识别用户意图，并进行智能体调度

核心功能：
1. 多意图识别和分类：融合上下文对模糊意图进行消歧
2. 智能体调度决策：基于预定义的触发条件和业务规则，根据识别结果决定调用哪些子智能体
3. Query改写：标准化用户口语化的query输入，补全上下文信息，提取和重组关键信息
4. 显示推理：输出的两段式结构（推理过程 + JSON决策），提升意图识别准确度

架构：
- 使用单一LLM（用户配置的模型）
- 输入：用户query（自然语言）
- 输出：推理过程生成（包含reasoning+原因） + 多意图识别（原因） + 智能Query改写 + 构建结构化决策
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import asyncio
import json
import logging
import random
import re
import traceback
from config import SCENARIO_TOKENS
from utils.skill_loader import SkillLoader
from utils.llm_response import extract_llm_json, extract_llm_text
from cache.decorators import cached

logger = logging.getLogger(__name__)


def _intention_cache_key(x) -> str:
    """
    意图识别缓存键必须包含完整上下文。
    只取最后一条 user 消息会导致省略追问（如"上海呢"）命中无上下文时的旧缓存，
    从而错误地复用 information_query 等结果。
    """
    if isinstance(x, list):
        return json.dumps(
            [
                {"role": getattr(m, "role", ""), "content": getattr(m, "content", "")[:200]}
                for m in x
            ],
            ensure_ascii=False,
        )
    return x.content if hasattr(x, "content") else str(x)


# ── 快速路由规则 ──────────────────────────────────────────
# 高置信度模式，命中后跳过 LLM 意图识别
_EXPENSE_PATTERNS = [
    re.compile(r"记[一]?[笔]?\s*(.+?)\s*(\d+(?:\.\d+)?)\s*[元块钱]"),
    re.compile(r"[花用]了?\s*(\d+(?:\.\d+)?)\s*[元块钱]\s*(.*)"),
    re.compile(r"[花用]了?\s*(\d+(?:\.\d+)?)"),
    re.compile(r"(打车|餐[饮费]|吃饭|住宿|机票|火车票|地铁|公交|加油|停车|通讯|快递|办公)[费花]?\s*(\d+(?:\.\d+)?)"),
    re.compile(r"支出\s*(\d+(?:\.\d+)?)"),
    re.compile(r"报销\s*(.+?)\s*(\d+(?:\.\d+)?)\s*[元块钱]?"),
]

_WEATHER_PATTERNS = [
    re.compile(r"(.{2,8}?)的?天气"),
    re.compile(r"[今明后][天日].*?天气"),
    re.compile(r"天气[怎么样如何]"),
]

# 住宿类关键词（酒店/民宿/旅馆/客栈/青旅/招待所/住的地方/落脚/下榻）
_HOTEL_KEYWORDS = r"酒店|民宿|宾馆|旅馆|客栈|青旅|青年旅舍|招待所|住宿|住的地方|住哪儿|哪儿住|睡的?地方|落脚|下榻|歇脚|安顿|过夜|睡觉|投宿|借宿|旅店|旅舍|公寓酒店|度假村"

# 政策/标准类问题信号：命中时不能当酒店/景点搜索
# 反例：「国际差旅住宿标准」曾命中 hotel 正则，又从历史里抽到"西安"当目的地，
# 结果把政策咨询做成了西安酒店搜索。
# 2026-10-22 补充：协议/优惠/折扣/差标/审批 也属于政策咨询
# 反例：「请帮我查协议酒店优惠」被当成酒店搜索，返回 600+ 家酒店。
_POLICY_QUERY = re.compile(
    r"标准|政策|规定|制度|报销|额度|上限|补贴|补助|办法|条款|规范|流程|协议|优惠|折扣|差标|审批"
)

_HOTEL_PATTERNS = [
    # "北京有哪些酒店" / "上海有没有住的地方"
    re.compile(rf"(.{{2,6}})[的有]?(?:哪些|什么|哪家|哪[些家]|有没有|有没).*?(?:{_HOTEL_KEYWORDS})"),
    # "找一下上海的民宿" / "搜北京宾馆"
    re.compile(rf"(?:找[一]?下?|查[一]?下?|搜[一]?[下索]?).{{0,6}}(.{{2,6}}).*?(?:{_HOTEL_KEYWORDS})"),
    # "帮我找民宿" / "推荐酒店" / "看看宾馆"
    re.compile(rf"(?:帮我找|帮我查|搜索|推荐|[看瞧]看?).*?(?:{_HOTEL_KEYWORDS})"),
    # "住宿推荐" / "酒店搜索"
    re.compile(rf"(?:{_HOTEL_KEYWORDS}).*?(?:推荐|搜索|查询|在[哪那]|怎么样)"),
    # "XX附近/周边/旁边的住宿" —— 必须含空间修饰词，避免"他住的地方离公司很远"误命中
    re.compile(rf"(.{{2,8}}?).*?(?:附近|周边|旁边).*?(?:{_HOTEL_KEYWORDS})"),
    # 删除原"倒装"和"哪里住"两条过宽模式：
    #   (?:{_HOTEL_KEYWORDS}).*?(.{2,8}?) 与 (?:住|住宿|...).*?(?:哪里|哪儿|...)
    # 这两条是 BUG-008/009/010 的主因（纯关键词命中叙述句）
]

# 餐饮类关键词（餐厅/饭店/小吃/好吃/吃的/吃饭的地方/觅食/下馆子/宵夜/大餐/菜系）
_RESTAURANT_KEYWORDS = r"餐厅|饭店|饭馆|餐馆|小吃|美食|好吃[的]?|特色菜|吃[的饭]|吃饭|聚餐|觅食|下馆子|填[饱]?肚子|搓[一]?顿|大餐|宵夜|夜宵|午餐|晚餐|早饭|午饭|晚饭|早餐|中餐|快餐|大排档|麻辣烫|自助餐|早茶|点心|面馆|粉店|粥[店铺]|食府|酒[楼家]"
_CUISINE_KEYWORDS = r"川菜|粤菜|湘菜|火锅|日料|韩餐|西餐|烧烤|海鲜|烤鸭|串串|本帮菜|农家菜|私房菜|土菜|西北菜|东北菜|泰国菜|越南菜|印度菜|日本料理|韩国料理"

_RESTAURANT_PATTERNS = [
    # "有啥好吃的" / "有什么好吃的" / "有什么好吃的推荐"
    re.compile(rf"有(啥|什么|哪些).*?(?:好吃[的]?|{_RESTAURANT_KEYWORDS}|{_CUISINE_KEYWORDS})"),
    # "北京有哪些好吃的" / "上海有没有好吃的"
    re.compile(rf"(.{{2,6}})[的有]?(?:哪些|什么|啥|哪家|哪[些家]|有没有|有没).*?(?:好吃[的]?|{_RESTAURANT_KEYWORDS}|{_CUISINE_KEYWORDS})"),
    # "找上海餐厅" / "搜北京火锅"
    re.compile(rf"(?:找[一]?下?|查[一]?下?|搜[一]?[下索]?).{{0,6}}(.{{2,6}}).*?(?:{_RESTAURANT_KEYWORDS}|{_CUISINE_KEYWORDS})"),
    # "帮我找好吃的" / "推荐美食" / "看看餐厅"
    re.compile(rf"(?:帮我找|帮我查|搜索|推荐|[看瞧]看?).*?(?:好吃[的]?|{_RESTAURANT_KEYWORDS}|{_CUISINE_KEYWORDS})"),
    # "美食推荐" / "餐厅搜索"
    re.compile(rf"(?:{_RESTAURANT_KEYWORDS}|{_CUISINE_KEYWORDS}).*?(?:推荐|搜索|查询|在[哪那]|怎么样)"),
    # "XX附近/周边/旁边的川菜/火锅" —— 必须含空间修饰词，避免"昨晚吃了一顿大餐"误命中
    re.compile(rf"(.{{2,8}}?).*?(?:附近|周边|旁边).*?(?:{_CUISINE_KEYWORDS}|{_RESTAURANT_KEYWORDS})"),
    # "哪里有好吃的" / "去哪吃" / "哪里吃饭" / "在哪儿觅食"
    re.compile(r"(?:吃[饭]?|聚餐|觅食|下馆子|搓一顿|填肚子|夜宵|宵夜).*?(?:哪里|哪儿|什么地方|去哪|在[哪那])|(?:哪里|哪儿|什么地方).*?(?:吃[饭]?|聚餐|觅食|下馆子|搓一顿|夜宵|宵夜)"),
    # "有什么好吃的" / "有啥好吃的" / "有什么特色"
    re.compile(r"有(?:什么|啥|哪些).*?(?:好吃[的]?|美食|特色|推荐|招牌)"),
    # 删除原"倒装"模式：({_CUISINE_KEYWORDS}).*?(.{2,8}?)
    # 该条是 BUG-009 的主因（纯关键词命中叙述句）
]

# 景点类关键词（景点/景区/公园/好玩的地方/打卡/游玩/逛/风景/名胜/出游/散心）
# 注意：已移除"旅游"——"A到B旅游"应走 LLM 识别为 itinerary_planning，由 _TRIP_SIGNAL_PATTERNS 兜底
_SCENIC_KEYWORDS = r"景点|景区|公园|乐园|好玩[的]?|游玩|逛逛|逛[一]?逛|必去|打卡|名胜|风景|出游|散心|观光|游览|踏青|登山|滑雪|漂流|徒步|看海|赏花|泡温泉|名胜古迹|网红[打]?卡|拍照[打]?卡"
_SCENIC_PLACE_KEYWORDS = r"风景区|名胜区|自然保护[区]?|森林公园|海洋公园|主题公园|博物馆|纪念馆|美术馆|科技馆|水族馆|海洋馆|动物园|植物园|古镇|古城|故居|园林|寺庙|教堂|清真寺|长城|峡谷|瀑布|温泉|海滩|海岛|步行街|老街|夜市[街]?|小吃街|迪士尼|环球影城|兵马俑"

_SCENIC_PATTERNS = [
    # "有啥好玩的" / "有什么景点"
    re.compile(rf"有(啥|什么|哪些).*?(?:好玩[的]?|{_SCENIC_KEYWORDS}|{_SCENIC_PLACE_KEYWORDS})"),
    # "北京有哪些好玩的" / "上海有没有景点"
    re.compile(rf"(.{{2,6}})[的有]?(?:哪些|什么|啥|哪家|哪[些家]|有没有|有没).*?(?:好玩[的]?|{_SCENIC_KEYWORDS}|{_SCENIC_PLACE_KEYWORDS})"),
    # "找北京景点" / "搜上海公园"
    re.compile(rf"(?:找[一]?下?|查[一]?下?|搜[一]?[下索]?).{{0,6}}(.{{2,6}}).*?(?:{_SCENIC_KEYWORDS}|{_SCENIC_PLACE_KEYWORDS})"),
    # "帮我找好玩的" / "推荐景点" / "看看打卡地"
    re.compile(rf"(?:帮我找|帮我查|搜索|推荐|[看瞧]看?).*?(?:好玩[的]?|{_SCENIC_KEYWORDS}|{_SCENIC_PLACE_KEYWORDS})"),
    # "景点推荐" / "公园搜索"
    re.compile(rf"(?:{_SCENIC_KEYWORDS}|{_SCENIC_PLACE_KEYWORDS}).*?(?:推荐|搜索|查询|在[哪那]|怎么样)"),
    # "XX附近/周边/旁边的景点" —— 必须含空间修饰词，避免"我们去逛逛街吧"误命中
    re.compile(rf"(.{{2,8}}?).*?(?:附近|周边|旁边).*?(?:{_SCENIC_PLACE_KEYWORDS}|{_SCENIC_KEYWORDS})"),
    # "哪里好玩" / "去哪玩" / "去哪儿逛" / "哪儿值得去"
    re.compile(r"(?:玩[一]?[下会]?|逛逛|逛[一]?逛|逛|游玩|出游|散心|观光|打卡|踏青|登山|滑雪|漂流|徒步|看海|赏花).*?(?:哪里|哪儿|什么地方|去哪|去哪[儿里]|在[哪那]|推荐|值得[去]?)"
               r"|(?:哪里|哪儿|什么地方|去哪[儿里]?).*?(?:好玩[的]?|玩[一]?[下会]?|逛逛|逛[一]?逛|逛|游玩|出游|散心|观光|打卡|踏青|登山)"),
    # "有什么好玩的" / "有啥景点" / "有哪里值得去"
    re.compile(r"有(?:什么|啥|哪些|哪里|哪儿).*?(?:好玩[的]?|景点|景区|公园|打卡|风景|名胜)"),
    # 删除原"倒装"模式：({_SCENIC_PLACE_KEYWORDS}).*?(.{2,8}?)
    # 该条是 BUG-010 的主因（纯关键词命中叙述句）
]

_CURRENCY_PATTERNS = [
    re.compile(r"(\d+(?:\.\d+)?)\s*([美元人民币日元欧元英镑港币韩元])\s*[兑换换比]\s*([美元人民币日元欧元英镑港币韩元])"),
    re.compile(r"([美元人民币日元欧元英镑港币韩元])[兑换换].*?([美元人民币日元欧元英镑港币韩元])"),
    re.compile(r"汇率"),
]

# 货币中文 → 代码
_CURRENCY_CODE = {
    "人民币": "CNY", "元": "CNY", "块": "CNY",
    "美元": "USD", "美金": "USD", "刀": "USD",
    "欧元": "EUR", "英镑": "GBP", "日元": "JPY",
    "韩元": "KRW", "港币": "HKD", "港元": "HKD",
    "新台币": "TWD", "台币": "TWD",
    "新加坡元": "SGD", "新币": "SGD",
    "泰铢": "THB", "澳元": "AUD", "加元": "CAD",
}

# 货币中文关键词按长度降序（避免"元"先匹配"美元"中的"元"）
_CURRENCY_WORDS = sorted(_CURRENCY_CODE.keys(), key=len, reverse=True)


def _extract_currency(q: str) -> Optional[dict]:
    """用正则从查询中提取货币信息，跳过 LLM 调用。返回 None 表示需要 LLM。"""
    # 模式1: "100美元多少人民币" / "100美元换人民币"
    m = re.search(r"(\d+(?:\.\d+)?)\s*([^\d\s]+?)\s*(?:多少|换|兑|兑换|换算|等于|是|转)\s*(?:多少|几)?\s*([^\d\s]+)", q)
    if m:
        amount = float(m.group(1))
        currencies = re.findall(r"|".join(_CURRENCY_WORDS), q)
        codes = list(dict.fromkeys(_CURRENCY_CODE[w] for w in currencies))  # 去重保序
        if len(codes) >= 2:
            return {"from_currency": codes[0], "to_currency": codes[1], "amount": amount}

    # 模式2: "美元兑人民币" / "日元汇率" (纯汇率，无金额)
    m = re.search(r"([^\d\s]+?)\s*(?:兑|兑换|换|汇率)\s*([^\d\s]+)", q)
    if m:
        currencies = re.findall(r"|".join(_CURRENCY_WORDS), q)
        codes = list(dict.fromkeys(_CURRENCY_CODE[w] for w in currencies))
        if len(codes) >= 2:
            return {"from_currency": codes[0], "to_currency": codes[1], "amount": 1}

    # 模式3: "汇率" 单关键词 + "日元" → 日元兑人民币
    m = re.search(r"|".join(_CURRENCY_WORDS), q)
    if m and "汇率" in q:
        return {"from_currency": _CURRENCY_CODE[m.group(0)], "to_currency": "CNY", "amount": 1}

    return None

# 翻译语言白名单（中文/英文双向，覆盖常见语种）
# 修复 BUG-021/022/023/024：补全俄/西班牙/阿拉伯/葡萄牙/意大利/泰/越南等语种
_TRANSLATION_LANGS_CN = (r"英文|日文|韩文|法文|德文|中文|俄文|西班牙文|阿拉伯文|葡萄牙文|意大利文|泰文|越南文"
                         r"|英语|日语|韩语|法语|德语|俄语|西班牙语|阿拉伯语|葡萄牙语|意大利语|泰语|越南语")
_TRANSLATION_PATTERNS = [
    re.compile(rf"翻译[成用]({_TRANSLATION_LANGS_CN})"),
    re.compile(rf"用({_TRANSLATION_LANGS_CN})怎么说"),
    re.compile(r"translate.*?to\s+(english|chinese|japanese|korean|french|german|"
               r"russian|spanish|arabic|portuguese|italian|thai|vietnamese)", re.I),
]

# 节假日名 → 日期映射（农历节假日为占位，需动态计算；公历节假日固定）
# 修复 BUG-011：扩展日期捕获覆盖节假日名，命中后由 LLM 映射到具体日期
_HOLIDAY_DATES = {
    "元旦": "01-01",
    "清明": "04-05",
    "劳动节": "05-01",
    "国庆": "10-01",
    "国庆节": "10-01",
    "圣诞节": "12-25",
    # 农历节假日（占位，需根据年份动态计算）
    "春节": "02-10",
    "端午": "06-10",
    "中秋": "09-15",
}

# 扩展日期捕获：下周X / 这周X / 月底 / 月初 / 节假日名
# 注意：仅作为模块级常量；_fast_match 内的日期提取（约 479 行）由其他窗口协同修改
_DATE_PATTERN_EXTENDED = re.compile(
    r"(今天|明天|后天|大后天|"
    r"下[一二三四五六日天]|这[一二三四五六日天]|"
    r"\d{1,2}月\d{1,2}[日号]|"
    r"\d{4}-\d{1,2}-\d{1,2}|"
    r"月底|月初|"
    r"元旦|春节|清明|劳动节|端午|中秋|国庆节?|圣诞节)"
)

_TRAIN_PATTERNS = [
    re.compile(r"(?:明天|后天|今天)?([一-龥]{2,4}?)\s*[到至去往]\s*([一-龥]{2,4}?)\s*的?\s*(?:火车|高铁|动车|列车|票)"),
    re.compile(r"(查|搜|看).*?(?:明天|后天|今天)?([一-龥]{2,4}?)\s*[到至去往]\s*([一-龥]{2,4}?)\s*的?\s*(?:火车|高铁|动车)"),
    re.compile(r"(火车票|高铁|动车|列车|12306).*?(?:明天|后天|今天)?([一-龥]{2,4}?)\s*[到至去往]\s*([一-龥]{2,4}?)"),
    re.compile(r"(?:明天|后天|今天)?([一-龥]{2,4}?)\s*到\s*([一-龥]{2,4}?).*?(票|车次|班次)"),
    re.compile(r"([GDCZTK]\d+).*?(经停|停靠|站点|路线)"),
    re.compile(r"(换乘|转车|中转).*?(?:明天|后天|今天)?([一-龥]{2,4}?)\s*[到至]\s*([一-龥]{2,4}?)"),
    re.compile(r"余票|有票|没票"),
]

_MEMORY_PATTERNS = [
    # "我去过哪些地方" / "我去过哪儿" —— "去过" + 疑问词（MF-005 基线）
    re.compile(r"我去过(?:哪些|哪里|什么地方|哪儿)"),
    # "我去过XX吗" —— 询问是否去过（MF-002 基线，疑问句）
    re.compile(r"我去过.{0,8}[吗?？]"),
    # "记得上次去XX的时候" —— 回忆历史（MF-004 基线）
    re.compile(r"记得.{0,6}上次|上次.{0,8}的?时候"),
    # 必须含查询动词 + 历史/记录类词
    re.compile(r"(查询?|看看?|查看|显示|汇总|总结)\s*(差旅|旅行|出行|旅游|行程|出差)\s*(记录|历史|情况|汇总|总结)"),
    # "查询我去过的地方" / "看看我的旅行记录"
    re.compile(r"(查询?|看看?|查看|显示).{0,6}(去过|旅行|差旅|出行|行程)"),
    # "历史/以往/过去" + "行程/旅行/差旅/出行/记录"
    re.compile(r"(历史|以往|过去).{0,4}(行程|旅行|差旅|出行|记录)"),
    # "查/看 + 历史记录/出行记录/..."
    re.compile(r"(查|看|看看|显示|查看).{0,4}(历史记录|出行记录|行程记录|旅行记录|差旅记录|去过哪)"),
    # 删除原过宽模式：(我去过|去过|去过哪些|...) —— BUG-018 主因
    # 删除原过宽模式：(我的?|以前|上次).*?(...|去过) —— 误命中"去年去过北京今年还想去"
]

# ── 差旅信号检测（用于 fast route 顶部短路，强制走 LLM） ──
# 命中任一即视为差旅/行程规划场景，不进 fast route
_TRIP_SIGNAL_PATTERNS = [
    re.compile(r"出差"),                    # 明确出差
    re.compile(r"\d+\s*天[的行程]?"),       # "3天" / "3天的行程" / "3天行程"
    re.compile(r"\d+\s*[日天][以之内]?[前后上]"),  # "3天以内" / "3天上"
    re.compile(r"[开见谈]会"),              # 开会/见客户/谈判
    re.compile(r"行程"),                    # 行程规划
    re.compile(r"安排[一二三四五六七八九两]?\s*[天下周]"),  # 安排一下/安排三天
    re.compile(r"规划[一行]?下?"),          # 规划/规划一下/规划行程
    re.compile(r"攻略"),                    # 旅游攻略
    re.compile(r"旅游\d+\s*天"),            # 旅游5天
    re.compile(r"探亲"),
    re.compile(r"度[假蜜月]"),              # 度假/度蜜月
]


def _has_trip_signal(query: str) -> bool:
    """检测查询是否含差旅/行程规划信号。"""
    return any(p.search(query) for p in _TRIP_SIGNAL_PATTERNS)


_TRIP_PAIR_CACHE = {}


def _match_trip_pair(q: str) -> Optional[dict]:
    """匹配「从A去/到B + N天」这种可判定的差旅骨架，命中则免掉一次 LLM 意图识别。"""
    if not q:
        return None
    pat = _TRIP_PAIR_CACHE.get("re")
    if pat is None:
        alt = "|".join(sorted(_EXTENDED_GEO_NAMES, key=len, reverse=True))
        pat = re.compile(
            rf"(?P<origin>{alt})\s*(?:去|到|飞往|飞|前往|出差到)\s*(?P<dest>{alt})"
            rf"[^\d]{{0,8}}?(?P<days>\d{{1,2}})\s*天"
        )
        _TRIP_PAIR_CACHE["re"] = pat
    m = pat.search(q)
    if not m:
        return None
    origin, dest = m.group("origin"), m.group("dest")
    try:
        days = int(m.group("days"))
    except (TypeError, ValueError):
        return None
    if origin == dest or not (1 <= days <= 30):
        return None
    return {
        "reasoning": f"规则匹配: {origin}→{dest} {days}天差旅",
        "intents": [{
            "type": "itinerary_planning",
            "confidence": 0.95,
            "description": f"{origin}到{dest}{days}天行程",
            "reason": "出发地、目的地、天数均已明确",
        }],
        "key_entities": {"origin": origin, "destination": dest, "duration_days": days},
        "fast_event": {
            "origin": origin, "destination": dest, "start_date": "", "end_date": "",
            "duration_days": days, "trip_purpose": "", "missing_info": [],
        },
        "rewritten_query": q,
        "needs_clarification": False,
        "clarification_question": "",
        "agent_schedule": [{
            "agent_name": "itinerary_planning",
            "priority": 1,
            "reason": "规划行程",
            "expected_output": "行程计划",
        }],
    }


# ── 多意图关键词检测（供天气/酒店/餐厅/景点分支复用） ──
_HOTEL_WORDS = ["住宿", "酒店", "宾馆", "民宿", "旅馆", "青旅", "客栈", "招待所"]
_RESTAURANT_WORDS = ["美食", "好吃", "餐厅", "餐馆", "饭店", "饭馆", "小吃", "火锅",
                     "川菜", "粤菜", "湘菜", "日料", "韩餐", "西餐", "烧烤", "海鲜"]
_SCENIC_WORDS = ["景点", "景区", "公园", "好玩", "旅游", "打卡", "名胜", "风景"]


def _detect_secondary_intents(q: str, primary: str) -> list:
    """
    检测查询中除主意图外的次要意图，返回 [(agent_name, reason, expected_output, intent_type, description), ...]。
    primary: 'hotel_search' / 'restaurant_search' / 'scenic_search' / 'information_query'
    """
    secondary = []
    if primary != "hotel_search" and any(w in q for w in _HOTEL_WORDS):
        secondary.append(("hotel_search", "查住宿", "酒店列表", "hotel_search", "酒店搜索"))
    if primary != "restaurant_search" and any(w in q for w in _RESTAURANT_WORDS):
        secondary.append(("restaurant_search", "查美食", "餐厅列表", "restaurant_search", "餐厅搜索"))
    if primary != "scenic_search" and any(w in q for w in _SCENIC_WORDS):
        secondary.append(("scenic_search", "查景点", "景点列表", "scenic_search", "景点搜索"))
    return secondary


def _city_from_history(dialogue_history: list) -> str:
    """
    从对话历史中提取最近出现的城市名（用于追问时回填 destination）。

    三层策略（按优先级）：
    1. 结构化提取：匹配 assistant 摘要里的「目的地：X」「目的地: X」
       - server/utils/assistant_summary.py 生成的摘要都含此字段，最可靠
    2. user 消息的「去/到/往/前往 X」模式提取
       - 第一轮 user 消息常用，X 必须是 _CITY_KEYWORDS
    3. 兜底 rfind：在所有历史里找最后出现的 _CITY_KEYWORDS 城市
       - 排除后面接"路/广场/寺/场/站"等后缀的污染匹配（如"南京路"→南京）

    返回 "" 表示未找到。
    """
    if not dialogue_history:
        return ""

    import re

    # 层 1：结构化「目的地：X」
    _DEST_RE = re.compile(r'目的地[：:]\s*([一-龥]{2,6})')
    for item in reversed(dialogue_history):
        m = _DEST_RE.search(item)
        if m:
            city = m.group(1).strip()
            # 去掉可能粘连的后缀（如"上海，"→"上海"）
            for suffix in "，,。；;、的":
                if city.endswith(suffix):
                    city = city[:-1]
            if city in _CITY_KEYWORDS:
                return city
            # 可能是 _EXTENDED_GEO_NAMES 里的扩展地名
            if city in _EXTENDED_GEO_NAMES:
                return city

    # 层 2：user 消息的「去/到/往/前往 X」
    _GO_RE = re.compile(r'(?:去|到|往|前往|飞往|出发去)\s*([一-龥]{2,4})')
    for item in reversed(dialogue_history):
        if not item.startswith("用户:"):
            continue
        m = _GO_RE.search(item)
        if m:
            city = m.group(1).strip()
            if city in _CITY_KEYWORDS:
                return city

    # 层 3：rfind 兜底，排除"南京路"等被污染的子串
    # 城市名后接这些字时视为商圈/地标，不是城市
    _GEO_SUFFIX_NOISE = set("路广场寺场站街区镇村县")
    def _last_match(text: str, names) -> str:
        last_city = ""
        last_pos = -1
        for c in names:
            pos = text.rfind(c)
            while pos != -1:
                # 检查城市名后是否接"路/广场"等污染后缀
                after = text[pos + len(c): pos + len(c) + 1]
                if after in _GEO_SUFFIX_NOISE:
                    # 这次匹配是商圈/地标，往前找
                    pos = text.rfind(c, 0, pos)
                    continue
                if pos > last_pos:
                    last_pos = pos
                    last_city = c
                break
            # while 结束后：要么 pos==-1（无合法匹配），要么已记录
            if pos == -1:
                # 全部匹配都被后缀污染了，继续下一个城市
                # 但 last_city 可能已记录其他城市的合法匹配
                pass
        return last_city

    for item in reversed(dialogue_history):
        city = _last_match(item, _CITY_KEYWORDS)
        if city:
            return city
    # 回退：扩展地理词库（地标群/商圈等，如"虹桥""外滩"）
    for item in reversed(dialogue_history):
        city = _last_match(
            item,
            [c for c in _EXTENDED_GEO_NAMES if c != "大学城"]  # 排除泛称
        )
        if city:
            return city
    return ""


# 城市关键词（模块级，供快速路由和天气/酒店检测共用）
_CITY_KEYWORDS = {"北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "苏州",
                  "天津", "重庆", "厦门", "青岛", "大连", "宁波", "无锡", "长沙", "郑州", "济南",
                  "哈尔滨", "沈阳", "昆明", "合肥", "福州", "石家庄", "南昌", "贵阳", "太原", "南宁",
                  "拉萨", "乌鲁木齐", "呼和浩特", "银川", "西宁", "兰州", "海口", "三亚", "珠海",
                  "嘉兴", "丽江", "大理", "桂林", "洛阳", "威海", "烟台", "温州", "绍兴", "徐州"}
# 移除：虹桥, 南站, 北站, 东站, 西站（这些是火车站/区域名，非城市）
# 新增地级市/旅游城市：嘉兴, 丽江, 大理, 桂林, 洛阳, 威海, 烟台, 温州, 绍兴, 徐州
_NON_CITY = {"查", "搜", "看", "火车", "高铁", "动车", "列车", "票", "经停", "停靠", "站点", "路线",
             "换乘", "转车", "中转", "余票", "有票", "没票", "车次", "班次", "明天", "后天", "今天",
             "下周", "这周", "周一", "周二", "周三", "周四", "周五", "周六", "周日"}

# 扩展地理名词库（供 _resolve_elliptical 消解省略追问，比 _CITY_KEYWORDS 更宽）
# 含地级市、县级市、知名旅游地、商圈、地标群
_EXTENDED_GEO_NAMES = _CITY_KEYWORDS | {
    # 地级市
    "佛山", "东莞", "惠州", "中山", "江门", "肇庆", "潮州", "揭阳", "汕尾", "梅州",
    "常州", "南通", "镇江", "泰州", "盐城", "淮安", "连云港", "宿迁", "湖州", "金华",
    "衢州", "舟山", "台州", "丽水", "芜湖", "潍坊", "临沂", "淄博", "济宁", "泰安",
    "泉州", "漳州", "龙岩", "三明", "莆田", "宁德", "南平", "宜昌", "襄阳", "荆州",
    "绵阳", "德阳", "宜宾", "南充", "泸州", "遵义", "曲靖", "玉溪", "长春", "吉林",
    "鞍山", "锦州", "咸阳", "宝鸡", "榆林", "柳州", "北海", "防城港", "儋州", "琼海",
    "包头", "鄂尔多斯", "赤峰", "九江", "景德镇", "岳阳", "延安", "秦皇岛", "承德",
    # 知名旅游地/县级市
    "香格里拉", "西双版纳", "九寨沟", "峨眉山", "张家界", "凤凰", "黄山", "敦煌",
    "平遥", "乌镇", "周庄", "西塘", "同里", "南浔", "阳朔", "德清", "安吉",
    # 上海/北京等大城市的区与地标群（用于"那浦东呢/那虹桥呢"消解）
    "浦东", "浦西", "虹桥", "陆家嘴", "徐家汇", "静安", "黄浦", "长宁", "杨浦",
    "海淀", "朝阳", "丰台", "通州", "顺义", "昌平", "大兴",
    "浦东新区", "滨海新区", "两江新区",
    # 大学的泛称（"那大学城呢"）
    "大学城",
}


def _resolve_elliptical(query: str, dialogue: list) -> Optional[dict]:
    """
    检测省略追问（"福州的呢"、"那上海呢"）并从对话历史推断意图。
    返回 None 表示不是省略追问，返回 dict 表示已解析。
    """
    q = query.strip().rstrip("？?")
    m = re.match(r"^(?:那)?(.{2,6})的?呢$", q)
    if not m:
        return None
    city = m.group(1).strip()
    # 改用扩展地理词库，覆盖地级市/旅游地/商圈/地标群
    if city not in _EXTENDED_GEO_NAMES:
        return None

    # 从最近一轮助手回复中推断意图类型
    _INTENT_SIGNATURES = [
        ("scenic_search", ["景点", "attractions", "scenic_search", "景区", "公园"]),
        ("restaurant_search", ["美食", "restaurants", "restaurant_search", "好吃", "餐厅", "火锅"]),
        ("hotel_search", ["酒店", "hotels", "hotel_search", "住宿", "民宿", "宾馆"]),
    ]
    last_intent = None
    for item in reversed(dialogue):
        if item.startswith("助手:"):
            for intent_type, keywords in _INTENT_SIGNATURES:
                if any(kw in item for kw in keywords):
                    last_intent = intent_type
                    break
        if last_intent:
            break

    if not last_intent:
        return None

    intent_labels = {
        "scenic_search": ("景点搜索", "搜景点", "景点列表", "景点"),
        "restaurant_search": ("餐厅搜索", "搜餐厅", "餐厅列表", "美食"),
        "hotel_search": ("酒店搜索", "搜酒店", "酒店列表", "酒店"),
    }
    label, reason, output, keyword = intent_labels[last_intent]
    return {
        "reasoning": f"上下文消解: 省略追问→{city}{label}",
        "intents": [{"type": last_intent, "confidence": 0.92, "description": label, "reason": "从对话历史推断省略追问"}],
        "key_entities": {"destination": city},
        "rewritten_query": f"{city}{keyword}",
        "agent_schedule": [{"agent_name": last_intent, "priority": 1, "reason": reason, "expected_output": output}],
    }


# 位置指示词（近称/远称/本地称）：需要从上文提取焦点城市来补全
_DEIXIS_TERMS = ("附近", "周边", "旁边", "那里", "那边", "当地", "本地")


def _contains_explicit_city(q: str) -> bool:
    """判断 query 中是否包含明确的城市名（不含位置指示词本身）。"""
    for c in _CITY_KEYWORDS:
        if c in q:
            return True
    return False


def _resolve_deixis(query: str, dialogue_history: list = None) -> tuple:
    """
    消解位置指示词（"附近"、"那边"、"当地"等）。
    如果用户使用了位置指示词且没有显式指定其他城市，
    则尝试从对话历史中提取最近的城市，替换掉指示词，并返回焦点城市。

    返回 (resolved_query, focus_city)
    """
    q = query.strip()
    if not any(term in q for term in _DEIXIS_TERMS):
        return q, None

    # 如果用户已经明确指定了另一个城市，则尊重用户输入，不替换
    for c in _CITY_KEYWORDS:
        if c in q:
            return q, None

    focus_city = _city_from_history(dialogue_history or [])
    if not focus_city:
        return q, None

    for term in _DEIXIS_TERMS:
        if term in q:
            resolved = q.replace(term, focus_city, 1)
            return resolved, focus_city
    return q, focus_city


def _extract_train_entities(query: str):
    """
    从查询中稳健提取火车/高铁查询所需的城市对和日期。
    返回 (from_city, to_city, date_str) 或 None（提取不到两个城市）。
    """
    q = query
    # 日期：支持 7月31日、2026-07-31、明天/明早/今晚/后天 等口语
    date_match = re.search(
        r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}[日号]|大后天|今天|今日|今早|今晚|明天|明日|明早|明晚|后天|后早)",
        q,
    )
    date_str = date_match.group(1) if date_match else ""

    # 按出现顺序收集城市名，去重，取前两个
    positions = []
    for city in _CITY_KEYWORDS:
        start = 0
        while True:
            pos = q.find(city, start)
            if pos == -1:
                break
            positions.append((pos, city))
            start = pos + len(city)
    positions.sort()

    ordered = []
    for _, city in positions:
        if city not in ordered:
            ordered.append(city)
        if len(ordered) >= 2:
            break

    if len(ordered) < 2:
        return None

    return ordered[0], ordered[1], date_str


def _fast_match(query: str, dialogue_history: list = None) -> Optional[dict]:
    """
    规则快速路由器：尝试用正则匹配高置信度意图。
    返回 None 表示需要走 LLM，返回 dict 表示直接命中。
    当 dialogue_history 非空时，对缺少关键实体（城市等）的查询不快速路由，
    交给 LLM 利用对话历史补全上下文。
    """
    _has_history = bool(dialogue_history)
    q = query.strip()

    # ── 位置指示词消解（"附近" → 焦点城市）──
    resolved_q, focus_city = _resolve_deixis(q, dialogue_history or [])
    if resolved_q != q:
        q = resolved_q

    # ── 明确的差旅骨架「从A去/到B + N天」：规则直接出意图 ──
    # 这类查询原来每次都要等一次 5~12s 的 LLM 意图识别，而结果其实完全可判定
    _pair = _match_trip_pair(q)
    if _pair:
        return _pair

    # ── 差旅信号短路：含出差/行程/开会等信号强制走 LLM ──
    # 原因：fast route 命中单关键词（如'酒店'）会吞掉 itinerary_planning
    # 意图并丢失 fast_event，导致差旅信息无法写入长期记忆。
    if _has_trip_signal(q):
        return None

    # ── 政策/标准类问题：直接走知识库，不是找酒店 ──
    # 「上海住宿标准是多少」「协议酒店有什么优惠」这类问题问的是制度，不是具体商家。
    if _POLICY_QUERY.search(q) and re.search(_HOTEL_KEYWORDS, q):
        return {
            "reasoning": "规则匹配: 差旅政策/标准咨询",
            "intents": [{
                "type": "rag_knowledge",
                "confidence": 0.9,
                "description": "差旅政策/标准查询",
                "reason": "命中政策类关键词，走知识库而不是地点搜索",
            }],
            "key_entities": {},
            "rewritten_query": q,
            "agent_schedule": [{
                "agent_name": "rag_knowledge",
                "priority": 1,
                "reason": "查差旅政策/标准",
                "expected_output": "政策条款与标准",
            }],
        }

    # 记账
    _CATEGORY_MAP = {
        "打车": "交通", "地铁": "交通", "公交": "交通", "机票": "交通", "火车票": "交通", "加油": "交通", "停车": "交通",
        "餐": "餐饮", "饭": "餐饮", "午餐": "餐饮", "晚餐": "餐饮", "早餐": "餐饮", "吃饭": "餐饮", "吃面": "餐饮",
        "住宿": "住宿", "酒店": "住宿",
        "通讯": "通讯", "话费": "通讯",
        "快递": "办公", "办公": "办公",
    }
    for p in _EXPENSE_PATTERNS:
        m = p.search(q)
        if m:
            groups = m.groups()
            amount, desc = None, ""
            for g in groups:
                if g and re.match(r"^\d+(\.\d+)?$", g):
                    amount = float(g)
                elif g:
                    desc = g.strip()
            if amount:
                # 从描述中推断分类
                category = "其他"
                for keyword, cat in _CATEGORY_MAP.items():
                    if keyword in q:
                        category = cat
                        break
                return {
                    "reasoning": "规则匹配: 记账关键词",
                    "intents": [{"type": "expense_tracking", "confidence": 0.95, "description": "费用记录", "reason": "匹配记账模式"}],
                    "key_entities": {"other": f"{desc} {amount}元"},
                    "rewritten_query": q,
                    "agent_schedule": [{"agent_name": "expense_tracking", "priority": 1, "reason": "记账", "expected_output": "记录确认"}],
                    # 快速路由提取的参数，供 expense agent 直接使用
                    "fast_expense": {
                        "amount": amount,
                        "category": category,
                        "description": desc or q,
                    },
                }

    # 天气
    for p in _WEATHER_PATTERNS:
        m = p.search(q)
        if m:
            city = m.group(1).strip() if m.lastindex and m.group(1) else ""
            # 也提取城市从住宿关键词
            if not city:
                for hq in ["住宿", "酒店", "宾馆", "民宿", "旅馆", "青旅", "客栈"]:
                    if hq in q:
                        # 尝试从城市列表中提取
                        for c in _CITY_KEYWORDS:
                            if c in q:
                                city = c
                                break
                        break
            # 有对话历史但没提取到城市 → 交给 LLM 用历史补全
            if not city and _has_history:
                return None
            # 检测是否同时有酒店/住宿需求
            has_hotel = any(w in q for w in _HOTEL_WORDS)
            # 餐厅/美食关键词
            has_restaurant = any(w in q for w in _RESTAURANT_WORDS)
            # 景点关键词
            has_scenic = any(w in q for w in _SCENIC_WORDS)
            agent_schedule = [{"agent_name": "information_query", "priority": 1, "reason": "查天气", "expected_output": "天气信息"}]
            intents = [{"type": "information_query", "confidence": 0.9, "description": "天气查询", "reason": "匹配天气模式"}]
            # 已知限制：当查询含多个城市（如"北京天气和上海酒店"）时，
            # 仅提取首个城市，后续 hotel_search/restaurant_search 复用该城市。
            # 完整修复需重构城市提取为列表，属 _CITY_KEYWORDS 范畴。
            if has_hotel:
                agent_schedule.append({"agent_name": "hotel_search", "priority": 1, "reason": "查住宿", "expected_output": "酒店列表"})
                intents.append({"type": "hotel_search", "confidence": 0.85, "description": "酒店搜索", "reason": "查询含住宿关键词"})
            if has_restaurant:
                agent_schedule.append({"agent_name": "restaurant_search", "priority": 1, "reason": "查美食", "expected_output": "餐厅列表"})
                intents.append({"type": "restaurant_search", "confidence": 0.85, "description": "餐厅搜索", "reason": "查询含美食关键词"})
            if has_scenic:
                agent_schedule.append({"agent_name": "scenic_search", "priority": 1, "reason": "查景点", "expected_output": "景点列表"})
                intents.append({"type": "scenic_search", "confidence": 0.85, "description": "景点搜索", "reason": "查询含景点关键词"})
            return {
                "reasoning": "规则匹配: 天气查询" +
                             ("+酒店搜索" if has_hotel else "") +
                             ("+餐厅搜索" if has_restaurant else "") +
                             ("+景点搜索" if has_scenic else ""),
                "intents": intents,
                "key_entities": {"destination": city} if city else {},
                "rewritten_query": q,
                "agent_schedule": agent_schedule,
            }

    # 火车票/高铁/动车查询：稳健提取城市对和日期，避免日期前缀污染正则分组
    train_ticket_keywords = ["火车", "高铁", "动车", "列车", "12306", "车次", "班次", "余票", "有票", "没票", "查票", "订票", "抢票"]
    if any(k in q for k in train_ticket_keywords):
        train_entities = _extract_train_entities(q)
        if train_entities:
            from_city, to_city, date_str = train_entities
            # 同时检测酒店/餐厅/景点等次要意图
            secondary = _detect_secondary_intents(q, "train_ticket")
            agent_schedule = [{"agent_name": "train_ticket", "priority": 1, "reason": "查火车票/高铁", "expected_output": "车次信息"}]
            intents = [{"type": "train_ticket", "confidence": 0.92, "description": "火车票/高铁查询", "reason": "匹配火车/高铁查询模式"}]
            for name, reason, output, itype, desc in secondary:
                agent_schedule.append({"agent_name": name, "priority": 1, "reason": reason, "expected_output": output})
                intents.append({"type": itype, "confidence": 0.85, "description": desc, "reason": "查询含次要意图关键词"})
            reasoning = "规则匹配: 火车票/高铁查询" + "".join(f"+{s[3].replace('_search', '')}" for s in secondary)
            return {
                "reasoning": reasoning,
                "intents": intents,
                "key_entities": {"origin": from_city, "destination": to_city, "date": date_str},
                "rewritten_query": f"{from_city}到{to_city}{' ' + date_str if date_str else ''}高铁/火车票",
                "agent_schedule": agent_schedule,
                "fast_train_ticket": {
                    "from": from_city,
                    "to": to_city,
                    "date": date_str,
                },
            }

    # 酒店/住宿搜索
    for p in _HOTEL_PATTERNS:
        m = p.search(q)
        if m:
            # 提取城市
            city = ""
            groups = m.groups()
            for g in groups:
                if g and g in _CITY_KEYWORDS:
                    city = g
                    break
            if not city:
                for c in _CITY_KEYWORDS:
                    if c in q:
                        city = c
                        break
            # 无城市时从对话历史回填（追问场景：上一轮已提到城市）
            if not city and dialogue_history:
                city = _city_from_history(dialogue_history)
            # 仍无城市 → 交给 LLM 推断（如"虹桥火车站附近"→上海）
            if not city:
                return None
            # 多意图附加：检测餐厅/景点
            secondary = _detect_secondary_intents(q, "hotel_search")
            agent_schedule = [{"agent_name": "hotel_search", "priority": 1, "reason": "搜酒店", "expected_output": "酒店列表"}]
            intents = [{"type": "hotel_search", "confidence": 0.9, "description": "酒店搜索", "reason": "匹配酒店搜索模式"}]
            for name, reason, output, itype, desc in secondary:
                agent_schedule.append({"agent_name": name, "priority": 1, "reason": reason, "expected_output": output})
                intents.append({"type": itype, "confidence": 0.85, "description": desc, "reason": "查询含次要意图关键词"})
            reasoning = "规则匹配: 酒店搜索" + "".join(f"+{s[3].replace('_search', '')}" for s in secondary)
            return {
                "reasoning": reasoning,
                "intents": intents,
                "key_entities": {"destination": city} if city else {},
                "rewritten_query": q,
                "agent_schedule": agent_schedule,
            }

    # 餐厅/美食搜索
    for p in _RESTAURANT_PATTERNS:
        m = p.search(q)
        if m:
            city = ""
            groups = m.groups()
            for g in groups:
                if g and g in _CITY_KEYWORDS:
                    city = g
                    break
            if not city:
                for c in _CITY_KEYWORDS:
                    if c in q:
                        city = c
                        break
            # 无城市时从对话历史回填
            if not city and dialogue_history:
                city = _city_from_history(dialogue_history)
            # 仍无城市 → 交给 LLM 推断
            if not city:
                return None
            # 多意图附加：检测酒店/景点
            secondary = _detect_secondary_intents(q, "restaurant_search")
            agent_schedule = [{"agent_name": "restaurant_search", "priority": 1, "reason": "搜餐厅", "expected_output": "餐厅列表"}]
            intents = [{"type": "restaurant_search", "confidence": 0.9, "description": "餐厅搜索", "reason": "匹配餐厅搜索模式"}]
            for name, reason, output, itype, desc in secondary:
                agent_schedule.append({"agent_name": name, "priority": 1, "reason": reason, "expected_output": output})
                intents.append({"type": itype, "confidence": 0.85, "description": desc, "reason": "查询含次要意图关键词"})
            reasoning = "规则匹配: 餐厅搜索" + "".join(f"+{s[3].replace('_search', '')}" for s in secondary)
            return {
                "reasoning": reasoning,
                "intents": intents,
                "key_entities": {"destination": city} if city else {},
                "rewritten_query": q,
                "agent_schedule": agent_schedule,
            }

    # 景点搜索
    for p in _SCENIC_PATTERNS:
        m = p.search(q)
        if m:
            city = ""
            groups = m.groups()
            for g in groups:
                if g and g in _CITY_KEYWORDS:
                    city = g
                    break
            if not city:
                for c in _CITY_KEYWORDS:
                    if c in q:
                        city = c
                        break
            # 无城市时从对话历史回填
            if not city and dialogue_history:
                city = _city_from_history(dialogue_history)
            # 仍无城市 → 交给 LLM 推断
            if not city:
                return None
            # 多意图附加：检测酒店/餐厅
            secondary = _detect_secondary_intents(q, "scenic_search")
            agent_schedule = [{"agent_name": "scenic_search", "priority": 1, "reason": "搜景点", "expected_output": "景点列表"}]
            intents = [{"type": "scenic_search", "confidence": 0.9, "description": "景点搜索", "reason": "匹配景点搜索模式"}]
            for name, reason, output, itype, desc in secondary:
                agent_schedule.append({"agent_name": name, "priority": 1, "reason": reason, "expected_output": output})
                intents.append({"type": itype, "confidence": 0.85, "description": desc, "reason": "查询含次要意图关键词"})
            reasoning = "规则匹配: 景点搜索" + "".join(f"+{s[3].replace('_search', '')}" for s in secondary)
            return {
                "reasoning": reasoning,
                "intents": intents,
                "key_entities": {"destination": city} if city else {},
                "rewritten_query": q,
                "agent_schedule": agent_schedule,
            }

    # 汇率
    for p in _CURRENCY_PATTERNS:
        m = p.search(q)
        if m:
            fast_currency = _extract_currency(q)
            return {
                "reasoning": "规则匹配: 汇率查询",
                "intents": [{"type": "currency_conversion", "confidence": 0.9, "description": "汇率查询", "reason": "匹配汇率模式"}],
                "key_entities": {},
                "rewritten_query": q,
                "agent_schedule": [{"agent_name": "currency_conversion", "priority": 1, "reason": "查汇率", "expected_output": "汇率信息"}],
                "fast_currency": fast_currency,
            }

    # 翻译
    for p in _TRANSLATION_PATTERNS:
        m = p.search(q)
        if m:
            return {
                "reasoning": "规则匹配: 翻译请求",
                "intents": [{"type": "translation", "confidence": 0.9, "description": "翻译", "reason": "匹配翻译模式"}],
                "key_entities": {},
                "rewritten_query": q,
                "agent_schedule": [{"agent_name": "translation", "priority": 1, "reason": "翻译", "expected_output": "翻译结果"}],
            }

    # 经停/站点/路线/换乘/车站搜索（保留兜底）
    for p in _TRAIN_PATTERNS:
        m = p.search(q)
        if m:
            groups = m.groups()
            # 提取出发地和目的地
            from_city, to_city = "", ""
            # 先从已知城市中匹配
            for g in groups:
                if g and g in _CITY_KEYWORDS:
                    if not from_city:
                        from_city = g
                    elif not to_city:
                        to_city = g
            # 如果没匹配到已知城市，尝试从正则组中提取
            if not from_city:
                for g in groups:
                    if g and re.match(r"^[一-龥]{2,4}$", g) and g not in _NON_CITY:
                        if not from_city:
                            from_city = g
                        elif not to_city:
                            to_city = g
            # 从整个查询中提取日期（含「明早/今晚/后天上午」这类口语）
            date_str = ""
            date_match = re.search(
                r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}[日号]|大后天|今天|今日|今早|今晚|明天|明日|明早|明晚|后天|后早)",
                q,
            )
            if date_match:
                date_str = date_match.group(1)
            return {
                "reasoning": "规则匹配: 火车票查询",
                "intents": [{"type": "train_ticket", "confidence": 0.9, "description": "火车票查询", "reason": "匹配火车票模式"}],
                "key_entities": {"origin": from_city, "destination": to_city},
                "rewritten_query": q,
                "agent_schedule": [{"agent_name": "train_ticket", "priority": 1, "reason": "查火车票", "expected_output": "车票信息"}],
                "fast_train_ticket": {
                    "from": from_city,
                    "to": to_city,
                    "date": date_str,
                },
            }

    # 记忆/历史查询
    for p in _MEMORY_PATTERNS:
        if p.search(q):
            return {
                "reasoning": "规则匹配: 历史/记忆查询",
                "intents": [{"type": "memory_query", "confidence": 0.92, "description": "查询历史记录或记忆", "reason": "匹配历史查询模式"}],
                "key_entities": {},
                "rewritten_query": q,
                "agent_schedule": [{"agent_name": "memory_query", "priority": 1, "reason": "查历史记录", "expected_output": "用户历史信息"}],
            }

    # 酒店/民宿搜索
    for p in _HOTEL_PATTERNS:
        if p.search(q):
            return {
                "reasoning": "规则匹配: 酒店搜索",
                "intents": [{"type": "hotel_search", "confidence": 0.92, "description": "酒店/民宿搜索", "reason": "匹配酒店搜索模式"}],
                "key_entities": {"other": q},
                "rewritten_query": q,
                "agent_schedule": [{"agent_name": "hotel_search", "priority": 1, "reason": "搜索住宿", "expected_output": "酒店列表"}],
            }

    return None


class IntentionAgent(AgentBase):
    """意图识别智能体（IntentionRecognitionAgent）"""

    def __init__(self, name: str = "IntentionRecognitionAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        self.conversation_history = []
        self.skill_loader = SkillLoader()

    @cached("intention", ttl=1800, key_fn=_intention_cache_key)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        """
        意图识别主流程
        1. 推理过程生成
        2. 多意图识别
        3. 智能Query改写
        4. 构建结构化决策
        """
        if x is None:
            return Msg(name=self.name, content=json.dumps({}), role="assistant")

        # 获取用户查询
        if isinstance(x, list):
            user_query = x[-1].content if x else ""
            self.conversation_history = []
            for msg in x[:-1]:
                if hasattr(msg, 'content') and hasattr(msg, 'role'):
                    if msg.role == "system":
                        summary = msg.content[:500] if len(msg.content) > 500 else msg.content
                        self.conversation_history.append(f"[系统记忆]\n{summary}")
                    else:
                        role_name = "用户" if msg.role == "user" else "助手"
                        # 助手消息放宽到 1500 字（存的是自然语言摘要，需要完整保留上下文）
                        max_len = 1500 if msg.role == "assistant" else 300
                        content = msg.content[:max_len] if len(msg.content) > max_len else msg.content
                        if len(msg.content) > max_len:
                            content += "..."
                        self.conversation_history.append(f"{role_name}: {content}")
        else:
            user_query = x.content

        # ── 快速路径：规则匹配跳过 LLM ──
        # 提取纯对话历史（不含系统记忆），用于判断是否为追问
        _dialogue = [h for h in self.conversation_history if not h.startswith("[系统记忆]")]
        # 先消解位置指示词（"附近"、"那边"、"当地"等）
        resolved_query, _focus_city = _resolve_deixis(user_query, _dialogue)
        if resolved_query != user_query:
            user_query = resolved_query

        import time as _time
        _t0 = _time.monotonic()

        # 先检测省略追问（"福州的呢"、"那上海呢"）直接从历史推断意图
        if _dialogue:
            _elliptical = _resolve_elliptical(user_query, _dialogue)
            if _elliptical:
                _msg = f"[TIMING] Elliptical resolved in {(_time.monotonic() - _t0) * 1000:.0f}ms, query: {user_query[:50]}"
                logger.info(_msg)
                print(_msg, flush=True)
                return Msg(name=self.name, content=json.dumps(_elliptical, ensure_ascii=False), role="assistant")

        fast = _fast_match(user_query, dialogue_history=_dialogue)
        _t_fast = (_time.monotonic() - _t0) * 1000
        if fast:
            _msg = f"[TIMING] Fast route hit in {_t_fast:.0f}ms, query: {user_query[:50]}"
            logger.info(_msg)
            print(_msg, flush=True)
            return Msg(name=self.name, content=json.dumps(fast, ensure_ascii=False), role="assistant")
        _msg = f"[TIMING] Fast route miss in {_t_fast:.0f}ms, falling back to LLM"
        logger.info(_msg)
        print(_msg, flush=True)

        # 构建上下文
        # 策略：长期记忆始终保留，短期对话全部保留（已在 cli.py 控制数量）
        context_parts = []
        system_memory = None
        dialogue_history = []

        for item in self.conversation_history:
            if item.startswith("[系统记忆]"):
                system_memory = item  # 保存长期记忆
            else:
                dialogue_history.append(item)  # 保存对话历史

        # 组装上下文：长期记忆 + 全部对话
        if system_memory:
            context_parts.append(system_memory)
        if dialogue_history:
            context_parts.extend(dialogue_history) 

        context_str = "\n".join(context_parts) if context_parts else "无历史对话"

        # 获取当前时间
        from datetime import datetime
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.now().weekday()]

        # 动态获取 Skills 描述
        skill_mapping = {
            "memory-query": "memory_query",
            "plan-trip": "itinerary_planning",
            "preference": "preference",
            "query-info": "information_query",
            "ask-question": "rag_knowledge",
            "event-collection": "event_collection",
            "expense-tracker": "expense_tracking",
            "currency-converter": "currency_conversion",
            "translation": "translation",
            "visa-info": "visa_info",
            "train-ticket": "train_ticket",
            "place-search": "hotel_search",
        }
        
        dynamic_skills_prompt = self.skill_loader.get_skill_prompt(skill_mapping)
        
        prompt = f"""你是意图识别专家。分析用户查询，输出JSON决策。

【当前时间】{current_time} {weekday}

【用户Query】{user_query}

【对话历史】{context_str}

【子智能体】
{dynamic_skills_prompt}

【意图区分】
- "我去过北京吗？" → memory_query（用户历史）
- "查询差旅记录" / "我的旅行记录" → memory_query（查历史行程，非费用）
- "费用汇总" / "花了多少钱" → expense_tracking（查费用/金额）
- "北京怎么样？" → information_query（客观信息）
- "我想去北京" → itinerary_planning（规划行程）
- "北京有哪些酒店" / "上海住宿" → hotel_search（酒店/民宿搜索）
- "上海住宿标准是多少" / "协议酒店有什么优惠" / "报销额度" → rag_knowledge（问的是制度/标准/优惠规则，不是找具体商家；这类问题不要调度 hotel_search）
- "北京有什么好吃的" / "成都火锅推荐" / "附近美食" → restaurant_search（餐厅/美食搜索）
- "北京有哪些景点" / "上海好玩的地方" / "杭州旅游景点" → scenic_search（景点搜索）
- 当查询同时包含"住宿"+"天气"时，同时调度 information_query 和 hotel_search（同P1并行）
- memory_query 优先于 information_query
- 区分 train_ticket 和 itinerary_planning：
  - "帮我查火车票"、"广州到揭阳"（上文为火车票）→ 只调度 train_ticket，不调度 itinerary_planning
  - "帮我规划广州到揭阳的行程"、"广州到揭阳怎么玩" → train_ticket + itinerary_planning

【上下文指代消解】（重要！对追问/省略查询尤其关键）
当用户查询是省略追问（缺少地点、主语等关键实体）时，必须从【对话历史】中提取上下文补全：
- 查酒店/餐厅/美食/景点但缺城市 → 从历史最近一轮提取城市名，补入 rewritten_query 和 key_entities.destination
  - 示例：历史有"上海酒店"，用户追问"帮我查查静安区的" → rewritten_query: "上海静安区酒店"，intent: hotel_search
  - 示例：历史有"北京有什么好吃的"，用户追问"那朝阳区呢" → rewritten_query: "北京朝阳区美食"，intent: restaurant_search
  - 示例：历史有"北京有哪些景点"，用户追问"那福州呢" → rewritten_query: "福州景点"，intent: scenic_search
  - 示例：历史有"明天从北京去上海出差3天"，用户追问"附近有哪些酒店和餐厅" → rewritten_query: "上海有哪些酒店和餐厅"，destination: 上海，intents: hotel_search + restaurant_search
  - 示例：历史有"上海3天行程"，用户追问"附近有什么好吃的" → rewritten_query: "上海有什么好吃的"，destination: 上海，intent: restaurant_search
- 位置指示词（"附近"、"周边"、"旁边"、"那边"、"那里"、"当地"、"本地"）默认指代【对话历史】中的最近焦点城市。如果 query 本身未指定其他城市，必须将位置指示词替换为焦点城市并填入 rewritten_query 和 key_entities.destination。
- 查天气但缺城市 → 同上，从历史提取最近城市
  - 示例：历史有"上海天气"，用户追问"明天呢" → rewritten_query: "上海明天天气"，intent: information_query
- 品牌/连锁查询（汉庭/全季/如家/锦江/希尔顿/万豪等）→ 从历史提取城市，补入 destination
  - 示例：历史有"上海3天行程"，用户追问"查汉庭门店" → rewritten_query: "上海汉庭酒店"，intent: hotel_search，destination: 上海
  - 示例：历史有"北京行程"，用户追问"全季酒店" → rewritten_query: "北京全季酒店"，intent: hotel_search，destination: 北京
- 火车/高铁/航班查询缺起终点 → 从历史提取 origin 和 destination
  - 示例：历史有"北京到上海出差"，用户追问"查高铁班次" → rewritten_query: "北京到上海高铁班次"，intent: train_ticket，origin: 北京，destination: 上海
  - 示例：历史有"上海行程"，用户追问"火车票" → 从历史推断（上海可能是 destination），若 origin 仍缺失则触发 needs_clarification 反问出发地
- "那XX呢"/"XX的呢"句式 → XX是对历史中某类事物的细分/替换，保留历史上下文，不要当作独立新查询
- 如果当前查询本身已包含完整信息（有城市/地点），则不需要补全，正常识别
- **关键**：不要将省略追问当作独立新查询，必须结合历史上下文理解用户真实意图
- **判断依据**：助手历史摘要含"已规划...行程：XX城市"或"在XX城市找到..."时，该城市即追问的默认城市

【行程信息提取】（关键：直接输出 fast_event，省掉 event_collection 调用）
当用户查询包含差旅信息时，直接提取以下字段到 fast_event：
- origin: 出发地（城市名，如"广州"）
- destination: 目的地
- start_date: 出发日期（YYYY-MM-DD，根据当前时间推断"明天""后天"等）
- end_date: 返程日期（YYYY-MM-DD，如有"三天"则推算为 start_date+2）
- duration_days: 天数（如"三天"→3）
- trip_purpose: 目的（出差/旅游/探亲等）
- missing_info: 缺失的关键信息列表（中文名，如["返程日期"]）

【调度规则】
- 当 fast_event 已包含 destination 时，agent_schedule 中不再加入 event_collection
- 用户仅查询火车票/高铁/动车（如"帮我查火车票"、承接上文的"广州到揭阳"）时：只调度 train_ticket (P1)
- 用户明确要求规划行程/攻略/完整旅行安排（如"帮我规划行程"、"怎么玩"）时：才加入 itinerary_planning (P2)，如同时需要火车票可再加入 train_ticket (P1)
- 无需火车票时只加 itinerary_planning

【关键信息缺失处理】（重要！在调度前先检查）
- 差旅需求（itinerary_planning）：检查 origin、destination、start_date
  - 优先级：destination > origin > start_date，至少需要 destination 才视为有效差旅需求
  - 如果对话历史的系统消息中有 [用户偏好] home_location，且origin缺失时，自动将home_location填入origin
  - 如果destination存在但origin缺失且无法从偏好/历史推断，必须设置 needs_clarification=true, clarification_question为自然口语反问（≤25字），agent_schedule=[]，同时必须在 fast_event.missing_info 中列出缺失实体名称（如 ["出发地"]）
  - 如果start_date缺失但origin+destination完整，可先执行查询不反问（日期默认为近期）
- 酒店/餐厅/景点搜索（hotel_search/restaurant_search/scenic_search）：检查 destination
  - 如果 query 本身无城市，必须先从【对话历史】最近一轮提取城市回填到 key_entities.destination 和 fast_event.destination
  - 示例：历史有"明天从北京去上海出差3天"，用户追问"查汉庭酒店" → destination=上海，rewritten_query="上海汉庭酒店"
  - 示例：历史有"杭州2日行程"，用户追问"全季房型" → destination=杭州
  - 仅当历史中也无法提取城市时，才设置 needs_clarification=true 反问城市（≤25字），agent_schedule=[]，missing_info=["目的地"]
  - 回填成功后 needs_clarification=false，正常调度
- 火车票查询（train_ticket）：检查 origin 和 destination，缺失时同差旅规则从历史回填
- 非实体查询场景（天气/汇率/翻译/知识库/记忆/费用等）不需要此检查，needs_clarification始终为false
- 如果所有关键实体完整或可从历史/偏好推断，needs_clarification=false
- **重要**：needs_clarification=true 时，fast_event.missing_info 必须至少包含一个缺失实体（出发地/出发日期/目的地等），用于后续合并用户回复
- **关键**：禁止在能从历史回填的情况下反问用户。回填优先级：query 本身 > 对话历史 > 用户偏好 > 反问

【输出JSON】（只输出JSON，无其他文本）

{{
    "reasoning": "≤30字",
    "intents": [
        {{
            "type": "itinerary_planning/preference/information_query/rag_knowledge/memory_query/expense_tracking/currency_conversion/translation/visa_info/train_ticket/hotel_search/restaurant_search/scenic_search",
            "confidence": 0.95,
            "description": "意图说明",
            "reason": "识别原因"
        }}
    ],
    "key_entities": {{"origin": "广州", "destination": "揭阳", "date": "今天"}},
    "fast_event": {{
        "origin": "广州",
        "destination": "揭阳",
        "start_date": "2026-07-30",
        "end_date": "",
        "duration_days": 1,
        "trip_purpose": "",
        "missing_info": []
    }},
    "rewritten_query": "广州到揭阳的火车票",
    "needs_clarification": false,
    "clarification_question": "",
    "agent_schedule": [
        {{"agent_name": "train_ticket", "priority": 1, "reason": "查询火车票", "expected_output": "车次列表"}}
    ]
}}

【优先级】同优先级并行，不同优先级顺序。
P1: memory_query, train_ticket, preference, information_query, rag_knowledge, expense_tracking, currency_conversion, translation, visa_info, hotel_search, restaurant_search, scenic_search
P2（依赖P1结果）: itinerary_planning

直接输出JSON：
"""

        # 调用LLM进行意图识别
        messages = [
            {"role": "system", "content": "你是一个高级意图识别专家。只输出JSON格式的结果，不要输出其他文本。reasoning字段必须≤30字，一句话概括判断依据。"},
            {"role": "user", "content": prompt}
        ]
        default_result = {
            "reasoning": "LLM返回结果解析失败，使用默认策略",
            "intents": [
                {
                    "type": "information_query",
                    "confidence": 0.5,
                    "description": "默认查询意图",
                    "reason": "JSON解析失败，回退到默认"
                }
            ],
            "key_entities": {},
            "fast_event": {},
            "rewritten_query": user_query,
            "needs_clarification": False,
            "clarification_question": "",
            "agent_schedule": [
                {
                    "agent_name": "information_query",
                    "priority": 1,
                    "reason": "默认查询",
                    "expected_output": "查询结果"
                }
            ]
        }

        result = default_result
        last_error_msg = "JSON解析失败"
        max_attempts = 2
        _t_llm_start = _time.monotonic()
        for attempt in range(1, max_attempts + 1):
            try:
                response = await self.model(messages, max_tokens=SCENARIO_TOKENS["intention"])
                _t_llm = (_time.monotonic() - _t_llm_start) * 1000
                _msg = f"[TIMING] LLM call took {_t_llm:.0f}ms (attempt {attempt}/{max_attempts})"
                logger.info(_msg)
                print(_msg, flush=True)
                parsed = extract_llm_json(response, fallback=None)
                if parsed is None or (isinstance(parsed, dict) and "error" in parsed):
                    raw_text = extract_llm_text(response, fallback="<empty>")
                    logger.warning(
                        "Intent JSON parse failed on attempt %d/%d, raw text (first 500 chars): %s",
                        attempt,
                        max_attempts,
                        raw_text[:500],
                    )
                    if attempt == max_attempts:
                        # 只留一句概括；原始文本已经在上面 warning 里，不进 reasoning
                        last_error_msg = "模型返回的内容不是可解析的 JSON"
                    continue
                result = parsed
                break
            except UnboundLocalError as exc:
                # Python 3.12+ 的 except ... as e 在退出 except 块后会隐式删除 e，
                # 如果底层 C 扩展（anyio _asyncio 后端）或异步任务取消/超时的竞态条件
                # 在已删除的帧局部变量上操作，就会触发此错误。
                last_error_msg = f"UnboundLocalError: {exc}"
                full_tb = traceback.format_exc()
                logger.error(
                    "Intent recognition UnboundLocalError on attempt %d/%d: %s\n"
                    "Likely cause: C extension (anyio) or async race condition.\n"
                    "Full traceback:\n%s",
                    attempt,
                    max_attempts,
                    last_error_msg,
                    full_tb,
                )
                if attempt == max_attempts:
                    break
                await asyncio.sleep(0.5 + random.random() * 0.5)
            except Exception as exc:
                last_error_msg = str(exc)
                full_tb = traceback.format_exc()
                logger.error(
                    "Intent recognition failed on attempt %d/%d: %s\nFull traceback:\n%s",
                    attempt,
                    max_attempts,
                    last_error_msg,
                    full_tb,
                )
                if attempt == max_attempts:
                    break
                await asyncio.sleep(0.5 + random.random() * 0.5)

        if result is default_result or "error" in result:
            # 侧栏 REASONING 会原样展示 reasoning：上游 403 的 JSON 不能写进来
            from utils.llm_errors import describe, friendly_text, classify

            _reason = friendly_text(last_error_msg, default="未能识别出明确意图")
            if last_error_msg:
                logger.warning("Intent fallback to default strategy: %s", describe(Exception(last_error_msg)))
            result = {
                "reasoning": f"意图识别出错，使用默认策略：{_reason}",
                "error_code": classify(Exception(last_error_msg)) if last_error_msg else "",
                "intents": [
                    {
                        "type": "information_query",
                        "confidence": 0.5,
                        "description": "默认查询意图",
                        "reason": "无法解析用户意图，使用默认策略"
                    }
                ],
                "key_entities": {},
                "fast_event": {},
                "rewritten_query": user_query,
                "agent_schedule": [
                    {
                        "agent_name": "information_query",
                        "priority": 1,
                        "reason": "默认查询",
                        "expected_output": "查询结果"
                    }
                ]
            }

        # 将结果转换为JSON字符串，因为Msg的content必须是字符串
        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
