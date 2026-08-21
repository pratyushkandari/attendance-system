import os
import time
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# In-memory dictionary fallback store
_memory_cache = {}


class SafeCacheStore:
    """
    Hybrid distributed Redis Cache with automatic in-memory fallback.
    Delivers sub-millisecond key-value TTL operations whether Redis is online or offline.
    """
    def __init__(self):
        self._redis = None
        self._redis_available = False
        self._init_redis()

    def _init_redis(self):
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            try:
                import redis
                self._redis = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1)
                self._redis.ping()
                self._redis_available = True
                print("[CACHE] Successfully connected to distributed Redis store.")
            except Exception as e:
                self._redis_available = False
                print(f"[CACHE] Redis offline ({e}), operating with in-memory TTL store.")

    def set(self, key, value, ex=None):
        if self._redis_available and self._redis:
            try:
                return self._redis.set(key, str(value), ex=ex)
            except Exception:
                self._redis_available = False

        expires_at = (time.time() + ex) if ex else None
        _memory_cache[key] = (str(value), expires_at)
        return True

    def get(self, key):
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

    def delete(self, key):
        if self._redis_available and self._redis:
            try:
                return self._redis.delete(key)
            except Exception:
                self._redis_available = False
        _memory_cache.pop(key, None)
        return True


cache = SafeCacheStore()