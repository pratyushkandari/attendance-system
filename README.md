# VisionAttend

[![CI](https://github.com/pratyushkandari/attendance-system/actions/workflows/ci.yml/badge.svg)](https://github.com/pratyushkandari/attendance-system/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Classroom attendance with two ways to check in: a face-recognition kiosk, and a rotating QR code that students scan with their phones. Built with Flask, PyTorch (FaceNet) and PostgreSQL.

**Live demo:** https://attendance-system-pratyush.onrender.com
(if the instance has been idle, the first page load can take about a minute)

## How it works

**Face kiosk.** An admin opens the kiosk page on a laptop. The browser sends webcam frames to the server, which finds faces with MTCNN, computes a 512-dimensional FaceNet embedding for each one and compares it against every enrolled student. A face is only marked present after the browser has seen that face blink, so holding up a printed photo doesn't work.

**Rotating QR code.** The classroom screen shows a QR code that changes every 5 seconds. Each code carries a token signed with HMAC-SHA256 that expires after 35 seconds, so a photo of the code sent to someone outside the room stops working almost immediately. Students scan it, enter their roll number and confirm.

Each student is recorded at most once per day (IST). Admins can browse, filter, export (CSV) and clear records from the dashboard.

## Features

- Admin sign-in with scrypt-hashed passwords: session cookies for the browser, JWTs for API clients
- Account lockout after repeated failed logins, shared across workers through Redis when it's configured
- Student enrollment with generated roll numbers (`2026CSE001`) and a 5-sample face capture
- Face detection on every 4th frame with OpenCV CSRT tracking in between, to keep CPU usage down
- Face matching as one matrix-vector product against a cached matrix of all enrolled students
- QR codes rendered on the server, so check-in tokens never go to a third-party service
- Prometheus metrics at `/metrics`, plus Docker Compose and Kubernetes configs

## Tech stack

Python 3.10, Flask 3.1, SQLAlchemy 2.0, PostgreSQL 16, facenet-pytorch on CPU PyTorch 2.14, OpenCV (contrib), NumPy, PyJWT, itsdangerous, segno, Redis (optional), prometheus-client and Gunicorn. The frontend is server-rendered Jinja templates with plain JavaScript.

## Getting started

### Docker Compose

Starts the app, PostgreSQL, Redis, Prometheus and Grafana. The database is seeded with a demo admin and two students.

```bash
cp .env.example .env
# set SECRET_KEY in .env, for example: python -c "import secrets; print(secrets.token_hex(32))"
docker compose up -d --build
```

| Service | URL |
| --- | --- |
| App | http://localhost:5000 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin / admin) |

Grafana starts without dashboards; add Prometheus (`http://prometheus:9090`) as a data source.

### Local Python environment

You need Python 3.10+ and PostgreSQL (SQLite also works). Redis is optional.

```bash
git clone https://github.com/pratyushkandari/attendance-system.git
cd attendance-system
python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\activate

pip install --upgrade pip
pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt

cp .env.example .env              # set SECRET_KEY, and DATABASE_URL if yours differs
python run.py                     # http://localhost:5000
```

To load the demo data into PostgreSQL:

```bash
psql -U postgres -d attendence_db -f seed.sql
```

That creates the admin `admin@institution.edu` / `AdminSecure@2026!` and two students without face profiles. Change the password on anything other than a local setup. Without the seed data, you can create the first admin from the login page.

The first face request downloads the FaceNet weights (about 110 MB) into the PyTorch cache, so expect it to be slow.

## Configuration

Settings come from environment variables; a `.env` file in the project root is loaded automatically.

| Variable | Default | Description |
| --- | --- | --- |
| `SECRET_KEY` | none, required | Signs sessions, JWTs and QR tokens. The app won't start without it, or with a value that has appeared in this repository. |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/attendence_db` | Any SQLAlchemy URL. `sqlite:///attendance.db` is fine for local use. |
| `REDIS_URL` | unset | Shares login-lockout counters between workers. Without it, each process keeps its own. |
| `PORT` | `5000` | Port used by `python run.py`. |
| `ALLOW_PUBLIC_ADMIN_SIGNUP` | `false` | Lets anyone create an admin account. Only for public demos. |
| `LOCKOUT_THRESHOLD` | `3` | Failed logins before an email is locked. |
| `LOCKOUT_DURATION_SECONDS` | `900` | How long the lock lasts. |
| `FACE_MATCH_THRESHOLD` | `0.70` | Minimum cosine similarity to accept a face match. |
| `MTCNN_CONFIDENCE_THRESHOLD` | `0.90` | Minimum face-detection confidence. |

## Project structure

```
app/
├── __init__.py       app factory: config, blueprints, metrics, table creation
├── config.py         settings read from the environment
├── extensions.py     SQLAlchemy and the Redis / in-memory cache
├── metrics.py        Prometheus metrics
├── ai/               MTCNN and FaceNet models, embedding matching
├── models/           Admin, Student, Attendance
├── routes/           auth and pages, enrollment, recognition and attendance
├── static/           CSS and JavaScript
└── templates/        Jinja templates
tests/                pytest suite (in-memory SQLite, no external services)
docs/                 API reference, design decisions, security, operations
k8s/                  Kubernetes manifests
```

## API

All request bodies are JSON. Admin endpoints accept either the session cookie or an `Authorization: Bearer <token>` header. The full reference, with request and response examples, is in [docs/API_SPECIFICATION.md](docs/API_SPECIFICATION.md).

| Endpoint | Access | Purpose |
| --- | --- | --- |
| `POST /login_admin` | public | Sign in; returns a JWT and sets the session cookie |
| `POST /register_admin` | first admin, then admins | Create an admin account |
| `GET /logout` | any | Clear the session |
| `POST /register` | admin | Create a student and assign a roll number |
| `POST /capture_face` | admin | Get the embedding of the largest face in a frame |
| `POST /save_face_data` | admin | Save a student's averaged face embedding |
| `POST /recognize_with_box` | admin | Detect, identify and track faces in a kiosk frame |
| `GET /generate_qr_token` | admin | New QR token, check-in URL and SVG QR code |
| `POST /verify_qr_token` | public | Check a scanned token |
| `POST /verify_student` | QR token or admin | Check that a roll number exists |
| `GET /get_student/<roll>` | QR token or admin | Student details for the confirmation screen |
| `POST /mark_attendance` | QR token (QR) or admin (Face) | Record today's attendance |
| `GET /records` | admin | Records grouped by date |
| `GET /export_records` | admin | CSV export, filterable by `date`, `dept` and `roll` |
| `POST /clear_records` | admin | Delete all attendance records |
| `GET /dashboard_data` | admin | Total, present and absent counts for today |
| `GET /metrics` | public | Prometheus metrics |

```bash
# Sign in
curl -X POST http://localhost:5000/login_admin \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@institution.edu", "password": "AdminSecure@2026!"}'

# Register a student
curl -X POST http://localhost:5000/register \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"first_name": "Alexander", "last_name": "Wright", "department": "CSE", "year": "2026", "email": "a.wright@institution.edu"}'

# Export one day's CSE records
curl "http://localhost:5000/export_records?dept=CSE&date=2026-10-27" \
  -H "Authorization: Bearer <token>" -o attendance.csv
```

## Tests

```bash
make test        # python -m pytest
make coverage    # with a coverage report
make lint        # ruff and bandit
```

The tests run against an in-memory SQLite database, so they don't need PostgreSQL, Redis or network access. The model inference path (MTCNN and FaceNet) isn't covered by unit tests because it needs the downloaded weights and real face images, and the browser-side blink check has no automated tests.

CI runs ruff, bandit and the test suite on every push and pull request to `main`.

## Deployment

The app runs from the Docker image or directly with `python run.py`, which starts Gunicorn on `$PORT` (one worker, four threads). Wherever it runs, set `SECRET_KEY` and `DATABASE_URL` in the environment.

The `k8s/` directory has a Deployment, Service, ConfigMap and HorizontalPodAutoscaler. Deployment steps, monitoring and troubleshooting are in [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md).

## Known limitations

- A QR token can be used by anyone for up to 35 seconds, with any roll number. It makes proxy attendance harder but doesn't prevent it.
- The blink check runs in the browser and won't catch a video of a student played on a phone screen.
- Lockout is per email, so someone who knows an admin's email can lock that account for 15 minutes.
- JWTs can't be revoked and stay valid for 24 hours, even after logging out.
- The one-check-in-per-day rule is enforced in application code, not by a database constraint.
- There are no migrations. `db.create_all()` creates missing tables but never alters existing ones.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [API reference](docs/API_SPECIFICATION.md)
- [Design decisions](docs/ARCHITECTURE_DECISION_RECORDS.md)
- [Security](docs/SECURITY.md)
- [Operations](docs/OPERATIONS_RUNBOOK.md)
- [Benchmarks](docs/BENCHMARKS.md)
- [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE)
