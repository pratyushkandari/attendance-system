# Testing

How the app is tested, from fast unit tests to checks against the running stack, and the latest results.

## Suites

| Suite | Command | Needs | Latest result |
| --- | --- | --- | --- |
| Lint | `make lint` | nothing | ruff and bandit clean |
| Unit and integration | `make test` | nothing (in-memory SQLite, in-process cache) | 148 passed, 92.5% coverage |
| End-to-end | `make e2e` | the Docker Compose stack, LFW photos | 12 passed |
| Browser | `make browser` | the Docker Compose stack, LFW photos, Chromium (the command installs it) | 11 passed |
| Recognition accuracy | `make accuracy` | the LFW download (about 180 MB) | [ACCURACY.md](ACCURACY.md) |
| Load | `make loadtest` | the Docker Compose stack | [BENCHMARKS.md](BENCHMARKS.md) |

CI runs the lint checks and `make test` on every push and pull request to `main`, and uploads the JUnit report and coverage XML as the `test-results` artifact. The end-to-end and browser suites need a running stack and the LFW photos, so they run locally.

To run the stack-based suites:

```bash
docker compose up -d
make accuracy        # the first run downloads LFW into data/, which the other suites reuse
make e2e
make browser
```

Both stack-based suites clear the stack's attendance records, so don't run them against data you want to keep. They read `E2E_BASE_URL` (default `http://127.0.0.1:5000`), `E2E_ADMIN_EMAIL` and `E2E_ADMIN_PASSWORD` (default: the `seed.sql` demo admin) and `E2E_LFW_DIR`.

## Unit and integration tests

| File | Covers |
| --- | --- |
| `tests/test_auth.py` | Admin signup and login, email and password rules, JWT and session auth, lockout (including expiry and corrupt records), cookie flags, the `SECRET_KEY` check |
| `tests/test_pages.py` | Every HTML page: redirects for anonymous visitors, rendering for admins, the public phone pages, sign-out |
| `tests/test_student.py` | Registration validation and roll clashes, `capture_face` outcomes, `save_face_data` validation, student lookups |
| `tests/test_attendance.py` | QR and face check-in, same-day duplicates, IST day boundaries, records, CSV export and filters, purge, dashboard counts, metrics |
| `tests/test_recognition.py` | `recognize_with_box` with MTCNN and FaceNet stubbed and real CSRT trackers: matching, unknown faces, filtering of low-confidence, tiny and flat faces, keyframes versus tracking frames, per-kiosk sessions, errors |
| `tests/test_crypto.py` | QR token signing (HMAC-SHA256), tampering, expiry and the 30-second verification window, server-side QR rendering, `SafeCacheStore` expiry and Redis fallback |
| `tests/test_vector.py` | Matrix matching |
| `tests/test_core.py` | Config flag parsing, the FaceNet wrapper with a fake network, `Student` model helpers |

None of these download the FaceNet weights or use the network. MTCNN runs with the weights bundled in facenet-pytorch.

Coverage by module:

| Module | Lines | Branches |
| --- | ---: | ---: |
| `app/__init__.py` | 100% | 100% |
| `app/config.py` | 85.7% | 62.5% |
| `app/extensions.py` | 78.6% | 84.6% |
| `app/metrics.py` | 100% | 100% |
| `app/ai/comparator.py` | 100% | 100% |
| `app/ai/facenet_model.py` | 89.8% | 41.7% |
| `app/models/` | 100% | 100% |
| `app/routes/attendance.py` | 89.7% | 85.5% |
| `app/routes/main.py` | 100% | 99.0% |
| `app/routes/student.py` | 92.0% | 92.7% |
| **Total** | **93.3%** | **89.9%** |

Not covered by this suite:

- The `except` branches that turn unexpected database or server errors into `500` responses.
- Connecting to a real Redis server (`app/extensions.py`). The fallback and reconnect logic is tested with a fake client.
- Settings evaluated when `app/config.py` is imported, such as a missing python-dotenv or a non-PostgreSQL database URL.
- Loading the real models (`get_mtcnn()`, `get_resnet()`). The end-to-end and browser suites use them.
- The KCF and `cv2.legacy` fallbacks in `_create_tracker()`, for OpenCV builds without CSRT.

## End-to-end tests

`tests/e2e/` sends real HTTP requests to the Compose stack: Gunicorn, PostgreSQL, Redis and the face models. The students are people from LFW. The tests cover:

- registration and roll sequences
- enrollment from 5 photos
- the kiosk recognising each student from a photo it hasn't seen
- an unregistered person reported as unknown
- two people in one frame
- tracking between keyframes
- face then QR, and QR then face, on the same day
- QR check-in from an unauthenticated phone session
- an unregistered roll number
- dashboard counts, records and CSV export
- lockout stored in Redis
- purge

## Browser tests

`tests/browser/` drives Chromium with Playwright against the same stack. It covers:

- login with a wrong and a correct password
- every admin page loading without console errors
- server validation messages on the registration form
- registering and enrolling a student through the camera
- the kiosk recognising that student and recording attendance after a blink
- the rotating QR code
- check-in from a phone-sized browser, including an unknown roll number
- the records page and CSV download, dashboard counts, purge and sign-out

Chromium's fake camera plays a 4-second clip made from an LFW photo (`Jacques_Chirac_0001`). In that clip the band the kiosk measures for liveness is flattened for 0.4 s, which the check reads as a blink. That runs the real kiosk code, but it isn't a person blinking. A real blink is the first manual check below.

## Manual checks

The automated suites can't do these. Run them with the stack up and a real webcam.

1. **A real blink.** Enroll yourself on Student Enrollment, then open Biometric Kiosk. Your box shows your roll number followed by "[Blink]". Blink once. The box turns cyan, and the result line reads "Attendance Recorded: <roll> (Live Verified)".
2. **A photo held up to the camera.** Hold up a printed or on-screen photo of an enrolled student and keep it still. It's recognised but stays at "[Blink]" and isn't recorded. Moving the photo can occasionally read as a blink; if it does, note it. A video of the student blinking will pass (see the known limitations in the README).
3. **Low light.** Cover the camera or dim the room. After two dark frames, the kiosk shows "Sub-Optimal Lighting Detected" and offers QR check-in.
4. **QR check-in on a real phone.** Open Dynamic QR at the computer's network address (for example `http://192.168.1.20:5000/qr_session`) and sign in there, scan the code with a phone on the same Wi-Fi, enter a roll number and confirm. The phone shows "Attendance Recorded!", and the record appears on Audit Logs.

## Latest results

3 November 2026, commit `f425b2d`. Intel Core i5-12500H, Windows 11, Python 3.10.11, Docker Desktop, Chromium from Playwright 1.64.1.

| Suite | Passed | Failed | Notes |
| --- | ---: | ---: | --- |
| Lint | | | ruff and bandit report nothing |
| Unit and integration | 148 | 0 | 92.5% coverage (93.3% of lines, 89.9% of branches) |
| End-to-end | 12 | 0 | |
| Browser | 11 | 0 | |

Before this round there were 59 unit and integration tests at 74.3% coverage, the 12 end-to-end tests, and no browser tests. No bugs were found in the app.
