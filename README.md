# Enterprise Biometric & Cryptographic Attendance Verification Platform

[![CI Pipeline](https://github.com/pratyushkandari/attendance-system/actions/workflows/ci.yml/badge.svg)](https://github.com/pratyushkandari/attendance-system/actions)
[![Live Demo](https://img.shields.io/badge/Live_Demo-Render_Cloud-success?style=flat-square&logo=render)](https://attendance-system-60nr.onrender.com)
[![Python](https://img.shields.io/badge/Python-3.10-blue?style=flat-square&logo=python)](https://python.org)
[![PyTorch](https://img.shields.io/badge/PyTorch-CPU_Optimized-EE4C2C?style=flat-square&logo=pytorch)](https://pytorch.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16_pgvector-336791?style=flat-square&logo=postgresql)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Multi_Stage-2496ED?style=flat-square&logo=docker)](https://docker.com)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-HPA_Manifests-326CE5?style=flat-square&logo=kubernetes)](https://kubernetes.io)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

A low-latency attendance verification system supporting 30 FPS facial recognition ($<45\text{ms}$ per-frame CPU budget) and 5-second rotating cryptographic dynamic QR check-ins. Built on Flask, PyTorch (`InceptionResnetV1`), OpenCV (CSRT object tracking), PostgreSQL (`pgvector`), Redis distributed caching, and Prometheus telemetry.

🔗 **Live Deployment:** [https://attendance-system-60nr.onrender.com](https://attendance-system-60nr.onrender.com)

---

## Technical Documentation Suite

For detailed technical specifications, architecture records, and operations manuals, refer to the documentation suite in `docs/`:

* 🏛️ **[System Architecture Document (ARCHITECTURE.md)](ARCHITECTURE.md):** End-to-end data flow, inference pipelines, and memory models.
* 📋 **[Architecture Decision Records (ADRs)](docs/ARCHITECTURE_DECISION_RECORDS.md):** 5 formal ADRs documenting trade-offs (MTCNN vs CSRT, BLAS SIMD vs Cosine loops, JWT vs Sessions).
* 📡 **[REST API Specification](docs/API_SPECIFICATION.md):** Complete contract with request/response schemas, error codes, and headers.
* 📊 **[Performance Benchmarks & Profiling](docs/BENCHMARKS.md):** Flamegraph analysis, $P_{50}/P_{95}/P_{99}$ latency budgets, and $N=50,000$ vector scalability curves.
* 🛡️ **[Security Architecture & Threat Model](docs/SECURITY.md):** STRIDE analysis, NIST 800-63B password policy, and ISO/IEC 30107-3 liveness standards.
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
* **Our Solution:** **Time-bound dynamic HMAC-SHA256 tokens** generated on the server with a 15-second TTL that auto-rotate every 5 seconds. Forwarded photos expire before remote recipients can receive and submit them.

### 4. Presentation Attacks (Photo & Video Spoofing)
* **The Problem:** Holding a printed photograph or smartphone screen displaying an enrolled student's face to the kiosk camera.
* **Our Solution:** Client-side **Eye Aspect Ratio (EAR) contrast gradient tracking**. The system requires natural eyelid blinking (variance dip and recovery within 40–1200ms) before permitting an attendance commit.

---

## Architectural Data Flow

```
[Webcam Stream (30 FPS)]                  [Mobile QR Scan]
         │                                       │
         ├──► Periodic MTCNN (1/4 frames)        ├──► Dynamic Token (15s TTL)
         ├──► Inter-frame CSRT Tracking          └──► HMAC Signature Check
         ├──► EAR Blink Liveness Verification            │
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
    │  (BLAS SIMD Matrix Dot) │             │ (pgvector + Indexing)   │
    └─────────────────────────┘             └─────────────────────────┘
                 │                                       │
                 ▼                                       ▼
    ┌─────────────────────────┐             ┌─────────────────────────┐
    │     Redis 7 Cache       │             │   Prometheus /metrics   │
    │   (Distributed Lock)    │             │   (Latency Histograms)  │
    └─────────────────────────┘             └─────────────────────────┘
```

---

## Performance Benchmarks Summary

Measured on standard 4-Core x86_64 CPU (without dedicated GPU):

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

# 3. Dynamic QR Attendance Check-In
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
* PostgreSQL 16 (or SQLite development fallback)
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
* `DATABASE_URL`: PostgreSQL connection string (`postgresql://postgres:postgres@localhost:5432/attendence_db`).
* `SECRET_KEY`: Master cryptographic signing secret.
* `LOCKOUT_THRESHOLD`: 3 failed attempts (15-min cooldown).

### 3. Database Initialization & Seed
```bash
# Run schema and seed script via PostgreSQL CLI
psql -U postgres -d attendence_db -f seed.sql
```
*Default Operator Account:* `admin@institution.edu` / `AdminSecure@2026!`

### 4. Run Application
```bash
python run.py
```
* Server binds to `http://localhost:5000`.

---

## Docker Compose Deployment

To spin up the complete 5-container infrastructure (Flask App, PostgreSQL with `pgvector`, Redis 7, Prometheus, and Grafana):

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

The codebase includes **28 automated unit and integration tests** with continuous coverage assertions:

```bash
# Run test suite
python -m pytest -v

# Run with terminal coverage report
python -m pytest --cov=app --cov-report=term-missing
```

### Test Coverage Highlights:
* `tests/test_auth.py`: JWT token generation, Bearer header authorization, expired/tampered token rejection, NIST 800-63B password complexity, salted cryptographic password hashing, RFC 5322 email validation, and sliding brute-force lockout.
* `tests/test_crypto.py`: Dynamic QR HMAC serialization, signature verification, instant expiration handling, and SafeCacheStore Redis/in-memory TTL cache.
* `tests/test_vector.py`: Cosine similarity mathematics, zero-division guardrails, and BLAS matrix dot product matching.
* `tests/test_attendance.py`: Student registration, collision-resistant roll generation, same-day duplicate prevention, CSV streaming export, and Prometheus `/metrics`.

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
3. Runs `ruff` for code style and PEP 8 compliance.
4. Executes `bandit` for static application security testing (SAST).
5. Executes the full **28-test automated pytest suite** with coverage reporting.

---

## License

This project is open-source under the [MIT License](LICENSE).
