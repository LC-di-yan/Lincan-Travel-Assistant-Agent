"""Redis 连接管理。

设计原则：Redis 是可选加速器，不参与正确性。
- 未配置 / 连不上 / 没装 redis 包时，get_redis() 返回 None，调用方自动降级。
- 进程内只建立一个连接池，重复调用直接复用。
"""
import logging
import os

logger = logging.getLogger(__name__)

_client = None          # redis.asyncio.Redis | None
_attempted = False      # 是否已经尝试过连接（失败后不再重试，避免每次请求都卡 5 秒）


def _redis_url() -> str:
    return (
        os.environ.get("ALIGO_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or ""
    ).strip()


async def get_redis():
    """返回可用的 Redis 客户端；不可用时返回 None（永不抛异常）。"""
    global _client, _attempted

    if _client is not None:
        return _client
    if _attempted:
        return None

    _attempted = True
    url = _redis_url()
    if not url:
        logger.info("ALIGO_REDIS_URL not set, Redis cache disabled")
        return None

    try:
        import redis.asyncio as aioredis
    except Exception as exc:  # redis 包未安装
        logger.warning(f"redis package unavailable ({exc}), cache disabled")
        return None

    try:
        client = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await client.ping()
        _client = client
        logger.info("Redis cache initialized")
        return _client
    except Exception as exc:
        logger.warning(f"Redis unavailable ({exc}), cache disabled")
        return None


async def close_redis():
    """关闭连接池。"""
    global _client, _attempted
    client, _client = _client, None
    _attempted = False
    if client is None:
        return
    try:
        await client.aclose()
    except Exception:
        try:
            await client.close()
        except Exception:
            pass