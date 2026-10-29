# Recognition accuracy

How often the face channel recognises the right person, and how often it accepts the wrong one, measured on [LFW](http://vis-www.cs.umass.edu/lfw/) (Labeled Faces in the Wild) with the app's own code. The script is `scripts/evaluate_accuracy.py` (`make accuracy`).

**Machine and versions:** Intel Core i5-12500H, Windows 11, Python 3.10.11, torch 2.14.1 (CPU), facenet-pytorch 2.5.3, OpenCV 4.9.0, NumPy 1.26.4.

## Method

LFW has 13,233 photos of 5,749 people. The script downloads the original, unaligned photos and the standard pairs list from the figshare mirror that scikit-learn uses, and checks their SHA-256.

Each photo is embedded with the same steps as enrollment:

1. MTCNN detection (`app/ai/facenet_model.py`).
2. The face nearest the centre of the photo. LFW labels the person in the middle, and 2,173 of the photos contain more than one face.
3. The checks `/capture_face` applies: detection confidence of at least 0.90 and a face at least 40 × 40 px.
4. The same crop, then `get_embedding_from_crop()`: resize to 160 × 160, FaceNet (VGGFace2 weights), scale to unit length.

Only one photo failed, on detection confidence.

Two tests use these embeddings:

- **Pairs.** The standard 6,000 LFW pairs: 3,000 of the same person and 3,000 of two different people, in 10 folds. The score is the cosine similarity of the two photos. A pair that includes a photo with no usable face counts as "different", because the kiosk couldn't match it.
- **Kiosk.** Everyone with at least 6 usable photos (311 people) is enrolled as the normalised mean of their first 5 embeddings, the same maths as `/save_face_data`. Their remaining 3,870 photos are then matched against all 311 at once, as `vectorized_matrix_match()` does, and so is one photo of each of the other 5,438 people. A photo of an enrolled person is either recognised, matched to the wrong person, or not recognised. A photo of a stranger is either rejected or accepted as someone it isn't.

## Results

10-fold pair accuracy is **98.95% ± 0.44%**. That's the standard LFW protocol, which picks the best threshold on 9 folds and tests on the 10th. facenet-pytorch reports 99.65% for the same model with its own preprocessing. The app crops the bare detector box without aligning the face, which probably accounts for most of the difference; that hasn't been tested.

Pairs at fixed thresholds:

| Threshold | Accuracy | False accept | False reject |
| ---: | ---: | ---: | ---: |
| 0.40 | 98.98% | 0.77% | 1.27% |
| 0.45 | 99.02% | 0.17% | 1.80% |
| 0.50 | 98.35% | 0.10% | 3.20% |
| 0.55 | 96.87% | 0.07% | 6.20% |
| 0.60 | 94.63% | 0.03% | 10.70% |
| 0.65 | 91.30% | 0.03% | 17.37% |
| 0.70 | 85.70% | 0.03% | 28.57% |
| 0.75 | 78.52% | 0.03% | 42.93% |
| 0.80 | 69.52% | 0.00% | 60.97% |
| 0.85 | 59.82% | 0.00% | 80.37% |
| 0.90 | 52.92% | 0.00% | 94.17% |

Kiosk, with 311 people enrolled:

| Threshold | Recognised | Wrong person | Not recognised | Stranger accepted |
| ---: | ---: | ---: | ---: | ---: |
| 0.40 | 99.59% | 0.39% | 0.03% | 87.77% |
| 0.45 | 99.51% | 0.36% | 0.13% | 70.01% |
| 0.50 | 99.41% | 0.28% | 0.31% | 47.04% |
| 0.55 | 99.28% | 0.13% | 0.59% | 24.09% |
| 0.60 | 98.81% | 0.03% | 1.16% | 10.90% |
| 0.65 | 97.98% | 0.03% | 1.99% | 4.36% |
| 0.70 | 95.56% | 0.03% | 4.42% | 1.40% |
| 0.75 | 90.18% | 0.03% | 9.79% | 0.48% |
| 0.80 | 77.70% | 0.03% | 22.27% | 0.11% |
| 0.85 | 54.70% | 0.00% | 45.30% | 0.04% |
| 0.90 | 21.47% | 0.00% | 78.53% | 0.00% |

The kiosk numbers are much higher than the pair numbers at the same threshold. Matching against the average of 5 photos is more reliable than matching one photo against another.

The face-selection step matters on LFW. A first run picked the largest face, as `/capture_face` does, and scored 96.20% on the pairs, because in some group photos the largest face isn't the person LFW labels. At a real kiosk the largest face is the right choice: it's the person standing closest to the camera.

## Choosing the threshold

Marking the wrong person present is worse than not recognising someone. A student who isn't recognised can still check in with the QR code, but a false match records attendance for someone who wasn't there. So the default is the lowest threshold that keeps false accepts at or below 0.1% in both tests. In the kiosk test, a false accept is a wrong-person match or an accepted stranger, counted over all 9,308 photos. On a 0.01 grid, that threshold is **0.79**:

| Threshold | Recognised | Wrong person | Stranger accepted | Kiosk false accepts | Pairs falsely accepted |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.70 (previous default) | 95.56% | 0.03% | 1.40% | 0.83% | 0.03% |
| 0.75 | 90.18% | 0.03% | 0.48% | 0.29% | 0.03% |
| **0.79 (default)** | **81.55%** | **0.03%** | **0.13%** | **0.09%** | **0.00%** |

Raising the threshold from 0.70 barely changes how often one enrolled student is mistaken for another. What it changes is strangers. At 0.70, about 1 in 70 people who weren't enrolled was accepted as someone who was. The cost is that 18% of single photos of enrolled people aren't recognised, against 4% at 0.70.

The kiosk sees a student over several keyframes, which gives them several chances to be recognised. A stranger also gets several chances, so the per-photo rates are the fair comparison.

Where every student in the building is enrolled, strangers are rare, and 0.75 is a reasonable setting if convenience matters more. The threshold is `FACE_MATCH_THRESHOLD`.

## Limits

- **LFW isn't a classroom.** Its photos are press photos of public figures: mostly frontal, sharp and well lit. A webcam in a classroom gives smaller, blurrier and worse-lit faces, so expect fewer recognitions at the same threshold.
- **LFW isn't demographically balanced.** Most of its people are adult men, and most are light-skinned. Error rates for people who are underrepresented may be higher, and this evaluation can't show that.
- **The class size here is 311.** With more students enrolled, wrong-person matches become more likely.
- **Enrollment here averages 5 photos taken on different occasions.** The real enrollment averages 5 webcam frames taken seconds apart, which vary much less.
- **The blink check isn't part of this test.** It runs in the browser and is checked by hand.

## Reproducing

```bash
make accuracy        # python scripts/evaluate_accuracy.py
```

The first run downloads about 180 MB into `data/lfw/` (ignored by git). Embedding all 13,233 photos took 23 minutes on this machine with 16 threads. The embeddings are cached in `data/lfw/embeddings.npz`, so later runs take seconds, and the full results are written to `data/lfw/results.json`. Run it with the laptop plugged in.
