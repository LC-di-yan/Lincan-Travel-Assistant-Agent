"""多通道 LLM 故障转移

背景（2026-10-20）：
    线上只有一个模型通道（.env 里 ALIGO_BASE_URL / ALIGO_API_KEY / ALIGO_MODEL_NAME），
    通道侧一纸「AccessDenied.Unpurchased」就让整个多智能体系统全部瘫痪：
    行程规划、意图识别、记忆总结全部共用同一个 OpenAIChatModel 实例。

做法：
    把「主通道 + N 个备用通道」包成一个可调用对象，语义与
    `agentscope.model.OpenAIChatModel` 一致（`await model(messages, **kwargs)`）。
    遇到 401/402/403/404/408/429/5xx、连接失败、超时时，自动切到下一条通道，
    并把可用通道记成 sticky（不来回抖动）。

    - 400/422（参数不被接受）**不**切换：plan-trip 自己会去掉 enable_thinking 重试，
      这类问题换通道也没用。
    - 解析失败不切换：调用是成功的。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from utils.llm_errors import classify, describe, status_code

logger = logging.getLogger(__name__)

# 值得换通道的状态码
_FAILOVER_STATUS = {401, 402, 403, 404, 408, 409, 429, 500, 502, 503, 504}

# 连接层异常（openai.APIConnectionError / APITimeoutError / httpx.*）
_CONN_KEYWORDS = (
    "timeout", "timed out", "connection", "connect", "reset by peer",
    "temporarily unavailable", "ssl", "proxy", "getaddrinfo",
)


def should_failover(exc: BaseException) -> bool:
    """这个异常是否值得换一条通道重试。"""
    code = classify(exc)
    if code in ("entitlement", "arrears", "auth", "rate_limit", "timeout", "upstream"):
        return True
    sc = status_code(exc)
    if sc in _FAILOVER_STATUS:
        return True
    text = str(exc).lower()
    return any(k in text for k in _CONN_KEYWORDS)


def _mask(api_key: str) -> str:
    if not api_key:
        return "<empty>"
    return f"{api_key[:6]}…{api_key[-4:]}" if len(api_key) > 12 else "***"


class FailoverChatModel:
    """把一个或多个 OpenAI 兼容通道包成同一个可调用模型。"""

    def __init__(
        self,
        channels: List[Dict[str, str]],
        *,
        stream: bool = False,
        timeout: float = 60.0,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        total_timeout: Optional[float] = None,
    ):
        if not channels:
            raise ValueError("FailoverChatModel 至少需要一个通道")
        self._channels = channels
        self._stream = stream
        self._timeout = timeout
        self._temperature = temperature
        self._max_tokens = max_tokens
        # 整条链的总预算：两个通道各卡 60s 再加 SDK 内部重试，曾出现 183s 无响应。
        # 到点就放弃并给用户人话，不让页面无限「处理中」。
        self._total_timeout = float(
            total_timeout
            if total_timeout is not None
            else os.environ.get("ALIGO_LLM_TOTAL_TIMEOUT", "110")
        )
        self._models: Dict[int, Any] = {}
        self._active = 0
        self._switches = 0

    # ── 通道管理 ────────────────────────────────────────────────
    @property
    def channels(self) -> List[Dict[str, str]]:
        return self._channels

    @property
    def active_index(self) -> int:
        return self._active

    @property
    def active_name(self) -> str:
        ch = self._channels[self._active]
        return f"{ch.get('name') or ch.get('base_url')} [{ch.get('model_name')}]"

    def _model(self, index: int):
        model = self._models.get(index)
        if model is None:
            from agentscope.model import OpenAIChatModel

            ch = self._channels[index]
            model = OpenAIChatModel(
                model_name=ch["model_name"],
                api_key=ch["api_key"],
                stream=self._stream,
                client_kwargs={
                    "base_url": ch["base_url"],
                    "timeout": float(self._timeout),
                    # SDK 默认会自己重试 2 次（隐形增加 2 倍耗时），重试交给通道链
                    "max_retries": 1,
                },
                generate_kwargs={
                    "temperature": self._temperature,
                    "max_tokens": self._max_tokens,
                },
            )
            self._models[index] = model
        return model

    # ── 调用 ────────────────────────────────────────────────────
    async def __call__(self, *args, **kwargs):
        order = [self._active] + [i for i in range(len(self._channels)) if i != self._active]
        last_exc: Optional[BaseException] = None
        deadline = asyncio.get_event_loop().time() + self._total_timeout

        for idx in order:
            ch = self._channels[idx]
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0.01:
                logger.error("LLM 通道链总超时（%.0fs）已用完，放弃剩余通道", self._total_timeout)
                break
            # 每个通道最多用 min(单次超时, 剩余预算)，保证后面的通道还有时间
            budget = min(self._timeout, remaining)
            try:
                result = await asyncio.wait_for(self._model(idx)(*args, **kwargs), timeout=budget)
                if idx != self._active:
                    logger.warning(
                        "LLM 通道切换：%s -> %s（第 %d 次切换）",
                        self._channels[self._active].get("name"), ch.get("name"), self._switches + 1,
                    )
                    self._switches += 1
                self._active = idx
                return result
            except asyncio.TimeoutError:
                last_exc = TimeoutError(
                    f"{ch.get('name')} 超过 {budget:.0f}s 未返回（整链预算 {self._total_timeout:.0f}s）"
                )
                logger.warning("LLM 通道超时：%s（%.0fs 未返回），尝试下一个通道", ch.get("name"), budget)
            except BaseException as exc:  # noqa: BLE001 - 需要按异常类型决定是否切换
                if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                    raise
                if not should_failover(exc):
                    logger.error("LLM 调用失败（不切换通道）：%s", describe(exc))
                    raise
                last_exc = exc
                logger.warning(
                    "LLM 通道不可用：%s -> %s；尝试下一个通道 (%d/%d)",
                    ch.get("name"), describe(exc), order.index(idx) + 1, len(order),
                )

        logger.error("所有 LLM 通道均不可用（共 %d 个）：%s", len(self._channels), describe(last_exc) if last_exc else "?")
        raise last_exc if last_exc else RuntimeError("no llm channel available")

    # ── 兼容性：像 OpenAIChatModel 一样被读取属性 ────────────────
    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._model(self._active), name)

    def __repr__(self) -> str:  # pragma: no cover
        chain = " -> ".join(ch.get("name", "?") for ch in self._channels)
        return f"<FailoverChatModel active={self.active_name} chain={chain}>"

    # ── 诊断 ────────────────────────────────────────────────────
    async def probe(self) -> Dict[str, Any]:
        """依次探活，返回第一个可用通道（会真实消耗几个 token）。"""
        report: Dict[str, Any] = {"channels": [], "active": None}
        for idx, ch in enumerate(self._channels):
            entry = {"name": ch.get("name"), "model": ch.get("model_name"), "base_url": ch.get("base_url")}
            try:
                await self._model(idx)(
                    [{"role": "user", "content": "ping"}],
                    max_tokens=4,
                )
                entry["ok"] = True
                report["channels"].append(entry)
                self._active = idx
                report["active"] = entry["name"]
                break
            except Exception as exc:  # noqa: BLE001
                entry["ok"] = False
                entry["error"] = describe(exc)
                report["channels"].append(entry)
        logger.info("LLM 通道探活结果：%s", report)
        return report


def build_chat_model(
    llm_config: Dict[str, Any],
    fallbacks: Optional[List[Dict[str, str]]] = None,
    *,
    timeout: float = 60.0,
) -> Any:
    """按主通道 + 备用通道构造模型；没有备用通道时保持原样返回。"""
    primary = {
        "name": "primary",
        "base_url": llm_config["base_url"],
        "api_key": llm_config["api_key"],
        "model_name": llm_config["model_name"],
    }

    channels = [primary]
    for i, fb in enumerate(fallbacks or [], start=1):
        if not fb.get("base_url") or not fb.get("model_name"):
            continue
        channels.append({
            "name": fb.get("name") or f"fallback{i}",
            "base_url": fb["base_url"],
            "api_key": fb.get("api_key") or llm_config["api_key"],
            "model_name": fb["model_name"],
        })

    if len(channels) == 1:
        # 无备用通道：行为与改动前完全一致，降低回归风险
        from agentscope.model import OpenAIChatModel

        return OpenAIChatModel(
            model_name=llm_config["model_name"],
            api_key=llm_config["api_key"],
            stream=False,
            client_kwargs={
                "base_url": llm_config["base_url"],
                "timeout": float(timeout),
                "max_retries": 1,
            },
            generate_kwargs={
                "temperature": llm_config.get("temperature", 0.7),
                "max_tokens": llm_config.get("max_tokens", 2000),
            },
        )

    logger.info(
        "LLM 通道链：%s",
        " -> ".join(f"{c['name']}({c['model_name']})" for c in channels),
    )
    return FailoverChatModel(
        channels,
        stream=False,
        timeout=timeout,
        temperature=llm_config.get("temperature", 0.7),
        max_tokens=llm_config.get("max_tokens", 2000),
    )
