"""Hand movement analyzer using MediaPipe Hands on person crops."""

from collections import defaultdict, deque
from typing import Any

import cv2
import numpy as np

from src.analysis.base_analyzer import AnalysisIndicator, Analyzer
from src.detection.tracker import TrackedPerson
from src.utils.exceptions import ModelLoadError


class HandAnalyzer(Analyzer):
    """Detects unusual or rapid hand movement within a person's bounding box."""

    def __init__(
        self,
        speed_threshold: float = 0.065,
        sustained_frames: int = 3,
        window_sec: float = 10.0,
        create_hands: bool = True,
        hands: Any = None,
    ) -> None:
        self._speed_threshold = speed_threshold
        self._sustained_frames = sustained_frames
        self._window_sec = window_sec
        self._prev_wrist: dict[int, tuple[float, float]] = {}
        self._fast_events: dict[int, deque[float]] = defaultdict(deque)
        self._owns_hands = hands is None
        if hands is not None:
            self._hands = hands
        else:
            self._hands = self._init_hands() if create_hands else None

    @staticmethod
    def _init_hands():
        from src.analysis.mediapipe_models import create_hand_landmarker

        return create_hand_landmarker()

    def analyse(
        self,
        person: TrackedPerson,
        frame: np.ndarray,
        timestamp_sec: float = 0.0,
        **context: Any,
    ) -> AnalysisIndicator:
        """Track wrist displacement across frames to flag unusual hand motion."""
        x1, y1, x2, y2 = person.bbox
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0 or self._hands is None:
            return AnalysisIndicator(
                name="unusual_hand_movement",
                detected=False,
                value=0.0,
                detail="No hand analysis available",
                person_id=person.track_id,
            )

        import mediapipe as mp

        ch, cw = crop.shape[:2]
        if max(ch, cw) > 320:
            scale = 320.0 / float(max(ch, cw))
            crop = cv2.resize(
                crop,
                (max(1, int(cw * scale)), max(1, int(ch * scale))),
                interpolation=cv2.INTER_AREA,
            )
        rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_crop)
        res = self._hands.detect(mp_image)

        max_disp = 0.0
        if res.hand_landmarks:
            # Track the primary wrist landmark (index 0) in normalized crop coords.
            wrist = res.hand_landmarks[0][0]
            curr_pos = (float(wrist.x), float(wrist.y))
            prev_pos = self._prev_wrist.get(person.track_id)
            if prev_pos is not None:
                max_disp = float(
                    np.hypot(curr_pos[0] - prev_pos[0], curr_pos[1] - prev_pos[1])
                )
                if max_disp >= self._speed_threshold:
                    self._fast_events[person.track_id].append(timestamp_sec)
            self._prev_wrist[person.track_id] = curr_pos

        history = self._fast_events[person.track_id]
        while history and (timestamp_sec - history[0]) > self._window_sec:
            history.popleft()

        detected = len(history) >= self._sustained_frames
        return AnalysisIndicator(
            name="unusual_hand_movement",
            detected=detected,
            value=max_disp,
            detail=f"Fast hand bursts: {len(history)} (last delta {max_disp:.3f})",
            person_id=person.track_id,
        )

    def close(self) -> None:
        if self._hands is not None and self._owns_hands:
            self._hands.close()
        self._hands = None
