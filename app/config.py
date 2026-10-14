"""
Configuration Module for VisionAttend Application Gateway.

Loads environment variables from `.env` files via python-dotenv and
configures SQLAlchemy database pooling, cryptographic secrets, rate limiting,
and biometric thresholds.
"""

import os
from pathlib import Path
from typing import Dict, Any

# Load environment configuration from .env file if available
try:
    from dotenv import load_dotenv
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
except ImportError:
    pass


class Config:
    """
    Centralized application configuration object for Flask application factory.
    """
    # Core Cryptographic Master Secret
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-attendance-secret-key-change-in-production-2026")

    # PostgreSQL / Cloud Database Connection URL
    db_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgresql@localhost:5432/attendence_db"
    )
    # Fix Render/Heroku postgres:// dialect compatibility for SQLAlchemy 2.0+
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI: str = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Production connection pool resiliency for cloud PostgreSQL instances
    # Mitigates dropped connections caused by cloud firewalls or AWS RDS idle timeouts
    if db_url and db_url.startswith("postgresql"):
        SQLALCHEMY_ENGINE_OPTIONS: Dict[str, Any] = {
            "pool_pre_ping": True,
            "pool_recycle": 280,
            "pool_timeout": 20
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS: Dict[str, Any] = {}

    # Distributed Redis Cache URL
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Rate Limiting & Brute-Force Lockout
    LOCKOUT_THRESHOLD: int = int(os.getenv("LOCKOUT_THRESHOLD", "3"))
    LOCKOUT_DURATION_SECONDS: int = int(os.getenv("LOCKOUT_DURATION_SECONDS", "900"))

    # Biometric Inference Thresholds
    FACE_MATCH_THRESHOLD: float = float(os.getenv("FACE_MATCH_THRESHOLD", "0.70"))
    MTCNN_CONFIDENCE_THRESHOLD: float = float(os.getenv("MTCNN_CONFIDENCE_THRESHOLD", "0.90"))
    EAR_BLINK_THRESHOLD: float = float(os.getenv("EAR_BLINK_THRESHOLD", "0.22"))