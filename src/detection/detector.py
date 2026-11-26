"""Object detector abstraction and YOLOv8 implementation for persons and phones."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv2
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

    def reset_tracker(self) -> None:
        """Reset any stateful multi-frame tracker between independent sessions."""


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
        yolo_model: Any = None,
    ) -> None:
        self._model_path = Path(model_path)
        self._confidence = float(confidence)
        self._imgsz = int(imgsz)
        self._use_tracking = use_tracking
        if yolo_model is not None:
            self._model = yolo_model
            self._backend = (
                "onnx_dnn" if isinstance(yolo_model, cv2.dnn.Net) else "ultralytics"
            )
        else:
            self._model, self._backend = self._load_model()

    def reset_tracker(self) -> None:
        """Reset Ultralytics ByteTrack state without reloading YOLO weights."""
        if self._backend != "ultralytics":
            return
        predictor = getattr(self._model, "predictor", None)
        if predictor is None:
            return
        trackers = getattr(predictor, "trackers", None)
        if trackers:
            for tracker in trackers:
                if hasattr(tracker, "reset"):
                    tracker.reset()

    def _load_model(self) -> tuple[Any, str]:
        """Prefer lightweight OpenCV ONNX DNN when available, else Ultralytics YOLO."""
        onnx_path = (
            self._model_path
            if self._model_path.suffix.lower() == ".onnx"
            else self._model_path.with_suffix(".onnx")
        )
        if onnx_path.exists() and onnx_path.stat().st_size > 0:
            try:
                net = cv2.dnn.readNetFromONNX(str(onnx_path))
                logger.info("Loaded YOLOv8 ONNX model via OpenCV DNN from '%s'", onnx_path)
                return net, "onnx_dnn"
            except Exception as exc:
                logger.warning(
                    "OpenCV DNN load failed for '%s' (%s); falling back to PyTorch YOLO.",
                    onnx_path,
                    exc,
                )

        try:
            import torch
            from ultralytics import YOLO

            torch.set_num_threads(2)
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
            return model, "ultralytics"
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
        if self._backend == "onnx_dnn":
            return self._detect_onnx_dnn(frame)
        return self._detect_ultralytics(frame)

    def _detect_onnx_dnn(self, frame: np.ndarray) -> list[Detection]:
        """Run memory-efficient YOLOv8n inference via OpenCV DNN ONNX (no PyTorch)."""
        h, w = frame.shape[:2]
        input_size = 640
        scale = min(input_size / float(w), input_size / float(h))
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        dw = (input_size - nw) // 2
        dh = (input_size - nh) // 2

        canvas = np.full((input_size, input_size, 3), 114, dtype=np.uint8)
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas[dh : dh + nh, dw : dw + nw] = resized

        blob = cv2.dnn.blobFromImage(
            canvas, 1.0 / 255.0, (input_size, input_size), swapRB=True, crop=False
        )
        self._model.setInput(blob)
        out = self._model.forward()
        preds = out[0].T  # (8400, 84) -> [cx, cy, bw, bh, cls0..cls79]

        p_scores = preds[:, 4 + PERSON_CLASS_ID]
        ph_scores = preds[:, 4 + CELL_PHONE_CLASS_ID]
        mask = (p_scores >= self._confidence) | (ph_scores >= self._confidence)
        if not np.any(mask):
            return []

        cand = preds[mask]
        detections: list[Detection] = []
        for cls_id, label in self.CLASS_NAMES.items():
            scores = cand[:, 4 + cls_id]
            cls_mask = scores >= self._confidence
            if not np.any(cls_mask):
                continue

            sub = cand[cls_mask]
            sub_scores = scores[cls_mask]
            # Require target class to beat unrelated classes unless it's high confidence cell phone.
            best_all = np.argmax(sub[:, 4:], axis=1)
            boxes_xywh: list[list[int]] = []
            confs: list[float] = []
            for row, sc, best_cls in zip(sub, sub_scores, best_all):
                if int(best_cls) != cls_id and not (
                    cls_id == CELL_PHONE_CLASS_ID and float(sc) >= max(self._confidence, 0.42)
                ):
                    continue
                cx, cy, bw, bh = float(row[0]), float(row[1]), float(row[2]), float(row[3])
                x1 = int(round((cx - bw / 2.0 - dw) / scale))
                y1 = int(round((cy - bh / 2.0 - dh) / scale))
                bw_orig = max(1, int(round(bw / scale)))
                bh_orig = max(1, int(round(bh / scale)))
                x1 = max(0, min(w - 1, x1))
                y1 = max(0, min(h - 1, y1))
                boxes_xywh.append([x1, y1, bw_orig, bh_orig])
                confs.append(float(sc))

            if not boxes_xywh:
                continue
            indices = cv2.dnn.NMSBoxes(boxes_xywh, confs, self._confidence, 0.45)
            if len(indices) == 0:
                continue
            for idx in np.array(indices).flatten():
                bx, by, bw_box, bh_box = boxes_xywh[int(idx)]
                x2 = max(bx + 1, min(w, bx + bw_box))
                y2 = max(by + 1, min(h, by + bh_box))
                detections.append(
                    Detection(
                        label=label,
                        confidence=confs[int(idx)],
                        bbox=(bx, by, x2, y2),
                        track_id=None,
                    )
                )
        return detections

    def _detect_ultralytics(self, frame: np.ndarray) -> list[Detection]:
        import torch

        classes = [PERSON_CLASS_ID, CELL_PHONE_CLASS_ID]
        with torch.inference_mode():
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
