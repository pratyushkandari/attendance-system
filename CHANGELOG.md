# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

**Upgrading:** the default `FACE_MATCH_THRESHOLD` is now 0.79. Deployments that set it explicitly keep their own value.

### Changed
- Raised the default face match threshold from 0.70 to 0.79, based on an evaluation on LFW. At 0.70, 1.4% of people who weren't enrolled were accepted as an enrolled student; at 0.79 it's 0.13%. See `docs/ACCURACY.md`.
- The match threshold and detection confidence are read only from the config. The duplicate defaults in the routes and `vectorized_matrix_match()` are gone.

### Added
- `scripts/evaluate_accuracy.py` (`make accuracy`): recognition accuracy on LFW using the app's own detection, crop and embedding code.
- `scripts/load_test.py` (`make loadtest`): several simulated kiosks against the Docker Compose stack over HTTP.
- End-to-end tests in `tests/e2e/` (`make e2e`), run against the Compose stack with LFW photos as students. They're excluded from `make test` and CI.
- `docs/ACCURACY.md`, plus load-test results in `docs/BENCHMARKS.md`.

### Removed
- Unused pytest markers (`unit`, `integration`, `crypto`).
- `data/` and `scripts/` are excluded from the Docker build context. A local `data/` folder was being copied into the image.

## [2.5.0] - 2026-10-27

**Upgrading:** `SECRET_KEY` must now be set explicitly. The app won't start without it, or with any key that has been committed to this repository.

### Security
- Required `SECRET_KEY`, with no default. `.env.example` no longer contains a key, and Docker Compose reads it from `.env`.
- Failed logins for unknown emails now run the same scrypt check as real ones. They used to return about 100 times faster, which revealed which emails were admins.
- QR tokens are signed with HMAC-SHA256. itsdangerous had been using its SHA-1 default. Tokens issued before the upgrade stop verifying, but they expire within 35 seconds anyway.
- The classroom QR code is generated on the server with segno. Previously the page loaded it from api.qrserver.com, which received a live check-in URL every 5 seconds.
- Request bodies are limited to 10 MB (`413`).
- Upgraded Flask to 3.1.3, gunicorn to 26.2.0, PyJWT to 2.15.1, python-dotenv to 1.2.4 and Pillow to 12.3.0; pinned PyTorch to 2.14.1.
- CI now fails on ruff or bandit findings.

### Fixed
- The kiosk reloaded and parsed every stored embedding on each detection keyframe (346 ms at 1,000 students). The matrix is now cached per process and rebuilt after an enrollment or every 30 seconds.
- Malformed base64 images caused a `500` from `/capture_face`; they now get a `400`.
- Anonymous API calls to `/export_records` were redirected to the login page instead of getting a JSON `401`.
- Logging wasn't configured, so INFO messages (including Redis status) were dropped.
- `run.py` fell back to Flask's development server on any Gunicorn error. It now does so only when Gunicorn isn't installed.
- "Today" queries use a timestamp range instead of `DATE(timestamp)`, so they can use the index.
- The default `DATABASE_URL` password now matches `.env.example` and Docker Compose.

### Frontend
- Face boxes now follow the video's `object-fit: cover` crop, so they stay on the faces with 16:9 and portrait cameras.
- Fixed navbar wrapping between 769 and 1180 px, the kiosk alert layout on phones and spacing on the enrollment form.
- Login errors are announced to screen readers; small grey text meets WCAG AA contrast.
- `/qr_result` only shows success after a real check-in. Capture retries reset the sample indicators, and "Retry Save" no longer captures again. The purge button is disabled while the request runs.
- Removed hard-coded status labels that didn't reflect what the app does ("SIMD Vector Search: 0.2ms • 30 FPS", "Encrypted Ledger Submission").

### Removed
- Unused files and code: `app/static/qr/qr.png`, `app/static/faces/`, `app/ai/face_utils.py`, `compare_embeddings()`, `MTCNNProxy.__call__`, `request.jwt_user`, `Config.REDIS_URL`, the duplicate `/admin_login` route, the `FLASK_ENV` and `FLASK_DEBUG` settings, and `curl` in the Docker image.
- Moved pytest and pytest-cov from `requirements.txt` to a new `requirements-dev.txt`. Docker Compose uses `postgres:16` instead of the pgvector image, which wasn't used.

### Documentation
- Rewrote the README and the docs in `docs/` for the current code.

## [2.4.3] - 2026-10-23

### Security
- `/register_admin` accepts anonymous signup only while no admin exists; later admins must be created by a signed-in admin. `ALLOW_PUBLIC_ADMIN_SIGNUP=true` reopens signup for demos, and the login page hides the signup link when it's closed.
- Kiosk liveness no longer passes automatically after 3 recognised frames, which let a printed photo be marked present. Blink state is now tracked per face.
- `/verify_student` and `/get_student` require a live QR token or admin credentials, so student names can't be listed by walking through roll numbers.
- Student `year` and `department` are validated, and server values are rendered as text in the admin UI to prevent markup injection.
- Session cookie explicitly set to `HttpOnly` and `SameSite=Lax`. `.env` is excluded from the Docker build context.

### Fixed
- The test suite used the production config, so it tried to connect to PostgreSQL (every API test failed in CI) and its teardown could drop a developer's real database. Tests now use an isolated SQLite config.
- Login lockout ignored `LOCKOUT_THRESHOLD` and `LOCKOUT_DURATION_SECONDS` and was stored in a per-process dict. It now uses the configured values and `SafeCacheStore`, shared through Redis when configured. The Kubernetes ConfigMap had the wrong variable names.
- `SafeCacheStore` never reconnected after a Redis failure; it now retries every 30 seconds.
- `FACE_MATCH_THRESHOLD` and `MTCNN_CONFIDENCE_THRESHOLD` weren't used. Recognition now uses `vectorized_matrix_match` instead of a duplicated inline copy and skips malformed stored vectors.
- `/save_face_data` validates embedding shape; a malformed vector used to break matching for every student.
- QR check-in accepts lower-case roll numbers. `/dashboard_data` counts in SQL. `/records` and `/dashboard_data` return `500` on failure instead of empty data. `/export_records` rejects malformed dates. The `attendance_marked_total` and `active_camera_clients_total` metrics are now updated.
- Added locks around the kiosk tracker registry and model loading.
- The Docker Compose app container now gets `REDIS_URL`.

### Frontend
- Admin navigation, including Sign Out, was hidden below 768 px; it now wraps and scrolls. The kiosk layout stacks on narrow screens.
- "Purge records" no longer reports success when the request fails. Records and the dashboard show error states, the enrollment form submits on Enter, capture is blocked without a camera, and expired sessions redirect to the login page.
- The QR result page distinguishes "already recorded today". Mobile pages allow pinch-zoom, keyboard focus is visible, and missing CSS variables are defined.

### Removed
- Unused `get_embedding` wrapper, `liveness_detection_total` metric and `EAR_BLINK_THRESHOLD` setting, unused imports and a duplicate Google Fonts import.

### Documentation
- Fixed descriptions that didn't match the code and documented known limitations in `docs/SECURITY.md`.

## [2.4.2] - 2026-10-15

### Added
- Documentation: `ARCHITECTURE.md`, design decision records, API reference, benchmarks, operations guide and security notes.
- `pyproject.toml` with pytest, coverage and ruff configuration; `.editorconfig`; `CONTRIBUTING.md`.
- `seed.sql` with the PostgreSQL schema, indexes and demo data.

### Changed
- Type hints across the config, AI, model and extension modules, and docstrings for public functions.
- `.env` is loaded automatically with python-dotenv.

### Fixed
- PostgreSQL password handling for local development on Windows.
- Removed leftover HTML reports and scratch directories.

## [2.4.0] - 2026-09-20

### Added
- Rotating, time-limited signed QR tokens (itsdangerous).
- In-memory fallback in `SafeCacheStore` when Redis is unavailable.
- Prometheus `/metrics` endpoint with request counts and latency histograms.

### Security
- Password policy: length limits plus upper-case, lower-case, digit and symbol requirements.

## [2.0.0] - 2026-07-15

### Added
- Face recognition with 512-d FaceNet embeddings (InceptionResnetV1, VGGFace2 weights).
- MTCNN face detection.
- Matching against all enrolled students with a single matrix-vector product.
- Browser-side blink detection.
