# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
