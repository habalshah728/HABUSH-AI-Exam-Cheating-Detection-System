"""Live Webcam Monitoring page with automatic camera discovery and real-time alerts."""

import time

import cv2
import streamlit as st

from src.scoring.engine import DetectionEngine
from src.scoring.session import MonitoringSession
from src.sources.webcam_source import CameraManager, WebcamSource
from src.storage.database import DatabaseManager
from src.storage.evidence_saver import EvidenceSaver
from src.ui.styles import format_duration
from src.utils.config import AppConfig
from src.utils.exceptions import ExamMonitorError


def render_live_page(config: AppConfig, db: DatabaseManager) -> None:
    """Render the Live Webcam Monitoring page."""
    st.title("Live Webcam Monitoring")
    st.caption("Cameras are detected automatically; uses the same AI engine as video mode")

    if "detected_cameras" not in st.session_state:
        st.session_state["detected_cameras"] = CameraManager.list_cameras(max_index=4)

    cameras = st.session_state["detected_cameras"]

    top_c1, top_c2, top_c3, top_c4 = st.columns([2.4, 1, 1, 0.9])
    if not cameras:
        st.warning(
            "No camera was detected on this device. Connect a laptop or USB webcam "
            "(or deploy with browser camera access) and click **Refresh Cameras**."
        )
        if top_c4.button("Refresh Cameras", use_container_width=True):
            st.session_state["detected_cameras"] = CameraManager.list_cameras(max_index=4)
            st.rerun()
        return

    cam_labels = [c.label for c in cameras]
    selected_idx = top_c1.selectbox(
        "Camera",
        options=range(len(cameras)),
        format_func=lambda i: cam_labels[i],
        label_visibility="collapsed",
    )
    selected_cam = cameras[selected_idx]

    start_clicked = top_c2.button(
        "Start Monitoring",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.get("live_monitoring_active", False),
    )
    stop_clicked = top_c3.button(
        "Stop Monitoring",
        use_container_width=True,
        disabled=not st.session_state.get("live_monitoring_active", False),
    )
    if top_c4.button("Refresh", use_container_width=True):
        st.session_state["detected_cameras"] = CameraManager.list_cameras(max_index=4)
        st.rerun()

    if stop_clicked:
        st.session_state["live_monitoring_active"] = False
        st.info("Stopping live monitoring and saving session...")
        st.rerun()

    if start_clicked:
        st.session_state["live_monitoring_active"] = True

    if not st.session_state.get("live_monitoring_active", False):
        _render_camera_preview(selected_cam, len(cameras))
        return

    _run_live_monitoring(config, db, selected_cam.index)


def _render_camera_preview(selected_cam, total_cameras: int) -> None:
    """Show a non-recording snapshot preview and detected device details."""
    st.markdown("#### Camera preview")
    prev_col, info_col = st.columns([2, 1])

    cam = WebcamSource(
        camera_index=selected_cam.index,
        width=selected_cam.width,
        height=selected_cam.height,
    )
    try:
        cam.open()
        time.sleep(0.15)
        ret, frame, _ = cam.read()
        if ret and frame is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            prev_col.image(
                rgb,
                caption="PREVIEW — not recording",
                use_container_width=True,
            )
        else:
            prev_col.info("Camera opened, waiting for preview frame...")
    except ExamMonitorError as exc:
        prev_col.error(str(exc))
    finally:
        cam.release()

    info_col.markdown(
        f"""
        <div class="kpi-card">
            <div class="option-title" style="margin-bottom:10px;">Detected devices</div>
            <p style="margin:4px 0;">Cameras found: <b>{total_cameras}</b></p>
            <p style="margin:4px 0;">Selected index: <b>{selected_cam.index}</b></p>
            <p style="margin:4px 0;">Resolution: <b>{selected_cam.width} × {selected_cam.height}</b></p>
            <p style="margin:4px 0;">Status: <span class="risk-low">Ready</span></p>
            <p class="disclaimer-note">
                Click <b>Start Monitoring</b> to begin real-time AI detection.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _run_live_monitoring(
    config: AppConfig, db: DatabaseManager, camera_index: int
) -> None:
    """Stream live webcam frames through the shared DetectionEngine."""
    feed_col, alert_col = st.columns([2.2, 1])
    feed_placeholder = feed_col.empty()
    alert_col.markdown("#### Live alerts")
    alerts_placeholder = alert_col.empty()
    stats_placeholder = st.empty()

    user_email = st.session_state.get("auth_user", {}).get("email", "")

    try:
        engine = DetectionEngine(config=config)
        source = WebcamSource(camera_index=camera_index)
        evidence_saver = EvidenceSaver(
            config.evidence_dir,
            cooldown_sec=config.thresholds.alert_cooldown_sec,
        )
        session = MonitoringSession(
            mode="live",
            source=source,
            engine=engine,
            db=db,
            evidence_saver=evidence_saver,
            frame_skip=config.frame_skip,
            user_email=user_email,
        )
        session.start()
    except ExamMonitorError as exc:
        st.session_state["live_monitoring_active"] = False
        st.error(f"Unable to start live monitoring: {exc}")
        return

    recent_alerts = []
    evidence_count = 0
    last_ui_time = time.monotonic()

    try:
        while st.session_state.get("live_monitoring_active", False):
            has_more, result = session.step()
            if not has_more:
                break
            if result is None:
                time.sleep(0.01)
                continue

            now = time.monotonic()
            fps = 1.0 / max(0.01, now - last_ui_time)
            last_ui_time = now

            rgb = cv2.cvtColor(result.annotated_frame, cv2.COLOR_BGR2RGB)
            feed_placeholder.image(
                rgb,
                caption=f"LIVE {format_duration(result.timestamp_sec)} • {fps:.1f} FPS",
                use_container_width=True,
            )

            for evt in result.new_events:
                if evt.screenshot_path:
                    evidence_count += 1
                recent_alerts.insert(0, evt)
            recent_alerts = recent_alerts[:8]

            if recent_alerts:
                cards_html = ""
                for evt in recent_alerts:
                    cls = (
                        "alert-item alert-item-high"
                        if evt.risk_level == "High"
                        else "alert-item"
                    )
                    cards_html += (
                        f'<div class="{cls}">'
                        f'<div class="alert-title">{evt.category}</div>'
                        f'<div class="alert-meta">Person {evt.track_id} • '
                        f'{format_duration(evt.timestamp_sec)} • {evt.risk_level} ({evt.risk_score})</div>'
                        f"</div>"
                    )
                alerts_placeholder.markdown(cards_html, unsafe_allow_html=True)
            else:
                alerts_placeholder.info("Monitoring active — no suspicious alerts yet.")

            stats = session.stats
            if stats is not None:
                stats_placeholder.markdown(
                    f"""
                    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:8px;">
                        <div class="kpi-card"><div class="kpi-label">People in view</div><div class="kpi-value">{len(result.persons)}</div></div>
                        <div class="kpi-card"><div class="kpi-label">Alerts so far</div><div class="kpi-value kpi-value-alert">{stats.total_events}</div></div>
                        <div class="kpi-card"><div class="kpi-label">Highest risk</div><div class="kpi-value">{stats.max_risk}</div></div>
                        <div class="kpi-card"><div class="kpi-label">Evidence saved</div><div class="kpi-value">{evidence_count}</div></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    finally:
        session.stop()
        engine.close()
        st.session_state["live_monitoring_active"] = False
