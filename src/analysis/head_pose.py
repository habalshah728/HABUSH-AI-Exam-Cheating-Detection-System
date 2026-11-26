"""Head pose estimation (yaw) and repeated side-looking analyzer."""

from collections import defaultdict, deque
from typing import Any, Optional

import cv2
import numpy as np

from src.analysis.base_analyzer import AnalysisIndicator, Analyzer
from src.detection.tracker import TrackedPerson
from src.utils.exceptions import ModelLoadError
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Canonical 3D facial model points (in mm) for solvePnP head pose estimation.
_MODEL_POINTS_3D = np.array(
    [
        (0.0, 0.0, 0.0),          # Nose tip (1)
        (0.0, -330.0, -65.0),     # Chin (152)
        (-225.0, 170.0, -135.0),  # Left eye left corner (263)
        (225.0, 170.0, -135.0),   # Right eye right corner (33)
        (-150.0, -150.0, -125.0), # Left mouth corner (287)
        (150.0, -150.0, -125.0),  # Right mouth corner (57)
    ],
    dtype=np.float64,
)
_LANDMARK_IDS = (1, 152, 263, 33, 287, 57)


class HeadPoseAnalyzer(Analyzer):
    """Estimates head yaw with MediaPipe Face Mesh and OpenCV ``solvePnP``."""

    def __init__(
        self,
        yaw_threshold_deg: float = 22.0,
        min_side_looks: int = 3,
        window_sec: float = 30.0,
        look_cooldown_sec: float = 1.5,
        create_mesh: bool = True,
    ) -> None:
        self._yaw_threshold = yaw_threshold_deg
        self._min_side_looks = min_side_looks
        self._window_sec = window_sec
        self._look_cooldown_sec = look_cooldown_sec
        self._side_look_times: dict[int, deque[float]] = defaultdict(deque)
        self._last_look_event: dict[int, float] = {}
        self._last_yaw: dict[int, float] = {}
        self._face_mesh = self._init_face_mesh() if create_mesh else None

    @staticmethod
    def _init_face_mesh():
        from src.analysis.mediapipe_models import create_face_landmarker

        return create_face_landmarker()

    def estimate_yaw(
        self, landmarks, crop_width: int, crop_height: int
    ) -> Optional[float]:
        """Compute head yaw angle in degrees from MediaPipe face landmarks."""
        if landmarks is None or crop_width <= 0 or crop_height <= 0:
            return None

        pts = landmarks.landmark if hasattr(landmarks, "landmark") else landmarks
        image_points = np.array(
            [
                (
                    pts[idx].x * crop_width,
                    pts[idx].y * crop_height,
                )
                for idx in _LANDMARK_IDS
            ],
            dtype=np.float64,
        )

        focal_length = float(crop_width)
        center = (crop_width / 2.0, crop_height / 2.0)
        camera_matrix = np.array(
            [
                [focal_length, 0.0, center[0]],
                [0.0, focal_length, center[1]],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        dist_coeffs = np.zeros((4, 1), dtype=np.float64)

        success, rotation_vec, _ = cv2.solvePnP(
            _MODEL_POINTS_3D,
            image_points,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not success:
            return None

        rotation_mat, _ = cv2.Rodrigues(rotation_vec)
        angles, _, _, _, _, _ = cv2.RQDecomp3x3(rotation_mat)
        # angles[1] corresponds to yaw (left/right turn) in degrees.
        return float(angles[1])

    def analyse(
        self,
        person: TrackedPerson,
        frame: np.ndarray,
        timestamp_sec: float = 0.0,
        **context: Any,
    ) -> AnalysisIndicator:
        """Analyse head yaw and count repeated side-looks within the sliding window."""
        x1, y1, x2, y2 = person.bbox
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return AnalysisIndicator(
                name="repeated_side_look",
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

        yaw = self.estimate_yaw(landmarks, crop.shape[1], crop.shape[0])
        if yaw is not None:
            self._last_yaw[person.track_id] = yaw
            if abs(yaw) >= self._yaw_threshold:
                last_t = self._last_look_event.get(person.track_id, -999.0)
                if timestamp_sec - last_t >= self._look_cooldown_sec:
                    self._side_look_times[person.track_id].append(timestamp_sec)
                    self._last_look_event[person.track_id] = timestamp_sec

        history = self._side_look_times[person.track_id]
        while history and (timestamp_sec - history[0]) > self._window_sec:
            history.popleft()

        count = len(history)
        detected = count >= self._min_side_looks
        yaw_str = f"{yaw:+.1f} deg" if yaw is not None else "n/a"
        return AnalysisIndicator(
            name="repeated_side_look",
            detected=detected,
            value=float(count),
            detail=f"Side-looks in 30s: {count} (yaw {yaw_str})",
            person_id=person.track_id,
        )

    def get_last_yaw(self, track_id: int) -> Optional[float]:
        """Return the most recently estimated yaw angle in degrees for a person."""
        return self._last_yaw.get(track_id)

    def close(self) -> None:
        if self._face_mesh is not None:
            self._face_mesh.close()
            self._face_mesh = None
