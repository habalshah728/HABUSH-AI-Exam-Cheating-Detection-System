"""Configuration dataclasses and default constants for the system."""

from dataclasses import dataclass, field
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class RiskWeights:
    """Configurable weights for the 30-second sliding-window risk scorer."""

    phone_visible: int = 40
    repeated_side_look: int = 25
    possible_talking: int = 15
    close_interaction: int = 15
    unusual_hand_movement: int = 10
    max_score: int = 100
    medium_threshold: int = 30
    high_threshold: int = 60


@dataclass(frozen=True)
class AnalysisThresholds:
    """Thresholds for behaviour and interaction rules."""

    sliding_window_sec: float = 30.0
    phone_min_duration_sec: float = 3.0
    side_look_yaw_deg: float = 22.0
    side_look_min_count: int = 3
    side_look_cooldown_sec: float = 1.5
    lip_open_ratio_threshold: float = 0.045
    lip_oscillation_min_count: int = 4
    hand_speed_threshold: float = 0.065
    hand_sustained_frames: int = 3
    interaction_distance_ratio: float = 1.65
    interaction_min_duration_sec: float = 3.0
    alert_cooldown_sec: float = 5.0


@dataclass
class AppConfig:
    """Top-level application paths and runtime defaults."""

    data_dir: Path = field(default_factory=lambda: BASE_DIR / "data")
    uploads_dir: Path = field(default_factory=lambda: BASE_DIR / "data" / "uploads")
    db_path: Path = field(default_factory=lambda: BASE_DIR / "data" / "sessions.db")
    evidence_dir: Path = field(default_factory=lambda: BASE_DIR / "evidence")
    reports_dir: Path = field(default_factory=lambda: BASE_DIR / "reports")
    models_dir: Path = field(default_factory=lambda: BASE_DIR / "models")
    yolo_model_name: str = "yolov8n.pt"
    resize_width: int = 640
    frame_skip: int = 4
    detection_confidence: float = 0.40
    supported_video_extensions: tuple[str, ...] = (".mp4", ".avi")
    weights: RiskWeights = field(default_factory=RiskWeights)
    thresholds: AnalysisThresholds = field(default_factory=AnalysisThresholds)

    def ensure_directories(self) -> None:
        """Create required runtime directories if they do not exist."""
        for directory in (
            self.data_dir,
            self.uploads_dir,
            self.evidence_dir,
            self.reports_dir,
            self.models_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
