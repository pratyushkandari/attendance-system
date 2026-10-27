# System Architecture & Technical Design Document (RFC-042)

**System:** VisionAttend - Enterprise Biometric & Dual-Channel Cryptographic Attendance Platform  
**Author:** Pratyush Kandari  
**Last Revised:** October 2026 (v2.5.0)  

---

## 1. Executive Summary & Problem Space

Institutional attendance recording at scale suffers from two distinct systemic vulnerabilities:
1. **Inference Latency in Computer Vision Pipelines:** Running cascaded deep-learning face detection (MTCNN) and an embedding network on every video frame is expensive on CPU-only servers, so a naive pipeline gives a slow, jittery kiosk.
2. **Proxy Attendance in QR-Based Tracking:** Static QR codes posted in lecture halls are photographed and shared via messaging apps, enabling students to check in remotely.

This platform addresses both through:
* **Periodic Detection + CSRT Tracking:** MTCNN and FaceNet run on every 4th frame per kiosk (or when nothing is tracked); OpenCV CSRT trackers move the boxes on the frames in between.
* **Matrix Similarity Search:** Normalized 512-D face embeddings are kept as one cached `(N, 512)` matrix per process and matched with a single `np.dot(matrix, query_vector)` (about 0.06 ms for 1,000 students single-threaded; see [docs/BENCHMARKS.md](docs/BENCHMARKS.md)).
* **Presentation Attack Detection (PAD):** Client-side eye-region contrast-variance tracking requires each recognised face to blink before it is marked, defeating static printed-photo attacks (video replays of a blinking face are not detected; see §3.2).
* **Dynamic Time-Bound QR Tokens:** Server-generated HMAC-SHA256 signed tokens rotate every 5 seconds and are accepted for at most 30–35 seconds, shrinking the window in which a forwarded photograph is usable.

---

## 2. High-Level Architecture & End-to-End Topology

```
                              HIGH-LEVEL DATA FLOW
  ┌─────────────────────────────────────────────────────────────────────────────────┐
  │                                                                                 │
  │  [Webcam Kiosk Client]               [Mobile QR Client / REST API Clients]      │
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
  │  │ BLAS Match vs   │                 │ (B-Tree indexes)│                        │
  │  │ cached matrix   │                 └─────────────────┘                        │
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
JPEG Frame from Browser (380 px wide, data URL)
      │
      ▼
[decode_image_payload: base64 + cv2.imdecode] ──► invalid → JSON error, loop continues
      │
      ▼
Luminance Check (mean < 35 triggers low-light alert)
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
      │   [BLAS Matrix Dot Product Search] (scores = cached matrix · query)
      │       │
      │       ▼
      │   Initialize new cv2.TrackerCSRT instances
      │
      └── Every frame (including keyframes):
              │
              ▼
          Update CSRT trackers; drop lost or tiny boxes
              │
              ▼
          Return boxes (frame coordinates) + identity labels; the browser smooths
          them and maps them through the video's object-fit: cover crop
```

The profile matrix comes from `get_face_profiles()`, which caches the stacked embeddings per process. `/save_face_data` invalidates the cache in the process that handled the enrollment; other workers and pods rebuild theirs when it is older than 30 seconds. Reloading and parsing every JSON embedding on each keyframe, as earlier versions did, took ~350 ms at 1,000 students.

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
* **Serialization & Signature:** Signed using `URLSafeTimedSerializer` with master `SECRET_KEY`, salt `qr-attendance-token` and an explicit HMAC-SHA256 digest (itsdangerous would otherwise use HMAC-SHA1).
* **Rendering:** `/generate_qr_token` builds the absolute `/qr_mobile?token=…` URL and returns it as an SVG QR code rendered with `segno`, so live tokens never leave the server. `ProxyFix` trusts one `X-Forwarded-Proto` hop so the URL uses `https` behind Render or an ingress.
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
* **Request Limits:** `MAX_CONTENT_LENGTH` is 10 MB; larger bodies get a JSON `413` before they are buffered.
* **Startup Checks & Logging:** `create_app` refuses to start with an empty `SECRET_KEY` or one published in this repository. `run.py` configures logging before importing the app so INFO lines (for example Redis status) are emitted.

---

## 4. Latency Budget (Design Targets)

These are the targets the pipeline is designed around. Apart from matrix matching, they have **not** been measured; see [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for what has been measured and how.

| Pipeline Phase | Target | Implementation Mechanism |
| :--- | :---: | :--- |
| **Canvas Frame Ingestion** | $< 15\text{ ms}$ | 380 px wide canvas JPEG at 0.60 quality |
| **Keyframe MTCNN Pass** | amortised over 4 frames | 1-in-4 periodic execution, faces < 45 px discarded |
| **CSRT Inter-Frame Tracking** | $< 10\text{ ms}$ per face | OpenCV C++ correlation filter |
| **Tensor Embedding Forward** | $< 40\text{ ms}$ per face | Zero-grad inference on a (160, 160) crop |
| **Matrix Search** | $< 1\text{ ms}$ for a class roster (measured: 0.06 ms at $N=1\text{k}$, 0.92 ms at $N=10\text{k}$) | Cached matrix, one BLAS matrix-vector product |
| **Network RTT & Serialization** | $< 15\text{ ms}$ | Compact JSON response (boxes + labels only) |

The kiosk sends the next frame only after the previous response, so its frame rate is 1 / round-trip time.

---

## 5. Security & Threat Modeling (STRIDE)

| Threat | Risk Profile | Defense Mechanism |
| :--- | :--- | :--- |
| **Spoofing (S)** | Presentation attack with printed student photo | Per-face ocular contrast blink verification in the kiosk browser |
| **Tampering (T)** | Modifying roll ID in QR payload | Cryptographic HMAC-SHA256 signature calculated over payload |
| **Repudiation (R)** | Student disputes attendance record | Timestamped record with check-in method (`Face`/`QR`); note that admins can purge all records |
| **Information Disclosure (I)** | Unauthenticated scraping of student database | `@admin_required` Bearer JWT / Session filter; phone lookups require a live QR token |
| **Denial of Service (D)** | Brute-force credential stuffing | Sliding-window lockout (3 attempts triggers 15-minute freeze) |
| **Elevation of Privilege (E)** | Unauthorized administrator creation | Anonymous signup only for the first admin (bootstrap); later admins require an authenticated admin unless `ALLOW_PUBLIC_ADMIN_SIGNUP=true` |

---

## 6. Disaster Recovery & Fallback Strategies

1. **Sub-Optimal Lighting:** If mean grayscale luminance drops below 35, the kiosk displays an interactive warning banner providing a 1-click fallback to the dynamic QR terminal.
2. **Camera Hardware Drop:** In the event of a webcam failure or permission denial, the kiosk cleanly catches the WebRTC exception and shows a prompt linking to the dynamic QR terminal.
3. **Cache Partition:** If Redis encounters network partitions, the `SafeCacheStore` automatically falls back to an in-memory TTL dictionary (login lockout keeps working per process) and re-probes Redis every 30 seconds, switching back once it answers.
