"""Central shared AI detection, analysis, and risk-scoring engine."""

from contextlib import nullcontext
from datetime import datetime
import threading
from typing import Any, Optional

import cv2
import numpy as np

from src.analysis.base_analyzer import Analyzer
from src.analysis.hand import HandAnalyzer
from src.analysis.head_pose import HeadPoseAnalyzer
from src.analysis.interaction import InteractionAnalyzer
from src.analysis.talking import TalkingAnalyzer
from src.detection.detector import Detection, Detector, PersonPhoneDetector
from src.detection.tracker import PersonTracker, TrackedPerson
from src.scoring.models import Event, FrameResult, RiskAssessment
from src.scoring.risk_scorer import INDICATOR_LABELS, RiskScorer
from src.utils.config import AppConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _format_video_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hrs, rem = divmod(total, 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


class DetectionEngine:
    """Shared AI pipeline used identically by Video Upload and Live Webcam modes."""

    def __init__(
        self,
        config: AppConfig | None = None,
        detector: Detector | None = None,
        shared_yolo_model: Any = None,
        shared_face_mesh: Any = None,
        shared_hands: Any = None,
        infer_lock: Optional[threading.Lock] = None,
    ) -> None:
        self._config = config or AppConfig()
        self._infer_lock = infer_lock
        self._detector = detector or PersonPhoneDetector(
            model_path=self._config.models_dir / self._config.yolo_model_name,
            confidence=self._config.detection_confidence,
            imgsz=self._config.resize_width,
            yolo_model=shared_yolo_model,
        )
        self._tracker = PersonTracker()
        self._scorer = RiskScorer(
            weights=self._config.weights,
            window_sec=self._config.thresholds.sliding_window_sec,
        )
        self._processed_count: int = 0

        # Shared FaceMesh for CPU efficiency; HeadPose & Talking reuse its landmarks.
        self._owns_face_mesh = shared_face_mesh is None
        self._shared_face_mesh = (
            shared_face_mesh
            if shared_face_mesh is not None
            else self._init_shared_face_mesh()
        )
        self._head_pose = HeadPoseAnalyzer(
            yaw_threshold_deg=self._config.thresholds.side_look_yaw_deg,
            min_side_looks=self._config.thresholds.side_look_min_count,
            window_sec=self._config.thresholds.sliding_window_sec,
            look_cooldown_sec=self._config.thresholds.side_look_cooldown_sec,
            create_mesh=self._shared_face_mesh is None,
        )
        self._talking = TalkingAnalyzer(
            lip_open_ratio=self._config.thresholds.lip_open_ratio_threshold,
            min_oscillations=self._config.thresholds.lip_oscillation_min_count,
            window_sec=self._config.thresholds.sliding_window_sec,
            create_mesh=self._shared_face_mesh is None,
        )
        self._hand = HandAnalyzer(
            speed_threshold=self._config.thresholds.hand_speed_threshold,
            sustained_frames=self._config.thresholds.hand_sustained_frames,
            create_hands=shared_hands is None,
            hands=shared_hands,
        )
        self._interaction = InteractionAnalyzer(
            distance_ratio=self._config.thresholds.interaction_distance_ratio,
            min_duration_sec=self._config.thresholds.interaction_min_duration_sec,
        )
        self._analyzers: list[Analyzer] = [
            self._head_pose,
            self._talking,
            self._hand,
            self._interaction,
        ]
        self._last_alert_time: dict[tuple[int, str], float] = {}
        self._alert_cooldown_sec: float = self._config.thresholds.alert_cooldown_sec

    def _init_shared_face_mesh(self):
        try:
            from src.analysis.mediapipe_models import create_face_landmarker

            return create_face_landmarker(self._config.models_dir)
        except Exception as exc:
            logger.warning("Shared FaceLandmarker unavailable (%s); falling back.", exc)
            return None

    def set_confidence(self, confidence: float) -> None:
        """Update detector confidence threshold."""
        self._detector.set_confidence(confidence)

    def set_alert_cooldown(self, cooldown_sec: float) -> None:
        """Update per-(person, indicator) alert cooldown in seconds."""
        self._alert_cooldown_sec = max(1.0, float(cooldown_sec))

    def process_frame(self, frame: np.ndarray, timestamp_sec: float) -> FrameResult:
        """Run the 5-step AI pipeline on a single BGR frame."""
        resized = self._resize_for_cpu(frame)
        self._processed_count += 1
        lock_ctx = self._infer_lock if self._infer_lock is not None else nullcontext()
        with lock_ctx:
            detections = self._detector.detect(resized)
        persons, phones = self._tracker.update(detections, timestamp_sec)

        phone_duration = self._tracker.get_phone_visible_duration(timestamp_sec)
        phone_flagged = phone_duration >= self._config.thresholds.phone_min_duration_sec

        # Pass 1: Extract FaceMesh once per person crop and run per-person analyzers.
        yaw_map: dict[int, Optional[float]] = {}
        person_triggers: dict[int, list[tuple[str, str]]] = {
            p.track_id: [] for p in persons
        }

        for person in persons:
            face_landmarks = self._extract_face_landmarks(resized, person.bbox)

            head_ind = self._head_pose.analyse(
                person, resized, timestamp_sec, face_landmarks=face_landmarks
            )
            yaw_map[person.track_id] = self._head_pose.get_last_yaw(person.track_id)
            if head_ind.detected:
                person_triggers[person.track_id].append((head_ind.name, head_ind.detail))

            talk_ind = self._talking.analyse(
                person, resized, timestamp_sec, face_landmarks=face_landmarks
            )
            if talk_ind.detected:
                person_triggers[person.track_id].append((talk_ind.name, talk_ind.detail))

            # CPU optimization: run hand analysis every 2nd processed frame or when phones/cues appear.
            run_hand = (
                (self._processed_count % 2 == 1 and len(persons) <= 3)
                or len(phones) > 0
                or bool(person_triggers[person.track_id])
            )
            if run_hand:
                with lock_ctx:
                    hand_ind = self._hand.analyse(person, resized, timestamp_sec)
                if hand_ind.detected:
                    person_triggers[person.track_id].append((hand_ind.name, hand_ind.detail))

        # Pass 2: Inter-person interaction and phone-to-person association.
        for person in persons:
            inter_ind = self._interaction.analyse(
                person,
                resized,
                timestamp_sec,
                all_persons=persons,
                yaw_map=yaw_map,
            )
            if inter_ind.detected:
                person_triggers[person.track_id].append((inter_ind.name, inter_ind.detail))

        if phone_flagged and phones:
            for phone in phones:
                owner_id = self._find_closest_person_id(phone, persons)
                if owner_id is not None:
                    person_triggers[owner_id].append(
                        (
                            "phone_visible",
                            f"Mobile phone visible for {phone_duration:.1f}s",
                        )
                    )

        # Pass 3: Compute explainable risk scores and generate cooldown-filtered events.
        assessments: dict[int, RiskAssessment] = {}
        new_events: list[Event] = []
        wall_time = datetime.now().strftime("%H:%M:%S")

        for person in persons:
            triggers = person_triggers[person.track_id]
            assessment = self._scorer.update(person.track_id, triggers, timestamp_sec)
            assessments[person.track_id] = assessment

            for ind_key, detail in triggers:
                cooldown_key = (person.track_id, ind_key)
                last_t = self._last_alert_time.get(cooldown_key, -999.0)
                if timestamp_sec - last_t >= self._alert_cooldown_sec:
                    self._last_alert_time[cooldown_key] = timestamp_sec
                    new_events.append(
                        Event(
                            timestamp_sec=timestamp_sec,
                            wall_time=wall_time,
                            track_id=person.track_id,
                            category=INDICATOR_LABELS.get(ind_key, ind_key),
                            risk_score=assessment.score,
                            risk_level=assessment.level,
                            notes=f"{detail} | Time {_format_video_time(timestamp_sec)}",
                        )
                    )

        annotated = self._draw_annotations(resized, persons, phones, assessments)
        return FrameResult(
            timestamp_sec=timestamp_sec,
            annotated_frame=annotated,
            persons=persons,
            phones=phones,
            assessments=assessments,
            new_events=new_events,
            total_unique_people=self._tracker.total_unique_people,
        )

    def _resize_for_cpu(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        target_w = self._config.resize_width
        if w <= target_w:
            return frame.copy()
        scale = target_w / float(w)
        target_h = max(1, int(h * scale))
        return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)

    def _extract_face_landmarks(
        self, frame: np.ndarray, bbox: tuple[int, int, int, int]
    ):
        if self._shared_face_mesh is None:
            return None
        x1, y1, x2, y2 = bbox
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        ch, cw = crop.shape[:2]
        if ch < 36 or cw < 36:
            return None
        if max(ch, cw) > 320:
            scale = 320.0 / float(max(ch, cw))
            crop = cv2.resize(
                crop,
                (max(1, int(cw * scale)), max(1, int(ch * scale))),
                interpolation=cv2.INTER_AREA,
            )
        import mediapipe as mp

        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        lock_ctx = self._infer_lock if self._infer_lock is not None else nullcontext()
        with lock_ctx:
            res = self._shared_face_mesh.detect(mp_image)
        if res.face_landmarks:
            return res.face_landmarks[0]
        return None

    @staticmethod
    def _find_closest_person_id(
        phone: Detection, persons: list[TrackedPerson]
    ) -> Optional[int]:
        if not persons:
            return None
        px = (phone.bbox[0] + phone.bbox[2]) / 2.0
        py = (phone.bbox[1] + phone.bbox[3]) / 2.0
        best_id = persons[0].track_id
        best_dist = float("inf")
        for person in persons:
            cx = (person.bbox[0] + person.bbox[2]) / 2.0
            cy = (person.bbox[1] + person.bbox[3]) / 2.0
            dist = float(np.hypot(px - cx, py - cy))
            if dist < best_dist:
                best_dist = dist
                best_id = person.track_id
        return best_id

    @staticmethod
    def _draw_annotations(
        frame: np.ndarray,
        persons: list[TrackedPerson],
        phones: list[Detection],
        assessments: dict[int, RiskAssessment],
    ) -> np.ndarray:
        annotated = frame.copy()
        level_colors = {
            "Low": (46, 204, 113),     # Green
            "Medium": (0, 165, 255),   # Amber/Orange
            "High": (60, 76, 231),     # Red
        }

        for person in persons:
            x1, y1, x2, y2 = person.bbox
            assessment = assessments.get(person.track_id)
            level = assessment.level if assessment else "Low"
            score = assessment.score if assessment else 0
            color = level_colors.get(level, (46, 204, 113))

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = (
                f"Person {person.track_id} | Risk {score} ({level})"
                if score > 0
                else f"Person {person.track_id}"
            )
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(
                annotated,
                (x1, max(0, y1 - th - 8)),
                (x1 + tw + 8, y1),
                color,
                -1,
            )
            cv2.putText(
                annotated,
                label,
                (x1 + 4, max(12, y1 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

        for phone in phones:
            x1, y1, x2, y2 = phone.bbox
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 235), 2)
            cv2.putText(
                annotated,
                f"Phone {phone.confidence:.2f}",
                (x1, max(15, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 235),
                2,
                cv2.LINE_AA,
            )

        return annotated

    def get_tracked_persons(self) -> list[TrackedPerson]:
        """Return all unique tracked persons seen in this engine instance."""
        return self._tracker.get_all_persons()

    def close(self) -> None:
        """Release owned MediaPipe resources and reset stateful tracker."""
        self._detector.reset_tracker()
        if self._shared_face_mesh is not None and self._owns_face_mesh:
            self._shared_face_mesh.close()
        self._shared_face_mesh = None
        for analyzer in self._analyzers:
            analyzer.close()
