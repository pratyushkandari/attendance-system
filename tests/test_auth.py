from app.routes.main import generate_jwt_token, reset_failed_logins


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
    reset_failed_logins(email)

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

    # Weak password (no special character)
    res = authenticated_client.post("/register_admin", json={"email": "newadmin@test.com", "password": "Password123"})
    assert res.status_code == 400
    assert res.get_json()["status"] == "weak_password"

    # Weak password (no uppercase)
    res = authenticated_client.post("/register_admin", json={"email": "newadmin@test.com", "password": "password@123"})
    assert res.status_code == 400
    assert res.get_json()["status"] == "weak_password"

    # Strong password (meets all criteria)
    res = authenticated_client.post("/register_admin", json={"email": "uniqueadmin@test.com", "password": "AdminSecure@2026!"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "registered"


def test_register_admin_invalid_email_format_rejected(authenticated_client):
    # Missing @ symbol
    res = authenticated_client.post("/register_admin", json={"email": "plainaddress.com", "password": "AdminSecure@2026!"})
    assert res.status_code == 400
    assert res.get_json()["status"] == "invalid_email"

    # Missing domain extension
    res = authenticated_client.post("/register_admin", json={"email": "user@nodomain", "password": "AdminSecure@2026!"})
    assert res.status_code == 400
    assert res.get_json()["status"] == "invalid_email"

    # Email with spaces
    res = authenticated_client.post("/register_admin", json={"email": "user name@example.com", "password": "AdminSecure@2026!"})
    assert res.status_code == 400
    assert res.get_json()["status"] == "invalid_email"


def test_password_is_never_stored_in_plaintext_and_is_cryptographically_hashed(app):
    from werkzeug.security import check_password_hash

    from app.models.admin import Admin

    with app.app_context():
        admin = Admin.query.filter_by(email="admin@test.com").first()
        assert admin is not None
        # Verify plaintext password is NEVER stored in database column
        assert admin.password != "password123"
        # Verify cryptographic salted hash format (scrypt or pbkdf2)
        assert admin.password.startswith(("scrypt:", "pbkdf2:sha256:", "argon2:"))
        # Verify mathematical hash resolution
        assert check_password_hash(admin.password, "password123") is True
        assert check_password_hash(admin.password, "wrongpassword") is False


def test_register_admin_closed_to_anonymous_users_after_bootstrap(client):
    # An admin already exists (seeded by the fixture), so anonymous signup is refused
    res = client.post("/register_admin", json={"email": "intruder@test.com", "password": "AdminSecure@2026!"})
    assert res.status_code == 403
    assert res.get_json()["status"] == "forbidden"


def test_register_admin_bootstrap_allows_first_admin(client):
    from app.extensions import db
    from app.models.admin import Admin

    # The fixture's app context is still active here, so this uses the same session
    # as the request handlers below.
    Admin.query.delete()
    db.session.commit()
    db.session.expunge_all()

    res = client.post("/register_admin", json={"email": "first@test.com", "password": "AdminSecure@2026!"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "registered"

    # Once the first admin exists, the door closes again
    res = client.post("/register_admin", json={"email": "second@test.com", "password": "AdminSecure@2026!"})
    assert res.status_code == 403


def test_register_admin_public_signup_flag(app, client):
    app.config["ALLOW_PUBLIC_ADMIN_SIGNUP"] = True
    res = client.post("/register_admin", json={"email": "demo@test.com", "password": "AdminSecure@2026!"})
    assert res.status_code == 200


def test_login_page_hides_signup_link_when_registration_closed(client, app):
    res = client.get("/")
    assert b'id="toggleText"' not in res.data

    app.config["ALLOW_PUBLIC_ADMIN_SIGNUP"] = True
    res = client.get("/")
    assert b'id="toggleText"' in res.data


def test_lockout_respects_configured_threshold(client, app):
    app.config["LOCKOUT_THRESHOLD"] = 5
    for _ in range(3):
        res = client.post("/login_admin", json={"email": "admin@test.com", "password": "wrong"})
    assert res.status_code == 401
    assert res.get_json()["attempts_left"] == 2


def test_locked_account_rejects_correct_password_until_expiry(client):
    for _ in range(3):
        client.post("/login_admin", json={"email": "admin@test.com", "password": "wrong"})

    res = client.post("/login_admin", json={"email": "admin@test.com", "password": "password123"})
    assert res.status_code == 403
    assert res.get_json()["status"] == "locked"


def test_successful_login_resets_failed_attempts(client):
    client.post("/login_admin", json={"email": "admin@test.com", "password": "wrong"})
    client.post("/login_admin", json={"email": "admin@test.com", "password": "wrong"})
    res = client.post("/login_admin", json={"email": "admin@test.com", "password": "password123"})
    assert res.status_code == 200

    res = client.post("/login_admin", json={"email": "admin@test.com", "password": "wrong"})
    assert res.get_json()["attempts_left"] == 2


def test_login_with_non_json_body_returns_json_error(client):
    res = client.post("/login_admin", data="email=a&password=b", content_type="application/x-www-form-urlencoded")
    assert res.status_code == 400
    assert res.get_json()["status"] == "invalid"


def test_session_cookie_is_httponly_and_samesite_lax(client):
    res = client.post("/login_admin", json={"email": "admin@test.com", "password": "password123"})
    cookie = res.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
