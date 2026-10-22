"""
Mathematical vector utility functions for biometric similarity search.
"""

from typing import Sequence, Union

import numpy as np


def cosine_similarity(
    a: Union[np.ndarray, Sequence[float]],
    b: Union[np.ndarray, Sequence[float]]
) -> float:
    """
    Computes cosine similarity between two 1D vector representations.
    Includes an epsilon guard in the denominator to prevent division by zero.

    Args:
        a: First normalized vector array.
        b: Second normalized vector array.

    Returns:
        float: Cosine similarity score bounded in [-1.0, 1.0]. Returns 0.0 for zero-norm vectors.
    """
    a_arr = np.asarray(a, dtype=np.float32)
    b_arr = np.asarray(b, dtype=np.float32)

    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)

    if norm_a < 1e-8 or norm_b < 1e-8:
        return 0.0

    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))
