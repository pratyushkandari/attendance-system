# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.4.3] - 2026-10-23

### Security
- `/register_admin` again accepts anonymous signup only while no administrator exists; later admins must be created by an authenticated admin. `ALLOW_PUBLIC_ADMIN_SIGNUP=true` reopens public signup for demo deployments, and the login page hides the signup link when it is closed.
- Kiosk liveness no longer auto-passes after 3 recognised frames (a printed photo could be marked present). Blink state is now tracked per recognised face.
- `/verify_student` and `/get_student` now require the live QR token (or admin credentials), closing unauthenticated enumeration of student names by sequential roll number.
- Student `year`/`department` are validated (4-digit year, 2–10 letter department code), and server values are rendered as text in the admin UI, preventing markup injection through roll numbers or error messages.
- Session cookie explicitly `HttpOnly` + `SameSite=Lax`; startup warning when the default development `SECRET_KEY` is in use; `.env` excluded from Docker build context.

### Fixed
- Test suite built the app with the production config, so it tried to connect to PostgreSQL (all API tests errored in CI) and its teardown could `drop_all()` a developer's real database. Tests now use an isolated SQLite config.
- Login lockout ignored `LOCKOUT_THRESHOLD`/`LOCKOUT_DURATION_SECONDS` and lived in a per-process dict; it now uses the configured values and `SafeCacheStore` (shared via Redis when configured). The Kubernetes ConfigMap used the wrong variable names.
- `SafeCacheStore` never reconnected after a Redis failure; it now re-probes every 30 seconds.
- `FACE_MATCH_THRESHOLD` and `MTCNN_CONFIDENCE_THRESHOLD` were not used; recognition and enrollment now read them. Recognition reuses `vectorized_matrix_match` instead of a duplicated inline copy and skips malformed stored vectors.
- `/save_face_data` validates embedding shape (malformed vectors previously broke matching for every student).
- QR check-in accepts lower-case roll numbers; `/dashboard_data` counts today's attendance in SQL; `/records` and `/dashboard_data` return HTTP 500 on failure instead of empty "success" data; `/export_records` rejects malformed dates; Prometheus `attendance_marked_total` and `active_camera_clients_total` are now updated.
- Thread-safety: lock around the kiosk tracker registry and lazy model initialisation.
- Docker Compose app container now receives `REDIS_URL`.

### Frontend
- Admin navigation (including Sign Out) was hidden below 768 px; it now wraps and scrolls horizontally. The kiosk layout stacks on narrow screens.
- "Purge records" no longer reports success when the request fails; records/dashboard show error states; enrollment form submits with Enter; capture is blocked when no camera is available; expired sessions redirect to login.
- QR result page distinguishes "already recorded today"; mobile pages allow pinch-zoom; visible keyboard focus styles; undefined CSS variables defined.

### Removed
- Unused `get_embedding` wrapper, unused `liveness_detection_total` metric, unused `EAR_BLINK_THRESHOLD` setting, unused imports, and the duplicate Google Fonts `@import`.

### Documentation
- Corrected claims that did not match the code (pgvector usage, Redis locks, database unique constraint, QR TTL, "EAR" liveness, ISO/NIST compliance wording) and documented known limitations in `docs/SECURITY.md`.

---

## [2.4.2] - 2026-10-15

### Added
- **Formal Engineering Documentation Suite**:
  - `ARCHITECTURE.md`: RFC-042 System Architecture Document detailing dual-channel authentication topology, state machines, and STRIDE threat models.
  - `docs/ARCHITECTURE_DECISION_RECORDS.md`: 5 formal Architectural Decision Records (ADRs) covering MTCNN+CSRT tracking, BLAS SIMD matching, dual-channel failover, HMAC-SHA256 tokens, and resilient cache fallbacks.
  - `docs/API_SPECIFICATION.md`: OpenAPI 3.1.0 REST contract specification for all authentication, student registration, and attendance endpoints.
  - `docs/BENCHMARKS.md`: Comprehensive profiling benchmarks covering p50/p95/p99 latency budgets, memory footprints, and vector scalability.
  - `docs/OPERATIONS_RUNBOOK.md`: Production SRE operations manual with SLO definitions, Prometheus alert rules, and incident remediation runbooks.
  - `docs/SECURITY.md`: Security architecture report detailing threat modeling, ISO/IEC 30107-3 compliance, and cryptographic boundaries.
- **Repository Tooling**:
  - `pyproject.toml`: Modern packaging and linter configuration for Pytest, Coverage, and Ruff.
  - `.editorconfig`: Cross-IDE indentation and whitespace enforcement.
  - `CONTRIBUTING.md`: Development setup, Conventional Commit standards, and testing policies.
- **Database Tooling**:
  - `seed.sql`: Idempotent PostgreSQL schema migration with performance B-Tree indices and default bootstrap records.

### Changed
- **Type Annotations**: Implemented comprehensive PEP 484 type hints across `app/config.py`, `app/ai/face_utils.py`, `app/ai/comparator.py`, `app/ai/facenet_model.py`, `app/models/`, and `app/extensions.py`.
- **Codebase Documentation**: Upgraded all internal docstrings to Google/Sphinx format including algorithmic time/space complexities ($O(N \cdot D)$ BLAS SGEMV).
- **Environment Handling**: Added automatic `.env` loading in `app/config.py` via `python-dotenv` with fallback defaults.

### Fixed
- Fixed PostgreSQL connection string password resolution for local Windows development environments.
- Cleaned up dangling HTML report artifacts and scratch directories.

---

## [2.4.0] - 2026-09-20

### Added
- Dynamic HMAC-SHA256 encrypted QR token generation with 30-second TTL.
- In-memory fallback support in `SafeCacheStore` when Redis service is offline.
- Prometheus observability `/metrics` endpoint with latency histograms and request counters.

### Security
- NIST 800-63B password complexity enforcement and constant-time token comparison via `hmac.compare_digest`.

---

## [2.0.0] - 2026-07-15

### Added
- FaceNet InceptionResnetV1 (VGGFace2) 512-D facial feature embedding extraction.
- MTCNN face detection with 3-stage cascaded neural networks.
- Vectorized SIMD matrix dot-product candidate matching.
- Real-time client-side EAR (Eye Aspect Ratio) blink liveness detection.
