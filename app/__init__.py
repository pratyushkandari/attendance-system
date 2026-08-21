from flask import Flask
from .config import Config
from .extensions import db

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    # Import models after db init
    from .models import Admin, Student, Attendance

    # Import routes
    from .routes.main import main_bp
    from .routes.student import student_bp
    from .routes.attendance import attendance_bp

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
