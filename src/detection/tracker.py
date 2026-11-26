"""Person tracking state and phone-visibility duration tracking."""

from dataclasses import dataclass
from typing import Optional

from src.detection.detector import Detection


@dataclass
class TrackedPerson:
    """Represents a tracked student across frames."""

    track_id: int
    bbox: tuple[int, int, int, int]
    confidence: float
    first_seen: float
    last_seen: float


class PersonTracker:
    """Maintains persistent person track IDs, lifetimes, and phone visibility."""

    def __init__(self, phone_reset_gap_sec: float = 1.5) -> None:
        self._persons: dict[int, TrackedPerson] = {}
        self._next_fallback_id: int = 1
        self._phone_first_seen: Optional[float] = None
        self._phone_last_seen: Optional[float] = None
        self._phone_reset_gap_sec = phone_reset_gap_sec

    def update(
        self, detections: list[Detection], timestamp_sec: float
    ) -> tuple[list[TrackedPerson], list[Detection]]:
        """Update tracked persons and phone detections for the current frame.

        Args:
            detections: Raw person and phone detections from :class:`Detector`.
            timestamp_sec: Current stream timestamp in seconds.

        Returns:
            Tuple of ``(active_persons, phone_detections)``.
        """
        active_persons: list[TrackedPerson] = []
        phones: list[Detection] = []

        for det in detections:
            if det.label == "cell phone":
                phones.append(det)
                continue

            if det.label != "person":
                continue

            track_id = det.track_id
            if track_id is None:
                track_id = self._match_or_assign_id(det.bbox, timestamp_sec)

            if track_id in self._persons:
                person = self._persons[track_id]
                person.bbox = det.bbox
                person.confidence = det.confidence
                person.last_seen = timestamp_sec
            else:
                person = TrackedPerson(
                    track_id=track_id,
                    bbox=det.bbox,
                    confidence=det.confidence,
                    first_seen=timestamp_sec,
                    last_seen=timestamp_sec,
                )
                self._persons[track_id] = person
            active_persons.append(person)

        self._update_phone_timer(len(phones) > 0, timestamp_sec)
        return active_persons, phones

    def _match_or_assign_id(
        self, bbox: tuple[int, int, int, int], timestamp_sec: float
    ) -> int:
        """Fallback IoU matcher if the detector did not supply a track ID."""
        best_id: Optional[int] = None
        best_iou = 0.30
        for tid, person in self._persons.items():
            if timestamp_sec - person.last_seen > 5.0:
                continue
            iou = self._compute_iou(bbox, person.bbox)
            if iou > best_iou:
                best_iou = iou
                best_id = tid
        if best_id is not None:
            return best_id

        while self._next_fallback_id in self._persons:
            self._next_fallback_id += 1
        assigned = self._next_fallback_id
        self._next_fallback_id += 1
        return assigned

    def _update_phone_timer(self, phone_present: bool, timestamp_sec: float) -> None:
        if phone_present:
            if (
                self._phone_first_seen is None
                or self._phone_last_seen is None
                or (timestamp_sec - self._phone_last_seen) > self._phone_reset_gap_sec
            ):
                self._phone_first_seen = timestamp_sec
            self._phone_last_seen = timestamp_sec
        elif (
            self._phone_last_seen is not None
            and (timestamp_sec - self._phone_last_seen) > self._phone_reset_gap_sec
        ):
            self._phone_first_seen = None
            self._phone_last_seen = None

    def get_phone_visible_duration(self, timestamp_sec: float) -> float:
        """Return continuous duration in seconds a phone has been visible."""
        if self._phone_first_seen is None or self._phone_last_seen is None:
            return 0.0
        if (timestamp_sec - self._phone_last_seen) > self._phone_reset_gap_sec:
            return 0.0
        return max(0.0, self._phone_last_seen - self._phone_first_seen)

    def get_all_persons(self) -> list[TrackedPerson]:
        """Return all unique persons seen during the session."""
        return list(self._persons.values())

    @property
    def total_unique_people(self) -> int:
        """Return the count of unique person track IDs seen so far."""
        return len(self._persons)

    @staticmethod
    def _compute_iou(
        box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]
    ) -> float:
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0, inter_x2 - inter_x1)
        inter_h = max(0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h
        if inter_area == 0:
            return 0.0
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter_area / float(area_a + area_b - inter_area)
