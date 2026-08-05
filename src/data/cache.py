"""
数据缓存模块
使用 diskcache 缓存 API 响应，减少重复请求
"""
from __future__ import annotations

import hashlib
import json
from functools import wraps
from typing import Any, Callable

import diskcache
from loguru import logger

from src.utils.config import config


class DataCache:
    """API 响应缓存"""

    def __init__(self) -> None:
        self.cache = diskcache.Cache(str(config.CACHE_DIR))
        self.default_ttl = 3600  # 默认 1 小时过期

    def _make_key(self, *args: Any, **kwargs: Any) -> str:
        """根据参数生成缓存键"""
        raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        return self.cache.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl or self.default_ttl
        self.cache.set(key, value, expire=ttl)

    def cached(self, ttl: int | None = None, prefix: str = ""):
        """缓存装饰器

        Usage:
            @cache.cached(ttl=600, prefix="team")
            def get_team(id): ...
        """

        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                cache_key = prefix + "_" + self._make_key(*args, **kwargs)
                cached = self.get(cache_key)
                if cached is not None:
                    logger.debug(f"缓存命中: {cache_key[:16]}...")
                    return cached
                result = func(*args, **kwargs)
                self.set(cache_key, result, ttl)
                return result

            return wrapper

        return decorator

    def clear(self) -> None:
        """清空所有缓存"""
        self.cache.clear()
        logger.info("缓存已清空")


# 全局缓存实例
cache = DataCache()
