import numpy as np

def cosine_similarity(a, b):
    """
    Computes cosine similarity between two 1D vectors.
    Includes epsilon in denominator to guard against zero-division.
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    
    if norm_a < 1e-8 or norm_b < 1e-8:
        return 0.0
        
    return float(np.dot(a, b) / (norm_a * norm_b))