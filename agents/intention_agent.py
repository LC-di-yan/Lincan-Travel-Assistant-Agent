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

_HOTEL_PATTERNS = [
    re.compile(r"(.{2,6})[的有]?(?:哪些|什么|哪家|有没有).*?(?:酒店|民宿|宾馆|旅馆|客栈|青旅|住宿)"),
    re.compile(r"(?:找|查|搜).{0,6}(.{2,6}).*?(?:酒店|民宿|宾馆|旅馆|客栈)"),
    re.compile(r"(?:帮我找|帮我查|搜索|推荐|看看?).*?(?:酒店|民宿|宾馆|旅馆|客栈|住宿)"),
    re.compile(r"(?:酒店|民宿|宾馆|旅馆|客栈|住宿).*?(?:推荐|搜索|查询)"),
    re.compile(r"(.{2,8}?).*?(住宿|酒店|宾馆|民宿|旅馆|青旅|青年旅舍|客栈|招待所)"),
    re.compile(r"(住宿|酒店|宾馆|民宿|旅馆|青旅|青年旅舍|客栈|招待所).*?(.{2,8}?)"),
    re.compile(r"(住|住宿).*?哪里|哪里.*?(住|住宿)"),
]

_RESTAURANT_PATTERNS = [
    re.compile(r"有(啥|什么).*?(好吃|美食|特色|推荐|餐厅|饭店|饭馆|小吃|餐馆)"),
    re.compile(r"(.{2,6})[的有]?(?:哪些|什么|啥|哪家|有没有).*?(?:好吃|美食|餐厅|饭店|饭馆|小吃|特色菜|餐馆|聚餐|吃饭)"),
    re.compile(r"(?:找|查|搜).{0,6}(.{2,6}).*?(?:好吃|美食|餐厅|饭店|饭馆|小吃|聚餐)"),
    re.compile(r"(?:帮我找|帮我查|搜索|推荐|看看?).*?(?:好吃|美食|餐厅|饭店|饭馆|小吃|特色菜|餐馆)"),
    re.compile(r"(?:好吃|美食|餐厅|饭店|饭馆|小吃|特色菜|餐馆).*?(?:推荐|搜索|查询)"),
    re.compile(r"(.{2,8}?).*?(川菜|粤菜|湘菜|火锅|日料|韩餐|西餐|烧烤|海鲜|早茶|自助餐|大排档|麻辣烫)"),
    re.compile(r"(川菜|粤菜|湘菜|火锅|日料|韩餐|西餐|烧烤|海鲜|早茶|自助餐).*?(.{2,8}?)"),
    re.compile(r"(吃|吃饭|聚餐).*?哪里|哪里.*?(吃|吃饭|聚餐)"),
    re.compile(r"有什么.*?(好吃|美食|特色|推荐)"),
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

_TRANSLATION_PATTERNS = [
    re.compile(r"翻译[成用](英文|日文|韩文|法文|德文|中文|日语|韩语|法语|德语|英语)"),
    re.compile(r"用(英文|日文|韩文|法文|德文|中文|日语|韩语|法语|德语|英语)怎么说"),
    re.compile(r"translate.*?to\s+(english|chinese|japanese|korean|french|german)", re.I),
]

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
    re.compile(r"(查询?|看看?|我的?|历史)\s*(差旅|旅行|出行|旅游|行程|出差)\s*(记录|历史|情况|汇总|总结)"),
    re.compile(r"(我去过|去过|去过哪些|去过哪里|去过什么地方)"),
    re.compile(r"(我的?|以前|上次).*?(旅行|差旅|出行|行程|出差|去过)"),
    re.compile(r"(历史|以往|过去).*?(行程|旅行|差旅|出行|记录)"),
    re.compile(r"(查|看|看看|显示|查看).*?(历史记录|出行记录|行程记录|旅行记录|差旅记录|去过哪)"),
]

# 城市关键词（模块级，供快速路由和天气/酒店检测共用）
_CITY_KEYWORDS = {"北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "苏州",
                  "天津", "重庆", "厦门", "青岛", "大连", "宁波", "无锡", "长沙", "郑州", "济南",
                  "哈尔滨", "沈阳", "昆明", "合肥", "福州", "石家庄", "南昌", "贵阳", "太原", "南宁",
                  "拉萨", "乌鲁木齐", "呼和浩特", "银川", "西宁", "兰州", "海口", "三亚", "珠海",
                  "虹桥", "南站", "北站", "东站", "西站"}
_NON_CITY = {"查", "搜", "看", "火车", "高铁", "动车", "列车", "票", "经停", "停靠", "站点", "路线",
             "换乘", "转车", "中转", "余票", "有票", "没票", "车次", "班次", "明天", "后天", "今天",
             "下周", "这周", "周一", "周二", "周三", "周四", "周五", "周六", "周日"}


def _fast_match(query: str, dialogue_history: list = None) -> Optional[dict]:
    """
    规则快速路由器：尝试用正则匹配高置信度意图。
    返回 None 表示需要走 LLM，返回 dict 表示直接命中。
    当 dialogue_history 非空时，对缺少关键实体（城市等）的查询不快速路由，
    交给 LLM 利用对话历史补全上下文。
    """
    _has_history = bool(dialogue_history)
    q = query.strip()

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
            hotel_words = ["住宿", "酒店", "宾馆", "民宿", "旅馆", "青旅", "客栈", "招待所", "住"]
            has_hotel = any(w in q for w in hotel_words)
            agent_schedule = [{"agent_name": "information_query", "priority": 1, "reason": "查天气", "expected_output": "天气信息"}]
            intents = [{"type": "information_query", "confidence": 0.9, "description": "天气查询", "reason": "匹配天气模式"}]
            if has_hotel:
                agent_schedule.append({"agent_name": "hotel_search", "priority": 1, "reason": "查住宿", "expected_output": "酒店列表"})
                intents.append({"type": "hotel_search", "confidence": 0.85, "description": "酒店搜索", "reason": "查询含住宿关键词"})
            return {
                "reasoning": "规则匹配: 天气查询" + ("+酒店搜索" if has_hotel else ""),
                "intents": intents,
                "key_entities": {"destination": city} if city else {},
                "rewritten_query": q,
                "agent_schedule": agent_schedule,
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
            # 有对话历史但没提取到城市 → 交给 LLM 用历史补全
            if not city and _has_history:
                return None
            return {
                "reasoning": "规则匹配: 酒店搜索",
                "intents": [{"type": "hotel_search", "confidence": 0.9, "description": "酒店搜索", "reason": "匹配酒店搜索模式"}],
                "key_entities": {"destination": city} if city else {},
                "rewritten_query": q,
                "agent_schedule": [{"agent_name": "hotel_search", "priority": 1, "reason": "搜酒店", "expected_output": "酒店列表"}],
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
            # 有对话历史但没提取到城市 → 交给 LLM 用历史补全
            if not city and _has_history:
                return None
            return {
                "reasoning": "规则匹配: 餐厅搜索",
                "intents": [{"type": "restaurant_search", "confidence": 0.9, "description": "餐厅搜索", "reason": "匹配餐厅搜索模式"}],
                "key_entities": {"destination": city} if city else {},
                "rewritten_query": q,
                "agent_schedule": [{"agent_name": "restaurant_search", "priority": 1, "reason": "搜餐厅", "expected_output": "餐厅列表"}],
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

    # 火车票
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
            # 从整个查询中提取日期
            date_str = ""
            date_match = re.search(r"(明天|后天|今天|\d{1,2}月\d{1,2}[日号]|\d{4}-\d{1,2}-\d{1,2})", q)
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

    @cached("intention", ttl=1800)
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
                        content = msg.content[:300] if len(msg.content) > 300 else msg.content
                        if len(msg.content) > 300:
                            content += "..."
                        self.conversation_history.append(f"{role_name}: {content}")
        else:
            user_query = x.content

        # ── 快速路径：规则匹配跳过 LLM ──
        # 提取纯对话历史（不含系统记忆），用于判断是否为追问
        _dialogue = [h for h in self.conversation_history if not h.startswith("[系统记忆]")]
        import time as _time
        _t0 = _time.monotonic()
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
            "hotel-search": "hotel_search",
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
- "北京有什么好吃的" / "成都火锅推荐" / "附近美食" → restaurant_search（餐厅/美食搜索）
- 当查询同时包含"住宿"+"天气"时，同时调度 information_query 和 hotel_search（同P1并行）
- memory_query 优先于 information_query

【上下文指代消解】（重要！对追问/省略查询尤其关键）
当用户查询是省略追问（缺少地点、主语等关键实体）时，必须从【对话历史】中提取上下文补全：
- 查酒店/餐厅/美食但缺城市 → 从历史最近一轮提取城市名，补入 rewritten_query 和 key_entities.destination
  - 示例：历史有"上海酒店"，用户追问"帮我查查静安区的" → rewritten_query: "上海静安区酒店"，intent: hotel_search
  - 示例：历史有"北京有什么好吃的"，用户追问"那朝阳区呢" → rewritten_query: "北京朝阳区美食"，intent: restaurant_search
- 查天气但缺城市 → 同上，从历史提取最近城市
  - 示例：历史有"上海天气"，用户追问"明天呢" → rewritten_query: "上海明天天气"，intent: information_query
- "那XX呢"/"XX的呢"句式 → XX是对历史中某类事物的细分/替换，保留历史上下文，不要当作独立新查询
- 如果当前查询本身已包含完整信息（有城市/地点），则不需要补全，正常识别
- **关键**：不要将省略追问当作独立新查询，必须结合历史上下文理解用户真实意图

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
- 有差旅需求时：train_ticket (P1，查火车票) + itinerary_planning (P2，用 fast_event 数据规划)
- 无需火车票时只加 itinerary_planning

【关键信息缺失处理】（重要！在调度前先检查）
- 当检测到差旅需求时，检查关键实体是否完整：origin（出发地）、destination（目的地）、start_date（出发日期）
- 优先级：destination > origin > start_date，至少需要 destination 才视为有效差旅需求
- 如果对话历史的系统消息中有 [用户偏好] home_location，且origin缺失时，自动将home_location填入origin
- 如果destination存在但origin缺失且无法从偏好推断，必须设置 needs_clarification=true, clarification_question为自然口语反问（≤25字），agent_schedule=[]，同时必须在 fast_event.missing_info 中列出缺失实体名称（如 ["出发地"]）
- 如果start_date缺失但origin+destination完整，可先执行查询不反问（日期默认为近期）
- 如果所有关键实体完整或可推断，needs_clarification=false
- 非差旅场景（天气/汇率/翻译/知识库等）不需要此检查，needs_clarification始终为false
- **重要**：needs_clarification=true 时，fast_event.missing_info 必须至少包含一个缺失实体（出发地/出发日期/目的地等），用于后续合并用户回复

【输出JSON】（只输出JSON，无其他文本）

{{
    "reasoning": "≤30字",
    "intents": [
        {{
            "type": "itinerary_planning/preference/information_query/rag_knowledge/memory_query/expense_tracking/currency_conversion/translation/visa_info/train_ticket/hotel_search/restaurant_search",
            "confidence": 0.95,
            "description": "意图说明",
            "reason": "识别原因"
        }}
    ],
    "key_entities": {{"origin": "广州", "destination": "揭阳", "date": "明天", "duration": "三天"}},
    "fast_event": {{
        "origin": "广州",
        "destination": "揭阳",
        "start_date": "2026-07-30",
        "end_date": "2026-08-01",
        "duration_days": 3,
        "trip_purpose": "出差",
        "missing_info": ["返程日期"]
    }},
    "rewritten_query": "标准化查询",
    "needs_clarification": false,
    "clarification_question": "",
    "agent_schedule": [
        {{"agent_name": "train_ticket", "priority": 1, "reason": "查询火车票", "expected_output": "车次列表"}},
        {{"agent_name": "itinerary_planning", "priority": 2, "reason": "规划行程", "expected_output": "行程计划"}}
    ]
}}

【优先级】同优先级并行，不同优先级顺序。
P1: memory_query, train_ticket, preference, information_query, rag_knowledge, expense_tracking, currency_conversion, translation, visa_info, hotel_search, restaurant_search
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
                        last_error_msg = f"JSON解析失败, raw: {raw_text[:200]}"
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
            result = {
                "reasoning": f"意图识别出错，使用默认策略。错误: {last_error_msg}",
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
