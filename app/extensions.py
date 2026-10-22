import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

from flask_sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

db: SQLAlchemy = SQLAlchemy()

# In-memory dictionary fallback store: key -> (value_str, expires_at_timestamp_or_none)
_memory_cache: Dict[str, Tuple[str, Optional[float]]] = {}

# After a Redis failure, wait this long before trying Redis again. Without a retry the
# store would stay on the per-process fallback forever after one network blip.
REDIS_RETRY_INTERVAL_SECONDS: float = 30.0

# Expired fallback entries are normally dropped when read. Keys that are never read
# again (e.g. failed logins for random e-mail addresses) are swept once the store
# grows past this size, so the fallback cannot grow without bound.
MEMORY_CACHE_SWEEP_THRESHOLD: int = 10_000


def _sweep_expired_memory_entries() -> None:
    now = time.time()
    for key, (_, exp) in list(_memory_cache.items()):
        if exp and now > exp:
            _memory_cache.pop(key, None)


class SafeCacheStore:
    """
    Hybrid distributed Redis Cache with automatic in-memory fallback.

    If REDIS_URL is set and reachable, keys live in Redis and are shared by every
    worker and pod. If Redis is unset, unreachable at startup, or fails at runtime,
    operations transparently degrade to an in-process TTL dictionary instead of
    raising. While degraded, the store retries Redis every
    ``REDIS_RETRY_INTERVAL_SECONDS`` and switches back once it responds.

    Note: values written to the in-memory fallback during an outage are not copied
    into Redis when it comes back; they simply expire.
    """

    def __init__(self) -> None:
        self._redis: Any = None
        self._redis_available: bool = False
        self._next_retry_at: float = 0.0
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
                self._mark_unavailable(e)

    def _mark_unavailable(self, error: Exception) -> None:
        if self._redis_available or self._next_retry_at == 0.0:
            logger.warning(f"[CACHE] Redis offline ({error}), operating with in-memory TTL store.")
        self._redis_available = False
        self._next_retry_at = time.time() + REDIS_RETRY_INTERVAL_SECONDS

    def _use_redis(self) -> bool:
        """Return True if Redis should serve this call, re-probing it after a cooldown."""
        if self._redis is None:
            return False
        if self._redis_available:
            return True
        if time.time() >= self._next_retry_at:
            try:
                self._redis.ping()
                self._redis_available = True
                logger.info("[CACHE] Redis connection restored.")
            except Exception as e:
                self._mark_unavailable(e)
        return self._redis_available

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """
        Store a key-value pair with optional TTL expiration in seconds.
        """
        if self._use_redis():
            try:
                return bool(self._redis.set(key, str(value), ex=ex))
            except Exception as e:
                self._mark_unavailable(e)

        if len(_memory_cache) >= MEMORY_CACHE_SWEEP_THRESHOLD:
            _sweep_expired_memory_entries()
        expires_at = (time.time() + ex) if ex else None
        _memory_cache[key] = (str(value), expires_at)
        return True

    def get(self, key: str) -> Optional[str]:
        """
        Retrieve cached string value by key if active and unexpired.
        """
        if self._use_redis():
            try:
                return self._redis.get(key)
            except Exception as e:
                self._mark_unavailable(e)

        entry = _memory_cache.get(key)
        if entry is None:
            return None
        val, exp = entry
        if exp and time.time() > exp:
            # pop() rather than del: another thread may already have evicted it.
            _memory_cache.pop(key, None)
            return None
        return val

    def delete(self, key: str) -> bool:
        """
        Evict a key from Redis and local memory fallback.
        """
        if self._use_redis():
            try:
                self._redis.delete(key)
            except Exception as e:
                self._mark_unavailable(e)
        _memory_cache.pop(key, None)
        return True


cache: SafeCacheStore = SafeCacheStore()
