"""Data containers for events, risk assessments, and frame processing results."""

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from src.detection.detector import Detection
from src.detection.tracker import TrackedPerson


@dataclass(frozen=True)
class Event:
    """Represents a flagged suspicious-activity event for storage and reporting."""

    timestamp_sec: float
    wall_time: str
    track_id: int
    category: str
    risk_score: int
    risk_level: str
    screenshot_path: str = ""
    notes: str = ""


@dataclass(frozen=True)
class RiskAssessment:
    """Explainable risk score for a single person at a point in time."""

    track_id: int
    score: int
    level: str  # "Low", "Medium", "High"
    reasons: list[str] = field(default_factory=list)
    active_indicators: list[str] = field(default_factory=list)


@dataclass
class FrameResult:
    """Complete output of ``DetectionEngine.process_frame``."""

    timestamp_sec: float
    annotated_frame: np.ndarray
    persons: list[TrackedPerson]
    phones: list[Detection]
    assessments: dict[int, RiskAssessment]
    new_events: list[Event]
    total_unique_people: int
