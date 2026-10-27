# Architecture Decision Records (ADRs)

This document tracks foundational architectural decisions, technical trade-offs, and design rationale across the lifecycle of the Biometric & Cryptographic Attendance Verification Platform.

---

## Index of Records

* [ADR-001: Hybrid MTCNN Cascaded CNN Detection + CSRT Correlation Tracking](#adr-001-hybrid-mtcnn-cascaded-cnn-detection--csrt-correlation-tracking)
* [ADR-002: Single-Instruction BLAS Matrix Dot Product for Biometric Search](#adr-002-single-instruction-blas-matrix-dot-product-for-biometric-search)
* [ADR-003: Dual-Channel Authentication (Stateless JWT Bearer + Session Cookie)](#adr-003-dual-channel-authentication-stateless-jwt-bearer--session-cookie)
* [ADR-004: Dynamic Cryptographic HMAC-SHA256 QR Tokens vs Static QR Codes](#adr-004-dynamic-cryptographic-hmac-sha256-qr-tokens-vs-static-qr-codes)
* [ADR-005: Resilient Two-Tier Cache Architecture (Distributed Redis + Memory Fallback)](#adr-005-resilient-two-tier-cache-architecture-distributed-redis--memory-fallback)

---

## ADR-001: Hybrid MTCNN Cascaded CNN Detection + CSRT Correlation Tracking

### Status
**Accepted**

### Context
Running deep multi-task cascaded convolutional neural networks (P-Net, R-Net, O-Net) plus an embedding network on every incoming video frame is the most expensive work in the system. On commodity x86_64 cloud containers lacking dedicated GPUs, doing it per frame limits the kiosk to a low frame rate with visible bounding-box lag.

### Decision
Decouple face localization from identity recognition by implementing a 1:4 periodic detection schedule paired with continuous object tracking:
1. **Periodic Keyframe Detection:** Run MTCNN only once every 4 frames (or whenever the active tracker list drops to zero).
2. **Inter-Frame Correlation Tracking:** Between MTCNN passes, hand off detected coordinates to OpenCV Channel and Spatial Reliability Trackers (`cv2.TrackerCSRT` or legacy KCF fallback). A tracker update is far cheaper than detection plus embedding, so most frames skip the neural networks entirely.
3. **Multi-Camera Isolation:** Scope tracker instances and frame counts to a client-generated ID (`client_id`) stored in a lock-guarded, per-process in-memory session registry with a 120-second inactivity TTL.

### Consequences
* **Positive:** Neural-network cost is paid on roughly one frame in four instead of every frame, without a GPU. (The per-stage timings have not been benchmarked in this repository; see `docs/BENCHMARKS.md`.)
* **Positive:** Prevents tracker state leakage across concurrent browser terminals.
* **Negative:** Rapid lateral head acceleration exceeding the CSRT search window between keyframes can cause transient bounding box displacement for up to 3 frames before MTCNN re-acquires.

### Alternatives Considered
* *MTCNN on Every Frame:* Rejected because it multiplies the CPU cost of the most expensive stage by four.
* *Haar Cascades:* Rejected because they are known to produce more false positives and miss angled faces under varied classroom lighting.
* *MediaPipe Face Mesh:* Viable alternative; FaceNet/MTCNN was preferred for tighter integration with the PyTorch VGGFace2 embedding pipeline.

---

## ADR-002: Single-Instruction BLAS Matrix Dot Product for Biometric Search

### Status
**Accepted**

### Context
Matching a 512-dimensional query embedding vector against an enrolled population of $N$ students requires computing similarity scores across the vector space. Iterating through database records with Python-level `for` loops and computing pairwise cosine similarities takes $O(N \cdot d)$ time with interpreter overhead per student (measured: 0.85 ms for $N = 1,000$ and 10.3 ms for $N = 10,000$ with one `np.dot` per student).

### Decision
Enforce unit $L_2$-norm normalization at embedding generation time:
$$\|\mathbf{q}\|_2 = 1.0, \quad \|\mathbf{e}_i\|_2 = 1.0$$
Because cosine similarity between two unit vectors reduces strictly to their scalar dot product:
$$\text{CosineSim}(\mathbf{q}, \mathbf{e}_i) = \frac{\mathbf{q} \cdot \mathbf{e}_i}{\|\mathbf{q}\|_2 \|\mathbf{e}_i\|_2} = \mathbf{q} \cdot \mathbf{e}_i$$
The entire enrolled student vector base is stacked into a contiguous 2D float32 matrix $\mathbf{E} \in \mathbb{R}^{N \times 512}$. Query matching executes via a single C-level BLAS matrix-vector product (`np.dot(matrix, query)`), returning similarity scores across all $N$ profiles simultaneously.

### Consequences
* **Positive:** Measured single-threaded: 0.06 ms for 1,000 profiles and 0.92 ms for 10,000 (about 11–14x faster than the per-student loop); see `docs/BENCHMARKS.md`.
* **Positive:** The stacked matrix is cached per process (`get_face_profiles()`), so keyframes make no database query. Enrollment invalidates the cache in its own process; other workers/pods refresh within 30 seconds.
* **Negative:** Requires holding normalized vectors in application memory: $50,000 \times 512 \times 4 \text{ bytes} \approx 98 \text{ MiB}$ per process.

### Alternatives Considered
* *Iterative Python Cosine Loops:* Rejected due to $O(N)$ interpreter overhead and GIL lock contention.
* *PostgreSQL pgvector HNSW Index:* Not adopted. Embeddings are stored as JSON text in `students.embedding` and matched in memory; Docker Compose runs plain `postgres:16`.

---

## ADR-003: Dual-Channel Authentication (Stateless JWT Bearer + Session Cookie)

### Status
**Accepted**

### Context
The platform serves two fundamentally distinct client archetypes:
1. **Interactive Web Portal:** Administrative users operating desktop dashboards requiring browser session security, CSRF protection, and HttpOnly cookies.
2. **Headless / Mobile Terminals:** Kiosk IoT hardware, automated export scripts, and student smartphones submitting check-ins requiring stateless, header-based bearer authentication without cross-site cookie requirements.

### Decision
Implement a hybrid authentication resolver (`@admin_required` decorator) evaluating credentials in prioritized sequence:
1. **Priority 1 (Stateless API):** Inspect `Authorization: Bearer <token>` header. Validate HMAC-SHA256 cryptographic signature and expiry claim (`exp`) using stateless JWT. If valid, allow the request without consulting the session.
2. **Priority 2 (Web Portal):** Inspect cryptographically signed Flask session cookie. Validate authenticated admin email.
3. **Failure:** A browser navigation (preferred `Accept: text/html`) is redirected to the login page (`/`); every other caller gets `401 Unauthorized` with a JSON body. Admin HTML pages are additionally redirected by a `before_app_request` hook.

### Consequences
* **Positive:** Unified access-control policy across human browser interactions and programmatic REST clients.
* **Positive:** Microservice-ready; downstream microservices can validate the self-contained JWT token without querying a central session database.
* **Negative:** Tokens cannot be revoked before their 24-hour expiration; a revocation list (e.g. in Redis) is not implemented.

---

## ADR-004: Dynamic Cryptographic HMAC-SHA256 QR Tokens vs Static QR Codes

### Status
**Accepted**

### Context
Static QR codes displayed on classroom podiums or projection screens are susceptible to proxy attendance: students in attendance take a smartphone photograph of the QR code and forward it to absent peers via messaging platforms (WhatsApp/Telegram), enabling remote fraudulent check-ins.

### Decision
Implement dynamic, time-bound rotating QR codes with cryptographic signature verification:
1. **Token Composition:** The server generates a payload comprising a unique 12-character cryptographic nonce and Unix timestamp:
   $$\text{Payload} = \{\text{nonce}: \text{UUID4}_{[:12]}, \text{created\_at}: \text{EpochTime}\}$$
2. **Cryptographic Signing:** Payload is serialized and signed using `URLSafeTimedSerializer` with master `SECRET_KEY`, salt `qr-attendance-token` and an explicit HMAC-SHA256 digest. The server also renders the check-in URL as the QR image (`segno`), so tokens are never sent to an external QR service.
3. **Rotation & TTL:** Kiosk UI refreshes the QR code every 5 seconds and advertises a 15-second validity. The server accepts tokens up to 30 seconds old at `/verify_qr_token` and up to 35 seconds old for the student lookup and `/mark_attendance`, to absorb cellular latency and typing time.
4. **Idempotent Ledger:** `/mark_attendance` checks for an existing `(roll, IST date)` record before inserting (application-level check; there is no database unique constraint).

### Consequences
* **Positive:** Shrinks remote photo-forwarding attacks to a ~35-second window; older forwarded QR images are rejected.
* **Negative:** Because the whole class scans the same rotating code, a token cannot be single-use; anyone holding a fresh token can submit any registered roll number within the window.
* **Positive:** Token verification is stateless: an HMAC check and a timestamp comparison, with no database access.
* **Negative:** Requires dynamic classroom display (monitor/tablet) connected to the kiosk server.

---

## ADR-005: Resilient Two-Tier Cache Architecture (Distributed Redis + Memory Fallback)

### Status
**Accepted**

### Context
The application uses a shared cache for brute-force login lockout counters (3 failed attempts $\rightarrow$ 15-minute lockout) so the limit holds across Gunicorn workers and pods. In containerized environments or developer local setups, an external Redis service may experience network partitions, configuration errors, or cold restarts. A hard dependency on Redis would cause total application downtime during cache outages.

### Decision
Implement `SafeCacheStore` encapsulation wrapping `redis.from_url` with automatic fallback to an in-memory dictionary store featuring timestamp-based TTL eviction:
1. On initialization, test Redis connectivity with a 1-second timeout `socket_connect_timeout=1`.
2. If Redis is reachable, operations (`set`, `get`, `delete`) execute against the distributed cluster.
3. If Redis raises an exception or is offline, the store sets `_redis_available = False` and routes operations to `_memory_cache` with expiry checking (`time.time() > exp`).
4. While degraded, Redis is re-probed with `PING` at most every 30 seconds; once it answers, operations move back to Redis (values written to memory during the outage are not migrated).

### Consequences
* **Positive:** Zero service downtime if Redis fails; core authentication, rate limiting, and attendance verification continue functioning transparently.
* **Positive:** Frictionless local developer onboarding without mandatory Redis installation.
* **Negative:** During Redis outages in multi-replica deployments, brute-force attempt counters and in-memory caches are scoped per pod rather than shared across the cluster.
