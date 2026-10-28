# Benchmarks

Measurements of the face recognition path, from matching and profile loading up to whole kiosk requests, with notes on reproducing them.

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

## Recognition requests

What the server spends on one kiosk frame. Same machine, on AC power, with the pinned versions: torch 2.14.1 (CPU), facenet-pytorch 2.5.3 and OpenCV 4.9.0. PyTorch, OpenMP and BLAS each use one thread, as in the Docker image.

The frames match what `recognize.js` sends: a 380 × 285 JPEG at quality 0.6, about 14 KB. The test image is a 512 × 512 portrait cropped to 4:3, which gives a 64 × 81 px face. The two-face frame puts two copies of the head side by side in a 380 × 214 (16:9) frame.

The figures come from one run. A second run agreed to within about 10%.

### Startup and the first face request

Cold-start times vary more between runs, so this table shows the range over both runs:

| Step | Time |
| --- | ---: |
| Import torch, OpenCV and facenet-pytorch (at app startup) | 6.6–7.6 s |
| Build MTCNN | 24–33 ms |
| Build InceptionResnetV1 and load the VGGFace2 weights | 0.4–0.5 s |
| First MTCNN detection | 0.1–0.2 s |
| First FaceNet embedding | 91–96 ms |

The models load lazily, so the first face request after startup builds both of them and runs them for the first time: about 0.7 s, compared with 0.2 s for a warm keyframe. The weights were already in the local PyTorch cache. A fresh container, including Render after a restart, downloads the 111,898,327-byte file first.

### Per step

| Step | p50 | p95 |
| --- | ---: | ---: |
| Decode the JPEG data URL | 0.8 ms | 2.1 ms |
| MTCNN detection, 380 × 285, one face | 96 ms | 133 ms |
| MTCNN detection, 380 × 214, two faces | 98 ms | 127 ms |
| FaceNet embedding, per face | 64 ms | 92 ms |
| CSRT tracker init, per face | 18 ms | 25 ms |
| CSRT tracker update, per face | 24 ms | 33 ms |

Matching against 1,000 students (0.06 ms, see above) is negligible next to these.

### Whole requests

`POST /recognize_with_box` through Flask's test client, so there's no network, TLS or Gunicorn time. 1,000 students are enrolled, and one kiosk sends frames that move a few pixels between them: 400 frames with one face and 200 with two, after 8 warm-up frames.

| Frame | One face, p50 | One face, p95 | Two faces, p50 | Two faces, p95 |
| --- | ---: | ---: | ---: | ---: |
| Keyframe: detection, embedding, match, tracker init and update | 199 ms | 261 ms | 299 ms | 358 ms |
| Tracking frame: tracker update only | 28 ms | 39 ms | 50 ms | 64 ms |

Detection runs on every 4th frame, so the average frame costs 73 ms with one face and 115 ms with two. The profile cache was warm throughout. At 1,000 students, one keyframe every 30 seconds also pays the ~290 ms cache rebuild from the table above.

The kiosk sends the next frame only after the previous response arrives, then waits 30 ms (`recognize.js`). Before any network time, one kiosk on this machine therefore runs at about 9.7 frames per second with one face in view and 6.9 with two. Without that pause, the server-side limit would be 13.7 and 8.7.

To reproduce, decode one kiosk frame with `decode_image_payload()`, then time `mtcnn.detect()`, `get_embedding_from_crop()` and a CSRT tracker on it. Then post a sequence of such frames to `/recognize_with_box`, using the test config and 1,000 random enrolled embeddings as in the profile benchmark. Set the three thread variables to 1 and plug the laptop in: on battery, Windows made each step 3 to 5 times slower.

## Not measured yet

- **Network and browser time.** The network round trip, the browser's canvas capture and the browser's JPEG encoding all add to every frame.
- **Production hardware.** A small cloud instance such as Render's will be slower than this laptop. To see real numbers on a deployment, watch the `http_request_duration_seconds` histogram for `attendance.recognize_with_box` on `/metrics` while a kiosk is running.
- **QR token checks.** Each is an HMAC-SHA256 verification and a timestamp comparison with no database access, and they weren't benchmarked separately.
