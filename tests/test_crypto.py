import time

import pytest
from itsdangerous import BadSignature, SignatureExpired

from app.routes.main import get_qr_serializer


def test_qr_token_generation_and_verification(app):
    with app.app_context():
        serializer = get_qr_serializer()
        payload = {"nonce": "test12345", "created_at": time.time()}
        token = serializer.dumps(payload)

        # Immediate verification should succeed
        decoded = serializer.loads(token, max_age=15)
        assert decoded["nonce"] == "test12345"

def test_qr_token_expired(app):
    with app.app_context():
        serializer = get_qr_serializer()
        payload = {"nonce": "test_expired", "created_at": time.time()}
        token = serializer.dumps(payload)

        # Negative max_age guarantees instantaneous expiration test
        with pytest.raises(SignatureExpired):
            serializer.loads(token, max_age=-1)

def test_qr_token_tampered(app):
    with app.app_context():
        serializer = get_qr_serializer()
        payload = {"nonce": "test_tamper", "created_at": time.time()}
        token = serializer.dumps(payload)

        # Tampered token
        tampered_token = token + "xyz"
        with pytest.raises(BadSignature):
            serializer.loads(tampered_token, max_age=15)

def test_verify_qr_token_api(client):
    with client.application.app_context():
        serializer = get_qr_serializer()
        token = serializer.dumps({"nonce": "api_test", "created_at": time.time()})

    res = client.post("/verify_qr_token", json={"token": token})
    assert res.status_code == 200
    assert res.get_json()["valid"] is True


def test_safe_cache_store_ttl_and_eviction():
    from app.extensions import cache

    # Set key with 2-second TTL
    cache.set("test_qr_nonce_123", "used", ex=2)
    assert cache.get("test_qr_nonce_123") == "used"

    # Delete key
    cache.delete("test_qr_nonce_123")
    assert cache.get("test_qr_nonce_123") is None



def test_safe_cache_store_falls_back_and_reconnects_to_redis(monkeypatch):
    from app import extensions
    from app.extensions import SafeCacheStore

    class FlakyRedis:
        def __init__(self):
            self.up = False
            self.store = {}

        def _check(self):
            if not self.up:
                raise ConnectionError("redis down")

        def ping(self):
            self._check()
            return True

        def set(self, key, value, ex=None):
            self._check()
            self.store[key] = value
            return True

        def get(self, key):
            self._check()
            return self.store.get(key)

        def delete(self, key):
            self._check()
            self.store.pop(key, None)

    store = SafeCacheStore()
    fake = FlakyRedis()
    store._redis = fake
    store._redis_available = True

    # Redis fails mid-flight: the write lands in the in-memory fallback instead of raising
    assert store.set("k", "v1") is True
    assert store.get("k") == "v1"
    assert store._redis_available is False

    # After the retry interval Redis is probed again and used once it answers
    fake.up = True
    monkeypatch.setattr(extensions, "REDIS_RETRY_INTERVAL_SECONDS", 0)
    store._next_retry_at = 0
    assert store.set("k", "v2") is True
    assert store._redis_available is True
    assert fake.store["k"] == "v2"
    assert store.get("k") == "v2"


def test_memory_fallback_sweeps_expired_entries(monkeypatch):
    from app import extensions
    from app.extensions import _memory_cache, cache

    monkeypatch.setattr(extensions, "MEMORY_CACHE_SWEEP_THRESHOLD", 3)
    _memory_cache["stale_1"] = ("x", 1.0)  # expired long ago
    _memory_cache["stale_2"] = ("x", 1.0)
    _memory_cache["live"] = ("x", None)

    cache.set("new_key", "v", ex=60)

    assert "stale_1" not in _memory_cache and "stale_2" not in _memory_cache
    assert cache.get("live") == "x"
    assert cache.get("new_key") == "v"
