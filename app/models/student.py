import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np

from app.extensions import db

# Indian Standard Time offset. Attendance timestamps are stored as *naive* IST wall-clock
# datetimes so that "today" and the times shown in the UI/CSV match the institution's
# local day without timezone conversion in every query.
IST_OFFSET = timedelta(hours=5, minutes=30)


def ist_now() -> datetime:
    """Return the current Indian Standard Time (UTC+5:30) as a naive datetime."""
    return datetime.utcnow() + IST_OFFSET


def ist_day_bounds(day: date) -> tuple[datetime, datetime]:
    """
    Return the ``[start, end)`` naive IST datetimes covering ``day``.

    Filtering ``start <= timestamp < end`` can use the index on
    ``attendance.timestamp``; ``DATE(timestamp) = day`` cannot.
    """
    start = datetime.combine(day, datetime.min.time())
    return start, start + timedelta(days=1)


class Student(db.Model):
    """
    Student entity representing enrolled university students with biometric profiles.

    Stores academic metadata alongside 512-dimensional facial embedding vectors
    projected onto the unit hypersphere for fast Euclidean/cosine biometric search.
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

    def set_embedding(self, emb: np.ndarray | Sequence[float] | list[float] | None) -> None:
        """
        Serializes a 512-D unit vector into a JSON string for persistent storage.

        Args:
            emb: 512-D normalized vector as a NumPy array or float sequence.
        """
        if emb is not None:
            if hasattr(emb, "tolist"):
                self.embedding = json.dumps(emb.tolist())  # type: ignore[union-attr]
            else:
                self.embedding = json.dumps(list(emb))

    def get_embedding(self) -> list[float] | None:
        """
        Deserializes the stored JSON representation back into a Python float list.

        Returns:
            List of 512 floats, or None if uninitialized.
        """
        if self.embedding:
            return json.loads(self.embedding)
        return None

    @classmethod
    def find_by_roll(cls, roll: str) -> Optional["Student"]:
        """
        Look up a student by roll number, tolerating lower-case input.

        Generated rolls are upper-case (e.g. ``2026CSE001``) but students type them on
        phones, so an exact match is tried first and an upper-cased match second. Both
        lookups use the unique index on ``students.roll``.
        """
        if not roll:
            return None
        student = cls.query.filter_by(roll=roll).first()
        if student is None and roll != roll.upper():
            student = cls.query.filter_by(roll=roll.upper()).first()
        return student

    def __repr__(self) -> str:
        return f"<Student roll='{self.roll}' email='{self.email}'>"


class Attendance(db.Model):
    """
    Attendance log record storing timestamped check-in events.

    At most one record per roll per IST calendar day is written; this is enforced by
    an application-level check in ``mark_attendance`` (there is no database-level
    unique constraint).

    Attributes:
        roll: Student roll identifier matching `students.roll`.
        method: Check-in modality ('Face' or 'QR').
        timestamp: Naive IST (UTC+5:30) datetime of successful verification.
    """
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    roll = db.Column(db.String(50), nullable=False, index=True)
    method = db.Column(db.String(10), nullable=False)  # 'Face' or 'QR'
    timestamp = db.Column(db.DateTime, default=ist_now, index=True)

    def __repr__(self) -> str:
        return f"<Attendance roll='{self.roll}' method='{self.method}' time='{self.timestamp}'>"
