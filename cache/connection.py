"""Redis 连接池管理 — 单例，类似 db/connection.py 模式"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = asyncio.Lock()


async def get_redis():
    """懒加载 Redis 连接（单例）。返回 None 表示未配置 Redis。"""
    global _pool
    if _pool is not None:
        return _pool

    async with _pool_lock:
        if _pool is not None:
            return _pool

        from config import REDIS_URL
        if not REDIS_URL:
            logger.info("ALIGO_REDIS_URL not set, using in-process dict fallback")
            return None

        try:
            import redis.asyncio as aioredis
            _pool = aioredis.from_url(
                REDIS_URL,
                max_connections=20,
                socket_timeout=5,
                socket_connect_timeout=5,
                decode_responses=True,
            )
            await _pool.ping()
            logger.info("Redis connection pool initialized")
        except Exception as e:
            logger.warning("Redis init failed (%s), using in-process dict fallback", e)
            _pool = None

        return _pool


async def close_redis():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Redis connection pool closed")
