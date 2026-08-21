import cv2
import numpy as np
import torch
from facenet_pytorch import MTCNN, InceptionResnetV1

# Optimize PyTorch CPU memory footprint for cloud containers
torch.set_grad_enabled(False)
torch.set_num_threads(1)

device = "cuda" if torch.cuda.is_available() else "cpu"

_mtcnn_instance = None
_resnet_instance = None


def get_mtcnn():
    """Lazy-loaded MTCNN singleton to minimize startup memory overhead."""
    global _mtcnn_instance
    if _mtcnn_instance is None:
        _mtcnn_instance = MTCNN(
            keep_all=True,
            min_face_size=20,
            thresholds=[0.6, 0.7, 0.7],
            device=device
        )
    return _mtcnn_instance


def get_resnet():
    """Lazy-loaded InceptionResnetV1 singleton in evaluation mode."""
    global _resnet_instance
    if _resnet_instance is None:
        _resnet_instance = InceptionResnetV1(pretrained="vggface2").eval().to(device)
    return _resnet_instance


# Backward-compatible proxy object
class MTCNNProxy:
    def detect(self, *args, **kwargs):
        return get_mtcnn().detect(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        return get_mtcnn()(*args, **kwargs)


mtcnn = MTCNNProxy()


def get_embedding_from_crop(face_bgr_crop):
    """
    Directly extracts 512-D embedding from a cropped face image.
    Uses zero-grad inference to keep memory under 150MB.
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
        print(f"[AI Model Error] get_embedding_from_crop failed: {e}")
        return None


def get_embedding(img_bgr):
    """
    Legacy wrapper that extracts embedding from a cropped face.
    """
    return get_embedding_from_crop(img_bgr)