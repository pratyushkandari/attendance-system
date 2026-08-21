# Attendance Platform

A low-latency attendance verification system supporting real-time video facial recognition and dynamic cryptographic QR check-ins. Built with Flask, PyTorch (InceptionResnetV1), OpenCV, PostgreSQL (`pgvector`), Redis, and Prometheus.

---

## Overview & Motivation

Traditional attendance systems suffer from two main bottlenecks:
1. **Biometric Inference Overhead:** Running deep-learning face detection (MTCNN) on every single video frame creates severe CPU/GPU bottlenecks, dropping video frame rates to 3–5 FPS.
2. **Proxy Attendance in QR Systems:** Static QR codes posted in classrooms are easily photographed and shared via messaging apps, allowing students to check in remotely.

This project addresses both problems through:
* **Hybrid Computer Vision Pipeline:** MTCNN runs periodically (1 in 8 frames), while lightweight OpenCV CSRT trackers maintain bounding boxes between detections at 30+ FPS (<10ms CPU time).
* **BLAS Vector Similarity:** Normalized 512-D face embeddings are matched against registered student matrices via single-instruction SIMD dot products (`np.dot(matrix, query_vector)`), executing in ~0.2ms for 10,000 profiles.
* **Anti-Spoofing:** Client-side Eye Aspect Ratio (EAR) contrast tracking requires natural blinking before marking attendance.
* **Time-Bound Dynamic QR Tokens:** Server generates HMAC-SHA256 tokens with a 15-second TTL that auto-rotate every 5 seconds, preventing replay attacks.
* **Hybrid Auth Layer:** Dual-mode authentication accepting either `Authorization: Bearer <jwt_token>` (for REST/mobile clients) or session cookies (for web dashboards).

---

## Architecture & Data Flow

```
[Webcam Stream (30 FPS)]                  [Mobile QR Scan]
         │                                       │
         ├──► Periodic MTCNN (1/8 frames)        ├──► Dynamic Token (15s TTL)
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

## Performance Benchmarks

Profiling measured on standard 4-core x86_64 CPU (without dedicated GPU):

| Pipeline Stage | Naive Approach | Implemented Approach | Speedup |
| :--- | :--- | :--- | :--- |
| **Face Detection per Frame** | MTCNN every frame (~320ms) | Hybrid CSRT Tracking (~8ms) | **40x** |
| **Vector Similarity (10k DB)** | Python `for` loop (~15ms) | NumPy BLAS Dot Product (~0.2ms) | **75x** |
| **Embedding Extraction** | Full image re-crop (~200ms) | Direct tensor crop (~38ms) | **5.2x** |
| **QR Validation Latency** | DB read + state update (~8ms) | Stateless HMAC check (<0.1ms) | **80x** |
| **Video Stream Throughput** | 2–4 FPS (Choppy) | 28–30 FPS (Real-time) | **Smooth** |

---

## REST API Contract

### Authentication

#### `POST /login_admin`
Authenticates administrator credentials and returns a 24-hour JWT token.
```bash
curl -X POST http://localhost:5000/login_admin \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "securepassword"}'
```
Response:
```json
{
  "status": "success",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 86400,
  "user": "admin@example.com"
}
```

### Attendance & Verification

#### `POST /mark_attendance`
Logs attendance record idempotently for the current calendar day.

**Via Dynamic QR Token:**
```bash
curl -X POST http://localhost:5000/mark_attendance \
  -H "Content-Type: application/json" \
  -d '{"roll": "2026CSE001", "method": "QR", "qr_token": "<token>"}'
```

**Via Facial Recognition (Admin authorized):**
```bash
curl -X POST http://localhost:5000/mark_attendance \
  -H "Authorization: Bearer <jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{"roll": "2026CSE001", "method": "Face"}'
```

### Telemetry

#### `GET /metrics`
Prometheus metrics export exposing request counts, connection gauges, and latency histograms (p50, p95, p99).

---

## Local Development & Setup

### Prerequisites
* Python 3.10+
* Docker & Docker Compose (optional, for full multi-container stack)

### 1. Virtual Environment Setup
```bash
# Clone repository
git clone https://github.com/pratyushkandari/attendance-system.git
cd attendance-system

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration
Copy the configuration template:
```bash
cp .env.example .env
```
Default parameters in `.env`:
* `DATABASE_URL`: PostgreSQL connection string (falls back to local SQLite if empty)
* `SECRET_KEY`: Master cryptographic signing secret
* `LOCKOUT_THRESHOLD`: 3 failed attempts (15-min cooldown)

### 3. Run the Application
```bash
python run.py
```
App runs locally at `http://localhost:5000`.

---

## Running with Docker Compose

To launch the full 5-service infrastructure (Flask Application, PostgreSQL with `pgvector`, Redis, Prometheus, and Grafana):

```bash
docker compose up --build
```

### Service Map:
* **Web & API Server:** `http://localhost:5000`
* **Prometheus Metrics:** `http://localhost:9090`
* **Grafana Dashboard:** `http://localhost:3000` (`admin` / `admin`)
* **PostgreSQL:** `localhost:5432`

---

## Test Suite & Validation

The codebase includes 23 unit and integration tests covering authentication, cryptographic tokens, vector mathematics, and API route safety.

```bash
# Run pytest suite
pytest -v

# Run with test coverage report
pytest --cov=app --cov-report=term-missing
```

### Test Coverage Areas:
* `tests/test_auth.py`: JWT token generation, Bearer header authorization, expired/tampered token rejection, and sliding brute-force lockout.
* `tests/test_crypto.py`: Dynamic QR HMAC serialization, signature verification, and instant expiration handling.
* `tests/test_vector.py`: Cosine similarity mathematics, zero-division guardrails, and BLAS matrix dot product matching.
* `tests/test_attendance.py`: Student registration, collision-resistant roll generation, same-day duplicate prevention, and Prometheus `/metrics`.

---

## Continuous Integration

The `.github/workflows/ci.yml` pipeline automatically runs on every push and pull request:
1. Installs system dependencies (`libgl1`, `libglib2.0-0`).
2. Runs `ruff` for code style and formatting checks.
3. Runs `bandit` for static security vulnerability scanning.
4. Executes the full 23-test `pytest` test suite with coverage assertions.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
