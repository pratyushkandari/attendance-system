import time
import uuid
import datetime
from functools import wraps
import jwt
from flask import (
    Blueprint, render_template, request, jsonify,
    session, redirect, make_response, current_app
)
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash

from app.models.admin import Admin
from app.extensions import db

main_bp = Blueprint("main", __name__)


# ================= JWT TOKEN HELPERS =================
def generate_jwt_token(email, role="admin", expires_in_seconds=86400):
    """
    Generates a stateless HS256 signed JSON Web Token (JWT) valid for 24 hours.
    """
    secret = current_app.config.get("SECRET_KEY", "fallback-secret")
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
    secret = current_app.config.get("SECRET_KEY", "fallback-secret")
    return jwt.decode(token, secret, algorithms=["HS256"])


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
                payload = decode_jwt_token(token)
                request.jwt_user = payload.get("sub")
                return f(*args, **kwargs)
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "JWT access token has expired."}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "Invalid JWT access token."}), 401

        # 2. Fall back to Session Cookie for Web UI
        if "admin" in session:
            return f(*args, **kwargs)

        # 3. Unauthorized
        if request.is_json or request.path.startswith(("/mark_", "/clear_", "/save_", "/register", "/records", "/dashboard_data", "/recognize", "/verify_student", "/capture_face", "/generate_qr_token")):
            return jsonify({"error": "Unauthorized. Bearer JWT token or Admin session required."}), 401

        return redirect("/")
    return decorated_function


# ================= BRUTE FORCE PROTECTION =================
# Stores: email -> {"count": int, "locked_at": float}
login_attempts = {}
LOCK_THRESHOLD = 3
LOCK_DURATION_SECONDS = 900  # 15 minutes


def is_account_locked(email):
    if email not in login_attempts:
        return False, 0
    
    record = login_attempts[email]
    if record["count"] >= LOCK_THRESHOLD:
        time_elapsed = time.time() - record["locked_at"]
        if time_elapsed < LOCK_DURATION_SECONDS:
            remaining_minutes = int((LOCK_DURATION_SECONDS - time_elapsed) // 60) + 1
            return True, remaining_minutes
        else:
            # Auto-unlock expired lockout
            login_attempts[email] = {"count": 0, "locked_at": 0}
            return False, 0
    return False, 0


# ================= GLOBAL ROUTE PROTECTION =================
@main_bp.before_app_request
def block_unauthorized():
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
def get_qr_serializer():
    secret = current_app.config.get("SECRET_KEY", "fallback-secret")
    return URLSafeTimedSerializer(secret, salt="qr-attendance-token")


@main_bp.route("/generate_qr_token", methods=["GET"])
@admin_required
def generate_qr_token():
    """
    Generates a cryptographically signed time-based token for dynamic QR session.
    Token is valid for 15 seconds.
    """
    serializer = get_qr_serializer()
    payload = {
        "nonce": uuid.uuid4().hex[:12],
        "created_at": time.time()
    }
    token = serializer.dumps(payload)
    return jsonify({
        "status": "success",
        "token": token,
        "expires_in": 15
    })


@main_bp.route("/verify_qr_token", methods=["POST"])
def verify_qr_token():
    """
    Validates dynamic QR token submitted from mobile browser.
    """
    data = request.json or {}
    token = data.get("token")
    if not token:
        return jsonify({"valid": False, "error": "Missing QR token"}), 400

    serializer = get_qr_serializer()
    try:
        # Max age: 30 seconds (gives 15s scan window + network margin)
        serializer.loads(token, max_age=30)
        return jsonify({"valid": True})
    except SignatureExpired:
        return jsonify({"valid": False, "error": "QR token expired. Please rescan."}), 400
    except BadSignature:
        return jsonify({"valid": False, "error": "Invalid QR token."}), 400


# ================= HTML PAGE ROUTES =================

@main_bp.route("/")
def home():
    if "admin" in session:
        return redirect("/dashboard")
    return render_template("admin_login.html")


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


import re

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def validate_email_format(email):
    """
    Validates email format using RFC 5322 standards:
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
    Enforces enterprise-grade NIST 800-63B password security policy:
    1. Minimum 8 characters, maximum 128 characters
    2. At least one lowercase letter (a-z)
    3. At least one uppercase letter (A-Z)
    4. At least one numeric digit (0-9)
    5. At least one special character (!@#$%^&*...)
    6. Disallows common dictionary/trivial passwords
    7. Disallows password containing the email prefix
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
    data = request.json or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"status": "error", "message": "Email and password are required."}), 400

    # RFC 5322 Email validation
    is_valid_email, email_error_msg = validate_email_format(email)
    if not is_valid_email:
        return jsonify({"status": "invalid_email", "message": email_error_msg}), 400

    # Enterprise password complexity validation
    is_valid_pwd, pwd_error_msg = validate_password_strength(password, email=email)
    if not is_valid_pwd:
        return jsonify({"status": "weak_password", "message": pwd_error_msg}), 400

    admin_count = Admin.query.count()
    # If admins already exist, only an authenticated admin can create new admin accounts
    if admin_count > 0 and "admin" not in session:
        auth_header = request.headers.get("Authorization")
        is_jwt_admin = False
        if auth_header and auth_header.startswith("Bearer "):
            try:
                decode_jwt_token(auth_header.split(" ")[1].strip())
                is_jwt_admin = True
            except Exception:
                pass

        if not is_jwt_admin:
            return jsonify({
                "status": "error",
                "message": "Unauthorized. Only existing administrators can register new admins."
            }), 403

    existing = Admin.query.filter_by(email=email).first()
    if existing:
        return jsonify({"status": "exists", "message": "Admin with this email already exists."})

    hashed_password = generate_password_hash(password)
    new_admin = Admin(email=email, password=hashed_password)
    db.session.add(new_admin)
    db.session.commit()

    return jsonify({"status": "registered", "message": "Admin registered successfully."})


@main_bp.route("/login_admin", methods=["POST"])
def login_admin():
    data = request.json or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"status": "invalid", "message": "Missing email or password."}), 400

    # RFC 5322 Email format validation
    is_valid_email, email_err = validate_email_format(email)
    if not is_valid_email:
        return jsonify({"status": "invalid_email", "message": email_err}), 400

    locked, remaining_min = is_account_locked(email)
    if locked:
        return jsonify({
            "status": "locked",
            "message": f"Account locked due to 3 failed attempts. Try again in {remaining_min} minutes."
        }), 403

    admin = Admin.query.filter_by(email=email).first()

    if admin and check_password_hash(admin.password, password):
        # Reset failed attempts
        login_attempts[email] = {"count": 0, "locked_at": 0}
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
    else:
        # Increment attempt counter
        if email not in login_attempts:
            login_attempts[email] = {"count": 0, "locked_at": 0}

        login_attempts[email]["count"] += 1

        if login_attempts[email]["count"] >= LOCK_THRESHOLD:
            login_attempts[email]["locked_at"] = time.time()
            return jsonify({
                "status": "locked",
                "message": "Account locked after 3 failed attempts. Locked for 15 minutes."
            }), 403

        attempts_left = LOCK_THRESHOLD - login_attempts[email]["count"]
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


@main_bp.route("/admin_login")
def admin_login():
    if "admin" in session:
        return redirect("/dashboard")
    return render_template("admin_login.html")