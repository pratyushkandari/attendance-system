import base64
import time
from datetime import datetime, timedelta
import cv2
import numpy as np
from flask import Blueprint, request, jsonify, session
from sqlalchemy import func
from itsdangerous import SignatureExpired, BadSignature

from app.models import Student, Attendance
from app.extensions import db
from app.routes.main import admin_required, get_qr_serializer, decode_jwt_token
from app.ai.facenet_model import mtcnn, get_embedding_from_crop
from app.ai.face_utils import cosine_similarity

attendance_bp = Blueprint("attendance", __name__)


# ---------------- IST TIMEZONE HELPER ----------------
def get_ist_now():
    """Returns current datetime in Indian Standard Time (UTC+5:30)."""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


# ---------------- MULTI-CLIENT SESSION TRACKER ----------------
# Stores: client_id -> {"trackers": [...], "tracker_data": [...], "frame_count": int, "last_active": float}
tracking_sessions = {}


def get_client_tracker_session(client_id):
    now = time.time()
    # Periodic cleanup of sessions inactive for > 2 minutes
    stale_keys = [k for k, v in tracking_sessions.items() if now - v["last_active"] > 120]
    for k in stale_keys:
        del tracking_sessions[k]

    if client_id not in tracking_sessions:
        tracking_sessions[client_id] = {
            "trackers": [],
            "tracker_data": [],
            "frame_count": 0,
            "last_active": now
        }
    else:
        tracking_sessions[client_id]["last_active"] = now

    return tracking_sessions[client_id]


# ---------------- RECOGNIZE WITH MULTI-FACE TRACKING ----------------
@attendance_bp.route("/recognize_with_box", methods=["POST"])
@admin_required
def recognize_with_box():
    try:
        data = request.json or {}
        image_raw = data.get("image", "")
        client_id = data.get("client_id", "default_camera")

        if not image_raw or "," not in image_raw:
            return jsonify({"faces": [], "error": "Invalid image data."})

        image_data = image_raw.split(",")[1]
        img_bytes = base64.b64decode(image_data)
        npimg = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(npimg, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({"faces": [], "error": "Corrupt frame."})

        # Low-light check
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = np.mean(gray)
        if brightness < 35:
            return jsonify({"faces": [], "error": "low light"})

        session_data = get_client_tracker_session(client_id)
        session_data["frame_count"] += 1
        frame_count = session_data["frame_count"]

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = []

        # Run detection periodically (every 4 frames) or when trackers list is empty
        run_detection = (frame_count % 4 == 0) or (len(session_data["trackers"]) == 0)

        if run_detection:
            boxes, probs = mtcnn.detect(rgb)

            if boxes is None or len(boxes) == 0:
                session_data["trackers"] = []
                session_data["tracker_data"] = []
            else:
                new_trackers = []
                new_tracker_data = []

                # Fetch all student embeddings once
                students = Student.query.all()
                student_profiles = []
                for s in students:
                    saved_emb = s.get_embedding()
                    if saved_emb:
                        student_profiles.append((s.roll, np.array(saved_emb, dtype=np.float32)))

                for i, box in enumerate(boxes):
                    # MTCNN confidence filter
                    if probs is not None and probs[i] < 0.92:
                        continue

                    x1, y1, x2, y2 = box
                    x = max(0, int(x1))
                    y = max(0, int(y1))
                    w = min(int(x2 - x1), frame.shape[1] - x)
                    h = min(int(y2 - y1), frame.shape[0] - y)

                    if w < 45 or h < 45:
                        continue

                    face_crop = frame[y:y+h, x:x+w]
                    if face_crop.size == 0 or np.std(face_crop) < 18:
                        continue

                    emb = get_embedding_from_crop(face_crop)
                    if emb is None:
                        continue

                    best_match = None
                    best_score = -1.0

                    if student_profiles:
                        rolls, embeddings_list = zip(*student_profiles)
                        matrix = np.vstack(embeddings_list)  # Matrix of shape (N, 512)
                        
                        # Vectorized matrix dot product across all registered embeddings
                        scores = np.dot(matrix, emb)
                        best_idx = int(np.argmax(scores))
                        best_score = float(scores[best_idx])
                        best_match = rolls[best_idx]

                    # Strict match threshold
                    if best_score >= 0.70 and best_match:
                        # Instantiate CSRT tracker safely
                        tracker = None
                        if hasattr(cv2, "TrackerCSRT_create"):
                            tracker = cv2.TrackerCSRT_create()
                        elif hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
                            tracker = cv2.legacy.TrackerCSRT_create()
                        elif hasattr(cv2, "TrackerKCF_create"):
                            tracker = cv2.TrackerKCF_create()

                        if tracker is not None:
                            try:
                                tracker.init(frame, (x, y, w, h))
                                new_trackers.append(tracker)
                                new_tracker_data.append({
                                    "roll": best_match,
                                    "confidence": float(best_score)
                                })
                            except Exception as te:
                                print("[TRACKER INIT WARNING]:", te)

                session_data["trackers"] = new_trackers
                session_data["tracker_data"] = new_tracker_data

        # Update existing trackers
        surviving_trackers = []
        surviving_data = []

        for i, tracker in enumerate(session_data["trackers"]):
            try:
                success, box = tracker.update(frame)
                if success and i < len(session_data["tracker_data"]):
                    x, y, w, h = [int(v) for v in box]
                    if w >= 40 and h >= 40:
                        results.append({
                            "roll": session_data["tracker_data"][i]["roll"],
                            "confidence": session_data["tracker_data"][i]["confidence"],
                            "box": [x, y, w, h]
                        })
                        surviving_trackers.append(tracker)
                        surviving_data.append(session_data["tracker_data"][i])
            except Exception:
                pass

        session_data["trackers"] = surviving_trackers
        session_data["tracker_data"] = surviving_data

        return jsonify({"faces": results})

    except Exception as e:
        print("[RECOGNIZE ERROR]:", e)
        return jsonify({"faces": [], "error": "Server error during recognition."})


# ---------------- MARK ATTENDANCE (SECURED) ----------------
@attendance_bp.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    try:
        data = request.json or {}
        roll = data.get("roll", "").strip()
        method = data.get("method", "").strip()
        qr_token = data.get("qr_token", "")

        if not roll or not method:
            return jsonify({"status": "error", "message": "Missing roll or method."}), 400

        # Verification rules per method:
        if method == "QR":
            if not qr_token:
                return jsonify({"status": "error", "message": "Missing QR verification token."}), 400
            serializer = get_qr_serializer()
            try:
                serializer.loads(qr_token, max_age=35)
            except SignatureExpired:
                return jsonify({"status": "error", "message": "QR code expired. Please rescan."}), 400
            except BadSignature:
                return jsonify({"status": "error", "message": "Invalid QR code signature."}), 400
        elif method == "Face":
            is_authorized = ("admin" in session)
            if not is_authorized:
                auth_header = request.headers.get("Authorization")
                if auth_header and auth_header.startswith("Bearer "):
                    try:
                        decode_jwt_token(auth_header.split(" ")[1].strip())
                        is_authorized = True
                    except Exception:
                        pass
            if not is_authorized:
                return jsonify({"status": "error", "message": "Unauthorized face attendance session."}), 401
        else:
            return jsonify({"status": "error", "message": "Invalid attendance method."}), 400

        # Verify student existence
        student = Student.query.filter_by(roll=roll).first()
        if not student:
            return jsonify({"status": "error", "message": "Student not registered."}), 404

        ist_now = get_ist_now()
        today = ist_now.date()

        # Check duplicate for today
        existing = Attendance.query.filter(
            Attendance.roll == roll,
            func.date(Attendance.timestamp) == today
        ).first()

        if existing:
            return jsonify({"status": "already marked today", "message": f"Attendance already marked for {roll} today."})

        record = Attendance(
            roll=roll,
            method=method,
            timestamp=ist_now
        )
        db.session.add(record)
        db.session.commit()

        return jsonify({"status": "marked", "message": f"Attendance marked for {roll} via {method}."})

    except Exception as e:
        print("[MARK ATTENDANCE ERROR]:", e)
        db.session.rollback()
        return jsonify({"status": "error", "message": "Server error while marking attendance."}), 500


# ---------------- RECORDS (ADMIN PROTECTED) ----------------
@attendance_bp.route("/records", methods=["GET"])
@admin_required
def get_records():
    try:
        records = Attendance.query.order_by(Attendance.timestamp.desc()).all()

        grouped = {}
        latest_per_student_per_day = {}

        for r in records:
            date_str = r.timestamp.strftime("%Y-%m-%d")
            key = (r.roll, date_str)

            if key not in latest_per_student_per_day or r.timestamp > latest_per_student_per_day[key].timestamp:
                latest_per_student_per_day[key] = r

        for r in latest_per_student_per_day.values():
            date_str = r.timestamp.strftime("%Y-%m-%d")
            if date_str not in grouped:
                grouped[date_str] = []

            grouped[date_str].append({
                "roll": r.roll,
                "method": r.method,
                "time": r.timestamp.strftime("%H:%M:%S")
            })

        return jsonify(grouped)

    except Exception as e:
        print("[RECORDS ERROR]:", e)
        return jsonify({})


# ---------------- CLEAR RECORDS (ADMIN PROTECTED) ----------------
@attendance_bp.route("/clear_records", methods=["POST"])
@admin_required
def clear_records():
    try:
        Attendance.query.delete()
        db.session.commit()
        return jsonify({"status": "cleared", "message": "All attendance records cleared."})
    except Exception as e:
        print("[CLEAR ERROR]:", e)
        db.session.rollback()
        return jsonify({"error": "Failed to clear records."}), 500


# ---------------- DASHBOARD STATS (ADMIN PROTECTED) ----------------
@attendance_bp.route("/dashboard_data")
@admin_required
def dashboard_data():
    try:
        total_students = Student.query.count()
        ist_now = get_ist_now()
        today = ist_now.date()

        records = Attendance.query.all()
        today_students_present = set()

        for r in records:
            if r.timestamp.date() == today:
                today_students_present.add(r.roll)

        today_present = len(today_students_present)

        return jsonify({
            "total_students": total_students,
            "present": today_present,
            "absent": max(0, total_students - today_present)
        })

    except Exception as e:
        print("[DASHBOARD ERROR]:", e)
        return jsonify({
            "total_students": 0,
            "present": 0,
            "absent": 0
        })