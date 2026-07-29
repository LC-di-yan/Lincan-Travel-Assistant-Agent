"""Redis 缓存层 — 可选启用，自动降级到进程内 dict"""
from .cache_layer import CacheLayer
from .connection import get_redis, close_redis
from .decorators import cached, TTL

__all__ = ["CacheLayer", "get_redis", "close_redis", "cached", "TTL"]
