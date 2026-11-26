"""Suspicious neighbour interaction analyzer."""

from typing import Any, Optional

import numpy as np

from src.analysis.base_analyzer import AnalysisIndicator, Analyzer
from src.detection.tracker import TrackedPerson


class InteractionAnalyzer(Analyzer):
    """Detects two neighbouring students staying close and turning towards each other."""

    def __init__(
        self,
        distance_ratio: float = 1.65,
        min_duration_sec: float = 3.0,
        reset_gap_sec: float = 1.5,
    ) -> None:
        self._distance_ratio = distance_ratio
        self._min_duration_sec = min_duration_sec
        self._reset_gap_sec = reset_gap_sec
        self._pair_start: dict[tuple[int, int], float] = {}
        self._pair_last: dict[tuple[int, int], float] = {}

    @staticmethod
    def _center_x(bbox: tuple[int, int, int, int]) -> float:
        return (bbox[0] + bbox[2]) / 2.0

    @staticmethod
    def _center_y(bbox: tuple[int, int, int, int]) -> float:
        return (bbox[1] + bbox[3]) / 2.0

    @staticmethod
    def _width(bbox: tuple[int, int, int, int]) -> float:
        return max(1.0, float(bbox[2] - bbox[0]))

    def analyse(
        self,
        person: TrackedPerson,
        frame: np.ndarray,
        timestamp_sec: float = 0.0,
        **context: Any,
    ) -> AnalysisIndicator:
        """Check whether ``person`` is interacting closely with any neighbour."""
        all_persons: list[TrackedPerson] = context.get("all_persons", [])
        yaw_map: dict[int, Optional[float]] = context.get("yaw_map", {})

        best_duration = 0.0
        best_partner: Optional[int] = None

        px = self._center_x(person.bbox)
        py = self._center_y(person.bbox)
        pw = self._width(person.bbox)

        for other in all_persons:
            if other.track_id == person.track_id:
                continue

            ox = self._center_x(other.bbox)
            oy = self._center_y(other.bbox)
            ow = self._width(other.bbox)
            avg_w = (pw + ow) / 2.0
            dist = float(np.hypot(px - ox, py - oy))

            close_enough = dist <= avg_w * self._distance_ratio
            facing_each_other = self._are_facing_each_other(
                px, ox, yaw_map.get(person.track_id), yaw_map.get(other.track_id)
            )

            pair_key = (
                min(person.track_id, other.track_id),
                max(person.track_id, other.track_id),
            )
            if close_enough and facing_each_other:
                last_t = self._pair_last.get(pair_key)
                if last_t is None or (timestamp_sec - last_t) > self._reset_gap_sec:
                    self._pair_start[pair_key] = timestamp_sec
                self._pair_last[pair_key] = timestamp_sec
                duration = timestamp_sec - self._pair_start[pair_key]
                if duration > best_duration:
                    best_duration = duration
                    best_partner = other.track_id
            elif (
                pair_key in self._pair_last
                and (timestamp_sec - self._pair_last[pair_key]) > self._reset_gap_sec
            ):
                self._pair_start.pop(pair_key, None)
                self._pair_last.pop(pair_key, None)

        detected = best_duration >= self._min_duration_sec
        detail = (
            f"Close interaction with Person {best_partner} for {best_duration:.1f}s"
            if best_partner is not None
            else "No suspicious neighbour interaction"
        )
        return AnalysisIndicator(
            name="close_interaction",
            detected=detected,
            value=best_duration,
            detail=detail,
            person_id=person.track_id,
            partner_id=best_partner,
        )

    @staticmethod
    def _are_facing_each_other(
        px: float,
        ox: float,
        p_yaw: Optional[float],
        o_yaw: Optional[float],
    ) -> bool:
        """Check if at least one person is turned towards the neighbour (or close)."""
        if p_yaw is None and o_yaw is None:
            return True
        if p_yaw is not None and o_yaw is not None:
            # If person is on the left (px < ox), turning right/towards has |yaw| >= 10.
            return abs(p_yaw) >= 10.0 or abs(o_yaw) >= 10.0
        return True
