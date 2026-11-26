"""Webcam frame source with background capture thread and camera discovery."""

from dataclasses import dataclass
import platform
import threading
import time
from typing import Optional

import cv2
import numpy as np

from src.sources.frame_source import FrameSource, VideoMetadata
from src.utils.exceptions import CameraNotFoundError
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CameraInfo:
    """Describes an available camera device."""

    index: int
    label: str
    width: int
    height: int
    fps: float


def _open_capture(index: int) -> cv2.VideoCapture:
    """Open a camera index using DirectShow on Windows for fast probing."""
    if platform.system() == "Windows":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap
        cap.release()
    return cv2.VideoCapture(index)


class CameraManager:
    """Discovers connected laptop or USB cameras."""

    @staticmethod
    def list_cameras(max_index: int = 5) -> list[CameraInfo]:
        """Scan camera indexes and return available devices.

        Args:
            max_index: Highest device index to probe (inclusive).

        Returns:
            List of :class:`CameraInfo` objects for working cameras.
        """
        cameras: list[CameraInfo] = []
        for idx in range(max_index + 1):
            cap = _open_capture(idx)
            if not cap.isOpened():
                cap.release()
                continue
            ret, _ = cap.read()
            if ret:
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
                fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
                label = (
                    f"Integrated Webcam (index {idx})"
                    if idx == 0
                    else f"USB / External Camera (index {idx})"
                )
                cameras.append(
                    CameraInfo(
                        index=idx,
                        label=label,
                        width=width,
                        height=height,
                        fps=fps if fps > 0 else 30.0,
                    )
                )
            cap.release()
        logger.info("Camera scan complete: found %d camera(s)", len(cameras))
        return cameras


class WebcamSource(FrameSource):
    """Threaded live webcam reader for low-latency frame delivery."""

    def __init__(self, camera_index: int = 0, width: int = 1280, height: int = 720) -> None:
        self._camera_index = camera_index
        self._requested_width = width
        self._requested_height = height
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_ret: bool = False
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time: float = 0.0
        self._actual_width: int = 0
        self._actual_height: int = 0
        self._actual_fps: float = 30.0

    def open(self) -> None:
        """Open the selected camera and start the background capture thread."""
        self._cap = _open_capture(self._camera_index)
        if not self._cap.isOpened():
            self._cap.release()
            self._cap = None
            raise CameraNotFoundError(
                f"No camera available at index {self._camera_index}. "
                "Check camera permissions or connect a USB webcam."
            )

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._requested_width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._requested_height)
        self._actual_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
        self._actual_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
        fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 30.0)
        self._actual_fps = fps if fps > 0 else 30.0

        ret, frame = self._cap.read()
        if not ret or frame is None:
            self.release()
            raise CameraNotFoundError(
                f"Camera index {self._camera_index} opened but failed to return a frame."
            )

        with self._lock:
            self._latest_ret = True
            self._latest_frame = frame

        self._start_time = time.monotonic()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Started webcam index %d (%dx%d)",
            self._camera_index,
            self._actual_width,
            self._actual_height,
        )

    def _capture_loop(self) -> None:
        """Continuously grab the newest frame in a background thread."""
        while self._running and self._cap is not None and self._cap.isOpened():
            ret, frame = self._cap.read()
            with self._lock:
                self._latest_ret = ret
                if ret and frame is not None:
                    self._latest_frame = frame
            time.sleep(0.005)

    def read(self) -> tuple[bool, Optional[np.ndarray], float]:
        """Return the latest captured webcam frame and elapsed timestamp."""
        if not self._running:
            return False, None, 0.0
        with self._lock:
            if not self._latest_ret or self._latest_frame is None:
                return False, None, 0.0
            frame_copy = self._latest_frame.copy()
        elapsed = time.monotonic() - self._start_time
        return True, frame_copy, elapsed

    def release(self) -> None:
        """Stop the background capture thread and release the camera."""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        logger.info("Released webcam index %d", self._camera_index)

    def is_opened(self) -> bool:
        """Return True if the webcam stream is active."""
        return self._running and self._cap is not None and self._cap.isOpened()

    def get_metadata(self) -> VideoMetadata:
        """Return live webcam resolution and nominal FPS."""
        return VideoMetadata(
            source_name=f"Webcam (index {self._camera_index})",
            width=self._actual_width,
            height=self._actual_height,
            fps=self._actual_fps,
            total_frames=0,
            duration_sec=0.0,
        )
