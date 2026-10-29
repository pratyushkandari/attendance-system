"""
End-to-end tests against the running Docker Compose stack: real HTTP through
Gunicorn, PostgreSQL, Redis and the face models, with LFW photos as students.

    docker compose up -d
    make e2e

They don't run with `make test` or in CI. The tests in this file run in order and
share one class of students, the way the system is used during a day. They clear
the attendance records first, so don't point them at data you want to keep.

Cases that don't need the real stack (expired or tampered tokens, malformed
images, validation errors, duplicate emails, 401s) are covered by the fast suite.
"""
import base64
import csv
import io
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:5000")
ADMIN_EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@institution.edu")        # seed.sql
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "AdminSecure@2026!")
LFW = Path(os.getenv("E2E_LFW_DIR", Path(__file__).resolve().parents[2] / "data" / "lfw" / "lfw"))

# LFW people with plenty of photos: 5 to enroll, the rest to check in with
FACE_STUDENTS = {"Colin_Powell": ("CSE", "2026"), "Tony_Blair": ("CSE", "2026"),
                 "Donald_Rumsfeld": ("ECE", "2027")}
QR_STUDENT = ("Gerhard_Schroeder", "ECE", "2027")   # registered, checks in by QR only
STRANGER = "Hugo_Chavez"                            # never registered
RUN = uuid.uuid4().hex[:6]
IST = timezone(timedelta(hours=5, minutes=30))


def url(path: str) -> str:
    return f"{BASE_URL}{path}"


def photo(person: str, n: int) -> Path:
    return LFW / person / f"{person}_{n:04d}.jpg"


def data_url(bgr: np.ndarray, quality: int = 90) -> str:
    ok, jpeg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def kiosk_frame(*photos: Path, shift: int = 0) -> str:
    """A 380 px wide kiosk frame (as recognize.js sends) with one or two photos in it."""
    if len(photos) == 1:
        frame = np.full((285, 380, 3), 128, np.uint8)
        frame[:, 47:332] = cv2.resize(cv2.imread(str(photos[0])), (285, 285))
    else:
        frame = np.full((214, 380, 3), 128, np.uint8)
        for i, p in enumerate(photos):
            frame[12:202, 190 * i:190 * (i + 1)] = cv2.resize(cv2.imread(str(p)), (190, 190))
    return data_url(np.roll(frame, shift, axis=1), quality=60)


def full_name(person: str) -> tuple[str, str]:
    first, *rest = person.split("_")
    return first, " ".join(rest)


def recognise(api: requests.Session, *photos: Path) -> list[dict]:
    """One detection keyframe from a fresh kiosk."""
    r = api.post(url("/recognize_with_box"),
                 json={"image": kiosk_frame(*photos), "client_id": f"e2e-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 200
    body = r.json()
    assert "error" not in body, body
    return body["faces"]


def student_name(api: requests.Session, roll: str) -> str:
    r = api.get(url(f"/get_student/{roll}"))
    assert r.status_code == 200, r.text
    return f"{r.json()['first_name']}_{r.json()['last_name'].replace(' ', '_')}"


@pytest.fixture(scope="module")
def api() -> requests.Session:
    session = requests.Session()
    try:
        r = session.post(url("/login_admin"), json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    except requests.ConnectionError:
        pytest.fail(f"Nothing is listening on {BASE_URL}. Start the stack with `docker compose up -d`.")
    assert r.json().get("status") == "success", r.text
    session.headers["Authorization"] = f"Bearer {r.json()['token']}"
    if not LFW.is_dir():
        pytest.fail(f"No LFW photos in {LFW}. Run `make accuracy` once to download them.")
    assert session.post(url("/clear_records")).status_code == 200
    return session


@pytest.fixture(scope="module")
def students(api: requests.Session) -> dict[str, str]:
    """Register the class and enroll a face profile for each FACE_STUDENTS entry."""
    rolls = {}
    for person, dept, year in [(p, *d) for p, d in FACE_STUDENTS.items()] + [QR_STUDENT]:
        first, last = full_name(person)
        r = api.post(url("/register"), json={"first_name": first, "last_name": last, "department": dept,
                                             "year": year, "email": f"{person.lower()}.{RUN}@example.com"})
        assert r.status_code == 200, r.text
        rolls[person] = r.json()["roll"]

    for person in FACE_STUDENTS:
        # Like the enrollment page: keep capturing until 5 frames gave a usable face
        samples, n = [], 0
        while len(samples) < 5:
            n += 1
            image = data_url(cv2.imread(str(photo(person, n))))
            body = api.post(url("/capture_face"), json={"image": image}).json()
            if body.get("status") == "success":
                samples.append(body["embedding"])
        r = api.post(url("/save_face_data"), json={"roll": rolls[person], "embeddings": samples})
        assert r.json()["status"] == "saved", r.text
    return rolls


def qr_token(api: requests.Session) -> str:
    r = api.get(url("/generate_qr_token"))
    assert r.status_code == 200
    return r.json()["token"]


def test_registration_numbers_each_department_in_sequence(students):
    cse = sorted(students[p] for p in ("Colin_Powell", "Tony_Blair"))
    ece = sorted(students[p] for p in ("Donald_Rumsfeld", "Gerhard_Schroeder"))
    assert all(r.startswith("2026CSE") for r in cse)
    assert all(r.startswith("2027ECE") for r in ece)
    assert int(cse[1][-3:]) == int(cse[0][-3:]) + 1
    assert int(ece[1][-3:]) == int(ece[0][-3:]) + 1


def test_enrollment_reports_frames_without_a_face(api):
    empty_room = np.full((480, 640, 3), 140, np.uint8)
    body = api.post(url("/capture_face"), json={"image": data_url(empty_room)}).json()
    assert body == {"error": "no face"}


def test_kiosk_recognises_each_enrolled_student(api, students):
    for person in FACE_STUDENTS:
        faces = recognise(api, photo(person, 20))   # a photo that wasn't used for enrollment
        assert len(faces) == 1
        assert not faces[0]["is_unknown"], person
        # On a reused database an earlier run may have enrolled the same face, so
        # check who was recognised rather than which roll number
        assert student_name(api, faces[0]["roll"]) == person


def test_kiosk_reports_an_unregistered_person_as_unknown(api, students):
    faces = recognise(api, photo(STRANGER, 1))
    assert len(faces) == 1
    assert faces[0]["is_unknown"] and faces[0]["roll"] == "Unknown"


def test_kiosk_identifies_two_students_in_one_frame(api, students):
    faces = recognise(api, photo("Colin_Powell", 21), photo("Tony_Blair", 21))
    assert len(faces) == 2
    assert {student_name(api, f["roll"]) for f in faces} == {"Colin_Powell", "Tony_Blair"}


def test_kiosk_keeps_tracking_a_face_between_keyframes(api, students):
    client_id = f"e2e-{uuid.uuid4().hex[:8]}"
    frames = []
    for shift in (0, 4, 8):   # frame 1 runs detection; frames 2 and 3 only move the tracker
        body = api.post(url("/recognize_with_box"),
                        json={"image": kiosk_frame(photo("Tony_Blair", 1), shift=shift),
                              "client_id": client_id}).json()
        frames.append({f["roll"]: f["box"][0] for f in body["faces"] if not f["is_unknown"]})

    roll = next(r for r in frames[0] if student_name(api, r) == "Tony_Blair")
    assert all(roll in f for f in frames)
    xs = [f[roll] for f in frames]
    assert xs[0] < xs[1] < xs[2]   # the box follows the face as it moves right


def test_face_check_in_marks_present_and_blocks_qr_the_same_day(api, students):
    roll = recognise(api, photo("Colin_Powell", 23))[0]["roll"]
    r = api.post(url("/mark_attendance"), json={"roll": roll, "method": "Face"})
    assert r.json()["status"] == "marked"

    phone = requests.Session()
    r = phone.post(url("/mark_attendance"), json={"roll": roll, "method": "QR", "qr_token": qr_token(api)})
    assert r.json()["status"] == "already marked today"


def test_qr_check_in_from_a_phone(api, students):
    roll = students[QR_STUDENT[0]]
    token = qr_token(api)
    phone = requests.Session()   # not signed in, like a student's phone

    assert phone.post(url("/verify_qr_token"), json={"token": token}).json() == {"valid": True}
    # Phones often submit the roll number in lower case
    r = phone.post(url("/verify_student"), json={"roll": roll.lower(), "token": token}).json()
    assert r == {"success": True, "roll": roll}
    r = phone.get(url(f"/get_student/{roll}"), headers={"X-QR-Token": token})
    assert (r.json()["first_name"], r.json()["last_name"]) == full_name(QR_STUDENT[0])
    r = phone.post(url("/mark_attendance"), json={"roll": roll.lower(), "method": "QR", "qr_token": token})
    assert r.json()["status"] == "marked"

    # The face channel can't mark them a second time today
    r = api.post(url("/mark_attendance"), json={"roll": roll, "method": "Face"})
    assert r.json()["status"] == "already marked today"


def test_qr_check_in_rejects_an_unregistered_roll(api):
    token = qr_token(api)
    phone = requests.Session()
    r = phone.post(url("/verify_student"), json={"roll": "2099XYZ999", "token": token}).json()
    assert r == {"success": False, "roll": None}
    r = phone.post(url("/mark_attendance"), json={"roll": "2099XYZ999", "method": "QR", "qr_token": token})
    assert r.status_code == 404


def test_dashboard_records_and_export_show_the_day(api, students):
    qr_roll = students[QR_STUDENT[0]]
    today = datetime.now(IST).strftime("%Y-%m-%d")

    stats = api.get(url("/dashboard_data")).json()
    assert stats["present"] == 2   # Colin Powell by face, Gerhard Schroeder by QR
    assert stats["absent"] == stats["total_students"] - 2

    day = api.get(url("/records")).json()[today]
    assert {"Face", "QR"} == {r["method"] for r in day}
    assert qr_roll in {r["roll"] for r in day}

    r = api.get(url("/export_records"), params={"date": today, "roll": qr_roll})
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 1
    assert (rows[0]["Student Name"], rows[0]["Method"]) == ("Gerhard Schroeder", "QR")

    r = api.get(url("/export_records"), params={"date": today, "dept": "CSE"})
    assert [row["Method"] for row in csv.DictReader(io.StringIO(r.text))] == ["Face"]


def test_failed_logins_lock_the_account_through_redis(api):
    email, password = f"lockout.{RUN}@example.com", "E2e!Lockout#Check2026"
    r = api.post(url("/register_admin"), json={"email": email, "password": password})
    assert r.json()["status"] == "registered", r.text

    stranger = requests.Session()
    for _ in range(3):
        r = stranger.post(url("/login_admin"), json={"email": email, "password": "Wrong!Password1"})
        assert r.json()["status"] in ("invalid", "locked")
    r = stranger.post(url("/login_admin"), json={"email": email, "password": password})
    assert r.json()["status"] == "locked"


def test_purge_clears_the_day(api, students):
    assert api.post(url("/clear_records")).json()["status"] == "cleared"
    assert api.get(url("/dashboard_data")).json()["present"] == 0
    assert api.get(url("/records")).json() == {}
