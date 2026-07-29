"""缓存装饰器 — 用于 Agent reply 方法的非侵入式缓存"""
import functools
import json
import logging

logger = logging.getLogger(__name__)

TTL = {
    "intention": 1800,       # 意图识别 30min
    "weather": 600,          # 天气 10min
    "currency": 3600,        # 汇率 1h
    "train_ticket": 300,     # 火车票 5min
    "web_search": 1800,      # 搜索 30min
    "translation": 86400,    # 翻译 24h
    "rag_knowledge": 3600,   # 知识库 1h
    "visa_info": 21600,      # 签证 6h
    "event_collection": 1800,# 事项收集 30min
    "itinerary": 3600,       # 行程规划 1h
}


def _extract_cache_key(x) -> str:
    """
    从 Agent reply 的输入中提取稳定缓存键。

    核心原则：只取用户原始查询，忽略上下文/记忆/历史等变化部分。
    - Skill Agent 输入: JSON {context: {rewritten_query: "..."}, ...}
    - IntentionAgent 输入: [Msg(...), Msg(...)]  取最后一条用户消息
    """
    # Case 1: list of Msg → 取最后一条 user 消息
    if isinstance(x, list):
        for msg in reversed(x):
            if hasattr(msg, "role") and msg.role == "user":
                return msg.content
            if hasattr(msg, "content") and not msg.content.startswith("{"):
                return msg.content
        return str(x[-1].content) if x else ""

    # Case 2: single Msg → 尝试从 JSON 中提取 rewritten_query
    content = x.content if hasattr(x, "content") else str(x)
    if isinstance(content, str) and content.startswith("{"):
        try:
            data = json.loads(content)
            ctx = data.get("context", {})
            rewritten = ctx.get("rewritten_query", "")
            if rewritten:
                return rewritten
            key_entities = ctx.get("key_entities", {})
            if key_entities:
                return json.dumps(key_entities, sort_keys=True, ensure_ascii=False)
        except (json.JSONDecodeError, AttributeError):
            pass
    return content


def cached(prefix: str, ttl: int = None, key_fn=None):
    """
    异步方法缓存装饰器。命中缓存时直接返回 Msg，跳过原方法。

    Usage:
        @cached("weather", ttl=600)
        async def reply(self, x): ...

    缓存键默认从用户原始查询中提取（忽略上下文/记忆变化），
    可通过 key_fn 参数自定义提取逻辑。
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            cache = getattr(self, "_cache_layer", None)
            if cache is None:
                return await func(self, *args, **kwargs)

            # 生成缓存键
            x = args[0] if args else kwargs.get("x")
            if key_fn:
                raw_key = key_fn(x)
            else:
                raw_key = _extract_cache_key(x)

            cache_key = cache._make_key(prefix, raw_key)

            # 尝试命中缓存
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                from agentscope.message import Msg
                logger.info("[Cache HIT] %s:%s", prefix, cache_key.split(":")[-1])
                return Msg(
                    name=getattr(self, "name", "agent"),
                    content=json.dumps(cached_value, ensure_ascii=False),
                    role="assistant",
                )

            # 执行原方法
            result = await func(self, *args, **kwargs)

            # 缓存结果
            try:
                content = result.content if hasattr(result, "content") else str(result)
                parsed = json.loads(content) if isinstance(content, str) else content
                await cache.set(cache_key, parsed, ttl=ttl or TTL.get(prefix, 3600))
                logger.info("[Cache SET] %s:%s", prefix, cache_key.split(":")[-1])
            except Exception as e:
                logger.debug("Cache set skipped: %s", e)

            return result

        return wrapper

    return decorator
