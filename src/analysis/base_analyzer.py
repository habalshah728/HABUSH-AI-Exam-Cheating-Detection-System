"""Abstract base class and indicator container for behaviour analyzers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from src.detection.tracker import TrackedPerson


@dataclass(frozen=True)
class AnalysisIndicator:
    """Result returned by a behaviour or interaction analyzer."""

    name: str
    detected: bool
    value: float
    detail: str
    person_id: int
    partner_id: Optional[int] = None


class Analyzer(ABC):
    """Abstract base class for per-person and inter-person behaviour analyzers."""

    @abstractmethod
    def analyse(
        self,
        person: TrackedPerson,
        frame: np.ndarray,
        timestamp_sec: float = 0.0,
        **context: Any,
    ) -> AnalysisIndicator:
        """Analyse a tracked person in the given frame and return an indicator."""

    def close(self) -> None:
        """Release any underlying model resources."""
