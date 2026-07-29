"""数据库模块"""
from .connection import get_pool, close_pool

__all__ = ["get_pool", "close_pool"]
