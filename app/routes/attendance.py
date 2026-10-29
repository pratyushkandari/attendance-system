import csv
import io
import logging
import threading
import time
from datetime import datetime
from typing import Any

import cv2
import numpy as np
from flask import Blueprint, Response, current_app, jsonify, request
from sqlalchemy import func

from app.ai.comparator import vectorized_matrix_match
from app.ai.facenet_model import get_embedding_from_crop, mtcnn
from app.extensions import db
from app.metrics import ACTIVE_CAMERA_CLIENTS, ATTENDANCE_MARKED_TOTAL
from app.models import Attendance, Student
from app.models.student import ist_day_bounds, ist_now
from app.routes.main import (
    QR_TOKEN_SUBMIT_MAX_AGE,
    admin_required,
    check_qr_token,
    decode_image_payload,
    get_json_body,
    get_str_field,
    is_admin_request,
)

logger = logging.getLogger(__name__)

attendance_bp = Blueprint("attendance", __name__)

EMBEDDING_DIM = 512


# ---------------- MULTI-CLIENT SESSION TRACKER ----------------
# Stores: client_id -> {"trackers": [...], "tracker_data": [...], "frame_count": int, "last_active": float}
# State is per process: with several Gunicorn workers or pods, a kiosk whose frames land
# on a different process simply starts a fresh tracker set (MTCNN re-detects next frame).
TRACKER_SESSION_TTL_SECONDS = 120
tracking_sessions: dict[str, dict[str, Any]] = {}
# Guards the registry dict itself; Gunicorn serves requests from several threads, and
# iterating it while another thread inserts would raise "dictionary changed size".
_tracking_lock = threading.Lock()


def get_client_tracker_session(client_id):
    now = time.time()
    with _tracking_lock:
        # Periodic cleanup of sessions inactive for > 2 minutes
        stale_keys = [k for k, v in tracking_sessions.items() if now - v["last_active"] > TRACKER_SESSION_TTL_SECONDS]
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

        ACTIVE_CAMERA_CLIENTS.set(len(tracking_sessions))
        return tracking_sessions[client_id]


def _create_tracker():
    """Return a CSRT tracker (KCF fallback) from whichever OpenCV API is available."""
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    if hasattr(cv2, "TrackerKCF_create"):
        return cv2.TrackerKCF_create()
    return None


def _load_student_profiles():
    """Return [(roll, 512-D float32 vector)] for every student with a valid face profile."""
    profiles = []
    for s in Student.query.filter(Student.embedding.isnot(None)).all():
        saved_emb = s.get_embedding()
        # Skip malformed vectors: one wrong-sized row would make np.vstack fail and turn
        # every face into "Unknown" for the whole kiosk.
        if saved_emb and len(saved_emb) == EMBEDDING_DIM:
            profiles.append((s.roll, np.array(saved_emb, dtype=np.float32)))
    return profiles


# ---------------- FACE PROFILE CACHE ----------------
# Reloading and JSON-parsing every stored embedding on each detection keyframe took
# ~350 ms at 1,000 enrolled students, so the stacked matrix is cached per process.
# /save_face_data invalidates it in the process that handled the enrollment; other
# Gunicorn workers or pods pick the change up once their copy is older than the TTL.
PROFILE_CACHE_TTL_SECONDS = 30
_profile_cache: dict[str, Any] = {"loaded_at": None, "rolls": [], "matrix": None}
_profile_cache_lock = threading.Lock()


def invalidate_face_profiles() -> None:
    """Make the next keyframe reload face profiles from the database."""
    with _profile_cache_lock:
        _profile_cache["loaded_at"] = None


def get_face_profiles() -> tuple[list[str], np.ndarray | None]:
    """
    Return ``(rolls, matrix)`` for all enrolled faces, where row ``i`` of the
    ``(N, 512)`` float32 matrix belongs to ``rolls[i]``. ``matrix`` is None when
    nobody is enrolled.
    """
    with _profile_cache_lock:
        loaded_at = _profile_cache["loaded_at"]
        if loaded_at is None or time.monotonic() - loaded_at > PROFILE_CACHE_TTL_SECONDS:
            profiles = _load_student_profiles()
            _profile_cache["rolls"] = [roll for roll, _ in profiles]
            _profile_cache["matrix"] = np.vstack([emb for _, emb in profiles]) if profiles else None
            _profile_cache["loaded_at"] = time.monotonic()
        return _profile_cache["rolls"], _profile_cache["matrix"]


# ---------------- RECOGNIZE WITH MULTI-FACE TRACKING ----------------
@attendance_bp.route("/recognize_with_box", methods=["POST"])
@admin_required
def recognize_with_box():
    """
    Detect, identify and track faces in one kiosk video frame.

    MTCNN + FaceNet run on every 4th frame per client (or when nothing is tracked);
    in between, per-client CSRT trackers move the last known boxes. Returns
    ``{"faces": [{"roll", "confidence", "is_unknown", "box": [x, y, w, h]}]}`` in the
    coordinate space of the submitted frame. Errors are reported in the JSON body
    with HTTP 200 so the kiosk loop keeps running.
    """
    try:
        data = get_json_body()
        client_id = get_str_field(data, "client_id")[:64] or "default_camera"

        frame = decode_image_payload(data.get("image"))
        if frame is None:
            return jsonify({"faces": [], "error": "Invalid or corrupt image data."})

        # Low-light check
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = np.mean(gray)
        if brightness < 35:
            return jsonify({
                "faces": [],
                "status": "low_light",
                "error": "low light",
                "message": "Low lighting detected. Switch to dynamic QR check-in if needed."
            })

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
                detection_threshold = float(current_app.config["MTCNN_CONFIDENCE_THRESHOLD"])
                match_threshold = float(current_app.config["FACE_MATCH_THRESHOLD"])

                new_trackers = []
                new_tracker_data = []

                profile_rolls, profile_matrix = get_face_profiles()

                for i, box in enumerate(boxes):
                    # MTCNN confidence filter
                    if probs is not None and probs[i] < detection_threshold:
                        continue

                    x1, y1, x2, y2 = box
                    x = max(0, int(x1))
                    y = max(0, int(y1))
                    w = min(int(x2 - x1), frame.shape[1] - x)
                    h = min(int(y2 - y1), frame.shape[0] - y)

                    if w < 45 or h < 45:
                        continue

                    # Reject tiny or flat (near-uniform) crops that cannot carry identity
                    face_crop = frame[y:y+h, x:x+w]
                    if face_crop.size == 0 or np.std(face_crop) < 18:
                        continue

                    emb = get_embedding_from_crop(face_crop)
                    if emb is None:
                        continue

                    # Vectorized dot product against all enrolled unit vectors
                    best_match, best_score = vectorized_matrix_match(
                        emb, profile_rolls, profile_matrix, threshold=match_threshold
                    )
                    is_match = best_match is not None
                    roll_label = best_match if is_match else "Unknown"

                    tracker = _create_tracker()
                    if tracker is not None:
                        try:
                            tracker.init(frame, (x, y, w, h))
                            new_trackers.append(tracker)
                            new_tracker_data.append({
                                "roll": roll_label,
                                "confidence": float(max(0.0, best_score)),
                                "is_unknown": not is_match
                            })
                        except Exception as te:
                            logger.warning("[TRACKER INIT WARNING]: %s", te)

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
                            "is_unknown": session_data["tracker_data"][i].get("is_unknown", False),
                            "box": [x, y, w, h]
                        })
                        surviving_trackers.append(tracker)
                        surviving_data.append(session_data["tracker_data"][i])
            except Exception:
                # A tracker that fails to update is dropped; MTCNN re-acquires the face
                # on the next keyframe.
                logger.debug("Dropping tracker after update failure", exc_info=True)

        session_data["trackers"] = surviving_trackers
        session_data["tracker_data"] = surviving_data

        return jsonify({"faces": results})

    except Exception:
        logger.exception("[RECOGNIZE ERROR]")
        return jsonify({"faces": [], "error": "Server error during recognition."})


# ---------------- MARK ATTENDANCE (SECURED) ----------------
@attendance_bp.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    """
    Record one attendance event per student per IST day.

    * ``method == "QR"``: public; requires a valid signed QR session token.
    * ``method == "Face"``: requires an admin session or Bearer JWT (kiosk).

    Liveness (blink) checks for the Face channel run in the kiosk browser; the server
    only enforces that the caller is an authenticated kiosk/admin.
    """
    try:
        data = get_json_body()
        roll = get_str_field(data, "roll")
        method = get_str_field(data, "method")
        qr_token = data.get("qr_token", "")

        if not roll or not method:
            return jsonify({"status": "error", "message": "Missing roll or method."}), 400

        # Verification rules per method:
        if method == "QR":
            if not qr_token:
                return jsonify({"status": "error", "message": "Missing QR verification token."}), 400
            is_valid, error = check_qr_token(qr_token, QR_TOKEN_SUBMIT_MAX_AGE)
            if not is_valid:
                return jsonify({"status": "error", "message": error}), 400
        elif method == "Face":
            if not is_admin_request():
                return jsonify({"status": "error", "message": "Unauthorized face attendance session."}), 401
        else:
            return jsonify({"status": "error", "message": "Invalid attendance method."}), 400

        # Verify student existence (case-insensitive: phones may submit lower-case rolls)
        student = Student.find_by_roll(roll)
        if not student:
            return jsonify({"status": "error", "message": "Student not registered."}), 404
        roll = student.roll

        now = ist_now()
        day_start, day_end = ist_day_bounds(now.date())

        # Check duplicate for today. This is an application-level check (no DB unique
        # constraint), so two simultaneous requests for the same roll could both pass.
        existing = Attendance.query.filter(
            Attendance.roll == roll,
            Attendance.timestamp >= day_start,
            Attendance.timestamp < day_end,
        ).first()

        if existing:
            return jsonify({"status": "already marked today", "message": f"Attendance already marked for {roll} today."})

        record = Attendance(
            roll=roll,
            method=method,
            timestamp=now
        )
        db.session.add(record)
        db.session.commit()
        ATTENDANCE_MARKED_TOTAL.labels(method=method).inc()

        return jsonify({"status": "marked", "message": f"Attendance marked for {roll} via {method}."})

    except Exception:
        logger.exception("[MARK ATTENDANCE ERROR]")
        db.session.rollback()
        return jsonify({"status": "error", "message": "Server error while marking attendance."}), 500


# ---------------- RECORDS (ADMIN PROTECTED) ----------------
@attendance_bp.route("/records", methods=["GET"])
@admin_required
def get_records():
    """Return attendance grouped by IST date: ``{"YYYY-MM-DD": [{roll, method, time}]}``."""
    try:
        records = Attendance.query.order_by(Attendance.timestamp.desc()).all()

        grouped = {}
        latest_per_student_per_day = {}

        # Keep one row per (roll, day) in case a race ever wrote a duplicate
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

    except Exception:
        logger.exception("[RECORDS ERROR]")
        return jsonify({"error": "Failed to load attendance records."}), 500


# ---------------- EXPORT ATTENDANCE REPORT (CSV) ----------------
@attendance_bp.route("/export_records", methods=["GET"])
@admin_required
def export_records():
    """
    Generates and streams a CSV report of attendance records with student profile metadata.
    Supports optional query filters: date (YYYY-MM-DD), dept, roll.
    """
    date_filter = request.args.get("date", "").strip()
    dept_filter = request.args.get("dept", "").strip().upper()
    roll_filter = request.args.get("roll", "").strip().upper()

    filter_date = None
    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date filter. Use YYYY-MM-DD."}), 400

    try:
        query = db.session.query(Attendance, Student).outerjoin(
            Student, Attendance.roll == Student.roll
        )

        if filter_date:
            day_start, day_end = ist_day_bounds(filter_date)
            query = query.filter(Attendance.timestamp >= day_start, Attendance.timestamp < day_end)
        if dept_filter:
            query = query.filter(Student.department == dept_filter)
        if roll_filter:
            query = query.filter(Attendance.roll == roll_filter)

        records = query.order_by(Attendance.timestamp.desc()).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Attendance ID", "Roll Number", "Student Name",
            "Department", "Year", "Email", "Method", "Date (IST)", "Time (IST)"
        ])

        for att, stu in records:
            name = f"{stu.first_name} {stu.last_name}" if stu else "N/A"
            dept = stu.department if stu else "N/A"
            year = stu.year if stu else "N/A"
            email = stu.email if stu else "N/A"
            date_str = att.timestamp.strftime("%Y-%m-%d")
            time_str = att.timestamp.strftime("%H:%M:%S")

            writer.writerow([
                att.id, att.roll, name, dept, year, email, att.method, date_str, time_str
            ])

        output.seek(0)
        filename = f"attendance_report_{ist_now().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception:
        logger.exception("[EXPORT ERROR]")
        return jsonify({"error": "Failed to generate CSV export."}), 500


# ---------------- CLEAR RECORDS (ADMIN PROTECTED) ----------------
@attendance_bp.route("/clear_records", methods=["POST"])
@admin_required
def clear_records():
    try:
        Attendance.query.delete()
        db.session.commit()
        return jsonify({"status": "cleared", "message": "All attendance records cleared."})
    except Exception:
        logger.exception("[CLEAR ERROR]")
        db.session.rollback()
        return jsonify({"error": "Failed to clear records."}), 500


# ---------------- DASHBOARD STATS (ADMIN PROTECTED) ----------------
@attendance_bp.route("/dashboard_data")
@admin_required
def dashboard_data():
    try:
        total_students = Student.query.count()
        day_start, day_end = ist_day_bounds(ist_now().date())

        # Count distinct students present today in SQL instead of loading the whole
        # attendance history into memory on every dashboard refresh.
        today_present = db.session.query(
            func.count(func.distinct(Attendance.roll))
        ).filter(
            Attendance.timestamp >= day_start,
            Attendance.timestamp < day_end,
        ).scalar() or 0

        return jsonify({
            "total_students": total_students,
            "present": today_present,
            "absent": max(0, total_students - today_present)
        })

    except Exception:
        logger.exception("[DASHBOARD ERROR]")
        return jsonify({
            "error": "Failed to load dashboard statistics.",
            "total_students": 0,
            "present": 0,
            "absent": 0
        }), 500
