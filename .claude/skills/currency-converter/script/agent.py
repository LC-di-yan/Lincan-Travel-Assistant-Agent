"""
汇率转换智能体
职责：查询实时汇率、货币换算
API: Frankfurter (免费，无需 key)

优化：fast_currency 快速路径 + regex 兜底，避免 LLM 调用。
"""
from agents.base import SkillAgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import json
import logging
import asyncio
import httpx
from utils.provider_http import provider_client
import time as _time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from threading import Lock
from utils.currency_parser import CURRENCY_MAP, parse_currency

from utils.llm_response import extract_llm_json
from utils.as_compat import mk_msg, msg_text, as_messages

logger = logging.getLogger(__name__)

CURRENCY_NAMES = {
    "CNY": "人民币", "USD": "美元", "EUR": "欧元", "GBP": "英镑",
    "JPY": "日元", "KRW": "韩元", "HKD": "港币", "TWD": "新台币",
    "SGD": "新加坡元", "THB": "泰铢", "AUD": "澳元", "CAD": "加元",
}

API_BASE = "https://api.frankfurter.dev/v1"
# 汇率是公开数据：按货币对共享缓存，而不是把整轮对话/金额当缓存键。
_RATE_CACHE = {}
_RATE_LOCK = Lock()
_RATE_TTL = 900


def _parse_currency_regex(query: str) -> Optional[dict]:
    return parse_currency(query)


class CurrencyConverterAgent(SkillAgentBase):
    """汇率转换智能体"""

    def __init__(self, name: str = "CurrencyConverterAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return mk_msg(self.name, {"error": "No input"})

        src = x[-1] if isinstance(x, list) else x
        raw = msg_text(src)
        fast_currency = None
        try:
            data = json.loads(raw)
            context = data.get("context", {})
            fast_currency = data.get("fast_currency")
            user_query = context.get("rewritten_query", "") or str(data)
        except json.JSONDecodeError:
            user_query = raw

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
                response = await self.model(as_messages([{"role": "user", "content": prompt}]))
                parsed = extract_llm_json(response)
                _msg = f"[TIMING] Currency LLM parsing took {(_time.monotonic() - _t0) * 1000:.0f}ms"
                logger.info(_msg)
                print(_msg, flush=True)
            except Exception as e:
                logger.error(f"Currency parsing failed: {e}")
                return mk_msg(self.name, {
                    "action": "error",
                    "answer": f"无法理解汇率查询请求: {str(e)}"
                })

            from_curr = parsed.get("from_currency", "USD").upper()
            to_curr = parsed.get("to_currency", "CNY").upper()
            amount = float(parsed.get("amount", 1))

        # 参数无效时不请求上游；相同币种无需联网。
        if from_curr not in CURRENCY_NAMES or to_curr not in CURRENCY_NAMES or not Decimal(str(amount)).is_finite() or amount < 0 or amount > 1e15:
            return mk_msg(self.name, {"action": "error", "answer": "请提供有效金额和支持的货币代码。"})

        # 调用 frankfurter.app API
        try:
            result = await self._fetch_rate(from_curr, to_curr, amount)
        except Exception as e:
            logger.warning("Rate fetch failed (%s)", type(e).__name__)
            result = {"action": "error", "answer": "汇率查询暂不可用，请稍后再试。"}

        return mk_msg(self.name, result)

    async def _fetch_rate(self, from_curr: str, to_curr: str, amount: float) -> dict:
        """Fetch a dated public quote; repeated amounts reuse the same currency pair."""
        rate_date = ""
        cached_quote = False
        if from_curr == to_curr:
            rate = Decimal("1")
        else:
            pair = (from_curr, to_curr)
            with _RATE_LOCK:
                quote = _RATE_CACHE.get(pair)
            if quote and _time.monotonic() - quote[0] < _RATE_TTL:
                rate, rate_date = quote[1:]
                cached_quote = True
            else:
                async with asyncio.timeout(8), provider_client("exchange", timeout=httpx.Timeout(5, connect=3, pool=2)) as client:
                    resp = await client.get(f"{API_BASE}/latest", params={"from": from_curr, "to": to_curr})
                    resp.raise_for_status()
                    data = resp.json()
                try:
                    rate = Decimal(str(data.get("rates", {}).get(to_curr)))
                    if not rate.is_finite() or rate <= 0:
                        raise ValueError("invalid rate")
                except (InvalidOperation, ValueError):
                    return {"action": "error", "answer": f"未取得可靠汇率: {from_curr} → {to_curr}"}
                rate_date = str(data.get("date") or "")
                with _RATE_LOCK:
                    if len(_RATE_CACHE) >= 128:
                        _RATE_CACHE.pop(next(iter(_RATE_CACHE)))
                    _RATE_CACHE[pair] = (_time.monotonic(), rate, rate_date)

        converted = (Decimal(str(amount)) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        from_name = CURRENCY_NAMES.get(from_curr, from_curr)
        to_name = CURRENCY_NAMES.get(to_curr, to_curr)
        date_note = f"；汇率日期 {rate_date}" if rate_date else ""
        if amount == 1:
            answer = f"{from_name}兑{to_name}参考汇率: 1 {from_curr} = {rate} {to_curr}{date_note}"
        else:
            amount_text = format(Decimal(str(amount)).normalize(), "f")
            answer = f"{amount_text} {from_name} = {converted} {to_name} (参考汇率: 1 {from_curr} = {rate} {to_curr}{date_note})"
        return {
            "action": "rate" if amount == 1 else "convert",
            "from": from_curr, "to": to_curr, "amount": amount,
            "rate": float(rate), "result": float(converted), "rate_date": rate_date,
            "rate_cached": cached_quote, "answer": answer,
            "proactive_question": "需要我帮你换算其他货币吗？",
        }
