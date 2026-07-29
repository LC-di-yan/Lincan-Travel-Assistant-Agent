"""统一缓存门面 — Redis 优先，自动降级到进程内 dict"""
import json
import hashlib
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CacheLayer:
    """统一缓存层。Redis 可用时走 Redis，否则回退进程内 dict。"""

    def __init__(self, redis_pool=None, default_ttl: int = 3600):
        self._redis = redis_pool
        self._default_ttl = default_ttl
        self._fallback: dict = {}
        self._fallback_ttls: dict = {}

    @staticmethod
    def _make_key(prefix: str, *args) -> str:
        raw = ":".join(json.dumps(a, ensure_ascii=False, sort_keys=True) for a in args)
        digest = hashlib.md5(raw.encode()).hexdigest()[:12]
        return f"aligo:{prefix}:{digest}"

    async def get(self, key: str) -> Optional[Any]:
        if self._redis:
            try:
                value = await self._redis.get(key)
                return json.loads(value) if value else None
            except Exception as e:
                logger.warning("Redis get failed, fallback to dict: %s", e)

        expire_at = self._fallback_ttls.get(key)
        if expire_at and time.monotonic() > expire_at:
            self._fallback.pop(key, None)
            self._fallback_ttls.pop(key, None)
            return None
        return self._fallback.get(key)

    async def set(self, key: str, value: Any, ttl: int = None):
        ttl = ttl or self._default_ttl
        if self._redis:
            try:
                await self._redis.setex(key, ttl, json.dumps(value, ensure_ascii=False))
                return
            except Exception as e:
                logger.warning("Redis set failed, fallback to dict: %s", e)

        self._fallback[key] = value
        self._fallback_ttls[key] = time.monotonic() + ttl

    async def delete(self, key: str):
        if self._redis:
            try:
                await self._redis.delete(key)
            except Exception:
                pass
        self._fallback.pop(key, None)
        self._fallback_ttls.pop(key, None)

    async def clear_pattern(self, prefix: str):
        """按前缀批量清除缓存"""
        if self._redis:
            try:
                cursor = 0
                while True:
                    cursor, keys = await self._redis.scan(
                        cursor, match=f"aligo:{prefix}:*", count=100
                    )
                    if keys:
                        await self._redis.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.warning("Redis clear_pattern failed: %s", e)

        to_del = [k for k in self._fallback if k.startswith(f"aligo:{prefix}:")]
        for k in to_del:
            self._fallback.pop(k, None)
            self._fallback_ttls.pop(k, None)

    @property
    def is_redis(self) -> bool:
        return self._redis is not None
