import numpy as np
from .face_utils import cosine_similarity

DEFAULT_MATCH_THRESHOLD = 0.70


def compare_embeddings(input_emb, stored_embeddings_list, threshold=DEFAULT_MATCH_THRESHOLD):
    """
    Compares an input embedding against a list of stored embeddings.
    Returns: (best_score, is_match)
    """
    if input_emb is None or not stored_embeddings_list:
        return 0.0, False

    best_score = -1.0
    for stored in stored_embeddings_list:
        if stored is None:
            continue
        score = cosine_similarity(input_emb, stored)
        if score > best_score:
            best_score = score

    return best_score, (best_score >= threshold)


def vectorized_matrix_match(query_emb, student_profiles, threshold=DEFAULT_MATCH_THRESHOLD):
    """
    Hardware-accelerated BLAS matrix dot product matching.
    student_profiles: List of tuples (roll, embedding_1d_numpy_array)
    Returns: (best_match_roll, best_score)
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
        print(f"[VECTOR MATRIX MATCH ERROR]: {e}")
        return None, -1.0