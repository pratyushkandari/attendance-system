import os
from pathlib import Path

# Load environment configuration from .env file if available
try:
    from dotenv import load_dotenv
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
except ImportError:
    pass


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-attendance-secret-key-change-in-production-2026")

    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgresql@localhost:5432/attendence_db"
    )
    # Fix Render/Heroku postgres:// dialect compatibility for SQLAlchemy 2.0+
    if db_url and db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Production connection pool resiliency for cloud PostgreSQL instances
    if db_url and db_url.startswith("postgresql"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": 280,
            "pool_timeout": 20
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {}