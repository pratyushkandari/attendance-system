import time

from app.models.student import Student
from app.routes.main import get_qr_serializer


def test_register_student_success(authenticated_client):
    payload = {
        "first_name": "Alice",
        "last_name": "Smith",
        "department": "CSE",
        "year": "2026",
        "email": "alice@univ.edu"
    }
    res = authenticated_client.post("/register", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "2026CSE" in data["roll"]

def test_register_duplicate_email_blocked(authenticated_client):
    payload = {
        "first_name": "Bob",
        "last_name": "Jones",
        "department": "ECE",
        "year": "2026",
        "email": "bob@univ.edu"
    }
    res1 = authenticated_client.post("/register", json=payload)
    assert res1.status_code == 200

    # Duplicate email
    res2 = authenticated_client.post("/register", json=payload)
    assert res2.status_code == 400

def test_mark_attendance_qr_flow(client, authenticated_client):
    # Register student first
    authenticated_client.post("/register", json={
        "first_name": "Charlie",
        "last_name": "Brown",
        "department": "ME",
        "year": "2026",
        "email": "charlie@univ.edu"
    })
    roll = "2026ME001"

    # Generate valid QR token
    with client.application.app_context():
        serializer = get_qr_serializer()
        qr_token = serializer.dumps({"nonce": "test_nonce", "created_at": time.time()})

    # Mark attendance via QR
    res = client.post("/mark_attendance", json={
        "roll": roll,
        "method": "QR",
        "qr_token": qr_token
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "marked"

    # Duplicate same-day check
    res_dup = client.post("/mark_attendance", json={
        "roll": roll,
        "method": "QR",
        "qr_token": qr_token
    })
    assert res_dup.status_code == 200
    assert res_dup.get_json()["status"] == "already marked today"

def test_metrics_endpoint(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert b"http_requests_total" in res.data


def test_export_records_csv(authenticated_client):
    res = authenticated_client.get("/export_records")
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    assert "attachment; filename=attendance_report_" in res.headers.get("Content-Disposition", "")
    assert b"Roll Number" in res.data
    assert b"Student Name" in res.data



def _register(client, first, dept="CSE", year="2026", email=None):
    res = client.post("/register", json={
        "first_name": first,
        "last_name": "Test",
        "department": dept,
        "year": year,
        "email": email or f"{first.lower()}@univ.edu",
    })
    assert res.status_code == 200, res.get_json()
    return res.get_json()["roll"]


def _qr_token(app):
    with app.app_context():
        return get_qr_serializer().dumps({"nonce": "n", "created_at": time.time()})


def test_register_student_rejects_malformed_year_and_department(authenticated_client):
    base = {"first_name": "Eve", "last_name": "X", "email": "eve@univ.edu"}

    res = authenticated_client.post("/register", json={**base, "department": "CSE", "year": "<b>26"})
    assert res.status_code == 400
    assert "Year" in res.get_json()["error"]

    res = authenticated_client.post("/register", json={**base, "department": "<img src=x>", "year": "2026"})
    assert res.status_code == 400
    assert "Department" in res.get_json()["error"]


def test_register_student_normalises_department_and_accepts_numeric_year(authenticated_client):
    res = authenticated_client.post("/register", json={
        "first_name": "Dan", "last_name": "Lee", "department": "cse", "year": 2026, "email": "DAN@Univ.edu"
    })
    assert res.status_code == 200
    assert res.get_json()["roll"] == "2026CSE001"


def test_mark_attendance_face_requires_admin(client, app):
    with app.test_client() as anon:
        res = anon.post("/mark_attendance", json={"roll": "2026CSE001", "method": "Face"})
    assert res.status_code == 401


def test_mark_attendance_face_with_admin_session(authenticated_client):
    roll = _register(authenticated_client, "Frank")
    res = authenticated_client.post("/mark_attendance", json={"roll": roll, "method": "Face"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "marked"


def test_mark_attendance_rejects_bad_qr_tokens(authenticated_client, app):
    roll = _register(authenticated_client, "Grace")

    res = authenticated_client.post("/mark_attendance", json={"roll": roll, "method": "QR"})
    assert res.status_code == 400

    res = authenticated_client.post("/mark_attendance", json={"roll": roll, "method": "QR", "qr_token": "forged.token"})
    assert res.status_code == 400
    assert "signature" in res.get_json()["message"].lower()


def test_mark_attendance_accepts_lowercase_roll(authenticated_client, app):
    roll = _register(authenticated_client, "Heidi")
    res = authenticated_client.post("/mark_attendance", json={
        "roll": roll.lower(), "method": "QR", "qr_token": _qr_token(app)
    })
    assert res.status_code == 200
    assert res.get_json()["status"] == "marked"

    records = authenticated_client.get("/records").get_json()
    rolls = [r["roll"] for day in records.values() for r in day]
    assert rolls == [roll]


def test_mark_attendance_increments_prometheus_counter(authenticated_client, app):
    from app.metrics import ATTENDANCE_MARKED_TOTAL

    before = ATTENDANCE_MARKED_TOTAL.labels(method="QR")._value.get()
    roll = _register(authenticated_client, "Ivan")
    authenticated_client.post("/mark_attendance", json={"roll": roll, "method": "QR", "qr_token": _qr_token(app)})
    assert ATTENDANCE_MARKED_TOTAL.labels(method="QR")._value.get() == before + 1


def test_dashboard_data_counts_present_and_absent(authenticated_client, app):
    present_roll = _register(authenticated_client, "Judy")
    _register(authenticated_client, "Karl")
    authenticated_client.post("/mark_attendance", json={"roll": present_roll, "method": "Face"})

    data = authenticated_client.get("/dashboard_data").get_json()
    assert data == {"total_students": 2, "present": 1, "absent": 1}


def test_verify_student_requires_live_qr_token(app):
    with app.test_client() as admin:
        with admin.session_transaction() as sess:
            sess["admin"] = "admin@test.com"
        roll = _register(admin, "Liam")

    with app.test_client() as phone:
        res = phone.post("/verify_student", json={"roll": roll})
        assert res.status_code == 401

        token = _qr_token(app)
        res = phone.post("/verify_student", json={"roll": roll.lower(), "token": token})
        assert res.status_code == 200
        assert res.get_json() == {"success": True, "roll": roll}

        res = phone.get(f"/get_student/{roll}")
        assert res.status_code == 401

        res = phone.get(f"/get_student/{roll}", headers={"X-QR-Token": token})
        assert res.status_code == 200
        assert res.get_json()["first_name"] == "Liam"


def test_save_face_data_validates_and_normalises_embeddings(authenticated_client, app):
    import numpy as np

    roll = _register(authenticated_client, "Mia")

    res = authenticated_client.post("/save_face_data", json={"roll": roll, "embeddings": [[0.1, 0.2, 0.3]]})
    assert res.status_code == 400

    samples = [[1.0] * 512, [3.0] * 512]
    res = authenticated_client.post("/save_face_data", json={"roll": roll, "embeddings": samples})
    assert res.status_code == 200
    assert res.get_json()["status"] == "saved"

    with app.app_context():
        stored = np.array(Student.query.filter_by(roll=roll).first().get_embedding())
    assert stored.shape == (512,)
    assert abs(np.linalg.norm(stored) - 1.0) < 1e-5


def test_export_records_rejects_invalid_date(authenticated_client):
    res = authenticated_client.get("/export_records?date=22-10-2026")
    assert res.status_code == 400


def test_recognize_reports_low_light_frames(authenticated_client):
    import base64

    import cv2
    import numpy as np

    dark = np.full((120, 160, 3), 10, dtype=np.uint8)
    ok, jpeg = cv2.imencode(".jpg", dark)
    assert ok
    image = "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode()

    res = authenticated_client.post("/recognize_with_box", json={"image": image, "client_id": "test-cam"})
    assert res.status_code == 200
    assert res.get_json()["status"] == "low_light"


def test_recognize_returns_no_faces_for_empty_scene(authenticated_client):
    import base64

    import cv2
    import numpy as np

    blank = np.full((240, 320, 3), 180, dtype=np.uint8)
    ok, jpeg = cv2.imencode(".jpg", blank)
    assert ok
    image = "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode()

    res = authenticated_client.post("/recognize_with_box", json={"image": image, "client_id": "test-cam"})
    assert res.status_code == 200
    assert res.get_json() == {"faces": []}


def test_malformed_image_payloads_are_client_errors(authenticated_client):
    # Invalid base64 used to escape as a 500 ("server error") with a logged traceback
    bad_images = ["data:image/jpeg;base64,@@@notbase64", "data:image/jpeg;base64,", "not-a-data-url"]
    for image in bad_images:
        res = authenticated_client.post("/capture_face", json={"image": image})
        assert res.status_code == 400, image
        assert res.get_json()["error"] == "invalid or corrupt image payload"

        res = authenticated_client.post("/recognize_with_box", json={"image": image, "client_id": "cam"})
        assert res.status_code == 200
        assert res.get_json() == {"faces": [], "error": "Invalid or corrupt image data."}


def test_roll_sequence_is_per_department_prefix(authenticated_client):
    # "CS" must not continue the "CSE" sequence just because 2026CS% matches 2026CSE001
    assert _register(authenticated_client, "Nina", dept="CSE") == "2026CSE001"
    assert _register(authenticated_client, "Omar", dept="CS") == "2026CS001"
    assert _register(authenticated_client, "Pia", dept="CSE") == "2026CSE002"
