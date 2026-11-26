"""Unit tests for DatabaseManager and ReportGenerator."""

from pathlib import Path

import cv2
import numpy as np

from src.detection.tracker import TrackedPerson
from src.reporting.report_generator import ReportGenerator
from src.scoring.models import Event
from src.storage.database import DatabaseManager
from src.storage.evidence_saver import EvidenceSaver


def test_database_and_pdf_report_generation(tmp_path: Path):
    db = DatabaseManager(tmp_path / "test_sessions.db")
    session_id = db.create_session(
        mode="video",
        source_name="exam_hall_1.mp4",
        duration_sec=120.0,
        user_email="controller@habush.edu",
        campus="Islamabad Campus",
    )

    saver = EvidenceSaver(tmp_path / "evidence", cooldown_sec=0.0)
    frame = np.full((240, 320, 3), 180, dtype=np.uint8)
    shot1 = saver.save_screenshot(session_id, 1, "Phone visible for 3+ s", 15.0, frame)
    shot2 = saver.save_screenshot(session_id, 1, "Unusual hand movement", 22.0, frame)
    assert Path(shot1).exists() and Path(shot2).exists()

    db.save_persons(
        session_id,
        [TrackedPerson(track_id=1, bbox=(10, 10, 100, 200), confidence=0.9, first_seen=0.0, last_seen=120.0)],
    )
    ev1 = db.add_event(
        session_id,
        Event(
            timestamp_sec=15.0,
            wall_time="10:00:15",
            track_id=1,
            category="Phone visible for 3+ s",
            risk_score=40,
            risk_level="Medium",
            screenshot_path=shot1,
            notes="Test event 1",
        ),
    )
    ev2 = db.add_event(
        session_id,
        Event(
            timestamp_sec=22.0,
            wall_time="10:00:22",
            track_id=1,
            category="Unusual hand movement",
            risk_score=80,
            risk_level="High",
            screenshot_path=shot2,
            notes="Test event 2",
        ),
    )
    db.finalize_session(
        session_id=session_id,
        duration_sec=120.0,
        total_people=1,
        total_events=2,
        max_risk="High",
    )

    stats = db.get_dashboard_stats(user_email="controller@habush.edu")
    assert stats["videos_analysed"] == 1
    assert stats["monitoring_sessions"] == 1
    assert stats["suspicious_activities"] == 2
    assert stats["phone_detections"] == 1

    generator = ReportGenerator(
        db,
        reports_dir=tmp_path / "reports",
        evidence_dir=tmp_path / "evidence",
    )
    pdf_path = generator.generate(session_id)
    assert pdf_path.exists()
    pdf_bytes = pdf_path.read_bytes()
    assert len(pdf_bytes) > 3000
    # ReportLab embeds JPEG/Flate XObject images when screenshots are included.
    assert b"/Subtype /Image" in pdf_bytes

    # Delete high-risk event and verify parent session totals recalculate
    del_ev = db.delete_event(ev2)
    assert del_ev is not None
    assert del_ev["total_events"] == 1
    assert del_ev["max_risk"] == "Medium"
    assert db.get_event_with_owner(ev1) is not None

    # Delete session and verify cascade cleanup
    del_sess = db.delete_session(session_id)
    assert del_sess is not None
    assert db.get_session(session_id) is None
    assert db.get_session_events(session_id) == []
