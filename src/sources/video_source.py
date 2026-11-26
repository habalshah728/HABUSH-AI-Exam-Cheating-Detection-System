"""Video file frame source implementation for MP4 and AVI recordings."""

from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from src.sources.frame_source import FrameSource, VideoMetadata
from src.utils.exceptions import UnsupportedVideoFormatError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class VideoFileSource(FrameSource):
    """Reads frames sequentially from an MP4 or AVI video file."""

    SUPPORTED_EXTENSIONS = (".mp4", ".avi")

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)
        self._validate_file()
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_index: int = 0
        self._fps: float = 25.0
        self._total_frames: int = 0
        self._width: int = 0
        self._height: int = 0

    def _validate_file(self) -> None:
        if not self._file_path.exists():
            raise UnsupportedVideoFormatError(
                f"Video file does not exist: {self._file_path}"
            )
        if self._file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise UnsupportedVideoFormatError(
                f"Unsupported video format '{self._file_path.suffix}'. "
                f"Supported formats: {', '.join(self.SUPPORTED_EXTENSIONS)}"
            )

    def open(self) -> None:
        """Open the video file using OpenCV."""
        self._cap = cv2.VideoCapture(str(self._file_path))
        if not self._cap.isOpened():
            raise UnsupportedVideoFormatError(
                f"Unable to decode video file: {self._file_path.name}"
            )
        self._fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 25.0)
        if self._fps <= 0:
            self._fps = 25.0
        self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self._frame_index = 0
        logger.info(
            "Opened video '%s' (%dx%d @ %.1f FPS, %d frames)",
            self._file_path.name,
            self._width,
            self._height,
            self._fps,
            self._total_frames,
        )

    def read(self) -> tuple[bool, Optional[np.ndarray], float]:
        """Read the next frame and compute its timestamp in seconds."""
        if self._cap is None or not self._cap.isOpened():
            return False, None, 0.0
        ret, frame = self._cap.read()
        if not ret or frame is None:
            return False, None, 0.0
        timestamp_sec = self._frame_index / self._fps
        self._frame_index += 1
        return True, frame, timestamp_sec

    def release(self) -> None:
        """Release the OpenCV VideoCapture handle."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("Released video '%s'", self._file_path.name)

    def is_opened(self) -> bool:
        """Return True if the video capture is currently open."""
        return self._cap is not None and self._cap.isOpened()

    def get_metadata(self) -> VideoMetadata:
        """Return video dimensions, FPS, frame count, and duration."""
        duration_sec = (
            self._total_frames / self._fps if self._fps > 0 and self._total_frames > 0 else 0.0
        )
        return VideoMetadata(
            source_name=self._file_path.name,
            width=self._width,
            height=self._height,
            fps=self._fps,
            total_frames=self._total_frames,
            duration_sec=duration_sec,
        )

    @property
    def current_frame_index(self) -> int:
        """Return the number of frames read so far."""
        return self._frame_index
