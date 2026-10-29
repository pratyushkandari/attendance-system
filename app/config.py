"""
Configuration Module for VisionAttend Application Gateway.

Loads environment variables from `.env` files via python-dotenv and
configures SQLAlchemy database pooling, cryptographic secrets, session cookie
hardening, login lockout limits, and biometric thresholds.
"""

import os
from pathlib import Path
from typing import Any

# Load environment configuration from .env file if available
try:
    from dotenv import load_dotenv
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
except ImportError:
    pass


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable ("1", "true", "yes", "on" are truthy)."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Keys that were published in this repository (old config default, `.env.example`,
# `docker-compose.yml`). Anyone can read them and forge sessions, JWTs and QR tokens,
# so `create_app` refuses to start with one of them, exactly as with an empty key.
PUBLISHED_SECRET_KEYS = frozenset({
    "dev-attendance-secret-key-change-in-production-2026",
    "production-secure-random-secret-key-xyz-987654321",
})

# Largest accepted request body. The biggest legitimate payload is one enrollment
# frame (a full-resolution JPEG data URL, well under 2 MB); the cap stops public
# endpoints from buffering arbitrarily large bodies in memory.
MAX_REQUEST_BYTES = 10 * 1024 * 1024


class Config:
    """
    Centralized application configuration object for Flask application factory.
    """
    # Core Cryptographic Master Secret (signs session cookies, JWTs and QR tokens).
    # Required: `create_app` raises if it is empty or a published key (outside tests).
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")

    MAX_CONTENT_LENGTH: int = MAX_REQUEST_BYTES

    # Session cookie hardening. HttpOnly keeps the cookie away from page scripts and
    # SameSite=Lax stops browsers from attaching it to cross-site POSTs (CSRF), which
    # matters because state-changing endpoints such as /clear_records rely on it.
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"

    # PostgreSQL / Cloud Database Connection URL
    db_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/attendence_db"
    )
    # Fix Render/Heroku postgres:// dialect compatibility for SQLAlchemy 2.0+
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI: str = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Production connection pool resiliency for cloud PostgreSQL instances
    # Mitigates dropped connections caused by cloud firewalls or AWS RDS idle timeouts
    if db_url and db_url.startswith("postgresql"):
        SQLALCHEMY_ENGINE_OPTIONS: dict[str, Any] = {
            "pool_pre_ping": True,
            "pool_recycle": 280,
            "pool_timeout": 20
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS: dict[str, Any] = {}

    # Admin self-registration. By default only the very first administrator can sign up
    # without being logged in (bootstrap); afterwards an existing admin must create new
    # admins. Set to true only for public demo deployments.
    ALLOW_PUBLIC_ADMIN_SIGNUP: bool = _env_flag("ALLOW_PUBLIC_ADMIN_SIGNUP", False)

    # Rate Limiting & Brute-Force Lockout
    LOCKOUT_THRESHOLD: int = int(os.getenv("LOCKOUT_THRESHOLD", "3"))
    LOCKOUT_DURATION_SECONDS: int = int(os.getenv("LOCKOUT_DURATION_SECONDS", "900"))

    # Biometric Inference Thresholds. 0.79 is the lowest match threshold that kept false
    # accepts at or below 0.1% on LFW; see docs/ACCURACY.md.
    FACE_MATCH_THRESHOLD: float = float(os.getenv("FACE_MATCH_THRESHOLD", "0.79"))
    MTCNN_CONFIDENCE_THRESHOLD: float = float(os.getenv("MTCNN_CONFIDENCE_THRESHOLD", "0.90"))
