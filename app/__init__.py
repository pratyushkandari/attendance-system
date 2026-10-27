from typing import Type

from flask import Flask, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

from .config import PUBLISHED_SECRET_KEYS, Config
from .extensions import db


def create_app(config_class: Type[Config] = Config) -> Flask:
    """
    Application factory for the Attendance System microservice.

    Initializes Flask application instance, loads configuration, sets up SQLAlchemy
    database connection, registers modular blueprints, and mounts Prometheus telemetry.

    Note: ``db.create_all()`` runs here, so the configured database must be reachable
    when the app is created (tests pass a SQLite in-memory config class).

    Args:
        config_class: Configuration class defining runtime environment parameters.

    Returns:
        Configured Flask WSGI application instance.

    Raises:
        RuntimeError: ``SECRET_KEY`` is empty or one of the keys published in this
            repository (tests, which set ``TESTING``, are exempt).
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    secret_key = app.config.get("SECRET_KEY")
    if not app.config.get("TESTING") and (not secret_key or secret_key in PUBLISHED_SECRET_KEYS):
        raise RuntimeError(
            "SECRET_KEY is missing or is a value published in this repository; anyone could "
            "forge admin sessions, JWTs and QR tokens with it. Set SECRET_KEY to a long random "
            "value, e.g. the output of: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    db.init_app(app)

    # Import models after db init so their tables are registered before create_all()
    from .models import Admin, Attendance, Student  # noqa: F401

    # Import routes
    from .routes.attendance import attendance_bp
    from .routes.main import main_bp
    from .routes.student import student_bp

    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(attendance_bp)

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error):
        return jsonify({"error": "Request body is too large."}), 413

    # Initialize Prometheus observability metrics
    from .metrics import init_metrics
    init_metrics(app)

    with app.app_context():
        db.create_all()

    return app
