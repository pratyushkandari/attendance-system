import logging
import os
import time
from typing import Any, Dict, Optional, Tuple
from flask_sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

db: SQLAlchemy = SQLAlchemy()

# In-memory dictionary fallback store: key -> (value_str, expires_at_timestamp_or_none)
_memory_cache: Dict[str, Tuple[str, Optional[float]]] = {}


class SafeCacheStore:
    """
    Hybrid distributed Redis Cache with automatic in-memory fallback.

    Provides sub-millisecond key-value TTL operations. If Redis is unavailable or
    fails dynamically during a network partition, operations transparently degrade
    to an in-process TTL cache without raising exceptions or dropping check-in requests.
    """

    def __init__(self) -> None:
        self._redis: Any = None
        self._redis_available: bool = False
        self._init_redis()

    def _init_redis(self) -> None:
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            try:
                import redis
                self._redis = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1)
                self._redis.ping()
                self._redis_available = True
                logger.info("[CACHE] Successfully connected to distributed Redis store.")
            except Exception as e:
                self._redis_available = False
                logger.warning(f"[CACHE] Redis offline ({e}), operating with in-memory TTL store.")

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """
        Store a key-value pair with optional TTL expiration in seconds.
        """
        if self._redis_available and self._redis:
            try:
                return bool(self._redis.set(key, str(value), ex=ex))
            except Exception:
                self._redis_available = False

        expires_at = (time.time() + ex) if ex else None
        _memory_cache[key] = (str(value), expires_at)
        return True

    def get(self, key: str) -> Optional[str]:
        """
        Retrieve cached string value by key if active and unexpired.
        """
        if self._redis_available and self._redis:
            try:
                return self._redis.get(key)
            except Exception:
                self._redis_available = False

        if key in _memory_cache:
            val, exp = _memory_cache[key]
            if exp and time.time() > exp:
                del _memory_cache[key]
                return None
            return val
        return None

    def delete(self, key: str) -> bool:
        """
        Evict a key from Redis and local memory fallback.
        """
        if self._redis_available and self._redis:
            try:
                self._redis.delete(key)
            except Exception:
                self._redis_available = False
        _memory_cache.pop(key, None)
        return True


cache: SafeCacheStore = SafeCacheStore()