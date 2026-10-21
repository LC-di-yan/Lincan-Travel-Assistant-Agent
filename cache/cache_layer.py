"""CacheLayer：Redis 之上的轻量 JSON 缓存门面。

约定：
- 所有方法都是 async，但内部吞掉异常 —— 缓存失败绝不影响主流程。
- 未传入 redis 客户端时对象仍可构造，所有读写退化为 no-op（返回 None / False）。
"""
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CacheLayer:
    """薄封装：get / set / delete，带前缀与 TTL。"""

    def __init__(self, redis_client=None, prefix: str = "aligo:"):
        self._redis = redis_client
        self._prefix = prefix

    @property
    def enabled(self) -> bool:
        return self._redis is not None

    def _k(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> Optional[str]:
        if self._redis is None:
            return None
        try:
            return await self._redis.get(self._k(key))
        except Exception as exc:
            logger.debug(f"cache get failed: {exc}")
            return None

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        if self._redis is None:
            return False
        try:
            if ttl:
                await self._redis.set(self._k(key), value, ex=int(ttl))
            else:
                await self._redis.set(self._k(key), value)
            return True
        except Exception as exc:
            logger.debug(f"cache set failed: {exc}")
            return False

    async def delete(self, key: str) -> bool:
        if self._redis is None:
            return False
        try:
            await self._redis.delete(self._k(key))
            return True
        except Exception as exc:
            logger.debug(f"cache delete failed: {exc}")
            return False

    async def get_json(self, key: str) -> Any:
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        try:
            payload = json.dumps(value, ensure_ascii=False)
        except Exception as exc:
            logger.debug(f"cache serialize failed: {exc}")
            return False
        return await self.set(key, payload, ttl=ttl)