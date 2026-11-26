"""Object detector abstraction and YOLOv8 implementation for persons and phones."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from src.utils.exceptions import ModelLoadError
from src.utils.logger import get_logger

logger = get_logger(__name__)

PERSON_CLASS_ID = 0
CELL_PHONE_CLASS_ID = 67


@dataclass(frozen=True)
class Detection:
    """Represents a single detected object in a video frame."""

    label: str
    confidence: float
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    track_id: Optional[int] = None


class Detector(ABC):
    """Abstract base class for object detectors."""

    @abstractmethod
    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Run object detection on a BGR frame."""

    @abstractmethod
    def set_confidence(self, confidence: float) -> None:
        """Update the minimum detection confidence threshold."""


class PersonPhoneDetector(Detector):
    """YOLOv8-based detector for ``person`` and ``cell phone`` classes with ByteTrack."""

    CLASS_NAMES = {
        PERSON_CLASS_ID: "person",
        CELL_PHONE_CLASS_ID: "cell phone",
    }

    def __init__(
        self,
        model_path: Path | str = "models/yolov8n.pt",
        confidence: float = 0.40,
        imgsz: int = 640,
        use_tracking: bool = True,
    ) -> None:
        self._model_path = Path(model_path)
        self._confidence = float(confidence)
        self._imgsz = int(imgsz)
        self._use_tracking = use_tracking
        self._model = self._load_model()

    def _load_model(self):
        """Load the Ultralytics YOLOv8 model, raising ModelLoadError on failure."""
        try:
            from ultralytics import YOLO

            self._model_path.parent.mkdir(parents=True, exist_ok=True)
            model_ref = (
                str(self._model_path)
                if self._model_path.exists()
                else self._model_path.name
            )
            model = YOLO(model_ref)
            if not self._model_path.exists():
                downloaded = Path(self._model_path.name)
                if downloaded.exists():
                    downloaded.replace(self._model_path)
            logger.info("Loaded YOLOv8 model from '%s'", self._model_path)
            return model
        except Exception as exc:
            raise ModelLoadError(
                f"Failed to load YOLOv8 model '{self._model_path}': {exc}"
            ) from exc

    def set_confidence(self, confidence: float) -> None:
        """Set detection confidence threshold clamped to [0.1, 0.95]."""
        self._confidence = max(0.1, min(0.95, float(confidence)))

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Detect persons and mobile phones in a BGR frame."""
        if frame is None or frame.size == 0:
            return []

        classes = [PERSON_CLASS_ID, CELL_PHONE_CLASS_ID]
        if self._use_tracking:
            results = self._model.track(
                frame,
                persist=True,
                tracker="bytetrack.yaml",
                classes=classes,
                conf=self._confidence,
                imgsz=self._imgsz,
                verbose=False,
            )
        else:
            results = self._model.predict(
                frame,
                classes=classes,
                conf=self._confidence,
                imgsz=self._imgsz,
                verbose=False,
            )

        detections: list[Detection] = []
        if not results:
            return detections

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return detections

        xyxy_list = boxes.xyxy.cpu().numpy()
        conf_list = boxes.conf.cpu().numpy()
        cls_list = boxes.cls.cpu().numpy().astype(int)
        id_list = (
            boxes.id.cpu().numpy().astype(int)
            if boxes.id is not None
            else [None] * len(xyxy_list)
        )

        h, w = frame.shape[:2]
        for coords, conf, cls_id, track_id in zip(
            xyxy_list, conf_list, cls_list, id_list
        ):
            label = self.CLASS_NAMES.get(int(cls_id))
            if label is None:
                continue
            x1 = max(0, min(w - 1, int(coords[0])))
            y1 = max(0, min(h - 1, int(coords[1])))
            x2 = max(x1 + 1, min(w, int(coords[2])))
            y2 = max(y1 + 1, min(h, int(coords[3])))
            detections.append(
                Detection(
                    label=label,
                    confidence=float(conf),
                    bbox=(x1, y1, x2, y2),
                    track_id=int(track_id) if track_id is not None else None,
                )
            )
        return detections
