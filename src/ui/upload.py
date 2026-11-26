"""Upload Examination Video & Video Analysis page."""

from pathlib import Path
import time

import cv2
import pandas as pd
import streamlit as st

from src.reporting.report_generator import ReportGenerator
from src.scoring.engine import DetectionEngine
from src.scoring.session import MonitoringSession
from src.sources.video_source import VideoFileSource
from src.storage.database import DatabaseManager
from src.storage.evidence_saver import EvidenceSaver
from src.ui.styles import format_duration
from src.utils.config import AppConfig
from src.utils.exceptions import ExamMonitorError


def render_upload_page(
    config: AppConfig,
    db: DatabaseManager,
    report_gen: ReportGenerator,
) -> None:
    """Render the Video Upload and Analysis workflow."""
    st.title("Upload Examination Video")
    st.caption("Step 1: choose a recorded exam video (MP4 / AVI) • Step 2: start analysis")

    uploaded = st.file_uploader(
        "Drag and drop a video here",
        type=["mp4", "avi"],
        help="Supported formats: MP4 and AVI",
    )

    if uploaded is not None:
        config.uploads_dir.mkdir(parents=True, exist_ok=True)
        saved_path = config.uploads_dir / uploaded.name
        if (
            st.session_state.get("last_uploaded_name") != uploaded.name
            or not saved_path.exists()
        ):
            saved_path.write_bytes(uploaded.getbuffer())
            st.session_state["last_uploaded_name"] = uploaded.name
            st.session_state["last_uploaded_path"] = str(saved_path)

    video_path_str = st.session_state.get("last_uploaded_path")
    if not video_path_str or not Path(video_path_str).exists():
        st.info("Upload an MP4 or AVI file above to inspect metadata and run analysis.")
        return

    video_path = Path(video_path_str)
    try:
        probe = VideoFileSource(video_path)
        probe.open()
        meta = probe.get_metadata()
        probe.release()
    except ExamMonitorError as exc:
        st.error(str(exc))
        return

    size_mb = video_path.stat().st_size / (1024 * 1024)
    st.markdown(
        f"""
        <div class="kpi-card" style="margin-bottom:14px;">
            <div style="font-weight:700;color:#1B365D;font-size:1rem;">
                Selected file: {meta.source_name}
            </div>
            <div style="color:#475569;font-size:0.88rem;margin-top:4px;">
                Duration: <b>{format_duration(meta.duration_sec)}</b> &nbsp;|&nbsp;
                Resolution: <b>{meta.width} × {meta.height}</b> &nbsp;|&nbsp;
                <b>{meta.fps:.0f} FPS</b> &nbsp;|&nbsp;
                Size: <b>{size_mb:.1f} MB</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### Analysis settings")
    s1, s2, s3 = st.columns(3)
    with s1:
        frame_skip = st.slider(
            "Process every Nth frame",
            min_value=1,
            max_value=10,
            value=config.frame_skip,
            help="Higher N = faster on CPU but less detail. Default 3 is tuned for laptops.",
        )
    with s2:
        confidence = st.slider(
            "Detection confidence",
            min_value=0.20,
            max_value=0.85,
            value=float(config.detection_confidence),
            step=0.05,
        )
    with s3:
        cooldown = st.slider(
            "Alert cooldown (seconds)",
            min_value=1,
            max_value=15,
            value=int(config.thresholds.alert_cooldown_sec),
        )

    start_clicked = st.button("Start Analysis", type="primary")
    if start_clicked:
        _run_video_analysis(
            video_path=video_path,
            config=config,
            db=db,
            frame_skip=frame_skip,
            confidence=confidence,
            cooldown=float(cooldown),
        )

    last_sid = st.session_state.get("last_video_session_id")
    if last_sid is not None and not start_clicked:
        _render_completed_summary(db, report_gen, int(last_sid))


def _run_video_analysis(
    video_path: Path,
    config: AppConfig,
    db: DatabaseManager,
    frame_skip: int,
    confidence: float,
    cooldown: float,
) -> None:
    """Execute the shared DetectionEngine across the uploaded video with live UI updates."""
    st.markdown("---")
    st.subheader("Video Analysis")
    st.caption(f"{video_path.name} — processing with the shared AI engine")

    left_col, right_col = st.columns([2.2, 1])
    frame_placeholder = left_col.empty()
    progress_bar = right_col.progress(0.0, text="Initializing AI models...")
    stats_placeholder = right_col.empty()

    user_email = st.session_state.get("auth_user", {}).get("email", "")

    try:
        engine = DetectionEngine(config=config)
        engine.set_confidence(confidence)
        engine.set_alert_cooldown(cooldown)
        source = VideoFileSource(video_path)
        evidence_saver = EvidenceSaver(config.evidence_dir, cooldown_sec=cooldown)
        session = MonitoringSession(
            mode="video",
            source=source,
            engine=engine,
            db=db,
            evidence_saver=evidence_saver,
            frame_skip=frame_skip,
            user_email=user_email,
        )
    except ExamMonitorError as exc:
        st.error(f"Could not start analysis: {exc}")
        return

    def _on_frame(result, stats):
        rgb = cv2.cvtColor(result.annotated_frame, cv2.COLOR_BGR2RGB)
        frame_placeholder.image(
            rgb,
            caption=f"Time {format_duration(result.timestamp_sec)}",
            use_container_width=True,
        )
        pct = int(stats.progress_ratio * 100)
        progress_bar.progress(
            stats.progress_ratio,
            text=f"{pct}% — frame {stats.frames_read}",
        )
        stats_placeholder.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-label">Live Analysis Counters</div>
                <p style="margin:4px 0;">People detected: <b>{stats.total_people}</b></p>
                <p style="margin:4px 0;">Events flagged: <b>{stats.total_events}</b></p>
                <p style="margin:4px 0;">Phones found: <b>{stats.phones_found}</b></p>
                <p style="margin:4px 0;">Max risk: <b>{stats.max_risk}</b></p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    t0 = time.perf_counter()
    try:
        final_stats = session.run_all(on_result=_on_frame)
    finally:
        engine.close()

    elapsed = time.perf_counter() - t0
    progress_bar.progress(1.0, text=f"100% — Completed in {elapsed:.1f}s")
    st.session_state["last_video_session_id"] = final_stats.session_id
    st.success(
        f"Analysis complete! Flagged {final_stats.total_events} event(s) across "
        f"{final_stats.total_people} detected person(s)."
    )
    st.rerun()


def _render_completed_summary(
    db: DatabaseManager, report_gen: ReportGenerator, session_id: int
) -> None:
    """Render activity timeline, event list, and PDF download for the analysed video."""
    session = db.get_session(session_id)
    if session is None:
        return
    events = db.get_session_events(session_id)

    st.markdown("---")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Session", f"#{session_id}")
    c2.metric("People detected", session.get("total_people", 0))
    c3.metric("Events flagged", session.get("total_events", 0))
    c4.metric("Max risk", session.get("max_risk", "Low"))
    with c5:
        if st.button("Generate PDF Report", type="primary", use_container_width=True):
            pdf_path = report_gen.generate(session_id)
            st.session_state["ready_pdf_path"] = str(pdf_path)

    ready_pdf = st.session_state.get("ready_pdf_path")
    if ready_pdf and Path(ready_pdf).exists():
        st.download_button(
            label="Download PDF Report",
            data=Path(ready_pdf).read_bytes(),
            file_name=Path(ready_pdf).name,
            mime="application/pdf",
        )

    st.markdown("#### Activity timeline & Suspicious event list")
    if not events:
        st.info("No suspicious events were flagged in this video.")
        return

    df = pd.DataFrame(
        [
            {
                "Time": format_duration(float(e["timestamp_sec"])),
                "Seconds": round(float(e["timestamp_sec"]), 1),
                "Indicator": e["category"],
                "Student": f"Person {e['track_id']}",
                "Score": int(e["risk_score"]),
                "Risk": e["risk_level"],
            }
            for e in events
        ]
    )
    st.scatter_chart(
        df,
        x="Seconds",
        y="Score",
        color="Risk",
        use_container_width=True,
    )
    st.dataframe(
        df[["Time", "Indicator", "Student", "Score", "Risk"]],
        use_container_width=True,
        hide_index=True,
    )
