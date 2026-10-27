import os
import sys

import pytest

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.extensions import _memory_cache, cache, db  # noqa: E402
from app.models.admin import Admin  # noqa: E402

# Tests must never talk to a developer's Redis (or leak keys into it), so force the
# cache onto its in-process fallback store.
cache._redis = None
cache._redis_available = False


class TestConfig(Config):
    """
    Isolated configuration for the test suite.

    It must be passed to ``create_app`` (not applied afterwards): Flask-SQLAlchemy
    builds its engine during ``init_app`` and ``create_app`` immediately runs
    ``db.create_all()``, so a late override would still hit the PostgreSQL URL from
    the environment, and ``drop_all()`` in teardown would wipe a real database.
    """
    TESTING = True
    # At least 32 bytes: PyJWT warns about shorter HS256 keys (RFC 7518 section 3.2)
    SECRET_KEY = "test-secret-key-for-unit-tests-0123456789"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS: dict = {}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ALLOW_PUBLIC_ADMIN_SIGNUP = False
    LOCKOUT_THRESHOLD = 3
    LOCKOUT_DURATION_SECONDS = 900


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear lockout counters and other cached state between tests."""
    _memory_cache.clear()
    yield
    _memory_cache.clear()


@pytest.fixture
def app():
    app = create_app(TestConfig)

    with app.app_context():
        db.create_all()
        # Seed test admin
        admin = Admin(email="admin@test.com", password=generate_password_hash("password123"))
        db.session.add(admin)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def authenticated_client(app, client):
    with client.session_transaction() as session:
        session["admin"] = "admin@test.com"
    return client
