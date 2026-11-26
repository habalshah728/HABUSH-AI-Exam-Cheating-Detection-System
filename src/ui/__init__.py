"""Streamlit UI pages package."""

from src.ui.auth_page import render_auth_page
from src.ui.dashboard import render_dashboard
from src.ui.live import render_live_page
from src.ui.reports import render_reports_page
from src.ui.styles import apply_custom_styles
from src.ui.upload import render_upload_page

__all__ = [
    "apply_custom_styles",
    "render_auth_page",
    "render_dashboard",
    "render_live_page",
    "render_reports_page",
    "render_upload_page",
]
