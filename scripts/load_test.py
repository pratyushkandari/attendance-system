"""
Load-test POST /recognize_with_box over real HTTP with several kiosks at once.

Each simulated kiosk behaves like recognize.js: it sends a 380 px wide JPEG
(quality 0.6) showing one real face, waits for the response, pauses 30 ms and
sends the next frame. The server runs MTCNN + FaceNet on every 4th frame of a
kiosk and only updates its CSRT trackers in between, so the two kinds of frame
are reported separately.

Run it against the Docker Compose stack, which serves the app with Gunicorn as
in production:

    docker compose up -d
    python scripts/load_test.py --photo data/lfw/lfw/Colin_Powell/Colin_Powell_0001.jpg

To see a smaller machine, limit the container and run it again:

    docker update --cpus 1 attendance_app
"""
import argparse
import base64
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
FRAME_WIDTH, FRAME_HEIGHT, JPEG_QUALITY = 380, 285, 60   # recognize.js: 380 px wide, quality 0.6
PAUSE_SECONDS = 0.03                                     # recognize.js: setTimeout(detectLoop, 30)


def kiosk_frames(photo: Path) -> list[str]:
    """A 4:3 kiosk frame around the photo, shifted a few pixels per frame so trackers have work to do."""
    face = cv2.resize(cv2.imread(str(photo)), (FRAME_HEIGHT, FRAME_HEIGHT))
    frame = np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), 128, np.uint8)
    left = (FRAME_WIDTH - FRAME_HEIGHT) // 2
    frame[:, left:left + FRAME_HEIGHT] = face
    frames = []
    for offset in (0, 2, 4, 6, 8, 10, 8, 6, 4, 2):
        ok, jpeg = cv2.imencode(".jpg", np.roll(frame, offset, axis=1),
                                [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        assert ok
        frames.append("data:image/jpeg;base64," + base64.b64encode(jpeg).decode())
    return frames


def login(base_url: str, email: str, password: str) -> str:
    r = requests.post(f"{base_url}/login_admin", json={"email": email, "password": password}, timeout=30)
    body = r.json()
    if body.get("status") != "success":
        raise SystemExit(f"Login failed: {body}")
    return body["token"]


class ContainerStats(threading.Thread):
    """Samples `docker stats` for one container: peak memory (MiB) and CPU %."""

    def __init__(self, container: str):
        super().__init__(daemon=True)
        self.container = container
        self.memory_mib: list[float] = []
        self.cpu_percent: list[float] = []
        self.running = True

    def run(self) -> None:
        units = {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}
        while self.running:
            out = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{json .}}", self.container],
                capture_output=True, text=True, check=False,
            ).stdout.strip()
            if out:
                stats = json.loads(out)
                used = stats["MemUsage"].split("/")[0].strip()
                for unit, factor in units.items():
                    if used.endswith(unit):
                        self.memory_mib.append(float(used[:-len(unit)]) * factor)
                self.cpu_percent.append(float(stats["CPUPerc"].rstrip("%")))
            time.sleep(1)


def run_level(args, frames: list[str], token: str, kiosks: int) -> dict:
    url = f"{args.base_url}/recognize_with_box"
    start = time.monotonic()
    measure_from, stop = start + args.warmup, start + args.warmup + args.duration
    samples: list[tuple[float, bool, str]] = []   # (seconds, keyframe, outcome)
    lock = threading.Lock()

    def kiosk() -> None:
        session = requests.Session()
        session.headers["Authorization"] = f"Bearer {token}"
        client_id = f"load-{uuid.uuid4().hex[:8]}"
        frame_no = 0
        while (sent_at := time.monotonic()) < stop:
            frame_no += 1
            t = time.perf_counter()
            try:
                r = session.post(url, json={"image": frames[frame_no % len(frames)],
                                            "client_id": client_id}, timeout=60)
                body = r.json()
                if r.status_code != 200 or "error" in body:
                    outcome = "error"
                else:
                    outcome = "ok" if len(body["faces"]) == 1 else "no face"
            except (requests.RequestException, ValueError):
                outcome = "error"
            elapsed = time.perf_counter() - t
            if sent_at >= measure_from:
                # The first frame and every 4th one run detection (recognize_with_box)
                with lock:
                    samples.append((elapsed, frame_no == 1 or frame_no % 4 == 0, outcome))
            time.sleep(PAUSE_SECONDS)

    stats = ContainerStats(args.container) if args.container else None
    if stats:
        stats.start()
    threads = [threading.Thread(target=kiosk) for _ in range(kiosks)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    if stats:
        stats.running = False

    def p(values: list[float], q: int) -> float:
        return 1000 * float(np.percentile(values, q)) if values else float("nan")

    key = [s for s, k, o in samples if k and o == "ok"]
    track = [s for s, k, o in samples if not k and o == "ok"]
    return {
        "kiosks": kiosks,
        "frames_per_s": len(samples) / args.duration,
        "key_p50": p(key, 50), "key_p95": p(key, 95),
        "track_p50": p(track, 50), "track_p95": p(track, 95),
        "errors": sum(1 for *_, o in samples if o == "error"),
        "no_face": sum(1 for *_, o in samples if o == "no face"),
        "frames": len(samples),
        "peak_mib": max(stats.memory_mib) if stats and stats.memory_mib else float("nan"),
        "mean_cpu": float(np.mean(stats.cpu_percent)) if stats and stats.cpu_percent else float("nan"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load-test /recognize_with_box with simulated kiosks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--email", default="admin@institution.edu", help="seed.sql demo admin")
    parser.add_argument("--password", default="AdminSecure@2026!")
    parser.add_argument("--photo", type=Path,
                        default=ROOT / "data/lfw/lfw/Colin_Powell/Colin_Powell_0001.jpg")
    parser.add_argument("--kiosks", default="1,2,4,8", help="comma-separated kiosk counts")
    parser.add_argument("--duration", type=float, default=60, help="seconds measured per level")
    parser.add_argument("--warmup", type=float, default=15, help="seconds before measuring")
    parser.add_argument("--container", default="attendance_app",
                        help="container to sample with docker stats ('' to skip)")
    args = parser.parse_args()

    frames = kiosk_frames(args.photo)
    token = login(args.base_url, args.email, args.password)
    print(f"{args.base_url}, {args.duration:.0f} s per level after {args.warmup:.0f} s warm-up, "
          f"photo {args.photo.name}")
    print("\n| Kiosks | Frames/s | Per kiosk | Keyframe p50 | Keyframe p95 | Tracking p50 | "
          "Tracking p95 | Errors | No face | Peak memory | Mean CPU |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for n in (int(v) for v in args.kiosks.split(",")):
        r = run_level(args, frames, token, n)
        print(f"| {n} | {r['frames_per_s']:.1f} | {r['frames_per_s'] / n:.1f} | "
              f"{r['key_p50']:.0f} ms | {r['key_p95']:.0f} ms | {r['track_p50']:.0f} ms | "
              f"{r['track_p95']:.0f} ms | {r['errors']} | {r['no_face']} | "
              f"{r['peak_mib']:.0f} MiB | {r['mean_cpu']:.0f}% |", flush=True)


if __name__ == "__main__":
    main()
