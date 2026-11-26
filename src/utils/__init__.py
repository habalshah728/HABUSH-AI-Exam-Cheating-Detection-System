"""Utility modules: configuration, logging, and custom exceptions."""

from src.utils.config import AnalysisThresholds, AppConfig, BASE_DIR, RiskWeights
from src.utils.exceptions import (
    CameraNotFoundError,
    DatabaseError,
    ExamMonitorError,
    ModelLoadError,
    UnsupportedVideoFormatError,
)
from src.utils.logger import get_logger

__all__ = [
    "AnalysisThresholds",
    "AppConfig",
    "BASE_DIR",
    "CameraNotFoundError",
    "DatabaseError",
    "ExamMonitorError",
    "ModelLoadError",
    "RiskWeights",
    "UnsupportedVideoFormatError",
    "get_logger",
]
