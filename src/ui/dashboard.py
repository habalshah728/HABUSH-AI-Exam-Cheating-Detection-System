"""Main Dashboard page showing summary KPIs, mode cards, and recent alerts."""

import pandas as pd
import streamlit as st

from src.storage.database import DatabaseManager
from src.ui.styles import format_duration


def render_dashboard(db: DatabaseManager) -> None:
    """Render the Main Dashboard page."""
    st.title("Main Dashboard")
    st.caption("Overview of all monitoring activity")

    stats = db.get_dashboard_stats()
    kpis = [
        ("Videos analysed", stats["videos_analysed"], False),
        ("Monitoring sessions", stats["monitoring_sessions"], False),
        ("People detected", stats["people_detected"], False),
        ("Suspicious activities", stats["suspicious_activities"], True),
        ("Phone detections", stats["phone_detections"], True),
    ]

    cols = st.columns(5)
    for col, (label, value, is_alert) in zip(cols, kpis):
        val_cls = "kpi-value kpi-value-alert" if is_alert else "kpi-value"
        with col:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-label">{label}</div>
                    <div class="{val_cls}">{value}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("### Choose a monitoring option")
    opt_a, opt_b = st.columns(2)
    with opt_a:
        st.markdown(
            """
            <div class="option-card">
                <div class="option-title">A. Upload Examination Video</div>
                <div class="option-sub">MP4 or AVI — analysed offline with timestamps and evidence</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Upload Video", type="primary", use_container_width=True):
            st.session_state["nav_page"] = "Upload Video"
            st.rerun()

    with opt_b:
        st.markdown(
            """
            <div class="option-card">
                <div class="option-title">B. Start Live Webcam Monitoring</div>
                <div class="option-sub">Laptop or USB camera — real-time alerts and risk scoring</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Start Monitoring", type="primary", use_container_width=True):
            st.session_state["nav_page"] = "Live Monitoring"
            st.rerun()

    st.markdown("### Recent alerts")
    recent = db.get_recent_events(limit=15)
    if not recent:
        st.info(
            "No suspicious alerts recorded yet. Upload an exam video or start live "
            "webcam monitoring to begin."
        )
        return

    rows = [
        {
            "Time": format_duration(float(r.get("timestamp_sec") or 0.0)),
            "Source": r.get("source_name", ""),
            "Indicator": r.get("category", ""),
            "Student ID": f"Person {r.get('track_id', '')}",
            "Risk": r.get("risk_level", "Low"),
        }
        for r in recent
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
