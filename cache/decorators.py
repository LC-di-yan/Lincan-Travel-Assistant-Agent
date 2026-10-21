"""@cached 装饰器：按 namespace + key_fn 结果缓存 async 方法的返回值。

行为约定：
- 宿主对象没有 _cache_layer（或缓存层未启用）时，直接透传，零行为改变。
- 返回值是 agentscope 的 Msg 时，只缓存 name/content/role，命中后重建 Msg。
- 任何缓存读写异常都吞掉，回落到真实调用。
"""
import functools
import hashlib
import inspect
import json
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def _default_key(args: tuple, kwargs: dict) -> str:
    """默认键：跳过 self，把其余参数稳定序列化。"""
    parts = []
    for a in args:
        parts.append(repr(getattr(a, "content", a)))
    for k in sorted(kwargs):
        parts.append(f"{k}={getattr(kwargs[k], 'content', kwargs[k])!r}")
    return json.dumps(parts, ensure_ascii=False)


def _deserialize(payload: Any):
    """把缓存内容还原成 Msg（延迟导入，避免污染无 agentscope 的环境）。"""
    if not isinstance(payload, dict):
        return None
    try:
        from agentscope.message import Msg

        return Msg(
            name=payload.get("name", "cached"),
            content=payload.get("content", ""),
            role=payload.get("role", "assistant"),
        )
    except Exception:
        return None


def _serialize(result: Any) -> Optional[dict]:
    if hasattr(result, "content") and hasattr(result, "role"):
        return {
            "name": getattr(result, "name", "cached"),
            "content": result.content,
            "role": result.role,
        }
    return None


def cached(namespace: str, ttl: int = 300, key_fn: Optional[Callable] = None):
    """缓存 async 方法返回值。

    Args:
        namespace: 键前缀，便于分类清理（如 "intention"、"rag_knowledge"）。
        ttl: 过期秒数。
        key_fn: 由业务方提供，输入是被装饰方法的第一个业务参数（如 Msg 或 List[Msg]）。
    """

    def decorator(func: Callable):
        if not inspect.iscoroutinefunction(func):
            # 同步方法不做缓存，避免阻塞事件循环
            return func

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            host = args[0] if args else None
            layer = getattr(host, "_cache_layer", None)

            if layer is None or not getattr(layer, "enabled", False):
                return await func(*args, **kwargs)

            try:
                if key_fn is not None:
                    business_args = args[1] if len(args) > 1 else kwargs.get("x")
                    raw_key = key_fn(business_args)
                else:
                    raw_key = _default_key(args[1:], kwargs)
                digest = hashlib.sha256(str(raw_key).encode("utf-8")).hexdigest()
                cache_key = f"{namespace}:{digest}"
            except Exception as exc:
                logger.debug(f"cache key build failed: {exc}")
                return await func(*args, **kwargs)

            try:
                hit = await layer.get_json(cache_key)
                restored = _deserialize(hit)
                if restored is not None:
                    return restored
            except Exception as exc:
                logger.debug(f"cache lookup failed: {exc}")

            result = await func(*args, **kwargs)
            payload = _serialize(result)
            if payload is not None:
                try:
                    await layer.set_json(cache_key, payload, ttl=ttl)
                except Exception as exc:
                    logger.debug(f"cache store failed: {exc}")
            return result

        return wrapper

    return decorator