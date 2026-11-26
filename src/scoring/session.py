"""MonitoringSession orchestrates a complete video or live monitoring run."""

from dataclasses import dataclass
from typing import Callable, Optional

from src.scoring.engine import DetectionEngine
from src.scoring.models import Event, FrameResult
from src.sources.frame_source import FrameSource, VideoMetadata
from src.storage.database import DatabaseManager
from src.storage.evidence_saver import EvidenceSaver
from src.utils.logger import get_logger

logger = get_logger(__name__)

_RISK_ORDER = {"Low": 0, "Medium": 1, "High": 2}


@dataclass
class SessionStats:
    """Live statistics for an active or completed monitoring session."""

    session_id: int
    frames_read: int = 0
    frames_processed: int = 0
    total_people: int = 0
    total_events: int = 0
    phones_found: int = 0
    max_risk: str = "Low"
    elapsed_sec: float = 0.0
    progress_ratio: float = 0.0


class MonitoringSession:
    """Connects a FrameSource, DetectionEngine, EvidenceSaver, and DatabaseManager."""

    def __init__(
        self,
        mode: str,
        source: FrameSource,
        engine: DetectionEngine,
        db: DatabaseManager,
        evidence_saver: EvidenceSaver,
        frame_skip: int = 3,
        user_email: str = "",
        campus: str = "",
    ) -> None:
        self._mode = mode
        self._source = source
        self._engine = engine
        self._db = db
        self._evidence_saver = evidence_saver
        self._frame_skip = max(1, int(frame_skip))
        self._user_email = user_email
        self._campus = campus
        self._session_id: Optional[int] = None
        self._metadata: Optional[VideoMetadata] = None
        self._stats: Optional[SessionStats] = None
        self._events: list[Event] = []
        self._running = False

    def start(self) -> int:
        """Open the frame source and create a database session record."""
        self._source.open()
        self._metadata = self._source.get_metadata()
        self._session_id = self._db.create_session(
            mode=self._mode,
            source_name=self._metadata.source_name,
            duration_sec=self._metadata.duration_sec,
            user_email=self._user_email,
            campus=self._campus,
        )
        self._stats = SessionStats(session_id=self._session_id)
        self._events = []
        self._running = True
        logger.info(
            "Started %s monitoring session %d for '%s'",
            self._mode,
            self._session_id,
            self._metadata.source_name,
        )
        return self._session_id

    def step(self) -> tuple[bool, Optional[FrameResult]]:
        """Read and optionally process the next frame.

        Returns:
            ``(has_more, frame_result_or_none)``. ``frame_result`` is ``None``
            when the frame is skipped for CPU optimization.
        """
        if not self._running or self._session_id is None or self._stats is None:
            return False, None

        ret, frame, timestamp_sec = self._source.read()
        if not ret or frame is None:
            return False, None

        self._stats.frames_read += 1
        self._stats.elapsed_sec = timestamp_sec
        if self._metadata and self._metadata.total_frames > 0:
            self._stats.progress_ratio = min(
                1.0, self._stats.frames_read / float(self._metadata.total_frames)
            )

        # Process frame 1 and every Nth frame thereafter.
        if (self._stats.frames_read - 1) % self._frame_skip != 0:
            return True, None

        result = self._engine.process_frame(frame, timestamp_sec)
        self._stats.frames_processed += 1
        if self._stats.frames_processed == 1:
            self._evidence_saver.save_session_snapshot(
                self._session_id, result.annotated_frame
            )
        self._stats.total_people = result.total_unique_people
        self._stats.phones_found = max(self._stats.phones_found, len(result.phones))

        for assessment in result.assessments.values():
            if _RISK_ORDER.get(assessment.level, 0) > _RISK_ORDER.get(
                self._stats.max_risk, 0
            ):
                self._stats.max_risk = assessment.level

        persisted_events: list[Event] = []
        for evt in result.new_events:
            shot_path = self._evidence_saver.save_screenshot(
                session_id=self._session_id,
                track_id=evt.track_id,
                category=evt.category,
                timestamp_sec=evt.timestamp_sec,
                frame=result.annotated_frame,
            )
            saved_evt = Event(
                timestamp_sec=evt.timestamp_sec,
                wall_time=evt.wall_time,
                track_id=evt.track_id,
                category=evt.category,
                risk_score=evt.risk_score,
                risk_level=evt.risk_level,
                screenshot_path=shot_path,
                notes=evt.notes,
            )
            self._db.add_event(self._session_id, saved_evt)
            self._events.append(saved_evt)
            persisted_events.append(saved_evt)

        result.new_events = persisted_events
        self._stats.total_events = len(self._events)
        return True, result

    def next_analyzed_step(self) -> tuple[bool, Optional[FrameResult]]:
        """Advance through skipped frames and return the next analyzed FrameResult."""
        while True:
            has_more, result = self.step()
            if not has_more:
                return False, None
            if result is not None:
                return True, result

    def run_all(
        self,
        on_result: Optional[Callable[[FrameResult, SessionStats], None]] = None,
    ) -> SessionStats:
        """Process an entire finite source (e.g. uploaded video) from start to finish."""
        self.start()
        try:
            while self._running:
                has_more, result = self.step()
                if not has_more:
                    break
                if result is not None and on_result is not None and self._stats is not None:
                    on_result(result, self._stats)
        finally:
            self.stop()
        assert self._stats is not None
        return self._stats

    def stop(self) -> Optional[SessionStats]:
        """Release the source and finalize session records in SQLite."""
        self._running = False
        self._source.release()
        if self._session_id is not None and self._stats is not None:
            persons = self._engine.get_tracked_persons()
            self._stats.total_people = max(self._stats.total_people, len(persons))
            duration = (
                self._metadata.duration_sec
                if self._metadata and self._metadata.duration_sec > 0
                else self._stats.elapsed_sec
            )
            self._db.save_persons(self._session_id, persons)
            self._db.finalize_session(
                session_id=self._session_id,
                duration_sec=duration,
                total_people=self._stats.total_people,
                total_events=self._stats.total_events,
                max_risk=self._stats.max_risk,
            )
            logger.info(
                "Finalized session %d: people=%d, events=%d, max_risk=%s",
                self._session_id,
                self._stats.total_people,
                self._stats.total_events,
                self._stats.max_risk,
            )
        return self._stats

    @property
    def stats(self) -> Optional[SessionStats]:
        return self._stats

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    @property
    def metadata(self) -> Optional[VideoMetadata]:
        return self._metadata
