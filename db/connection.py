"""asyncpg 连接池管理"""
import asyncio
import json
import logging

from config import DATABASE_URL

logger = logging.getLogger(__name__)

try:
    import asyncpg
    _has_asyncpg = True
except ImportError:
    asyncpg = None  # type: ignore
    _has_asyncpg = False

_pool = None
_pool_lock = asyncio.Lock()


async def _init_connection(conn):
    """每个新连接注册 JSONB 编解码器，自动在 Python dict/list 和 JSONB 间转换。"""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def get_pool():
    """获取连接池；如果未配置 DATABASE_URL 则返回 None，走 JSON 文件回退。"""
    if not DATABASE_URL or not _has_asyncpg:
        return None

    global _pool
    if _pool is not None:
        return _pool

    async with _pool_lock:
        if _pool is not None:
            return _pool
        logger.info("Creating asyncpg connection pool...")
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=2,
            max_size=10,
            max_inactive_connection_lifetime=300,
            command_timeout=30,
            init=_init_connection,
        )
        logger.info("asyncpg connection pool created")
    return _pool


async def close_pool() -> None:
    """关闭连接池"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("asyncpg connection pool closed")
