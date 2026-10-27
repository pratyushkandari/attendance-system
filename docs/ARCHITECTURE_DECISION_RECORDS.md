# Architecture Decision Records

Short records of the main design decisions: what the problem was, what I chose, and what it costs.

- [ADR-001: Detect faces on keyframes, track them in between](#adr-001-detect-faces-on-keyframes-track-them-in-between)
- [ADR-002: Match embeddings with a single matrix-vector product](#adr-002-match-embeddings-with-a-single-matrix-vector-product)
- [ADR-003: Accept both session cookies and JWTs](#adr-003-accept-both-session-cookies-and-jwts)
- [ADR-004: Rotating signed QR codes instead of a static code](#adr-004-rotating-signed-qr-codes-instead-of-a-static-code)
- [ADR-005: Redis is optional, with an in-memory fallback](#adr-005-redis-is-optional-with-an-in-memory-fallback)

---

## ADR-001: Detect faces on keyframes, track them in between

**Status:** Accepted

### Context

Running MTCNN detection and a FaceNet forward pass on every frame is the most expensive thing the app does. On a CPU-only server, doing that per frame makes the kiosk slow and the boxes visibly lag behind the faces.

### Decision

- Run MTCNN and FaceNet only on every 4th frame per kiosk, or whenever no face is being tracked.
- On the frames in between, move the boxes with OpenCV CSRT trackers (KCF if CSRT isn't available). A tracker update is much cheaper than detection plus embedding.
- Keep tracker state per kiosk, keyed by a `client_id` the browser generates, in a lock-protected in-memory registry that drops idle kiosks after 120 seconds.

### Consequences

- The neural networks run on roughly one frame in four, with no GPU needed.
- Two kiosks never share or overwrite each other's trackers.
- If a head moves quickly, a box can drift for a few frames until the next keyframe corrects it.
- Tracker state is per process. With several pods, a kiosk should stick to one pod; otherwise its trackers are rebuilt on the next keyframe.

### Alternatives considered

- **Detection on every frame:** roughly four times the CPU cost of the most expensive step.
- **Haar cascades:** cheaper, but more false positives and worse with angled faces and uneven classroom lighting.
- **MediaPipe:** a reasonable option. MTCNN was chosen because it ships with facenet-pytorch, next to the VGGFace2 FaceNet model used for embeddings.

---

## ADR-002: Match embeddings with a single matrix-vector product

**Status:** Accepted

### Context

Each detected face has to be compared against every enrolled student. Looping over students in Python and computing a cosine similarity for each costs about 0.85 ms at 1,000 students and 10 ms at 10,000, and that runs for every face on every keyframe.

### Decision

Scale every embedding to unit length when it's created. For unit vectors, cosine similarity equals the dot product, so the enrolled embeddings can be stacked into one `N x 512` float32 matrix and scored with a single `matrix @ query`. The best score is a match if it's at least `FACE_MATCH_THRESHOLD`.

### Consequences

- Matching takes 0.06 ms at 1,000 students and 0.92 ms at 10,000 on one core, 11 to 14 times faster than the loop (see [BENCHMARKS.md](BENCHMARKS.md)).
- The stacked matrix is cached per process, so keyframes don't hit the database. An enrollment clears the cache in its own process; other processes pick up the change within 30 seconds.
- The matrix lives in memory: about 98 MB per process at 50,000 students.

### Alternatives considered

- **Per-student Python loop:** the interpreter overhead grows with every student.
- **pgvector with an HNSW index:** would scale further, but adds a PostgreSQL extension and approximate search that a classroom-sized roster doesn't need. Embeddings are stored as JSON text and matched in memory.

---

## ADR-003: Accept both session cookies and JWTs

**Status:** Accepted

### Context

There are two kinds of clients. Admins use the browser UI, where an `HttpOnly` cookie is the safer choice. Scripts and API clients (CSV exports, curl, Postman) are easier to write against a bearer token.

### Decision

A single `@admin_required` decorator checks, in order:

1. An `Authorization: Bearer <token>` header with a valid HS256 JWT.
2. Otherwise, the signed Flask session cookie.
3. Otherwise, a browser loading a page is redirected to the login page, and every other caller gets a `401` with a JSON body.

### Consequences

- One access-control rule covers both the UI and the API.
- A JWT can be verified without any server-side lookup.
- JWTs can't be revoked: a leaked token is valid until it expires (24 hours), including after logout. A revocation list in Redis would fix this but isn't implemented.

---

## ADR-004: Rotating signed QR codes instead of a static code

**Status:** Accepted

### Context

A static QR code on the classroom screen is easy to abuse: a student in the room takes a photo and sends it to friends who aren't there.

### Decision

- The server issues a token containing a random nonce and a timestamp, signed by itsdangerous (`URLSafeTimedSerializer`) with HMAC-SHA256, the app's `SECRET_KEY` and a fixed salt.
- The classroom screen fetches a new token every 5 seconds. The server renders the check-in URL as the QR image itself (segno), so tokens are never sent to an outside QR service.
- Tokens are accepted up to 30 seconds old when scanned and up to 35 seconds old for the lookup and check-in, to allow for slow mobile connections and typing.
- `/mark_attendance` skips the insert if the student already has a record for that IST date.

### Consequences

- A forwarded photo of the code stops working within about 35 seconds.
- Verifying a token is an HMAC check and a timestamp comparison, with no database access.
- Because the whole class scans the same code, tokens can't be single-use. Anyone with a fresh token can submit any roll number inside that window.
- It needs a screen in the classroom that can show the rotating code.

---

## ADR-005: Redis is optional, with an in-memory fallback

**Status:** Accepted

### Context

Login lockout (3 failures, then 15 minutes) only works across several Gunicorn workers or pods if the counters are shared, which is what Redis is for. But making Redis a hard dependency would mean a Redis outage takes down logins too, and it makes local setup heavier.

### Decision

`SafeCacheStore` wraps the Redis client:

1. At startup it tries to connect with a 1-second timeout.
2. If Redis is reachable, `get`, `set` and `delete` go to Redis.
3. If Redis is unreachable or a call fails, it switches to an in-memory dictionary with expiry timestamps.
4. While degraded, it pings Redis at most every 30 seconds and switches back once Redis answers. Counters written to memory in the meantime aren't copied over.

### Consequences

- Logins and attendance keep working if Redis goes down.
- Local development doesn't need Redis.
- During an outage, or with no Redis configured, each process counts failed logins on its own, so the lockout is less strict.
