"""Abstract base class and metadata container for frame input sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class VideoMetadata:
    """Metadata describing a video file or live camera stream."""

    source_name: str
    width: int
    height: int
    fps: float
    total_frames: int = 0
    duration_sec: float = 0.0


class FrameSource(ABC):
    """Abstract interface for video files and live webcams."""

    @abstractmethod
    def open(self) -> None:
        """Open the underlying video stream or camera device."""

    @abstractmethod
    def read(self) -> tuple[bool, Optional[np.ndarray], float]:
        """Read the next frame.

        Returns:
            Tuple of ``(success, frame_bgr, timestamp_sec)``.
        """

    @abstractmethod
    def release(self) -> None:
        """Release the underlying capture resources."""

    @abstractmethod
    def get_metadata(self) -> VideoMetadata:
        """Return stream metadata such as resolution, FPS, and duration."""

    @abstractmethod
    def is_opened(self) -> bool:
        """Return True if the source is currently open and ready."""

    def __enter__(self) -> "FrameSource":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
