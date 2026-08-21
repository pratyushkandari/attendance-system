import cv2
import numpy as np
import torch
from facenet_pytorch import MTCNN, InceptionResnetV1

device = "cuda" if torch.cuda.is_available() else "cpu"

# MTCNN initialized once for the app
mtcnn = MTCNN(
    keep_all=True,
    min_face_size=20,
    thresholds=[0.6, 0.7, 0.7],
    device=device
)

# InceptionResnetV1 pretrained on VGGFace2
resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)


def get_embedding_from_crop(face_bgr_crop):
    """
    Directly extracts 512-D embedding from an already cropped face image.
    Avoids re-running MTCNN a second time on a tight crop.
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

        with torch.no_grad():
            emb = resnet(tensor)
            
        emb_np = emb.detach().cpu().numpy()[0]
        # Normalize embedding vector
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