from typing import Optional, Type
from flask import Flask
from .config import Config
from .extensions import db


def create_app(config_class: Type[Config] = Config) -> Flask:
    """
    Application factory for the Attendance System microservice.

    Initializes Flask application instance, loads configuration, sets up SQLAlchemy
    database connection, registers modular blueprints, and mounts Prometheus telemetry.

    Args:
        config_class: Configuration class defining runtime environment parameters.

    Returns:
        Configured Flask WSGI application instance.
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    # Import models after db init
    from .models import Admin, Attendance, Student

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

