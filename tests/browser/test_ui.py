"""
Browser tests: the admin pages, enrollment, the face kiosk and QR check-in from a phone,
driven through Chromium against the running Docker Compose stack.

    docker compose up -d
    make browser

Chromium's fake camera plays a clip made from an LFW photo. In that clip the eye region
is flattened for 0.4 s, which the kiosk's liveness check reads as a blink. That runs the
real browser code but isn't a person blinking, so a real blink is still checked by hand
(docs/TESTING.md).

The tests share one browser session and run in order. They clear the stack's attendance
records, so don't point them at data you want to keep.
"""
import os
import re
import uuid
from pathlib import Path

import cv2
import numpy as np
import pytest
from facenet_pytorch import MTCNN
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.browser

BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:5000")
ADMIN_EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@institution.edu")        # seed.sql
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "AdminSecure@2026!")
LFW = Path(os.getenv("E2E_LFW_DIR", Path(__file__).resolve().parents[2] / "data" / "lfw" / "lfw"))

PERSON = ("Jacques", "Chirac")                       # enrolled through the camera
PHOTO = LFW / "Jacques_Chirac" / "Jacques_Chirac_0001.jpg"
RUN = uuid.uuid4().hex[:6]
ADMIN_PAGES = ["/dashboard", "/register_page", "/capture", "/recognize_page", "/records_page", "/qr_session"]


def write_fake_camera(photo: Path, target: Path) -> Path:
    """
    Write a 4-second 640 x 480 Y4M clip for Chromium's fake camera: the photo on a grey
    background, with the eye band flattened for frames 36-41 (0.4 s) to imitate a blink.
    """
    face = cv2.resize(cv2.imread(str(photo)), (480, 480))
    frame = np.full((480, 640, 3), 120, np.uint8)
    frame[:, 80:560] = face

    boxes, _ = MTCNN(keep_all=True).detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    x1, y1, x2, y2 = np.asarray(boxes[0], dtype=float)
    w, h = x2 - x1, y2 - y1
    # Same band the kiosk measures in analyzeEyeLiveness() (recognize.js)
    top, bottom = int(y1 + 0.18 * h), int(y1 + 0.46 * h)
    left, right = int(x1 + 0.12 * w), int(x1 + 0.88 * w)
    closed = frame.copy()
    closed[top:bottom, left:right] = closed[top:bottom, left:right].mean(axis=(0, 1))

    with target.open("wb") as f:
        f.write(b"YUV4MPEG2 W640 H480 F15:1 Ip A1:1 C420jpeg\n")
        for i in range(60):
            f.write(b"FRAME\n")
            f.write(cv2.cvtColor(closed if 36 <= i < 42 else frame, cv2.COLOR_BGR2YUV_I420).tobytes())
    return target


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    if not PHOTO.is_file():
        pytest.fail(f"{PHOTO} not found. Run `make accuracy` once to download LFW.")
    camera = write_fake_camera(PHOTO, tmp_path_factory.mktemp("camera") / "face.y4m")
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-video-capture={camera}",
        ])
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def errors():
    return []


@pytest.fixture(scope="module")
def page(browser, errors):
    context = browser.new_context(base_url=BASE_URL, permissions=["camera"])
    page = context.new_page()
    page.set_default_timeout(30_000)
    page.on("console", lambda msg: msg.type == "error" and errors.append(f"{page.url}: {msg.text}"))
    page.on("pageerror", lambda exc: errors.append(f"{page.url}: {exc}"))
    try:
        page.request.get("/metrics")
    except Exception:
        pytest.fail(f"Nothing is listening on {BASE_URL}. Start the stack with `docker compose up -d`.")
    yield page
    context.close()


@pytest.fixture(scope="module")
def state():
    """Values one test hands to the next (the tests run in file order)."""
    return {}


def test_login_shows_an_error_for_a_wrong_password(page):
    page.goto("/")
    page.fill("#email", ADMIN_EMAIL)
    page.fill("#password", "Wrong!Password1")
    page.click("#mainBtn")
    expect(page.locator("#errorMsg")).to_contain_text("Invalid credentials")


def test_login_opens_the_dashboard(page):
    page.fill("#password", ADMIN_PASSWORD)
    page.click("#mainBtn")
    expect(page).to_have_url(re.compile(r"/dashboard$"))
    expect(page.locator("#students")).to_have_text(re.compile(r"^\d+$"))
    # Start the day with no attendance
    assert page.request.post("/clear_records").ok


def test_every_admin_page_loads_without_console_errors(page, errors):
    errors.clear()
    for path in ADMIN_PAGES:
        page.goto(path)
        # The kiosk and QR pages poll the server, so the network never goes idle; give
        # their scripts a moment to run instead
        page.wait_for_timeout(1_500)
        assert page.url.endswith(path) or path == "/capture"   # /capture redirects without a pending roll
    assert errors == []


def test_registration_form_shows_server_validation_errors(page):
    page.goto("/register_page")
    page.fill("#first", "Test")
    page.fill("#last", "Student")
    page.fill("#department", "C1")
    page.fill("#year", "2026")
    page.fill("#email", f"validation.{RUN}@example.com")
    page.click("#registerBtn")
    expect(page.locator("#msg")).to_contain_text("Department must be a 2-10 letter code")


def test_register_and_enroll_a_student_with_the_camera(page, state):
    page.goto("/register_page")
    page.fill("#first", PERSON[0])
    page.fill("#last", PERSON[1])
    page.fill("#department", "CSE")
    page.fill("#year", "2026")
    page.fill("#email", f"chirac.{RUN}@example.com")
    page.click("#registerBtn")
    expect(page.locator("#msg")).to_contain_text("Assigned Roll ID")
    state["face_roll"] = re.search(r"Roll ID: (\w+)", page.locator("#msg").inner_text()).group(1)

    page.wait_for_url(re.compile(r"/capture$"))
    expect(page.locator("#rollDisplay")).to_contain_text(state["face_roll"])
    page.click("#startBtn")
    # 5 samples, then the profile is saved and the page returns to the dashboard. The
    # first face request in a fresh container also downloads the FaceNet weights.
    page.wait_for_url(re.compile(r"/dashboard$"), timeout=240_000)


def test_kiosk_recognises_the_student_and_marks_them_after_a_blink(page, state):
    page.goto("/recognize_page")
    result = page.locator("#result")
    expect(result).to_contain_text("Attendance Recorded", timeout=90_000)
    roll = re.search(r"Attendance Recorded: (\w+)", result.inner_text()).group(1)
    # On a reused database an earlier run may have enrolled the same face, so check
    # who was recognised rather than which roll number
    student = page.request.get(f"/get_student/{roll}").json()
    assert (student["first_name"], student["last_name"]) == PERSON
    state["kiosk_roll"] = roll


def test_qr_check_in_from_a_phone(page, browser, state):
    res = page.request.post("/register", data={
        "first_name": "Quinn", "last_name": "Phone", "department": "ECE", "year": "2027",
        "email": f"quinn.{RUN}@example.com",
    })
    state["qr_roll"] = roll = res.json()["roll"]

    with page.expect_response("**/generate_qr_token") as first:
        page.goto("/qr_session")
    checkin_url = first.value.json()["checkin_url"]
    qr = page.locator("#qrImage")
    expect(qr).to_have_attribute("src", re.compile(r"^data:image/svg\+xml"))
    shown = qr.get_attribute("src")
    expect(qr).not_to_have_attribute("src", shown, timeout=8_000)   # rotates every 5 s

    phone = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
    mobile = phone.new_page()
    mobile.goto(checkin_url)
    mobile.fill("#roll", "2099XYZ999")
    mobile.click("#verifyBtn")
    expect(mobile.locator("#msg")).to_contain_text("Student roll number not found")

    mobile.fill("#roll", roll.lower())   # phones often type lower case
    mobile.click("#verifyBtn")
    mobile.wait_for_url(re.compile(r"/qr_verify$"))
    expect(mobile.locator("#name")).to_have_text("Quinn Phone")
    mobile.click("#confirmBtn")
    mobile.wait_for_url(re.compile(r"/qr_result$"))
    expect(mobile.locator("#resultTitle")).to_have_text("Attendance Recorded!")
    phone.close()


def test_records_page_lists_the_check_ins_and_exports_csv(page, state):
    page.goto("/records_page")
    table = page.locator("#table")
    expect(table).to_contain_text(state["kiosk_roll"])
    expect(table).to_contain_text(state["qr_roll"])

    with page.expect_download() as download:
        page.click("a[href='/export_records']")
    csv_text = Path(download.value.path()).read_text()
    assert state["kiosk_roll"] in csv_text and state["qr_roll"] in csv_text


def test_dashboard_counts_the_check_ins(page):
    page.goto("/dashboard")
    expect(page.locator("#present")).to_have_text("2")


def test_purge_clears_the_records(page, state):
    page.goto("/records_page")
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("button.btn-danger")
    expect(page.locator("#table")).not_to_contain_text(state["qr_roll"])
    assert page.request.get("/records").json() == {}


def test_sign_out_returns_to_the_login_page(page, errors):
    page.click("a[href='/logout']")
    expect(page).to_have_url(re.compile(r"/$"))
    page.goto("/dashboard")
    expect(page).to_have_url(re.compile(r"/$"))
    # Chrome logs every 4xx response; the wrong-password and validation tests above
    # trigger those on purpose. Anything else is a real script error.
    assert [e for e in errors if "responded with a status of 4" not in e] == []
