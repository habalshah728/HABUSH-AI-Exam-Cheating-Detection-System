"""Unit tests for FrameSource implementations."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from src.sources.video_source import VideoFileSource
from src.sources.webcam_source import WebcamSource
from src.utils.exceptions import CameraNotFoundError, UnsupportedVideoFormatError


def test_video_file_source_reads_synthetic_mp4(tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10.0,
        (320, 240),
    )
    for idx in range(5):
        frame = np.full((240, 320, 3), idx * 40, dtype=np.uint8)
        writer.write(frame)
    writer.release()

    with VideoFileSource(video_path) as src:
        meta = src.get_metadata()
        assert meta.width == 320
        assert meta.height == 240
        assert meta.total_frames == 5

        frames_read = 0
        while True:
            ok, frame, _ = src.read()
            if not ok:
                break
            assert frame is not None
            frames_read += 1
        assert frames_read == 5


def test_unsupported_video_format_raises(tmp_path: Path):
    bad_file = tmp_path / "notes.txt"
    bad_file.write_text("not a video", encoding="utf-8")
    with pytest.raises(UnsupportedVideoFormatError):
        VideoFileSource(bad_file)


def test_invalid_camera_index_raises():
    cam = WebcamSource(camera_index=99)
    with pytest.raises(CameraNotFoundError):
        cam.open()
