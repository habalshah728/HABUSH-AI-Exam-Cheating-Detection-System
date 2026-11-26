"""Evidence screenshot saver with per-event cooldown deduplication."""

from pathlib import Path
import re

import cv2
import numpy as np

from src.utils.logger import get_logger

logger = get_logger(__name__)


class EvidenceSaver:
    """Saves annotated evidence screenshots to disk with cooldown protection."""

    def __init__(
        self,
        evidence_dir: Path | str = "evidence",
        cooldown_sec: float = 5.0,
    ) -> None:
        self._evidence_dir = Path(evidence_dir)
        self._evidence_dir.mkdir(parents=True, exist_ok=True)
        self._cooldown_sec = float(cooldown_sec)
        self._last_saved: dict[tuple[int, int, str], float] = {}

    def save_screenshot(
        self,
        session_id: int,
        track_id: int,
        category: str,
        timestamp_sec: float,
        frame: np.ndarray,
    ) -> str:
        """Save an evidence screenshot if outside the cooldown window.

        Returns:
            Relative/string path to the saved PNG file, or empty string if skipped.
        """
        if frame is None or frame.size == 0:
            return ""

        key = (session_id, track_id, category)
        last_t = self._last_saved.get(key, -999.0)
        if (timestamp_sec - last_t) < self._cooldown_sec:
            return ""

        session_dir = self._evidence_dir / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)

        safe_cat = re.sub(r"[^a-z0-9_]+", "_", category.lower()).strip("_")
        filename = f"p{track_id}_{safe_cat}_{int(timestamp_sec * 10):06d}.png"
        out_path = session_dir / filename

        ok = cv2.imwrite(str(out_path), frame)
        if not ok:
            logger.warning("Failed to write evidence screenshot: %s", out_path)
            return ""

        self._last_saved[key] = timestamp_sec
        return str(out_path)

    def save_session_snapshot(self, session_id: int, frame: np.ndarray) -> str:
        """Save one representative overview snapshot for a session if not already saved."""
        if frame is None or frame.size == 0:
            return ""
        session_dir = self._evidence_dir / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)
        out_path = session_dir / "session_snapshot.png"
        if out_path.exists():
            return str(out_path)
        if not cv2.imwrite(str(out_path), frame):
            logger.warning("Failed to write session snapshot: %s", out_path)
            return ""
        return str(out_path)
