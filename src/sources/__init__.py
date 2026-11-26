"""Frame source abstractions and concrete video/webcam providers."""

from src.sources.frame_source import FrameSource, VideoMetadata
from src.sources.video_source import VideoFileSource
from src.sources.webcam_source import CameraInfo, CameraManager, WebcamSource

__all__ = [
    "CameraInfo",
    "CameraManager",
    "FrameSource",
    "VideoFileSource",
    "VideoMetadata",
    "WebcamSource",
]
