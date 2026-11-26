"""Reports page showing session summary, category chart, evidence gallery, and PDF download."""

from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from src.reporting.report_generator import ReportGenerator
from src.storage.database import DatabaseManager
from src.ui.styles import format_duration


def render_reports_page(db: DatabaseManager, report_gen: ReportGenerator) -> None:
    """Render the Reports & PDF Export page."""
    st.title("Reports")
    st.caption("Session summary, evidence screenshots, and downloadable PDF report")

    sessions = db.get_sessions()
    if not sessions:
        st.info("No monitoring sessions recorded yet. Run a video or live session first.")
        return

    session_options = {
        s["id"]: f"Exam_Session_{s['id']:02d} — {s['source_name']} ({s['mode']})"
        for s in sessions
    }
    selected_id = st.selectbox(
        "Select Monitoring Session",
        options=list(session_options.keys()),
        format_func=lambda sid: session_options[sid],
    )

    session = db.get_session(selected_id)
    if session is None:
        return
    events = db.get_session_events(selected_id)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Session", f"Exam_Session_{selected_id:02d}")
    c2.metric("Mode", str(session.get("mode", "")).capitalize())
    c3.metric("Duration", format_duration(float(session.get("duration_sec") or 0.0)))
    c4.metric("Total events", len(events))
    c5.metric("Max risk", str(session.get("max_risk", "Low")))

    st.markdown("---")
    left_col, right_col = st.columns([1.1, 1.4])

    with left_col:
        st.markdown("#### Events by category")
        counts = Counter(e.get("category", "Other") for e in events)
        if counts:
            cat_df = pd.DataFrame(
                [{"Category": k, "Count": v} for k, v in counts.most_common()]
            ).set_index("Category")
            st.bar_chart(cat_df, use_container_width=True)
        else:
            st.info("No events recorded in this session.")

    with right_col:
        st.markdown("#### Evidence screenshots")
        shots = [
            e for e in events if e.get("screenshot_path") and Path(e["screenshot_path"]).exists()
        ][:6]
        if shots:
            img_cols = st.columns(3)
            for idx, evt in enumerate(shots):
                with img_cols[idx % 3]:
                    st.image(
                        evt["screenshot_path"],
                        caption=f"{format_duration(float(evt['timestamp_sec']))} • {evt['category']}",
                        use_container_width=True,
                    )
        else:
            st.info("No evidence screenshots saved for this session.")

    st.markdown("#### Event details")
    if events:
        table_df = pd.DataFrame(
            [
                {
                    "Time": format_duration(float(e["timestamp_sec"])),
                    "Indicator": e["category"],
                    "Student": f"Person {e['track_id']}",
                    "Score": int(e["risk_score"]),
                    "Level": e["risk_level"],
                }
                for e in events
            ]
        )
        st.dataframe(table_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    btn_col, note_col = st.columns([1, 2.5])
    with btn_col:
        if st.button("Build PDF Report", type="primary", use_container_width=True):
            pdf_path = report_gen.generate(selected_id)
            st.session_state[f"pdf_ready_{selected_id}"] = str(pdf_path)

    ready_path = st.session_state.get(f"pdf_ready_{selected_id}")
    if ready_path and Path(ready_path).exists():
        with btn_col:
            st.download_button(
                label="Download PDF Report",
                data=Path(ready_path).read_bytes(),
                file_name=Path(ready_path).name,
                mime="application/pdf",
                use_container_width=True,
            )

    with note_col:
        st.markdown(
            '<p class="disclaimer-note">'
            "All entries are suspicious indicators — human verification required."
            "</p>",
            unsafe_allow_html=True,
        )
