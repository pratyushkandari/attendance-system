import logging
import math
import re

import cv2
import numpy as np
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.ai.facenet_model import get_embedding_from_crop, mtcnn
from app.extensions import db
from app.models import Student
from app.routes.main import (
    QR_TOKEN_SUBMIT_MAX_AGE,
    admin_required,
    check_qr_token,
    decode_image_payload,
    get_json_body,
    get_str_field,
    is_admin_request,
    validate_email_format,
)

logger = logging.getLogger(__name__)

student_bp = Blueprint("student", __name__)

EMBEDDING_DIM = 512
MAX_FACE_SAMPLES = 20

# Roll numbers are built as <year><DEPT><seq> (e.g. 2026CSE001) and are shown in the
# admin UI and typed by students, so their building blocks are restricted to a 4-digit
# year and a short letters-only department code. Letters only keeps the format
# unambiguous: with "CSE2" allowed, "2026CSE2001" could be CSE #2001 or CSE2 #001.
YEAR_PATTERN = re.compile(r"^\d{4}$")
DEPARTMENT_PATTERN = re.compile(r"^[A-Za-z]{2,10}$")
MAX_NAME_LENGTH = 100   # students.first_name / last_name column size
MAX_EMAIL_LENGTH = 120  # students.email column size


# ------------------ ROBUST ROLL GENERATOR ------------------
def generate_roll(year, dept):
    """
    Generates roll numbers like '2026CSE001'.
    Finds the highest existing sequence number for (year, dept) to avoid collisions
    even if middle records were deleted.
    """
    prefix = f"{year}{dept.upper()}"
    students = Student.query.filter(Student.roll.like(f"{prefix}%")).all()

    # LIKE '2026CS%' also returns 2026CSE... rolls, so only count rolls that are
    # exactly <prefix><digits>.
    roll_pattern = re.compile(rf"{re.escape(prefix)}(\d+)")
    max_num = 0
    for s in students:
        match = roll_pattern.fullmatch(s.roll)
        if match:
            num = int(match.group(1))
            if num > max_num:
                max_num = num

    next_num = max_num + 1
    return f"{prefix}{str(next_num).zfill(3)}"


def validate_student_fields(data):
    """
    Validate and normalise the enrollment payload.

    Returns:
        ``(fields, None)`` with stripped values on success, or ``(None, error_message)``.
    """
    required = ["first_name", "last_name", "department", "year", "email"]
    fields = {}
    for field in required:
        raw = data.get(field)
        # Accept numeric years from API clients ({"year": 2026}) as well as strings
        val = str(raw) if isinstance(raw, int) and not isinstance(raw, bool) else get_str_field(data, field)
        if not val:
            return None, f"{field.replace('_', ' ').title()} is required"
        fields[field] = val

    for field in ("first_name", "last_name"):
        if len(fields[field]) > MAX_NAME_LENGTH:
            return None, f"{field.replace('_', ' ').title()} cannot exceed {MAX_NAME_LENGTH} characters"

    if not YEAR_PATTERN.match(fields["year"]):
        return None, "Year must be a 4-digit year (e.g. 2026)"

    if not DEPARTMENT_PATTERN.match(fields["department"]):
        return None, "Department must be a 2-10 letter code (e.g. CSE)"
    fields["department"] = fields["department"].upper()

    email = fields["email"].lower()
    is_valid_email, email_err = validate_email_format(email)
    if not is_valid_email:
        return None, email_err
    if len(email) > MAX_EMAIL_LENGTH:
        return None, f"Email address cannot exceed {MAX_EMAIL_LENGTH} characters."
    fields["email"] = email

    return fields, None


# ------------------ REGISTER (ADMIN PROTECTED) ------------------
@student_bp.route("/register", methods=["POST"])
@admin_required
def register():
    try:
        fields, error = validate_student_fields(get_json_body())
        if error:
            return jsonify({"error": error}), 400

        email = fields["email"]
        if Student.query.filter_by(email=email).first():
            return jsonify({"error": "A student with this email is already registered."}), 400

        # Attempt registration with collision retry: two admins enrolling into the same
        # (year, dept) at once can compute the same next roll; the unique index rejects
        # the loser, which then recomputes.
        for attempt in range(5):
            try:
                roll = generate_roll(fields["year"], fields["department"])
                student = Student(
                    roll=roll,
                    first_name=fields["first_name"],
                    last_name=fields["last_name"],
                    department=fields["department"],
                    year=fields["year"],
                    email=email
                )
                db.session.add(student)
                db.session.commit()
                return jsonify({"status": "success", "roll": roll})
            except IntegrityError:
                db.session.rollback()
                if attempt == 4:
                    raise

        return jsonify({"error": "Failed to generate unique roll number. Please try again."}), 500

    except Exception:
        logger.exception("[STUDENT REGISTER ERROR]")
        db.session.rollback()
        return jsonify({"error": "Server error during registration."}), 500


# ------------------ CAPTURE FACE (ADMIN PROTECTED) ------------------
@student_bp.route("/capture_face", methods=["POST"])
@admin_required
def capture_face():
    """
    Extract one 512-D embedding from the largest face in an enrollment frame.

    "No usable face" outcomes return HTTP 200 with an ``error`` field so the
    enrollment loop can simply retry with the next frame.
    """
    try:
        frame = decode_image_payload(get_json_body().get("image"))
        if frame is None:
            return jsonify({"error": "invalid or corrupt image payload"}), 400

        # Convert BGR -> RGB for MTCNN
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        boxes, probs = mtcnn.detect(rgb)

        if boxes is None or len(boxes) == 0:
            return jsonify({"error": "no face"}), 200

        # MTCNN orders boxes largest-first (select_largest=True), so index 0 is the
        # face closest to the camera. Filter it by detection confidence.
        detection_threshold = float(current_app.config.get("MTCNN_CONFIDENCE_THRESHOLD", 0.90))
        if probs is not None and probs[0] < detection_threshold:
            return jsonify({"error": "low confidence face"}), 200

        x1, y1, x2, y2 = boxes[0]
        h_img, w_img = frame.shape[:2]

        x = max(0, int(x1))
        y = max(0, int(y1))
        w = min(int(x2 - x1), w_img - x)
        h = min(int(y2 - y1), h_img - y)

        if w < 40 or h < 40:
            return jsonify({"error": "face too small"}), 200

        face_crop = frame[y:y+h, x:x+w]
        if face_crop.size == 0:
            return jsonify({"error": "invalid face crop"}), 200

        emb = get_embedding_from_crop(face_crop)
        if emb is None:
            return jsonify({"error": "embedding extraction failed"}), 200

        return jsonify({
            "status": "success",
            "embedding": emb.tolist(),
            "box": [int(x), int(y), int(w), int(h)]
        })

    except Exception:
        logger.exception("[CAPTURE FACE ERROR]")
        return jsonify({"error": "server error during face capture"}), 500


def _parse_embeddings(embeddings):
    """
    Validate client-supplied face samples.

    Returns a ``(K, 512)`` float32 array, or ``None`` if the payload is not a non-empty
    list of at most ``MAX_FACE_SAMPLES`` finite 512-D vectors.
    """
    if not isinstance(embeddings, list) or not 0 < len(embeddings) <= MAX_FACE_SAMPLES:
        return None
    for sample in embeddings:
        if not isinstance(sample, list) or len(sample) != EMBEDDING_DIM:
            return None
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in sample):
            return None
    return np.array(embeddings, dtype=np.float32)


# ------------------ SAVE EMBEDDINGS (ADMIN PROTECTED) ------------------
@student_bp.route("/save_face_data", methods=["POST"])
@admin_required
def save_face_data():
    """
    Average the captured samples into one unit-length centroid and store it.

    Payload: ``{"roll": str, "embeddings": [[512 floats], ...]}``.
    """
    try:
        data = get_json_body()
        roll = get_str_field(data, "roll")
        embeddings = data.get("embeddings")

        if not roll or not embeddings:
            return jsonify({"error": "Missing roll number or face samples."}), 400

        # Reject malformed vectors before they reach the database: a stored vector with
        # the wrong length would break matrix matching for every student.
        embeddings_np = _parse_embeddings(embeddings)
        if embeddings_np is None:
            return jsonify({"error": f"Face samples must be 1-{MAX_FACE_SAMPLES} vectors of {EMBEDDING_DIM} numbers."}), 400

        # Compute centroid average vector
        avg_embedding = np.mean(embeddings_np, axis=0)
        norm = np.linalg.norm(avg_embedding)
        if norm > 1e-8:
            avg_embedding = avg_embedding / norm

        student = Student.find_by_roll(roll)
        if not student:
            return jsonify({"error": "Student record not found."}), 404

        student.set_embedding(avg_embedding)
        db.session.commit()

        return jsonify({"status": "saved", "message": f"Biometric face profile created for {student.roll}."})

    except Exception:
        logger.exception("[SAVE FACE ERROR]")
        db.session.rollback()
        return jsonify({"error": "Server error while saving face profile."}), 500


# ------------------ STUDENT LOOKUPS (QR CHECK-IN FLOW) ------------------
# These endpoints are used by the student's phone after scanning the classroom QR code.
# They require that live QR token (or admin credentials) so roll numbers, which are
# sequential and easy to guess, cannot be used to scrape student names from the internet.
def _qr_or_admin_authorized(token):
    if is_admin_request():
        return True, ""
    return check_qr_token(token, QR_TOKEN_SUBMIT_MAX_AGE)


# ------------------ VERIFY STUDENT (QR TOKEN REQUIRED) ------------------
@student_bp.route("/verify_student", methods=["POST"])
def verify_student():
    """Payload ``{"roll": str, "token": <QR token>}`` -> ``{"success": bool}``."""
    data = get_json_body()
    roll = get_str_field(data, "roll")

    if not roll:
        return jsonify({"success": False, "message": "Roll number is required."}), 400

    authorized, error = _qr_or_admin_authorized(data.get("token"))
    if not authorized:
        return jsonify({"success": False, "message": error}), 401

    student = Student.find_by_roll(roll)
    return jsonify({"success": bool(student), "roll": student.roll if student else None})


# ------------------ GET STUDENT (QR TOKEN REQUIRED) ------------------
@student_bp.route("/get_student/<roll>")
def get_student(roll):
    """Return public profile fields; requires the ``X-QR-Token`` header or admin auth."""
    authorized, error = _qr_or_admin_authorized(request.headers.get("X-QR-Token"))
    if not authorized:
        return jsonify({"error": error}), 401

    student = Student.find_by_roll(roll.strip())

    if not student:
        return jsonify({"error": "Student not found"}), 404

    return jsonify({
        "roll": student.roll,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "department": student.department,
        "year": student.year
    })
