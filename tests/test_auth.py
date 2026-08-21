import pytest
from app.routes.main import login_attempts, LOCK_THRESHOLD, generate_jwt_token


def test_login_success_returns_jwt(client):
    res = client.post("/login_admin", json={"email": "admin@test.com", "password": "password123"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "token" in data
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] == 86400


def test_login_invalid_password(client):
    res = client.post("/login_admin", json={"email": "admin@test.com", "password": "wrongpassword"})
    assert res.status_code == 401
    assert res.get_json()["status"] == "invalid"
    assert res.get_json()["attempts_left"] == 2


def test_account_lockout_after_three_attempts(client):
    email = "target@test.com"
    login_attempts.pop(email, None)

    # 3 consecutive failed attempts
    for _ in range(3):
        res = client.post("/login_admin", json={"email": email, "password": "wrong"})

    assert res.status_code == 403
    assert res.get_json()["status"] == "locked"


def test_unauthorized_api_access_blocked(client):
    res = client.get("/records")
    assert res.status_code == 401

    res = client.post("/clear_records")
    assert res.status_code == 401


def test_authorized_session_access_allowed(authenticated_client):
    res = authenticated_client.get("/records")
    assert res.status_code == 200


def test_authorized_jwt_bearer_access_allowed(client, app):
    # Generate valid JWT token
    with app.app_context():
        token = generate_jwt_token("admin@test.com")

    # Access protected endpoint with Bearer token header
    headers = {"Authorization": f"Bearer {token}"}
    res = client.get("/records", headers=headers)
    assert res.status_code == 200


def test_expired_jwt_bearer_access_blocked(client, app):
    # Generate expired JWT token (-10 seconds)
    with app.app_context():
        expired_token = generate_jwt_token("admin@test.com", expires_in_seconds=-10)

    headers = {"Authorization": f"Bearer {expired_token}"}
    res = client.get("/records", headers=headers)
    assert res.status_code == 401
    assert "expired" in res.get_json()["error"].lower()


def test_tampered_jwt_bearer_access_blocked(client, app):
    # Generate valid token and tamper with signature
    with app.app_context():
        token = generate_jwt_token("admin@test.com")
    tampered_token = token + "xyzcorrupt"

    headers = {"Authorization": f"Bearer {tampered_token}"}
    res = client.get("/records", headers=headers)
    assert res.status_code == 401
    assert "invalid" in res.get_json()["error"].lower()


def test_register_admin_weak_password_rejected(authenticated_client):
    # Weak password (<8 chars)
    res = authenticated_client.post("/register_admin", json={"email": "newadmin@test.com", "password": "123"})
    assert res.status_code == 400
    assert res.get_json()["status"] == "weak_password"

    # Weak password (no number)
    res = authenticated_client.post("/register_admin", json={"email": "newadmin@test.com", "password": "passwordonly"})
    assert res.status_code == 400
    assert res.get_json()["status"] == "weak_password"

