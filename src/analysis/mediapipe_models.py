"""MediaPipe Tasks model loader with automatic bundle download into ``models/``."""

from pathlib import Path
import urllib.request

from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from src.utils.exceptions import ModelLoadError
from src.utils.logger import get_logger

logger = get_logger(__name__)

_FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
_HAND_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)


def _ensure_model_file(path: Path, url: str) -> Path:
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading MediaPipe model '%s'...", path.name)
    try:
        urllib.request.urlretrieve(url, str(path))
        return path
    except Exception as exc:
        raise ModelLoadError(f"Failed to download '{path.name}': {exc}") from exc


def create_face_landmarker(
    models_dir: Path | str = "models",
) -> vision.FaceLandmarker:
    """Create a MediaPipe Tasks ``FaceLandmarker`` for person-crop analysis."""
    try:
        model_path = _ensure_model_file(
            Path(models_dir) / "face_landmarker.task", _FACE_LANDMARKER_URL
        )
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.45,
            min_face_presence_confidence=0.45,
            min_tracking_confidence=0.45,
        )
        return vision.FaceLandmarker.create_from_options(options)
    except ModelLoadError:
        raise
    except Exception as exc:
        raise ModelLoadError(f"Failed to initialize FaceLandmarker: {exc}") from exc


def create_hand_landmarker(
    models_dir: Path | str = "models",
) -> vision.HandLandmarker:
    """Create a MediaPipe Tasks ``HandLandmarker`` for person-crop analysis."""
    try:
        model_path = _ensure_model_file(
            Path(models_dir) / "hand_landmarker.task", _HAND_LANDMARKER_URL
        )
        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.45,
            min_hand_presence_confidence=0.45,
            min_tracking_confidence=0.45,
        )
        return vision.HandLandmarker.create_from_options(options)
    except ModelLoadError:
        raise
    except Exception as exc:
        raise ModelLoadError(f"Failed to initialize HandLandmarker: {exc}") from exc
