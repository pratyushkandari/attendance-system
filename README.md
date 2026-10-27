# VisionAttend: Face Recognition & Dynamic QR Attendance

[![CI Pipeline](https://github.com/pratyushkandari/attendance-system/actions/workflows/ci.yml/badge.svg)](https://github.com/pratyushkandari/attendance-system/actions)
[![Live Demo](https://img.shields.io/badge/Live_Demo-Render_Cloud-success?style=flat-square&logo=render)](https://attendance-system-60nr.onrender.com)
[![Python](https://img.shields.io/badge/Python-3.10-blue?style=flat-square&logo=python)](https://python.org)
[![PyTorch](https://img.shields.io/badge/PyTorch-CPU-EE4C2C?style=flat-square&logo=pytorch)](https://pytorch.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

A Flask application for classroom attendance with two check-in channels:

* **Face kiosk:** an admin's browser streams webcam frames; the server detects faces (MTCNN), embeds them (FaceNet `InceptionResnetV1`, VGGFace2 weights) and matches them against enrolled students. The browser requires each recognised face to blink before attendance is recorded.
* **Dynamic QR:** the classroom screen shows a QR code that rotates every 5 seconds. Each code carries an HMAC-SHA256 signed token, so a photo of the code stops working within 35 seconds. Students scan it with their phone camera, type their roll number and confirm.

Each student is recorded at most once per day (Indian Standard Time). Admins can browse, export (CSV) and purge records, and Prometheus can scrape request metrics.

🔗 **Live deployment:** [attendance-system-60nr.onrender.com](https://attendance-system-60nr.onrender.com)

---

## Features

| Area | What it does |
| :--- | :--- |
| Admin access | Sign-in with a scrypt-hashed password. Browsers use a signed session cookie (`HttpOnly`, `SameSite=Lax`); API clients get a 24-hour HS256 JWT. 3 failed attempts lock an email for 15 minutes. Only the first admin can sign up from the login page; later admins are created by an existing admin. |
| Enrollment | Admin enters name, department, year and email; the server assigns a roll number such as `2026CSE001`. The capture page then takes 5 webcam samples, and the server stores their averaged, unit-length 512-D embedding. |
| Face kiosk | Detection and embedding run on every 4th frame per kiosk; OpenCV CSRT trackers move the boxes in between. Matching is one matrix-vector product against a cached matrix of all enrolled faces. Low-light frames and camera failures prompt the operator to switch to QR. |
| QR check-in | Admin-only token endpoint; the server renders the QR code itself. The phone flow checks the token, looks up the roll number (only with a live token, so names can't be scraped) and records the check-in. |
| Records | Dashboard counts for today, records grouped by day, CSV export with optional `date`/`dept`/`roll` filters, and a purge action. |
| Operations | `/metrics` for Prometheus, Docker Compose stack (app, PostgreSQL 16, Redis 7, Prometheus, Grafana), Kubernetes manifests with an HPA. |

---

## Architecture

```
 Admin browser (kiosk)          Admin browser (classroom screen)       Student phone
  webcam → JPEG frames            polls every 5 s                       scans QR → /qr_mobile
  blink check per face            shows server-rendered QR              roll number → confirm
        │                                 │                                    │
        ▼                                 ▼                                    ▼
 ┌───────────────────────────────── Flask app (run.py → Gunicorn) ─────────────────────────────────┐
 │ routes/main.py        auth (session or JWT), lockout, QR token issue/verify, HTML pages          │
 │ routes/student.py     enrollment, face capture, embedding save, QR-gated student lookup          │
 │ routes/attendance.py  recognition + tracking, mark attendance, records, CSV export, dashboard    │
 │ ai/facenet_model.py   lazy MTCNN + FaceNet singletons      ai/comparator.py  matrix matching     │
 │ metrics.py            request counters/latency, /metrics                                         │
 └──────────────┬──────────────────────────────────────┬───────────────────────────────────────────┘
                ▼                                      ▼
   PostgreSQL (SQLite in tests)            Redis (optional) or in-process store
   admins · students (embedding as JSON)   failed-login counters only
   attendance (naive IST timestamps)
```

**Face check-in flow**
1. `recognize.js` sends a 380-px-wide JPEG to `POST /recognize_with_box` with a per-tab `client_id`.
2. On a keyframe the server runs MTCNN, crops each confident face, computes its embedding and takes the best cosine score against the cached profile matrix (`FACE_MATCH_THRESHOLD`, default 0.70). It then starts one CSRT tracker per face. Other frames only update the trackers.
3. The response lists boxes, rolls and scores. The browser tracks eye-region contrast per recognised roll; after that face's own blink it calls `POST /mark_attendance` with `method: "Face"` (accepted only from an admin session or JWT).

**QR check-in flow**
1. `qr_session.html` calls `GET /generate_qr_token` every 5 s and shows the returned `qr_svg`, which encodes `/qr_mobile?token=…`.
2. The phone stores the token, calls `POST /verify_qr_token` (accepts tokens up to 30 s old), then `POST /verify_student` and `GET /get_student/<roll>`.
3. Confirming calls `POST /mark_attendance` with `method: "QR"` (token up to 35 s old).

**Enrollment flow:** `POST /register` → `/capture` page → 5 × `POST /capture_face` → `POST /save_face_data`, which also refreshes the kiosk's profile cache.

Design decisions and trade-offs are recorded in [docs/ARCHITECTURE_DECISION_RECORDS.md](docs/ARCHITECTURE_DECISION_RECORDS.md); a longer walkthrough is in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Tech Stack

Python 3.10 · Flask 3.1 · Flask-SQLAlchemy / SQLAlchemy 2.0 · PostgreSQL 16 · facenet-pytorch (MTCNN, InceptionResnetV1) on CPU PyTorch 2.14 · OpenCV contrib (CSRT tracking) · NumPy · PyJWT · itsdangerous · segno (QR rendering) · Redis (optional) · prometheus-client · Gunicorn · vanilla JavaScript + Jinja2 templates.

```
app/
  __init__.py          app factory: config, SECRET_KEY check, ProxyFix, blueprints, metrics, create_all()
  config.py            environment-driven settings
  extensions.py        SQLAlchemy instance and SafeCacheStore (Redis with in-memory fallback)
  ai/                  facenet_model.py (models, embeddings), comparator.py (matrix matching)
  models/              Admin, Student, Attendance
  routes/              main.py, student.py, attendance.py
  static/, templates/  admin pages, kiosk, QR screens, shared common.js
tests/                 pytest suite (SQLite in memory, no network services)
k8s/, Dockerfile, docker-compose.yml, prometheus.yml, seed.sql
```

---

## API

All `POST` bodies are JSON. Admin endpoints accept either the session cookie or `Authorization: Bearer <jwt>`. Unauthenticated API calls get `401` JSON; a browser navigating to an admin URL is redirected to the login page. Bodies over 10 MB get `413`. Full request/response schemas: [docs/API_SPECIFICATION.md](docs/API_SPECIFICATION.md).

| Method & path | Access | Purpose |
| :--- | :--- | :--- |
| `POST /login_admin` | public | Sign in; returns a JWT and sets the session cookie |
| `POST /register_admin` | first admin, then admins only | Create an admin account |
| `GET /logout` | any | Clear the session |
| `POST /register` | admin | Create a student and assign a roll number |
| `POST /capture_face` | admin | Return the embedding of the largest face in one frame |
| `POST /save_face_data` | admin | Store the averaged embedding for a roll number |
| `POST /recognize_with_box` | admin | Detect, identify and track faces in one kiosk frame |
| `GET /generate_qr_token` | admin | New signed token, its check-in URL and the QR code (`qr_svg`) |
| `POST /verify_qr_token` | public | Check a scanned token |
| `POST /verify_student` | live QR token or admin | Does this roll number exist? |
| `GET /get_student/<roll>` | `X-QR-Token` header or admin | Name, department and year for the confirm screen |
| `POST /mark_attendance` | QR: live token · Face: admin | Record today's attendance |
| `GET /records` | admin | Records grouped by IST date |
| `GET /export_records` | admin | CSV export (`date=YYYY-MM-DD`, `dept`, `roll` filters) |
| `POST /clear_records` | admin | Delete all attendance records |
| `GET /dashboard_data` | admin | Total students, present today, absent |
| `GET /metrics` | public | Prometheus metrics |

```bash
# Sign in (returns {"token": "...", "token_type": "Bearer", ...})
curl -X POST http://localhost:5000/login_admin \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@institution.edu", "password": "AdminSecure@2026!"}'

# Enroll a student
curl -X POST http://localhost:5000/register \
  -H "Authorization: Bearer <jwt>" -H "Content-Type: application/json" \
  -d '{"first_name": "Alexander", "last_name": "Wright", "department": "CSE", "year": "2026", "email": "a.wright@institution.edu"}'

# Export today's CSE records
curl "http://localhost:5000/export_records?dept=CSE&date=2026-10-27" \
  -H "Authorization: Bearer <jwt>" -o attendance_report.csv
```

---

## Configuration

Settings are read from the environment (and from `.env` via python-dotenv). Copy [.env.example](.env.example) to `.env` to start.

| Variable | Default | Notes |
| :--- | :--- | :--- |
| `SECRET_KEY` | none (required) | Signs sessions, JWTs and QR tokens. The app refuses to start if it is empty or a value previously published in this repo. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/attendence_db` | `postgres://` URLs are rewritten for SQLAlchemy. SQLite works for local use, e.g. `sqlite:///attendance.db`. The database must be reachable at startup (tables are created then). |
| `REDIS_URL` | unset | When set, failed-login counters are shared by all workers/pods; otherwise each process keeps its own. |
| `PORT` | `5000` | Port for `python run.py`. |
| `ALLOW_PUBLIC_ADMIN_SIGNUP` | `false` | `true` lets any visitor create an admin account (public demos only). |
| `LOCKOUT_THRESHOLD` / `LOCKOUT_DURATION_SECONDS` | `3` / `900` | Failed logins before lockout, and lockout length. |
| `FACE_MATCH_THRESHOLD` | `0.70` | Minimum cosine similarity for a face match. |
| `MTCNN_CONFIDENCE_THRESHOLD` | `0.90` | Minimum face-detection confidence. |

---

## Local Setup

Prerequisites: Python 3.10+, and PostgreSQL 16 or SQLite. Redis is optional.

```bash
git clone https://github.com/pratyushkandari/attendance-system.git
cd attendance-system
python -m venv venv
source venv/bin/activate            # Windows: .\venv\Scripts\activate

# CPU-only PyTorch first (same pinned versions as the Dockerfile and CI), then the app and dev tools
pip install --upgrade pip
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt   # production installs use requirements.txt

cp .env.example .env                  # then set SECRET_KEY (and DATABASE_URL if needed)
```

Optional demo data for PostgreSQL (creates the tables, one admin and two students without face profiles):

```bash
psql -U postgres -d attendence_db -f seed.sql
```

The seeded admin is `admin@institution.edu` / `AdminSecure@2026!`; change it in any shared deployment. Without the seed, create the first admin from the login page ("Initialize Admin Profile").

```bash
python run.py        # http://localhost:5000 (Gunicorn on Linux/macOS, Flask's server on Windows)
```

The first face request downloads the VGGFace2 FaceNet weights (about 100 MB) into the PyTorch cache.

---

## Docker Compose

Runs the app, PostgreSQL 16 (initialised from `seed.sql`), Redis 7, Prometheus and Grafana. Compose reads `SECRET_KEY` from `.env` and stops if it is missing.

```bash
cp .env.example .env    # set SECRET_KEY
docker compose up -d --build
```

| Service | URL |
| :--- | :--- |
| App | http://localhost:5000 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (`admin` / `admin`; no dashboards are provisioned: add Prometheus at `http://prometheus:9090` as a data source) |
| PostgreSQL / Redis | `localhost:5432` / `localhost:6379` |

---

## Kubernetes

`k8s/` contains a ConfigMap, Deployment (2 replicas), LoadBalancer Service and an HPA (2–10 pods on CPU/memory). Before applying them you need to:

1. Build and push the image referenced in `k8s/deployment.yaml` (no workflow here publishes it).
2. Create the secret: `kubectl create secret generic attendance-secrets --from-literal=database-url=... --from-literal=secret-key=...`
3. Provide a Redis Service named `redis-service`, or each pod keeps its own lockout counters.

```bash
make k8s-apply
```

Kiosk tracker state lives in each process, so with several replicas a kiosk's frames should reach the same pod (session affinity); otherwise trackers are simply rebuilt on the next keyframe.

---

## Tests & Quality Checks

59 tests run against an in-memory SQLite database and the in-process cache, so no PostgreSQL, Redis or network access is needed:

```bash
python -m pytest                                   # all tests
python -m pytest --cov=app --cov-report=term-missing
ruff check .                                       # lint (pyupgrade, bugbear, isort, pyflakes, pycodestyle)
bandit -r app/ -ll                                 # security scan
```

* `tests/test_auth.py`: login, JWT and session auth, lockout, password and email rules, admin bootstrap, login timing equalisation, required `SECRET_KEY`, 401/413 behaviour.
* `tests/test_crypto.py`: QR token signing (HMAC-SHA256), expiry and tampering, server-rendered QR codes, cache fallback to memory and Redis reconnection.
* `tests/test_attendance.py`: enrollment validation and roll numbers, QR and Face check-in rules, one record per IST day, QR-gated lookups, embedding validation, profile caching, malformed images, dashboard, CSV export, `/metrics`.
* `tests/test_vector.py`: matrix matching.

The MTCNN/FaceNet inference path needs the downloaded weights and a real face, so it is not covered by unit tests; verify it with a webcam. The browser-side blink check has no automated tests.

[CI](.github/workflows/ci.yml) runs on every push and pull request to `main`: install pinned dependencies, then `ruff`, `bandit` and `pytest` with coverage. Any failure fails the build.

---

## Known Limitations

* A QR token can be used by anyone for up to 35 seconds, for any roll number.
* Liveness (blink) detection runs in the kiosk browser and does not detect video replays.
* Anyone can lock out an admin by repeatedly entering a wrong password for that email; JWTs stay valid for 24 hours after logout.
* One-record-per-day is an application-level check, not a database constraint.
* `db.create_all()` creates missing tables but never alters existing ones; there are no migrations.

See [docs/SECURITY.md](docs/SECURITY.md) for the threat model.

## Further Documentation

[ARCHITECTURE.md](ARCHITECTURE.md) · [API specification](docs/API_SPECIFICATION.md) · [Decision records](docs/ARCHITECTURE_DECISION_RECORDS.md) · [Benchmarks](docs/BENCHMARKS.md) · [Security](docs/SECURITY.md) · [Operations runbook](docs/OPERATIONS_RUNBOOK.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Project handbook](PROJECT_HANDBOOK.html)

## License

MIT; see [LICENSE](LICENSE).
