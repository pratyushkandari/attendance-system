# Performance Measurements

This page separates what has been **measured** (with the code to reproduce it) from **design targets** that have not been measured. Earlier versions listed load-test, profiler and end-to-end latency results that no script in this repository produced; those were removed.

---

## 1. Measured: face matching

Recognition compares one 512-D query embedding against every enrolled student with a single matrix-vector product (`app/ai/comparator.py`). All vectors are unit length, so each dot product is the cosine similarity.

**Environment:** Intel Core i5-12500H, Windows 11, Python 3.10.11, NumPy 1.26.4 (OpenBLAS), single-threaded BLAS as configured in the Dockerfile (`OPENBLAS_NUM_THREADS=1`). Random unit vectors; 300 runs per size for `np.dot`, 5–30 for the loop.

| Enrolled students (N) | Matrix size | `np.dot` P50 | `np.dot` P99 | Python loop, one `np.dot` per student (P50) |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 0.2 MB | 0.007 ms | 0.011 ms | 0.09 ms |
| 1,000 | 2.0 MB | 0.061 ms | 0.134 ms | 0.85 ms |
| 10,000 | 19.5 MB | 0.923 ms | 1.575 ms | 10.29 ms |
| 50,000 | 97.7 MB | 5.571 ms | 8.146 ms | 50.82 ms |

With BLAS allowed to use all 16 threads, small matrices got *slower* (0.148 ms at N = 100) because of threading overhead, which is one reason the container pins BLAS to one thread.

Reproduce:

```python
import time, numpy as np
rng = np.random.default_rng(0)
for n in (100, 1_000, 10_000, 50_000):
    m = rng.standard_normal((n, 512)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    q = m[n // 2].copy()
    runs = []
    for _ in range(300):
        t = time.perf_counter(); int(np.argmax(m @ q)); runs.append(time.perf_counter() - t)
    print(n, f"{1000 * np.percentile(runs, 50):.3f} ms")
```

Run it with `OPENBLAS_NUM_THREADS=1` to match the container.

---

## 2. Measured: loading face profiles

Embeddings are stored as JSON text in `students.embedding`. Before version 2.5.0 the kiosk reloaded and parsed every embedding on each detection keyframe. The stacked matrix is now cached per process (`get_face_profiles()` in `app/routes/attendance.py`) and rebuilt after an enrollment or every 30 seconds.

Same machine, SQLite in memory, multi-threaded BLAS:

| Enrolled students | Per keyframe before 2.5.0 | Cache rebuild (once per 30 s or enrollment) | Per keyframe with a warm cache (lookup + match) |
| ---: | ---: | ---: | ---: |
| 1,000 | 346 ms | 287 ms | 0.15 ms |
| 5,000 | 1,523 ms | 1,376 ms | 0.34 ms |

To reproduce, create the app with the test configuration, bulk-insert `Student` rows with random unit-vector embeddings, and time `get_face_profiles()` after `invalidate_face_profiles()` (cold) and on a second call (warm).

---

## 3. Not measured: model inference and end-to-end latency

MTCNN detection, FaceNet embedding and CSRT tracking were not benchmarked here. They depend heavily on the CPU, image size and thread settings, and need the VGGFace2 weights plus real face images. These are the **design targets** the pipeline is built around, not results:

| Stage | Target | Mechanism |
| :--- | :--- | :--- |
| Frame upload | small payload | 380 px wide JPEG at quality 0.6 from the browser |
| Detection | amortised over 4 frames | MTCNN only on every 4th frame per kiosk, or when no face is being tracked |
| Tracking | far cheaper than detection | one OpenCV CSRT tracker per face between keyframes |
| Embedding | once per detected face per keyframe | 160 × 160 crop through `InceptionResnetV1` with gradients disabled |
| Matching | well under 1 ms for a class-sized roster | cached matrix, one `np.dot` (section 1) |

The kiosk sends the next frame only after the previous response arrives, so frame rate equals 1 / round-trip time. To measure it, record `http_request_duration_seconds` for `attendance.recognize_with_box` from `/metrics` while a kiosk is running.

---

## 4. QR token checks

Verifying a QR token is an HMAC-SHA256 signature check plus a timestamp comparison in `itsdangerous`, with no database access. It was not benchmarked separately.
