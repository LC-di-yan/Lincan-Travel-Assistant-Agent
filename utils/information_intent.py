"""Recognise only complete, supported weather/clothing/local-information requests."""
from functools import lru_cache
import re

_WORDS = """
请 麻烦 帮我 帮忙 给我 替我 查一下 查下 查询 查查 查 看一下 看看 查看 看 告诉我 了解一下 了解
请问 你好 您好 麻烦你 麻烦您 请你 请您 我想知道 我想了解 我想 我要 我能不能 我可以 可以帮我 能不能 能否 可否 可不可以 介绍 讲讲
天气预报 天气 气温 温度 预报 实况 现在 当前 此刻 实时 目前 近期 最近 未来 接下来
怎么样 怎样 如何 怎么选 怎么选择 好不好 冷不冷 热不热 冷吗 热吗 多少度 几度 会不会 是否 会
下雨 下雪 晴 多云 阴 雨 雪 带伞 要不要 需不需要 用不用 需要 适合 合适 行不行 可以 不
穿什么衣服 穿什么 穿多少 穿多厚 穿衣建议 穿衣指数 穿衣 衣服 羽绒服 外套 毛衣 短袖 长袖 穿
交通建议 交通推荐 交通 出行方式 出行 当地 市内 地铁推荐 地铁方便 公交推荐 公交方便
出门 适不适合 附近 周边 旁边 本地 那边 那里 这边
怎么坐车 怎么出行 如何出行 坐车 方式 路线 换乘 方便 便利 拥堵 情况 建议 推荐
住宿 酒店 宾馆 民宿 旅馆 青旅 客栈 招待所 找 搜索 搜
美食 好吃 餐厅 餐馆 饭店 饭馆 小吃 火锅 川菜 粤菜 湘菜 日料 韩餐 西餐 烧烤 海鲜
景点 景区 公园 好玩 打卡 名胜 风景
今天 今日 今早 今晚 明天 明日 明早 明晚 后天 大后天 日间 夜间 白天 晚上 夜里 早上 上午 下午
的 和 与 及 以及 并且 同时 还有 顺便 再 也 呢 吗 吧 啊 呀 一下 有哪些 有什么 有 什么 一些
""".split()
_WORDS_RE = re.compile("|".join(re.escape(word) for word in sorted(set(_WORDS), key=lambda value: (-len(value), value))))
_DATE_RE = re.compile(
    r"(?<!\d)(?:\d{4}(?:年|[-/]))?\d{1,2}(?:月|[-/])\d{1,2}(?:日|号)?(?!\d)|"
    r"(?:未来|接下来|近|最近)?[\d一二两三四五六七八九十]+(?:天|日|周)|"
    r"(?:下下|下|本|这)?(?:周|星期)[一二三四五六日天末]?|下个?月"
)
_NEGATED_TASK = re.compile(r"(?:不|别|无需)(?:用|要|需要)?(?:查|搜|看|推荐|提供)|不(?:要|需要)(?:天气|酒店|住宿|交通|穿衣|景点|美食)")


@lru_cache(maxsize=4)
def _cities_pattern(cities: tuple[str, ...]):
    return re.compile("|".join(re.escape(city) for city in sorted(cities, key=lambda value: (-len(value), value))))


def is_simple_information_request(query: str, cities) -> bool:
    """Unknown clauses go to full intent recognition, never disappear after a keyword hit."""
    if _NEGATED_TASK.search(query):
        return False
    residue = _cities_pattern(tuple(sorted(cities))).sub("", query)
    residue = _DATE_RE.sub("", residue)
    residue = _WORDS_RE.sub("", residue)
    return not re.sub(r"[\s，,。.!！?？、；;：:()（）\-—~～/]+", "", residue)
