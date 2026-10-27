import logging
from typing import Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MATCH_THRESHOLD: float = 0.70


def vectorized_matrix_match(
    query_emb: Optional[np.ndarray],
    rolls: Sequence[str],
    matrix: Optional[np.ndarray],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> Tuple[Optional[str], float]:
    """
    Hardware-accelerated BLAS matrix dot-product vector matching.

    Scores the query against every enrolled vector with one BLAS matrix-vector
    multiplication. Because all vectors are L2-normalised, each dot product is the
    cosine similarity.

    Args:
        query_emb: L2-normalized 1D NumPy array of shape (512,).
        rolls: Student roll numbers, one per matrix row.
        matrix: (N, 512) float32 matrix of L2-normalized enrolled vectors, or None.
        threshold: Minimum cosine score threshold for a valid identity match.

    Returns:
        Tuple of (matched_roll, confidence_score). If confidence < threshold or
        query/profiles are invalid, matched_roll is None.
    """
    if query_emb is None or matrix is None or len(rolls) == 0:
        return None, -1.0

    try:
        scores = np.dot(matrix, query_emb)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])

        if best_score >= threshold:
            return rolls[best_idx], best_score
        return None, best_score

    except Exception as e:
        logger.error(f"[VECTOR MATRIX MATCH ERROR]: {e}", exc_info=True)
        return None, -1.0
