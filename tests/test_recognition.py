"""
/recognize_with_box with the face models stubbed: detection keyframes, tracking frames,
matching and the per-kiosk tracker sessions. The CSRT trackers are the real OpenCV ones.
"""
import base64
import time

import cv2
import numpy as np
import pytest

import app.routes.attendance as attendance_routes

FRAME = np.random.default_rng(1).integers(0, 256, (240, 320, 3), dtype=np.uint8)
FACE = [100.0, 60.0, 200.0, 180.0]   # x1, y1, x2, y2 in FRAME


def _data_url(frame):
    ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode()


def _unit(i):
    vector = np.zeros(512, dtype=np.float32)
    vector[i] = 1.0
    return vector


class FakeDetector:
    def __init__(self, boxes=(), probs=(), error=None):
        self.boxes, self.probs, self.error, self.calls = list(boxes), list(probs), error, 0

    def detect(self, rgb):
        self.calls += 1
        if self.error:
            raise self.error
        if not self.boxes:
            return None, None
        return np.array(self.boxes, dtype=np.float32), np.array(self.probs, dtype=np.float32)


@pytest.fixture
def kiosk(authenticated_client, monkeypatch):
    """Enroll one student with embedding e0 and return (roll, send_frame)."""
    monkeypatch.setattr(attendance_routes, "tracking_sessions", {})
    res = authenticated_client.post("/register", json={
        "first_name": "Kiosk", "last_name": "Test", "department": "CSE", "year": "2026",
        "email": "kiosk@univ.edu",
    })
    roll = res.get_json()["roll"]
    res = authenticated_client.post("/save_face_data", json={"roll": roll, "embeddings": [_unit(0).tolist()]})
    assert res.status_code == 200

    def send(detector, embedding=None, client_id="cam-1", frame=FRAME):
        monkeypatch.setattr(attendance_routes, "mtcnn", detector)
        monkeypatch.setattr(attendance_routes, "get_embedding_from_crop", lambda crop: embedding)
        res = authenticated_client.post("/recognize_with_box",
                                        json={"image": _data_url(frame), "client_id": client_id})
        assert res.status_code == 200
        return res.get_json()

    return roll, send


def test_keyframe_identifies_an_enrolled_face(kiosk):
    roll, send = kiosk
    body = send(FakeDetector([FACE], [0.99]), embedding=_unit(0))
    (face,) = body["faces"]
    assert face["roll"] == roll
    assert not face["is_unknown"]
    assert face["confidence"] == pytest.approx(1.0)
    x, y, w, h = face["box"]
    assert abs(x - 100) <= 3 and abs(y - 60) <= 3 and abs(w - 100) <= 3 and abs(h - 120) <= 3


def test_keyframe_reports_a_face_below_the_threshold_as_unknown(kiosk):
    _, send = kiosk
    (face,) = send(FakeDetector([FACE], [0.99]), embedding=_unit(1))["faces"]
    assert face["is_unknown"]
    assert face["roll"] == "Unknown"
    assert face["confidence"] == 0.0


def test_keyframe_skips_low_confidence_tiny_and_flat_faces(kiosk):
    _, send = kiosk
    flat = FRAME.copy()
    flat[60:180, 220:300] = 128   # a face box with no texture
    detector = FakeDetector(
        [FACE, [10, 10, 40, 40], [220, 60, 300, 180]],
        [0.5, 0.99, 0.99],          # low confidence, too small (30 px), flat crop
    )
    assert send(detector, embedding=_unit(0), frame=flat) == {"faces": []}


def test_tracking_frames_reuse_the_last_detection(kiosk):
    roll, send = kiosk
    detector = FakeDetector([FACE], [0.99])
    rolls = [[f["roll"] for f in send(detector, embedding=_unit(0))["faces"]] for _ in range(4)]
    # Frame 1 detects; frames 2 and 3 only update the tracker; frame 4 detects again
    assert detector.calls == 2
    assert rolls == [[roll]] * 4


def test_detection_runs_again_while_nothing_is_tracked(kiosk):
    _, send = kiosk
    detector = FakeDetector()   # nobody in front of the camera
    send(detector)
    send(detector)
    assert detector.calls == 2


def test_each_kiosk_has_its_own_tracker_session(kiosk):
    roll, send = kiosk
    send(FakeDetector([FACE], [0.99]), embedding=_unit(0), client_id="cam-1")
    other = FakeDetector()
    assert send(other, client_id="cam-2") == {"faces": []}
    assert other.calls == 1


def test_idle_tracker_sessions_are_dropped(monkeypatch):
    stale = time.time() - attendance_routes.TRACKER_SESSION_TTL_SECONDS - 1
    monkeypatch.setattr(attendance_routes, "tracking_sessions", {
        "old-cam": {"trackers": [], "tracker_data": [], "frame_count": 9, "last_active": stale},
    })
    attendance_routes.get_client_tracker_session("new-cam")
    assert list(attendance_routes.tracking_sessions) == ["new-cam"]


def test_recognition_errors_are_reported_in_the_response(kiosk):
    _, send = kiosk
    body = send(FakeDetector(error=RuntimeError("model failed")))
    assert body == {"faces": [], "error": "Server error during recognition."}
