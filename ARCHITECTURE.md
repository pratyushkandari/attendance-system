# Architecture

How VisionAttend is put together. Setup instructions are in the [README](README.md), and the reasoning behind the main design choices is in [docs/ARCHITECTURE_DECISION_RECORDS.md](docs/ARCHITECTURE_DECISION_RECORDS.md).

## Overview

```
 Admin browser (kiosk)          Admin browser (classroom screen)       Student phone
  webcam -> JPEG frames           polls every 5 s                       scans QR -> /qr_mobile
  blink check per face            shows server-rendered QR              roll number -> confirm
        |                                 |                                    |
        v                                 v                                    v
 +--------------------------------- Flask app (run.py -> Gunicorn) ---------------------------------+
 | routes/main.py        auth (session or JWT), lockout, QR token issue/verify, HTML pages          |
 | routes/student.py     enrollment, face capture, embedding save, QR-gated student lookup          |
 | routes/attendance.py  recognition and tracking, mark attendance, records, CSV export, dashboard  |
 | ai/facenet_model.py   lazily loaded MTCNN + FaceNet     ai/comparator.py   embedding matching    |
 | metrics.py            request counters and latency, /metrics                                     |
 +----------------+------------------------------------------+--------------------------------------+
                  v                                          v
     PostgreSQL (SQLite in tests)                Redis (optional) or in-process store
     admins, students, attendance                failed-login counters
```

The app is a single Flask service. It serves the admin pages and the JSON API, runs face detection and recognition in-process on the CPU, stores everything in PostgreSQL, and can use Redis for login-lockout counters.

| Module | Responsibility |
| --- | --- |
| `app/__init__.py` | App factory: loads config, checks `SECRET_KEY`, registers blueprints and metrics, creates tables |
| `app/routes/main.py` | Login, sessions and JWTs, lockout, QR token issue and verification, page routes |
| `app/routes/student.py` | Student registration, face capture, saving embeddings, QR-gated student lookup |
| `app/routes/attendance.py` | Recognition and tracking, marking attendance, records, CSV export, dashboard data |
| `app/ai/facenet_model.py` | MTCNN and InceptionResnetV1 (VGGFace2 weights), loaded on first use |
| `app/ai/comparator.py` | Scores a query embedding against the matrix of enrolled embeddings |
| `app/extensions.py` | SQLAlchemy and `SafeCacheStore` (Redis with an in-memory fallback) |
| `app/metrics.py` | Prometheus counters, histograms and gauges |

## Data model

- **admins**: email and scrypt password hash.
- **students**: roll number, name, department, year, email, and the face embedding (512 floats stored as JSON text).
- **attendance**: roll number, method (`Face` or `QR`) and timestamp. Timestamps are stored as naive datetimes in IST.

Tables are created with `db.create_all()` at startup. `seed.sql` creates the same schema for PostgreSQL along with demo data.

## Enrollment

1. The admin fills in the student form (`POST /register`). The server validates it and assigns the next roll number for that year and department, e.g. `2026CSE001`.
2. The capture page takes five webcam frames and sends each one to `POST /capture_face`, which returns the embedding of the largest face in the frame. Frames without a usable face are skipped.
3. `POST /save_face_data` averages the five embeddings, scales the result to unit length and stores it. It also clears the recognition cache so the student can be recognised right away.

## Face check-in

The kiosk page sends a 380 px wide JPEG to `POST /recognize_with_box`, waits for the response, then sends the next frame. Each browser tab has its own `client_id` so the server can keep separate tracker state per kiosk.

```
frame
  -> decode; if mean brightness < 35, tell the operator to switch to QR
  -> keyframe? (every 4th frame for this kiosk, or no face is being tracked)
       yes: MTCNN detection -> crop each face, resize to 160x160
            -> FaceNet embedding -> score against all enrolled students
            -> start one CSRT tracker per face
       no:  update the existing CSRT trackers
  -> return boxes, roll numbers and scores
```

Detection and embedding are by far the most expensive steps, so they only run on keyframes. In between, the CSRT trackers keep the boxes on the faces. Boxes are returned in frame coordinates and the browser maps them onto the video element, accounting for the `object-fit: cover` crop.

### Matching

Every embedding is scaled to unit length, so cosine similarity is just a dot product. The enrolled embeddings are stacked into an `N x 512` float32 matrix, and `matrix @ query` gives every student's score in one call. The best score counts as a match if it's at least `FACE_MATCH_THRESHOLD` (0.70 by default).

Building that matrix means loading and parsing every stored embedding, which is slow, so it's cached per process. The cache is rebuilt after 30 seconds, or straight away when an enrollment is saved in the same process. Timings are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

### Blink check

For each recognised face, the browser measures the contrast of a band across the eyes (from 18% to 46% of the face box height, 76% of its width). A blink shows up as a short dip: contrast falls below 88% of the recent average and recovers above 92% within 40 to 1200 ms. The kiosk calls `POST /mark_attendance` for a face only after it has seen that face blink. If a face leaves the frame for more than 1.5 seconds, it has to blink again.

This check runs in the browser. The server only requires that `Face` check-ins come from a signed-in admin, so it can't tell whether a blink actually happened. A video of a blinking student played on a phone will pass.

## QR check-in

1. The classroom screen calls `GET /generate_qr_token` every 5 seconds. The server creates a token (a random nonce and a timestamp, signed by itsdangerous with HMAC-SHA256 and the app's `SECRET_KEY`), builds the `/qr_mobile?token=...` URL and returns it as an SVG QR code generated with segno.
2. The student's phone opens that URL. The page checks the token with `POST /verify_qr_token` (accepted up to 30 seconds old), then looks up the roll number the student types with `POST /verify_student` and `GET /get_student/<roll>`. Both lookups require the token, so nobody can walk through roll numbers to collect student names.
3. Confirming sends `POST /mark_attendance` with `method: "QR"` and the token (accepted up to 35 seconds old, to leave time for typing).

The whole class scans the same code, so a token can't be single-use. Its job is to make a forwarded photo of the code useless after about 35 seconds.

The app wraps Werkzeug's `ProxyFix` around the WSGI app and trusts one `X-Forwarded-Proto` hop, so the check-in URL uses `https` behind Render's proxy or a Kubernetes ingress.

## Authentication

- `POST /login_admin` checks the password against its scrypt hash. Unknown emails are checked against a dummy hash, so a failed login takes the same time whether or not the email exists.
- A successful login sets a signed session cookie (`HttpOnly`, `SameSite=Lax`) and returns a 24-hour HS256 JWT.
- The `@admin_required` decorator accepts a Bearer token first, then the session. API callers without valid credentials get a JSON `401`; a browser loading an admin page is redirected to the login page.
- Failed logins are counted per email in `SafeCacheStore`. After 3 failures the email is locked for 15 minutes, and a successful login resets the count.
- Anyone can create the first admin from the login page. After that, only a signed-in admin can create more, unless `ALLOW_PUBLIC_ADMIN_SIGNUP=true`.

## Concurrency and runtime state

- `run.py` starts Gunicorn with one worker and four threads. PyTorch is limited to one thread (`torch.set_num_threads(1)`) and the Docker image limits BLAS to one thread, so the request threads don't fight over CPU cores.
- MTCNN and FaceNet are loaded on first use, under a lock, so two simultaneous first requests don't load the models twice.
- Tracker state lives in process memory, keyed by `client_id`, protected by a lock and dropped after 120 seconds of inactivity. With several pods, a kiosk's frames should stick to one pod (session affinity). If they don't, the trackers are rebuilt on the next keyframe.
- The database pool uses `pool_pre_ping` and recycles connections after 280 seconds, since hosted PostgreSQL providers close idle connections.
- Request bodies larger than 10 MB are rejected with `413`.
- `create_app` refuses to start if `SECRET_KEY` is empty or is a value that has been committed to this repository.

## Failure handling

- **Low light.** If a frame's mean brightness is below 35, the kiosk shows a banner with a link to the QR session.
- **No camera.** If the browser can't open the webcam (no device, or permission denied), the kiosk offers the QR session instead.
- **Redis down.** `SafeCacheStore` falls back to an in-memory store with expiry times and re-checks Redis every 30 seconds. Lockout keeps working, but per process.
- **Bad input.** Images that can't be decoded get a `400` (or an error field in the kiosk response, so the kiosk keeps running) instead of a server error.
