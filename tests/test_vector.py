import numpy as np

from app.ai.comparator import vectorized_matrix_match


def test_vectorized_matrix_match_success():
    query = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    rolls = ["2026CSE001", "2026CSE002", "2026CSE003"]
    matrix = np.eye(3, dtype=np.float32)
    best_roll, best_score = vectorized_matrix_match(query, rolls, matrix, threshold=0.70)
    assert best_roll == "2026CSE002"
    assert abs(best_score - 1.0) < 1e-5


def test_vectorized_matrix_match_below_threshold():
    query = np.array([0.577, 0.577, 0.577], dtype=np.float32)
    rolls = ["2026CSE001", "2026CSE002"]
    matrix = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    best_roll, best_score = vectorized_matrix_match(query, rolls, matrix, threshold=0.90)
    assert best_roll is None
    assert best_score < 0.90


def test_vectorized_matrix_match_with_no_enrolled_faces():
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert vectorized_matrix_match(query, [], None) == (None, -1.0)
