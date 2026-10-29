"""
Measure face recognition accuracy on LFW (Labeled Faces in the Wild).

Every photo goes through the app's own code: MTCNN detection, the checks and crop
that /capture_face applies, and get_embedding_from_crop(). The results describe
what the app does rather than FaceNet in general. Two tests:

* Pairs: the standard 6,000 LFW pairs (3,000 of the same person, 3,000 of two
  different people), compared with cosine similarity.
* Kiosk: everyone with at least 6 usable photos is enrolled the way
  /save_face_data does it (the normalised mean of 5 embeddings). Their other
  photos, plus one photo of everybody else, are matched against all enrolled
  people at once, as the kiosk does.

The first run downloads LFW (about 180 MB) into --data-dir and caches the
embeddings there, so later runs only redo the maths.

Usage: python scripts/evaluate_accuracy.py [--data-dir data/lfw] [--threads N]
"""
import argparse
import hashlib
import json
import os
import sys
import tarfile
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The figshare copies scikit-learn downloads, with their SHA-256 checksums
DOWNLOADS = {
    "lfw.tgz": (
        "https://ndownloader.figshare.com/files/5976018",
        "055f7d9c632d7370e6fb4afc7468d40f970c34a80d4c6f50ffec63f5a8d536c0",
    ),
    "pairs.txt": (
        "https://ndownloader.figshare.com/files/5976006",
        "ea42330c62c92989f9d7c03237ed5d591365e89b3e649747777b70e692dc1592",
    ),
}
ENROLL_SAMPLES = 5           # the kiosk enrollment captures 5 samples (capture.js)
MAX_FALSE_ACCEPT = 0.001     # at most 1 in 1,000 comparisons accepted as the wrong person
SWEEP = [round(t, 2) for t in np.arange(0.40, 0.901, 0.05)]
FINE_GRID = np.round(np.arange(0.0, 1.0001, 0.01), 2)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, (url, checksum) in DOWNLOADS.items():
        target = data_dir / name
        if target.exists():
            continue
        print(f"Downloading {name} ...")
        partial = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(url, partial)  # fixed https URL from the table above
        if sha256(partial) != checksum:
            partial.unlink()
            raise SystemExit(f"{name}: checksum mismatch, download deleted")
        partial.rename(target)

    photos = data_dir / "lfw"
    if not photos.exists():
        print("Extracting lfw.tgz ...")
        root = data_dir.resolve()
        with tarfile.open(data_dir / "lfw.tgz") as tar:
            members = tar.getmembers()
            for m in members:
                target = (data_dir / m.name).resolve()
                if not (m.isfile() or m.isdir()) or root not in target.parents:
                    raise SystemExit(f"Unexpected entry in lfw.tgz: {m.name}")
            tar.extractall(data_dir, members=members)


def embed(paths: list[Path], threads: int) -> tuple[np.ndarray, list[str], np.ndarray]:
    """
    Embed the labelled face in each photo with the app's code. Returns (N, 512)
    embeddings, a per-photo error ("" if a face was embedded) and faces detected per photo.
    """
    import cv2
    import torch

    from app.ai.facenet_model import get_embedding_from_crop, mtcnn
    from app.config import Config

    torch.set_num_threads(threads)  # the server pins one thread; results don't depend on it
    embeddings = np.zeros((len(paths), 512), dtype=np.float32)
    errors = [""] * len(paths)
    faces = np.zeros(len(paths), dtype=np.int32)
    start = time.time()
    for i, path in enumerate(paths):
        if i and i % 1000 == 0:
            print(f"  {i}/{len(paths)} photos, {time.time() - start:.0f} s")
        frame = cv2.imread(str(path))
        boxes, probs = mtcnn.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if boxes is None:
            errors[i] = "no face"
            continue
        boxes = np.asarray(boxes, dtype=np.float32)   # facenet-pytorch returns an object array
        faces[i] = len(boxes)

        # LFW labels the person in the middle of the photo. /capture_face takes the
        # largest face instead, which in LFW's group photos is sometimes someone else.
        h_img, w_img = frame.shape[:2]
        centres = (boxes[:, :2] + boxes[:, 2:]) / 2
        j = int(np.argmin(np.linalg.norm(centres - [w_img / 2, h_img / 2], axis=1)))

        # From here on, the same checks and crop as /capture_face
        if probs[j] < Config.MTCNN_CONFIDENCE_THRESHOLD:
            errors[i] = "low confidence face"
            continue
        x1, y1, x2, y2 = boxes[j]
        x, y = max(0, int(x1)), max(0, int(y1))
        w, h = min(int(x2 - x1), w_img - x), min(int(y2 - y1), h_img - y)
        if w < 40 or h < 40:
            errors[i] = "face too small"
            continue
        embedding = get_embedding_from_crop(frame[y:y + h, x:x + w])
        if embedding is None:
            errors[i] = "embedding failed"
            continue
        embeddings[i] = embedding
    return embeddings, errors, faces


def load_embeddings(data_dir: Path, threads: int) -> tuple[list[str], np.ndarray, list[str], np.ndarray]:
    photo_dir = data_dir / "lfw"
    names = sorted(p.relative_to(photo_dir).as_posix() for p in photo_dir.glob("*/*.jpg"))
    cache_file = data_dir / "embeddings.npz"
    if cache_file.exists():
        cached = np.load(cache_file)
        if "faces" in cached and list(cached["names"]) == names:
            return names, cached["embeddings"], list(cached["errors"]), cached["faces"]
    print(f"Embedding {len(names)} photos ...")
    embeddings, errors, faces = embed([photo_dir / n for n in names], threads)
    np.savez(cache_file, names=np.array(names), embeddings=embeddings, errors=np.array(errors),
             faces=faces)
    return names, embeddings, errors, faces


def read_pairs(path: Path) -> list[tuple[str, str, bool, int]]:
    """Parse pairs.txt into (photo_a, photo_b, same_person, fold)."""
    def photo(name: str, number: str) -> str:
        return f"{name}/{name}_{int(number):04d}.jpg"

    lines = path.read_text().splitlines()
    folds, per_fold = (int(v) for v in lines[0].split())
    pairs = []
    for i, line in enumerate(lines[1:]):
        fold = i // (2 * per_fold)
        parts = line.split("\t")
        if len(parts) == 3:
            pairs.append((photo(parts[0], parts[1]), photo(parts[0], parts[2]), True, fold))
        else:
            pairs.append((photo(parts[0], parts[1]), photo(parts[2], parts[3]), False, fold))
    assert len(pairs) == folds * 2 * per_fold
    return pairs


def pair_test(pairs, index, embeddings, found) -> dict:
    a = np.array([index[p[0]] for p in pairs])
    b = np.array([index[p[1]] for p in pairs])
    same = np.array([p[2] for p in pairs])
    folds = np.array([p[3] for p in pairs])
    usable = found[a] & found[b]
    # No face in either photo: the kiosk can't match it, so it counts as "not the same"
    scores = np.where(usable, np.sum(embeddings[a] * embeddings[b], axis=1), -1.0)

    def rates(t: float, mask=slice(None)) -> dict:
        accept = scores[mask] >= t
        s = same[mask]
        return {
            "accuracy": float(np.mean(accept == s)),
            "false_accept": float(np.mean(accept[~s])),
            "false_reject": float(np.mean(~accept[s])),
        }

    # Standard LFW protocol: pick the best threshold on 9 folds, test on the 10th
    fold_acc = []
    for k in range(folds.max() + 1):
        train, test = folds != k, folds == k
        best = max(FINE_GRID, key=lambda t: rates(t, train)["accuracy"])
        fold_acc.append(rates(best, test)["accuracy"])

    return {
        "pairs": len(pairs),
        "pairs_missing_a_face": int(np.sum(~usable)),
        "ten_fold_accuracy": (float(np.mean(fold_acc)), float(np.std(fold_acc))),
        "sweep": {t: rates(t) for t in SWEEP},
        "fine": {float(t): rates(t) for t in FINE_GRID},
    }


def kiosk_test(names, embeddings, found) -> dict:
    by_person = defaultdict(list)
    for i, name in enumerate(names):
        by_person[name.split("/")[0]].append(i)

    centroids, enrolled_probes, probe_owner, strangers = [], [], [], []
    no_face_probes = 0
    for photos in by_person.values():
        usable = [i for i in photos if found[i]]
        if len(usable) > ENROLL_SAMPLES:
            # Same maths as /save_face_data: normalised mean of the samples
            mean = embeddings[usable[:ENROLL_SAMPLES]].mean(axis=0)
            centroids.append(mean / np.linalg.norm(mean))
            owner = len(centroids) - 1
            enrolled_probes += usable[ENROLL_SAMPLES:]
            probe_owner += [owner] * len(usable[ENROLL_SAMPLES:])
            no_face_probes += len(photos) - len(usable)
        elif usable:
            strangers.append(usable[0])

    matrix = np.stack(centroids)
    owner = np.array(probe_owner)
    # Same as vectorized_matrix_match: one matrix product, best score wins
    genuine_scores = embeddings[enrolled_probes] @ matrix.T
    best, best_score = genuine_scores.argmax(axis=1), genuine_scores.max(axis=1)
    stranger_best = (embeddings[strangers] @ matrix.T).max(axis=1)

    def rates(t: float) -> dict:
        accepted = best_score >= t
        right = accepted & (best == owner)
        wrong = accepted & (best != owner)
        stranger_accepted = stranger_best >= t
        return {
            "recognised": float(np.mean(right)),
            "wrong_person": float(np.mean(wrong)),
            "not_recognised": float(np.mean(~accepted)),
            "stranger_accepted": float(np.mean(stranger_accepted)),
            # Anyone marked as someone they aren't, over every probe
            "false_accept": float((wrong.sum() + stranger_accepted.sum())
                                  / (len(best) + len(stranger_best))),
        }

    return {
        "enrolled_people": len(centroids),
        "enrolled_probes": len(enrolled_probes),
        "enrolled_probes_without_face": no_face_probes,
        "strangers": len(strangers),
        "sweep": {t: rates(t) for t in SWEEP},
        "fine": {float(t): rates(t) for t in FINE_GRID},
    }


def pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "lfw")
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()

    download(args.data_dir)
    names, embeddings, errors, faces = load_embeddings(args.data_dir, args.threads)
    found = np.array([not e for e in errors])
    index = {n: i for i, n in enumerate(names)}

    failures = defaultdict(int)
    for e in errors:
        if e:
            failures[e] += 1
    print(f"\nPhotos: {len(names)}, with more than one face: {int(np.sum(faces > 1))}, "
          f"no usable face: {len(names) - int(found.sum())} {dict(failures)}")

    pairs = pair_test(read_pairs(args.data_dir / "pairs.txt"), index, embeddings, found)
    mean, std = pairs["ten_fold_accuracy"]
    print(f"\nPairs: {pairs['pairs']} ({pairs['pairs_missing_a_face']} with a photo where no face was found)")
    print(f"10-fold accuracy: {pct(mean)} ± {pct(std)}")
    print("\n| Threshold | Accuracy | False accept | False reject |")
    print("| ---: | ---: | ---: | ---: |")
    for t, r in pairs["sweep"].items():
        print(f"| {t:.2f} | {pct(r['accuracy'])} | {pct(r['false_accept'])} | {pct(r['false_reject'])} |")

    kiosk = kiosk_test(names, embeddings, found)
    print(f"\nKiosk: {kiosk['enrolled_people']} people enrolled, {kiosk['enrolled_probes']} photos of them "
          f"({kiosk['enrolled_probes_without_face']} more had no usable face), {kiosk['strangers']} strangers")
    print("\n| Threshold | Recognised | Wrong person | Not recognised | Stranger accepted |")
    print("| ---: | ---: | ---: | ---: | ---: |")
    for t, r in kiosk["sweep"].items():
        print(f"| {t:.2f} | {pct(r['recognised'])} | {pct(r['wrong_person'])} | "
              f"{pct(r['not_recognised'])} | {pct(r['stranger_accepted'])} |")

    # Lowest threshold where both tests stay within the false-accept budget
    chosen = next(t for t in FINE_GRID
                  if pairs["fine"][float(t)]["false_accept"] <= MAX_FALSE_ACCEPT
                  and kiosk["fine"][float(t)]["false_accept"] <= MAX_FALSE_ACCEPT)
    p, k = pairs["fine"][float(chosen)], kiosk["fine"][float(chosen)]
    print(f"\nLowest threshold with false accepts <= {pct(MAX_FALSE_ACCEPT)} in both tests: {chosen:.2f}")
    print(f"  pairs: false accept {pct(p['false_accept'])}, false reject {pct(p['false_reject'])}")
    print(f"  kiosk: recognised {pct(k['recognised'])}, wrong person {pct(k['wrong_person'])}, "
          f"stranger accepted {pct(k['stranger_accepted'])}")

    results = {"photos": len(names), "photos_with_several_faces": int(np.sum(faces > 1)),
               "no_face": dict(failures), "pairs": pairs, "kiosk": kiosk,
               "chosen_threshold": float(chosen)}
    (args.data_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
