"""Lip-movement analyzer for approximate talking/whispering detection."""

from collections import defaultdict, deque
from typing import Any, Optional

import cv2
import numpy as np

from src.analysis.base_analyzer import AnalysisIndicator, Analyzer
from src.detection.tracker import TrackedPerson
from src.utils.exceptions import ModelLoadError


class TalkingAnalyzer(Analyzer):
    """Detects repeated lip-opening oscillations using MediaPipe Face Mesh."""

    _UPPER_LIP = 13
    _LOWER_LIP = 14
    _LEFT_MOUTH = 61
    _RIGHT_MOUTH = 291

    def __init__(
        self,
        lip_open_ratio: float = 0.045,
        min_oscillations: int = 4,
        window_sec: float = 30.0,
        create_mesh: bool = True,
    ) -> None:
        self._lip_open_ratio = lip_open_ratio
        self._min_oscillations = min_oscillations
        self._window_sec = window_sec
        self._prev_open: dict[int, bool] = {}
        self._oscillation_times: dict[int, deque[float]] = defaultdict(deque)
        self._face_mesh = self._init_face_mesh() if create_mesh else None

    @staticmethod
    def _init_face_mesh():
        from src.analysis.mediapipe_models import create_face_landmarker

        return create_face_landmarker()

    def compute_mouth_ratio(self, landmarks) -> Optional[float]:
        """Compute normalized vertical-to-horizontal mouth opening ratio."""
        if landmarks is None:
            return None
        pts = landmarks.landmark if hasattr(landmarks, "landmark") else landmarks
        upper = pts[self._UPPER_LIP]
        lower = pts[self._LOWER_LIP]
        left = pts[self._LEFT_MOUTH]
        right = pts[self._RIGHT_MOUTH]

        vertical = float(np.hypot(upper.x - lower.x, upper.y - lower.y))
        horizontal = float(np.hypot(left.x - right.x, left.y - right.y))
        if horizontal <= 1e-6:
            return None
        return vertical / horizontal

    def analyse(
        self,
        person: TrackedPerson,
        frame: np.ndarray,
        timestamp_sec: float = 0.0,
        **context: Any,
    ) -> AnalysisIndicator:
        """Track lip-opening state transitions to flag possible talking."""
        x1, y1, x2, y2 = person.bbox
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return AnalysisIndicator(
                name="possible_talking",
                detected=False,
                value=0.0,
                detail="Empty person crop",
                person_id=person.track_id,
            )

        landmarks = context.get("face_landmarks")
        if landmarks is None and self._face_mesh is not None:
            import mediapipe as mp

            rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_crop)
            res = self._face_mesh.detect(mp_image)
            if res.face_landmarks:
                landmarks = res.face_landmarks[0]

        ratio = self.compute_mouth_ratio(landmarks)
        if ratio is not None:
            is_open = ratio >= self._lip_open_ratio
            was_open = self._prev_open.get(person.track_id, False)
            if is_open != was_open:
                self._oscillation_times[person.track_id].append(timestamp_sec)
            self._prev_open[person.track_id] = is_open

        history = self._oscillation_times[person.track_id]
        while history and (timestamp_sec - history[0]) > self._window_sec:
            history.popleft()

        changes = len(history)
        detected = changes >= self._min_oscillations
        return AnalysisIndicator(
            name="possible_talking",
            detected=detected,
            value=float(changes),
            detail=f"Lip movement transitions in 30s: {changes}",
            person_id=person.track_id,
        )

    def close(self) -> None:
        if self._face_mesh is not None:
            self._face_mesh.close()
            self._face_mesh = None
