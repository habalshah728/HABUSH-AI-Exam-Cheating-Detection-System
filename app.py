"""Streamlit entry point for the AI-Based Smart Exam Cheating Detection System."""

import streamlit as st

from src.auth.auth_manager import AuthManager
from src.reporting.report_generator import ReportGenerator
from src.storage.database import DatabaseManager
from src.ui import (
    apply_custom_styles,
    render_auth_page,
    render_dashboard,
    render_live_page,
    render_reports_page,
    render_upload_page,
)
from src.utils.config import AppConfig


def main() -> None:
    """Initialize configuration, enforce verified login, and route sidebar pages."""
    st.set_page_config(
        page_title="Smart Exam Cheating Detection System",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_custom_styles()

    config = AppConfig()
    config.ensure_directories()
    db = DatabaseManager(config.db_path)
    auth_manager = AuthManager(db)
    report_gen = ReportGenerator(db, config.reports_dir)

    user = st.session_state.get("auth_user")
    if user is None:
        render_auth_page(auth_manager)
        return

    pages = ["Dashboard", "Upload Video", "Live Monitoring", "Reports"]
    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = "Dashboard"

    with st.sidebar:
        st.markdown("## EXAM MONITOR")
        st.caption("AI suspicious-activity assistant")
        st.markdown("---")

        selected_page = st.radio(
            "Navigation",
            options=pages,
            index=pages.index(st.session_state["nav_page"]),
            label_visibility="collapsed",
        )
        if selected_page != st.session_state["nav_page"]:
            st.session_state["nav_page"] = selected_page
            st.rerun()

        st.markdown("---")
        st.caption(f"Signed in as **{user.get('full_name', '')}**")
        st.caption(user.get("email", ""))
        if st.button("Sign Out", use_container_width=True):
            st.session_state.pop("auth_user", None)
            st.session_state["live_monitoring_active"] = False
            st.rerun()

        st.markdown("---")
        st.caption("Alerts = indicators only.\nHuman verification required.")

    current = st.session_state["nav_page"]
    if current == "Dashboard":
        render_dashboard(db)
    elif current == "Upload Video":
        render_upload_page(config, db, report_gen)
    elif current == "Live Monitoring":
        render_live_page(config, db)
    elif current == "Reports":
        render_reports_page(db, report_gen)


if __name__ == "__main__":
    main()
