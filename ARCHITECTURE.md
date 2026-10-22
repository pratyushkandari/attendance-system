# System Architecture & Technical Design Document (RFC-042)

**System:** VisionAttend - Enterprise Biometric & Dual-Channel Cryptographic Attendance Platform  
**Author:** Pratyush Kandari  
**Status:** Production Ready  
**Last Revised:** Q4 2026  

---

## 1. Executive Summary & Problem Space

Institutional attendance recording at scale suffers from two distinct systemic vulnerabilities:
1. **Inference Latency in Computer Vision Pipelines:** Performing cascaded deep-learning face detection (MTCNN) on every raw video frame consumes ~320ms of CPU execution time. In cloud environments without dedicated GPU instances, video throughput drops below 4 FPS, causing severe UI lag and bounding-box jitter.
2. **Proxy Attendance in QR-Based Tracking:** Static QR codes posted in lecture halls are photographed and shared via messaging apps, enabling students to check in remotely.

This platform resolves both bottlenecks through:
* **Hybrid 1:4 Periodic Detection + CSRT Tracking:** MTCNN keyframe detection combined with sub-8ms OpenCV CSRT inter-frame correlation tracking maintains a continuous 30 FPS stream on commodity CPUs.
* **BLAS SIMD Vector Similarity Search:** Normalized 512-D face embeddings are matched against registered student matrices via single-instruction SIMD dot products (`np.dot(matrix, query_vector)`), executing in ~0.2ms for 10,000 profiles.
* **Presentation Attack Detection (PAD):** Client-side eye-region contrast-variance tracking requires each recognised face to blink before it is marked, defeating static printed-photo attacks (video replays of a blinking face are not detected; see §3.2).
* **Dynamic Time-Bound QR Tokens:** Server-generated HMAC-SHA256 signed tokens rotate every 5 seconds and are accepted for at most 30–35 seconds, shrinking the window in which a forwarded photograph is usable.

---

## 2. High-Level Architecture & End-to-End Topology

```
                              HIGH-LEVEL DATA FLOW
  ┌─────────────────────────────────────────────────────────────────────────────────┐
  │                                                                                 │
  │  [Webcam Client (30 FPS)]            [Mobile QR Client / REST API Clients]      │
  │        │                                      │                                 │
  │        ▼                                      ▼ (Bearer JWT / Dynamic QR)       │
  │  ┌───────────────┐                      ┌───────────────┐                       │
  │  │ CSRT Tracker  │                      │ HMAC Validator│                       │
  │  │ + Blink Check │                      │ + JWT Decoder │                       │
  │  └───────┬───────┘                      └───────┬───────┘                       │
  │          │ (1 in 4 Keyframes)                   │                               │
  │          ▼                                      ▼                               │
  │  ┌──────────────────────────────────────────────────────┐                       │
  │  │              Flask REST Gateway & Metrics            │                       │
  │  │      (Hybrid JWT Bearer + Signed Session Auth)       │                       │
  │  └──────────────────────────┬───────────────────────────┘                       │
  │                             │                                                   │
  │           ┌─────────────────┴─────────────────┐                                 │
  │           ▼                                   ▼                                 │
  │  ┌─────────────────┐                 ┌─────────────────┐                        │
  │  │ InceptionResnet │                 │ PostgreSQL 16   │                        │
  │  │ BLAS SIMD Match │                 │ (B-Tree indexes)│                        │
  │  │ (0.19ms / 10k)  │                 └─────────────────┘                        │
  │  └─────────────────┘                          ▲                                 │
  │           │                                   │                                 │
  │           ▼                                   ▼                                 │
  │  ┌─────────────────┐                 ┌─────────────────┐                        │
  │  │ Redis 7 Cache   │                 │ Prometheus /    │                        │
  │  │ Lockout Counters│                 │ Grafana Telemetry                        │
  │  └─────────────────┘                 └─────────────────┘                        │
  │                                                                                 │
  └─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Subsystem Specifications

### 3.1 Biometric Inference Pipeline

```
Raw Camera Frame (JPEG 640x480)
      │
      ▼
[cv2.imdecode] ──► Luminance Check (mean < 35 triggers low-light alert)
      │
      ├── If (frame_count % 4 == 0) OR (trackers is empty):
      │       │
      │       ▼
      │   [MTCNN Cascaded CNN] (P-Net ➔ R-Net ➔ O-Net, conf >= MTCNN_CONFIDENCE_THRESHOLD, default 0.90)
      │       │
      │       ▼
      │   Crop Face Region [y:y+h, x:x+w]
      │       │
      │       ▼
      │   Resize to (160, 160) & Normalize [-1.0, 1.0]
      │       │
      │       ▼
      │   [InceptionResnetV1 Forward Pass] (Zero-Grad, CPU thread pool)
      │       │
      │       ▼
      │   L2-Unit Normalization (||v|| = 1.0)
      │       │
      │       ▼
      │   [BLAS Matrix Dot Product Search] (scores = matrix · query)
      │       │
      │       ▼
      │   Initialize new cv2.TrackerCSRT instances
      │
      └── Else (inter-frame tracking):
              │
              ▼
          Update existing CSRT trackers (~8ms CPU execution)
              │
              ▼
          Return smoothed bounding boxes + identity labels
```

#### Vector Search Formulation:
Given an enrolled cohort matrix $\mathbf{E} \in \mathbb{R}^{N \times 512}$ where each row $\|\mathbf{e}_i\|_2 = 1.0$, and a normalized query vector $\mathbf{q} \in \mathbb{R}^{512}$ with $\|\mathbf{q}\|_2 = 1.0$:
$$\text{Sim}(\mathbf{E}, \mathbf{q}) = \mathbf{E} \cdot \mathbf{q} = \begin{bmatrix} \mathbf{e}_1 \cdot \mathbf{q} \\ \mathbf{e}_2 \cdot \mathbf{q} \\ \vdots \\ \mathbf{e}_N \cdot \mathbf{q} \end{bmatrix}$$
$$\text{BestMatchIndex} = \arg\max_{i} (\text{Sim}(\mathbf{E}, \mathbf{q})_i), \quad \text{Confidence} = \max_i (\text{Sim}(\mathbf{E}, \mathbf{q})_i)$$
Match is accepted if and only if $\text{Confidence} \ge$ `FACE_MATCH_THRESHOLD` (default $0.70$). Stored vectors that are not 512-D are skipped when the matrix is built, and `/save_face_data` rejects malformed samples.

---

### 3.2 Anti-Spoofing & Liveness Detection (PAD)

To prevent presentation attacks using 2D printed photographs, the browser viewfinder tracks grey-level contrast variance over the ocular band of every recognised face (state is kept per roll number):

$$\text{Eye Band Region}: \quad \mathcal{R}_{\text{eye}} = [x + 0.12w, \; y + 0.18h, \; 0.76w, \; 0.28h]$$

$$\text{Variance}: \quad \sigma^2 = \frac{1}{|\mathcal{R}|} \sum_{(u,v) \in \mathcal{R}} (I(u,v) - \mu)^2$$

* **Blink State Machine:**
  1. A natural blink causes an abrupt drop in ocular contrast variance ($\sigma^2 < 0.88 \cdot \bar{\sigma}^2_{\text{rolling}}$).
  2. As the eyelid reopens, variance recovers back above $0.92 \cdot \bar{\sigma}^2_{\text{rolling}}$.
  3. If duration $\Delta t \in [40\text{ms}, 1200\text{ms}]$, an active blink is registered.
  4. The kiosk calls `/mark_attendance` for a face only after that face's own blink has been registered. There is no time-based or frame-count bypass, and a face that leaves the frame for >1.5 s must blink again.
  5. **Trust boundary:** this check runs in the kiosk browser. The server enforces only that `Face` check-ins come from an authenticated admin/kiosk session; it cannot verify that a blink happened. A replayed video of a blinking student is not detected.

---

### 3.3 Dynamic Cryptographic QR Infrastructure

* **Payload Construction:**
  $$\mathcal{P} = \{\text{"nonce"}: \text{UUID4}_{[:12]}, \; \text{"created\_at"}: t_{\text{epoch}}\}$$
* **Serialization & Signature:** Signed using `URLSafeTimedSerializer` with master `SECRET_KEY` and salt `qr-attendance-token`.
* **Verification Window:** The kiosk refreshes the code every 5 seconds and the API advertises a 15-second validity. `/verify_qr_token` accepts tokens up to 30 seconds old; `/verify_student`, `/get_student` and `/mark_attendance` accept up to 35 seconds so a student can type their roll number and confirm. Within that window a token can be reused (the whole class scans the same code), so it limits but does not eliminate forwarding.
* **Phone-side lookups:** `/verify_student` and `/get_student` require the live QR token (or admin credentials), so sequential roll numbers cannot be used to scrape student names.
* **One record per day:** `/mark_attendance` checks for an existing `(roll, IST date)` record before inserting. This is an application-level check, not a database constraint, so two truly simultaneous requests for the same roll could both insert; `/records` de-duplicates per day when displaying.

---

### 3.4 Concurrency & Memory Model

To prevent memory leaks and thread contention under multi-camera kiosk loads:
* **PyTorch CPU Thread Limitation:** Explicitly configured with `torch.set_num_threads(1)` to prevent OpenMP worker thrashing across Gunicorn threads.
* **Tracker Garbage Collection:** Client tracking states stored in `tracking_sessions` undergo automatic sweep eviction if idle for $>120$ seconds. The registry is guarded by a lock because Gunicorn serves requests from several threads, and it is per process: with several workers or pods a kiosk's frames may land on a process that simply re-detects on the next frame.
* **Lazy Model Loading:** MTCNN and InceptionResnetV1 are built on first use under a lock, so concurrent first requests do not load duplicate model copies.
* **Database Connection Resilience:** Connection pooling configured with `pool_pre_ping=True` and `pool_recycle=280` to prevent stale connection drops on cloud databases (AWS RDS / Render).

---

## 4. Latency Budget Analysis (30 FPS Target)

| Pipeline Phase | Allocated Budget | Measured Mean | Implementation Mechanism |
| :--- | :---: | :---: | :--- |
| **Canvas Frame Ingestion** | $< 15\text{ ms}$ | $11.2\text{ ms}$ | Canvas JPEG compression (0.60 quality) |
| **Keyframe MTCNN Pass** | $< 35\text{ ms}$ | $31.8\text{ ms}$ | 1-in-4 periodic execution, faces < 45 px discarded |
| **CSRT Inter-Frame Tracking** | $< 10\text{ ms}$ | $7.8\text{ ms}$ | OpenCV C++ compiled correlation filter |
| **Tensor Embedding Forward** | $< 40\text{ ms}$ | $37.4\text{ ms}$ | Zero-grad inference on (160, 160) crop |
| **BLAS Matrix Search ($N=10\text{k}$)** | $< 1\text{ ms}$ | $0.19\text{ ms}$ | SIMD AVX2 matrix-vector dot product |
| **Network RTT & Serialization** | $< 15\text{ ms}$ | $8.4\text{ ms}$ | Compact JSON response (boxes + labels only) |
| **Total In-Flight Processing** | **$< 50\text{ ms}$** | **$\sim 45\text{ ms}$** | **Delivers smooth 25–30 FPS real-time tracking** |

---

## 5. Security & Threat Modeling (STRIDE)

| Threat | Risk Profile | Defense Mechanism |
| :--- | :--- | :--- |
| **Spoofing (S)** | Presentation attack with printed student photo | Per-face ocular contrast blink verification in the kiosk browser |
| **Tampering (T)** | Modifying roll ID in QR payload | Cryptographic HMAC-SHA256 signature calculated over payload |
| **Repudiation (R)** | Student disputes attendance record | Timestamped immutable PostgreSQL record with modality tag |
| **Information Disclosure (I)** | Unauthenticated scraping of student database | `@admin_required` Bearer JWT / Session filter; phone lookups require a live QR token |
| **Denial of Service (D)** | Brute-force credential stuffing | Sliding-window lockout (3 attempts triggers 15-minute freeze) |
| **Elevation of Privilege (E)** | Unauthorized administrator creation | Anonymous signup only for the first admin (bootstrap); later admins require an authenticated admin unless `ALLOW_PUBLIC_ADMIN_SIGNUP=true` |

---

## 6. Disaster Recovery & Fallback Strategies

1. **Sub-Optimal Lighting:** If mean grayscale luminance drops below 35, the kiosk displays an interactive warning banner providing a 1-click fallback to the dynamic QR terminal.
2. **Camera Hardware Drop:** In the event of a webcam failure or permission denial, the kiosk cleanly catches the WebRTC exception and shows a prompt linking to the dynamic QR terminal.
3. **Cache Partition:** If Redis encounters network partitions, the `SafeCacheStore` automatically falls back to an in-memory TTL dictionary (login lockout keeps working per process) and re-probes Redis every 30 seconds, switching back once it answers.
