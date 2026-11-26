"""Explainable 30-second sliding-window risk scorer."""

from collections import defaultdict, deque

from src.scoring.models import RiskAssessment
from src.utils.config import RiskWeights


INDICATOR_LABELS = {
    "phone_visible": "Phone visible for 3+ s",
    "repeated_side_look": "Repeated side-looking",
    "possible_talking": "Possible talking",
    "close_interaction": "Close interaction",
    "unusual_hand_movement": "Unusual hand movement",
}


class RiskScorer:
    """Combines active indicators inside a 30-second sliding window."""

    def __init__(
        self,
        weights: RiskWeights | None = None,
        window_sec: float = 30.0,
    ) -> None:
        self._weights = weights or RiskWeights()
        self._window_sec = window_sec
        self._indicator_history: dict[int, dict[str, float]] = defaultdict(dict)
        self._weight_map = {
            "phone_visible": self._weights.phone_visible,
            "repeated_side_look": self._weights.repeated_side_look,
            "possible_talking": self._weights.possible_talking,
            "close_interaction": self._weights.close_interaction,
            "unusual_hand_movement": self._weights.unusual_hand_movement,
        }

    def update(
        self,
        track_id: int,
        triggered_indicators: list[tuple[str, str]],
        timestamp_sec: float,
    ) -> RiskAssessment:
        """Record newly triggered indicators and compute the current 30s risk score.

        Args:
            track_id: Tracked person ID.
            triggered_indicators: List of ``(indicator_key, human_detail)`` pairs.
            timestamp_sec: Current timestamp in seconds.

        Returns:
            :class:`RiskAssessment` with score (0-100), level, and explainable reasons.
        """
        history = self._indicator_history[track_id]
        for key, _ in triggered_indicators:
            if key in self._weight_map:
                history[key] = timestamp_sec

        # Prune indicators older than the 30-second sliding window.
        expired = [
            k for k, t in history.items() if (timestamp_sec - t) > self._window_sec
        ]
        for k in expired:
            del history[k]

        raw_score = sum(self._weight_map[k] for k in history)
        score = min(self._weights.max_score, raw_score)
        level = self._classify_level(score)

        active_keys = sorted(history.keys(), key=lambda k: self._weight_map[k], reverse=True)
        reasons = [
            f"{INDICATOR_LABELS.get(k, k)} (+{self._weight_map[k]})"
            for k in active_keys
        ]
        return RiskAssessment(
            track_id=track_id,
            score=score,
            level=level,
            reasons=reasons,
            active_indicators=active_keys,
        )

    def _classify_level(self, score: int) -> str:
        if score >= self._weights.high_threshold:
            return "High"
        if score >= self._weights.medium_threshold:
            return "Medium"
        return "Low"

    def reset(self) -> None:
        """Clear all sliding-window history."""
        self._indicator_history.clear()
