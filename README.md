# 🤖 Biometric & Cryptographic Attendance Platform

[![CI/CD Pipeline](https://github.com/your-username/attendance-system/actions/workflows/ci.yml/badge.svg)](https://github.com/your-username/attendance-system/actions)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A high-performance, production-grade automated attendance management platform designed for multi-camera video streaming and mobile check-ins. Built with **Flask**, **PyTorch (InceptionResnetV1 / FaceNet)**, **OpenCV CSRT Tracking**, **PostgreSQL (pgvector)**, **Redis**, and **Prometheus Telemetry**.

---

## 🏛️ System Architecture

```
                    PRODUCTION DISTRIBUTED ARCHITECTURE
 ┌─────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                 │
 │   [Webcam Client]                     [Mobile QR Client]                        │
 │         │                                      │                                │
 │         ▼ (30 FPS Stream)                      ▼ (Dynamic Token)                │
 │   ┌───────────────┐                      ┌───────────────┐                      │
 │   │ CSRT Tracker  │                      │ HMAC Validator│                      │
 │   │ + EAR Liveness│                      │ (15s TTL)     │                      │
 │   └───────┬───────┘                      └───────┬───────┘                      │
 │           │ (1 in 8 Frames)                      │                              │
 │           ▼                                      ▼                              │
 │   ┌──────────────────────────────────────────────────────┐                      │
 │   │              Flask REST Gateway & Metrics            │                      │
 │   │      (Hybrid JWT Bearer + Signed Session Auth)       │                      │
 │   └──────────────────────────┬───────────────────────────┘                      │
 │                              │                                                  │
 │            ┌─────────────────┴─────────────────┐                                │
 │            ▼                                   ▼                                │
 │   ┌─────────────────┐                 ┌─────────────────┐                       │
 │   │ InceptionResnet │                 │ PostgreSQL 16   │                       │
 │   │ BLAS SIMD Match │                 │ (pgvector HNSW) │                       │
 │   │ (0.2ms / 10k)   │                 └─────────────────┘                       │
 │   └─────────────────┘                          ▲                                │
 │            │                                   │                                │
 │            ▼                                   ▼                                │
 │   ┌─────────────────┐                 ┌─────────────────┐                       │
 │   │ Redis 7 Cache   │                 │ Prometheus /    │                       │
 │   │ Distributed Lock│                 │ Grafana Telemetry                       │
 │   └─────────────────┘                 └─────────────────┘                       │
 │                                                                                 │
 └─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Key Engineering Highlights (MAANG SDE-1 Focus)

1. **Hardware-Accelerated BLAS Vector Matching ($\mathbf{0.2\text{ms}}$ for 10,000 Vectors):**
   * Unit-normalized centroid embeddings ($\text{Mean} + L_2 \text{ norm}$) matched via single SIMD matrix dot products (`np.dot(matrix, query_vector)`).
2. **Hybrid Detection + CSRT Tracking (80% CPU Reduction):**
   * Heavy MTCNN face detection runs once every 8 frames; lightweight OpenCV CSRT trackers maintain bounding boxes in $<10\text{ms}$ on CPU, achieving smooth 30 FPS tracking.
3. **Active Biometric Anti-Spoofing (Liveness Detection):**
   * Real-time **Eye Aspect Ratio (EAR)** contrast variance analysis enforces live natural blinking before attendance is logged, blocking photo and screen replay attacks.
4. **Cryptographically Signed Dynamic QR (Zero Replay Attack):**
   * HMAC-SHA256 time-bound tokens (`URLSafeTimedSerializer`) valid for 15 seconds, refreshed every 5 seconds with an animated countdown timer.
5. **Hybrid Stateless JWT + Session Authentication:**
   * Universal access control supporting both `Authorization: Bearer <jwt_token>` (for mobile/API clients) and secure `HttpOnly` browser session cookies.
6. **Multi-Camera Concurrency & State Isolation:**
   * Client-scoped tracker dictionaries (`tracking_sessions[client_id]`) with TTL-based memory eviction prevent thread race conditions across multiple classroom streams.

---

## 📡 REST API Reference

| Method | Endpoint | Auth Required | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/login_admin` | Public | Authenticates admin, returns 24h JWT access token and session cookie. |
| `POST` | `/register_admin` | Bootstrap / Admin | Creates initial admin or registers additional admins with authorization. |
| `POST` | `/register` | Bearer / Session | Registers a new student and generates a collision-free roll number. |
| `POST` | `/capture_face` | Bearer / Session | Extracts 512-D embedding from a single webcam frame. |
| `POST` | `/save_face_data` | Bearer / Session | Saves 5-shot normalized centroid face profile to database. |
| `POST` | `/recognize_with_box` | Bearer / Session | Performs multi-face tracking and BLAS vector similarity search. |
| `GET` | `/generate_qr_token` | Bearer / Session | Generates a 15-second HMAC cryptographic token for dynamic QR sessions. |
| `POST` | `/verify_qr_token` | Public | Validates dynamic QR token signature and expiration. |
| `POST` | `/mark_attendance` | Verified Method | Idempotently logs attendance for today via `Face` (Admin) or `QR` (Token). |
| `GET` | `/records` | Bearer / Session | Fetches grouped chronological attendance logs. |
| `POST` | `/clear_records` | Bearer / Session | Clears attendance logs (guarded by confirmation). |
| `GET` | `/metrics` | Public | Prometheus scrape endpoint exporting latency histograms and counters. |

---

## 🐳 Quickstart: Run with Docker Compose

Ensure [Docker Desktop](https://www.docker.com/) is installed and running, then execute:

```bash
# 1. Clone repository
git clone https://github.com/<your-username>/attendance-system.git
cd attendance-system

# 2. Build and launch all 5 microservices
docker compose up --build
```

### 🌐 Service Endpoints:
* **Web & Biometric Application:** [http://localhost:5000](http://localhost:5000)
* **Prometheus Metrics Engine:** [http://localhost:9090](http://localhost:9090)
* **Grafana Telemetry Dashboard:** [http://localhost:3000](http://localhost:3000) (User: `admin` / Password: `admin`)
* **PostgreSQL Database (`pgvector`):** `localhost:5432`

---

## 🧪 Automated Testing Suite

Run the 23-test automated unit and integration suite:

```bash
# Activate virtual environment
.\venv\Scripts\activate

# Run pytest with test coverage
pytest -v --cov=app --cov-report=term-missing
```

### Test Suite Summary:
* `tests/test_auth.py`: JWT token generation, Bearer header authorization, expired/tampered token rejection, and 15-min account lockout.
* `tests/test_crypto.py`: Dynamic QR HMAC serialization, signature verification, and instant expiration handling.
* `tests/test_vector.py`: Cosine similarity mathematics, zero-division guardrails, and vectorized BLAS matrix matching.
* `tests/test_attendance.py`: Student registration, collision-resistant roll generation, same-day duplicate prevention, and Prometheus `/metrics`.

---

## 📊 Observability & Telemetry

The system instruments **Prometheus** metrics at `/metrics`:
* `http_request_duration_seconds`: Histogram with p50, p95, and p99 request latency distribution.
* `http_requests_total`: Counter tracking request throughput by status code.
* `attendance_marked_total`: Counter tracking check-in methods (`Face` vs `QR`).
* `active_camera_clients_total`: Gauge tracking concurrent webcam streaming sessions.

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
