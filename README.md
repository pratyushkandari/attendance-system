# Enterprise Biometric & Cryptographic Attendance Verification Platform

[![CI Pipeline](https://github.com/pratyushkandari/attendance-system/actions/workflows/ci.yml/badge.svg)](https://github.com/pratyushkandari/attendance-system/actions)
[![Live Demo](https://img.shields.io/badge/Live_Demo-Render_Cloud-success?style=flat-square&logo=render)](https://attendance-system-60nr.onrender.com)
[![Python](https://img.shields.io/badge/Python-3.10-blue?style=flat-square&logo=python)](https://python.org)
[![PyTorch](https://img.shields.io/badge/PyTorch-CPU_Optimized-EE4C2C?style=flat-square&logo=pytorch)](https://pytorch.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker)](https://docker.com)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-HPA_Manifests-326CE5?style=flat-square&logo=kubernetes)](https://kubernetes.io)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

A low-latency attendance verification system supporting 30 FPS facial recognition ($<45\text{ms}$ per-frame CPU budget) and 5-second rotating cryptographic dynamic QR check-ins. Built on Flask, PyTorch (`InceptionResnetV1`), OpenCV (CSRT object tracking), PostgreSQL, Redis (optional, shared login-lockout counters), and Prometheus telemetry.

🔗 **Live Deployment:** [https://attendance-system-60nr.onrender.com](https://attendance-system-60nr.onrender.com)

---

## Technical Documentation Suite

For detailed technical specifications, architecture records, and operations manuals, refer to the documentation suite in `docs/`:

* 🏛️ **[System Architecture Document (ARCHITECTURE.md)](ARCHITECTURE.md):** End-to-end data flow, inference pipelines, and memory models.
* 📋 **[Architecture Decision Records (ADRs)](docs/ARCHITECTURE_DECISION_RECORDS.md):** 5 formal ADRs documenting trade-offs (MTCNN vs CSRT, BLAS SIMD vs Cosine loops, JWT vs Sessions).
* 📡 **[REST API Specification](docs/API_SPECIFICATION.md):** Complete contract with request/response schemas, error codes, and headers.
* 📊 **[Performance Benchmarks & Profiling](docs/BENCHMARKS.md):** Flamegraph analysis, $P_{50}/P_{95}/P_{99}$ latency budgets, and $N=50,000$ vector scalability curves.
* 🛡️ **[Security Architecture & Threat Model](docs/SECURITY.md):** STRIDE analysis, password policy, liveness design, and known limitations.
* 🚨 **[Operations & Incident Runbook](docs/OPERATIONS_RUNBOOK.md):** SLOs, Prometheus alerting rules, and disaster recovery playbooks.

---

## Engineering Overview & Bottlenecks Solved

### 1. The Deep Learning CPU Inference Bottleneck
* **The Problem:** Running deep convolutional face detection (MTCNN) on every single video frame takes ~320ms on commodity CPU nodes, collapsing frame rates to 2–4 FPS.
* **Our Solution:** A **hybrid 1:4 periodic detection schedule**. MTCNN runs on keyframes, while lightweight OpenCV CSRT trackers maintain bounding boxes between keyframes at ~8ms per frame, delivering a fluid 28–30 FPS terminal experience on standard CPU servers.

### 2. The $O(N)$ Vector Search Bottleneck
* **The Problem:** Iterating through stored facial embeddings with Python loops and calculating pairwise cosine distances scales linearly ($O(N)$), adding unacceptable latency for large student cohorts.
* **Our Solution:** Normalized 512-D unit vectors stacked into a contiguous 2D float32 matrix $\mathbf{E} \in \mathbb{R}^{N \times 512}$. Similarity matching executes via single-instruction **BLAS matrix-vector dot products (`np.dot(matrix, query)`)**, running in **0.19ms for 10,000 students**.

### 3. Proxy Attendance in QR Check-in Systems
* **The Problem:** Static QR codes posted in classrooms are photographed and forwarded to absent peers via messaging apps, allowing fraudulent remote check-ins.
* **Our Solution:** **Time-bound dynamic HMAC-SHA256 tokens** that the classroom screen rotates every 5 seconds. The server accepts a scanned token for at most 30 s (token check) / 35 s (final submission), so a forwarded photo is only useful within that short window. Student lookups on the phone also require the live token, so roll numbers cannot be used to scrape student names.

### 4. Presentation Attacks (Photo & Video Spoofing)
* **The Problem:** Holding a printed photograph or smartphone screen displaying an enrolled student's face to the kiosk camera.
* **Our Solution:** Client-side **eye-region contrast-variance blink detection**. Each recognised face must show its own natural blink (variance dip and recovery within 40–1200 ms) before the kiosk commits attendance; there is no time-based bypass, and one person's blink never verifies another face. The check runs in the kiosk browser, and the server accepts `Face` check-ins only from an authenticated admin/kiosk session.

---

## Architectural Data Flow

```
[Webcam Stream (30 FPS)]                  [Mobile QR Scan]
         │                                       │
         ├──► Periodic MTCNN (1/4 frames)        ├──► Dynamic Token (rotates every 5s)
         ├──► Inter-frame CSRT Tracking          └──► HMAC Signature Check
         ├──► Per-face Blink Liveness (browser)          │
         └──► Direct Tensor Crop to FaceNet              │
                     │                                   │
                     ▼                                   ▼
          ┌─────────────────────────────────────────────────────┐
          │               Flask Application Gateway             │
          │         (JWT Bearer / Session Cookie Auth)          │
          └──────────────────────────┬──────────────────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
    ┌─────────────────────────┐             ┌─────────────────────────┐
    │   Biometric Vector DB   │             │   PostgreSQL Database   │
    │  (BLAS SIMD Matrix Dot) │             │  (B-Tree Indexed)       │
    └─────────────────────────┘             └─────────────────────────┘
                 │                                       │
                 ▼                                       ▼
    ┌─────────────────────────┐             ┌─────────────────────────┐
    │     Redis 7 Cache       │             │   Prometheus /metrics   │
    │  (Lockout Counters)     │             │   (Latency Histograms)  │
    └─────────────────────────┘             └─────────────────────────┘
```

---

## Performance Benchmarks Summary

Reported for a standard 4-Core x86_64 CPU (without dedicated GPU). These figures are not produced by a benchmark script in this repository; see [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

| Pipeline Stage | Naive Approach | Implemented Approach | Speedup | Latency Impact |
| :--- | :--- | :--- | :---: | :---: |
| **Face Detection per Frame** | MTCNN every frame (~320ms) | Hybrid CSRT Tracking (~8ms) | **40.0x** | Enables 30 FPS stream |
| **Vector Similarity ($N=10\text{k}$)** | Python `for` loops (~15ms) | NumPy BLAS Dot Product (~0.2ms) | **75.0x** | Sub-millisecond matching |
| **Embedding Extraction** | Full image re-crop (~200ms) | Direct tensor crop (~38ms) | **5.2x** | Low CPU footprint |
| **QR Validation Latency** | DB read + lock (~8ms) | Stateless HMAC check (<0.1ms) | **80.0x** | High throughput |
| **Video Stream Throughput** | 2–4 FPS (Choppy) | 28–30 FPS (Fluid) | **Smooth** | Real-time terminal |

---

## Core API Contract Summary

Complete documentation with request payloads and schemas is in [docs/API_SPECIFICATION.md](docs/API_SPECIFICATION.md).

```bash
# 1. Administrator Authentication (Returns 24h Bearer JWT)
curl -X POST http://localhost:5000/login_admin \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@institution.edu", "password": "AdminSecure@2026!"}'

# 2. Student Enrollment
curl -X POST http://localhost:5000/register \
  -H "Authorization: Bearer <jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{"first_name": "Alexander", "last_name": "Wright", "department": "CSE", "year": "2026", "email": "a.wright@institution.edu"}'

# 3. Dynamic QR Attendance Check-In (roll lookup is case-insensitive)
curl -X POST http://localhost:5000/mark_attendance \
  -H "Content-Type: application/json" \
  -d '{"roll": "2026CSE001", "method": "QR", "qr_token": "<token>"}'

# 4. Stream Exported Attendance Ledger (CSV)
curl -X GET "http://localhost:5000/export_records?dept=CSE" \
  -H "Authorization: Bearer <jwt_token>" \
  -o attendance_report.csv

# 5. Prometheus Metrics Telemetry
curl -X GET http://localhost:5000/metrics
```

---

## Local Development & Setup

### Prerequisites
* Python 3.10+
* PostgreSQL 16 (or SQLite for local development, e.g. `DATABASE_URL=sqlite:///attendance.db`)
* Redis (optional; automatically falls back to in-memory TTL cache)

### 1. Environment Setup
```bash
# Clone repository
git clone https://github.com/pratyushkandari/attendance-system.git
cd attendance-system

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install CPU PyTorch build & dependencies
pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

### 2. Environment Configuration
```bash
cp .env.example .env
```
Default parameters in `.env`:
* `DATABASE_URL`: PostgreSQL connection string (`postgresql://postgres:postgres@localhost:5432/attendence_db`). The database must be reachable at startup because the app creates missing tables.
* `SECRET_KEY`: Master cryptographic signing secret. The app logs a warning if the built-in development default is used.
* `REDIS_URL`: Optional. When set, failed-login counters are shared across workers/pods; otherwise an in-memory store is used.
* `LOCKOUT_THRESHOLD` / `LOCKOUT_DURATION_SECONDS`: 3 failed attempts → 15-minute lockout.
* `ALLOW_PUBLIC_ADMIN_SIGNUP`: `false` by default. Only the **first** administrator can sign up from the login page; after that, new admins must be created by a logged-in admin (`POST /register_admin` with a session or Bearer JWT). Set to `true` only for a public demo where visitors should be able to create admin accounts.
* `FACE_MATCH_THRESHOLD` (0.70) / `MTCNN_CONFIDENCE_THRESHOLD` (0.90): recognition and face-detection thresholds.

### 3. Database Initialization & Seed
```bash
# Run schema and seed script via PostgreSQL CLI
psql -U postgres -d attendence_db -f seed.sql
```
*Default Operator Account (created by `seed.sql` only):* `admin@institution.edu` / `AdminSecure@2026!`. Change this password in any shared deployment. Without the seed, create the first admin from the login page ("Initialize Admin Profile").

### 4. Run Application
```bash
python run.py
```
* Server binds to `http://localhost:5000`.

---

## Docker Compose Deployment

To spin up the complete 5-container infrastructure (Flask App, PostgreSQL 16, Redis 7, Prometheus, and Grafana):

```bash
docker compose up -d --build
```

### Service Map:
* **Web Gateway & API:** `http://localhost:5000`
* **Prometheus Metrics:** `http://localhost:9090`
* **Grafana Dashboards:** `http://localhost:3000` (Default credentials: `admin` / `admin`)
* **PostgreSQL:** `localhost:5432`
* **Redis:** `localhost:6379`

---

## Automated Test Suite

The codebase includes **53 automated unit and integration tests**. They run against an in-memory SQLite database and the in-process cache, so no PostgreSQL or Redis instance is needed:

```bash
# Run test suite
python -m pytest -v

# Run with terminal coverage report
python -m pytest --cov=app --cov-report=term-missing
```

### Test Coverage Highlights:
* `tests/test_auth.py`: JWT token generation, Bearer header authorization, expired/tampered token rejection, password policy, salted password hashing, email validation, configurable brute-force lockout, first-admin-only registration, and session cookie flags.
* `tests/test_crypto.py`: Dynamic QR HMAC serialization, signature verification, expiration handling, and the SafeCacheStore TTL cache including Redis failover and reconnection.
* `tests/test_vector.py`: Cosine similarity mathematics, zero-division guardrails, and BLAS matrix dot product matching.
* `tests/test_attendance.py`: Student registration and input validation, roll generation, QR and Face check-in rules, same-day duplicate prevention, QR-token-gated student lookups, embedding validation, dashboard counts, CSV export, recognition low-light/no-face paths, and Prometheus `/metrics`.

The MTCNN/FaceNet inference path itself (which downloads VGGFace2 weights on first use) is not exercised by the unit tests; verify it end to end with a webcam or a recorded frame.

---

## Kubernetes Production Deployment

Enterprise declarative manifests are provided in `k8s/`:

```bash
# Apply ConfigMap, Deployment, Service, and HorizontalPodAutoscaler
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/hpa.yaml

# Verify pod status and auto-scaling metrics
kubectl get pods -l app=attendance-system
kubectl get hpa attendance-hpa
```

---

## Continuous Integration & Quality Gate

The [.github/workflows/ci.yml](.github/workflows/ci.yml) workflow triggers on every push and pull request:
1. Installs OpenCV system dependencies (`libgl1`, `libglib2.0-0`).
2. Installs lightweight CPU-only PyTorch and project dependencies.
3. Runs `ruff` for code style and PEP 8 compliance (report only, `--exit-zero`).
4. Executes `bandit` for static application security testing (report only, `--exit-zero`).
5. Executes the full pytest suite with coverage reporting (this step gates the build).

---

## License

This project is open-source under the [MIT License](LICENSE).
