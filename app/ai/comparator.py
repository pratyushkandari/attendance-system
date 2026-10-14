import logging
from typing import List, Optional, Sequence, Tuple, Union
import numpy as np
from .face_utils import cosine_similarity

logger = logging.getLogger(__name__)

DEFAULT_MATCH_THRESHOLD: float = 0.70


def compare_embeddings(
    input_emb: Optional[Union[np.ndarray, List[float]]],
    stored_embeddings_list: Sequence[Optional[Union[np.ndarray, List[float]]]],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> Tuple[float, bool]:
    """
    Compare a query embedding vector against a sequence of candidate embeddings.

    Iterates over stored facial embeddings, computing pairwise cosine similarities,
    and returns the maximal score along with a boolean match classification.

    Args:
        input_emb: Query embedding vector, shape (512,) or convertible list.
        stored_embeddings_list: Sequence of candidate 512-D vectors.
        threshold: Minimum cosine similarity score required for positive match.

    Returns:
        Tuple of (best_score: float, is_match: bool). Returns (0.0, False)
        if query or candidates are empty.
    """
    if input_emb is None or not stored_embeddings_list:
        return 0.0, False

    best_score: float = -1.0
    for stored in stored_embeddings_list:
        if stored is None:
            continue
        score = cosine_similarity(input_emb, stored)
        if score > best_score:
            best_score = score

    return best_score, (best_score >= threshold)


def vectorized_matrix_match(
    query_emb: Optional[np.ndarray],
    student_profiles: Sequence[Tuple[str, np.ndarray]],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> Tuple[Optional[str], float]:
    """
    Hardware-accelerated BLAS matrix dot-product vector matching.

    Stacks candidate student vectors into an (N, 512) float32 matrix and computes
    single-call BLAS SGEMV matrix-vector multiplication against the query vector.
    Executes in O(N * D) time using CPU SIMD AVX2/AVX-512 instructions.

    Args:
        query_emb: L2-normalized 1D NumPy array of shape (512,).
        student_profiles: Sequence of (student_roll, 512d_numpy_vector) tuples.
        threshold: Minimum cosine score threshold for a valid identity match.

    Returns:
        Tuple of (matched_roll, confidence_score). If confidence < threshold or
        query/profiles are invalid, matched_roll is None.
    """
    if query_emb is None or not student_profiles:
        return None, -1.0

    try:
        rolls, embeddings_list = zip(*student_profiles)
        matrix = np.vstack(embeddings_list)  # Matrix shape: (N, 512)

        # High-speed SIMD matrix-vector dot product (BLAS C-level execution)
        scores = np.dot(matrix, query_emb)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])

        if best_score >= threshold:
            return rolls[best_idx], best_score
        return None, best_score

    except Exception as e:
        logger.error(f"[VECTOR MATRIX MATCH ERROR]: {e}", exc_info=True)
        return None, -1.0