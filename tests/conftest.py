import os
import sys
import pytest

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.extensions import db
from app.models.admin import Admin
from werkzeug.security import generate_password_hash

class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret-key-for-unit-tests"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False

@pytest.fixture
def app():
    app = create_app()
    app.config.from_object(TestConfig)

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
