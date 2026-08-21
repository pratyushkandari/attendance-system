import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-attendance-secret-key-change-in-production-2026")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgresql@localhost:5432/attendence_db"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False