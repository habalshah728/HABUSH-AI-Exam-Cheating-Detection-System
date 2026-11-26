"""Custom exception hierarchy for the Exam Cheating Detection System."""


class ExamMonitorError(Exception):
    """Base exception for all application-specific errors."""


class CameraNotFoundError(ExamMonitorError):
    """Raised when no webcam is detected or a requested camera index fails to open."""


class UnsupportedVideoFormatError(ExamMonitorError):
    """Raised when an uploaded or provided video file has an unsupported format."""


class ModelLoadError(ExamMonitorError):
    """Raised when YOLO or MediaPipe models fail to load or initialize."""


class DatabaseError(ExamMonitorError):
    """Raised when an SQLite database operation fails."""
