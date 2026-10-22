import logging
from typing import Type

from flask import Flask

from .config import DEFAULT_SECRET_KEY, Config
from .extensions import db

logger = logging.getLogger(__name__)


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
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    if app.config.get("SECRET_KEY") == DEFAULT_SECRET_KEY and not app.config.get("TESTING"):
        logger.warning(
            "SECRET_KEY is using the built-in development default. Set the SECRET_KEY "
            "environment variable; otherwise sessions, JWTs and QR tokens can be forged."
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

    # Initialize Prometheus observability metrics
    from .metrics import init_metrics
    init_metrics(app)

    with app.app_context():
        db.create_all()

    return app
