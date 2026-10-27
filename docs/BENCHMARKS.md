# Benchmarks

Measurements for the parts of the recognition path that can be timed in isolation, with the code to reproduce them. Model inference isn't covered yet; see the last section.

**Machine:** Intel Core i5-12500H, Windows 11, Python 3.10.11, NumPy 1.26.4 (OpenBLAS).

## Face matching

Recognition scores one 512-d query embedding against every enrolled student with a single matrix-vector product (`app/ai/comparator.py`). All vectors are unit length, so each dot product is a cosine similarity.

BLAS limited to one thread (`OPENBLAS_NUM_THREADS=1`, as in the Docker image), random unit vectors, 300 runs per size for `np.dot` and 5 to 30 for the loop:

| Students (N) | Matrix size | `np.dot` p50 | `np.dot` p99 | Python loop, p50 |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 0.2 MB | 0.007 ms | 0.011 ms | 0.09 ms |
| 1,000 | 2.0 MB | 0.061 ms | 0.134 ms | 0.85 ms |
| 10,000 | 19.5 MB | 0.923 ms | 1.575 ms | 10.29 ms |
| 50,000 | 97.7 MB | 5.571 ms | 8.146 ms | 50.82 ms |

The loop column is one `np.dot` per student in Python, for comparison.

Letting BLAS use all 16 threads made small matrices slower (0.148 ms at N = 100) because of threading overhead. That's one of the reasons the container pins BLAS to a single thread.

To reproduce:

```python
import time

import numpy as np

rng = np.random.default_rng(0)
for n in (100, 1_000, 10_000, 50_000):
    m = rng.standard_normal((n, 512)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    q = m[n // 2].copy()
    runs = []
    for _ in range(300):
        t = time.perf_counter()
        int(np.argmax(m @ q))
        runs.append(time.perf_counter() - t)
    print(n, f"{1000 * np.percentile(runs, 50):.3f} ms")
```

Run it with `OPENBLAS_NUM_THREADS=1` set to match the container.

## Loading face profiles

Embeddings are stored as JSON text in `students.embedding`, so building the matrix means loading and parsing every row. Up to version 2.4.3 this happened on every detection keyframe. Since 2.5.0 the matrix is cached per process (`get_face_profiles()` in `app/routes/attendance.py`) and rebuilt after an enrollment or every 30 seconds.

Same machine, in-memory SQLite, default BLAS threading:

| Students | Per keyframe, 2.4.3 | Cache rebuild | Per keyframe, warm cache |
| ---: | ---: | ---: | ---: |
| 1,000 | 346 ms | 287 ms | 0.15 ms |
| 5,000 | 1,523 ms | 1,376 ms | 0.34 ms |

To reproduce, create the app with the test config, bulk-insert `Student` rows with random unit-vector embeddings, then time `get_face_profiles()` right after `invalidate_face_profiles()` (cold) and again on the second call (warm).

## Not measured yet

MTCNN detection, FaceNet embedding and CSRT tracking haven't been benchmarked. Their cost depends heavily on the CPU, frame size and thread settings, and measuring them needs the VGGFace2 weights and real face images.

The kiosk only sends a new frame once the previous response arrives, so its frame rate is 1 / round-trip time. The easiest way to measure it on a real deployment is the `http_request_duration_seconds` histogram for `attendance.recognize_with_box` on `/metrics` while a kiosk is running.

QR token checks are an HMAC-SHA256 verification and a timestamp comparison with no database access, and weren't benchmarked separately.
