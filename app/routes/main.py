import base64
import binascii
import datetime
import hashlib
import json
import re
import time
import uuid
from functools import lru_cache, wraps
from typing import Any

import cv2
import jwt
import numpy as np
import segno
from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import cache, db
from app.models.admin import Admin

main_bp = Blueprint("main", __name__)


# ================= REQUEST PARSING HELPERS =================
def get_json_body() -> dict[str, Any]:
    """
    Return the JSON request body as a dict, or ``{}`` if it is missing or malformed.

    ``request.json`` raises (HTTP 415/400 HTML pages) when the body is not valid JSON;
    using ``silent=True`` lets each endpoint answer with its own JSON error instead.
    """
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def get_str_field(data: dict[str, Any], key: str) -> str:
    """Return ``data[key]`` stripped if it is a string, otherwise ``""``."""
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


def decode_image_payload(value: Any) -> np.ndarray | None:
    """
    Decode a ``data:image/...;base64,...`` string (as made by canvas.toDataURL) into a
    BGR image. Returns ``None`` for anything that is not a decodable image, so callers
    can answer with a client error instead of failing inside base64/OpenCV.
    """
    if not isinstance(value, str) or "," not in value:
        return None
    try:
        img_bytes = base64.b64decode(value.split(",", 1)[1], validate=True)
    except (binascii.Error, ValueError):
        return None
    if not img_bytes:
        return None
    return cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)


# ================= JWT TOKEN HELPERS =================
def generate_jwt_token(email, role="admin", expires_in_seconds=86400):
    """
    Generates a stateless HS256 signed JSON Web Token (JWT) valid for 24 hours.
    """
    secret = current_app.config["SECRET_KEY"]
    payload = {
        "sub": email,
        "role": role,
        "iat": datetime.datetime.utcnow(),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in_seconds)
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt_token(token):
    """
    Decodes and validates JWT token signature and expiration.
    """
    secret = current_app.config["SECRET_KEY"]
    return jwt.decode(token, secret, algorithms=["HS256"])


def is_admin_request() -> bool:
    """
    Return True if the current request carries admin credentials.

    Accepts either a valid ``Authorization: Bearer <jwt>`` header or an admin session
    cookie. Unlike ``admin_required`` this never short-circuits the request, so it can
    be used by endpoints that are public but behave differently for admins.
    """
    if "admin" in session:
        return True
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            decode_jwt_token(auth_header.split(" ", 1)[1].strip())
            return True
        except jwt.InvalidTokenError:
            return False
    return False


# ================= HYBRID AUTHENTICATION DECORATOR =================
def admin_required(f):
    """
    Hybrid Access Control Decorator:
    1. Checks 'Authorization: Bearer <jwt_token>' header (Stateless REST / Mobile / Postman).
    2. Falls back to Flask signed session cookie (Web Dashboard).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Check Bearer JWT Token Header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1].strip()
            try:
                decode_jwt_token(token)
                return f(*args, **kwargs)
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "JWT access token has expired."}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "Invalid JWT access token."}), 401

        # 2. Fall back to Session Cookie for Web UI
        if "admin" in session:
            return f(*args, **kwargs)

        # 3. Unauthorized: a browser navigating to a link (e.g. the CSV export) is sent to
        # the login page; API callers (fetch, curl, Postman send */* or JSON) get a JSON 401.
        # Admin HTML pages never get here: `block_unauthorized` redirects them first.
        if request.accept_mimetypes.best == "text/html":
            return redirect("/")
        return jsonify({"error": "Unauthorized. Bearer JWT token or Admin session required."}), 401
    return decorated_function


# ================= BRUTE FORCE PROTECTION =================
# Failed-login counters live in the shared SafeCacheStore (Redis when REDIS_URL is set,
# otherwise an in-process dict), so the lockout holds across Gunicorn workers and pods.
# Each record expires LOCKOUT_DURATION_SECONDS after the most recent failure.
# The read-modify-write below is not atomic; under heavy parallel guessing a few extra
# attempts may slip through before the lock engages, which is acceptable for this use.
def _lockout_settings() -> tuple[int, int]:
    """Return (threshold, duration_seconds) from the app config."""
    return (
        int(current_app.config.get("LOCKOUT_THRESHOLD", 3)),
        int(current_app.config.get("LOCKOUT_DURATION_SECONDS", 900)),
    )


def _lockout_key(email: str) -> str:
    return f"login_failures:{email}"


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """A hash of a random password with the same cost as real admin hashes."""
    return generate_password_hash(uuid.uuid4().hex)


def _get_failure_record(email: str) -> dict[str, float]:
    raw = cache.get(_lockout_key(email))
    if raw:
        try:
            record = json.loads(raw)
            return {"count": int(record["count"]), "locked_at": float(record["locked_at"])}
        except (ValueError, KeyError, TypeError):
            pass
    return {"count": 0, "locked_at": 0.0}


def reset_failed_logins(email: str) -> None:
    """Clear the failed-login counter for ``email`` (called after a successful login)."""
    cache.delete(_lockout_key(email))


def record_failed_login(email: str) -> int:
    """Increment and persist the failed-login counter; return the new count."""
    threshold, duration = _lockout_settings()
    record = _get_failure_record(email)
    record["count"] += 1
    if record["count"] >= threshold and not record["locked_at"]:
        record["locked_at"] = time.time()
    cache.set(_lockout_key(email), json.dumps(record), ex=duration)
    return int(record["count"])


def is_account_locked(email: str) -> tuple[bool, int]:
    """
    Return ``(locked, remaining_minutes)`` for ``email``.

    An expired lock is cleared so the user gets a fresh set of attempts.
    """
    threshold, duration = _lockout_settings()
    record = _get_failure_record(email)
    if record["count"] >= threshold:
        time_elapsed = time.time() - record["locked_at"]
        if time_elapsed < duration:
            remaining_minutes = int((duration - time_elapsed) // 60) + 1
            return True, remaining_minutes
        # Auto-unlock expired lockout
        reset_failed_logins(email)
    return False, 0


# ================= GLOBAL ROUTE PROTECTION =================
@main_bp.before_app_request
def block_unauthorized():
    """
    Redirect anonymous browsers away from admin HTML pages.

    ``admin_required`` also guards these routes, but it answers JSON 401 for paths that
    share a prefix with API endpoints (e.g. /register_page, /records_page). This hook
    guarantees a redirect to the login page for every admin HTML page instead.
    """
    protected_html_routes = [
        "/dashboard",
        "/register_page",
        "/capture",
        "/recognize_page",
        "/records_page",
        "/qr_session"
    ]

    if request.path in protected_html_routes:
        if "admin" not in session:
            return redirect("/")


# ================= DYNAMIC QR TOKEN HELPERS =================
# Timing model for the rotating classroom QR code:
#   * the kiosk fetches a new token every 5 s and the API advertises 15 s of validity;
#   * /verify_qr_token accepts tokens up to 30 s old (15 s scan window + network leeway);
#   * endpoints used after the student has typed their roll number (student lookup and
#     /mark_attendance) accept up to 35 s so a slow confirmation still succeeds.
QR_TOKEN_TTL_SECONDS = 15
QR_TOKEN_VERIFY_MAX_AGE = 30
QR_TOKEN_SUBMIT_MAX_AGE = 35


def get_qr_serializer():
    # itsdangerous signs with HMAC-SHA1 unless told otherwise; the QR channel is
    # documented (and audited) as HMAC-SHA256.
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt="qr-attendance-token",
        signer_kwargs={"digest_method": hashlib.sha256},
    )


def check_qr_token(token: str | None, max_age: int) -> tuple[bool, str]:
    """
    Validate a signed QR session token.

    Returns:
        ``(True, "")`` if the signature is valid and the token is younger than
        ``max_age`` seconds, otherwise ``(False, <user-facing reason>)``.
    """
    if not token or not isinstance(token, str):
        return False, "Missing QR token."
    try:
        get_qr_serializer().loads(token, max_age=max_age)
        return True, ""
    except SignatureExpired:
        return False, "QR code expired. Please rescan."
    except BadSignature:
        return False, "Invalid QR code signature."


@main_bp.route("/generate_qr_token", methods=["GET"])
@admin_required
def generate_qr_token():
    """
    Generates a cryptographically signed time-based token for dynamic QR session.
    Token is advertised as valid for 15 seconds (see the timing model above).

    Returns the token, the student check-in URL that embeds it, and that URL rendered
    as a QR code (``qr_svg``, an SVG data URI ready for an ``<img src>``).
    """
    serializer = get_qr_serializer()
    payload = {
        "nonce": uuid.uuid4().hex[:12],
        "created_at": time.time()
    }
    token = serializer.dumps(payload)
    checkin_url = url_for("main.qr_mobile", token=token, _external=True)
    # Rendered here so live check-in URLs never leave the server; a third-party QR image
    # API would receive a usable token on every rotation.
    qr_svg = segno.make(checkin_url, error="m").svg_data_uri(border=4, omitsize=True, light="white")
    return jsonify({
        "status": "success",
        "token": token,
        "expires_in": QR_TOKEN_TTL_SECONDS,
        "checkin_url": checkin_url,
        "qr_svg": qr_svg,
    })


@main_bp.route("/verify_qr_token", methods=["POST"])
def verify_qr_token():
    """
    Validates dynamic QR token submitted from mobile browser.
    """
    token = get_json_body().get("token")
    if not token:
        return jsonify({"valid": False, "error": "Missing QR token"}), 400

    is_valid, error = check_qr_token(token, QR_TOKEN_VERIFY_MAX_AGE)
    if not is_valid:
        return jsonify({"valid": False, "error": error}), 400
    return jsonify({"valid": True})


# ================= HTML PAGE ROUTES =================

def admin_signup_open() -> bool:
    """True if an anonymous visitor may create an admin account right now."""
    if current_app.config.get("ALLOW_PUBLIC_ADMIN_SIGNUP"):
        return True
    return Admin.query.count() == 0


@main_bp.route("/")
def home():
    if "admin" in session:
        return redirect("/dashboard")
    return render_template("admin_login.html", allow_admin_signup=admin_signup_open())


@main_bp.route("/dashboard")
@admin_required
def dashboard():
    response = make_response(render_template("dashboard.html"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@main_bp.route("/register_page")
@admin_required
def register_page():
    return render_template("register.html")


@main_bp.route("/capture")
@admin_required
def capture():
    return render_template("capture.html")


@main_bp.route("/recognize_page")
@admin_required
def recognize():
    return render_template("recognize.html")


@main_bp.route("/records_page")
@admin_required
def records():
    return render_template("records.html")


@main_bp.route("/qr_session")
@admin_required
def qr():
    return render_template("qr_session.html")


@main_bp.route("/qr_mobile")
def qr_mobile():
    return render_template("qr_mobile.html")


@main_bp.route("/qr_verify")
def qr_verify():
    return render_template("qr_verify.html")


@main_bp.route("/qr_result")
def qr_result():
    return render_template("qr_result.html")


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def validate_email_format(email):
    """
    Validates email format with a pragmatic subset of RFC 5322 rules:
    - Must not be empty, max 254 characters
    - Must contain valid local-part and valid domain
    - TLD must be at least 2 alpha characters
    - Disallows invalid characters, spaces, and consecutive dots
    """
    if not email or not isinstance(email, str):
        return False, "Email address is required."

    email = email.strip()
    if len(email) > 254:
        return False, "Email address exceeds maximum length of 254 characters."

    if " " in email:
        return False, "Email address cannot contain spaces."

    if ".." in email:
        return False, "Email address cannot contain consecutive dots."

    if "@" not in email:
        return False, "Invalid email format: missing '@' symbol (e.g. user@example.com)."

    parts = email.split("@")
    if len(parts) != 2:
        return False, "Invalid email format: contains multiple '@' symbols."

    local, domain = parts
    if not local or len(local) > 64:
        return False, "Invalid email format: username before '@' is invalid."

    if not domain or "." not in domain:
        return False, "Invalid email format: missing domain (e.g. user@example.com)."

    tld = domain.split(".")[-1]
    if len(tld) < 2 or not tld.isalpha():
        return False, "Invalid email format: invalid top-level domain extension (.com, .edu, etc.)."

    if not EMAIL_REGEX.match(email):
        return False, "Invalid email format. Please provide a valid email (e.g. user@example.com)."

    return True, ""


def validate_password_strength(password, email=""):
    """
    Enforces the platform password policy:
    1. Minimum 8 characters, maximum 128 characters (NIST 800-63B length guidance)
    2. At least one lowercase letter (a-z)
    3. At least one uppercase letter (A-Z)
    4. At least one numeric digit (0-9)
    5. At least one special character (!@#$%^&*...)
    6. Disallows common dictionary/trivial passwords
    7. Disallows password containing the email prefix

    Rules 2-5 are composition rules that go beyond NIST 800-63B (which does not
    require them); they are kept as an institutional policy choice.
    """
    if not password:
        return False, "Password cannot be empty."
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if len(password) > 128:
        return False, "Password cannot exceed 128 characters."
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter (a-z)."
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter (A-Z)."
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one numeric digit (0-9)."

    special_chars = set("!@#$%^&*()_+-=[]{}|;:,.<>?/~`'\"\\")
    if not any(c in special_chars for c in password):
        return False, "Password must contain at least one special symbol (e.g. !@#$%^&*)."

    # Common trivial blocklist
    common_weak = {
        "password123!", "admin12345!", "welcome123!", "qwerty12345!",
        "pass@123456", "admin@12345", "administrator"
    }
    if password.lower() in common_weak:
        return False, "Password is too common or easily guessable. Please choose a stronger password."

    # Prevent email prefix usage
    if email and "@" in email:
        prefix = email.split("@")[0].lower()
        if len(prefix) >= 3 and prefix in password.lower():
            return False, "Password cannot contain your email username or handle."

    return True, ""


@main_bp.route("/register_admin", methods=["POST"])
def register_admin():
    """
    Create an administrator account.

    Anyone may create the *first* admin (bootstrap). Once an admin exists, the caller
    must be an authenticated admin (session or Bearer JWT), unless the deployment sets
    ``ALLOW_PUBLIC_ADMIN_SIGNUP=true`` (intended for public demos only).
    """
    if not admin_signup_open() and not is_admin_request():
        return jsonify({
            "status": "forbidden",
            "message": "Administrator registration is closed. Ask an existing administrator to create your account."
        }), 403

    data = get_json_body()
    email = get_str_field(data, "email").lower()
    password = data.get("password") if isinstance(data.get("password"), str) else ""

    if not email or not password:
        return jsonify({"status": "error", "message": "Email and password are required."}), 400

    # Email format validation (also bounded by the 120-char `admins.email` column)
    is_valid_email, email_error_msg = validate_email_format(email)
    if is_valid_email and len(email) > 120:
        is_valid_email, email_error_msg = False, "Email address cannot exceed 120 characters."
    if not is_valid_email:
        return jsonify({"status": "invalid_email", "message": email_error_msg}), 400

    # Enterprise password complexity validation
    is_valid_pwd, pwd_error_msg = validate_password_strength(password, email=email)
    if not is_valid_pwd:
        return jsonify({"status": "weak_password", "message": pwd_error_msg}), 400

    # Check duplicate email
    existing = Admin.query.filter_by(email=email).first()
    if existing:
        return jsonify({"status": "exists", "message": "An administrator with this email already exists."}), 400

    hashed_password = generate_password_hash(password)
    new_admin = Admin(email=email, password=hashed_password)
    db.session.add(new_admin)
    db.session.commit()

    return jsonify({"status": "registered", "message": "Admin registered successfully."}), 200


@main_bp.route("/login_admin", methods=["POST"])
def login_admin():
    data = get_json_body()
    email = get_str_field(data, "email").lower()
    password = data.get("password") if isinstance(data.get("password"), str) else ""

    if not email or not password:
        return jsonify({"status": "invalid", "message": "Missing email or password."}), 400

    # Email format validation
    is_valid_email, email_err = validate_email_format(email)
    if not is_valid_email:
        return jsonify({"status": "invalid_email", "message": email_err}), 400

    threshold, duration = _lockout_settings()
    locked, remaining_min = is_account_locked(email)
    if locked:
        return jsonify({
            "status": "locked",
            "message": f"Account locked due to {threshold} failed attempts. Try again in {remaining_min} minutes."
        }), 403

    admin = Admin.query.filter_by(email=email).first()

    # Always run one scrypt check, even for unknown emails: skipping it made failed logins
    # for unknown addresses ~100x faster, which revealed which emails belong to admins.
    password_ok = check_password_hash(admin.password if admin else _dummy_password_hash(), password)

    if admin and password_ok:
        # Reset failed attempts
        reset_failed_logins(email)
        session["admin"] = admin.email

        # Generate Stateless JWT Token
        jwt_token = generate_jwt_token(admin.email)

        return jsonify({
            "status": "success",
            "token": jwt_token,
            "token_type": "Bearer",
            "expires_in": 86400,
            "user": admin.email
        })

    # Increment attempt counter (also for unknown emails, so responses do not reveal
    # which addresses belong to real administrators)
    failed_count = record_failed_login(email)

    if failed_count >= threshold:
        return jsonify({
            "status": "locked",
            "message": f"Account locked after {threshold} failed attempts. Locked for {max(1, duration // 60)} minutes."
        }), 403

    attempts_left = threshold - failed_count
    return jsonify({
        "status": "invalid",
        "attempts_left": attempts_left,
        "message": f"Invalid credentials. {attempts_left} attempts left."
    }), 401


@main_bp.route("/logout")
def logout():
    session.clear()
    response = redirect("/")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response
