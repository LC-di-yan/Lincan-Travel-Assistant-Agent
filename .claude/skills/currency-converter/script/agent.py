"""
汇率转换智能体
职责：查询实时汇率、货币换算
API: frankfurter.app (免费，无需 key)

优化：fast_currency 快速路径 + regex 兜底，避免 LLM 调用。
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import json
import logging
import re
import requests
import time as _time

from utils.llm_response import extract_llm_json
from cache.decorators import cached

logger = logging.getLogger(__name__)

# 常用货币中文名映射
CURRENCY_MAP = {
    "人民币": "CNY", "元": "CNY", "块": "CNY",
    "美元": "USD", "美金": "USD", "刀": "USD",
    "欧元": "EUR", "英镑": "GBP", "日元": "JPY",
    "韩元": "KRW", "港币": "HKD", "港元": "HKD",
    "新台币": "TWD", "台币": "TWD",
    "新加坡元": "SGD", "新币": "SGD",
    "泰铢": "THB", "澳元": "AUD", "加元": "CAD",
}

CURRENCY_NAMES = {
    "CNY": "人民币", "USD": "美元", "EUR": "欧元", "GBP": "英镑",
    "JPY": "日元", "KRW": "韩元", "HKD": "港币", "TWD": "新台币",
    "SGD": "新加坡元", "THB": "泰铢", "AUD": "澳元", "CAD": "加元",
}

# 货币关键词按长度降序（避免"元"先匹配"美元"中的"元"）
_CURRENCY_WORDS = sorted(CURRENCY_MAP.keys(), key=len, reverse=True)

API_BASE = "https://api.frankfurter.app"


def _parse_currency_regex(query: str) -> Optional[dict]:
    """用正则从查询中提取货币信息。返回 {from_currency, to_currency, amount} 或 None。"""
    q = query.strip()

    # 模式1: "100美元多少人民币" / "100美元换多少人民币"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(\S+?)\s*(?:多少|换|兑|兑换|换算|等于|是|转)\s*(?:多少|几)?\s*(\S+)", q)
    if m:
        amount = float(m.group(1))
        currencies = re.findall(r"|".join(_CURRENCY_WORDS), q)
        codes = list(dict.fromkeys(CURRENCY_MAP[w] for w in currencies))
        if len(codes) >= 2:
            return {"from_currency": codes[0], "to_currency": codes[1], "amount": amount}

    # 模式2: "美元兑人民币" / "日元汇率" (无金额 → amount=1)
    currencies = re.findall(r"|".join(_CURRENCY_WORDS), q)
    codes = list(dict.fromkeys(CURRENCY_MAP[w] for w in currencies))
    if len(codes) >= 2:
        return {"from_currency": codes[0], "to_currency": codes[1], "amount": 1}

    # 模式3: "汇率" + 单个货币 → 该货币兑人民币
    if len(codes) == 1 and "汇率" in q:
        return {"from_currency": codes[0], "to_currency": "CNY", "amount": 1}

    return None


class CurrencyConverterAgent(AgentBase):
    """汇率转换智能体"""

    def __init__(self, name: str = "CurrencyConverterAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model

    @cached("currency", ttl=3600)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content=json.dumps({"error": "No input"}), role="assistant")

        content = x.content if not isinstance(x, list) else x[-1].content
        if isinstance(content, str):
            try:
                data = json.loads(content)
                context = data.get("context", {})
                fast_currency = data.get("fast_currency")
                user_query = context.get("rewritten_query", "") or str(data)
            except json.JSONDecodeError:
                user_query = content
                fast_currency = None
        else:
            user_query = str(content)
            fast_currency = None

        # ── 快速路径1: IntentionAgent 已提取 ──
        if fast_currency:
            _t0 = _time.monotonic()
            from_curr = fast_currency.get("from_currency", "USD").upper()
            to_curr = fast_currency.get("to_currency", "CNY").upper()
            amount = float(fast_currency.get("amount", 1))
            parsed = fast_currency
            _msg = f"[TIMING] Currency fast route hit in {(_time.monotonic() - _t0) * 1000:.0f}ms"
            logger.info(_msg)
            print(_msg, flush=True)

        # ── 快速路径2: regex 本地解析 ──
        elif parsed := _parse_currency_regex(user_query):
            _t0 = _time.monotonic()
            from_curr = parsed.get("from_currency", "USD").upper()
            to_curr = parsed.get("to_currency", "CNY").upper()
            amount = float(parsed.get("amount", 1))
            _msg = f"[TIMING] Currency regex hit in {(_time.monotonic() - _t0) * 1000:.0f}ms"
            logger.info(_msg)
            print(_msg, flush=True)

        # ── 降级: LLM 解析 ──
        else:
            _msg = "[TIMING] Currency regex miss, falling back to LLM"
            logger.info(_msg)
            print(_msg, flush=True)

            prompt = f"""你是汇率查询助手，请从用户输入中提取货币信息。

用户输入: {user_query}

请输出JSON:
{{
  "from_currency": "源货币代码(如USD)",
  "to_currency": "目标货币代码(如CNY)",
  "amount": 数字(如果没有指定金额则为1)
}}

货币代码参考: CNY(人民币/元), USD(美元), EUR(欧元), JPY(日元), GBP(英镑), KRW(韩元), HKD(港币), TWD(新台币), SGD(新加坡元), THB(泰铢), AUD(澳元), CAD(加元)

只输出JSON，不要其他文字。"""

            try:
                _t0 = _time.monotonic()
                response = await self.model([{"role": "user", "content": prompt}])
                parsed = extract_llm_json(response)
                _msg = f"[TIMING] Currency LLM parsing took {(_time.monotonic() - _t0) * 1000:.0f}ms"
                logger.info(_msg)
                print(_msg, flush=True)
            except Exception as e:
                logger.error(f"Currency parsing failed: {e}")
                return Msg(name=self.name, content=json.dumps({
                    "action": "error",
                    "answer": f"无法理解汇率查询请求: {str(e)}"
                }, ensure_ascii=False), role="assistant")

            from_curr = parsed.get("from_currency", "USD").upper()
            to_curr = parsed.get("to_currency", "CNY").upper()
            amount = float(parsed.get("amount", 1))

        # 调用 frankfurter.app API
        try:
            result = self._fetch_rate(from_curr, to_curr, amount)
        except Exception as e:
            logger.error(f"Rate fetch failed: {e}")
            result = {"action": "error", "answer": f"汇率查询失败: {str(e)}"}

        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

    def _fetch_rate(self, from_curr: str, to_curr: str, amount: float) -> dict:
        """调用 frankfurter.app 获取汇率"""
        url = f"{API_BASE}/latest?from={from_curr}&to={to_curr}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        rate = data.get("rates", {}).get(to_curr)
        if rate is None:
            return {"action": "error", "answer": f"不支持的货币对: {from_curr} → {to_curr}"}

        converted = round(amount * rate, 2)
        from_name = CURRENCY_NAMES.get(from_curr, from_curr)
        to_name = CURRENCY_NAMES.get(to_curr, to_curr)

        if amount == 1:
            answer = f"当前{from_name}兑{to_name}汇率: 1 {from_curr} = {rate} {to_curr}"
        else:
            answer = f"{amount} {from_name} = {converted} {to_name} (汇率: 1 {from_curr} = {rate} {to_curr})"

        return {
            "action": "convert" if amount > 1 else "rate",
            "from": from_curr,
            "to": to_curr,
            "amount": amount,
            "rate": rate,
            "result": converted,
            "answer": answer,
            "proactive_question": "需要我帮你换算其他货币吗？",
        }
