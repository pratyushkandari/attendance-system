import base64
import re
import cv2
import numpy as np
from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError

from app.models import Student
from app.extensions import db
from app.routes.main import admin_required
from app.ai.facenet_model import mtcnn, get_embedding_from_crop

student_bp = Blueprint("student", __name__)


# ------------------ ROBUST ROLL GENERATOR ------------------
def generate_roll(year, dept):
    """
    Generates roll numbers like '2026CSE001'.
    Finds the highest existing sequence number for (year, dept) to avoid collisions
    even if middle records were deleted.
    """
    prefix = f"{year}{dept.upper()}"
    students = Student.query.filter(Student.roll.like(f"{prefix}%")).all()
    
    max_num = 0
    for s in students:
        match = re.search(r"(\d+)$", s.roll)
        if match:
            num = int(match.group(1))
            if num > max_num:
                max_num = num
                
    next_num = max_num + 1
    return f"{prefix}{str(next_num).zfill(3)}"


# ------------------ REGISTER (ADMIN PROTECTED) ------------------
@student_bp.route("/register", methods=["POST"])
@admin_required
def register():
    try:
        data = request.json or {}

        required = ["first_name", "last_name", "department", "year", "email"]
        for field in required:
            val = data.get(field, "").strip() if isinstance(data.get(field), str) else data.get(field)
            if not val:
                return jsonify({"error": f"{field.replace('_', ' ').title()} is required"}), 400

        email = data["email"].strip().lower()
        if Student.query.filter_by(email=email).first():
            return jsonify({"error": "A student with this email is already registered."}), 400

        # Attempt registration with collision retry
        for attempt in range(5):
            try:
                roll = generate_roll(data["year"].strip(), data["department"].strip())
                student = Student(
                    roll=roll,
                    first_name=data["first_name"].strip(),
                    last_name=data["last_name"].strip(),
                    department=data["department"].strip().upper(),
                    year=data["year"].strip(),
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

    except Exception as e:
        print("[STUDENT REGISTER ERROR]:", e)
        db.session.rollback()
        return jsonify({"error": "Server error during registration."}), 500


# ------------------ CAPTURE FACE (ADMIN PROTECTED) ------------------
@student_bp.route("/capture_face", methods=["POST"])
@admin_required
def capture_face():
    try:
        data = request.json or {}
        image_raw = data.get("image", "")

        if not image_raw or "," not in image_raw:
            return jsonify({"error": "invalid image payload"}), 400

        image_data = image_raw.split(",")[1]
        img_bytes = base64.b64decode(image_data)
        npimg = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(npimg, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({"error": "corrupt image"}), 400

        # Convert BGR -> RGB for MTCNN
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        boxes, probs = mtcnn.detect(rgb)

        if boxes is None or len(boxes) == 0:
            return jsonify({"error": "no face"}), 200

        # Filter by detection confidence
        if probs is not None and probs[0] < 0.90:
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

    except Exception as e:
        print("[CAPTURE FACE ERROR]:", e)
        return jsonify({"error": "server error during face capture"}), 500


# ------------------ SAVE EMBEDDINGS (ADMIN PROTECTED) ------------------
@student_bp.route("/save_face_data", methods=["POST"])
@admin_required
def save_face_data():
    try:
        data = request.json or {}
        roll = data.get("roll")
        embeddings = data.get("embeddings")

        if not roll or not embeddings or len(embeddings) == 0:
            return jsonify({"error": "Missing roll number or face samples."}), 400

        embeddings_np = np.array(embeddings, dtype=np.float32)

        # Compute centroid average vector
        avg_embedding = np.mean(embeddings_np, axis=0)
        norm = np.linalg.norm(avg_embedding)
        if norm > 1e-8:
            avg_embedding = avg_embedding / norm

        student = Student.query.filter_by(roll=roll).first()
        if not student:
            return jsonify({"error": "Student record not found."}), 404

        student.set_embedding(avg_embedding)
        db.session.commit()

        return jsonify({"status": "saved", "message": f"Biometric face profile created for {roll}."})

    except Exception as e:
        print("[SAVE FACE ERROR]:", e)
        db.session.rollback()
        return jsonify({"error": "Server error while saving face profile."}), 500


# ------------------ VERIFY STUDENT (STUDENT ACCESSIBLE) ------------------
@student_bp.route("/verify_student", methods=["POST"])
def verify_student():
    data = request.json or {}
    roll = data.get("roll", "").strip()

    if not roll:
        return jsonify({"success": False, "message": "Roll number is required."}), 400

    student = Student.query.filter_by(roll=roll).first()
    return jsonify({"success": bool(student)})


# ------------------ GET STUDENT (STUDENT ACCESSIBLE) ------------------
@student_bp.route("/get_student/<roll>")
def get_student(roll):
    student = Student.query.filter_by(roll=roll.strip()).first()

    if not student:
        return jsonify({"error": "Student not found"}), 404

    return jsonify({
        "roll": student.roll,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "department": student.department,
        "year": student.year
    })