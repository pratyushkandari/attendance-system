import json
from datetime import datetime
from app.extensions import db


class Student(db.Model):
    """
    Student entity representing enrolled university students with biometric profiles.
    """
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    roll = db.Column(db.String(50), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), index=True)
    year = db.Column(db.String(20))
    email = db.Column(db.String(120), unique=True, index=True)

    # 512-Dimensional normalized facial vector stored as serialized JSON
    embedding = db.Column(db.Text)

    def set_embedding(self, emb):
        """
        Serializes a NumPy 512-D unit vector into JSON string for PostgreSQL storage.

        Args:
            emb (numpy.ndarray or list): 512-D normalized vector array.
        """
        if emb is not None:
            if hasattr(emb, "tolist"):
                self.embedding = json.dumps(emb.tolist())
            else:
                self.embedding = json.dumps(list(emb))

    def get_embedding(self):
        """
        Deserializes the stored JSON string back into a Python list.

        Returns:
            list or None: 512-D embedding list.
        """
        if self.embedding:
            return json.loads(self.embedding)
        return None

    def __repr__(self):
        return f"<Student roll='{self.roll}' email='{self.email}'>"


class Attendance(db.Model):
    """
    Attendance log record storing timestamped check-in events.
    """
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    roll = db.Column(db.String(50), nullable=False, index=True)
    method = db.Column(db.String(10), nullable=False)  # 'Face' or 'QR'
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<Attendance roll='{self.roll}' method='{self.method}' time='{self.timestamp}'>"