import base64

import cv2
import numpy as np
import pytest

import app.routes.student as student_routes

UNIT_VECTOR = np.ones(512, dtype=np.float32) / np.sqrt(512)


def _register(client, first, email=None):
    res = client.post("/register", json={
        "first_name": first, "last_name": "Test", "department": "CSE", "year": "2026",
        "email": email or f"{first.lower()}@univ.edu",
    })
    assert res.status_code == 200, res.get_json()
    return res.get_json()["roll"]


def _image(height=240, width=320):
    frame = np.random.default_rng(0).integers(0, 256, (height, width, 3), dtype=np.uint8)
    ok, jpeg = cv2.imencode(".jpg", frame)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode()


class FakeDetector:
    """Stands in for MTCNN: returns fixed boxes ([x1, y1, x2, y2]) and probabilities."""

    def __init__(self, boxes, probs):
        self.boxes, self.probs = boxes, probs

    def detect(self, rgb):
        if self.boxes is None:
            return None, None
        return np.array(self.boxes, dtype=np.float32), np.array(self.probs, dtype=np.float32)


@pytest.fixture
def stub_face_models(monkeypatch):
    def install(boxes, probs, embedding=UNIT_VECTOR):
        monkeypatch.setattr(student_routes, "mtcnn", FakeDetector(boxes, probs))
        monkeypatch.setattr(student_routes, "get_embedding_from_crop", lambda crop: embedding)
    return install


@pytest.mark.parametrize("path", ["/register", "/capture_face", "/save_face_data"])
def test_enrollment_endpoints_require_an_admin(client, path):
    assert client.post(path, json={}).status_code == 401


@pytest.mark.parametrize("field, value, error", [
    ("first_name", "", "First Name is required"),
    ("last_name", "x" * 101, "Last Name cannot exceed 100 characters"),
    ("email", "not-an-email", "Invalid email format"),
    ("email", "user@" + "d" * 112 + ".com", "Email address cannot exceed 120 characters"),
])
def test_register_rejects_invalid_fields(authenticated_client, field, value, error):
    payload = {"first_name": "Yara", "last_name": "Test", "department": "CSE", "year": "2026",
               "email": "yara@univ.edu", field: value}
    res = authenticated_client.post("/register", json=payload)
    assert res.status_code == 400
    assert res.get_json()["error"].startswith(error)


def test_register_retries_when_the_generated_roll_is_already_taken(authenticated_client, monkeypatch):
    # Two admins enrolling at once can compute the same roll; the unique index rejects
    # the second insert and registration recomputes the roll
    first = _register(authenticated_client, "Zane")
    real_generate = student_routes.generate_roll
    calls = []

    def stale_then_real(year, dept):
        calls.append(1)
        return first if len(calls) == 1 else real_generate(year, dept)

    monkeypatch.setattr(student_routes, "generate_roll", stale_then_real)
    assert _register(authenticated_client, "Abel") == "2026CSE002"
    assert len(calls) == 2


def test_capture_face_returns_an_embedding_and_the_face_box(authenticated_client, stub_face_models):
    stub_face_models([[40, 30, 160, 170]], [0.99])
    body = authenticated_client.post("/capture_face", json={"image": _image()}).get_json()
    assert body["status"] == "success"
    assert len(body["embedding"]) == 512
    assert body["box"] == [40, 30, 120, 140]


@pytest.mark.parametrize("boxes, probs, error", [
    (None, None, "no face"),
    ([[40, 30, 160, 170]], [0.5], "low confidence face"),
    ([[40, 30, 70, 60]], [0.99], "face too small"),
])
def test_capture_face_explains_why_a_frame_was_not_usable(authenticated_client, stub_face_models,
                                                          boxes, probs, error):
    stub_face_models(boxes, probs)
    res = authenticated_client.post("/capture_face", json={"image": _image()})
    # 200 so the enrollment page simply retries with the next frame
    assert res.status_code == 200
    assert res.get_json() == {"error": error}


def test_capture_face_reports_a_failed_embedding(authenticated_client, stub_face_models):
    stub_face_models([[40, 30, 160, 170]], [0.99], embedding=None)
    res = authenticated_client.post("/capture_face", json={"image": _image()})
    assert res.get_json() == {"error": "embedding extraction failed"}


def test_save_face_data_rejects_missing_rolls_and_unknown_students(authenticated_client):
    sample = [[1.0] * 512]
    res = authenticated_client.post("/save_face_data", json={"embeddings": sample})
    assert res.status_code == 400

    res = authenticated_client.post("/save_face_data", json={"roll": "2099XYZ999", "embeddings": sample})
    assert res.status_code == 404


@pytest.mark.parametrize("embeddings", [
    [[1.0] * 512] * 21,               # more than MAX_FACE_SAMPLES
    [[True] * 512],                   # booleans aren't numbers
    [[float("nan")] + [1.0] * 511],   # non-finite values
])
def test_save_face_data_rejects_malformed_samples(authenticated_client, embeddings):
    roll = _register(authenticated_client, "Bea")
    res = authenticated_client.post("/save_face_data", json={"roll": roll, "embeddings": embeddings})
    assert res.status_code == 400


def test_student_lookups_validate_their_input(authenticated_client):
    assert authenticated_client.post("/verify_student", json={}).status_code == 400
    assert authenticated_client.get("/get_student/2099XYZ999").status_code == 404
