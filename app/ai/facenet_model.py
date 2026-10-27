import logging
import threading
from typing import Any

import cv2
import numpy as np
import torch
from facenet_pytorch import MTCNN, InceptionResnetV1

logger = logging.getLogger(__name__)

# Optimize PyTorch CPU memory footprint for cloud containers
torch.set_grad_enabled(False)
torch.set_num_threads(1)

device: str = "cuda" if torch.cuda.is_available() else "cpu"

_mtcnn_instance: MTCNN | None = None
_resnet_instance: InceptionResnetV1 | None = None

# Gunicorn runs several threads per worker. Without a lock, the first concurrent
# requests could each build their own model copy, doubling peak memory on small
# (512 MB) instances.
_model_init_lock = threading.Lock()


def get_mtcnn() -> MTCNN:
    """
    Lazy-loaded MTCNN singleton to minimize startup memory overhead.

    Configured with a 3-stage cascade threshold [0.6, 0.7, 0.7] and min_face_size=20.
    """
    global _mtcnn_instance
    if _mtcnn_instance is None:
        with _model_init_lock:
            if _mtcnn_instance is None:
                _mtcnn_instance = MTCNN(
                    keep_all=True,
                    min_face_size=20,
                    thresholds=[0.6, 0.7, 0.7],
                    device=device,
                )
    return _mtcnn_instance


def get_resnet() -> InceptionResnetV1:
    """
    Lazy-loaded InceptionResnetV1 singleton in strict evaluation mode.

    Loads VGGFace2 pretrained weights producing unit-sphere projected 512-D embeddings.
    """
    global _resnet_instance
    if _resnet_instance is None:
        with _model_init_lock:
            if _resnet_instance is None:
                _resnet_instance = InceptionResnetV1(pretrained="vggface2").eval().to(device)
    return _resnet_instance


class MTCNNProxy:
    """Lets routes call ``mtcnn.detect(...)`` while the model itself loads on first use."""

    def detect(self, *args: Any, **kwargs: Any) -> Any:
        return get_mtcnn().detect(*args, **kwargs)


mtcnn = MTCNNProxy()


def get_embedding_from_crop(face_bgr_crop: np.ndarray | None) -> np.ndarray | None:
    """
    Extract a normalized 512-D facial embedding vector directly from a cropped BGR image.

    Pipelines:
        1. BGR -> RGB color space conversion.
        2. Area-interpolated (cv2.INTER_AREA) resize to model input dimensions (160x160).
        3. Normalization to standard floating-point range [-1.0, 1.0].
        4. InceptionResnetV1 forward-pass under `torch.no_grad()`.
        5. L2-normalization to enforce unit hypersphere geometry.

    Args:
        face_bgr_crop: Cropped facial sub-image as a 3-channel BGR NumPy array.

    Returns:
        1D float32 NumPy array of shape (512,) with ||v||_2 = 1.0, or None if crop invalid.
    """
    try:
        if face_bgr_crop is None or face_bgr_crop.size == 0:
            return None

        # Convert BGR -> RGB and resize to FaceNet input size (160x160)
        rgb = cv2.cvtColor(face_bgr_crop, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (160, 160), interpolation=cv2.INTER_AREA)

        # Convert to float tensor (1, 3, 160, 160) and normalize [-1, 1]
        tensor = torch.from_numpy(resized).permute(2, 0, 1).float().unsqueeze(0).to(device)
        tensor = (tensor - 127.5) / 128.0

        model = get_resnet()
        with torch.no_grad():
            emb = model(tensor)

        emb_np = emb.detach().cpu().numpy()[0]

        # Normalize embedding vector to unit sphere
        norm = np.linalg.norm(emb_np)
        if norm > 1e-8:
            emb_np = emb_np / norm

        return emb_np

    except Exception as e:
        logger.error(f"[AI Model Error] get_embedding_from_crop failed: {e}", exc_info=True)
        return None
