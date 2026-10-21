"""缓存层（Redis 可选，缺失时自动降级为不缓存）。"""

from .connection import get_redis, close_redis
from .cache_layer import CacheLayer
from .decorators import cached

__all__ = ["get_redis", "close_redis", "CacheLayer", "cached"]