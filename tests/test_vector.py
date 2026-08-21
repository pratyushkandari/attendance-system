import numpy as np
import pytest
from app.ai.face_utils import cosine_similarity
from app.ai.comparator import compare_embeddings, vectorized_matrix_match


def test_cosine_similarity_identical():
    v1 = np.array([1.0, 2.0, 3.0])
    v2 = np.array([1.0, 2.0, 3.0])
    sim = cosine_similarity(v1, v2)
    assert abs(sim - 1.0) < 1e-5


def test_cosine_similarity_orthogonal():
    v1 = np.array([1.0, 0.0, 0.0])
    v2 = np.array([0.0, 1.0, 0.0])
    sim = cosine_similarity(v1, v2)
    assert abs(sim - 0.0) < 1e-5


def test_cosine_similarity_zero_vector():
    v1 = np.array([0.0, 0.0, 0.0])
    v2 = np.array([1.0, 2.0, 3.0])
    sim = cosine_similarity(v1, v2)
    assert sim == 0.0  # Must not raise ZeroDivisionError


def test_compare_embeddings_match():
    query = np.array([0.5, 0.5, 0.5])
    stored_db = [
        np.array([0.5, 0.5, 0.5]),
        np.array([0.1, 0.9, 0.2]),
        np.array([0.9, 0.1, 0.1])
    ]
    score, is_match = compare_embeddings(query, stored_db, threshold=0.70)
    assert is_match is True
    assert abs(score - 1.0) < 1e-5


def test_compare_embeddings_no_match():
    query = np.array([1.0, 0.0, 0.0])
    stored_db = [
        np.array([0.0, 1.0, 0.0]),
        np.array([0.0, 0.0, 1.0])
    ]
    score, is_match = compare_embeddings(query, stored_db, threshold=0.70)
    assert is_match is False
    assert score < 0.70


def test_vectorized_matrix_match_success():
    query = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    student_profiles = [
        ("2026CSE001", np.array([1.0, 0.0, 0.0], dtype=np.float32)),
        ("2026CSE002", np.array([0.0, 1.0, 0.0], dtype=np.float32)),
        ("2026CSE003", np.array([0.0, 0.0, 1.0], dtype=np.float32))
    ]
    best_roll, best_score = vectorized_matrix_match(query, student_profiles, threshold=0.70)
    assert best_roll == "2026CSE002"
    assert abs(best_score - 1.0) < 1e-5


def test_vectorized_matrix_match_below_threshold():
    query = np.array([0.577, 0.577, 0.577], dtype=np.float32)
    student_profiles = [
        ("2026CSE001", np.array([1.0, 0.0, 0.0], dtype=np.float32)),
        ("2026CSE002", np.array([0.0, 1.0, 0.0], dtype=np.float32))
    ]
    best_roll, best_score = vectorized_matrix_match(query, student_profiles, threshold=0.90)
    assert best_roll is None
    assert best_score < 0.90
